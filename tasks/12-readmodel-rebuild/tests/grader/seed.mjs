/**
 * Puts the world back to the state the service has been running in: the
 * preserved delivery log in Gel, folded into the generation v1 projections,
 * generation v2 empty, routing on v1, no rebuild bookkeeping.
 *
 * The verifier seeds rather than calling the workspace's seed script, so that a
 * candidate cannot change what it is graded against, and a broken seed script
 * is never mistaken for a broken harness.
 */

import { readFileSync } from 'node:fs';
import { gelScript, gelQuery, redisCli, VERIFIER } from './lib.mjs';

export const SNAPSHOT_BOUNDARY = 1200;

const TYPES = [
  'FeedByUserV1', 'CountByOrgV1', 'RecentByTagV1',
  'FeedByUserV2', 'CountByOrgV2', 'RecentByTagV2',
  'RebuildMeta', 'Event',
];

export function loadTruth() {
  const raw = readFileSync(`${VERIFIER}/truth/events_truth.jsonl`, 'utf8');
  return raw.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

export function loadLiveScript() {
  const raw = readFileSync(`${VERIFIER}/fixtures/live-events.jsonl`, 'utf8');
  return raw.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

/** Generation v1's bucket, which is the UTC calendar date. */
const utcDay = (iso) => iso.slice(0, 10);

const quote = (s) => JSON.stringify(s);

export function resetStores() {
  gelScript(TYPES.map((t) => `delete ${t};`).join('\n'));
  redisCli('flushall');
  for (const key of ['proj:feed:active', 'proj:counts:active', 'proj:tags:active']) {
    redisCli('set', key, 'v1');
  }
}

/**
 * Puts deliveries into the log without going near the append handler, the way
 * the producer's backfill path does. Used for the preserved log and, during a
 * graded run, for the positions the script marks as arriving that way.
 */
export function writeToLog(deliveries, received = '2025-12-31T00:00:00Z') {
  if (deliveries.length === 0) return 0;

  // A delivery already in the log is left alone. The harness offers the same
  // delivery again when it is not sure the first attempt landed, and putting a
  // second copy of it in the log would be the harness inventing a redelivery
  // that the script never called for -- and, since event_id is exclusive, would
  // take the whole run down with a constraint violation rather than a verdict.
  const ids = deliveries.map((e) => e.event_id);
  const seen = new Set(
    gelQuery(
      `with wanted := (select <str>json_array_unpack(to_json(${quote(JSON.stringify(ids))})))
       select Event { event_id } filter .event_id in wanted`,
    ).map((r) => r.event_id),
  );
  const fresh = deliveries.filter((e) => !seen.has(e.event_id));
  if (fresh.length === 0) return 0;

  const [{ next }] = gelQuery('select { next := (max(Event.delivery_no) ?? 0) + 1 }');
  const payload = fresh.map((e, i) => ({
    ...e,
    delivery_no: Number(next) + i,
    received_at: e.received_at ?? received,
  }));

  gelScript(`
with raw := to_json(${quote(JSON.stringify(payload))})
for e in json_array_unpack(raw) union (
  insert Event {
    delivery_no := <int64>e['delivery_no'],
    seq := <int64>e['seq'],
    event_id := <str>e['event_id'],
    org_id := <str>e['org_id'],
    user_id := <str>e['user_id'],
    tags := array_agg(<str>json_array_unpack(e['tags'])),
    occurred_at := <datetime>e['occurred_at'],
    schema_ver := <int16>e['schema_ver'],
    received_at := <datetime>e['received_at']
  });
`);
  return payload.length;
}

export function seedPreservedLog() {
  const truth = loadTruth();
  const deliveries = truth.filter((d) => d.seq <= SNAPSHOT_BOUNDARY);

  const seen = new Set();
  const first = [];
  for (const d of deliveries) {
    if (seen.has(d.seq)) continue;
    seen.add(d.seq);
    first.push(d);
  }

  writeToLog(deliveries);

  const org = new Map();
  const tag = new Map();
  for (const e of first) {
    const day = utcDay(e.occurred_at);
    org.set(`${e.org_id}\u0000${day}`, (org.get(`${e.org_id}\u0000${day}`) ?? 0) + 1);
    for (const t of new Set(e.tags)) {
      tag.set(`${t}\u0000${day}`, (tag.get(`${t}\u0000${day}`) ?? 0) + 1);
    }
  }
  const rows = (m) => [...m].map(([k, count]) => {
    const [name, day] = k.split('\u0000');
    return { name, day, count };
  });

  gelScript(`
with raw := to_json(${quote(JSON.stringify(first))})
for e in json_array_unpack(raw) union (
  insert FeedByUserV1 {
    user_id := <str>e['user_id'],
    seq := <int64>e['seq'],
    event_id := <str>e['event_id'],
    occurred_at := <datetime>e['occurred_at']
  });

with raw := to_json(${quote(JSON.stringify(rows(org)))})
for e in json_array_unpack(raw) union (
  insert CountByOrgV1 {
    org_id := <str>e['name'], day_bucket := <str>e['day'], count := <int64>e['count']
  });

with raw := to_json(${quote(JSON.stringify(rows(tag)))})
for e in json_array_unpack(raw) union (
  insert RecentByTagV1 {
    tag := <str>e['name'], day_bucket := <str>e['day'], count := <int64>e['count']
  });
`);

  return { deliveries: deliveries.length, positions: first.length, orgRows: org.size, tagRows: tag.size };
}
