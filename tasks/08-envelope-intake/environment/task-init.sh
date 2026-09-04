#!/bin/bash
# Brings the box to a state the workspace's own documentation describes, then
# hands control on.
#
# Nothing long-running is started here: the service is the deliverable and the
# agent starts it. What this does is make sure the store the workspace defaults
# to exists and has the shipped schema in it, so `npm start` works on a box
# nobody has touched yet.
set -euo pipefail

READY_DIR=/tmp/task-infra
mkdir -p "$READY_DIR"
rm -f "$READY_DIR/.ready"

# With no network namespace of its own the container hostname resolves nowhere,
# and sudo prints a resolver warning over the top of every command.
if ! getent hosts "$(hostname)" > /dev/null 2>&1; then
    printf '127.0.1.1\t%s\n' "$(hostname)" >> /etc/hosts 2>/dev/null || true
fi

# The dependency tree is resolved at build time and is in none of the copies we
# keep, so a workspace staged into /app by a replay or a reset arrives without
# one and cannot even migrate. Restore it rather than let the box come up
# broken; the Dockerfile has the detail.
if [ ! -e /app/node_modules ] && [ -d /opt/intake-deps/node_modules ]; then
    ln -sfn /opt/intake-deps/node_modules /app/node_modules
    echo "restored the dependency tree from /opt/intake-deps"
fi

if [ "$(id -u)" = "0" ] && id agent > /dev/null 2>&1; then
    su agent -s /bin/bash -c 'cd /app && npm run --silent migrate' \
        > "$READY_DIR/migrate.log" 2>&1 || true
else
    (cd /app && npm run --silent migrate) > "$READY_DIR/migrate.log" 2>&1 || true
fi

# --- mockgmail (context service; see README "Desk mailbox") ---
MOCK_INFRA=/tmp/task-infra
install -d -m 0755 "$MOCK_INFRA"
install -d -m 0700 -o root -g root /var/lib/task-data /var/lib/task-data/run /var/lib/task-data/journal
MOCK_TOKEN="$(head -c 18 /dev/urandom | od -An -tx1 | tr -d ' \n')"
printf '%s' "$MOCK_TOKEN" > /var/lib/task-data/run/admin-token
chmod 0600 /var/lib/task-data/run/admin-token
MOCKGMAIL_ADMIN_TOKEN="$MOCK_TOKEN" \
MOCKGMAIL_JOURNAL=/var/lib/task-data/journal/gmail-calls.jsonl \
PYTHONPATH=/opt/mockgmail PYTHONDONTWRITEBYTECODE=1 \
    python3 -m mockgmail --scenario /opt/gmail-sandbox/public.json \
        --host 127.0.0.1 --port 4570 --seed 7 > "$MOCK_INFRA/mockgmail.log" 2>&1 &
echo $! > "$MOCK_INFRA/mockgmail.pid"
unset MOCK_TOKEN
for _ in $(seq 1 60); do
    if curl -s -o /dev/null "http://127.0.0.1:4570/healthz"; then break; fi
    sleep 0.5
done
if ! curl -s -o /dev/null "http://127.0.0.1:4570/healthz"; then
    echo "mockgmail failed to start; see $MOCK_INFRA/mockgmail.log" >&2
    cat "$MOCK_INFRA/mockgmail.log" >&2 || true
    exit 1
fi
echo "gmail workspace ready on port 4570"

touch "$READY_DIR/.ready"
echo "intake workspace ready (store ${INTAKE_DB:-/data/intake.db})"

# Runs as the image entrypoint, so hand control to whatever command the harness
# supplied. Harbor replaces the image CMD with its own keep-alive, so a script
# that idled here instead of exec'ing would strand the container.
if [ "${1:-}" = "--wait" ]; then
    exec tail -f /dev/null
fi

if [ "$#" -gt 0 ]; then
    exec "$@"
fi
