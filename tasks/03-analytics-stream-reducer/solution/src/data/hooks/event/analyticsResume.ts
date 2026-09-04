// Where a resumed read has to start from.
//
// A dropped connection is not a reason to throw away a dashboard, and it is not
// a reason to make the backend recompute everything either. When the client
// re-opens it says how far it got, and the backend replays only what is newer.
// Two things follow from that, and both matter:
//
//   * the resume point is the newest revision the client is *showing*, not the
//     newest it has *seen*. A section that failed, or that was refused, has no
//     value to keep, so it must not be skipped by the resume — the whole point
//     of re-opening is to get another chance at it.
//   * a fresh read has no resume point at all. Restarting, or moving to another
//     event, throws away every revision along with the figures, so the request
//     must ask for the stream from the beginning. Sending a stale resume point
//     into a fresh read would leave the dashboard permanently missing whatever
//     the backend decided was old news.

/** The query parameter the endpoint reads a resume point from. */
export const RESUME_PARAM = "since";

/**
 * The newest revision any section is currently showing, or null when the client
 * holds nothing that a resume could skip.
 */
export function resumePoint(revisions: Partial<Record<string, number>>): number | null {
    let newest: number | null = null;
    for (const value of Object.values(revisions)) {
        if (typeof value !== "number" || !Number.isFinite(value)) continue;
        if (newest === null || value > newest) newest = value;
    }
    return newest;
}

/**
 * Add a resume point to a stream URL. Returns the URL unchanged when there is
 * nothing to resume from, so the same call site serves both a first read and a
 * continuation.
 */
export function withResumePoint(url: string, point: number | null): string {
    if (point === null || !Number.isFinite(point)) return url;

    const [base, query = ""] = url.split("?", 2);
    const params = new URLSearchParams(query);
    params.set(RESUME_PARAM, String(point));
    return `${base}?${params.toString()}`;
}
