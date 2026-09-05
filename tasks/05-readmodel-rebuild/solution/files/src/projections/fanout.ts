/**
 * Where the live append path fans a delivery out to projection generations
 * other than v1.
 *
 * Once a rebuild has started, v2 is a generation this service maintains, and
 * the append path is responsible for keeping it current — before the cutover so
 * the backlog does not grow, and after it because v2 is what readers see. This
 * runs inside the append transaction, so a position lands in the log and in
 * both generations together or not at all.
 *
 * Folding here is safe alongside the rebuild's own passes: the fold consults
 * what has already been folded inside the same transaction, so whichever of the
 * two gets there first, the position counts once.
 */

import type { Executor } from 'gel';
import type { EventRecord } from '../domain/types.js';
import { foldIntoV2 } from './v2/projector.js';
import { v2IsBeingMaintained } from '../rebuild/state.js';

export async function liveFanout(tx: Executor, event: EventRecord): Promise<void> {
  if (!(await v2IsBeingMaintained())) return;
  await foldIntoV2(tx, [event]);
}
