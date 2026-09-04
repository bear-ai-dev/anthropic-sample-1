#!/bin/bash
# Grading entry point. Runs with an empty environment, so everything it needs is
# established here rather than inherited.
#
# Reward is written to /logs/verifier/reward.json in every case, including the
# ones where this script itself gives up. That directory is the only one Harbor
# collects and reads the reward from; a reward written anywhere else is invisible
# to the harness and the trial fails with RewardFileNotFoundError, carrying no
# score even though grading ran to completion.

export PATH=/usr/local/go/bin:/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME=/root
export GOPATH=/go GOMODCACHE=/go/pkg/mod GOCACHE=/go/cache
export GOFLAGS=-mod=mod GOTOOLCHAIN=local GOPROXY=off
export GEL_DSN=gel://admin:dev@localhost:5656/main
export GEL_CLIENT_TLS_SECURITY=insecure
export REDIS_ENDPOINT=localhost:6379
export SKIP_AWS_SECRETS=true IS_TEST=true ABLY_SECRET= PORT=3000
# The recurrence rules must not depend on the process zone. Pinning it to UTC
# here means a candidate that reads time.Local instead of the series' zone is
# wrong in the fixture's zones rather than accidentally right in one of them.
export TZ=UTC

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REWARD_DIR=${REWARD_DIR:-/logs/verifier}
export REWARD_DIR
mkdir -p "$REWARD_DIR" /var/log/task

# Fail closed: if anything below dies without producing a verdict, this stands.
give_up() {
  echo "[test] harness failure: $1" >&2
  printf '{"reward": 0.0, "harness_failure": 1}\n' > "$REWARD_DIR/reward.json"
  printf '{"harness_failure": "%s"}\n' "$1" > "$REWARD_DIR/reward-detail.json"
  exit 0
}
printf '{"reward": 0.0, "harness_failure": 1}\n' > "$REWARD_DIR/reward.json"
printf '{"harness_failure": "test.sh exited before grading"}\n' > "$REWARD_DIR/reward-detail.json"

# === Bound every readiness wait by the verifier's own timeout ===
#
# The gel ceilings in lib.sh were 300s, which is a number that demonstrably loses a graded
# run -- the log reads `TIMEOUT waiting for gel after 300s` for a submission that scores
# 1.0 on an unloaded host. A cold data directory needs over two minutes here with nothing
# competing, so 300s was barely twice the cold start.
#
# Raising it cannot move a score. Every wait it bounds happens before a line of submission
# code is exercised, and each has exactly two outcomes: the services answer and grading
# proceeds against the same grader, fixture and reference as before, or they do not and
# this script gives up with {"reward": 0.0, "harness_failure": 1}, which is excluded from a
# rate rather than counted as a failure. The only newly available transition is a lost
# trial becoming a real grade.
#
# The clamp is what makes that argument hold. An unbounded raise could overrun
# [verifier] timeout_sec, and an overrun is worse than a tight ceiling: the run is killed
# with no reward file, so Harbor reports no score instead of a harness failure. Clamping
# keeps give_up reachable. timeout_sec is deliberately NOT raised -- that bounds submission
# code and would convert a killed run, which is excluded, into a counted 0.0.
VERIFIER_TIMEOUT_SEC=${VERIFIER_TIMEOUT_SEC:-2700}   # task.toml [verifier] timeout_sec
# Reserved for everything after the services answer: the fixture reset, the build, the api
# start and grader.py over 27 rules.
GRADING_RESERVE_SEC=${GRADING_RESERVE_SEC:-1200}
READY_DEADLINE=$(( $(date +%s) + VERIFIER_TIMEOUT_SEC - GRADING_RESERVE_SEC ))
export READY_DEADLINE

# Keep the graded tree beside the reward. Evidence, never an input to the
# verdict -- grading below drives the live workspace, not this copy.
#
# A replay stages this snapshot into a fresh sandbox, and looks for it at exactly
# `verifier/deliverable`. Without it the replay stages an untouched workspace,
# reports `missing_workspace` with a zero-byte diff, and returns
# INFRASTRUCTURE_FAILURE however good this grader is.
#
# Snapshot /workspace, not `/app`, which does not exist here. Every error here is
# swallowed, so a snapshot that exists and is empty is indistinguishable from a
# solver who changed nothing. Say so on stderr if it ever comes back empty.
echo "=== Snapshot the deliverable ==="
mkdir -p "$REWARD_DIR/deliverable"
tar -C /workspace --exclude=./.git --exclude=./vendor --exclude=./bin \
    --exclude='./*.test' -cf - . 2>/dev/null \
    | tar -C "$REWARD_DIR/deliverable" -xf - 2>/dev/null || true
[ -n "$(ls -A "$REWARD_DIR/deliverable" 2>/dev/null)" ] \
    || echo "[test] WARNING: deliverable snapshot is empty; a replay will be blind" >&2

source /opt/harness/lib.sh || give_up "harness library missing"

# The independent model is held out of the image entirely and travels with this
# script. It has to live under tests/: the harness uploads that directory and
# mounts it at /tests, so anything kept beside it under environment/ would be
# baked into the solver's own container instead.
VERIFIER_DATA=""
for cand in "$HERE/verifier-data" /tests/verifier-data; do
  if [ -f "$cand/recurrence_model.py" ]; then VERIFIER_DATA="$cand"; break; fi
done
[ -n "$VERIFIER_DATA" ] || give_up "independent recurrence model not found"
export VERIFIER_DATA

# The container assembles itself before anyone drives it, and grading must not
# start in the middle of that. Gel answers a query long before the fixture is
# loaded, so starting the reset on the strength of the first answer races the
# entrypoint's own seeding; the collision surfaces as a uniqueness violation on
# the seed, which reads like a broken fixture rather than a missed handover.
wait_for_setup || give_up "the container never finished its own setup"

start_gel   || give_up "gel did not become ready"
start_redis || give_up "redis did not become ready"

# Tear down before building and before touching the database. A survivor from a
# previous run holds the port and an open handle on the store, and it would
# answer every probe below in this candidate's place.
stop_api || give_up "port 3000 was still held after teardown"

# Build whatever is in the workspace now. A tree that does not compile cannot be
# graded on behaviour, and that is the solver's problem. A build the kernel
# killed is the opposite: nothing was learned about the code, so it is reported
# as a harness failure and not as a wrong answer.
build_attempt=0
until build_api > /var/log/task/build.log 2>&1; do
  build_attempt=$((build_attempt + 1))
  if build_was_killed /var/log/task/build.log; then
    if [ "$build_attempt" -lt 3 ]; then
      echo "[test] build killed (attempt $build_attempt); retrying single-threaded" >&2
      GO_BUILD_P=1
      export GO_BUILD_P
      continue
    fi
    give_up "build killed by the kernel $build_attempt times (out of memory)"
  fi
  echo "[test] workspace does not build" >&2
  printf '{"reward": 0.0}\n' > "$REWARD_DIR/reward.json"
  python3 - "$REWARD_DIR" <<'PY'
import json, sys
log = open('/var/log/task/build.log').read()[-4000:]
json.dump({"reward": 0.0, "failed_rules": ["R0-compiles"], "build_error": log},
          open(sys.argv[1] + "/reward-detail.json", "w"), indent=2)
PY
  exit 0
done

reset_db  || give_up "could not reset the database, or the reset left it empty"

# The graded subjects arrive now, from the tests tree, under identifiers that
# appear nowhere in the image. The sandbox carries the evidence a solver reads;
# this carries the series the rules drive. Applied after reset_db so that a
# candidate cannot have left anything of its own on them.
gel query --tls-security insecure --dsn "$GEL_DSN" \
     -f "$VERIFIER_DATA/seed-holdout.edgeql" >/dev/null \
  || give_up "the held-out subjects could not be loaded"
subjects=$(gel query --tls-security insecure --output-format json --dsn "$GEL_DSN" \
           "select count((select EventSeries filter .series_id like 'hs-%'))" \
           2>/dev/null | tr -dc '0-9')
[ "${subjects:-0}" -eq 6 ] \
  || give_up "expected six held-out subjects, store holds ${subjects:-0}"

start_api || give_up "service did not start, or the process holding the port is not this build"

# The grader has its own deadline and writes a harness failure if it passes it.
# This one is the outer bound: a grader that is stopped so hard it cannot write
# anything -- the kernel taking it for memory, say -- still has to leave a
# verdict behind, and the fail-closed file at the top of this script is it.
GRADER_WALL=${GRADER_WALL:-2400}
if command -v timeout >/dev/null 2>&1; then
  timeout -s KILL "$GRADER_WALL" python3 "$HERE/grader.py"
  rc=$?
else
  python3 "$HERE/grader.py"
  rc=$?
fi
[ "$rc" -eq 0 ] || echo "[test] grader exited $rc" >&2

cp /var/lib/task-data/journal/linear-calls.jsonl "$REWARD_DIR/linear-calls.jsonl" 2>/dev/null || true
cp /var/log/task/mocklinear.log "$REWARD_DIR/mocklinear.log" 2>/dev/null || true
if [ -f /var/log/task/mocklinear.pid ]; then
  kill "$(cat /var/log/task/mocklinear.pid)" 2>/dev/null || true
fi
pkill -f 'python3 -m mocklinear --scenario' 2>/dev/null || true

# Whatever happened above, what leaves this container has to be a number Harbor
# can read. A reward.json that is missing, truncated or not JSON is not a zero;
# it is an exception in the trial, and an exception carries no score at all.
python3 - "$REWARD_DIR" <<'PY' || give_up "the grader left no readable verdict"
import json, os, sys
path = os.path.join(sys.argv[1], "reward.json")
with open(path) as fh:
    body = json.load(fh)
if not isinstance(body.get("reward"), (int, float)):
    raise SystemExit(f"reward.json holds no numeric reward: {body!r}")
for key, value in body.items():
    if not isinstance(value, (int, float)):
        raise SystemExit(f"reward.json holds a non-number at {key!r}: {value!r}")
PY

echo "[test] reward: $(cat "$REWARD_DIR/reward.json")"
exit 0
