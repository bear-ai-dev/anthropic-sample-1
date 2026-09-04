/**
 * The cutover.
 *
 * The three routing keys describe one decision, so they move in one Redis
 * transaction. Setting them one at a time leaves a window — however short — in
 * which a reader gets its feed from one generation and its counts from the
 * other, and a process killed inside that window leaves routing torn with
 * nobody left to fix it.
 *
 * Everything here is idempotent, because the only way to survive being killed
 * mid-cutover is for the restart to be able to run the same code again. The
 * switch decides what to do from the routing keys themselves, not from a phase
 * marker written before the attempt.
 *
 * The decision is also recorded where it will still be there if the cache is
 * not, and it is recorded first. Writing it afterwards would mean a cutover
 * that committed and then lost the cache had moved callers onto a generation
 * that no surviving record names; writing it first means the worst case is a
 * decision taken and not yet carried out, which is what reconciling is for.
 */

import { redis, ROUTE_KEYS, allActiveGenerations } from '../redis/client.js';
import { headSeq } from './log.js';
import { setSwitchSeq, getSwitchSeq } from './state.js';
import { putDurable, getDurable } from './durable.js';

export type SwitchOutcome = 'switched' | 'already-switched' | 'repaired';

export interface SwitchResult {
  outcome: SwitchOutcome;
  switchSeq: number;
}

function tally(aliases: Record<string, string>): { v1: number; v2: number } {
  const values = ROUTE_KEYS.map((k) => aliases[k]);
  return {
    v1: values.filter((v) => v !== 'v2').length,
    v2: values.filter((v) => v === 'v2').length,
  };
}

/** Moves every routing key to v2 in one atomic step, and says so first. */
async function commit(): Promise<void> {
  await putDurable('routing:generation', 'v2');
  const multi = redis.multi();
  for (const key of ROUTE_KEYS) multi.set(key, 'v2');
  const replies = await multi.exec();
  if (replies === null) throw new Error('routing transaction was discarded');
  for (const [err] of replies) if (err) throw err;
}

/**
 * Closes the window: the highest position in the log now that routing has
 * moved. Read after the commit, so a position that slipped in while the cutover
 * was in flight falls inside the drain window rather than through it.
 */
async function recordWindow(): Promise<number> {
  const head = await headSeq();
  const existing = await getSwitchSeq();
  const seq = existing === null ? head : Math.max(existing, head);
  await setSwitchSeq(seq);
  return seq;
}

export async function runAliasSwitch(): Promise<SwitchResult> {
  const before = tally(await allActiveGenerations());

  if (before.v2 === ROUTE_KEYS.length) {
    // A previous attempt committed and then died. Nothing to move; the window
    // may still be unrecorded.
    return { outcome: 'already-switched', switchSeq: await recordWindow() };
  }

  const torn = before.v2 > 0;
  await commit();
  return { outcome: torn ? 'repaired' : 'switched', switchSeq: await recordWindow() };
}

/**
 * Called on startup. Routing that is torn has to be resolved before anything
 * else happens, and forward is the only direction: v2 has readers by then, and
 * some of them have already been answered from it.
 *
 * Torn is one of two ways to find routing wrong. The other is to find it
 * missing, which a cache that has been restarted looks exactly like, and which
 * the keys alone cannot tell apart from a rebuild that has not started: three
 * keys saying nothing and three keys saying v1 are the same three keys. The
 * store can tell them apart, so it is asked, and whatever it says is written
 * back over all three at once.
 */
export async function reconcileRouting(): Promise<'consistent' | 'repaired' | 'restored'> {
  const aliases = await allActiveGenerations();
  const state = tally(aliases);

  if (state.v2 > 0 && state.v2 < ROUTE_KEYS.length) {
    await commit();
    await recordWindow();
    return 'repaired';
  }

  const missing = await redis.mget(...ROUTE_KEYS);
  if (missing.every((v) => v === null)) {
    const stated = await getDurable('routing:generation');
    const multi = redis.multi();
    for (const key of ROUTE_KEYS) multi.set(key, stated === 'v2' ? 'v2' : 'v1');
    await multi.exec();
    return 'restored';
  }

  return 'consistent';
}
