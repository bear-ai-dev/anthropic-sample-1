#!/bin/bash
# Verifier entry point.
#
# Trust model: the agent owns /app, so anything that loads /app code can
# fabricate its own success. Nothing here derives the reward from an exit code
# or from stdout. The submitted service is started against a store it has never
# seen, provisioned with reference data that appears nowhere in the workspace,
# and then driven over HTTP by a process that loads none of its code. The
# transcript is handed to compute_reward.py, which runs as root under `env -i`
# and works out for itself what should have happened.
#
# The port matters. Inside the shipped container this is the only service and
# the default is correct, but the same script runs on shared build machines where
# other tasks are listening. So: the port comes from the environment and is
# never scanned for; nothing is ever signalled except the process this script
# started, by pidfile; and the store is a directory of this run's own, thrown
# away afterwards.
set -uo pipefail

VERIFIER_DIR="/logs/verifier"
TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_DATA="/var/lib/task-data"
VERIFIER_DATA="$TASK_DATA/verifier"
APP_DIR="${APP_DIR:-/app}"
PORT="${INTAKE_VERIFY_PORT:-8421}"

mkdir -p "$VERIFIER_DIR"
chmod 700 "$VERIFIER_DIR"
rm -f "$VERIFIER_DIR"/reward.json "$VERIFIER_DIR"/reward.txt \
      "$VERIFIER_DIR"/reward-detail.json "$VERIFIER_DIR"/report.txt

# Fail closed, and numerically. An unexpected exit is exactly the case that
# never reaches a sanitising sweep at the bottom of a script, and a reward.json
# carrying a string or a bool is not a zero -- it is a trial recorded as an
# exception with no score at all.
printf '{"reward": 0.0, "harness_failure": 1}\n' > "$VERIFIER_DIR/reward.json"
printf '0.0\n' > "$VERIFIER_DIR/reward.txt"
printf 'harness: the verifier did not run to completion\n' > "$VERIFIER_DIR/report.txt"

SERVER_PID=""

# Teardown is in stop_service.py, and the reasons it is not two lines of `kill`
# are documented there. The short version: `su` gives the service a session of
# its own, so neither the pid this script forked nor its process group reaches
# the listener, and a listener that outlives its run answers the next one from a
# store that has already been deleted.
port_is_free() {
    python3 "$TESTS_DIR/stop_service.py" --port "$PORT" --check > /dev/null 2>&1
}

stop_server() {
    INNER_PID=""
    if [ -n "${RUN_DIR:-}" ] && [ -r "$RUN_DIR/service.inner.pid" ]; then
        INNER_PID="$(cat "$RUN_DIR/service.inner.pid" 2>/dev/null)"
    fi
    python3 "$TESTS_DIR/stop_service.py" --port "$PORT" \
        $SERVER_PID $INNER_PID >> "$VERIFIER_DIR/teardown.log" 2>&1
    TEARDOWN_EXIT=$?
    SERVER_PID=""
    return $TEARDOWN_EXIT
}

# Nothing may outlive this script. The named exits below stop the service
# themselves; this catches the ones nobody thought of.
trap stop_server EXIT

# The split is written by compute_reward.py on every path, including these two,
# because these are the paths that exit before any sweep at the end.
fail_with() {
    stop_server
    python3 "$TESTS_DIR/compute_reward.py" --fail "$1" --output-dir "$VERIFIER_DIR"
    echo "FAIL: $1"
    exit 0
}

harness_failure() {
    stop_server
    python3 "$TESTS_DIR/compute_reward.py" --harness-failure "$1" --output-dir "$VERIFIER_DIR"
    echo "HARNESS FAILURE: $1"
    exit 0
}

if [ "$(id -u)" != "0" ]; then
    harness_failure "the verifier must run as root"
fi
if [ ! -r "$VERIFIER_DATA/run-spec.json" ]; then
    harness_failure "the graded run is missing from the image"
fi
if [ ! -r "$VERIFIER_DATA/model/intake_model.py" ]; then
    harness_failure "the independent model is missing from the image"
fi
if [ ! -d "$APP_DIR/src" ]; then
    fail_with "$APP_DIR/src is missing"
fi

# Keep the graded deliverable beside the reward, so a run can be audited long
# after the sandbox is gone. Evidence, never an input to the verdict.
echo "=== Snapshot the deliverable ==="
mkdir -p "$VERIFIER_DIR/deliverable"
tar -C "$APP_DIR" --exclude=./node_modules --exclude=./.git -cf - . 2>/dev/null \
    | tar -C "$VERIFIER_DIR/deliverable" -xf - 2>/dev/null

# --- mockgmail: keep the consultation journal as evidence, then stop the daemon.
# Evidence only: nothing below is an input to the verdict.
echo "=== Gmail workspace: keep the consultation journal, stop the daemon ==="
cp /var/lib/task-data/journal/gmail-calls.jsonl "$VERIFIER_DIR/gmail-calls.jsonl" 2>/dev/null || true
cp /tmp/task-infra/mockgmail.log "$VERIFIER_DIR/mockgmail.log" 2>/dev/null || true
echo "gmail journal: $(wc -l < "$VERIFIER_DIR/gmail-calls.jsonl" 2>/dev/null || echo 0) calls recorded"
if [ -f /tmp/task-infra/mockgmail.pid ]; then
    kill "$(cat /tmp/task-infra/mockgmail.pid)" 2>/dev/null
fi
pkill -f 'python3 -m mockgmail --scenario' 2>/dev/null
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
    pkill -9 -f 'python3 -m mockgmail --scenario' 2>/dev/null
    sleep 0.5
done

# A store of this run's own, in a scratch directory the service can write to and
# nothing else uses. The workspace's own default store is left alone: whatever
# the agent left in it is not what gets graded.
RUN_DIR="$(mktemp -d /tmp/intake-verify-XXXXXX)"
chmod 0777 "$RUN_DIR"
STORE="$RUN_DIR/graded.db"
OBSERVED="$RUN_DIR/observed.json"

# The transport's side of the outbound wire. `src/egress/handoff.ts` ships in the
# workspace and writes here, so the run reads the spool directly to see what
# actually went out -- which is the one thing about the egress path that does not
# come from the submission's own answers.
SPOOL="$RUN_DIR/spool"
FLAKE="$RUN_DIR/flake.txt"
mkdir -p "$SPOOL"
chmod 0777 "$SPOOL"

AGENT_USER="agent"
id "$AGENT_USER" > /dev/null 2>&1 || AGENT_USER="root"

# The dependency tree is resolved when the image is built and is excluded from
# the deliverable snapshot above, from `pristine_app`, and from git. So a tree
# staged back into /app by a replay has no `node_modules`, and the migrate below
# fails with "Cannot find module 'sqlite3'" -- which this script would then read
# as a submission that cannot create a store and score 0.0 with a reason about
# the submission. That is an infrastructure gap wearing a verdict, and it is how
# the first reproduce_grade probe of [REDACTED_SOURCE_RUN_ID] died. Restore the copy the
# image keeps for exactly this, and say so in the log.
if [ ! -e "$APP_DIR/node_modules" ] && [ -d /opt/intake-deps/node_modules ]; then
    ln -sfn /opt/intake-deps/node_modules "$APP_DIR/node_modules"
    echo "restored the dependency tree from /opt/intake-deps (the staged tree had none)"
fi

echo "=== Apply the schema to the graded store ==="
# The service's own migration, run the way the workspace documents it. If this
# does not work the submission cannot be exercised at all.
su "$AGENT_USER" -s /bin/bash -c "cd '$APP_DIR' && env -i \
    PATH=/usr/local/bin:/usr/bin:/bin \
    HOME=/home/$AGENT_USER \
    TZ=Etc/UTC \
    INTAKE_DB='$STORE' \
    timeout 180 npm run --silent migrate" > "$VERIFIER_DIR/migrate.log" 2>&1
MIGRATE_EXIT=$?
if [ "$MIGRATE_EXIT" != 0 ] || [ ! -f "$STORE" ]; then
    echo "npm run migrate failed (exit $MIGRATE_EXIT); trying the module directly"
    su "$AGENT_USER" -s /bin/bash -c "cd '$APP_DIR' && env -i \
        PATH=/usr/local/bin:/usr/bin:/bin \
        HOME=/home/$AGENT_USER \
        TZ=Etc/UTC \
        INTAKE_DB='$STORE' \
        timeout 180 tsx src/db/migrate.ts" >> "$VERIFIER_DIR/migrate.log" 2>&1
fi

# The file existing is not the same as the schema having been applied: a failed
# migration still leaves a store behind, because opening one creates it. A store
# with no tables in it cannot be exercised by anything, and grading a submission
# zero for routing when nothing was ever created would be a number about the
# wrong thing. Counted rather than named: which tables a submission keeps is its
# own business, and the verifier does not require a particular schema.
TABLES="$(python3 - "$STORE" <<'PY' 2>/dev/null
import sqlite3, sys

try:
    connection = sqlite3.connect(sys.argv[1])
    print(
        connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
    )
except Exception:
    print(0)
PY
)"
if [ ! -f "$STORE" ] || [ "${TABLES:-0}" -lt 1 ]; then
    # Theirs, not ours: the migration is submitted code and the shipped one
    # works. A submission that cannot create a store is wrong about the whole
    # run, and a wrong answer is a nought with a reason rather than an
    # exception.
    fail_with "no table exists after the submission's own migration; see migrate.log"
fi

echo "=== Provision the desks ==="
# Reference data, written the way the workspace's own seed script writes it:
# identities, aliases, the desks' own addresses and how each desk's gateway is
# wired are provisioned outside intake and intake only reads them. A submission
# that removed those tables fails the rule that depends on them rather than
# stopping the run.
#
# This also writes the history the desks already had: tickets and the deliveries
# on them, in the two tables the shipped schema defines, exactly as a store that
# has been in service would hold them. Nothing submission-specific is written --
# the verifier does not know and does not require what tables a submission adds.
PROVISION_STATUS=0
python3 "$TESTS_DIR/provision.py" \
    --store "$STORE" --spec "$VERIFIER_DATA/run-spec.json" \
    --spool "$SPOOL" --flake "$FLAKE" \
    > "$VERIFIER_DIR/provision.log" 2>&1 || PROVISION_STATUS=$?
if [ "$PROVISION_STATUS" != 0 ]; then
    echo "provisioning the reference data did not fully succeed; see provision.log"
fi
chmod 0666 "$STORE" 2>/dev/null
chmod 0666 "$FLAKE" 2>/dev/null
chmod 0777 "$RUN_DIR" 2>/dev/null

echo "=== Migrate again, over the history ==="
# The upgrade, as an operator performs it: the code is new and the store is not.
# `npm run migrate` is documented as safe to run again and is run again here,
# against a store that now has tickets and deliveries in it that predate
# everything the submission added. What the submission's migrations make of that
# history is graded; that they can be run twice is graded by their being run
# twice.
su "$AGENT_USER" -s /bin/bash -c "cd '$APP_DIR' && env -i \
    PATH=/usr/local/bin:/usr/bin:/bin \
    HOME=/home/$AGENT_USER \
    TZ=Etc/UTC \
    INTAKE_DB='$STORE' \
    timeout 180 npm run --silent migrate" >> "$VERIFIER_DIR/migrate.log" 2>&1
echo "second migrate exit: $?"
chmod 0666 "$STORE" 2>/dev/null

echo "=== Start the submitted service on port $PORT ==="
# Nothing may already be answering on this port. If something is, the run would
# grade whatever that is, so refuse rather than produce a number.
if ! port_is_free; then
    harness_failure "port $PORT was already in use before the service was started"
fi

# Starting the service is written down once, in a script, because the run starts
# it more than once: some of the graded operations stop it and start it again in
# the middle, and a restart has to be the same command as the first start or it
# would be measuring a difference the run did not ask for.
#
# `env -i` keeps every verifier path and secret out of a process that runs
# submitted code. The store and the port are the only things it is told.
#
# The inner shell records its own pid before exec'ing npm, so teardown has a pid
# on the far side of `su` -- the near side is a different session and its tree is
# no help. The quoted heredoc keeps every expansion for the moment the script
# runs, and `\$\$` is escaped again so the innermost shell expands it.
export AGENT_USER APP_DIR RUN_DIR STORE PORT TESTS_DIR VERIFIER_DIR SPOOL FLAKE
cat > "$RUN_DIR/launch.sh" <<'LAUNCH'
#!/bin/bash
su "$AGENT_USER" -s /bin/bash -c "cd '$APP_DIR' && \
    echo \$\$ > '$RUN_DIR/service.inner.pid' && exec env -i \
    PATH=/usr/local/bin:/usr/bin:/bin \
    HOME=/home/$AGENT_USER \
    TZ=Etc/UTC \
    NODE_OPTIONS=--max-old-space-size=1024 \
    INTAKE_DB='$STORE' \
    DESK_SPOOL='$SPOOL' \
    DESK_SPOOL_FLAKE='$FLAKE' \
    PORT='$PORT' \
    npm run --silent start" >> "$VERIFIER_DIR/service.log" 2>&1 &
echo $! > "$RUN_DIR/service.pid"
LAUNCH

# A restart, for the operations in the run that ask for one. The stop is the
# same teardown the whole script uses, so a listener that survives it survives
# nothing: the port sweep catches it however it is related to us. Only a failed
# stop is reported as ours -- a service that does not answer afterwards is the
# submission's own answer to the run, and the deliveries after it say so.
cat > "$RUN_DIR/restart.sh" <<'RESTART'
#!/bin/bash
INNER=""
OUTER=""
[ -r "$RUN_DIR/service.inner.pid" ] && INNER="$(cat "$RUN_DIR/service.inner.pid")"
[ -r "$RUN_DIR/service.pid" ] && OUTER="$(cat "$RUN_DIR/service.pid")"
python3 "$TESTS_DIR/stop_service.py" --port "$PORT" $OUTER $INNER \
    >> "$VERIFIER_DIR/teardown.log" 2>&1 || exit 1
exec "$RUN_DIR/launch.sh"
RESTART
chmod +x "$RUN_DIR/launch.sh" "$RUN_DIR/restart.sh"

"$RUN_DIR/launch.sh"
SERVER_PID="$(cat "$RUN_DIR/service.pid" 2>/dev/null)"

echo "=== Drive the graded run ==="
# The driver speaks HTTP and loads none of the submission's code, so its exit
# status is a diagnostic. A non-zero exit means the driver itself did not finish,
# which is ours and not theirs.
python3 "$TESTS_DIR/drive.py" \
    --spec "$VERIFIER_DATA/run-spec.json" \
    --out "$OBSERVED" \
    --port "$PORT" \
    --restart-command "$RUN_DIR/restart.sh" \
    --spool "$SPOOL" \
    --health-budget 60 > "$VERIFIER_DIR/driver.log" 2>&1
DRIVER_EXIT=$?

# The service is started again by the restarts, so the pid the teardown below
# reaches for is whichever start was the last one.
SERVER_PID="$(cat "$RUN_DIR/service.pid" 2>/dev/null)"
echo "driver diagnostic exit: $DRIVER_EXIT"

# A teardown that cannot free the port does not invalidate the transcript just
# taken -- that run did reach this script's own service -- but it does leave the
# box dirty for whatever runs next, so it is recorded rather than swallowed.
if ! stop_server; then
    echo "warning: teardown left the port held; see teardown.log"
fi

if [ "$DRIVER_EXIT" != 0 ]; then
    harness_failure "the driver did not complete (exit ${DRIVER_EXIT}); see driver.log"
fi
if [ ! -s "$OBSERVED" ]; then
    harness_failure "the driver left no transcript behind; see driver.log"
fi

echo "=== Score (root, env -i, no submitted code loaded) ==="
# PYTHONDONTWRITEBYTECODE is set in the image but `env -i` drops it, and without
# it importing the model writes a __pycache__ into the held-out directory: a
# world-readable directory inside data that is otherwise root-only, and a write
# into material that should be identical on every run.
env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/root TZ=Etc/UTC \
    PYTHONDONTWRITEBYTECODE=1 \
    python3 "$TESTS_DIR/compute_reward.py" \
        --output-dir "$VERIFIER_DIR" \
        --spec "$VERIFIER_DATA/run-spec.json" \
        --observed "$OBSERVED" \
        --model-dir "$VERIFIER_DATA/model"

cp -a "$OBSERVED" "$VERIFIER_DIR/observed.json" 2>/dev/null
rm -rf "$RUN_DIR"
cat "$VERIFIER_DIR/report.txt" 2>/dev/null

# --- Harbor reward.json contract -------------------------------------------
# The split above is done at the point of writing, on every path. This is the
# net: it catches anything that wrote a reward.json some other way.
python3 - <<'SANITISE_REWARD' 2>/dev/null || true
import json, pathlib

for path in pathlib.Path("/logs").rglob("reward.json"):
    try:
        payload = json.loads(path.read_text())
    except Exception:
        continue
    if not isinstance(payload, dict):
        continue
    numeric = {
        key: value
        for key, value in payload.items()
        # bool is an int in Python but pydantic rejects it for float|int.
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    if numeric == payload:
        continue
    path.with_name("reward-detail.json").write_text(
        json.dumps(payload, indent=2, default=str)
    )
    path.write_text(json.dumps(numeric))
SANITISE_REWARD
