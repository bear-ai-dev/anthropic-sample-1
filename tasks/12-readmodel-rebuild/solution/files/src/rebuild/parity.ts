/**
 * The parity gate.
 *
 * The gate answers one question: if we point readers at generation v2 right
 * now, will they get the right answers? The only way to know is to work out what
 * the right answers are from the append log, and then ask v2 what it actually
 * returns. Comparing v2 against the rebuild's own notion of what it wrote proves
 * the rebuild agrees with itself, which is worth nothing.
 *
 * So: fold the log here, in memory, from scratch; read the projections back out
 * of the store; compare. Nothing the snapshot, the tail or the drain recorded is
 * consulted.
 *
 * The gate is re-runnable and has no side effects beyond its verdict.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Executor } from 'gel';
import { gel } from '../gel/client.js';
import { readAll, headSeq } from './log.js';
import { nyDayBucket } from './nybucket.js';
import type { EventRecord, FeedItem } from '../domain/types.js';

const BATTERY_PATH = resolve(import.meta.dirname, '../../config/parity-queries.json');

interface BatteryQuery {
  id: string;
  kind: 'feed' | 'org' | 'tag';
  user_id?: string;
  limit?: number;
  org_id?: string;
  tag?: string;
  day?: string;
}

export interface ParityResult {
  ok: boolean;
  checked: number;
  head: number;
  mismatches: string[];
}

let battery: BatteryQuery[] | null = null;

function loadBattery(): BatteryQuery[] {
  if (!battery) battery = JSON.parse(readFileSync(BATTERY_PATH, 'utf8')) as BatteryQuery[];
  return battery;
}

interface OrgBucket {
  count: number;
  people: Set<string>;
}

interface TagBucket {
  count: number;
  newest_event_id: string;
  newest_at: string;
  newest_seq: number;
}

interface Expected {
  feed: Map<string, FeedItem[]>;
  org: Map<string, OrgBucket>;
  tag: Map<string, TagBucket>;
}

/** Whether `a` reports a later moment than `b`, positions breaking a tie. */
function isNewer(a: { at: string; seq: number }, b: { at: string; seq: number }): boolean {
  const left = Date.parse(a.at);
  const right = Date.parse(b.at);
  return left === right ? a.seq > b.seq : left > right;
}

/** Folds the log the way generation v2 is specified to fold it. */
function expectedFromLog(log: EventRecord[]): Expected {
  const feed = new Map<string, FeedItem[]>();
  const org = new Map<string, OrgBucket>();
  const tag = new Map<string, TagBucket>();
  const seen = new Set<number>();

  for (const event of log) {
    if (seen.has(event.seq)) continue;
    seen.add(event.seq);

    const day = nyDayBucket(event.occurred_at);
    const items = feed.get(event.user_id) ?? [];
    items.push({
      seq: event.seq,
      event_id: event.event_id,
      occurred_at: event.occurred_at,
      tags: [...event.tags],
    });
    feed.set(event.user_id, items);

    const orgKey = `${event.org_id}\u0000${day}`;
    const bucket = org.get(orgKey) ?? { count: 0, people: new Set<string>() };
    bucket.count += 1;
    bucket.people.add(event.user_id);
    org.set(orgKey, bucket);

    for (const t of new Set(event.tags)) {
      const tagKey = `${t}\u0000${day}`;
      const held = tag.get(tagKey);
      if (!held) {
        tag.set(tagKey, {
          count: 1,
          newest_event_id: event.event_id,
          newest_at: event.occurred_at,
          newest_seq: event.seq,
        });
        continue;
      }
      held.count += 1;
      if (isNewer(
        { at: event.occurred_at, seq: event.seq },
        { at: held.newest_at, seq: held.newest_seq },
      )) {
        held.newest_event_id = event.event_id;
        held.newest_at = event.occurred_at;
        held.newest_seq = event.seq;
      }
    }
  }

  for (const [user, items] of feed) {
    items.sort((a, b) => {
      const ta = Date.parse(a.occurred_at);
      const tb = Date.parse(b.occurred_at);
      return tb === ta ? b.seq - a.seq : tb - ta;
    });
    feed.set(user, items);
  }

  return { feed, org, tag };
}

async function actualFeed(tx: Executor, userId: string, limit: number): Promise<FeedItem[]> {
  const rows = await tx.query<{
    seq: number; event_id: string; occurred_at: Date; tags: string[];
  }>(
    `select FeedByUserV2 { seq, event_id, occurred_at, tags }
     filter .user_id = <str>$user_id
     order by .occurred_at desc then .seq desc
     limit <int64>$limit`,
    { user_id: userId, limit },
  );
  return rows.map((r) => ({
    seq: Number(r.seq),
    event_id: r.event_id,
    occurred_at: r.occurred_at.toISOString(),
    tags: [...r.tags],
  }));
}

async function actualOrg(tx: Executor, orgId: string, day: string): Promise<{ count: number; actors: number }> {
  const row = await tx.querySingle<{ count: number; actors: number } | null>(
    `select CountByOrgV2 { count, actors }
     filter .org_id = <str>$org_id and .day_bucket = <str>$day limit 1`,
    { org_id: orgId, day },
  );
  return { count: row ? Number(row.count) : 0, actors: row ? Number(row.actors) : 0 };
}

async function actualTag(
  tx: Executor,
  tagName: string,
  day: string,
): Promise<{ count: number; newest_event_id: string }> {
  const row = await tx.querySingle<{ count: number; newest_event_id: string } | null>(
    `select RecentByTagV2 { count, newest_event_id }
     filter .tag = <str>$tag and .day_bucket = <str>$day limit 1`,
    { tag: tagName, day },
  );
  return {
    count: row ? Number(row.count) : 0,
    newest_event_id: row ? row.newest_event_id : '',
  };
}

/**
 * Compares every org and tag bucket in the store against the fold, in both
 * directions, and stops at a readable number of differences.
 *
 * Both directions matter and for different reasons. A bucket the fold has and
 * the store does not is work that never landed. A bucket the store has and the
 * fold does not is worse: it is a delivery counted into a day it does not
 * belong to, and no amount of counting the same day again will find it.
 */
async function sweepBuckets(tx: Executor, expected: Expected): Promise<string[]> {
  const out: string[] = [];
  const LIMIT = 12;

  const orgRows = await tx.query<{
    org_id: string; day_bucket: string; count: number; actors: number;
  }>('select CountByOrgV2 { org_id, day_bucket, count, actors }');
  const orgSeen = new Set<string>();

  for (const row of orgRows) {
    const key = `${row.org_id}\u0000${row.day_bucket}`;
    orgSeen.add(key);
    const want = expected.org.get(key);
    if (!want) {
      out.push(`org ${row.org_id}/${row.day_bucket}: v2 has a bucket the log does not put anything in`);
    } else if (Number(row.count) !== want.count) {
      out.push(`org ${row.org_id}/${row.day_bucket}: expected ${want.count} deliveries, v2 has ${row.count}`);
    } else if (Number(row.actors) !== want.people.size) {
      out.push(`org ${row.org_id}/${row.day_bucket}: expected ${want.people.size} actors, v2 has ${row.actors}`);
    }
    if (out.length >= LIMIT) return out;
  }
  for (const key of expected.org.keys()) {
    if (orgSeen.has(key)) continue;
    out.push(`org ${key.replace('\u0000', '/')}: the log puts deliveries here and v2 has no bucket`);
    if (out.length >= LIMIT) return out;
  }

  const tagRows = await tx.query<{
    tag: string; day_bucket: string; count: number; newest_event_id: string;
  }>('select RecentByTagV2 { tag, day_bucket, count, newest_event_id }');
  const tagSeen = new Set<string>();

  for (const row of tagRows) {
    const key = `${row.tag}\u0000${row.day_bucket}`;
    tagSeen.add(key);
    const want = expected.tag.get(key);
    if (!want) {
      out.push(`tag ${row.tag}/${row.day_bucket}: v2 has a bucket the log does not put anything in`);
    } else if (Number(row.count) !== want.count) {
      out.push(`tag ${row.tag}/${row.day_bucket}: expected ${want.count}, v2 has ${row.count}`);
    } else if (row.newest_event_id !== want.newest_event_id) {
      out.push(
        `tag ${row.tag}/${row.day_bucket}: newest is ${want.newest_event_id} at ${want.newest_at}, `
        + `v2 points at ${row.newest_event_id}`,
      );
    }
    if (out.length >= LIMIT) return out;
  }
  for (const key of expected.tag.keys()) {
    if (tagSeen.has(key)) continue;
    out.push(`tag ${key.replace('\u0000', '/')}: the log puts deliveries here and v2 has no bucket`);
    if (out.length >= LIMIT) return out;
  }

  return out;
}

const sameTags = (a: string[], b: string[]): boolean =>
  a.length === b.length && a.every((t, i) => t === b[i]);

const sameFeed = (a: FeedItem[], b: FeedItem[]): boolean =>
  a.length === b.length
  && a.every((x, i) => x.seq === b[i].seq
    && x.event_id === b[i].event_id
    && x.occurred_at === b[i].occurred_at
    && sameTags(x.tags, b[i].tags));

/**
 * Runs the gate against the log as it stands now. `head` in the result is the
 * position the gate was evaluated at, so a caller can tell whether the log moved
 * underneath it.
 */
export async function proveParity(tx: Executor = gel): Promise<ParityResult> {
  const head = await headSeq(tx);
  const log = await readAll(tx);
  const expected = expectedFromLog(log);
  const queries = loadBattery();
  const mismatches: string[] = [];

  // Every position in the log must be present in the new generation, not just
  // the ones the battery happens to look at.
  const foldedRows = await tx.query<{ seq: number }>('select FeedByUserV2 { seq }');
  const folded = new Set(foldedRows.map((r) => Number(r.seq)));
  const expectedSeqs = new Set(log.map((e) => e.seq));
  for (const seq of expectedSeqs) {
    if (!folded.has(seq)) mismatches.push(`position ${seq} is in the log but not in v2`);
    if (mismatches.length > 20) break;
  }
  for (const seq of folded) {
    if (!expectedSeqs.has(seq)) mismatches.push(`v2 holds position ${seq}, which is not in the log`);
    if (mismatches.length > 20) break;
  }

  // The battery is what the product team signed off, not what the projection
  // has to be right about. Generation v2 keeps three different things in three
  // different ways, and forty-odd queries touch a few dozen of several hundred
  // buckets, so the gate sweeps every bucket first and uses the battery as a
  // second opinion on the read shapes.
  mismatches.push(...await sweepBuckets(tx, expected));

  for (const query of queries) {
    if (query.kind === 'feed') {
      const want = (expected.feed.get(query.user_id ?? '') ?? []).slice(0, query.limit ?? 20);
      const got = await actualFeed(tx, query.user_id ?? '', query.limit ?? 20);
      if (!sameFeed(want, got)) {
        mismatches.push(`${query.id}: feed differs (expected ${want.length} rows, got ${got.length})`);
      }
    } else if (query.kind === 'org') {
      const want = expected.org.get(`${query.org_id}\u0000${query.day}`)
        ?? { count: 0, people: new Set<string>() };
      const got = await actualOrg(tx, query.org_id ?? '', query.day ?? '');
      if (want.count !== got.count) {
        mismatches.push(`${query.id}: expected ${want.count} deliveries, v2 returned ${got.count}`);
      }
      if (want.people.size !== got.actors) {
        mismatches.push(`${query.id}: expected ${want.people.size} actors, v2 returned ${got.actors}`);
      }
    } else {
      const want = expected.tag.get(`${query.tag}\u0000${query.day}`);
      const got = await actualTag(tx, query.tag ?? '', query.day ?? '');
      const wantCount = want?.count ?? 0;
      if (wantCount !== got.count) {
        mismatches.push(`${query.id}: expected ${wantCount}, v2 returned ${got.count}`);
      }
      if ((want?.newest_event_id ?? '') !== got.newest_event_id) {
        mismatches.push(
          `${query.id}: newest is ${want?.newest_event_id ?? 'none'}, v2 says ${got.newest_event_id || 'none'}`,
        );
      }
    }
  }

  return { ok: mismatches.length === 0, checked: queries.length, head, mismatches: mismatches.slice(0, 20) };
}
