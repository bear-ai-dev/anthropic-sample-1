#!/bin/bash
# Shared helpers for starting and driving the offline stack.

GEL_DSN_LOCAL="gel://admin:dev@localhost:5656/main"
GEL_DATA_DIR=/opt/geldata
API_PORT=3000
API_BASE="http://127.0.0.1:${API_PORT}"
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Written by the entrypoint once the fixture is in. See wait_for_setup.
SETUP_MARKER=/run/task/setup-complete

gelq() { gel query --tls-security insecure --dsn "$GEL_DSN_LOCAL" "$@"; }
gelj() { gel query --tls-security insecure --output-format json --dsn "$GEL_DSN_LOCAL" "$@"; }

# Clamp a readiness budget to READY_DEADLINE, when the caller has set one.
#
# A readiness wait must never outlive the timeout of whoever is driving it. Under
# the verifier that is task.toml's [verifier] timeout_sec, and overrunning it does
# not produce a late verdict -- the run is killed with no reward file, which Harbor
# reports as no score at all rather than as the harness failure it is. Under the
# entrypoint it is setup_timeout_sec, and the same applies to the fixture load.
#
# So the budgets below are ceilings on how long a wait MAY take, and this is the
# guarantee that the caller still has time left to say what happened. Callers with
# no deadline are unchanged.
clamp_budget() {
  local budget=$1 left
  if [ -n "${READY_DEADLINE:-}" ]; then
    left=$(( READY_DEADLINE - $(date +%s) ))
    [ "$left" -lt "$budget" ] && budget=$left
  fi
  [ "$budget" -lt 1 ] && budget=1
  echo "$budget"
}

# Wait for a condition by polling it. Never sleeps for a fixed total; returns
# as soon as the condition holds, and fails once the budget is spent.
# usage: wait_for <seconds> <label> <command...>
wait_for() {
  local budget=$1 label=$2; shift 2
  budget=$(clamp_budget "$budget")
  local deadline=$(( $(date +%s) + budget ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if "$@" >/dev/null 2>&1; then
      echo "[harness] $label ready after $(( budget - (deadline - $(date +%s)) ))s"
      return 0
    fi
    sleep 0.25
  done
  echo "[harness] TIMEOUT waiting for $label after ${budget}s" >&2
  return 1
}

# True while pid $1 exists and has not exited. A backgrounded child that exits
# stays a zombie until the shell reaps it, so `kill -0` still succeeds on it and
# cannot answer this question; the state field can. The comm field can contain
# spaces and parentheses, so cut from the LAST ')' rather than splitting on
# whitespace.
#
# An unreadable /proc entry counts as gone. That direction is deliberate: it ends
# the wait early and the caller reports a harness failure, which is excluded from
# a rate, rather than grading against a database that is not there.
proc_live() {
  local line state
  line=$(cat "/proc/$1/stat" 2>/dev/null) || return 1
  [ -n "$line" ] || return 1
  state=${line##*') '}; state=${state%% *}
  [ "$state" != Z ]
}

# True when some process is still serving our data directory, whoever started it.
# The pid we backgrounded is not the only possible answer -- a server that re-execs
# or one somebody restarted by hand keeps serving under a pid this shell never saw
# -- so the fast-fail in wait_for_gel asks this before concluding the database is
# gone. Erring towards "still running" is the safe direction: the worst it costs is
# the wait we would have had anyway.
#
# Matched on the data directory rather than the process name, because Gel runs as
# an interpreter and every pattern naming the server matches nothing at all; this
# is the same signal tests/matrix.sh keys on. Compared as a whole argv element, so
# a shell that merely mentions the path in its own command line -- this function's
# caller included -- cannot match itself.
gel_server_running() {
  local p pid a
  for p in /proc/[0-9]*; do
    pid=${p#/proc/}
    # Never match this shell, the subshell running the scan, or its parent. A
      # liveness check that can match its own caller can only ever answer yes.
    case $pid in "$$"|"${BASHPID:-0}"|"$PPID") continue ;; esac
    while IFS= read -r a; do
      [ "$a" = "--data-dir=$GEL_DATA_DIR" ] && return 0
    done < <(tr '\0' '\n' < "$p/cmdline" 2>/dev/null)
  done
  return 1
}

# Poll for the database, giving up early if the server process just started has
# gone away. Waiting out a ceiling for a server that has already exited is pure
# cost: it cannot become ready, and under a bounded verifier it spends time the
# grading still needs to write a verdict.
#
# This is a fast FAILURE and never a fast success. The only exit with status 0 is
# the database answering a query; a dead server returns non-zero exactly as a
# timeout does, and the caller gives up either way. Dropping the wait, or letting
# it proceed on the assumption that the database is probably up by now, would be
# a check that cannot fail.
wait_for_gel() {
  local budget=$1 srv=$2
  budget=$(clamp_budget "$budget")
  local deadline=$(( $(date +%s) + budget ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if gelq 'select 1' >/dev/null 2>&1; then
      echo "[harness] gel ready after $(( budget - (deadline - $(date +%s)) ))s"
      return 0
    fi
    if ! proc_live "$srv" && ! gel_server_running; then
      echo "[harness] gel-server exited after $(( budget - (deadline - $(date +%s)) ))s" >&2
      echo "[harness] without answering; see /var/log/task/gel.log" >&2
      return 1
    fi
    sleep 0.25
  done
  echo "[harness] TIMEOUT waiting for gel after ${budget}s" >&2
  return 1
}

start_gel() {
  if gelq 'select 1' >/dev/null 2>&1; then return 0; fi
  # The database server refuses to run as root and is launched through gosu, so
  # only root can start it. The container entrypoint does that before anyone
  # gets a shell, and it stays up for the life of the container. Said out loud
  # rather than failing on a permission error from four lines further down: a
  # step that cannot work has to announce it, or silence and success have the
  # same shape.
  if [ "$(id -u)" != 0 ]; then
    echo "[harness] gel is not answering, and starting it needs root; it is" >&2
    echo "[harness] owned by the container entrypoint. Nothing you can do here." >&2
    return 1
  fi
  mkdir -p /var/log/task
  # The compiler pool defaults to one worker per CPU, and each worker is a
  # separate interpreter holding the whole schema -- on a ten-core box that is
  # over two gigabytes of resident memory before a single query arrives, and the
  # kernel reaps the Postgres backend instead. Two workers are enough for a
  # single API process, and the server then fits in a sandbox rather than
  # dying in one; a dead backend reads as a broken candidate.
  # The backend connection ceiling is sized from *total* memory, not from what is
  # free, so on a shared box it reserves for a load that will never arrive and
  # spends the cold start building it -- seventy-eight slots on an eight-gigabyte
  # host with one API process attached.
  #
  # Sized from the widest thing the harness drives, and not one connection
  # tighter. Twelve was tried, on the arithmetic that the widest race presents
  # twelve callers: the server keeps slots back for its own system database, so
  # twelve callers could not all be served, the warm-up never settled, and the
  # verifier correctly reported a harness failure rather than a verdict -- a
  # tuning parameter turning into "no result", which is the shape of an
  # optimisation that costs a trial. Thirty-two leaves the boundary far away.
  gosu gel gel-server-7 \
    --data-dir="$GEL_DATA_DIR" \
    --security=insecure_dev_mode \
    --tls-cert-mode=generate_self_signed \
    --bind-address=127.0.0.1 \
    --port=5656 \
    --compiler-pool-size="${GEL_COMPILER_POOL:-2}" \
    --max-backend-connections="${GEL_MAX_BACKEND_CONNECTIONS:-32}" \
    >/var/log/task/gel.log 2>&1 &
  local srv=$!
  # Gel can take a long time on a cold data directory. Poll; do not sleep.
  #
    # The ceiling was 300s and that was too tight to be safe. A cold data directory
    # needs over two minutes here with nothing competing for the machine, so 300 was
    # about 2.3x the quiet-host cold start. What that costs is a submission which
    # scores 1.0 on a quiet host logging `TIMEOUT waiting for gel after 300s` and
    # returning a harness failure in place of a verdict.
  #
  # Raising it cannot move a score. This wait happens before any submission code
  # is exercised, and its only two outcomes are "the services are up, proceed" and
  # "give up"; a longer ceiling converts the second into the first and can do
  # nothing else. Waiting costs seconds, and a lost graded trial costs a rollout.
  # The real bound is READY_DEADLINE, which keeps this inside the verifier's own
  # timeout so a give_up is always still writable.
  wait_for_gel "${GEL_READY_BUDGET:-900}" "$srv"
}

start_redis() {
  if redis-cli ping >/dev/null 2>&1; then return 0; fi
  mkdir -p /var/log/task
  redis-server --port 6379 --bind 127.0.0.1 --save '' --appendonly no \
    >/var/log/task/redis.log 2>&1 &
  wait_for 60 "redis" redis-cli ping
}

# An empty database is still a database: every projection reads zero out of one
# without complaining, and a candidate graded against it looks merely quiet
# rather than broken. Count what is in the store instead of trusting that a
# reset ran.
db_populated() {
  local ev ri
  ev=$(gelj 'select count(Event)' 2>/dev/null | tr -dc '0-9')
  ri=$(gelj 'select count(ReceiptItem)' 2>/dev/null | tr -dc '0-9')
  [ "${ev:-0}" -ge 1 ] && [ "${ri:-0}" -ge "${FIXTURE_MIN_ITEMS:-15}" ]
}

# What the reset is supposed to have removed. Checked between the delete and
# the seed, because the seed inserts by exclusive key: anything the delete left
# behind comes back as a uniqueness violation on the first insert, which names
# the symptom and hides the cause.
db_leftovers() {
  local t n
  for t in Scan IdempotencyRecord ReceiptItem PersonaEvent Event EventTicket User; do
    n=$(gelj "select count($t)" 2>/dev/null | tr -dc '0-9')
    [ "${n:-0}" != "0" ] && echo "$t=$n"
  done
}

# A statement that lost a serialization race has not failed; it has been asked
# to try again. Gel runs each of these as its own serializable transaction, and
# the one documented caller that resets while the service is up --
# `scripts/smoke-scan`, which RUNBOOK.md tells the solver to run and which
# refuses to start unless the API is answering -- lost about one reset in five
# to `TransactionSerializationError: could not serialize access due to
# read/write dependencies among transactions`. reset_db reported that as "the
# reset statement itself failed" and the script reported it as "could not reload
# the fixture", and neither names anything the reader can act on.
#
# Retried here, at the statement, and only for that error: anything else still
# fails on the first attempt with its own message, because a retry loop that
# swallows every error is how a broken fixture comes to look slow instead of
# broken.
gel_retry() {
  local tries=${GEL_RETRY_TRIES:-6} attempt=1 out rc
  while :; do
    out=$(gelq "$@" 2>&1); rc=$?
    [ "$rc" = 0 ] && { printf '%s' "$out"; return 0; }
    case $out in
      *TransactionSerializationError*|*"could not serialize access"*|\
      *TransactionConflictError*|*TransactionDeadlockError*) ;;
      *) printf '%s\n' "$out" >&2; return "$rc" ;;
    esac
    if [ "$attempt" -ge "$tries" ]; then
      echo "[harness] $attempt serialization conflicts in a row; giving up" >&2
      printf '%s\n' "$out" >&2
      return "$rc"
    fi
    echo "[harness] serialization conflict (attempt $attempt); retrying" >&2
    attempt=$((attempt + 1))
    sleep 0.5
  done
}

reset_db() {
  # The leftovers check is inside the loop with the delete, not after it: a
  # service that inserted a row between the two is the same transient as a
  # conflict, and reporting "something else is writing to this database" on the
  # first occurrence names a permanent cause for a temporary condition.
  local attempt=1 tries=${RESET_TRIES:-4} left
  while :; do
    if ! gel_retry -f "$HARNESS_DIR/reset.edgeql" >/dev/null; then
      echo "[harness] the reset statement itself failed" >&2
      return 1
    fi
    left=$(db_leftovers)
    [ -z "$left" ] && break
    if [ "$attempt" -ge "$tries" ]; then
      echo "[harness] reset ran but left rows behind: $left" >&2
      echo "[harness] something else is writing to this database concurrently" >&2
      return 1
    fi
    echo "[harness] reset left rows behind ($left) on attempt $attempt; retrying" >&2
    attempt=$((attempt + 1))
    sleep 0.5
  done
  gel_retry -f "$HARNESS_DIR/seed.edgeql" >/dev/null || return 1
  if ! db_populated; then
    echo "[harness] seed ran but left an empty or short store" >&2
    return 1
  fi
}

# Block until the entrypoint says the box is assembled. Gel answers queries well
# before the fixture is loaded, so "the database is up" is not the same question
# as "the database is ready", and resetting it on the strength of the first
# answer races the seeding that is still in flight.
wait_for_setup() {
  [ -f "$SETUP_MARKER" ] && return 0
  wait_for "${SETUP_WAIT_BUDGET:-900}" "container setup" test -f "$SETUP_MARKER"
}

api_up() { curl -sf -o /dev/null "$API_BASE/"; }

# --- port ownership -------------------------------------------------------
# No ss, lsof or fuser in this image, so ask the kernel directly: find the
# listening socket's inode in /proc/net/tcp, then find whoever holds that inode
# as an open descriptor. This answers "who has the port" rather than "who did I
# fork", and those are different questions once a child lands in a new session.

_listen_inodes() {
  local hex; hex=$(printf '%04X' "${1:-$API_PORT}")
  awk -v h=":$hex" '$4=="0A" && $2 ~ h"$" {print $10}' \
      /proc/net/tcp /proc/net/tcp6 2>/dev/null | sort -u
}

port_busy() { [ -n "$(_listen_inodes "${1:-$API_PORT}")" ]; }

port_holders() {
  local inodes; inodes=$(_listen_inodes "${1:-$API_PORT}")
  [ -z "$inodes" ] && return 0
  local pid target ino
  for pid in $(ls /proc 2>/dev/null | grep -E '^[0-9]+$'); do
    for target in $(ls -l /proc/"$pid"/fd 2>/dev/null | grep -o 'socket:\[[0-9]*\]'); do
      ino=${target#socket:[}; ino=${ino%]}
      if echo "$inodes" | grep -qx "$ino"; then echo "$pid"; break; fi
    done
  done | sort -u
}

# Every descendant of a pid, collected in one pass before anything is
# signalled. Reaping a parent first orphans its children and they are then
# unreachable by tree, so ordering matters here.
proc_tree() {
  python3 - "$1" <<'PY'
import os, sys
root = int(sys.argv[1]); kids = {}
for d in os.listdir('/proc'):
    if not d.isdigit():
        continue
    try:
        st = open('/proc/%s/stat' % d).read()
        ppid = int(st[st.rindex(')') + 2:].split()[1])
    except Exception:
        continue
    kids.setdefault(ppid, []).append(int(d))
seen, stack = [], [root]
while stack:
    p = stack.pop()
    if p in seen:
        continue
    seen.append(p); stack.extend(kids.get(p, []))
print(' '.join(str(p) for p in seen))
PY
}

# The process answering on the port must be the binary this candidate just
# built. Comparing the inode behind /proc/<pid>/exe is what actually rules out
# a survivor from the previous run holding the port and answering in its place.
verify_api_binary() {
  local want holders got p
  want=$(stat -c '%d:%i' /workspace/bin/ExampleCo-backend 2>/dev/null) || return 1
  holders=$(port_holders "$API_PORT")
  if [ -z "$holders" ]; then
    echo "[harness] nothing is listening on $API_PORT" >&2; return 1
  fi
  for p in $holders; do
    got=$(stat -Lc '%d:%i' "/proc/$p/exe" 2>/dev/null)
    if [ "$got" != "$want" ]; then
      echo "[harness] pid $p on port $API_PORT is not this build ($got != $want)" >&2
      return 1
    fi
  done
  echo "[harness] api pid(s) $(echo $holders) verified as this build ($want)"
}

start_api() {
  mkdir -p /var/log/task
  # Refuse to start on a busy port. Binding would fail silently and every probe
  # after it would be answered by the survivor, which is the failure mode that
  # makes a wrong candidate look correct.
  if port_busy "$API_PORT"; then
    echo "[harness] refusing to start: port $API_PORT held by $(port_holders "$API_PORT")" >&2
    return 2
  fi
  : > /var/log/task/api.log
  ( cd /workspace && setsid ./bin/ExampleCo-backend >>/var/log/task/api.log 2>&1 & echo $! >/var/log/task/api.pid )
  wait_for "${API_READY_BUDGET:-120}" "api" api_up || return 1
  verify_api_binary
}

stop_api() {
  local victims="" root uniq
  # Collect the tree first, signal second.
  if [ -f /var/log/task/api.pid ]; then
    root=$(cat /var/log/task/api.pid 2>/dev/null)
    if [ -n "$root" ] && [ -d "/proc/$root" ]; then
      victims="$(proc_tree "$root")"
    fi
  fi
  # Then whoever actually holds the port, which need not be anything we forked.
  victims="$victims $(port_holders "$API_PORT")"
  # Then by exact executable name. Never -f: that pattern also matches the
  # shell running the pkill, which kills the runner and skips the restore.
  victims="$victims $(pgrep -x ExampleCo-backend 2>/dev/null | tr '\n' ' ')"
  uniq=$(echo $victims | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u)
  [ -n "$uniq" ] && kill -9 $uniq 2>/dev/null
  rm -f /var/log/task/api.pid
  # Assert the effect. "I sent a kill" is not "the process is gone", and the
  # socket is the only thing that settles it.
  local deadline=$(( $(date +%s) + 30 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    port_busy "$API_PORT" || return 0
    sleep 0.2
  done
  echo "[harness] port $API_PORT still held by $(port_holders "$API_PORT")" >&2
  return 1
}

# Build the service. Linking this binary is the single most memory-hungry step
# in the task, so debug info is dropped and compile parallelism is capped: on a
# busy host the linker is otherwise a candidate for the OOM killer, and a build
# that dies that way says nothing about the code.
build_api() {
  cd /workspace || return 1
  mkdir -p bin
  # A soft heap ceiling on the compiler and linker themselves. Without it the
  # Go GC sizes the heap against the whole machine, which on a container with a
  # limit means it grows past the limit and the kernel answers; with it the
  # build collects harder and finishes slower instead of dying.
  GOGC="${GOGC:-50}" GOMEMLIMIT="${GOMEMLIMIT:-768MiB}" \
  go build -p "${GO_BUILD_P:-2}" -tags timetzdata -ldflags='-s -w' \
     -o bin/ExampleCo-backend ./cmd/main
}

# True when a failed build log looks like the kernel killed the compiler or
# linker rather than the compiler rejecting the code.
build_was_killed() {
  grep -qE 'signal: killed|out of memory|cannot allocate memory|fatal error: runtime: out of memory' "$1"
}
