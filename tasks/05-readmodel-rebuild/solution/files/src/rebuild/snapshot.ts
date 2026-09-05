/**
 * The snapshot: folds every position up to the boundary into generation v2.
 *
 * Batched, and resumable from the store rather than from the cursor, because
 * the process can die halfway through and the cursor may be older than the work
 * that actually landed.
 */

import { gel } from '../gel/client.js';
import { headSeq, readBatch, unfoldedInWindow } from './log.js';
import { foldIntoV2 } from '../projections/v2/projector.js';
import { advanceCursor, fixBoundary, getBoundary } from './state.js';

const BATCH = 200;

export interface SnapshotResult {
  folded: number;
  boundary: number;
}

/** The boundary this rebuild is working to, fixed at the log head when it began. */
export async function snapshotBoundary(): Promise<number> {
  return fixBoundary(await headSeq());
}

/** Where to resume from: the highest position at or below the boundary that v2 holds. */
async function resumeFrom(boundary: number): Promise<number> {
  const value = await gel.querySingle<number | null>(
    'select max((select FeedByUserV2 filter .seq <= <int64>$boundary).seq)',
    { boundary },
  );
  return value === null ? 0 : Number(value);
}

export async function runSnapshot(): Promise<SnapshotResult> {
  const boundary = await snapshotBoundary();
  let folded = 0;
  let after = await resumeFrom(boundary);

  while (after < boundary) {
    const applied = await gel.transaction(async (tx) => {
      const batch = await readBatch(tx, after, boundary, BATCH);
      if (batch.length === 0) return null;
      const seqs = await foldIntoV2(tx, batch);
      return { last: batch[batch.length - 1].seq, count: seqs.length };
    });

    if (applied === null) break;
    folded += applied.count;
    after = applied.last;
    await advanceCursor(after);
  }

  // A batch can end part way through a position's deliveries, and a crash can
  // leave a hole behind the high-water mark, so finish on what the store says
  // rather than on how far the loop reached.
  for (let pass = 0; pass < 20; pass++) {
    const missing = await gel.transaction((tx) => unfoldedInWindow(tx, 0, boundary));
    if (missing.length === 0) break;
    const applied = await gel.transaction(async (tx) => {
      const batch = await readBatch(tx, missing[0] - 1, boundary, BATCH);
      if (batch.length === 0) return 0;
      return (await foldIntoV2(tx, batch)).length;
    });
    if (applied === 0) break;
    folded += applied;
  }

  await advanceCursor(boundary);
  return { folded, boundary };
}

export async function boundaryOrNull(): Promise<number | null> {
  return getBoundary();
}
