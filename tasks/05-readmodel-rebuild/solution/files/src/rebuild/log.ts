/**
 * Reads of the append log.
 *
 * The log is the only authority. Everything the rebuild believes about what
 * should be in a projection comes from here, never from the projection itself
 * and never from bookkeeping the rebuild wrote earlier.
 *
 * The log is a stream of deliveries, so a position can appear in it more than
 * once. Reads are ordered by position and then by arrival, which is what makes
 * "the first delivery of a position" a fact about the log rather than about the
 * order rows came back in.
 */

import type { Executor } from 'gel';
import { gel } from '../gel/client.js';
import type { EventRecord } from '../domain/types.js';

interface RawEvent {
  seq: number;
  event_id: string;
  org_id: string;
  user_id: string;
  tags: string[];
  occurred_at: Date;
  schema_ver: number;
}

const toRecord = (r: RawEvent): EventRecord => ({
  seq: Number(r.seq),
  event_id: r.event_id,
  org_id: r.org_id,
  user_id: r.user_id,
  tags: [...r.tags],
  occurred_at: r.occurred_at.toISOString(),
  schema_ver: Number(r.schema_ver),
});

const SHAPE = 'seq, event_id, org_id, user_id, tags, occurred_at, schema_ver';
const ORDER = 'order by .seq asc then .delivery_no asc';

export async function headSeq(tx: Executor = gel): Promise<number> {
  const value = await tx.querySingle<number | null>('select max(Event.seq)');
  return value === null ? 0 : Number(value);
}

export async function countInRange(tx: Executor, lo: number, hi: number): Promise<number> {
  const value = await tx.querySingle<number>(
    'select count(distinct (select Event filter .seq > <int64>$lo and .seq <= <int64>$hi).seq)',
    { lo, hi },
  );
  return Number(value);
}

/** Deliveries of positions in `(after, ceiling]`, oldest position first. */
export async function readBatch(
  tx: Executor,
  after: number,
  ceiling: number,
  limit: number,
): Promise<EventRecord[]> {
  const rows = await tx.query<RawEvent>(
    `select Event { ${SHAPE} }
     filter .seq > <int64>$after and .seq <= <int64>$ceiling
     ${ORDER}
     limit <int64>$limit`,
    { after, ceiling, limit },
  );
  return rows.map(toRecord);
}

/** Every delivery in the log, oldest position first. Used by the parity gate. */
export async function readAll(tx: Executor = gel): Promise<EventRecord[]> {
  const rows = await tx.query<RawEvent>(`select Event { ${SHAPE} } ${ORDER}`);
  return rows.map(toRecord);
}

/** Positions in `(lo, hi]` that generation v2 has not folded yet. */
export async function unfoldedInWindow(tx: Executor, lo: number, hi: number): Promise<number[]> {
  const rows = await tx.query<{ seq: number }>(
    `select Event { seq }
     filter .seq > <int64>$lo and .seq <= <int64>$hi
       and not exists (select FeedByUserV2 filter .seq = Event.seq)
     order by .seq asc`,
    { lo, hi },
  );
  return [...new Set(rows.map((r) => Number(r.seq)))];
}
