/**
 * The rebuild state machine.
 *
 * `step()` advances by at most one stage and returns where it got to, so an
 * operator can stop between any two stages and look at the store. A stage only
 * hands over when its own postcondition holds — checked against Gel and Redis,
 * not against the fact that the code for that stage ran to completion. That is
 * what makes the machine safe to re-enter after the process has been killed:
 * running a stage again is either a no-op or the completion of unfinished work.
 */

import { redis, allActiveGenerations, ROUTE_KEYS } from '../redis/client.js';
import { gel } from '../gel/client.js';
import type { RebuildPhase, RebuildStatus } from '../domain/types.js';
import { getCursor, getPhase, getSwitchSeq, setPhase } from './state.js';
import { runSnapshot, snapshotBoundary } from './snapshot.js';
import { runTail } from './tail.js';
import { proveParity } from './parity.js';
import { reconcileRouting, runAliasSwitch } from './alias-switch.js';
import { drainLag, runDrain } from './drain.js';
import { DrainIncomplete, runCleanup, v1RowCount } from './cleanup.js';
import { headSeq } from './log.js';
import { foldedHighWater } from '../projections/v2/projector.js';

export class NotImplemented extends Error {
  constructor(what: string) {
    super(`${what} is not implemented`);
    this.name = 'NotImplemented';
  }
}

export class StageRefused extends Error {
  constructor(readonly stage: RebuildPhase, reason: string) {
    super(`${stage} refused: ${reason}`);
    this.name = 'StageRefused';
  }
}

let lastParityOk = false;

async function snapshotComplete(boundary: number): Promise<boolean> {
  const missing = await gel.querySingle<number>(
    `select count((select Event
       filter .seq <= <int64>$boundary
         and not exists (select FeedByUserV2 filter .seq = Event.seq)))`,
    { boundary },
  );
  return Number(missing) === 0;
}

export async function step(): Promise<RebuildStatus> {
  // Routing is repaired before anything else looks at it, so a stage never
  // reasons about a torn cutover.
  await reconcileRouting();

  const phase = await getPhase();

  switch (phase) {
    case 'LIVE_V1': {
      // Fixes the boundary at the log as it stands now, and puts the live
      // append path to work on v2 as well so the backlog stops growing while
      // the snapshot runs.
      await snapshotBoundary();
      await setPhase('SNAPSHOT');
      break;
    }

    case 'SNAPSHOT': {
      const { boundary } = await runSnapshot();
      if (!(await snapshotComplete(boundary))) {
        throw new StageRefused('SNAPSHOT', `positions up to ${boundary} are not all folded`);
      }
      await setPhase('TAIL');
      break;
    }

    case 'TAIL': {
      const result = await runTail();
      if (!result.caughtUp) {
        throw new StageRefused('TAIL', `v2 is still behind the log at ${result.head}`);
      }
      await setPhase('PARITY');
      break;
    }

    case 'PARITY': {
      const parity = await proveParity();
      lastParityOk = parity.ok;
      if (!parity.ok) {
        // The gate is not a place to sit and retry: whatever it found is work
        // the tail has not done, so go back and do it.
        await setPhase('TAIL');
        throw new StageRefused('PARITY', parity.mismatches.slice(0, 3).join('; ') || 'battery mismatch');
      }
      await setPhase('SWITCH');
      break;
    }

    case 'SWITCH': {
      // The gate is re-proved here rather than trusted from the previous call:
      // the operator may have paused between stages, and the log moves.
      const parity = await proveParity();
      lastParityOk = parity.ok;
      if (!parity.ok) {
        await setPhase('TAIL');
        throw new StageRefused('SWITCH', 'parity no longer holds; returned to the tail');
      }
      await runAliasSwitch();
      await setPhase('DRAIN');
      break;
    }

    case 'DRAIN': {
      const result = await runDrain();
      if (result.lag > 0) throw new StageRefused('DRAIN', `${result.lag} position(s) still unfolded`);
      await setPhase('CLEANUP');
      break;
    }

    case 'CLEANUP': {
      try {
        await runCleanup();
      } catch (err) {
        if (err instanceof DrainIncomplete) {
          // Something in the window is unfolded. That is the drain's work, not
          // a reason to sit here refusing, so go back and do it.
          await setPhase('DRAIN');
          throw new StageRefused('CLEANUP', err.message);
        }
        throw err;
      }
      await setPhase('COMPLETE');
      break;
    }

    case 'COMPLETE':
      break;
  }

  return status();
}

export async function abort(): Promise<RebuildStatus> {
  const aliases = await allActiveGenerations();
  const live = ROUTE_KEYS.filter((k) => aliases[k] === 'v2').length;
  if (live > 0) {
    throw new StageRefused('SWITCH', 'routing has already moved to v2; the cutover cannot be undone');
  }
  await setPhase('LIVE_V1');
  // Both copies, and the store's first. Forgetting an abandoned attempt only in
  // the cache leaves the next one to read a boundary and a cursor belonging to
  // a rebuild that was called off, and start its snapshot part-way through the
  // log.
  await gel.execute(
    'delete RebuildMeta filter .key in {"rebuild:cursor", "rebuild:switch_seq", "rebuild:boundary"}',
  );
  await redis.del('rebuild:cursor', 'rebuild:switch_seq', 'rebuild:boundary');
  return status();
}

export async function status(): Promise<RebuildStatus> {
  // An operator asking where the rebuild is should be told where it is, not
  // where the cache last remembered it being. Reconciling here costs a read of
  // one table on an endpoint nobody is in a hurry on, and it means the status
  // an operator sees after a cache restart is the status the readers get.
  await reconcileRouting();

  const [phase, cursor, switchSeq, lag, aliases] = await Promise.all([
    getPhase(),
    getCursor(),
    getSwitchSeq(),
    drainLag(),
    allActiveGenerations(),
  ]);

  return {
    phase,
    cursor: Math.max(cursor, await foldedHighWater(gel)),
    parity_ok: lastParityOk,
    drain_lag: lag,
    switch_seq: switchSeq,
    aliases,
  };
}

/** Reported by the status endpoint for operators watching a cutover. */
export async function diagnostics(): Promise<Record<string, number>> {
  return {
    head: await headSeq(),
    v1_rows: await v1RowCount(),
  };
}
