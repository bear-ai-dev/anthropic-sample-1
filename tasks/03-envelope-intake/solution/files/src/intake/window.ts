/**
 * The reopen window.
 *
 * A closed ticket takes a reply back if the reply arrived within the window of
 * the moment the ticket closed. The anchor is the ticket's `closed_at` and
 * nothing else: not the ticket's `created_at`, not the arrival of the first
 * delivery on it, not the arrival of the previous one. A ticket that was closed,
 * reopened and closed again is anchored on the close it is currently sitting in,
 * which is the value `closed_at` holds.
 */
export const REOPEN_WINDOW_HOURS = 720;

const MS_PER_HOUR = 3_600_000;

export function reopenWindowMs(): number {
  return REOPEN_WINDOW_HOURS * MS_PER_HOUR;
}

/** Milliseconds between two ISO-8601 instants, or null if either will not parse. */
export function elapsedMs(from: string, to: string): number | null {
  const start = Date.parse(from);
  const end = Date.parse(to);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return end - start;
}

/**
 * Whether a delivery that arrived at `receivedAt` still falls inside the window
 * of a ticket closed at `closedAt`.
 *
 * A delivery whose arrival predates the close is inside it: the gateway held it
 * while the case was being wrapped up, and it belongs to the case it was
 * written about.
 *
 * An unparseable or absent `closed_at` is not a window. There is no anchor to
 * measure from, so nothing can be said to be inside one.
 */
export function withinReopenWindow(
  closedAt: string | null,
  receivedAt: string,
): boolean {
  if (closedAt === null || closedAt === '') return false;
  const elapsed = elapsedMs(closedAt, receivedAt);
  if (elapsed === null) return false;
  return elapsed <= reopenWindowMs();
}
