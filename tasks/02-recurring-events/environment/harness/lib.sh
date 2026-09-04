#!/bin/bash
# Shared helpers for starting and driving the offline stack.

GEL_DSN_LOCAL="gel://admin:dev@localhost:5656/main"

# Written by the entrypoint once the fixture is in. See wait_for_setup.
SETUP_MARKER=/run/task/setup-complete

API_PORT=3000
API_BASE="http://127.0.0.1:${API_PORT}"
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The instant the service reports as "now". Pinned so that a series created by
# a scenario has a start date the grader can predict, and so that two runs of
# the same candidate produce the same dates. It sits a few weeks before the
# March offset transitions the fixture is built around.
TASK_CLOCK_ISO="${TASK_CLOCK_ISO:-2026-02-10T12:00:00Z}"
export TASK_CLOCK_ISO

gelq() { gel query --tls-security insecure --dsn "$GEL_DSN_LOCAL" "$@"; }
gelj() { gel query --tls-security insecure --output-format json --dsn "$GEL_DSN_LOCAL" "$@"; }

# Wait for a condition by polling it. Never sleeps for a fixed total; returns as
# soon as the condition holds, and fails once the budget is spent.
# usage: wait_for <seconds> <label> <command...>
# Keep every readiness wait inside the deadline its driver is working to. Without this,
# raising a ceiling can push a run past [verifier] timeout_sec, and an overrun is not a
# late verdict -- the run is killed, no reward file is written, and the result is no score
# at all rather than the harness failure give_up would have recorded.
clamp_budget() {
  local budget=$1 left
  if [ -n "${READY_DEADLINE:-}" ]; then
    left=$(( READY_DEADLINE - $(date +%s) ))
    [ "$left" -lt "$budget" ] && budget=$left
  fi
  [ "$budget" -lt 1 ] && budget=1
  echo "$budget"
}

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

# The container assembles itself before anyone drives it, and grading must not
# start in the middle of that. Gel answers a query long before the fixture is
# loaded, so treating the first answer as the handover races the entrypoint's own
# seeding; the collision surfaces as a uniqueness violation on the seed, which
# reads like a broken fixture rather than a missed handover.
wait_for_setup() {
  [ -f "$SETUP_MARKER" ] && return 0
  wait_for "${SETUP_WAIT_BUDGET:-900}" "container setup" test -f "$SETUP_MARKER"
}

_gel_spawn() {
  mkdir -p /var/log/task
  gosu gel gel-server-7 \
    --data-dir=/opt/geldata \
    --security=insecure_dev_mode \
    --tls-cert-mode=generate_self_signed \
    --bind-address=127.0.0.1 \
    --port=5656 \
    >>"${1:-/var/log/task/gel.log}" 2>&1 &
}

# Bring the store up, and keep trying rather than reporting a trial that was
# never graded.
#
# The failure this is written against is not a cold start being slow: it is a
# server left half alive by an earlier run, or one the kernel took for memory on
# a loaded box. Either way the port is held, the replacement cannot bind, the
# wait runs out, and the trial ends with no verdict about the submission at all
# -- which is the worst outcome there is, because it looks exactly like a
# candidate that failed. So a server that is still not answering after its first
# budget is taken out and replaced. All of this happens before a single thing
# about the submission has been measured, so it cannot turn a wrong answer into
# a right one.
start_gel() {
  if gelq 'select 1' >/dev/null 2>&1; then return 0; fi
  # The store is the one thing here that genuinely needs root: Gel refuses to
  # run as root itself and is launched through gosu, which only root may call.
  # The container entrypoint does that before anyone gets a shell and it stays
  # up for the life of the container, so a solver reaching this has hit a wall
  # rather than a bug. Said out loud instead of failing on a permission error
  # from twenty lines down, where silence and success have the same shape.
  if [ "$(id -u)" != 0 ]; then
    echo "[harness] gel is not answering, and starting it needs root: the" >&2
    echo "[harness] server is launched through gosu by the container" >&2
    echo "[harness] entrypoint. Nothing you can do from this account." >&2
    return 1
  fi
  mkdir -p /var/log/task
  _gel_spawn /var/log/task/gel.log
  # Gel can take a long time on a cold data directory. Poll; do not sleep.
  if wait_for "${GEL_READY_BUDGET:-900}" "gel" gelq 'select 1'; then
    return 0
  fi

  local attempt
  for attempt in 1 2; do
    echo "[harness] gel is not answering; replacing it (attempt $attempt)" >&2
    pkill -f gel-server >/dev/null 2>&1
    sleep 2
    pkill -9 -f gel-server >/dev/null 2>&1
    pkill -9 -f 'gel-server-7' >/dev/null 2>&1
    sleep 3
    _gel_spawn /var/log/task/gel-revived.log
    if wait_for "${GEL_REVIVE_BUDGET:-900}" "gel" gelq 'select 1'; then
      return 0
    fi
  done
  return 1
}

start_redis() {
  if redis-cli ping >/dev/null 2>&1; then return 0; fi
  mkdir -p /var/log/task
  redis-server --port 6379 --bind 127.0.0.1 --save '' --appendonly no \
    >/var/log/task/redis.log 2>&1 &
  wait_for 60 "redis" redis-cli ping
}

# An empty database is still a database: every query answers zero out of zero
# without complaining, and a candidate graded against one looks merely quiet
# rather than ungraded. Count what the fixture is supposed to contain instead of
# trusting that the reset ran.
db_populated() {
  local series occ ri org
  series=$(gelj 'select count(EventSeries)' 2>/dev/null | tr -dc '0-9')
  occ=$(gelj 'select count(EventSeriesOccurrence)' 2>/dev/null | tr -dc '0-9')
  ri=$(gelj 'select count(ReceiptItem)' 2>/dev/null | tr -dc '0-9')
  org=$(gelj 'select count(Organization)' 2>/dev/null | tr -dc '0-9')
  [ "${series:-0}" -ge "${FIXTURE_MIN_SERIES:-5}" ] \
    && [ "${occ:-0}" -ge "${FIXTURE_MIN_OCCURRENCES:-23}" ] \
    && [ "${ri:-0}" -ge "${FIXTURE_MIN_RECEIPTS:-9}" ] \
    && [ "${org:-0}" -ge 1 ]
}

# The timezone column is the one piece of the fixture the whole task rests on.
# If the migration that adds it did not apply, every series reads as UTC, the
# daylight-saving rules become unprovable, and the run would look like a task
# whose rules are simply wrong. Check it separately and loudly.
fixture_has_timezones() {
  local zones
  zones=$(gelj 'select count(distinct EventSeriesRepeatConfig.timezone)' 2>/dev/null | tr -dc '0-9')
  [ "${zones:-0}" -ge 3 ]
}

reset_db() {
  gelq -f "$HARNESS_DIR/reset.edgeql" >/dev/null || return 1
  gelq -f "$HARNESS_DIR/seed.edgeql" >/dev/null || return 1
  if ! db_populated; then
    echo "[harness] reset left an empty or short store" >&2
    return 1
  fi
  if ! fixture_has_timezones; then
    echo "[harness] fixture carries fewer than three distinct timezones" >&2
    return 1
  fi
}

api_up() { curl -sf -o /dev/null "$API_BASE/"; }

# --- port ownership -------------------------------------------------------
# No ss, lsof or fuser in this image, so ask the kernel directly: find the
# listening socket's inode in /proc/net/tcp, then find whoever holds that inode
# as an open descriptor. This answers "who has the port" rather than "who did I
# fork", and those are different questions once a child lands in a new session.
#
# The descriptor half of that is not free. Reading /proc/<pid>/fd on another
# account's process is a ptrace-mode read, and the default docker capability set
# omits CAP_SYS_PTRACE (CapEff 00000000a80425fb), so root here gets Permission
# denied on every descriptor belonging to the solver's account. The scan then
# comes back empty -- and empty is indistinguishable from "nobody holds it",
# which is the one answer that must never be wrong, because teardown reads it as
# the port being clear.
#
# The socket table is not gated the same way: it carries the owning uid beside
# the inode, and anyone may read it. So a busy port with no visible holder is a
# question that can still be answered -- ask who owns the socket, then run the
# same scan again as them, where the ptrace check passes on identity instead of
# on capability.

_listen_inodes() {
  local hex; hex=$(printf '%04X' "${1:-$API_PORT}")
  awk -v h=":$hex" '$4=="0A" && $2 ~ h"$" {print $10}' \
      /proc/net/tcp /proc/net/tcp6 2>/dev/null | sort -u
}

# Field 8 of the same rows. The uid that opened the listening socket.
_listen_uids() {
  local hex; hex=$(printf '%04X' "${1:-$API_PORT}")
  awk -v h=":$hex" '$4=="0A" && $2 ~ h"$" {print $8}' \
      /proc/net/tcp /proc/net/tcp6 2>/dev/null | sort -u
}

# Naming the owning accounts, for the messages that have to be written when no
# pid can be produced. "Held by nothing I can name" is a report; "held by" with
# an empty tail is a bug report about the harness.
_listen_owners() {
  local uid name out=""
  for uid in $(_listen_uids "${1:-$API_PORT}"); do
    name=$(getent passwd "$uid" 2>/dev/null | cut -d: -f1)
    out="$out ${name:-?}(uid $uid)"
  done
  echo "${out# }"
}

port_busy() { [ -n "$(_listen_inodes "${1:-$API_PORT}")" ]; }

# The scan proper, kept standalone so it can be handed to another account
# verbatim with declare -f. Takes the inodes to look for on argv.
_holders_scan() {
  local inodes=$1 pid target ino
  for pid in $(ls /proc 2>/dev/null | grep -E '^[0-9]+$'); do
    for target in $(ls -l /proc/"$pid"/fd 2>/dev/null | grep -o 'socket:\[[0-9]*\]'); do
      ino=${target#socket:[}; ino=${ino%]}
      if echo "$inodes" | grep -qx "$ino"; then echo "$pid"; break; fi
    done
  done | sort -u
}

port_holders() {
  local port=${1:-$API_PORT} inodes found="" uid me name
  inodes=$(_listen_inodes "$port")
  [ -z "$inodes" ] && return 0
  found=$(_holders_scan "$inodes")
  if [ -n "$found" ]; then echo "$found"; return 0; fi

  # Busy, and nothing in our own view holds it. Retry from each owning account.
  me=$(id -u)
  if [ "$me" = 0 ] && command -v runuser >/dev/null 2>&1; then
    for uid in $(_listen_uids "$port"); do
      [ "$uid" = "$me" ] && continue
      name=$(getent passwd "$uid" 2>/dev/null | cut -d: -f1)
      [ -n "$name" ] || continue
      found="$found $(runuser -u "$name" -- bash -c \
        "$(declare -f _holders_scan); _holders_scan '$inodes'" 2>/dev/null)"
    done
    found=$(echo $found | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u)
    if [ -n "$found" ]; then echo "$found"; return 0; fi
  fi

  # Say so. A caller that cannot tell "free" from "unreadable" will act on the
  # wrong one, and the empty list on stdout says nothing about which this is.
  echo "[harness] port $port is held but no holder is visible from uid $me;" >&2
  echo "[harness] the socket belongs to $(_listen_owners "$port") and reading" >&2
  echo "[harness] another account's descriptors needs CAP_SYS_PTRACE, which" >&2
  echo "[harness] this container does not have." >&2
  return 0
}

# Every descendant of a pid, collected in one pass before anything is signalled.
# Reaping a parent first orphans its children and they are then unreachable by
# tree, so the order matters here.
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
# built. Comparing the inode behind /proc/<pid>/exe is what actually rules out a
# survivor from a previous run holding the port and answering in its place.
verify_api_binary() {
  local want holders got p
  want=$(stat -c '%d:%i' /workspace/bin/ExampleCo-backend 2>/dev/null) || return 1
  holders=$(port_holders "$API_PORT")
  if [ -z "$holders" ]; then
    if port_busy "$API_PORT"; then
      echo "[harness] port $API_PORT is held by $(_listen_owners "$API_PORT")," >&2
      echo "[harness] which this account cannot name, so the process answering" >&2
      echo "[harness] cannot be shown to be this build" >&2
    else
      echo "[harness] nothing is listening on $API_PORT" >&2
    fi
    return 1
  fi
  for p in $holders; do
    got=$(stat -Lc '%d:%i' "/proc/$p/exe" 2>/dev/null)
    if [ -z "$got" ]; then
      echo "[harness] pid $p on port $API_PORT runs as $(stat -c '%U' "/proc/$p" 2>/dev/null) and its executable is unreadable from here" >&2
      return 1
    fi
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
    local who; who=$(port_holders "$API_PORT" 2>/dev/null | tr '\n' ' ')
    echo "[harness] refusing to start: port $API_PORT held by ${who:-$(_listen_owners "$API_PORT")}" >&2
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
  # Then by exact executable name. Never -f: that pattern also matches the shell
  # running the pkill, which kills the runner and skips the restore.
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

  # Still held, and every pid we could name is gone, so what is left is a
  # process belonging to an account we cannot look into. Clearing the port is
  # worth more than precision here: the alternative is a trial that ends with no
  # verdict about the submission at all, which in a pass rate is
  # indistinguishable from a submission that was simply wrong.
  #
  # Only root does this, and only against accounts that are not root's own. The
  # id check is the whole safety argument: a solver who calls stop_api from
  # their own shell is not root, so they never reach this and cannot reap the
  # session they are typing into. Root's own processes -- this shell, the
  # runner, gel, redis -- are visible to the scan above and were already dealt
  # with by pid, so an account-wide signal is never aimed at uid 0.
  if [ "$(id -u)" = 0 ]; then
    local uid name reaped=""
    for uid in $(_listen_uids "$API_PORT"); do
      [ "$uid" = 0 ] && continue
      name=$(getent passwd "$uid" 2>/dev/null | cut -d: -f1)
      echo "[harness] port $API_PORT is still held by ${name:-uid $uid} and no" >&2
      echo "[harness] pid for it can be read; reaping that account." >&2
      pkill -9 -u "$uid" >/dev/null 2>&1
      reaped=1
    done
    if [ -n "$reaped" ]; then
      deadline=$(( $(date +%s) + 15 ))
      while [ "$(date +%s)" -lt "$deadline" ]; do
        port_busy "$API_PORT" || return 0
        sleep 0.2
      done
    fi
  fi

  local blame; blame=$(port_holders "$API_PORT" 2>/dev/null | tr '\n' ' ')
  echo "[harness] port $API_PORT still held by ${blame:-$(_listen_owners "$API_PORT")}" >&2
  return 1
}

# Build the service. Linking this binary is the single most memory-hungry step
# in the task, so debug info is dropped and compile parallelism is capped: on a
# busy host the linker is otherwise a candidate for the OOM killer, and a build
# that dies that way says nothing about the code.
#
# timetzdata matters more here than in most tasks: it embeds the zone database
# in the binary, so the recurrence rules do not depend on what the base image
# happens to have in /usr/share/zoneinfo.
build_api() {
  cd /workspace || return 1
  mkdir -p bin
  go build -p "${GO_BUILD_P:-2}" -tags timetzdata -ldflags='-s -w' \
     -o bin/ExampleCo-backend ./cmd/main
}

# True when a failed build log looks like the kernel killed the compiler or
# linker rather than the compiler rejecting the code.
build_was_killed() {
  grep -qE 'signal: killed|out of memory|cannot allocate memory|fatal error: runtime: out of memory' "$1"
}
