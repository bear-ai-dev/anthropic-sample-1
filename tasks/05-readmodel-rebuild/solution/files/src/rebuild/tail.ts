/**
 * The incremental tail: folds everything that arrived after the snapshot
 * boundary, and keeps folding until it has caught up with the log.
 *
 * It reads forward from a cursor rather than rescanning, and it re-reads the
 * head on each pass because appends do not stop while it runs. "Caught up"
 * means a pass found nothing left, not that a pass finished.
 */

import { gel } from '../gel/client.js';
import { headSeq, readBatch, unfoldedInWindow } from './log.js';
import { foldIntoV2 } from '../projections/v2/projector.js';
import { advanceCursor, getCursor } from './state.js';
import { snapshotBoundary } from './snapshot.js';

const BATCH = 200;
const MAX_PASSES = 200;

export interface TailResult {
  folded: number;
  cursor: number;
  head: number;
  caughtUp: boolean;
}

export async function runTail(): Promise<TailResult> {
  const boundary = await snapshotBoundary();
  let folded = 0;
  let cursor = Math.max(await getCursor(), 0);
  let head = await headSeq();

  for (let pass = 0; pass < MAX_PASSES; pass++) {
    if (cursor >= head) {
      const straggler = await gel.transaction((tx) => unfoldedInWindow(tx, 0, head));
      if (straggler.length === 0) break;
      // Something in the window was skipped — a position that reached the log
      // without passing through the append handler, one that arrived out of
      // order, or work lost to a crash. Go back for it rather than trusting the
      // cursor, which only records how far a pass reached.
      cursor = Math.min(...straggler) - 1;
    }

    const applied = await gel.transaction(async (tx) => {
      const batch = await readBatch(tx, cursor, head, BATCH);
      if (batch.length === 0) return null;
      const seqs = await foldIntoV2(tx, batch);
      return { last: batch[batch.length - 1].seq, count: seqs.length };
    });

    if (applied === null) {
      cursor = head;
    } else {
      folded += applied.count;
      cursor = applied.last;
    }

    await advanceCursor(cursor);
    head = await headSeq();
  }

  const remaining = await gel.transaction((tx) => unfoldedInWindow(tx, 0, head));
  return { folded, cursor, head, caughtUp: remaining.length === 0 && cursor >= boundary };
}
