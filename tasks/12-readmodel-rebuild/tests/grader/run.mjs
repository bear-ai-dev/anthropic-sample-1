/**
 * Drives a candidate through a cutover and grades what happened.
 *
 * Every interesting moment is reached by arranging the world, never by waiting
 * and hoping: the gap between the snapshot and the live stream is made by
 * appending known positions between observable stages, and the cutover is
 * interrupted at the instant Redis applies the first routing command, not after
 * a delay.
 */

import { writeFileSync } from 'node:fs';
import {
  appExited, appIsDown, appPid, checkpointArrivals, checkpointTally, delay, disarmCheckpoint,
  gelScript, holdCheckpoint, http, killAtCheckpoint, redisCli, redisDel, redisGet,
  releaseCheckpoint, routingState, startApp, startMonitor, stopApp, waitForApp,
} from './lib.mjs';
import { SNAPSHOT_BOUNDARY, loadLiveScript, resetStores, seedPreservedLog, writeToLog } from './seed.mjs';
import {
  RULES, actorsVerdict, battery, bucketVerdict, canonFeed, counterAnswer, counterKeys,
  coverageVerdict, exposureVerdict, feedAnswer, feedUsers, foldedOnceVerdict,
  inFlightReadVerdict, logPositions, newestVerdict, readPathVerdict, routingAtomicityVerdict,
  storeState, v2Positions, writeJSON,
} from './rules.mjs';

const OUT_DIR = process.env.OUT_DIR ?? '/tmp/grade';
const APP_LOG = `${OUT_DIR}/app.log`;
const MAX_STEPS = 40;

const rules = Object.fromEntries(Object.keys(RULES).map((k) => [k, null]));
const detail = { rules: {}, timeline: [], notes: [], steps: [] };
let harnessFailure = null;
let monitor = null;

const note = (msg) => { detail.notes.push(msg); console.log(`  · ${msg}`); };
const mark = (name, value) => { detail.timeline.push({ at: new Date().toISOString(), name, value }); };

function record(id, verdict) {
  if (rules[id] !== null) return;
  rules[id] = verdict.pass ? 1 : 0;
  detail.rules[id] = { description: RULES[id], ...verdict };
  console.log(`  ${verdict.pass ? 'PASS' : 'FAIL'}  ${id}  ${RULES[id]}`);
}

const live = loadLiveScript();
const batchFor = (phase) => live.filter((r) => r.phase === phase);

// The cutover window is fed in two instalments: some deliveries arrive after the
// parity gate has passed but before routing moves, the rest while the cutover is
// held open. A rebuild that folds the log only when its own stages run, or that
// trusts a verdict the gate reached earlier, is behind by the first group before
// it has touched a routing key.
const afterGate = () => batchFor('switching').slice(0, 5);
const duringSwitch = () => batchFor('switching').slice(5);

const accepted = (res) => res !== null && (res.status === 200 || res.status === 201);

/**
 * Puts every delivery in `rows` into the log, and says how many landed.
 *
 * Not all of them arrive the same way. Most are offered to the public append
 * handler; the ones the script marks otherwise are written straight into the
 * log, which is what the producer's backfill path does and what `npm run seed`
 * does. A position that reached the log without any handler in the service
 * seeing it is still a position the serving generation has to hold.
 *
 * For the ones that go over HTTP: a delivery that comes back without an answer
 * has not been refused; on a busy box, with the cutover parked and the store
 * contended, it is the harness that failed to deliver. Grading that as a lost
 * position blames the candidate for the harness's own dropped call. So the same
 * delivery is offered again -- it carries the same identity, so a delivery that
 * did land and one that did not both come back the same way the second time.
 */
// Deliveries the service answered and turned away. A delivery that got no
// answer at all is not in here: that is the harness failing to deliver, not the
// service refusing, and the two must never be confused.
const refusals = [];

async function append(rows) {
  const direct = rows.filter((r) => r.via === 'log');
  if (direct.length > 0) {
    writeToLog(direct.map((r) => r.event));
    mark('written-to-log', { seqs: direct.map((r) => r.event.seq) });
  }

  let ok = direct.length;
  for (const row of rows.filter((r) => r.via !== 'log')) {
    let res = null;
    for (let attempt = 1; attempt <= 4 && !accepted(res); attempt += 1) {
      if (attempt > 1) await delay(500 * attempt);
      res = await http('/events', { method: 'POST', body: row.event, timeoutMs: 120_000 });
    }
    if (accepted(res)) ok += 1;
    else {
      note(`position ${row.event.seq} was never accepted (last answer: ${res?.status ?? 0})`);
      if (res !== null && res.status >= 400) {
        refusals.push({ seq: row.event.seq, status: res.status });
      }
    }
  }
  return ok;
}

// ------------------------------------------------ a read across the cutover ---
//
// Callers are parked at the instant they have been told which generation
// answers them, and let go once the cutover has happened and the old generation
// has been thrown away. What they were told was true when they were told it.
// The question is what they are handed at the end, and there are two right
// answers -- see `inFlightReadVerdict`.
//
// Reaching that instant needs a hold rather than a race, and the hold is
// released early if the candidate's own stages turn out to consult a routing
// key the same way: a rule that cannot be set up is not a rule the candidate
// failed, and it must never be a reason the run stalls.
const inFlight = {
  armed: false, released: false, releasedEarly: false,
  note: null, parked: 0, reads: [], pending: [],
};

const HOLD_LIMIT_MS = 90_000;
const FEED_LIMIT = 50;
let holdDeadline = Infinity;

function releaseReaders(early) {
  if (inFlight.released) return;
  inFlight.released = true;
  inFlight.releasedEarly = early;
  releaseCheckpoint('route_read');
}

/** Polled while a step is in flight, so a stage that parks here cannot wedge the run. */
function readerGuard() {
  if (inFlight.armed && !inFlight.released && Date.now() > holdDeadline) {
    releaseReaders(true);
    note('a stage of the rebuild parked where a reader parks; the readers were let go early');
  }
  return false;
}

async function parkReaders() {
  const routing = routingState();
  if (!routing.allV1) {
    inFlight.note = `routing already said ${routing.values.join(',')}; no read could straddle the cutover`;
    return;
  }

  // Keys both generations hold, so that a read answered out of a generation
  // that has been taken away cannot look like either right answer.
  //
  const tally = (table) => {
    const counts = new Map();
    for (const u of feedUsers(table)) counts.set(u, (counts.get(u) ?? 0) + 1);
    return counts;
  };
  const inV1 = tally('FeedByUserV1');
  const inV2 = tally('FeedByUserV2');
  const user = [...inV1.entries()]
    .filter(([u, n]) => n > 0 && (inV2.get(u) ?? 0) > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([u]) => u)[0];

  const bothHold = (v1Table, v2Table, field) => {
    const old = new Set(counterKeys(v1Table, field)
      .filter((r) => r.count > 0).map((r) => `${r.name}\u0000${r.day}`));
    return counterKeys(v2Table, field)
      .filter((r) => r.count > 0 && old.has(`${r.name}\u0000${r.day}`))
      .sort((a, b) => b.count - a.count)[0];
  };

  const shared = bothHold('CountByOrgV1', 'CountByOrgV2', 'org_id');
  const sharedTag = bothHold('RecentByTagV1', 'RecentByTagV2', 'tag');

  if (!user || !shared || !sharedTag) {
    inFlight.note = 'no key both generations hold; a lost read would be indistinguishable from a right one';
    return;
  }

  const baseline = checkpointTally('route_read');
  holdCheckpoint('route_read');

  inFlight.pending = [
    {
      id: 'feed-in-flight',
      path: `/feed?user_id=${encodeURIComponent(user)}&limit=${FEED_LIMIT}`,
      before: { old_generation_as_it_stood: feedAnswer('FeedByUserV1', user) },
      serving: () => feedAnswer('FeedByUserV2', user),
      answer: (body) => (Array.isArray(body?.items) ? canonFeed(body.items) : null),
    },
    {
      id: 'org-in-flight',
      path: `/counts/org?org_id=${encodeURIComponent(shared.name)}&day=${encodeURIComponent(shared.day)}`,
      before: { old_generation_as_it_stood: counterAnswer('CountByOrgV1', 'org_id', shared.name, shared.day) },
      serving: () => counterAnswer('CountByOrgV2', 'org_id', shared.name, shared.day),
      answer: (body) => (body?.count === undefined || body?.count === null ? null : Number(body.count)),
    },
    {
      id: 'tag-in-flight',
      path: `/counts/tag?tag=${encodeURIComponent(sharedTag.name)}&day=${encodeURIComponent(sharedTag.day)}`,
      before: { old_generation_as_it_stood: counterAnswer('RecentByTagV1', 'tag', sharedTag.name, sharedTag.day) },
      serving: () => counterAnswer('RecentByTagV2', 'tag', sharedTag.name, sharedTag.day),
      answer: (body) => (body?.count === undefined || body?.count === null ? null : Number(body.count)),
    },
  ];

  for (const p of inFlight.pending) {
    p.call = http(p.path, { timeoutMs: 300_000 }).catch(() => ({ status: 0, body: null }));
  }

  const deadline = Date.now() + 30_000;
  while (checkpointTally('route_read') < baseline + inFlight.pending.length && Date.now() < deadline) {
    await delay(50);
  }

  inFlight.armed = checkpointTally('route_read') > baseline;
  holdDeadline = Date.now() + HOLD_LIMIT_MS;
  mark('readers-parked', {
    arrivals: checkpointTally('route_read') - baseline,
    user,
    org: `${shared.name} ${shared.day}`,
    tag: `${sharedTag.name} ${sharedTag.day}`,
    detail: redisGet('test:cpd:route_read'),
  });

  if (!inFlight.armed) {
    inFlight.note = 'the read path never asked the routing key for a single generation through the shipped client';
    releaseReaders(false);
  } else {
    inFlight.parked = checkpointTally('route_read') - baseline;
    note(`${inFlight.parked} of ${inFlight.pending.length} reader(s) parked holding generation v1`);
  }
}

async function collectReaders() {
  releaseReaders(false);
  for (const p of inFlight.pending) {
    if (!p.call) continue;
    const atRelease = p.serving();
    const res = await p.call;

    // The same question again, with nothing in flight and the cutover long
    // over. A service that answers it wrongly now is wrong for a reason that
    // has nothing to do with a read straddling a cutover, and R7, R8 and the
    // coverage rules are the ones that own that. Only a reader whose answer
    // the service can produce correctly a moment later is judged here.
    const again = await http(p.path, { timeoutMs: 60_000 });

    inFlight.reads.push({
      id: p.id,
      status: res.status,
      asked: p.path,
      answered: JSON.stringify(res.body ?? null).slice(0, 300),
      generation: res.body?.generation ?? null,
      got: p.answer(res.body),
      settled: again.status === 200 ? p.answer(again.body) : null,
      accepted: [
        { label: Object.keys(p.before)[0], value: Object.values(p.before)[0] },
        { label: 'the generation serving when the reader was let go', value: atRelease },
        { label: 'the generation serving once the reader had answered', value: p.serving() },
      ],
    });
  }
}

const phaseOf = (body) => String(body?.phase ?? '');
const PAST_SNAPSHOT = new Set(['TAIL', 'PARITY', 'SWITCH', 'DRAIN', 'CLEANUP', 'COMPLETE']);

/**
 * Calls the step endpoint until `until` says to stop, or the budget runs out.
 *
 * `watch` is checked while a step is still in flight, which is the only way to
 * catch the rebuild parked at a checkpoint: the request that parked it will not
 * return until it is released, so waiting for the response first would mean
 * arriving after the moment of interest had passed.
 */
async function drive(until, watch = null, budget = MAX_STEPS) {
  const seen = [];
  let refused = 0;
  for (let i = 0; i < budget; i += 1) {
    if (watch?.()) return seen;
    if (await until(seen)) return seen;
    if (watch?.()) return seen;

    const t0 = Date.now();
    let settled = null;
    http('/admin/projections/rebuild/step', { method: 'POST', timeoutMs: 240_000 })
      .then((r) => { settled = r; }, () => { settled = { status: 0, body: null }; });

    while (settled === null) {
      if (watch?.()) return seen;
      await delay(60);
    }

    const step = { status: settled.status, phase: phaseOf(settled.body), ms: Date.now() - t0 };
    // Why a stage would not advance, kept so a run that stalls can be explained
    // rather than guessed at.
    if (settled.status >= 400 && settled.body?.error) {
      step.refused = String(settled.body.error).slice(0, 300);
    }
    seen.push(step);
    detail.steps.push(step);
    if (step.status === 501 || step.status === 0) return seen;
    // A stage that refuses to advance will go on refusing; there is no point
    // asking it forty times.
    refused = step.status === 409 ? refused + 1 : 0;
    if (refused >= 8) return seen;
    if (step.status === 409) await delay(50);
  }
  await until(seen);
  return seen;
}

// ------------------------------------------------------------------- run ---

async function main() {
  console.log('preparing stores');
  resetStores();
  const seeded = seedPreservedLog();
  note(`seeded ${seeded.positions} positions, ${seeded.orgRows} org rows, ${seeded.tagRows} tag rows`);

  monitor = startMonitor();

  console.log('starting the service');
  startApp(APP_LOG);
  const up = await waitForApp(180_000);
  if (up === 'foreign') {
    harnessFailure = 'port 8080 is held by a process this grader did not start';
    return;
  }
  if (!up) {
    harnessFailure = 'the service never answered /healthz';
    return;
  }

  const sanity = await ask('/feed?user_id=usr-001&limit=3');
  if (sanity.status !== 200 || !Array.isArray(sanity.body?.items) || sanity.body.items.length === 0) {
    harnessFailure = `the surviving read path did not answer: ${JSON.stringify(sanity.body).slice(0, 200)}`;
    return;
  }
  note(`baseline feed answers from generation ${sanity.body.generation}`);

  // ---- is anything implemented at all? -----------------------------------
  const probe = await http('/admin/projections/rebuild/step', { method: 'POST', timeoutMs: 60_000 });
  if (probe.status === 501) {
    note('the rebuild endpoint is unimplemented; there is nothing to grade beyond that');
    for (const id of Object.keys(rules)) record(id, { pass: false, reason: 'the rebuild is not implemented' });
    return;
  }
  mark('first-step', { status: probe.status, phase: phaseOf(probe.body) });

  // ---- build the new generation while the log grows underneath it ---------
  // Routing is pinned closed from here, so a cutover cannot happen unobserved.
  // The baseline discounts the writes the service makes at startup to give the
  // routing keys their initial value.
  const routeBaseline = checkpointArrivals('route_write');
  holdCheckpoint('route_write');

  let gapAppended = false;
  let r1Done = false;
  let gateAppended = false;
  const parked = () => checkpointArrivals('route_write') > routeBaseline;

  if (PAST_SNAPSHOT.has(phaseOf(probe.body))) {
    r1Done = true;
    const required = Array.from({ length: SNAPSHOT_BOUNDARY }, (_, i) => i + 1);
    record('R1', coverageVerdict(required, v2Positions(), logPositions()));
  }

  await drive(async (seen) => {
    const phase = seen.length ? seen[seen.length - 1].phase : '';

    // The snapshot must have materialised the whole boundary before the rebuild
    // is allowed to report itself past that stage.
    if (!r1Done && PAST_SNAPSHOT.has(phase)) {
      r1Done = true;
      const present = v2Positions();
      const required = Array.from({ length: SNAPSHOT_BOUNDARY }, (_, i) => i + 1);
      record('R1', coverageVerdict(required, present, logPositions()));
      mark('snapshot-observed', { phase, present: present.length });
    }

    // The gap that matters: positions arriving after the snapshot has fixed its
    // boundary and before the cutover.
    if (!gapAppended && (r1Done || storeState().v2 > 0)) {
      gapAppended = true;
      const during = await append(batchFor('during_snapshot'));
      const gap = await append(batchFor('gap'));
      note(`appended ${during + gap} live deliveries after the snapshot boundary was fixed`);
      mark('gap-appended', { during, gap, head: storeState().head });
    }

    // The gate has passed and the cutover has not happened yet. Anything that
    // arrives now has to be folded before routing may move.
    if (!gateAppended && phase === 'SWITCH') {
      gateAppended = true;
      const n = await append(afterGate());
      note(`appended ${n} deliveries after the parity gate passed`);
      mark('after-gate-appended', { n, head: storeState().head });
    }

    return false;
  }, parked);

  if (!gapAppended) {
    const n = (await append(batchFor('during_snapshot'))) + (await append(batchFor('gap')));
    note(`appended ${n} live deliveries (late)`);
    gapAppended = true;
  }
  if (!parked()) await drive(async () => false, parked, 15);
  if (!r1Done) note('no stage past the snapshot was ever reported; R1 falls back to the cutover reading');

  // ---- the instant before routing moves -----------------------------------
  let crashed = false;
  // Whether the cutover was ever caught in flight. Read from the flag rather
  // than from the checkpoint counter, which a restart resets: the counter after
  // a restart is about the new process and says nothing about what the old one
  // reached.
  let reachedCutover = false;

  if (parked()) {
    reachedCutover = true;
    mark('parked-at-cutover', { arrivals: checkpointArrivals('route_write') });

    const atPark = routingState();
    if (atPark.torn) {
      record('R5', {
        pass: false,
        reason: 'routing was already torn when the next routing command was taken',
        observed: atPark.values,
      });
    }

    const logNow = logPositions();
    const verdict = coverageVerdict(logNow, v2Positions(), logNow);
    record('R2', verdict);
    if (!r1Done) record('R1', verdict);

    // Positions that arrive while the cutover is in flight. This is the only
    // way to create them at a chosen point rather than by racing.
    const inflight = await append(duringSwitch());
    note(`appended ${inflight} deliveries while the cutover was parked`);
    mark('inflight-appended', { inflight, head: storeState().head });

    // Die before the routing command goes out, not after it. The caller is
    // parked at the point where it is about to move a key, so arming the fault
    // at the arrival that is parked and then letting it go kills it on the way
    // out. Routing is left where it was, and a rebuild that believed it was
    // committing a cutover comes back to find that nothing happened.
    const armAt = checkpointArrivals('route_write');
    killAtCheckpoint('route_write', armAt);
    mark('kill-armed', { armAt, pid: appPid(), fault: redisGet('test:fault:route_write') });
    releaseCheckpoint('route_write');

    crashed = await appIsDown(60_000);
    mark('crash-check', {
      crashed,
      exited: appExited(),
      write_arrivals: checkpointArrivals('route_write'),
      fault_key: redisGet('test:fault:route_write'),
    });
    disarmCheckpoint('route_write');

    if (crashed) {
      const afterCrash = routingState();
      mark('crashed-at-cutover', afterCrash.values);
      note(`routing after the crash: ${afterCrash.values.join(',')}`);
      if (afterCrash.torn) {
        record('R5', {
          pass: false,
          reason: 'the process died with the routing keys disagreeing',
          observed: afterCrash.values,
        });
      }
      stopApp();
      startApp(APP_LOG);
      const back = await waitForApp(180_000);
      if (back === 'foreign') {
        harnessFailure = 'after the crash, port 8080 was held by a process this grader did not start';
        return;
      }
      if (!back) {
        harnessFailure = 'the service did not come back after the cutover crash';
        return;
      }
      note('the service restarted after the crash');
    } else {
      note('the service survived the routing fault');
    }
  } else {
    note('the candidate never tried to move routing');
    const logNow = logPositions();
    record('R2', coverageVerdict(logNow, v2Positions(), logNow));
    if (!r1Done) record('R1', { pass: false, reason: 'no observable snapshot stage and no cutover' });
    if (!gateAppended) await append(afterGate());
    await append(duringSwitch());
  }

  const preCutoverHead = storeState().head;
  note(`the log stood at ${preCutoverHead} when the cutover committed`);

  if (reachedCutover) await parkReaders();

  // ---- finish the cutover, watching the old generation go -----------------
  holdCheckpoint('v1_remove');
  let r6Done = false;
  let v1WasRetired = false;

  const judgeRemoval = (reason) => {
    if (r6Done) return;
    r6Done = true;
    const required = logPositions().filter((s) => s <= preCutoverHead);
    record('R6', {
      ...coverageVerdict(required, v2Positions(), logPositions()),
      observed_at: reason,
      pre_cutover_head: preCutoverHead,
    });
    releaseCheckpoint('v1_remove');
  };

  // Held at the retirement statement, so the drain and the removal are two
  // separately observable events rather than one indivisible "cleanup".
  const atRemoval = () => readerGuard() || (!r6Done && checkpointArrivals('v1_remove') >= 1);

  // The producer's backfill path lands two positions from below the cutover
  // point straight in the log, after the cutover has committed and while the
  // rebuild is on its last stage. They are inside the window the cutover left
  // open and no handler in the service has seen them, so the only thing that
  // can put them in the serving generation is the rebuild's own last pass --
  // and it has to happen before the old generation is thrown away.
  let backfilled = false;

  await drive(async (seen) => {
    const phase = seen.length ? seen[seen.length - 1].phase : '';
    if (!backfilled && phase === 'CLEANUP') {
      backfilled = true;
      const n = await append(batchFor('backfill'));
      note(`backfilled ${n} position(s) below the cutover point`);
      mark('backfilled', { n, head: storeState().head, v2: storeState().v2 });
    }

    const state = storeState();
    if (state.v1 === 0) v1WasRetired = true;
    // Backstop for a candidate that empties v1 without going through the
    // instrumented client.
    if (!r6Done && state.v1 === 0) {
      judgeRemoval('generation v1 was already empty');
      return true;
    }
    return (seen.length ? seen[seen.length - 1].phase : '') === 'COMPLETE';
  }, atRemoval);

  if (atRemoval()) judgeRemoval('the statement that retires generation v1');
  releaseCheckpoint('v1_remove');
  await delay(500);

  await drive(async (seen) => {
    const state = storeState();
    if (state.v1 === 0) v1WasRetired = true;
    if (!r6Done && state.v1 === 0) judgeRemoval('generation v1 was emptied');
    return (seen.length ? seen[seen.length - 1].phase : '') === 'COMPLETE';
  }, readerGuard, 12);

  if (atRemoval()) judgeRemoval('the retirement statement, after release');
  if (storeState().v1 === 0) v1WasRetired = true;

  // The parked readers have now been through the cutover and the retirement.
  await collectReaders();
  record('R11', inFlight.reads.length === 0
    ? { pass: true, reason: inFlight.note ?? 'no read was in flight across the cutover' }
    : {
        ...inFlightReadVerdict(inFlight.reads),
        readers_parked: inFlight.parked,
        v1_was_retired_first: v1WasRetired,
        released_early: inFlight.releasedEarly,
      });

  if (!r6Done) {
    // Why it never got there matters to whoever reads this. A rebuild whose own
    // gate went on refusing has found a fault in its projections and stopped,
    // which is the machine working; the rule it failed is the one the gate was
    // complaining about, and this is the consequence.
    const refusals = detail.steps.filter((s) => s.refused);
    record('R6', {
      pass: false,
      reason: 'generation v1 was never retired',
      v1_rows_remaining: storeState().v1,
      last_phase_reached: detail.steps.length
        ? detail.steps[detail.steps.length - 1].phase : null,
      the_rebuild_last_refused_because: refusals.length
        ? refusals[refusals.length - 1].refused : null,
    });
  } else if (!v1WasRetired) {
    // The removal was seen but never actually landed.
    detail.rules.R6.v1_never_emptied = true;
    if (rules.R6 === 1) {
      rules.R6 = 0;
      detail.rules.R6.pass = false;
      detail.rules.R6.reason = 'the retirement was attempted but generation v1 was never emptied';
      console.log('  FAIL  R6  (retirement never landed)');
    }
  }

  // ---- life after the cutover --------------------------------------------
  const posted = await append(batchFor('post_switch'));
  note(`appended ${posted} deliveries after the cutover`);
  await drive(async (seen) => seen.length >= 2, null, 2);
  mark('post-switch-appended', { posted, head: storeState().head });

  record('R3', foldedOnceVerdict());
  record('R4', bucketVerdict());
  record('R12', actorsVerdict());
  record('R13', newestVerdict());

  // The rebuild is over. Whatever is serving has to be level with the log,
  // including everything that arrived after the cutover.
  const logAtEnd = logPositions();
  record('R9', coverageVerdict(logAtEnd, v2Positions(), logAtEnd));

  record('R10', refusals.length === 0
    ? { pass: true, refused: 0 }
    : {
        pass: false,
        reason: 'deliveries were turned away while the rebuild was in flight',
        refused: refusals.slice(0, 10),
      });

  const answers = await runBattery();
  // A candidate that never moved routing has already failed R2 and R6. Judging
  // the read path against a generation it never adopted, or the old
  // generation's influence when the old generation was never retired, would
  // add failures that are about the same one mistake.
  record('R8', routingState().allV2
    ? readPathVerdict(answers)
    : { pass: true, reason: 'routing never moved; the read path is R2 and R6\'s business' });
  record('R14', routingState().allV2
    ? exposureVerdict(answers)
    : { pass: true, reason: 'routing never moved; there is no new generation being served' });
  record('R7', v1WasRetired
    ? await v1IndependenceVerdict(answers)
    : { pass: true, reason: 'generation v1 was never retired; there is nothing to be independent of' });

  // ---- what did Redis actually see? ---------------------------------------
  await delay(300);
  const lines = [...monitor.lines];
  monitor.stop();
  monitor = null;
  const atomicity = routingAtomicityVerdict(lines);
  const finalRouting = routingState();
  if (rules.R5 === null) {
    record('R5', {
      ...atomicity,
      // Whether routing moved is R2's and R6's business. This rule is only
      // about whether anybody could ever have seen the three keys disagree.
      pass: atomicity.pass && !finalRouting.torn,
      crashed_mid_cutover: crashed,
      final_routing: finalRouting.values,
    });
  } else {
    detail.rules.R5.command_stream = atomicity;
  }

  // ---- and then the cache goes away ---------------------------------------
  //
  // Last, because it is the only step that touches the keyspace itself, and
  // everything judged from the command stream has been judged by now.
  record('R15', routingState().allV2 && v1WasRetired
    ? await cacheLossVerdict()
    : {
        pass: true,
        reason: 'the cutover did not complete; there is no serving generation to lose the note of',
      });
}

/**
 * R15: the service survives the cache being emptied under it.
 *
 * Redis on these boxes runs with no persistence file and has been restarted
 * under this service before. It is where routing is read from and where the
 * rebuild's working state is read from, and it is not where either of them
 * lives: a restarted cache comes back with no opinion about which generation is
 * serving, and no opinion is not the same answer as "the one that always did".
 * Once the old generation has been retired the difference between those two is
 * the difference between the answer and an empty table.
 *
 * Emptied rather than restarted, and with the fault channel left alone: the
 * effect on the service is identical, and restarting the process the harness is
 * driving would be a different test. Judged on three things, all of them
 * consequences a caller can see:
 *
 *   the reads still answer, out of the same generation, with the same answers
 *   a delivery arriving afterwards still reaches the serving generation
 *   the routing keys are back, and agree
 *
 * Lenient in the ways the other read rules are: only answers that were 200
 * before are required to be 200 after, and only the fields those answers
 * carried are compared.
 *
 * Both limbs are measured against the service as it stands a moment before the
 * cache goes, not against anything recorded earlier in the run. A read path
 * that was already answering out of the retired generation answers out of it
 * just as wrongly either side of the loss, and a fanout that had already
 * stopped following the log was not stopped by the cache: both are somebody
 * else's rule, and comparing against a stale baseline charges them here too.
 * So the battery is re-asked first, and the delivery limb is only judged at all
 * if the deliveries that arrived before the cache went had themselves arrived.
 */
async function cacheLossVerdict() {
  // The baseline, taken now. R7 plants a row in the old generation to see
  // whether anything still reads it; a candidate that does will answer
  // differently from the battery run before that probe, and that difference is
  // R7's finding, not this one's.
  const before = await runBattery();

  // Was the serving generation level with the log before any of this? If the
  // deliveries from the last batch never landed, the append path was already
  // not reaching it and the cache is not what broke it.
  const owedBefore = batchFor('post_switch').filter((r) => r.delivery === 1).map((r) => r.event.seq);
  const heldBefore = new Set(v2Positions());
  const missingBefore = owedBefore.filter((seq) => !heldBefore.has(seq));
  const deliveriesJudgeable = missingBefore.length === 0;

  const survivors = redisCli('keys', '*').split('\n').map((s) => s.trim()).filter(Boolean);
  const appKeys = survivors.filter((k) => !k.startsWith('test:'));
  for (const key of appKeys) redisDel(key);
  mark('cache-emptied', { removed: appKeys.sort(), kept: survivors.length - appKeys.length });
  note(`emptied the cache: ${appKeys.length} keys the service had put there are gone`);

  const after = await runBattery();
  const byId = new Map(after.map((a) => [a.q.id, a]));

  const wrong = [];
  let compared = 0;

  for (const was of before) {
    if (was.status !== 200) continue;
    const now = byId.get(was.q.id);
    compared += 1;

    if (!now || now.status !== 200) {
      wrong.push({
        answer: was.q.id,
        was: 'answered',
        now: `status ${now?.status ?? 0}`,
      });
      continue;
    }
    if (now.generation !== was.generation) {
      wrong.push({
        answer: was.q.id,
        field: 'generation',
        before: was.generation,
        after: now.generation,
      });
      continue;
    }
    if (was.q.kind === 'feed') {
      const a = (was.items ?? []).map((i) => Number(i.seq)).join(',');
      const b = (now.items ?? []).map((i) => Number(i.seq)).join(',');
      if (a !== b) wrong.push({ answer: was.q.id, field: 'items', before: a, after: b });
    } else if (Number(now.count) !== Number(was.count)) {
      wrong.push({
        answer: was.q.id, field: 'count', before: was.count, after: now.count,
      });
    }
  }

  // A delivery that arrives now still has to reach whatever is serving. The
  // routing note and the note saying a rebuild is in progress were in the same
  // cache, and the append path reads the second one to decide where a delivery
  // goes.
  // No stage is driven here. The cutover is over; in the world this is a model
  // of, nobody is running the rebuild any more, and the append path is the only
  // thing left that puts a delivery into the serving generation. Waited on
  // rather than read once, because nothing says the fold has to be finished by
  // the time the append is answered.
  const batch = batchFor('after_cache_loss');
  const landed = await append(batch);

  const owed = batch.filter((r) => r.delivery === 1).map((r) => r.event.seq);
  let dropped = owed;
  for (let waited = 0; waited < 20 && dropped.length > 0; waited += 1) {
    await delay(1_000);
    const held = new Set(v2Positions());
    dropped = owed.filter((seq) => !held.has(seq));
  }

  const routing = routingState();

  return {
    pass: wrong.length === 0
      && (!deliveriesJudgeable || dropped.length === 0)
      && routing.allV2 && !routing.torn,
    keys_removed: appKeys.length,
    answers_compared: compared,
    answers_that_changed: wrong.length,
    changed: wrong.slice(0, 6),
    deliveries_after_the_cache_went: owed.length,
    deliveries_accepted: landed,
    deliveries_that_never_reached_the_serving_generation: dropped.slice(0, 8),
    // If deliveries were not reaching the serving generation before the cache
    // went either, this limb says nothing about the cache. R9 is where that
    // failure belongs and it has already been recorded there.
    deliveries_were_landing_before_the_cache_went: deliveriesJudgeable,
    deliveries_already_missing_before: missingBefore.slice(0, 8),
    routing_after: routing.values,
  };
}

// ------------------------------------------------------------- batteries ---

/**
 * Asks one battery question, and does not mistake a dropped answer for a wrong
 * one.
 *
 * A single read that came back empty used to be graded as the read path being
 * wrong: the same query, once, returning nothing with no generation on it, which
 * is what a momentary failure looks like rather than a wrong implementation.
 * Under load on a shared box that fails correct work, which is the expensive
 * direction because it looks exactly like difficulty.
 *
 * A read path that is genuinely broken answers the same way every time, so
 * asking again costs a wrong submission nothing. What comes back after the last
 * attempt is what gets graded, and the attempts are recorded either way.
 */
async function ask(path) {
  let res = null;
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    if (attempt > 1) await delay(300 * attempt);
    res = await http(path, { timeoutMs: 30_000 });
    if (res.status === 200 && res.body && typeof res.body === 'object') {
      return { ...res, attempts: attempt };
    }
  }
  note(`the read path never answered ${path} (last status ${res?.status ?? 0})`);
  return { ...res, attempts: 4 };
}

async function runBattery() {
  const out = [];
  for (const q of battery()) {
    if (q.kind === 'feed') {
      const res = await ask(`/feed?user_id=${encodeURIComponent(q.user_id)}&limit=${q.limit}`);
      out.push({ q, status: res.status, attempts: res.attempts, generation: res.body?.generation, items: res.body?.items ?? null });
    } else if (q.kind === 'org') {
      const res = await ask(`/counts/org?org_id=${encodeURIComponent(q.org_id)}&day=${q.day}`);
      out.push({
        q, status: res.status, attempts: res.attempts, generation: res.body?.generation,
        count: res.body?.count ?? null, actors: res.body?.actors ?? null,
      });
    } else {
      const res = await ask(`/counts/tag?tag=${encodeURIComponent(q.tag)}&day=${q.day}`);
      out.push({
        q, status: res.status, attempts: res.attempts, generation: res.body?.generation,
        count: res.body?.count ?? null, newest_event_id: res.body?.newest_event_id ?? null,
      });
    }
  }
  return out;
}

/**
 * R7: the old generation has been retired, so its tables mean nothing. Fill them
 * with nonsense — including keys the new generation has no row for, which is the
 * only way a quiet fallback shows itself — and see whether any answer moves.
 */
async function v1IndependenceVerdict(before) {
  const poison = [
    ...battery().filter((q) => q.kind === 'org').map((q) => ({ t: 'CountByOrgV1', a: 'org_id', n: q.org_id, d: q.day })),
    ...battery().filter((q) => q.kind === 'tag').map((q) => ({ t: 'RecentByTagV1', a: 'tag', n: q.tag, d: q.day })),
    { t: 'CountByOrgV1', a: 'org_id', n: 'org-1', d: '1999-01-01' },
    { t: 'RecentByTagV1', a: 'tag', n: 'tag-0', d: '1999-01-01' },
  ];

  const statements = poison.map(({ t, a, n, d }, i) => `
insert ${t} { ${a} := ${JSON.stringify(n)}, day_bucket := ${JSON.stringify(d)}, count := ${424000 + i} }
unless conflict on ((.${a}, .day_bucket))
else (update ${t} set { count := ${424000 + i} });`).join('\n');

  const feedPoison = [1, 2, 3].map((i) => `
insert FeedByUserV1 {
  user_id := "usr-001", seq := ${800000 + i}, event_id := "evt-poison",
  occurred_at := <datetime>"2099-01-0${i}T00:00:00Z"
} unless conflict on (.seq) else (select FeedByUserV1);`).join('\n');

  gelScript(`${statements}\n${feedPoison}`);

  const after = await runBattery();
  const changed = [];
  for (let i = 0; i < before.length; i += 1) {
    const a = before[i];
    const b = after[i];
    const same = a.q.kind === 'feed'
      ? JSON.stringify(a.items) === JSON.stringify(b.items)
      : Number(a.count) === Number(b.count);
    if (!same) changed.push({ id: a.q.id, before: a.count ?? a.items?.length, after: b.count ?? b.items?.length });
  }

  const absentOrg = await ask('/counts/org?org_id=org-1&day=1999-01-01');
  const absentTag = await ask('/counts/tag?tag=tag-0&day=1999-01-01');
  const leaked = Number(absentOrg.body?.count ?? 0) !== 0 || Number(absentTag.body?.count ?? 0) !== 0;

  return {
    pass: changed.length === 0 && !leaked,
    poisoned_rows: poison.length + 3,
    changed_answers: changed.slice(0, 8),
    changed_count: changed.length,
    fallback_leak: leaked,
    absent_key_answers: [Number(absentOrg.body?.count ?? -1), Number(absentTag.body?.count ?? -1)],
  };
}

// ------------------------------------------------------------------ exit ---

try {
  await main();
} catch (err) {
  harnessFailure = harnessFailure ?? `grader threw: ${String(err).slice(0, 500)}`;
  detail.error = String(err?.stack ?? err).slice(0, 2000);
} finally {
  // Anything still parked has to be let go before the service is taken down,
  // or a run that failed early leaves a reader waiting on a checkpoint that
  // nobody is coming back to.
  try { releaseReaders(true); } catch { /* redis is already gone */ }
  try { stopApp(); } catch { /* nothing to stop */ }
  try { monitor?.stop(); } catch { /* already stopped */ }
}

const values = Object.values(rules);
const graded = values.every((v) => v !== null);
const reward = graded && values.every((v) => v === 1) ? 1 : 0;

detail.rule_results = rules;
detail.harness_failure = harnessFailure;
detail.reward = harnessFailure ? null : reward;

if (harnessFailure) {
  // The flag and a reward together. A harness failure is not a wrong answer,
  // and the flag is what says so downstream, but a file with no reward in it is
  // a second failure stacked on the first and it hides the first.
  writeFileSync(`${OUT_DIR}/reward.json`, JSON.stringify({ reward: 0.0, harness_failure: 1 }));
  console.log(`\nHARNESS FAILURE: ${harnessFailure}`);
} else {
  writeFileSync(`${OUT_DIR}/reward.json`, JSON.stringify({ reward }));
  console.log(`\nreward ${reward}   (${values.filter((v) => v === 1).length}/${values.length} rules)`);
}
writeJSON(`${OUT_DIR}/reward-detail.json`, detail);
