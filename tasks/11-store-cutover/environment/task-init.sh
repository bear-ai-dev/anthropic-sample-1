#!/bin/bash
# Bring the box up: the destination database, the coordination keyspace, the
# storage service in front of them, and a seeded legacy ledger.
#
# Everything is local and nothing reaches a network. Gel takes its time to
# answer the first query, so this polls for it rather than sleeping.
set -uo pipefail

INFRA=/tmp/task-infra
RUN=/run/ledger
export GEL_DSN="gel://admin:dev@localhost:5656/main"
export GEL_CLIENT_TLS_SECURITY=insecure
export GEL_SERVER_SECURITY=insecure_dev_mode
export GEL_SERVER_PASSWORD=dev
export GEL_SERVER_TLS_CERT_MODE=generate_self_signed

mkdir -p "$INFRA" "$RUN"
chmod 0755 "$RUN"
rm -f "$INFRA/.ready"

log() { echo "task-init: $*"; }

# The reward directory, claimed for root before the solver has a session.
# The grader makes it root-only when it runs, but that is after submit, so
# until then the directory is merely absent -- and an absent directory in a
# writable /logs is one the solving account can create, own and put a
# reward.json of its own into, against a grader that never gets to overwrite
# it. Root owns it from start-up instead, so the agent account reads
# `Permission denied` for the whole of the run.
#
# Attempted unconditionally and reported either way. This used to be guarded by
# `[ -d /logs ]` with its errors sent to /dev/null, which made three different
# outcomes look identical from the start-up log: the claim succeeding, the claim
# failing, and /logs not existing yet because the harness had not mounted it.
# The last of those leaves the directory absent for the whole run, which is the
# window this exists to close. Silence and success must not have the same shape,
# so the mode and owner that resulted are logged and a failure says so on stderr
# rather than being swallowed.
#
# /logs itself is left exactly as it is found. It belongs to the harness, which
# mounts it world-writable and may have its own writers there, and `install -d`
# would otherwise apply 0700 to it as a leading component. It is created only if
# it is missing altogether.
[ -d /logs ] || install -d -m 0755 -o root -g root /logs

# Whatever is already at the path is removed rather than adjusted, and a symlink
# is the reason. `install -d` follows one: with /logs/verifier standing in for
# /home/agent, `install -d -m 0700 -o root -g root` left the symlink alone and
# applied root:root 0700 to the *agent's home directory* -- which locks the
# solver out of its own $HOME and its Go build cache with it, an environment
# defect far worse than the leak this claim exists to close. It was found by
# planting exactly that symlink and reading the start-up line, which said
# `claimed /logs/verifier as root:root 755` and not 0700, so the log caught it.
# The same reasoning is in tests/test.sh at grading time; both windows need it,
# and only the grader had it.
if [ -L /logs/verifier ] || { [ -e /logs/verifier ] && \
    [ "$(stat -c %u /logs/verifier 2>/dev/null)" != "0" ]; }; then
    log "removing a pre-existing /logs/verifier that is not root's own directory"
    rm -rf /logs/verifier
fi
if install -d -m 0700 -o root -g root /logs/verifier; then
    log "claimed /logs/verifier as $(stat -c '%U:%G %a' /logs/verifier)"
else
    log "WARNING: could not claim /logs/verifier; the reward directory is unowned" >&2
fi

log "starting the coordination keyspace"
redis-server --port 6379 --save '' --appendonly no --dir /tmp --daemonize yes \
    >> "$INFRA/redis.log" 2>&1
for _ in $(seq 1 60); do
    redis-cli ping 2>/dev/null | grep -q PONG && break
    sleep 0.5
done

log "starting the destination database"
/usr/local/bin/docker-entrypoint.sh server >> "$INFRA/gel.log" 2>&1 &
GEL_PID=$!
echo "$GEL_PID" > "$INFRA/gel.pid"

# The first query is the only reliable readiness signal, and it can be a long
# way behind the process starting.
READY=no
for attempt in $(seq 1 300); do
    if ! kill -0 "$GEL_PID" 2>/dev/null; then
        log "the destination database exited; see $INFRA/gel.log"
        break
    fi
    if gel query "select 1" >/dev/null 2>&1; then
        READY=yes
        log "destination database answered after ${attempt} attempt(s)"
        break
    fi
    sleep 1
done
if [ "$READY" != "yes" ]; then
    log "the destination database never answered"
    exit 1
fi

log "applying the destination schema"
cd /opt/ledger/gelproj || exit 1
gel migration create --non-interactive >> "$INFRA/gel-schema.log" 2>&1
gel migration apply >> "$INFRA/gel-schema.log" 2>&1
gel query "select count(MigrationMeta)" >> "$INFRA/gel-schema.log" 2>&1 \
    || { log "the destination schema did not apply"; exit 1; }

log "seeding the legacy ledger"
install -d -o agent -g agent /app/data
if [ ! -f /app/data/legacy.db ]; then
    install -o agent -g agent -m 0644 /opt/ledger/fixtures/dev/legacy.db /app/data/legacy.db
fi

# The deployment clock. Whoever is driving the box owns this file.
if [ ! -f "$RUN/clock" ]; then
    echo 1742000000 > "$RUN/clock"
fi
chmod 0644 "$RUN/clock"

log "starting the storage service"
/usr/local/bin/storesvc \
    -socket "$RUN/store.sock" \
    -control-socket "$RUN/store-control.sock" \
    -dev-smoke /app/data/smoke-faults \
    -dev-reset /app/data/reset-request \
    -dev-legacy /app/data/legacy.db \
    -dev-legacy-seed /opt/ledger/fixtures/dev/legacy.db \
    -oplog "$INFRA/store-oplog.jsonl" \
    >> "$INFRA/storesvc.log" 2>&1 &
echo "$!" > "$INFRA/storesvc.pid"

for _ in $(seq 1 120); do
    [ -S "$RUN/store.sock" ] && break
    sleep 0.5
done
if [ ! -S "$RUN/store.sock" ]; then
    log "the storage service never opened its socket; see $INFRA/storesvc.log"
    exit 1
fi

# --- mockgithub (context service; see README "GitHub workspace") ---
install -d -m 0700 -o root -g root /var/lib/task-data /var/lib/task-data/run /var/lib/task-data/journal
MOCK_TOKEN="$(head -c 18 /dev/urandom | od -An -tx1 | tr -d ' \n')"
printf '%s' "$MOCK_TOKEN" > /var/lib/task-data/run/admin-token
chmod 0600 /var/lib/task-data/run/admin-token
MOCKGITHUB_ADMIN_TOKEN="$MOCK_TOKEN" \
MOCKGITHUB_JOURNAL=/var/lib/task-data/journal/github-calls.jsonl \
PYTHONPATH=/opt/mockgithub PYTHONDONTWRITEBYTECODE=1 \
    python3 -m mockgithub --scenario /opt/github-sandbox/public.json \
        --host 127.0.0.1 --port 4570 --seed 7 > "$INFRA/mockgithub.log" 2>&1 &
echo $! > "$INFRA/mockgithub.pid"
unset MOCK_TOKEN
for _ in $(seq 1 60); do
    if curl -s -o /dev/null "http://127.0.0.1:4570/healthz"; then break; fi
    sleep 0.5
done
if ! curl -s -o /dev/null "http://127.0.0.1:4570/healthz"; then
    echo "mockgithub failed to start; see $INFRA/mockgithub.log" >&2
    cat "$INFRA/mockgithub.log" >&2 || true
    exit 1
fi
log "github workspace ready on port 4570"

touch "$INFRA/.ready"
log "ready"

if [ "${1:-}" = "--wait" ]; then
    while true; do sleep 3600; done
fi
exec "$@"
