/**
 * The generation v2 projector.
 *
 * Three projections, three different disciplines, and none of them is the
 * others with the names changed:
 *
 *   feed    a row per position, carrying the delivery's tags. Idempotent by
 *           construction, because `seq` is exclusive.
 *   org     a count of deliveries and a count of *people*. The second is a set
 *           question: a bucket's second delivery from someone already in it
 *           moves `count` and not `actors`.
 *   tag     a count of positions and a pointer at the newest of them, where
 *           newest is by the instant a delivery reports and then by position.
 *           That is not the order deliveries arrive in, so the last write is
 *           not the answer.
 *
 * Only the feed is idempotent on its own. The other two move for a position
 * this generation has not folded before and for no other reason, and which
 * positions those are is decided inside the caller's transaction, so two folds
 * racing over one position cannot both call it new.
 */

import type { Executor } from 'gel';
import type { EventRecord } from '../../domain/types.js';
import { nyDayBucket } from '../../rebuild/nybucket.js';

/** The first delivery of each position in `batch`, in the order given. */
export function firstDeliveries(batch: EventRecord[]): EventRecord[] {
  const seen = new Set<number>();
  const out: EventRecord[] = [];
  for (const event of batch) {
    if (seen.has(event.seq)) continue;
    seen.add(event.seq);
    out.push(event);
  }
  return out;
}

/**
 * Folds a batch into the v2 feed projection.
 *
 * One row per position, with `seq` exclusive, so the table is its own record of
 * what it holds: a position that is already there keeps the row it has.
 */
export async function foldFeedIntoV2(tx: Executor, batch: EventRecord[]): Promise<void> {
  const rows = firstDeliveries(batch);
  if (rows.length === 0) return;

  await tx.execute(
    `with raw := to_json(<str>$payload),
     for e in json_array_unpack(raw) union (
       insert FeedByUserV2 {
         user_id := <str>e['user_id'],
         seq := <int64>e['seq'],
         event_id := <str>e['event_id'],
         occurred_at := <datetime>e['occurred_at'],
         tags := array_agg(<str>json_array_unpack(e['tags']))
       }
       unless conflict on (.seq)
       else (select FeedByUserV2)
     )`,
    {
      payload: JSON.stringify(
        rows.map((e) => ({
          user_id: e.user_id,
          seq: e.seq,
          event_id: e.event_id,
          occurred_at: e.occurred_at,
          tags: e.tags,
        })),
      ),
    },
  );
}

/** Positions folded into v2 so far. */
export async function foldedCount(tx: Executor): Promise<number> {
  return Number(await tx.querySingle<number>('select count(FeedByUserV2)'));
}

export async function foldedHighWater(tx: Executor): Promise<number> {
  const value = await tx.querySingle<number | null>('select max(FeedByUserV2.seq)');
  return value === null ? 0 : Number(value);
}

// --------------------------------------------------------------- counters ---

interface OrgDelta {
  name: string;
  day: string;
  delta: number;
  /** Everyone this batch saw in the bucket. A union, not an addition. */
  people: string[];
}

interface TagDelta {
  name: string;
  day: string;
  delta: number;
  /** The newest delivery this batch saw in the bucket, by event time. */
  newest_event_id: string;
  newest_at: string;
  newest_seq: number;
}

/** Whether `a` is newer than `b`: event instant first, then position. */
function newer(
  a: { at: string; seq: number },
  b: { at: string; seq: number },
): boolean {
  const left = Date.parse(a.at);
  const right = Date.parse(b.at);
  if (left !== right) return left > right;
  return a.seq > b.seq;
}

function accumulate(events: EventRecord[]): { org: OrgDelta[]; tag: TagDelta[] } {
  const org = new Map<string, OrgDelta & { seen: Set<string> }>();
  const tag = new Map<string, TagDelta>();

  for (const event of events) {
    const day = nyDayBucket(event.occurred_at);

    const orgKey = `${event.org_id}\u0000${day}`;
    let orgEntry = org.get(orgKey);
    if (!orgEntry) {
      orgEntry = { name: event.org_id, day, delta: 0, people: [], seen: new Set() };
      org.set(orgKey, orgEntry);
    }
    orgEntry.delta += 1;
    if (!orgEntry.seen.has(event.user_id)) {
      orgEntry.seen.add(event.user_id);
      orgEntry.people.push(event.user_id);
    }

    // A position that carries a tag twice counts once for that tag.
    for (const t of new Set(event.tags)) {
      const tagKey = `${t}\u0000${day}`;
      const tagEntry = tag.get(tagKey);
      if (!tagEntry) {
        tag.set(tagKey, {
          name: t,
          day,
          delta: 1,
          newest_event_id: event.event_id,
          newest_at: event.occurred_at,
          newest_seq: event.seq,
        });
        continue;
      }
      tagEntry.delta += 1;
      const candidate = { at: event.occurred_at, seq: event.seq };
      const held = { at: tagEntry.newest_at, seq: tagEntry.newest_seq };
      if (newer(candidate, held)) {
        tagEntry.newest_event_id = event.event_id;
        tagEntry.newest_at = event.occurred_at;
        tagEntry.newest_seq = event.seq;
      }
    }
  }

  return {
    org: [...org.values()].map(({ seen: _seen, ...rest }) => rest),
    tag: [...tag.values()],
  };
}

/** Positions from `candidates` that v2 has not folded yet, in log order. */
export async function selectUnfolded(tx: Executor, candidates: EventRecord[]): Promise<EventRecord[]> {
  if (candidates.length === 0) return [];
  const seqs = candidates.map((e) => e.seq);
  const rows = await tx.query<{ seq: number }>(
    `with wanted := array_unpack(<array<int64>>$seqs)
     select FeedByUserV2 { seq } filter .seq in wanted`,
    { seqs },
  );
  const folded = new Set(rows.map((r) => Number(r.seq)));
  return firstDeliveries(candidates).filter((e) => !folded.has(e.seq));
}

/**
 * Adds this batch's people to each org bucket and re-derives how many there
 * are.
 *
 * Two statements rather than one, because an update sees the membership as it
 * was when the statement began: the count has to be taken after the union has
 * landed, or it counts the wrong set. Adding a member already present is a
 * union and changes nothing, which is what makes a repeated fold harmless here
 * even though the delivery count beside it is not.
 *
 * `distinct` on both sides, because a multi property will hold the same string
 * twice quite happily: appending to one is not the same as adding to a set, and
 * a bucket that saw the same person on two days running would otherwise count
 * them twice.
 */
async function foldOrgBuckets(tx: Executor, org: OrgDelta[]): Promise<void> {
  if (org.length === 0) return;

  await tx.execute(
    `with raw := to_json(<str>$payload),
     for e in json_array_unpack(raw) union (
       insert CountByOrgV2 {
         org_id := <str>e['name'],
         day_bucket := <str>e['day'],
         count := <int64>e['delta'],
         actors := 0,
         actor_ids := (select distinct <str>json_array_unpack(e['people']))
       }
       unless conflict on ((.org_id, .day_bucket))
       else (update CountByOrgV2 set {
         count := CountByOrgV2.count + <int64>e['delta'],
         actor_ids := (
           select distinct (
             CountByOrgV2.actor_ids union (select <str>json_array_unpack(e['people']))
           )
         )
       })
     )`,
    { payload: JSON.stringify(org) },
  );

  await tx.execute(
    `with raw := to_json(<str>$payload),
     for e in json_array_unpack(raw) union (
       update CountByOrgV2
       filter .org_id = <str>e['name'] and .day_bucket = <str>e['day']
       set { actors := count(distinct .actor_ids) }
     )`,
    { payload: JSON.stringify(org.map((e) => ({ name: e.name, day: e.day }))) },
  );
}

/**
 * Adds this batch's positions to each tag bucket and moves the newest pointer
 * only when this batch actually carried something newer.
 *
 * The comparison is on the delivery's own instant, not on when it was folded.
 * A rebuild folds oldest position first and the log's positions are not in
 * event-time order, so a fold that let the last write win would end up pointing
 * at whichever position happened to be highest.
 */
async function foldTagBuckets(tx: Executor, tag: TagDelta[]): Promise<void> {
  if (tag.length === 0) return;

  await tx.execute(
    `with raw := to_json(<str>$payload),
     for e in json_array_unpack(raw) union (
       insert RecentByTagV2 {
         tag := <str>e['name'],
         day_bucket := <str>e['day'],
         count := <int64>e['delta'],
         newest_event_id := <str>e['newest_event_id'],
         newest_at := <datetime>e['newest_at'],
         newest_seq := <int64>e['newest_seq']
       }
       unless conflict on ((.tag, .day_bucket))
       else (update RecentByTagV2 set {
         count := RecentByTagV2.count + <int64>e['delta'],
         newest_event_id := (
           <str>e['newest_event_id']
           if (<datetime>e['newest_at'] > RecentByTagV2.newest_at
               or (<datetime>e['newest_at'] = RecentByTagV2.newest_at
                   and <int64>e['newest_seq'] > RecentByTagV2.newest_seq))
           else RecentByTagV2.newest_event_id
         ),
         newest_seq := (
           <int64>e['newest_seq']
           if (<datetime>e['newest_at'] > RecentByTagV2.newest_at
               or (<datetime>e['newest_at'] = RecentByTagV2.newest_at
                   and <int64>e['newest_seq'] > RecentByTagV2.newest_seq))
           else RecentByTagV2.newest_seq
         ),
         newest_at := (
           <datetime>e['newest_at']
           if (<datetime>e['newest_at'] > RecentByTagV2.newest_at
               or (<datetime>e['newest_at'] = RecentByTagV2.newest_at
                   and <int64>e['newest_seq'] > RecentByTagV2.newest_seq))
           else RecentByTagV2.newest_at
         )
       })
     )`,
    { payload: JSON.stringify(tag) },
  );
}

/**
 * Folds a batch into every v2 projection. Returns the positions actually
 * folded, which is not the batch when some of it was already there.
 *
 * The caller supplies the transaction: the check for what is already folded and
 * the writes that follow it have to be one atomic step.
 */
export async function foldIntoV2(tx: Executor, batch: EventRecord[]): Promise<number[]> {
  const fresh = await selectUnfolded(tx, batch);
  if (fresh.length === 0) return [];

  await foldFeedIntoV2(tx, fresh);

  const { org, tag } = accumulate(fresh);
  await foldOrgBuckets(tx, org);
  await foldTagBuckets(tx, tag);

  return fresh.map((e) => e.seq);
}
