// The fallback for a section the stream is never going to produce.
//
// The stream computes ten sections; the ordinary analytics query computes three
// of them, and which three is not a matter of taste — `AnalyticsRequest.type`
// is the whole list of things that endpoint can be asked for, and
// `EventAnalytics` is the whole list of things it answers with. A section
// outside that list has no second source, so a panel for one of those stays
// empty when the stream gives up on it, and asking the query about it would be
// a request the backend has no handler for.
//
// The trigger is the reducer's own conclusion, not a timer and not the end of
// the stream: a section is worth asking about exactly once the read has settled
// it without a value. That happens three different ways — the stream refuses the
// section outright, the stream ends without mentioning it, or re-opening runs
// out of attempts — and all three mean the same thing to a panel, so all three
// take the same fallback. A section still waiting is not one of them: the stream
// may yet produce it, and a figure from the query would be replaced seconds
// later by a fresher one, which is exactly the flicker this endpoint exists to
// avoid.
//
// A value that arrives this way carries no revision, because the query does not
// version anything. Two consequences follow and both are load-bearing: it can
// never raise the resume point of the next connection, and any later frame for
// that section replaces it, however the frame is numbered.
//
// What the two sources do have in common is the question. Both endpoints
// aggregate over the window the request names, so a figure from the query only
// stands in for the stream's if it was computed over the same one: the panel
// beside it is labelled with a window, and its neighbours are all showing that
// window's numbers.

import { AnalyticsRequest, AnalyticsResponse } from "@data/hooks/event/useEventAnalytics";
import { AnalyticsWindow } from "@data/types/analyticsRange.types";
import {
    AnalyticsDataSection,
    AnalyticsStreamState,
} from "@data/types/analyticsStream.types";
import { ENDPOINTS } from "../../endpoints";
import { sendRequest } from "../../sendRequest";
import { printDebug } from "../../../util/misc";

/**
 * The sections that have a second source. Named as the query's own `type`
 * values, because that is what they are.
 */
export const QUERY_SERVED_SECTIONS = ["charts", "revenue", "demographics"] as const;

export type QueryServedSection = (typeof QUERY_SERVED_SECTIONS)[number];

function isQueryServed(section: AnalyticsDataSection): section is QueryServedSection {
    return (QUERY_SERVED_SECTIONS as readonly string[]).includes(section);
}

/**
 * The sections this read has finished with, has no value for, and the query can
 * answer for. Everything else is either still coming, already shown, or beyond
 * the query's reach.
 */
export function sectionsAwaitingBackfill(state: AnalyticsStreamState): QueryServedSection[] {
    const awaiting: QueryServedSection[] = [];
    for (const section of QUERY_SERVED_SECTIONS) {
        if (!isQueryServed(section)) continue;
        if (state.receivedSections.has(section)) continue;
        if (!state.settledSections.has(section)) continue;
        if (state[section] !== null && state[section] !== undefined) continue;
        awaiting.push(section);
    }
    return awaiting;
}

/**
 * Ask the analytics query for one section, over the window on screen.
 *
 * Returns null whenever there is nothing to show: the event is not eligible for
 * analytics at all, the query has not computed this section, or the request
 * failed. None of those are worth reporting to the host — the panel is already
 * in the state the stream left it in, and this was the second attempt.
 */
export async function fetchSectionFromQuery(
    authToken: string,
    eventId: string,
    section: QueryServedSection,
    window: AnalyticsWindow
): Promise<unknown | null> {
    const params: AnalyticsRequest = {
        eventId,
        type: section,
        startTime: window.startTime,
        endTime: window.endTime,
        buckets: window.buckets,
    };

    try {
        const response: AnalyticsResponse | undefined = await sendRequest({
            ...ENDPOINTS.EVENT.analytics,
            params,
            authToken,
        });

        if (!response || !response.eligible) return null;
        const value = response.analytics?.[section];
        return value === undefined || value === null ? null : value;
    } catch (error) {
        printDebug(`Analytics query: ${section} unavailable`, error);
        return null;
    }
}

/**
 * Put a queried value on screen.
 *
 * Guarded rather than assumed: a request is in flight for as long as the backend
 * takes, and the stream can deliver the section in the meantime. The streamed
 * value is the better one — it is versioned and it is newer — so a queried value
 * only ever fills a hole that is still a hole. No revision is recorded, because
 * there is none to record.
 */
export function applyQueriedSection(
    state: AnalyticsStreamState,
    section: QueryServedSection,
    data: unknown
): AnalyticsStreamState {
    if (state.receivedSections.has(section)) return state;
    if (data === null || data === undefined) return state;

    const receivedSections = new Set(state.receivedSections);
    receivedSections.add(section);

    const settledSections = new Set(state.settledSections);
    settledSections.delete(section);

    const sectionErrors = { ...state.sectionErrors };
    delete sectionErrors[section];

    const revisions = { ...state.revisions };
    delete revisions[section];

    return {
        ...state,
        [section]: data,
        receivedSections,
        settledSections,
        sectionErrors,
        revisions,
    } as AnalyticsStreamState;
}
