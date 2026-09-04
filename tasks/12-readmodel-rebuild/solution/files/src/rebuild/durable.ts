/**
 * The rebuild's bookkeeping, in the store rather than in the cache.
 *
 * Redis holds the routing keys and the rebuild's working state, and it says of
 * itself that nothing durable lives there. That is true of a cache and it is
 * still true on the day the cache comes back empty: the process survives, the
 * log survives, both generations of projection survive, and the only thing lost
 * is the note saying which of them callers are supposed to be reading.
 *
 * So the note is kept twice. Redis is the copy everything reads, because every
 * read on the service goes through it and it is the only one fast enough to be
 * in that path. `RebuildMeta` is the copy that is true. When the two disagree,
 * or when Redis has nothing to say at all, the store wins and the cache is
 * written back from it.
 *
 * Order matters at the one moment the two can disagree honestly. The durable
 * record of a routing move is written *before* the cache is moved, never after:
 * a crash in between then leaves a stated intention that the next reconcile
 * carries out, whereas the other order leaves callers pointed at a generation
 * no record admits to and nothing to repair it from.
 */

import { gel } from '../gel/client.js';
import { redis, ROUTE_KEYS } from '../redis/client.js';
import type { Generation } from '../redis/client.js';

/** What the store keeps, and the cache mirrors. */
export const DURABLE_KEYS = [
  'rebuild:phase',
  'rebuild:boundary',
  'rebuild:cursor',
  'rebuild:switch_seq',
  'routing:generation',
] as const;

export type DurableKey = (typeof DURABLE_KEYS)[number];

export async function putDurable(key: DurableKey, value: string): Promise<void> {
  await gel.execute(
    `insert RebuildMeta { key := <str>$key, value := <str>$value }
     unless conflict on (.key)
     else (update RebuildMeta set { value := <str>$value })`,
    { key, value },
  );
}

export async function getDurable(key: DurableKey): Promise<string | null> {
  const row = await gel.querySingle<{ value: string } | null>(
    'select RebuildMeta { value } filter .key = <str>$key limit 1',
    { key },
  );
  return row ? row.value : null;
}

async function allDurable(): Promise<Map<string, string>> {
  const rows = await gel.query<{ key: string; value: string }>(
    'select RebuildMeta { key, value }',
  );
  return new Map(rows.map((r) => [r.key, r.value]));
}

/**
 * Writes the cache back from the store, and answers which generation is
 * serving.
 *
 * The three routing keys go in one transaction for the same reason the cutover
 * does: a caller must never be able to see them disagreeing, and a repair is
 * just as capable of showing them a torn answer as the original move was.
 *
 * Called when the cache has no opinion, which is either a cache that has been
 * restarted or a rebuild that has not started yet. Both want the same answer,
 * and if there is no durable record either then the answer is the generation
 * that was serving before any of this began.
 */
export async function reconcileFromStore(): Promise<Generation> {
  const durable = await allDurable();
  const serving: Generation = durable.get('routing:generation') === 'v2' ? 'v2' : 'v1';

  const tx = redis.multi();
  for (const key of ROUTE_KEYS) tx.set(key, serving);
  for (const key of DURABLE_KEYS) {
    if (key === 'routing:generation') continue;
    const value = durable.get(key);
    if (value !== undefined) tx.set(key, value);
  }
  await tx.exec();

  return serving;
}

/**
 * The generation serving a routing key, taking the store's word for it when the
 * cache has none.
 *
 * The shipped helper reads the key and treats anything that is not `"v2"` as
 * v1, which is the right reading of a key that says `"v1"` and the wrong one of
 * a key that is not there. Once the old generation has been retired those are
 * very different answers: the first is a generation, the second is a cache that
 * has forgotten, and answering the second out of v1 means answering out of
 * tables that no longer exist.
 */
export async function servingGeneration(key: (typeof ROUTE_KEYS)[number]): Promise<Generation> {
  const said = await redis.get(key);
  if (said === 'v1' || said === 'v2') return said;
  return reconcileFromStore();
}
