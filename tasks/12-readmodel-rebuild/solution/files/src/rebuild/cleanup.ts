/**
 * Retirement of generation v1.
 *
 * This is the irreversible step. v1 is the only other copy of anything v2 has
 * not folded, so it may not go while the drain is outstanding — and the check
 * is made here, against the store, rather than being assumed from the fact that
 * the drain stage ran.
 */

import { gel } from '../gel/client.js';
import { drainLag } from './drain.js';

export class DrainIncomplete extends Error {
  constructor(readonly lag: number) {
    super(`refusing to retire generation v1 while ${lag} position(s) in the drain window are unfolded`);
    this.name = 'DrainIncomplete';
  }
}

const V1_TYPES = ['FeedByUserV1', 'CountByOrgV1', 'RecentByTagV1'];

export async function v1RowCount(): Promise<number> {
  const counts = await Promise.all(
    V1_TYPES.map((t) => gel.querySingle<number | null>(`select count(${t})`)),
  );
  return counts.reduce<number>((a, b) => a + Number(b ?? 0), 0);
}

export async function runCleanup(): Promise<{ removed: number }> {
  const lag = await drainLag();
  if (lag === null) throw new DrainIncomplete(-1);
  if (lag > 0) throw new DrainIncomplete(lag);

  const before = await v1RowCount();
  await gel.transaction(async (tx) => {
    for (const type of V1_TYPES) await tx.execute(`delete ${type}`);
  });
  return { removed: before };
}
