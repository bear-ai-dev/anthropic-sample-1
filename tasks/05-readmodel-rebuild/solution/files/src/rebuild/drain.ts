/**
 * The drain.
 *
 * Between the parity gate passing and routing actually moving, the log kept
 * growing. The drain closes that window: every position in
 * `(boundary, switch_seq]` that v2 has not folded gets folded now.
 *
 * `drainLag` is computed by asking the store, never by subtracting cursors. A
 * cursor records how far a pass reached; it does not record what landed, and
 * after a crash those are different numbers.
 */

import { gel } from '../gel/client.js';
import { readBatch, unfoldedInWindow } from './log.js';
import { foldIntoV2 } from '../projections/v2/projector.js';
import { snapshotBoundary } from './snapshot.js';
import { getSwitchSeq } from './state.js';

const BATCH = 200;

export async function drainLag(): Promise<number | null> {
  const switchSeq = await getSwitchSeq();
  if (switchSeq === null) return null;
  const boundary = await snapshotBoundary();
  const missing = await gel.transaction((tx) => unfoldedInWindow(tx, boundary, switchSeq));
  return missing.length;
}

export interface DrainResult {
  folded: number;
  lag: number;
  window: [number, number];
}

export async function runDrain(): Promise<DrainResult> {
  const switchSeq = await getSwitchSeq();
  if (switchSeq === null) throw new Error('cannot drain before the cutover window is known');
  const boundary = await snapshotBoundary();

  let folded = 0;
  for (let pass = 0; pass < 200; pass++) {
    const missing = await gel.transaction((tx) => unfoldedInWindow(tx, boundary, switchSeq));
    if (missing.length === 0) break;

    const from = missing[0] - 1;
    const applied = await gel.transaction(async (tx) => {
      const batch = await readBatch(tx, from, switchSeq, BATCH);
      if (batch.length === 0) return 0;
      return (await foldIntoV2(tx, batch)).length;
    });
    if (applied === 0) break;
    folded += applied;
  }

  const remaining = await gel.transaction((tx) => unfoldedInWindow(tx, boundary, switchSeq));
  return { folded, lag: remaining.length, window: [boundary, switchSeq] };
}
