import { compareInstants } from './instant';

/**
 * Arrival order for a list of deliveries.
 *
 * `src/intake/instant.ts` compares two `received_at` values and stops there: it
 * returns 0 for two values that denote the same instant, whatever width each was
 * stamped to, and says nothing about what to do with that tie. Every read here
 * needs a total order, because a listing has to come out the same way twice, so
 * the tie is broken on `transport_id` -- unique per delivery, and the only column
 * on the row that is.
 *
 * This is separate from the comparison itself because the two facts are separate.
 * That the fraction is part of the instant is a property of the field. That a
 * listing of deliveries is ordered by arrival, and that equal instants resolve by
 * transport identity rather than by insertion, is a property of the read.
 */
export function byArrival<T extends { received_at: string; transport_id: string }>(
  left: T,
  right: T,
): number {
  const instant = compareInstants(left.received_at, right.received_at);
  if (instant !== 0) return instant;
  if (left.transport_id === right.transport_id) return 0;
  return left.transport_id < right.transport_id ? -1 : 1;
}
