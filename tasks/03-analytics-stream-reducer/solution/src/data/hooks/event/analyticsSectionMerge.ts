// Merge helpers for the analytics stream reducer.
//
// The endpoint may deliver a section more than once: the backend recomputes a
// section and pushes it again, and a reconnect replays whatever it has already
// produced. Two properties have to hold at once:
//
//   * a redelivery carrying the value we already show must be a no-op, so that
//     nothing downstream re-renders or re-counts;
//   * a redelivery carrying a *different* value must replace what we show,
//     because the newer figure is the truer one.
//
// Recognising "the value we already show" therefore has to compare values, not
// section names. Payloads arrive as parsed JSON, so a structural walk is enough
// and is cheaper than serialising both sides.

/** True when two decoded JSON values are indistinguishable. */
export function sameStreamPayload(left: unknown, right: unknown): boolean {
    if (left === right) return true;

    // NaN never arrives from JSON.parse, but a hand-built payload can carry it.
    if (typeof left === "number" && typeof right === "number") {
        return Number.isNaN(left) && Number.isNaN(right);
    }

    if (left === null || right === null) return false;
    if (typeof left !== "object" || typeof right !== "object") return false;

    const leftIsArray = Array.isArray(left);
    if (leftIsArray !== Array.isArray(right)) return false;

    if (leftIsArray) {
        const a = left as unknown[];
        const b = right as unknown[];
        if (a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++) {
            if (!sameStreamPayload(a[i], b[i])) return false;
        }
        return true;
    }

    const a = left as Record<string, unknown>;
    const b = right as Record<string, unknown>;
    const aKeys = Object.keys(a);
    const bKeys = Object.keys(b);
    if (aKeys.length !== bKeys.length) return false;
    for (const key of aKeys) {
        if (!Object.prototype.hasOwnProperty.call(b, key)) return false;
        if (!sameStreamPayload(a[key], b[key])) return false;
    }
    return true;
}

export interface DecodedFrame {
    section: string;
    data?: unknown;
    error?: string;
    revision?: number;
}

/**
 * Decode one SSE `data` field. Returns null for anything that is not a frame we
 * can act on: unparseable text, a JSON scalar, an array, or an object with no
 * section discriminator. A bad frame must never take the connection down with
 * it, so the caller only has to check for null.
 */
export function decodeStreamFrame(raw: string): DecodedFrame | null {
    if (typeof raw !== "string" || raw.length === 0) return null;

    let parsed: unknown;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return null;
    }

    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;

    const candidate = parsed as Record<string, unknown>;
    if (typeof candidate.section !== "string" || candidate.section.length === 0) return null;

    const frame: DecodedFrame = { section: candidate.section };
    if (candidate.data !== undefined) frame.data = candidate.data;
    if (typeof candidate.error === "string" && candidate.error.length > 0) frame.error = candidate.error;
    // A revision that is not a finite number tells us nothing about ordering, so
    // it is dropped rather than guessed at: the frame is then treated as
    // unversioned and always current.
    if (typeof candidate.revision === "number" && Number.isFinite(candidate.revision)) {
        frame.revision = candidate.revision;
    }
    return frame;
}
