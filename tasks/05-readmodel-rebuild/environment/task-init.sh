#!/usr/bin/env bash
# Brings the two stores up before anyone is let into the box.
#
# The container's own process runs as root, which is how the database gets to
# start at all: the account the solver works as cannot, and the README tells
# them to run `gel migrate`, `npm run seed` and `npm start` against a database
# that is already listening. Everything is local; nothing reaches a network.
#
# Gel answers its first query a long way after its process starts, and how long
# varies with the host, so this polls rather than sleeping. The readiness marker
# is what [environment.healthcheck] in task.toml waits on, so a solver never
# starts work against a half-open database.
set -uo pipefail

INFRA=/tmp/task-infra
export GEL_DSN="${GEL_DSN:-gel://admin:dev@localhost:5656/main}"
export GEL_CLIENT_TLS_SECURITY=insecure

mkdir -p "$INFRA"
chmod 0777 "$INFRA"
rm -f "$INFRA/.ready"
install -d -m 0700 -o root -g root /var/lib/task-data /var/lib/task-data/run /var/lib/task-data/journal

log() { echo "task-init: $*"; }

MOCK_TOKEN=$(head -c 18 /dev/urandom | od -An -tx1 | tr -d ' \n')
printf '%s' "$MOCK_TOKEN" > /var/lib/task-data/run/github-admin-token
chmod 0600 /var/lib/task-data/run/github-admin-token
MOCKGITHUB_ADMIN_TOKEN="$MOCK_TOKEN" \
MOCKGITHUB_JOURNAL=/var/lib/task-data/journal/github-calls.jsonl \
PYTHONPATH=/opt/mockgithub PYTHONDONTWRITEBYTECODE=1 \
    python3 -m mockgithub --scenario /opt/github-sandbox/public.json \
        --host 127.0.0.1 --port 4570 --seed 7 > "$INFRA/mockgithub.log" 2>&1 &
echo $! > "$INFRA/mockgithub.pid"
for _ in $(seq 1 60); do
    python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:4570/healthz", timeout=1)' >/dev/null 2>&1 && break
    sleep 0.25
done
python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:4570/healthz", timeout=1)' >/dev/null 2>&1 \
    || {
        log "mockgithub did not start; see $INFRA/mockgithub.log"
        exit 1
    }

log "starting the routing keyspace"
redis-server --port 6379 --bind 127.0.0.1 --save '' --appendonly no --dir /tmp \
    --daemonize yes >> "$INFRA/redis.log" 2>&1
for _ in $(seq 1 60); do
    redis-cli ping 2>/dev/null | grep -q PONG && break
    sleep 0.5
done
redis-cli ping 2>/dev/null | grep -q PONG || log "the routing keyspace never answered"

log "starting the database"
/usr/local/bin/docker-entrypoint.sh server >> "$INFRA/gel.log" 2>&1 &
GEL_PID=$!
echo "$GEL_PID" > "$INFRA/gel.pid"

# The first answered query is the only readiness signal worth having; the
# process being alive says nothing.
READY=no
for attempt in $(seq 1 600); do
    if ! kill -0 "$GEL_PID" 2>/dev/null; then
        log "the database exited; see $INFRA/gel.log"
        break
    fi
    if /usr/bin/gel query --tls-security insecure --dsn "$GEL_DSN" 'select 1' >/dev/null 2>&1; then
        READY=yes
        log "the database answered after ${attempt} attempt(s)"
        break
    fi
    sleep 1
done

if [ "$READY" = yes ]; then
    touch "$INFRA/.ready"
    chmod 0644 "$INFRA/.ready"
    log "ready"
else
    # Left without the marker on purpose: the healthcheck is what reports this,
    # and staying up keeps $INFRA/gel.log collectable.
    log "the database never answered; the readiness marker was not written"
fi

if [ "${1:-}" = "--wait" ]; then
    while true; do sleep 3600; done
fi
exec "$@"
