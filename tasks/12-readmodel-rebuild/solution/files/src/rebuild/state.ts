/**
 * Rebuild bookkeeping.
 *
 * All of it is derived: the log and the projections are the truth, and every
 * value here can be recomputed from them. That is deliberate — the process is
 * expected to be killed at any point, and a restart must be able to work out
 * where it is without trusting anything it wrote on the way down.
 *
 * Being derivable is not the same as being cheap to derive, and it is not the
 * same as being available. Redis is where these values are read from, because
 * they are read on the append path and on every phase transition. Redis also
 * holds nothing durable, which is a property of a cache and not a complaint
 * about one — so each of them is written to the store as well and read back
 * from there when the cache has nothing to say.
 *
 * The two are written in that order for the values that matter: the store
 * first, the cache second. The cache is allowed to be behind the store. It is
 * not allowed to be ahead of it, because a value only the cache has is a value
 * one restart away from never having existed.
 */

import { redis } from '../redis/client.js';
import type { RebuildPhase } from '../domain/types.js';
import { PHASE_ORDER } from '../domain/types.js';
import { putDurable, getDurable } from './durable.js';

const PHASE_KEY = 'rebuild:phase';
const CURSOR_KEY = 'rebuild:cursor';
const SWITCH_SEQ_KEY = 'rebuild:switch_seq';
const BOUNDARY_KEY = 'rebuild:boundary';

/**
 * The cache's answer, or the store's if the cache has none, in which case the
 * cache is filled in on the way past.
 */
async function cached(key: 'rebuild:phase' | 'rebuild:cursor' | 'rebuild:switch_seq' | 'rebuild:boundary'): Promise<string | null> {
  const hit = await redis.get(key);
  if (hit !== null) return hit;
  const stored = await getDurable(key);
  if (stored === null) return null;
  await redis.set(key, stored);
  return stored;
}

async function write(
  key: 'rebuild:phase' | 'rebuild:cursor' | 'rebuild:switch_seq' | 'rebuild:boundary',
  value: string,
): Promise<void> {
  await putDurable(key, value);
  await redis.set(key, value);
}

export async function getPhase(): Promise<RebuildPhase> {
  const raw = await cached(PHASE_KEY);
  return (PHASE_ORDER as string[]).includes(raw ?? '') ? (raw as RebuildPhase) : 'LIVE_V1';
}

export async function setPhase(phase: RebuildPhase): Promise<void> {
  await write(PHASE_KEY, phase);
}

/**
 * The position the log had reached when this rebuild started. Fixed once: the
 * snapshot covers it, and everything after it is the tail's and the drain's.
 */
export async function getBoundary(): Promise<number | null> {
  const raw = await cached(BOUNDARY_KEY);
  return raw === null ? null : Number(raw);
}

export async function fixBoundary(seq: number): Promise<number> {
  const existing = await getBoundary();
  if (existing !== null) return existing;
  await write(BOUNDARY_KEY, String(seq));
  return seq;
}

export async function getCursor(): Promise<number> {
  return Number((await cached(CURSOR_KEY)) ?? 0);
}

/** The cursor only ever moves forward; a restart must not walk it back. */
export async function advanceCursor(to: number): Promise<number> {
  const current = await getCursor();
  if (to <= current) return current;
  await write(CURSOR_KEY, String(to));
  return to;
}

export async function getSwitchSeq(): Promise<number | null> {
  const raw = await cached(SWITCH_SEQ_KEY);
  return raw === null ? null : Number(raw);
}

export async function setSwitchSeq(seq: number): Promise<void> {
  await write(SWITCH_SEQ_KEY, String(seq));
}

/** True once the rebuild is maintaining v2, so the live path must fan out to it. */
export async function v2IsBeingMaintained(): Promise<boolean> {
  const phase = await getPhase();
  return phase !== 'LIVE_V1';
}

export async function nextPhase(phase: RebuildPhase): Promise<RebuildPhase> {
  const at = PHASE_ORDER.indexOf(phase);
  return PHASE_ORDER[Math.min(at + 1, PHASE_ORDER.length - 1)];
}
