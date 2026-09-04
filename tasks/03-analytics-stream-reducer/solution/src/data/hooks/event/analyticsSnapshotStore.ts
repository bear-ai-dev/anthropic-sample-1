// The storage side of the kept dashboard.
//
// Every call here is wrapped, because `localStorage` is the one browser API a
// dashboard cannot afford to trust: it throws on read in a private window, it
// throws on write when the origin is over quota, and a write that fails part way
// through leaves the key holding half a record. None of those are reasons for a
// host to see a blank page, so the failure of anything in this file degrades to
// "there is no kept picture" and the stream carries the dashboard on its own.

import { AnalyticsRange } from "@data/types/analyticsRange.types";
import { AnalyticsStreamState } from "@data/types/analyticsStream.types";
import { snapshotStorageKey } from "@data/types/analyticsSnapshot.types";
import { printDebug } from "../../../util/misc";
import { decodeAnalyticsSnapshot, encodeAnalyticsSnapshot, RestoredSection, worthKeeping } from "./analyticsSnapshotCodec";

function store(): Storage | null {
    try {
        return typeof window === "undefined" ? null : window.localStorage;
    } catch {
        return null;
    }
}

/**
 * What the browser kept for this dashboard, or null when there is nothing
 * usable. A dashboard is an event and a window, and the record has to be both
 * before its figures mean anything here.
 */
export function readAnalyticsSnapshot(eventId: string, range: AnalyticsRange): RestoredSection[] | null {
    const storage = store();
    if (!storage) return null;

    let raw: string | null = null;
    try {
        raw = storage.getItem(snapshotStorageKey(eventId));
    } catch {
        return null;
    }
    if (raw === null) return null;

    const restored = decodeAnalyticsSnapshot(raw, eventId, range);
    if (!restored) {
        // Unreadable, someone else's, another window's, or from a build we do
        // not know. Leave it where it is: this build cannot say whether a newer
        // one still wants it, and a record for another window is still the
        // right record for the dashboard that wrote it.
        printDebug(`Analytics snapshot: nothing usable kept for ${eventId} over ${range}`);
        return null;
    }
    return restored;
}

/** Keep what is on screen, stamped with the window it was computed over. */
export function writeAnalyticsSnapshot(
    eventId: string,
    range: AnalyticsRange,
    state: AnalyticsStreamState
): void {
    const storage = store();
    if (!storage) return;

    if (!worthKeeping(state)) {
        // A record holding no figures is worse than no record: next time in it
        // would restore an empty dashboard and claim to have been updated.
        clearAnalyticsSnapshot(eventId);
        return;
    }

    try {
        storage.setItem(snapshotStorageKey(eventId), encodeAnalyticsSnapshot(eventId, range, state, Date.now()));
    } catch {
        // Over quota, most likely. A dashboard that cannot be kept is still a
        // dashboard; drop whatever half-written value is there and move on.
        clearAnalyticsSnapshot(eventId);
    }
}

/**
 * Forget what was kept for this event. This is what a restart means: everything
 * on screen has just been thrown away, and a record left behind would put it
 * back the next time the page loads, along with a resume point for figures the
 * host explicitly asked to have recomputed.
 */
export function clearAnalyticsSnapshot(eventId: string): void {
    const storage = store();
    if (!storage) return;
    try {
        storage.removeItem(snapshotStorageKey(eventId));
    } catch {
        // Nothing further to try.
    }
}
