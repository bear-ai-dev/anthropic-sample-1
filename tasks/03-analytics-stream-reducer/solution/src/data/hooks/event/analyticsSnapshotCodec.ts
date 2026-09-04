// Reading and writing the record the browser keeps for one dashboard.
//
// Three record layouts are in circulation and all three have to be read. The
// one this release writes keeps each section beside the revision it was
// delivered at and names the window the figures cover; version 2 keeps the
// revisions and names no window; version 1 keeps the section values alone.
//
// Neither difference is cosmetic, and they are independent of each other.
//
// The revision decides where a restored dashboard can resume the stream from,
// because a value with no revision beside it is a value the backend cannot be
// asked to continue after. So version 1 restores every figure it holds and no
// resume point at all, and that is the correct outcome rather than a
// shortcoming: asking the backend to skip ahead to a revision we cannot name
// would lose whatever it considers older news.
//
// The window decides whether the figures are about this dashboard at all. A
// record written while the host was looking at the last day holds day-long
// aggregates; standing them up under a dashboard showing the whole event would
// put numbers on screen that answer a question nobody asked, and the stream
// would then have to be resumed from a revision counted in a different read.
// A record that names no window was written when there was only one, so it is
// the whole event's and nothing else's.
//
// What a record does *not* hold is just as deliberate. A refusal is one
// attempt's answer and the end of a stream is one read's conclusion; neither is
// a fact about the figures, so neither is kept. A restored dashboard therefore
// starts a new read with every section it does not hold a value for waiting
// again, which is what a host who reloads the page is asking for.

import { AnalyticsRange, DEFAULT_ANALYTICS_RANGE } from "@data/types/analyticsRange.types";
import {
    ANALYTICS_SNAPSHOT_VERSION,
    readStoredSnapshotHeader,
    StoredSnapshotHeader,
} from "@data/types/analyticsSnapshot.types";
import {
    AnalyticsDataSection,
    AnalyticsStreamState,
    ANALYTICS_DATA_SECTIONS,
    isValidSection,
} from "@data/types/analyticsStream.types";

/** One section as it comes back out of storage. */
export interface RestoredSection {
    section: AnalyticsDataSection;
    data: unknown;
    /** The revision the value was delivered at, or null when unknown. */
    revision: number | null;
}

function isDataSection(name: string): name is AnalyticsDataSection {
    return isValidSection(name) && name !== "__complete__";
}

function usableRevision(value: unknown): number | null {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function usablePayload(value: unknown): boolean {
    return value !== undefined && value !== null;
}

/**
 * Decode the current layout: a `sections` map of section name to the value and
 * the revision it arrived at.
 */
function decodeCurrent(record: Record<string, unknown>): RestoredSection[] {
    const sections = record.sections;
    if (sections === null || typeof sections !== "object" || Array.isArray(sections)) return [];

    const restored: RestoredSection[] = [];
    for (const [name, entry] of Object.entries(sections as Record<string, unknown>)) {
        if (!isDataSection(name)) continue;
        if (entry === null || typeof entry !== "object" || Array.isArray(entry)) continue;
        const cell = entry as Record<string, unknown>;
        if (!usablePayload(cell.data)) continue;
        restored.push({ section: name, data: cell.data, revision: usableRevision(cell.revision) });
    }
    return restored;
}

/**
 * Decode the previous layout: a flat `data` map of section name to value, with
 * nowhere for a revision to live.
 */
function decodePrevious(record: Record<string, unknown>): RestoredSection[] {
    const data = record.data;
    if (data === null || typeof data !== "object" || Array.isArray(data)) return [];

    const restored: RestoredSection[] = [];
    for (const [name, value] of Object.entries(data as Record<string, unknown>)) {
        if (!isDataSection(name)) continue;
        if (!usablePayload(value)) continue;
        restored.push({ section: name, data: value, revision: null });
    }
    return restored;
}

/**
 * The window a record's figures were aggregated over: the one it names, or the
 * whole event when it comes from a layout that had nowhere to name one.
 */
function windowOf(record: Record<string, unknown>, version: number): AnalyticsRange | null {
    if (version < 3) return DEFAULT_ANALYTICS_RANGE;
    const named = record.range;
    return typeof named === "string" ? (named as AnalyticsRange) : null;
}

/**
 * Decode one stored value for one dashboard: one event, over one window.
 *
 * Returns null when there is nothing here we can use: text that is not a record,
 * a record belonging to a different event, a record whose figures cover a
 * different window, or a record written by a release newer than this one. The
 * last of those is not paranoia — a browser that has run a newer build and then
 * been rolled back has such a record, and guessing at a layout we have never
 * seen would put invented figures in front of a host.
 */
export function decodeAnalyticsSnapshot(
    raw: string | null | undefined,
    eventId: string,
    range: AnalyticsRange
): RestoredSection[] | null {
    const header: StoredSnapshotHeader | null = readStoredSnapshotHeader(raw);
    if (!header) return null;
    if (header.eventId !== eventId) return null;
    if (header.version > ANALYTICS_SNAPSHOT_VERSION) return null;

    let record: Record<string, unknown>;
    try {
        record = JSON.parse(raw as string) as Record<string, unknown>;
    } catch {
        return null;
    }

    if (windowOf(record, header.version) !== range) return null;

    const restored = header.version >= 2 ? decodeCurrent(record) : decodePrevious(record);
    return restored.length > 0 ? restored : null;
}

/**
 * Serialise what is on screen. Only sections holding a value are written: a
 * section still waiting, or one this read was told it would not get, has nothing
 * worth keeping and would come back as an answer next time.
 */
export function encodeAnalyticsSnapshot(
    eventId: string,
    range: AnalyticsRange,
    state: AnalyticsStreamState,
    now: number
): string {
    const sections: Record<string, { revision: number | null; data: unknown }> = {};

    for (const section of ANALYTICS_DATA_SECTIONS) {
        if (!state.receivedSections.has(section)) continue;
        const value = state[section];
        if (!usablePayload(value)) continue;
        sections[section] = {
            revision: usableRevision(state.revisions[section]),
            data: value,
        };
    }

    return JSON.stringify({
        version: ANALYTICS_SNAPSHOT_VERSION,
        eventId,
        range,
        savedAt: Math.floor(now / 1000),
        sections,
    });
}

/** Whether a state holds anything a stored record could usefully carry. */
export function worthKeeping(state: AnalyticsStreamState): boolean {
    for (const section of ANALYTICS_DATA_SECTIONS) {
        if (state.receivedSections.has(section) && usablePayload(state[section])) return true;
    }
    return false;
}
