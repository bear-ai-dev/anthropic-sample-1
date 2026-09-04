#!/usr/bin/env bash
#
# Brings up the stores, then hands over to the grader.
#
# The reward split is written at the point of decision inside the grader, and
# swept here as a net. Every exit path below writes something, so a crash is
# reported rather than being silence.

set -uo pipefail

# Harbor collects /logs/verifier and reads the reward from there. A reward
# written anywhere else is invisible: grading runs, decides, exits 0, and the
# trial still fails with RewardFileNotFoundError carrying no score.
OUT_DIR="${OUT_DIR:-/logs/verifier}"
# Two halves, in two places, on purpose. The held-out data -- the canonical
# delivery log, the script of live deliveries, the independent model -- is baked
# into the image root-only, because a container with no network cannot fetch it
# later. The grader that reads it is not baked in at all: Harbor uploads tests/
# to /tests after the agent has stopped, so nothing the solver could read while
# working carries the questions it will be asked.
VERIFIER_DIR="${VERIFIER_DIR:-/opt/verifier}"
GRADER_DIR="${GRADER_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/grader}"
WORKSPACE="${WORKSPACE:-/app/event-feed}"
GEL_DSN="${GEL_DSN:-gel://admin:dev@localhost:5656/main}"
GEL_READY_SECONDS="${GEL_READY_SECONDS:-600}"
# Comfortably above the reference run and comfortably below [verifier]
# timeout_sec, so the margin belongs to us rather than to Harbor's killer.
GRADER_SECONDS="${GRADER_SECONDS:-1800}"

# Removed before it is created, not merely created. The agent's own log
# directory is its sibling and is writable by the agent for the whole of the
# run, so the account being graded can reach this path before the verifier does
# and leave a directory -- or a symlink to one -- already in place with modes of
# its choosing. Taking it away first means what follows applies to a directory
# this script made.
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR" || {
  echo "HARNESS FAILURE: cannot create $OUT_DIR; no verdict can be reported" >&2
  exit 1
}

# Root only, and said here rather than in the Dockerfile because /logs is where
# Harbor puts the agent's own transcript and the agent has to be able to write
# there; locking the parent locks that too. Everything written below is an
# answer key: the per-rule detail names the buckets a projection got wrong and
# the deliverable snapshot is the graded tree. The verifier runs as root after the agent has
# stopped, so nothing legitimate loses by this; an agent that could read it
# would have the whole rule set, and one that could write it would have the
# reward.
chmod 0700 "$OUT_DIR"
chown root:root "$OUT_DIR" 2>/dev/null || true

# Fail closed, and say which kind of closed. Until something decides, the file
# on disk says the harness did not reach a verdict -- not "the candidate scored
# nothing". Those are the same number and they are not the same claim, and the
# expensive direction is the one that looks like a clean zero: a broken grader
# reporting 0.0 is indistinguishable from a solver that failed.
# A real verdict overwrites this; anything else -- a crash here, the verifier
# timing out and being signalled, the box going away -- leaves the flag up.
UNDECIDED='{"reward": 0.0, "harness_failure": 1}'
printf '%s' "$UNDECIDED" > "$OUT_DIR/reward.json"
printf '{"harness_failure": "the verifier did not reach a verdict"}' > "$OUT_DIR/reward-detail.json"

# Keep the graded tree beside the reward. Evidence, never an input to the
# verdict -- the grader below reads $WORKSPACE, not this copy.
#
# A replay stages this snapshot into a fresh sandbox, and looks for it at exactly
# `verifier/deliverable`. Without it the replay stages an untouched workspace,
# reports `missing_workspace` with a zero-byte diff, and returns
# INFRASTRUCTURE_FAILURE however good the grader is.
echo "=== Snapshot the deliverable ==="
mkdir -p "$OUT_DIR/deliverable"
tar -C "$WORKSPACE" --exclude=./node_modules --exclude=./.git --exclude=./dist \
    --exclude=./gel/.gel -cf - . 2>/dev/null \
    | tar -C "$OUT_DIR/deliverable" -xf - 2>/dev/null || true

cp /var/lib/task-data/journal/github-calls.jsonl "$OUT_DIR/github-calls.jsonl" 2>/dev/null || true
cp /tmp/task-infra/mockgithub.log "$OUT_DIR/mockgithub.log" 2>/dev/null || true
if [ -f /tmp/task-infra/mockgithub.pid ]; then
  kill "$(cat /tmp/task-infra/mockgithub.pid)" 2>/dev/null || true
fi
pkill -f 'python3 -m mockgithub --scenario' 2>/dev/null || true

# The sweep runs on the way out however we leave, including on a signal, so
# there is no exit path that reports nothing. It only ever removes non-numbers
# and substitutes the marker for a file that cannot be read as a verdict; a
# verdict already written is left exactly as it was.
sweep() {
  node -e '
const fs = require("node:fs");
const p = process.argv[1];
const failed = { reward: 0.0, harness_failure: 1 };
let v;
try { v = JSON.parse(fs.readFileSync(p, "utf8")); } catch { v = null; }
if (v === null || typeof v !== "object" || Array.isArray(v)) {
  fs.writeFileSync(p, JSON.stringify(failed));
  process.exit(0);
}
const clean = {};
for (const [k, x] of Object.entries(v)) if (typeof x === "number" && Number.isFinite(x)) clean[k] = x;
fs.writeFileSync(p, JSON.stringify(typeof clean.reward === "number" ? clean : failed));
' "$OUT_DIR/reward.json" 2>/dev/null \
    || printf '%s' "$UNDECIDED" > "$OUT_DIR/reward.json"
  cat "$OUT_DIR/reward.json"
  echo
}
trap sweep EXIT
trap 'echo "HARNESS FAILURE: the verifier was signalled before it decided" >&2; exit 0' TERM INT

fail_harness() {
  echo "HARNESS FAILURE: $1" >&2
  printf '%s' "$UNDECIDED" > "$OUT_DIR/reward.json"
  printf '{"harness_failure": "%s"}' "${1//\"/\'}" > "$OUT_DIR/reward-detail.json"
  exit 0
}

# ------------------------------------------------------------------ Redis ---
if ! redis-cli ping >/dev/null 2>&1; then
  redis-server --daemonize yes --save '' --appendonly no --bind 127.0.0.1 --port 6379 \
    >"$OUT_DIR/redis.log" 2>&1
  for _ in $(seq 1 60); do
    redis-cli ping >/dev/null 2>&1 && break
    sleep 0.5
  done
fi
redis-cli ping >/dev/null 2>&1 || fail_harness "redis did not start"

# -------------------------------------------------------------------- Gel ---
# Startup is slow and variable, so this polls rather than sleeping, and the
# budget is deliberately far larger than any startup seen in practice.
if ! /usr/bin/gel query --tls-security insecure --dsn "$GEL_DSN" 'select 1' >/dev/null 2>&1; then
  nohup docker-entrypoint.sh server >"$OUT_DIR/gel.log" 2>&1 &
fi

ready=0
for _ in $(seq 1 "$GEL_READY_SECONDS"); do
  if /usr/bin/gel query --tls-security insecure --dsn "$GEL_DSN" 'select 1' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = 1 ] || fail_harness "gel did not answer within ${GEL_READY_SECONDS}s"

# ------------------------------------------------------------- migrations ---
# Whatever schema the workspace declares is what the candidate is graded on.
if [ -d "$WORKSPACE/gel/dbschema" ]; then
  ( cd "$WORKSPACE/gel" \
    && /usr/bin/gel migrate --tls-security insecure --dsn "$GEL_DSN" ) \
    >"$OUT_DIR/migrate.log" 2>&1 \
    || fail_harness "gel migrate failed; see migrate.log"
fi

/usr/bin/gel query --tls-security insecure --dsn "$GEL_DSN" 'select count(FeedByUserV2)' >/dev/null 2>&1 \
  || fail_harness "the projection schema is not present after migration"

if [ ! -d "$WORKSPACE/node_modules" ]; then
  fail_harness "the workspace has no installed dependencies"
fi

# ------------------------------------------------------------------- reap ---
# Anything the agent left listening is taken down before grading starts.
#
# A solver runs its service to see whether it works, and mini-swe-agent's shell
# survives the turn that started it, so arriving here with a server already on
# 8080 is the normal case, not the strange one -- and it is a case neither the
# oracle nor an untouched workspace ever produces, so nothing before a real
# rollout can find it. Left alone it is silently worse than a crash: the
# grader's own `npm start` loses the port and dies, /healthz answers anyway
# because the agent's process is still there, and the run grades a service
# nobody can see the state of, with the crash injection killing a pid that
# exited seconds after it was spawned.
for _ in 1 2 3; do
  pkill -f 'tsx .*src/server' 2>/dev/null
  pkill -f 'node .*src/server' 2>/dev/null
  pkill -f 'npm.* start' 2>/dev/null
  fuser -k -TERM 8080/tcp 2>/dev/null
  sleep 1
  fuser -s 8080/tcp 2>/dev/null || break
  fuser -k -KILL 8080/tcp 2>/dev/null
  sleep 1
done
if fuser -s 8080/tcp 2>/dev/null; then
  fail_harness "port 8080 is still held after the workspace's own processes were killed"
fi

[ -f "$GRADER_DIR/run.mjs" ] || fail_harness "the grader was not delivered to $GRADER_DIR"
[ -x "$VERIFIER_DIR/bin/projfold" ] || fail_harness "the model binary is missing from the image"
[ -f "$VERIFIER_DIR/truth/events_truth.jsonl" ] || fail_harness "the canonical log is missing from the image"

# ----------------------------------------------------------------- grader ---
# Run with an explicit, minimal environment so nothing the candidate left behind
# can reach it, and under a clock of our own.
#
# The clock is the point: [verifier] timeout_sec is enforced by killing this
# container, which leaves whatever is on disk as the answer and no way to say
# why. Stopping the grader ourselves, well inside that, means a candidate that
# wedges -- a step endpoint that never returns, a checkpoint nothing ever
# arrives at -- is reported as an undecided run rather than as a silence.
timeout --signal=TERM --kill-after=60 "$GRADER_SECONDS" \
  env -i \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/root \
    OUT_DIR="$OUT_DIR" \
    VERIFIER_DIR="$VERIFIER_DIR" \
    WORKSPACE="$WORKSPACE" \
    GEL_DSN="$GEL_DSN" \
    BASE_URL=http://127.0.0.1:8080 \
    node "$GRADER_DIR/run.mjs" 2>&1 | tee "$OUT_DIR/grader.log"

status="${PIPESTATUS[0]}"
case "$status" in
  124|137)
    fail_harness "the grader did not finish within ${GRADER_SECONDS}s and was stopped"
    ;;
esac

# The grader writes the split at the point of decision. Whatever is on disk now
# goes through the sweep in the EXIT trap, which is the only place that reports.
exit 0
