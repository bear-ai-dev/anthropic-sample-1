import { Event } from "@data/types/event/event";
import { parseAsBoolean, useQueryState } from "nuqs";
import { useCallback, useEffect, useRef, useState } from "react";
import { getVersion, printDebug } from "../../../util/misc";
import { ENDPOINTS } from "../../endpoints";
import {
    AnalyticsRange,
    analyticsRangeWindow,
    AnalyticsWindow,
    DEFAULT_ANALYTICS_RANGE,
} from "../../types/analyticsRange.types";
import {
    ANALYTICS_DATA_SECTIONS,
    AnalyticsStreamState,
    createInitialAnalyticsStreamState,
    RawAnalyticsStreamEvent,
    updateStateForSection,
} from "../../types/analyticsStream.types";
import { applyQueriedSection, fetchSectionFromQuery, sectionsAwaitingBackfill } from "./analyticsBackfill";
import { resumePoint, withResumePoint } from "./analyticsResume";
import { decodeStreamFrame } from "./analyticsSectionMerge";
import { stateFromRestoredSections } from "./analyticsRestore";
import { clearAnalyticsSnapshot, readAnalyticsSnapshot, writeAnalyticsSnapshot } from "./analyticsSnapshotStore";
import { AnalyticsStreamSession, LostVerdict } from "./analyticsStreamSession";

const BASE_URL = import.meta.env.VITE_BASE_API_URL as string;

/**
 * Sample payloads kept for local development, taken off the wire while the
 * endpoint was being built. `tests/fixtures/analytics-stream.capture.txt` is the
 * session they came out of.
 */
export const DUMMY_ANALYTICS_DATA: RawAnalyticsStreamEvent[] = [
    {
        section: "scanStats",
        revision: 1,
        data: {
            scannedPeople: 312,
            expectedAttendees: 400,
            scanRatePercent: 78.0,
            repeatScansCount: 9,
            invalidScansCount: 4,
            expiredScansCount: 2,
        },
    },
    {
        section: "purchasesByDevice",
        revision: 2,
        data: {
            ios: { count: 240, percentage: 63, revenueCents: 612000 },
            web: { count: 141, percentage: 37, revenueCents: 359500 },
        },
    },
    {
        section: "financials",
        revision: 4,
        data: {
            net: 971500,
            payment: { pending: 0, available: 971500, linked: 1 },
            refunded: 18000,
            revenueBySource: [
                { source: "feed", sum: 612000, count: 240 },
                { source: "chat", sum: 359500, count: 141 },
            ],
        },
    },
    { section: "__complete__" },
];

/**
 * The headers the stream endpoint expects. A request without a bearer token is
 * refused, so the caller has to have one before there is anything to send.
 */
export function streamRequestHeaders(authToken: string): Record<string, string> {
    return {
        Authorization: `Bearer ${authToken}`,
        "x-platform": "web",
        "x-build": (getVersion() as string) || "0.0.0",
    };
}

export interface UseAnalyticsStreamOptions {
    /** Whether to automatically start the stream on mount */
    autoStart?: boolean;
    /** Retry count for failed connections */
    maxRetries?: number;
    /** Retry delay in milliseconds */
    retryDelay?: number;
}

export interface UseAnalyticsStreamResult extends AnalyticsStreamState {
    /** Manually start the stream */
    start: () => void;
    /** Manually stop the stream */
    stop: () => void;
    /** Reset state and restart the stream */
    restart: () => void;
}

/**
 * Hook for consuming the analytics stream SSE endpoint.
 * Provides type-safe state updates as each section arrives.
 *
 * Connections are numbered. `generationRef` holds the number of the connection
 * whose frames are allowed to reach the state, and it is bumped whenever the
 * stream is stopped, re-opened, or pointed at a different event. Everything a
 * connection does — opening, reading a frame, failing — is checked against it,
 * including inside the state updater itself, because a frame can be in flight
 * across a generation change and React will happily apply a stale closure.
 *
 * Three things feed a panel and they are not equals. The stream is the source of
 * truth. What the browser kept from the last visit stands in for the stream
 * until it has said something, and is what the first connection resumes from.
 * The analytics query is the last resort, for the three sections it can answer
 * and only once this read has finished without them.
 *
 * All three are about one dashboard, and a dashboard is an event *and* a window.
 * Both endpoints aggregate over the window they are asked for, so the window is
 * part of what every figure means: changing it is as much a different dashboard
 * as changing the event, the record kept for one window is not the other's, and
 * the query is asked over whatever is on screen.
 */
export function useAnalyticsStream(
    authToken: string | undefined,
    event: Event | undefined,
    range: AnalyticsRange = DEFAULT_ANALYTICS_RANGE,
    options: UseAnalyticsStreamOptions = {}
): UseAnalyticsStreamResult {
    const { autoStart = true, maxRetries = 3, retryDelay = 1000 } = options;

    const [state, setState] = useState<AnalyticsStreamState>(createInitialAnalyticsStreamState);

    // Refs, not state: these are read from callbacks that outlive the render
    // that created them.
    const generationRef = useRef(0);
    const sessionRef = useRef<AnalyticsStreamSession | null>(null);
    const currentEventIdRef = useRef<string | null>(null);
    /** The window the figures on screen were computed over. */
    const currentRangeRef = useRef<AnalyticsRange | null>(null);

    /**
     * A mirror of the state for the callbacks to read. A reconnect has to know
     * which revisions are on screen *at the moment it happens*, and a callback
     * closed over a render cannot ask React for that.
     */
    const shownRef = useRef<AnalyticsStreamState>(state);
    shownRef.current = state;

    /** Consecutive failures with no successful open in between. */
    const failuresRef = useRef(0);
    const reopenTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    /** Sections already asked of the query, per event, so it is asked once. */
    const queriedRef = useRef<Set<string>>(new Set());

    // Extract stable values from event
    const eventId = event?.id;
    const eventDateCreated = event?.dateCreated;

    /** The three aggregation parameters both endpoints are asked over. */
    const streamWindow = useCallback(
        (): AnalyticsWindow => analyticsRangeWindow(range, eventDateCreated, Date.now()),
        [range, eventDateCreated]
    );

    // Build the stream URL with query parameters (using stable values)
    const buildStreamUrl = useCallback((): string | null => {
        if (!eventId) return null;
        const endpoint = ENDPOINTS.EVENT.analyticsStream.url;
        const window = streamWindow();
        const params = new URLSearchParams({
            eventId: eventId,
            startTime: String(window.startTime),
            endTime: String(window.endTime),
            buckets: String(window.buckets),
        });
        return `${BASE_URL}${endpoint}?${params.toString()}`;
    }, [eventId, streamWindow]);

    // The failure handler outlives the render that created it, so it reads the
    // token and the URL builder through refs rather than closing over them.
    const authTokenRef = useRef(authToken);
    authTokenRef.current = authToken;
    const buildStreamUrlRef = useRef(buildStreamUrl);
    buildStreamUrlRef.current = buildStreamUrl;

    /**
     * Commit one frame. The generation is checked twice on purpose: once here,
     * and once inside the updater, which is the only check that is actually
     * ordered with respect to the state it is about to modify.
     */
    const commitFrame = useCallback((raw: string, generation: number) => {
        if (generation !== generationRef.current) return;

        const frame = decodeStreamFrame(raw);
        if (!frame) {
            // A malformed frame is noise on the wire. Log it and keep reading:
            // throwing here would tear down the connection and lose the
            // sections that have not been sent yet.
            printDebug("Analytics stream: discarding unreadable frame");
            return;
        }

        setState((previous) => {
            if (generation !== generationRef.current) return previous;
            return updateStateForSection(previous, frame);
        });
    }, []);

    const handleOpen = useCallback((generation: number) => {
        if (generation !== generationRef.current) return;
        // A connection that came up is a clean slate for the failure budget: a
        // stream that drops once an hour must not exhaust it over a whole day.
        failuresRef.current = 0;
        printDebug(`Analytics stream: connection ${generation} open`);
    }, []);

    /**
     * Nothing further will be attempted. Record the failure without discarding
     * sections: a partial dashboard is worth more than an empty one, and every
     * section still in flight has to stop waiting, because waiting for
     * something that is never coming is the one state a panel must not be left
     * in. Settling them is also what puts the three sections the analytics
     * query can answer within reach of it.
     */
    const handleGiveUp = useCallback((error: Error, generation: number) => {
        if (generation !== generationRef.current) return;
        console.error("Analytics stream error:", error);
        setState((previous) => {
            if (generation !== generationRef.current) return previous;
            const settledSections = new Set(previous.settledSections);
            for (const section of ANALYTICS_DATA_SECTIONS) {
                if (!previous.receivedSections.has(section)) settledSections.add(section);
            }
            return { ...previous, loading: false, error, settledSections };
        });
    }, []);

    /** Cancel a reconnect that has been scheduled but not yet fired. */
    const cancelPendingReopen = useCallback(() => {
        if (reopenTimerRef.current === null) return;
        clearTimeout(reopenTimerRef.current);
        reopenTimerRef.current = null;
    }, []);

    /** Retire the current connection and make its generation stale. */
    const retireCurrentGeneration = useCallback(() => {
        cancelPendingReopen();
        generationRef.current += 1;
        const session = sessionRef.current;
        sessionRef.current = null;
        session?.close();
        return generationRef.current;
    }, [cancelPendingReopen]);

    // `open` and the failure handler call each other, so one of them has to be
    // reached through a ref.
    const openGenerationRef = useRef<(generation: number, url: string, token: string) => void>(() => {});

    /**
     * The connection failed. Decide whether this read continues.
     *
     * Continuing means opening a *new* connection that asks the backend to
     * resume from the newest revision on screen, so that the sections already
     * displayed are not recomputed and — more importantly — the sections that
     * are still missing get another chance. The panels are untouched: this is
     * the same logical read, and a blip in the transport is not news the user
     * needs to see.
     */
    const handleLost = useCallback(
        (error: Error, generation: number): LostVerdict => {
            if (generation !== generationRef.current) return "stop";
            printDebug(`Analytics stream: connection ${generation} dropped (${error.message})`);

            failuresRef.current += 1;
            if (failuresRef.current > maxRetries) {
                printDebug("Analytics stream: out of attempts");
                return "stop";
            }

            const attempt = failuresRef.current;
            const token = authTokenRef.current;
            const url = buildStreamUrlRef.current();
            if (!token || !url) return "stop";

            printDebug(`Analytics stream: lost connection ${generation}, resuming (attempt ${attempt})`);
            cancelPendingReopen();
            reopenTimerRef.current = setTimeout(() => {
                reopenTimerRef.current = null;
                if (generation !== generationRef.current) return;
                // Retire the failed connection and continue the same read. The
                // state is deliberately left alone.
                const next = retireCurrentGeneration();
                openGenerationRef.current(next, url, token);
            }, retryDelay * attempt);

            return "handoff";
        },
        [cancelPendingReopen, maxRetries, retryDelay, retireCurrentGeneration]
    );

    /**
     * Open a connection for a read that is already in whatever state it is in.
     *
     * There is no "resume or not" flag here, and there deliberately is not one:
     * where a connection starts is a fact about what the dashboard is showing,
     * not about why it is being opened. A read with nothing on screen asks for
     * the stream from the top; a read carrying figures — because a connection
     * dropped, or because the browser had them kept from last time — asks the
     * backend to continue after the newest revision among them. Handing the
     * decision to the caller is how a restored dashboard ends up asking for
     * everything again, and how a restarted one ends up permanently missing
     * whatever the backend considered old news.
     */
    const openGeneration = useCallback(
        (generation: number, url: string, token: string) => {
            const target = withResumePoint(url, resumePoint(shownRef.current.revisions));
            const session = new AnalyticsStreamSession(
                generation,
                target,
                streamRequestHeaders(token),
                { onFrame: commitFrame, onOpen: handleOpen, onLost: handleLost, onGiveUp: handleGiveUp },
                () => generationRef.current
            );
            sessionRef.current = session;
            printDebug(`Analytics stream: starting connection ${generation} to ${target}`);
            void session.open();
        },
        [commitFrame, handleOpen, handleLost, handleGiveUp]
    );
    openGenerationRef.current = openGeneration;

    const start = useCallback(() => {
        if (!authToken) {
            printDebug("Analytics stream: No auth token, skipping");
            return;
        }
        if (!eventId) {
            printDebug("Analytics stream: No event, waiting");
            return;
        }

        const url = buildStreamUrl();
        if (!url) {
            printDebug("Analytics stream: No URL, skipping");
            return;
        }

        // Already reading this dashboard: opening a second connection would
        // double every section and race the first one.
        const changed = currentEventIdRef.current !== eventId || currentRangeRef.current !== range;
        const existing = sessionRef.current;
        if (existing && !existing.superseded && !changed) {
            printDebug("Analytics stream: Already running for this dashboard, skipping");
            return;
        }

        currentEventIdRef.current = eventId;
        currentRangeRef.current = range;

        const generation = retireCurrentGeneration();
        failuresRef.current = 0;

        // A different dashboard — another event, or the same event over another
        // window. Nothing from the previous one may stay on screen, not even for
        // a frame, because its figures answer a different question and its
        // revisions were counted in a different read. But this one is not
        // necessarily blank either: whatever the browser kept *for it* is what
        // the host saw last time, and standing that up now is the difference
        // between a dashboard and ten skeletons. The mirror is written directly
        // because the connection below has to see it before React has
        // re-rendered.
        if (changed) {
            const restored = stateFromRestoredSections(readAnalyticsSnapshot(eventId, range));
            shownRef.current = restored;
            setState(restored);
        }

        openGeneration(generation, url, authToken);
    }, [authToken, eventId, range, buildStreamUrl, retireCurrentGeneration, openGeneration]);

    const stop = useCallback(() => {
        printDebug("Analytics stream: Stopping");
        // Bumping the generation is what makes this stick. Aborting alone leaves
        // any frame already read on its way to the state.
        retireCurrentGeneration();
    }, [retireCurrentGeneration]);

    const restart = useCallback(() => {
        printDebug("Analytics stream: Restarting");
        const fresh = createInitialAnalyticsStreamState();
        // The host has asked for the figures to be computed again, so the kept
        // copy goes with the ones on screen. Leaving it would put them back on
        // the next visit, and worse, would send a resume point derived from
        // figures this read has just disowned.
        if (eventId) {
            clearAnalyticsSnapshot(eventId);
            queriedRef.current = new Set();
        }

        if (!authToken || !eventId) {
            retireCurrentGeneration();
            shownRef.current = fresh;
            setState(fresh);
            return;
        }
        const url = buildStreamUrl();
        const generation = retireCurrentGeneration();
        failuresRef.current = 0;
        shownRef.current = fresh;
        setState(fresh);
        currentEventIdRef.current = eventId;
        currentRangeRef.current = range;
        if (!url) return;
        openGeneration(generation, url, authToken);
    }, [authToken, eventId, range, buildStreamUrl, retireCurrentGeneration, openGeneration]);

    // Load dummy data function
    const loadDummyData = useCallback(() => {
        printDebug("Analytics stream: Loading dummy data");
        const generation = retireCurrentGeneration();
        setState(createInitialAnalyticsStreamState());

        let index = 0;
        const processNextSection = () => {
            if (generation !== generationRef.current) return;
            if (index >= DUMMY_ANALYTICS_DATA.length) return;
            const frame = DUMMY_ANALYTICS_DATA[index];
            index++;
            setState((previous) => {
                if (generation !== generationRef.current) return previous;
                return updateStateForSection(previous, frame);
            });
            setTimeout(processNextSection, 50);
        };

        processNextSection();
    }, [retireCurrentGeneration]);

    const [useDummyData] = useQueryState("dummy", parseAsBoolean.withDefault(false));

    /**
     * Keep what is on screen. This runs on every change rather than on the way
     * out, because the page is as likely to be closed by the browser as by the
     * user, and a snapshot written in an unmount handler is a snapshot that is
     * missing precisely when it is needed.
     */
    useEffect(() => {
        if (useDummyData) return;
        const owner = currentEventIdRef.current;
        const window = currentRangeRef.current;
        if (!owner || !window) return;
        writeAnalyticsSnapshot(owner, window, state);
    }, [state, useDummyData]);

    /**
     * Ask the analytics query about the sections this read has finished with and
     * has nothing to show for. The set is derived from the state rather than
     * hooked to any particular event, so a refusal, a terminal frame and running
     * out of attempts all reach it by the same route.
     */
    useEffect(() => {
        if (useDummyData) return;
        const owner = currentEventIdRef.current;
        const window = currentRangeRef.current;
        const token = authTokenRef.current;
        if (!owner || !window || !token) return;

        for (const section of sectionsAwaitingBackfill(state)) {
            // Asked once per dashboard, and a dashboard is an event and a
            // window: the answer for one window is not an answer for another,
            // so the same section is worth asking about again over the next one.
            const once = `${owner}:${window}:${section}`;
            if (queriedRef.current.has(once)) continue;
            queriedRef.current.add(once);

            void fetchSectionFromQuery(token, owner, section, streamWindow()).then((data) => {
                if (data === null) return;
                // The dashboard may have changed while the request was out; the
                // answer belongs to the one that asked for it.
                if (currentEventIdRef.current !== owner || currentRangeRef.current !== window) return;
                setState((previous) => applyQueriedSection(previous, section, data));
            });
        }
    }, [state, authToken, useDummyData, streamWindow]);

    // Auto-start on mount if enabled (using stable dependencies to avoid flickering)
    useEffect(() => {
        if (autoStart) {
            if (useDummyData) {
                loadDummyData();
            } else if (authToken && eventId) {
                start();
            }
        }

        // Cleanup on unmount or when the dashboard changes
        return () => {
            retireCurrentGeneration();
        };
        // Note: start/stop are intentionally excluded to prevent re-triggering on every render.
        // The effect should only re-run when the actual data dependencies change.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [autoStart, authToken, eventId, range, useDummyData]);

    return {
        ...state,
        start,
        stop,
        restart,
    };
}
