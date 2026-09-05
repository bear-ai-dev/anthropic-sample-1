#!/usr/bin/env bash
# Grade one submission.
#
# Runs as root inside the shipped container. Puts the graded ledger in place,
# builds whatever is in /app as the account that owns it, drives it through its
# own endpoints, and hands what happened to an independent model. The model
# decides; nothing here does.
set -uo pipefail

VERIFIER=/var/lib/task-data/verifier
RUN=/var/lib/task-data/run
# Harbor collects /logs/verifier and reads the reward from there. Writing it
# anywhere else is invisible to the harness: the grader runs, decides, exits 0,
# and the trial still fails with RewardFileNotFoundError and no score -- which
# looks like a broken task rather than a misfiled result.
OUT_DIR=${REWARD_DIR:-/logs/verifier}
REWARD_FILE="$OUT_DIR/reward.json"
DETAIL_FILE="$OUT_DIR/reward-detail.json"
LOG="$RUN/verify.log"

# The reward directory is the verifier's, not the workspace's. Harbor collects
# it as root, the solving account has no business listing it, and a run that
# plants a reward and then arranges for the grader to die must not leave a file
# of its own standing here. `mkdir -p` leaves 0755 under the default umask and
# an audit found exactly that, with reward.json at 0644 -- both readable from
# the agent account. Nothing was exploited: the grade is written after submit.
# This is the layer that has to hold when that stops being true.
#
# Ownership matters as much as mode. A directory the agent created and root
# then chmods to 0700 is still the agent's, and 0700 on an agent-owned
# directory denies the agent nothing. So anything here that is not root's, and
# any symlink standing in for it, is removed rather than adjusted.
#
# The mode is set on the directory and on the two files by hand rather than
# through a umask: the storage service's socket is created further down this
# script and the service that has to connect to it runs as the agent, so a
# umask here would close the graded run's own data path.
if [ -L "$OUT_DIR" ] || { [ -e "$OUT_DIR" ] && [ "$(stat -c %u "$OUT_DIR" 2>/dev/null)" != "0" ]; }; then
    rm -rf "$OUT_DIR"
fi
rm -rf "$RUN"
mkdir -p "$RUN" "$OUT_DIR"
chmod 700 "$RUN"
chown root:root "$OUT_DIR" 2>/dev/null
chmod 700 "$OUT_DIR"
# Removed and remade rather than truncated, so a planted file's mode and owner
# cannot survive into the run. Every later write is a truncation of these two,
# which keeps 0600.
rm -f "$REWARD_FILE" "$DETAIL_FILE"
: > "$REWARD_FILE"
: > "$DETAIL_FILE"
chmod 600 "$REWARD_FILE" "$DETAIL_FILE"
: > "$LOG"

say() { printf 'verify: %s\n' "$*" | tee -a "$LOG" >&2; }

# Every exit goes through here, so the numbers-only split holds on the failure
# paths too and not just the happy one.
emit() {
    local reward="$1" detail="$2"
    if [ "$reward" = "harness_failure" ]; then
        # Carry a reward as well as the flag. A harness failure is not a wrong
        # answer, but a file with no reward at all is a second failure mode on
        # top of the first, and the flag is what distinguishes them downstream.
        printf '{"reward": 0.0, "harness_failure": 1}\n' > "$REWARD_FILE"
    else
        printf '{"reward": %s}\n' "$reward" > "$REWARD_FILE"
    fi
    python3 - "$DETAIL_FILE" "$detail" "$RUN" <<'PY'
import json, re, sys, os
out, note, run = sys.argv[1], sys.argv[2], sys.argv[3]
detail = {"note": note}


def read(name):
    try:
        with open(os.path.join(run, name)) as handle:
            return json.load(handle)
    except Exception:
        return None


verdict = read("verdict.json")
if verdict:
    detail["verdict"] = verdict
        # The rules that did not hold, named once each and without the scenario
        # they failed in. The verdict records "cutover/R13", which says where a
        # rule broke; a flat list is what a reader asking which rule broke can
        # use, where a nested per-scenario structure is not. Entries like
        # "cutover/absent" are not rules and are left out.
    detail["failed_rules"] = sorted({
        rule for rule in
        (entry.rsplit("/", 1)[-1] for entry in verdict.get("failed", []))
        if re.fullmatch(r"R\d+", rule)
    })
obs = read("observations.json")
if obs:
    detail["seam"] = obs.get("seam")
    if obs.get("harness_failure"):
        detail["driver_harness_failure"] = obs["harness_failure"]
    for name, one in sorted((obs.get("scenarios") or {}).items()):
        detail[f"scenario_{name}"] = {
            "notes": one.get("notes", []),
            "faults_fired": one.get("faults_fired", {}),
            "restarts": one.get("restarts", []),
            "advance_calls": one.get("advance_calls"),
            "injected": {
                key: one.get(key)
                for key in ("divergence_injected", "extra_injected", "duplicate_injected",
                            "window_injected", "late_injected")
            },
        }
try:
    with open(os.path.join(run, "verify.log")) as handle:
        detail["log_tail"] = handle.read()[-4000:]
except Exception:
    pass
with open(out, "w") as handle:
    json.dump(detail, handle, indent=2, sort_keys=True)
PY
    say "$detail"
    say "reward: $reward"
    exit 0
}

fail_with()      { emit 0.0 "$1"; }
harness_failure() { emit harness_failure "$1"; }

# Fail closed from the first line.
printf '{"reward": 0.0}\n' > "$REWARD_FILE"

[ "$(id -u)" = "0" ] || harness_failure "the verifier must run as root"
[ -d "$VERIFIER" ] || harness_failure "the held-out material is missing"
[ -d /app ] || harness_failure "there is no workspace to grade"

# ------------------------------------------------------ the deliverable, kept
#
# A replay stages the submitted tree into a fresh sandbox, and finds that tree in
# the trial's artifacts at exactly `verifier/deliverable`. Nothing produces it
# for us. Without it the replay stages a pristine workspace, records
# `missing_workspace`, produces a zero-byte `agent-changes.diff` with baseline
# and final pointing at identical trees, and the submission has to be
# reconstructed from the trajectory instead.
#
# Taken before anything below touches /app, and it is evidence and never an
# input: every check after this reads the live workspace.
say "snapshotting the deliverable"
mkdir -p "$OUT_DIR/deliverable"
tar -C /app --exclude=./.git --exclude=./data --exclude=./membershipd \
    --exclude=./membershipledger -cf - . 2>/dev/null \
    | tar -C "$OUT_DIR/deliverable" -xf - 2>/dev/null || true
# The whole verifier log tree, not just its top, and after the extraction rather
# than before it: the archive's first member is `./`, so tar restores /app's own
# mode and owner onto this directory and any chmod before the pipe is undone by
# it. Left alone the snapshot comes out agent:agent 0755 full of agent-owned
# files, which is the submission handed back to the account that wrote it if the
# parent's 0700 ever regresses. Harbor collects as root and is unaffected.
chown -R root:root "$OUT_DIR/deliverable" 2>/dev/null
chmod -R u+rwX,go-rwx "$OUT_DIR/deliverable" 2>/dev/null
say "deliverable: $(find "$OUT_DIR/deliverable" -type f 2>/dev/null | wc -l) file(s), \
$(stat -c '%U:%G %a' "$OUT_DIR/deliverable")"

# ------------------------------------------------------------------ the box

# Anything left listening from an earlier run would answer for the submission
# being graded now, so nothing survives this. Matching on the path as well as
# the name matters: the built binary is not called "membershipd".
# Nothing here sleeps a fixed amount. A pause long enough on this machine is
# not long enough on a loaded one, and a teardown that only usually finishes
# leaves the previous run's process answering for this one -- which reads as a
# wrong answer and is not one. Each step waits for the condition it actually
# needs and escalates when it does not arrive.
port_free() {
    python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(2)
sys.exit(0 if s.connect_ex(('127.0.0.1', $1)) != 0 else 1)
"
}

# $1 seconds, then the condition as a command.
wait_for() {
    local limit=$1; shift
    local until=$(( $(date +%s) + limit ))
    while [ "$(date +%s)" -lt "$until" ]; do
        if "$@"; then return 0; fi
        sleep 0.1
    done
    return 1
}

gone() { ! pgrep -f "$1" >/dev/null 2>&1; }
gone_exact() { ! pgrep -x "$1" >/dev/null 2>&1; }

pkill -x membershipd >/dev/null 2>&1
# Every build of this service, not just the one this script makes. The box
# starts a copy of its own for whoever is working in it, a solver may well have
# left one of their own behind, and either of those is still holding the port
# the driver needs. A leftover listener is not a wrong answer -- it answers for
# the submission in the submission's place -- so it cannot be allowed to survive
# into a graded run and be reported as one.
pkill -f /tmp/membershipd >/dev/null 2>&1
wait_for 20 gone /tmp/membershipd || pkill -9 -f /tmp/membershipd >/dev/null 2>&1
wait_for 20 gone /tmp/membershipd || \
    harness_failure "a previous run's service would not go away"
rm -f /tmp/membershipd-candidate

# The storage service has to be seen to exit, not merely asked to. It unlinks
# its own sockets on the way down, so a replacement started while the old one
# is still shutting down comes up, binds, and then has the sockets pulled out
# from under it by its predecessor: it stays running, answers nothing, and the
# run dies at the readiness check below with no sign of why.
pkill -x storesvc >/dev/null 2>&1
wait_for 20 gone_exact storesvc || pkill -9 -x storesvc >/dev/null 2>&1
wait_for 20 gone_exact storesvc || \
    harness_failure "a previous run's storage service would not go away"

# And whatever is still on the two ports, whatever it is called. `fuser` is the
# one that works without procfs cooperation from another user's process.
for port in 8080 8081; do
    fuser -k -TERM "$port/tcp" >/dev/null 2>&1
    if ! wait_for 20 port_free "$port"; then
        fuser -k -KILL "$port/tcp" >/dev/null 2>&1
        wait_for 20 port_free "$port" || harness_failure \
            "something is still listening on 127.0.0.1:$port and would answer for the submission"
    fi
done

# --- mockgithub: keep the consultation journal as evidence, then stop the daemon.
# Evidence only: nothing below is an input to the verdict.
echo "=== GitHub workspace: keep the consultation journal, stop the daemon ==="
cp /var/lib/task-data/journal/github-calls.jsonl "$OUT_DIR/github-calls.jsonl" 2>/dev/null || true
cp /tmp/task-infra/mockgithub.log "$OUT_DIR/mockgithub.log" 2>/dev/null || true
echo "github journal: $(wc -l < "$OUT_DIR/github-calls.jsonl" 2>/dev/null || echo 0) calls recorded"
if [ -f /tmp/task-infra/mockgithub.pid ]; then
    kill "$(cat /tmp/task-infra/mockgithub.pid)" 2>/dev/null
fi
pkill -f 'python3 -m mockgithub --scenario' 2>/dev/null
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
    pkill -9 -f 'python3 -m mockgithub --scenario' 2>/dev/null
    sleep 0.5
done
rm -f /run/ledger/store.sock /run/ledger/store-control.sock /run/ledger/oplog.jsonl
rm -f /run/ledger/fault-plan.json
# The graded service is started with neither -dev-smoke nor -dev-reset, so
# nothing in the workspace can reach the fault table. Removing these as well
# costs nothing and means a leftover from the solver's own testing cannot be
# mistaken for part of a graded run when the logs are read later.
rm -f /app/data/fault-plan.json /app/data/smoke-faults
rm -f /app/data/reset-request /app/data/reset-request.done

say "installing the graded ledger"
install -o agent -g agent -m 644 "$VERIFIER/graded/legacy.db" /app/data/legacy.db || \
    harness_failure "the graded ledger would not install"
rm -f /app/data/legacy.db-wal /app/data/legacy.db-shm
cp "$VERIFIER/graded/truth.jsonl" "$RUN/seed-truth.jsonl" || \
    harness_failure "the graded ledger log is missing"

# The storage service comes back with no plan file of any kind, so whatever the
# submission may have left in /app/data is ignored: a graded run's faults arrive
# over the root-only control channel and nowhere else. Its write log lands where
# only root can read it.
say "restarting the storage service"
setsid /usr/local/bin/storesvc \
    -socket /run/ledger/store.sock \
    -control-socket /run/ledger/store-control.sock \
    -oplog /run/ledger/oplog.jsonl \
    >> "$RUN/storesvc.log" 2>&1 &
for _ in $(seq 1 240); do
    [ -S /run/ledger/store-control.sock ] && [ -S /run/ledger/store.sock ] && break
    sleep 0.5
done
[ -S /run/ledger/store-control.sock ] || harness_failure "the storage service never came up"

# ---------------------------------------------------------------- the build

say "building the submission"
BUILD_LOG="$RUN/build.log"
if ! setpriv --reuid agent --regid agent --clear-groups -- \
        env -i PATH=/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin \
                HOME=/home/agent GOFLAGS=-mod=mod GOTOOLCHAIN=local \
                GOPATH=/go GOMODCACHE=/go/pkg/mod \
                GOCACHE=/home/agent/.cache/go-build \
                GOPROXY=off CGO_ENABLED=0 \
        bash -c 'cd /app && go build -o /tmp/membershipd-candidate ./cmd/membershipd' \
        > "$BUILD_LOG" 2>&1; then
    say "$(tail -25 "$BUILD_LOG")"
    harness_failure "the submission does not build"
fi
[ -x /tmp/membershipd-candidate ] || harness_failure "the build produced no binary"

# ---------------------------------------------------------------- the drive

say "driving the migration"
python3 "$VERIFIER/driver.py" \
    --binary /tmp/membershipd-candidate \
    --run-dir "$RUN" \
    --seed-truth "$RUN/seed-truth.jsonl" \
    --legacy-pristine "$VERIFIER/graded/legacy.db" \
    --boundary 620 \
    --lease-ttl 23 \
    --clock-start 1745000000 \
    --dsn "${GEL_DSN:-gel://admin:dev@localhost:5656/main}" \
    ${ONLY_SCENARIOS:+--only "$ONLY_SCENARIOS"} \
    >> "$LOG" 2>&1
DRIVE=$?
pkill -f /tmp/membershipd-candidate >/dev/null 2>&1

[ -f "$RUN/observations.json" ] || harness_failure "the drive recorded nothing"
if [ "$DRIVE" != "0" ]; then
    harness_failure "the drive could not be completed: $(python3 -c '
import json
print(json.load(open("'"$RUN"'/observations.json")).get("harness_failure", "unknown"))' 2>/dev/null)"
fi

SEAM=$(python3 -c '
import json
print(json.load(open("'"$RUN"'/observations.json")).get("seam", "unknown"))')
if [ "$SEAM" = "absent" ]; then
    fail_with "the migration is not implemented: advancing it is still refused"
fi

# ---------------------------------------------------------------- the model

say "judging what happened"
env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C.UTF-8 \
    python3 "$VERIFIER/model/model.py" \
        --truth-dir "$RUN" \
        --observations "$RUN/observations.json" \
        --out "$RUN/verdict.json" \
    >> "$LOG" 2>&1
JUDGED=$?

[ -f "$RUN/verdict.json" ] || harness_failure "the model produced no verdict"
if [ "$JUDGED" = "0" ]; then
    emit 1.0 "every rule held"
fi
# The model exits 2 when it was handed something it cannot score at all -- a
# canonical log carrying a movement origin no rule reasons about, for instance.
# That is not a wrong answer and must not be reported as one.
if [ "$JUDGED" = "2" ]; then
    harness_failure "$(python3 -c '
import json
print(json.load(open("'"$RUN"'/verdict.json")).get("harness_failure", "the model could not reach a verdict"))')"
fi
FAILED=$(python3 -c '
import json
print(",".join(json.load(open("'"$RUN"'/verdict.json"))["failed"]))')
fail_with "rules that did not hold: ${FAILED:-unknown}"
