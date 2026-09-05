/**
 * The graded rules, and the model they are judged against.
 *
 * Expected values come from `projfold`, which folds the canonical delivery log
 * and has never seen the workspace. Actual values come from the store and from
 * HTTP. Nothing here derives an expectation from anything the candidate wrote.
 *
 * Each predicate is deliberately narrow. Coverage -- which positions the new
 * generation holds -- is R1, R2 and R9's business and nobody else's, so the
 * rules that judge contents are asked only about the positions the candidate
 * actually folded. That is what lets "folded the wrong identity", "counted a
 * position twice", "bucketed it into the wrong day" and "never folded it" be
 * four separable failures rather than one.
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { gelQuery, isoInstant, VERIFIER } from './lib.mjs';

const TRUTH = `${VERIFIER}/truth/events_truth.jsonl`;
const BATTERY = `${VERIFIER}/fixtures/parity-queries.json`;

export const RULES = {
  R1: 'the snapshot materialises the whole boundary before the rebuild moves on',
  R2: 'routing does not move while the new generation is behind the log',
  R3: 'a position is folded exactly once, first delivery authoritative',
  R4: 'counters bucket days by New York local date',
  R5: 'the three routing keys are never observed disagreeing',
  R6: 'the old generation is not retired while the new one is missing a position',
  R7: 'nothing on the read path depends on the old generation once it is gone',
  R8: 'the read path serves the new generation, ordered and limited as specified',
  R9: 'the new generation stays level with the log once it is the one serving',
  R10: 'the append path keeps taking deliveries for the whole of a rebuild',
  R11: 'a read in flight when the cutover lands is still answered out of a whole generation',
  R12: 'the org projection counts people as well as deliveries, and knows they are different',
  R13: 'the tag projection points at the newest delivery in its bucket, by event time',
  R14: 'the read path hands back everything the serving generation holds',
  R15: 'losing the cache does not lose which generation is serving, or the rebuild',
};

/** Folds the canonical log over a chosen set of positions. */
export function model(seqs, generation = 'v2') {
  const spec = seqs === 'all' ? '1-100000' : compress(seqs);
  const out = `/tmp/expected-${Math.random().toString(36).slice(2)}.json`;
  const res = spawnSync(`${VERIFIER}/bin/projfold`, [
    'fold', '-truth', TRUTH, '-battery', BATTERY, '-seqs', spec,
    '-generation', generation, '-out', out,
  ], { encoding: 'utf8' });
  if (res.status !== 0) throw new Error(`model failed: ${res.stderr || res.stdout}`);
  return JSON.parse(readFileSync(out, 'utf8'));
}

function compress(seqs) {
  const sorted = [...new Set(seqs)].sort((a, b) => a - b);
  const parts = [];
  let start = null;
  let prev = null;
  for (const s of sorted) {
    if (start === null) { start = prev = s; continue; }
    if (s === prev + 1) { prev = s; continue; }
    parts.push(start === prev ? `${start}` : `${start}-${prev}`);
    start = prev = s;
  }
  if (start !== null) parts.push(start === prev ? `${start}` : `${start}-${prev}`);
  return parts.join(',') || '0';
}

export const battery = () => JSON.parse(readFileSync(BATTERY, 'utf8'));

// ------------------------------------------------------- store readings ----

export const logPositions = () =>
  [...new Set(gelQuery('select Event { seq } order by .seq').map((r) => Number(r.seq)))];

export const v2Positions = () =>
  gelQuery('select FeedByUserV2 { seq } order by .seq').map((r) => Number(r.seq));

export const v2FeedRows = () =>
  gelQuery('select FeedByUserV2 { user_id, seq, event_id, occurred_at, tags }').map((r) => ({
    user_id: r.user_id,
    seq: Number(r.seq),
    event_id: r.event_id,
    occurred_at: isoInstant(r.occurred_at),
    tags: [...(r.tags ?? [])],
  }));

/** The org buckets as generation v2 holds them, keyed the way the model keys them. */
export const v2OrgBuckets = () =>
  gelQuery('select CountByOrgV2 { org_id, day_bucket, count, actors, actor_ids }').map((r) => ({
    key: `${r.org_id}|${r.day_bucket}`,
    org_id: r.org_id,
    day: r.day_bucket,
    count: Number(r.count),
    actors: Number(r.actors),
    people: [...(r.actor_ids ?? [])].sort(),
  }));

/** The tag buckets as generation v2 holds them. */
export const v2TagBuckets = () =>
  gelQuery('select RecentByTagV2 { tag, day_bucket, count, newest_event_id, newest_at, newest_seq }')
    .map((r) => ({
      key: `${r.tag}|${r.day_bucket}`,
      tag: r.tag,
      day: r.day_bucket,
      count: Number(r.count),
      newest_event_id: String(r.newest_event_id ?? ''),
      newest_at: r.newest_at === null || r.newest_at === undefined ? null : isoInstant(r.newest_at),
      newest_seq: Number(r.newest_seq ?? 0),
    }));

/**
 * What a given generation's tables answer a feed query with, read straight out
 * of the store rather than over HTTP.
 *
 * Used by R11, which needs to know both of the answers a reader could
 * legitimately have been given, and by nothing else. Nothing here derives an
 * expectation about what the tables should *contain* -- that is R3, R4 and the
 * coverage rules' business.
 *
 * Sorted into one canonical order rather than the order a reader would present
 * them in, and taken without a limit: R11 asks which generation answered, and
 * a candidate that sorts or truncates its own output differently has not got
 * that question wrong. `canonFeed` puts a reader's answer in the same shape.
 */
export function feedAnswer(table, userId) {
  return canonFeed(
    gelQuery(
      `select ${table} { seq, event_id, occurred_at }
       filter .user_id = ${JSON.stringify(userId)}`,
    ),
  );
}

export const canonFeed = (rows) =>
  rows
    .map((r) => ({
      seq: Number(r.seq),
      event_id: String(r.event_id ?? ''),
      occurred_at: isoInstant(r.occurred_at),
    }))
    .sort((a, b) => a.seq - b.seq || (a.event_id < b.event_id ? -1 : 1));

export function counterAnswer(table, field, name, day) {
  const rows = gelQuery(
    `select ${table} { count }
     filter .${field} = ${JSON.stringify(name)} and .day_bucket = ${JSON.stringify(day)}
     limit 1`,
  );
  return rows.length > 0 ? Number(rows[0].count) : 0;
}

export const counterKeys = (table, field) =>
  gelQuery(`select ${table} { name := .${field}, day_bucket, count }`)
    .map((r) => ({ name: r.name, day: r.day_bucket, count: Number(r.count) }));

export const feedUsers = (table) =>
  gelQuery(`select ${table} { user_id }`).map((r) => r.user_id);

export const v2CounterTotals = () => {
  const org = gelQuery('select CountByOrgV2 { count }').reduce((a, r) => a + Number(r.count), 0);
  const tag = gelQuery('select RecentByTagV2 { count }').reduce((a, r) => a + Number(r.count), 0);
  return { org, tag };
};

export const v1RowCount = () => storeState().v1;

/**
 * Everything the polling loops need, in one round trip. The gel CLI costs about
 * a fifth of a second to start, so asking it five separate questions on every
 * iteration dominates the run.
 */
export function storeState() {
  const [s] = gelQuery(`select {
    log := count(distinct Event.seq),
    deliveries := count(Event),
    head := max(Event.seq) ?? 0,
    v2 := count(FeedByUserV2),
    v2_head := max(FeedByUserV2.seq) ?? 0,
    v2_below_boundary := count((select FeedByUserV2 filter .seq <= 1200)),
    v1 := count(FeedByUserV1) + count(CountByOrgV1) + count(RecentByTagV1)
  }`);
  return {
    log: Number(s.log), deliveries: Number(s.deliveries), head: Number(s.head),
    v2: Number(s.v2), v2Head: Number(s.v2_head),
    v2BelowBoundary: Number(s.v2_below_boundary),
    v1: Number(s.v1),
  };
}

// ------------------------------------------------------------ predicates ---

const missingFrom = (want, have) => {
  const set = new Set(have);
  return want.filter((x) => !set.has(x));
};

/**
 * R1 / R2 / R9 are about coverage: which positions the new generation holds.
 * They deliberately say nothing about row contents, so that "folded the wrong
 * event_id" and "did not fold at all" are separable failures.
 */
export function coverageVerdict(required, present, logSeqs) {
  const missing = missingFrom(required, present);
  const spurious = missingFrom(present, logSeqs);
  return {
    pass: missing.length === 0 && spurious.length === 0,
    missing: missing.slice(0, 12),
    missing_count: missing.length,
    spurious: spurious.slice(0, 12),
    spurious_count: spurious.length,
    present_count: present.length,
    required_count: required.length,
  };
}

/**
 * R3: one row per position carrying the first delivery's identity, and counters
 * that moved once for each position folded.
 *
 * Judged against a fold of exactly the positions the candidate holds, so a
 * generation that is missing work fails R1, R2 or R9 for that and is judged here
 * only on what it did fold.
 */
export function foldedOnceVerdict() {
  const rows = v2FeedRows();
  const held = rows.map((r) => r.seq);
  const expected = model(held.length ? held : [0]);

  const wanted = new Map();
  for (const [user, items] of Object.entries(expected.feed)) {
    for (const item of items) wanted.set(item.seq, { ...item, user_id: user });
  }

  const bySeq = new Map();
  const duplicated = [];
  for (const row of rows) {
    if (bySeq.has(row.seq)) duplicated.push(row.seq);
    bySeq.set(row.seq, row);
  }

  const wrong = [];
  for (const [seq, want] of wanted) {
    const got = bySeq.get(seq);
    if (!got) continue; // coverage is R1/R2/R9's business
    if (got.event_id !== want.event_id || got.user_id !== want.user_id
        || isoInstant(got.occurred_at) !== isoInstant(want.occurred_at)) {
      wrong.push({ seq, expected: want.event_id, got: got.event_id });
    }
  }

  const totals = v2CounterTotals();
  const expectedOrgTotal = expected.seq_count;
  const expectedTagTotal = Object.values(expected.tag).reduce((a, b) => a + b.count, 0);

  return {
    pass: duplicated.length === 0 && wrong.length === 0
      && totals.org === expectedOrgTotal && totals.tag === expectedTagTotal,
    positions_held: held.length,
    duplicated_positions: duplicated.slice(0, 10),
    wrong_identity: wrong.slice(0, 10),
    wrong_identity_count: wrong.length,
    org_counter_total: totals.org,
    org_counter_expected: expectedOrgTotal,
    tag_counter_total: totals.tag,
    tag_counter_expected: expectedTagTotal,
  };
}

/**
 * R4: which day a delivery is counted into.
 *
 * Judged by comparing two independent folds of the positions the candidate
 * holds -- one bucketed in New York, one in UTC -- and looking only at the days
 * where they disagree. The verdict is about placement, not magnitude, so a
 * projection that counts every delivery twice still passes here and fails R3
 * instead, and one that is missing half the log is judged only on the half it
 * has. One bug, one rule.
 */
export function bucketVerdict() {
  const held = v2Positions();
  const seqs = held.length ? held : [0];
  const ny = model(seqs, 'v2');
  const utc = model(seqs, 'v1');

  const stored = {
    org: gelQuery('select CountByOrgV2 { org_id, day_bucket, count }')
      .filter((r) => Number(r.count) > 0).map((r) => `${r.org_id}|${r.day_bucket}`),
    tag: gelQuery('select RecentByTagV2 { tag, day_bucket, count }')
      .filter((r) => Number(r.count) > 0).map((r) => `${r.tag}|${r.day_bucket}`),
  };

  const misplaced = [];
  for (const kind of ['org', 'tag']) {
    const present = new Set(stored[kind]);
    const inNY = new Set(Object.keys(ny[kind]).filter((k) => ny[kind][k].count > 0));
    const inUTC = new Set(Object.keys(utc[kind]).filter((k) => utc[kind][k].count > 0));

    for (const key of inNY) {
      if (!inUTC.has(key) && !present.has(key)) {
        misplaced.push(`${kind} ${key}: New York puts deliveries on this day and the projection has none`);
      }
    }
    for (const key of inUTC) {
      if (!inNY.has(key) && present.has(key)) {
        misplaced.push(`${kind} ${key}: this day only exists in UTC and the projection has counted into it`);
      }
    }
  }

  return {
    pass: misplaced.length === 0,
    positions_held: held.length,
    misplaced_count: misplaced.length,
    misplaced: misplaced.slice(0, 8),
  };
}

/**
 * The fold whose day placement matches the candidate's, and the positions it
 * holds.
 *
 * R12 and R13 are about what a bucket says, not about which day it is. A
 * projection bucketed in UTC has put its deliveries on the wrong days, which is
 * R4's question and R4 fails it for exactly that; asking R12 and R13 about the
 * same mistake a second time would be three rules for one bug. So both folds
 * are taken and the one that agrees with the projection about *which buckets
 * exist* is the one its contents are judged against. A projection bucketed
 * correctly matches the New York fold and is judged against that.
 */
function foldMatchingTheBucketing(kind, storedKeys) {
  const held = v2Positions();
  const seqs = held.length ? held : [0];
  const overlap = (fold) => {
    const keys = new Set(Object.keys(fold[kind]));
    return storedKeys.filter((k) => keys.has(k)).length;
  };
  const ny = model(seqs, 'v2');
  const nyOverlap = overlap(ny);
  const utc = model(seqs, 'v1');
  return overlap(utc) > nyOverlap
    ? { fold: utc, bucketing: 'the projection buckets in UTC; judged against a UTC fold' }
    : { fold: ny, bucketing: 'New York' };
}

/**
 * R12: how many different people a bucket's deliveries came from.
 *
 * `actors` is beside `count` in the same row and is not derivable from it: the
 * two agree in a bucket where nobody appears twice and part company in a bucket
 * where somebody does. A projection that maintains it the way it maintains the
 * count -- one more per delivery -- is right in most buckets and wrong in the
 * ones where the question means anything.
 *
 * Judged against a fold of exactly the positions the candidate holds, so work
 * that is missing fails a coverage rule rather than this one, and judged only
 * on buckets the fold and the projection both have, so a projection that put a
 * delivery on the wrong day fails R4 and is not failed twice for it.
 */
export function actorsVerdict() {
  const buckets = v2OrgBuckets();
  const { fold: expected, bucketing } = foldMatchingTheBucketing(
    'org', buckets.map((b) => b.key),
  );

  const wrong = [];
  const inflated = [];
  let compared = 0;

  for (const bucket of buckets) {
    if (bucket.actors > bucket.count) {
      inflated.push({ bucket: bucket.key, deliveries: bucket.count, actors: bucket.actors });
    }
    const want = expected.org[bucket.key];
    if (!want) continue;
    compared += 1;
    if (bucket.actors !== want.actors) {
      wrong.push({
        bucket: bucket.key,
        deliveries: bucket.count,
        actors_expected: want.actors,
        actors_recorded: bucket.actors,
        the_people_in_this_bucket: want.people.slice(0, 8),
      });
    }
  }

  return {
    pass: wrong.length === 0 && inflated.length === 0 && compared > 0,
    days_bucketed_by: bucketing,
    buckets_compared: compared,
    buckets_where_the_two_numbers_differ:
      Object.values(expected.org).filter((b) => b.actors !== b.count).length,
    wrong_count: wrong.length,
    wrong: wrong.slice(0, 6),
    more_actors_than_deliveries: inflated.slice(0, 4),
  };
}

/**
 * R13: which delivery a tag bucket points at as its newest.
 *
 * Newest is by the instant the delivery reports and then by position. The log's
 * positions are not in event-time order, and a rebuild folds them oldest
 * position first, so a projection that lets the last write win points at the
 * highest position in the bucket rather than the latest one. The two answers
 * differ in most buckets in this log.
 *
 * Same discipline as R12: folded against what the candidate holds, compared
 * only where both have the bucket.
 */
export function newestVerdict() {
  const buckets = v2TagBuckets();
  const { fold: expected, bucketing } = foldMatchingTheBucketing(
    'tag', buckets.map((b) => b.key),
  );

  const wrong = [];
  let compared = 0;

  for (const bucket of buckets) {
    const want = expected.tag[bucket.key];
    if (!want) continue;
    compared += 1;
    if (bucket.newest_event_id === want.newest_event_id) continue;
    wrong.push({
      bucket: bucket.key,
      newest_expected: want.newest_event_id,
      newest_at_expected: want.newest_at,
      newest_recorded: bucket.newest_event_id,
      recorded_at: bucket.newest_at,
    });
  }

  return {
    pass: wrong.length === 0 && compared > 0,
    days_bucketed_by: bucketing,
    buckets_compared: compared,
    wrong_count: wrong.length,
    wrong: wrong.slice(0, 6),
  };
}

/**
 * R14: the read path hands back what the serving generation holds.
 *
 * Generation v2 keeps three things v1 has no column for, and it does not keep
 * them in the same way, so there are three separate answers to get out of the
 * store and onto the wire. Compared against the rows themselves rather than
 * against the model: a projection folded wrongly fails R3, R4, R12 or R13 for
 * that, and is judged here only on whether what it holds reaches the caller.
 *
 * Lenient about presentation. A feed answer is judged on the tags of the rows
 * it did return, in the order the row holds them; a bucket with no row is
 * allowed to answer either none or nothing at all.
 */
export function exposureVerdict(answers) {
  const feedRows = new Map(v2FeedRows().map((r) => [r.seq, r]));
  const orgRows = new Map(v2OrgBuckets().map((b) => [b.key, b]));
  const tagRows = new Map(v2TagBuckets().map((b) => [b.key, b]));

  const wrong = [];
  let checked = 0;

  for (const a of answers) {
    if (a.status !== 200) continue;

    if (a.q.kind === 'feed') {
      for (const item of a.items ?? []) {
        const row = feedRows.get(Number(item.seq));
        if (!row) continue;
        checked += 1;
        const got = Array.isArray(item.tags) ? item.tags : null;
        if (got === null || got.length !== row.tags.length
            || got.some((t, i) => t !== row.tags[i])) {
          wrong.push({
            answer: a.q.id,
            about: `position ${row.seq}`,
            field: 'tags',
            held: row.tags,
            served: got,
          });
        }
      }
      continue;
    }

    if (a.q.kind === 'org') {
      const row = orgRows.get(`${a.q.org_id}|${a.q.day}`);
      if (!row) continue;
      checked += 1;
      if (Number(a.actors) !== row.actors) {
        wrong.push({
          answer: a.q.id,
          about: `${a.q.org_id} on ${a.q.day}`,
          field: 'actors',
          held: row.actors,
          served: a.actors,
        });
      }
      continue;
    }

    const row = tagRows.get(`${a.q.tag}|${a.q.day}`);
    if (!row) continue;
    checked += 1;
    if (String(a.newest_event_id ?? '') !== row.newest_event_id) {
      wrong.push({
        answer: a.q.id,
        about: `${a.q.tag} on ${a.q.day}`,
        field: 'newest_event_id',
        held: row.newest_event_id,
        served: a.newest_event_id,
      });
    }
  }

  return {
    pass: wrong.length === 0 && checked > 0,
    fields_checked: checked,
    wrong_count: wrong.length,
    wrong: wrong.slice(0, 6),
  };
}

/**
 * R8: the read path exposes the generation that is serving, in the order the
 * response contract fixes, honouring the caller's limit.
 *
 * Compared against the projection rows themselves rather than against the
 * model, so a generation that was folded wrongly fails R3, R4 or a coverage
 * rule for that and is judged here only on how it is served.
 */
export function readPathVerdict(answers) {
  const rows = v2FeedRows();
  const byUser = new Map();
  for (const row of rows) {
    const list = byUser.get(row.user_id) ?? [];
    list.push(row);
    byUser.set(row.user_id, list);
  }
  for (const [user, list] of byUser) {
    list.sort((a, b) => {
      const ta = Date.parse(a.occurred_at);
      const tb = Date.parse(b.occurred_at);
      return tb === ta ? b.seq - a.seq : tb - ta;
    });
    byUser.set(user, list);
  }

  const wrong = [];
  let checked = 0;
  for (const a of answers) {
    if (a.q.kind !== 'feed') continue;
    checked += 1;
    const want = (byUser.get(a.q.user_id) ?? []).slice(0, a.q.limit ?? 20);
    const got = a.items ?? [];
    const same = a.status === 200
      && got.length === want.length
      && want.every((w, i) => Number(got[i]?.seq) === Number(w.seq)
        && got[i]?.event_id === w.event_id
        && new Date(got[i]?.occurred_at ?? 0).getTime() === new Date(w.occurred_at).getTime());
    if (!same) {
      wrong.push({
        id: a.q.id,
        expected_seqs: want.slice(0, 6).map((w) => w.seq),
        got_seqs: got.slice(0, 6).map((g) => Number(g.seq)),
        expected_len: want.length,
        got_len: got.length,
      });
    }
  }

  const generations = [...new Set(answers.map((a) => a.generation))];
  return {
    pass: wrong.length === 0 && generations.length === 1 && generations[0] === 'v2',
    checked,
    wrong_count: wrong.length,
    wrong: wrong.slice(0, 6),
    generations_reported: generations,
  };
}

/**
 * R11: what a read is handed when the cutover lands between the moment it was
 * told which generation serves it and the moment it is answered.
 *
 * Two answers are right. The old generation as it stood when the reader was
 * pointed at it is right, because it was a whole and correct view of the log at
 * that moment. The serving generation's answer is right, because that is the
 * answer now. Which of the two a candidate produces is a design choice and
 * neither is preferred here.
 *
 * What is not right is a third thing, and there is only one way to get one:
 * being answered out of a generation that was taken away while the read was in
 * flight, which yields the rows that are left rather than the rows that were
 * there. Judged against readings taken from the store, so a projection that was
 * folded wrongly fails R3 or R4 for that and is judged here only on which
 * generation answered it.
 *
 * A list is judged by where its rows came from, not by how many came back or in
 * what order: a reader is free to sort and to cut its answer short, so the only
 * thing asked of a list is that it is not empty when both generations held rows,
 * and that everything in it stands in one of the generations that could rightly
 * have answered. A single number has nothing to sort or cut and is compared as
 * it stands.
 *
 * And every reader's question is asked once more at the end, with nothing in
 * flight and the cutover long over. A service that gets it wrong then is wrong
 * about something other than a cutover, and that reader drops out of this rule
 * rather than failing it: R7, R8 and the coverage rules own a read path that
 * cannot answer at rest.
 */

/** Enough of a list to see what happened, without a projection in the report. */
const brief = (value) => (Array.isArray(value)
  ? { rows: value.length, first: value.slice(0, 3), last: value.slice(-3) }
  : value);

const inOneOf = (got, accepted) =>
  got.length > 0
  && accepted.some(({ value }) => {
    const rows = new Set(value.map((v) => JSON.stringify(v)));
    return got.every((g) => rows.has(JSON.stringify(g)));
  });

const answersIt = (value, accepted) => (Array.isArray(value)
  ? inOneOf(value, accepted)
  : accepted.some((a) => JSON.stringify(a.value) === JSON.stringify(value)));

export function inFlightReadVerdict(reads) {
  const wrong = [];
  const unanswered = [];
  const cannotAnswer = [];

  for (const read of reads) {
    if (read.status === 0 || read.got === null) {
      // No answer at all is the harness losing a call, not the service
      // refusing one; the same treatment a dropped delivery gets.
      unanswered.push(read.id);
      continue;
    }
    if (read.settled === null || !answersIt(read.settled, read.accepted)) {
      // The same question is answered the same way with nothing in flight, so
      // whatever is wrong is not about the cutover. Another rule owns it.
      cannotAnswer.push(read.id);
      continue;
    }
    if (!answersIt(read.got, read.accepted)) {
      wrong.push({
        id: read.id,
        status: read.status,
        asked: read.asked,
        answered: read.answered,
        generation_reported: read.generation,
        got: brief(read.got),
        the_same_question_a_moment_later: brief(read.settled),
        would_have_been_right: read.accepted.map((a) => ({ [a.label]: brief(a.value) })),
      });
    }
  }

  return {
    pass: wrong.length === 0,
    reads_judged: reads.length - unanswered.length - cannotAnswer.length,
    unanswered,
    not_about_the_cutover: cannotAnswer,
    wrong_count: wrong.length,
    wrong: wrong.slice(0, 4),
  };
}

// -------------------------------------------------- routing atomicity ------

const CLIENT = /^\d+\.\d+ \[\d+ ([^\]]+)\] (.*)$/;
const ROUTE_KEYS = new Set(['proj:feed:active', 'proj:counts:active', 'proj:tags:active']);

function parseArgs(rest) {
  return [...rest.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1].replace(/\\(.)/g, '$1'));
}

/**
 * Replays what Redis was actually asked to do and reports whether the three
 * routing keys were ever left disagreeing between one atomic unit and the next.
 *
 * Reading the command stream rather than a client-library hook means the answer
 * does not depend on which library the candidate used, or on whether it used
 * one at all: MULTI/EXEC, a Lua script, MSET and three plain SETs are all
 * judged by the states they leave behind.
 */
export function routingAtomicityVerdict(lines) {
  const units = [];
  const openMulti = new Map();
  let luaUnit = null;

  for (const line of lines) {
    const m = CLIENT.exec(line);
    if (!m) continue;
    const [, client, rest] = m;
    const args = parseArgs(rest);
    if (args.length === 0) continue;
    const name = args[0].toLowerCase();

    if (client === 'lua') {
      if (luaUnit) luaUnit.push(args);
      continue;
    }
    luaUnit = null;

    if (name === 'multi') { openMulti.set(client, []); continue; }
    if (name === 'exec') {
      units.push(openMulti.get(client) ?? []);
      openMulti.delete(client);
      continue;
    }
    if (name === 'discard') { openMulti.delete(client); continue; }
    if (openMulti.has(client)) { openMulti.get(client).push(args); continue; }
    if (name === 'eval' || name === 'evalsha') {
      luaUnit = [];
      units.push(luaUnit);
      continue;
    }
    units.push([args]);
  }

  const state = new Map();
  let moved = false;
  const torn = [];

  for (const unit of units) {
    for (const args of unit) {
      const name = args[0].toLowerCase();
      if (name === 'set' && ROUTE_KEYS.has(args[1])) state.set(args[1], args[2]);
      else if (name === 'mset') {
        for (let i = 1; i + 1 < args.length; i += 2) {
          if (ROUTE_KEYS.has(args[i])) state.set(args[i], args[i + 1]);
        }
      }
    }
    const values = [...ROUTE_KEYS].map((k) => state.get(k) ?? 'v1');
    if (values.some((v) => v === 'v2')) moved = true;
    if (moved && new Set(values).size > 1) {
      torn.push(Object.fromEntries([...ROUTE_KEYS].map((k, i) => [k, values[i]])));
    }
  }

  return {
    pass: torn.length === 0,
    observed_units: units.length,
    routing_moved: moved,
    torn_states: torn.slice(0, 5),
  };
}

export function writeJSON(path, value) {
  writeFileSync(path, JSON.stringify(value, null, 2));
}
