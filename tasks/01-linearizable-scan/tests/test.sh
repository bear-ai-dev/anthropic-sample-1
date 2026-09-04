#!/bin/bash
# Grading entry point. Runs with an empty environment, so everything it needs
# is established here rather than inherited.
#
# Reward is written to /logs/verifier/reward.json in every case, including the
# ones where this script itself gives up. That directory is the one Harbor
# collects and reads the reward from; a reward written anywhere else is invisible
# to the harness, and the trial fails with RewardFileNotFoundError and no score
# even though grading ran to completion.

export PATH=/usr/local/go/bin:/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME=/root
export GOPATH=/go GOMODCACHE=/go/pkg/mod GOCACHE=/go/cache
export GOFLAGS=-mod=mod GOTOOLCHAIN=local GOPROXY=off
export GEL_DSN=gel://admin:dev@localhost:5656/main
export GEL_CLIENT_TLS_SECURITY=insecure
export REDIS_ENDPOINT=localhost:6379
export SKIP_AWS_SECRETS=true IS_TEST=true ABLY_SECRET= PORT=3000

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REWARD_DIR=${REWARD_DIR:-/logs/verifier}
export REWARD_DIR
# Root-only, and asserted here rather than assumed from the image: whoever
# creates this directory first sets its mode, and if that was the harness with a
# default 0755 then the solver's account could read the verdict and the
# per-rule detail of the run being graded.
#
# `install -d` follows a symlink, so the claim below would land on the link's
# TARGET and leave the link itself alone. A link planted here pointing at
# /home/agent would apply root:root 0700 to the solver's own home directory,
# taking the solver's build cache away without closing the leak the hardening
# exists to close. Nothing legitimate puts a non-directory
# at this path, so anything found here is removed and the removal is announced:
# a step that quietly repairs an attack is indistinguishable from one that never
# had to.
if [ -L "$REWARD_DIR" ] || { [ -e "$REWARD_DIR" ] && [ ! -d "$REWARD_DIR" ]; }; then
  echo "[test] $REWARD_DIR was not a directory; removing it before claiming it" >&2
  ls -ld "$REWARD_DIR" >&2 || true
  rm -f "$REWARD_DIR"
fi
install -d -m 0700 -o root -g root "$REWARD_DIR"

# --- mocklinear: keep the consultation journal as evidence, then stop the daemon.
# Evidence only: nothing below is an input to the verdict.
echo "=== Linear workspace: keep the consultation journal, stop the daemon ==="
cp /var/lib/task-data/journal/linear-calls.jsonl "$REWARD_DIR/linear-calls.jsonl" 2>/dev/null || true
cp /tmp/task-infra/mocklinear.log "$REWARD_DIR/mocklinear.log" 2>/dev/null || true
echo "linear journal: $(wc -l < "$REWARD_DIR/linear-calls.jsonl" 2>/dev/null || echo 0) calls recorded"
if [ -f /tmp/task-infra/mocklinear.pid ]; then
    kill "$(cat /tmp/task-infra/mocklinear.pid)" 2>/dev/null
fi
pkill -f 'python3 -m mocklinear --scenario' 2>/dev/null
for _ in $(seq 1 40); do
    if python3 - <<'PY'
import socket
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("127.0.0.1", 4570))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
PY
    then break; fi
    pkill -9 -f 'python3 -m mocklinear --scenario' 2>/dev/null
    sleep 0.5
done

mkdir -p /var/log/task

# === Bound every readiness wait by the verifier's own timeout ===
#
# task.toml gives this run [verifier] timeout_sec. Overrunning it does not produce
# a late verdict: the run is killed, no reward file is written, and Harbor reports
# no score at all -- strictly less informative than the harness failure a give_up
# would have recorded. So the service waits below are clamped to leave time for
# the grading that has to follow them, and a verdict is always still writable.
#
# Raising a readiness ceiling cannot move a score. Every wait it bounds happens
# before a line of submission code is exercised, and each has exactly two
# outcomes: the service came up and grading proceeds, or it did not and this
# script gives up with {"reward": 0.0, "harness_failure": 1}, which is excluded
# from a rate rather than counted as a failure. A submission that would pass still
# passes and one that would fail still fails; the only thing that changes is that
# a trial which would have been LOST becomes a real grade.
VERIFIER_TIMEOUT_SEC=${VERIFIER_TIMEOUT_SEC:-1800}   # task.toml [verifier]
# Reserved for what happens once the services answer: the Go build plus up to two
# retries of one the kernel killed, the reset, the service start and the grader.
GRADING_RESERVE_SEC=${GRADING_RESERVE_SEC:-900}
READY_DEADLINE=$(( $(date +%s) + VERIFIER_TIMEOUT_SEC - GRADING_RESERVE_SEC ))
export READY_DEADLINE

# Fail closed: if anything below dies without producing a verdict, this stands.
give_up() {
  echo "[test] harness failure: $1" >&2
  printf '{"reward": 0.0, "harness_failure": 1}\n' > "$REWARD_DIR/reward.json"
  printf '{"harness_failure": "%s"}\n' "$1" > "$REWARD_DIR/reward-detail.json"
  exit 0
}
printf '{"reward": 0.0, "harness_failure": 1}\n' > "$REWARD_DIR/reward.json"
printf '{"harness_failure": "test.sh exited before grading"}\n' > "$REWARD_DIR/reward-detail.json"

# Assert the effect rather than the intent. `install -d` re-applies mode and
# ownership to a directory that already exists, but it cannot do so on a
# filesystem that does not enforce them, and a mount at /logs the image did not
# create can arrive as something other than root's. Checked after the fail-closed
# reward is in place, so a refusal here is still a reward Harbor can read rather
# than a missing file it reports as no score at all.
boundary=$(stat -c '%U:%G %a' "$REWARD_DIR" 2>/dev/null)
[ "$boundary" = "root:root 700" ] \
  || give_up "$REWARD_DIR is $boundary, wanted root:root 700"

WORKSPACE=${WORKSPACE:-/workspace}
export WORKSPACE

# === Snapshot the deliverable ===
#
# A replay stages the submitted tree into a fresh sandbox, and looks for that
# tree at exactly verifier/deliverable in the trial's artifacts. Nothing else
# produces it. When it is absent the replay does not say so plainly: it stages an
# untouched workspace, emits a zero-byte diff between two identical trees, and
# returns an infrastructure failure, at which point a submission that passed most
# of its rules is indistinguishable from one that changed nothing at all.
#
# Taken here, before the build writes a binary and before reset_db and the
# grader start moving things, so it records what was submitted rather than what
# grading left behind.
#
# This copy is evidence and is never read back. The grader drives the live
# service built from $WORKSPACE and queries the live store; nothing below
# consults this directory, because a tree the solver could write to must not be
# the tree that decides their score. A failure to snapshot is not a failure to
# grade, so it cannot stop the run.
echo "=== Snapshot the deliverable ==="
mkdir -p "$REWARD_DIR/deliverable"
tar -C "$WORKSPACE" \
    --exclude=./bin \
    --exclude=./.git \
    --exclude=./node_modules \
    --exclude=./vendor \
    --exclude=./gel/dbschema/migrations/.cache \
    -cf - . 2>/dev/null | tar -C "$REWARD_DIR/deliverable" -xf - 2>/dev/null || true
echo "[test] deliverable: $(find "$REWARD_DIR/deliverable" -type f 2>/dev/null | wc -l) files"

source /opt/harness/lib.sh || give_up "harness library missing"

# The independent model is held out of the image entirely and travels with this
# script, so the container the solver works in never contains it at all. It has
# to live under tests/: the harness uploads that directory and only that
# directory, mounting it at /tests, so anything kept beside it under
# environment/ is simply not there when this runs.
VERIFIER_DATA=""
for cand in "$HERE/verifier-data" /tests/verifier-data; do
  if [ -f "$cand/scan_model.py" ]; then VERIFIER_DATA="$cand"; break; fi
done
[ -n "$VERIFIER_DATA" ] || give_up "independent model not found"
export VERIFIER_DATA

# The container assembles itself before anyone drives it, and grading must not
# start in the middle of that. Gel answers a query long before the fixture is
# loaded, so starting the reset on the strength of the first answer races the
# entrypoint's own seeding; the collision surfaces as a uniqueness violation on
# the seed, which reads like a broken fixture rather than a missed handover.
wait_for_setup || give_up "the container never finished its own setup"

start_gel  || give_up "gel did not become ready"
start_redis || give_up "redis did not become ready"

# Tear down before building and before touching the database. A survivor from a
# previous run holds the port and an open handle on the store, and it would
# answer every probe below in this candidate's place.
stop_api || give_up "port 3000 was still held after teardown"

# Build whatever is in the workspace now. A tree that does not compile cannot
# be graded on behaviour, and that is the solver's problem, not the harness's.
# A build the kernel killed is the opposite: nothing was learned about the
# code, so it is reported as a harness failure and not as a wrong answer.
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
json.dump({"failed_rules": ["R0-compiles"], "build_error": log},
          open(sys.argv[1] + "/reward-detail.json", "w"), indent=2)
PY
  exit 0
done

reset_db || give_up "could not reset the database, or the reset left it empty"
start_api || give_up "service did not start, or the process holding the port is not this build"

python3 "$HERE/grader.py"

# The grader writes its own verdict; if it somehow did not, the fail-closed
# file written at the top is what survives.
echo "[test] reward: $(cat "$REWARD_DIR/reward.json")"
exit 0
