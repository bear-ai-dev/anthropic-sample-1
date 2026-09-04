#!/bin/bash
# Bring the stack up before handing over. Whoever opens this container — the
# solver or the grader — finds Gel listening, Redis listening, and the fixture
# loaded, because the task is about what the service does with that data and
# not about assembling the environment.
set -u

source /opt/harness/lib.sh

mkdir -p /var/log/task "$(dirname "$SETUP_MARKER")"

# Container assembly is bounded by task.toml's setup_timeout_sec, so the waits
# below get a deadline for the same reason the verifier's do: a start_gel that
# outruns setup leaves the sandbox with no marker and nothing that says why. The
# subtraction leaves room for redis and the fixture load after the database.
# Without this the database's own ceiling would be free to spend the whole of
# setup on its own, which is how a generous ceiling turns into a broken box.
READY_DEADLINE=$(( $(date +%s) + ${SETUP_TIMEOUT_SEC:-900} - 240 ))
export READY_DEADLINE
# Cleared first and written last, so its presence means this script finished
# rather than merely started. Anything that drives the database has to wait for
# it: Gel answers queries a good while before the fixture is in, and a verifier
# that starts resetting while this is still seeding races it. That race shows up
# as a uniqueness violation on the seed and reads like a broken fixture.
rm -f "$SETUP_MARKER"

if ! start_gel; then
  echo "[entrypoint] gel did not come up; see /var/log/task/gel.log" >&2
fi
if ! start_redis; then
  echo "[entrypoint] redis did not come up; see /var/log/task/redis.log" >&2
fi

# Seed only an empty database, so restarting the container does not throw away
# whatever state someone was in the middle of looking at.
if gelq 'select 1' >/dev/null 2>&1; then
  count=$(gelj 'select count(Event)' 2>/dev/null | tr -dc '0-9')
  if [ "${count:-0}" = "0" ]; then
    reset_db && echo "[entrypoint] fixture loaded"
  else
    echo "[entrypoint] database already populated; left alone"
  fi
fi

# --- mocklinear (context service; see README "Linear workspace") ---
MOCK_INFRA=/tmp/task-infra
install -d -m 0755 "$MOCK_INFRA"
install -d -m 0700 -o root -g root /var/lib/task-data /var/lib/task-data/run /var/lib/task-data/journal
MOCK_TOKEN="$(head -c 18 /dev/urandom | od -An -tx1 | tr -d ' \n')"
printf '%s' "$MOCK_TOKEN" > /var/lib/task-data/run/admin-token
chmod 0600 /var/lib/task-data/run/admin-token
MOCKLINEAR_ADMIN_TOKEN="$MOCK_TOKEN" \
MOCKLINEAR_JOURNAL=/var/lib/task-data/journal/linear-calls.jsonl \
PYTHONPATH=/opt/mocklinear PYTHONDONTWRITEBYTECODE=1 \
    python3 -m mocklinear --scenario /opt/linear-sandbox/public.json \
        --host 127.0.0.1 --port 4570 --seed 7 > "$MOCK_INFRA/mocklinear.log" 2>&1 &
echo $! > "$MOCK_INFRA/mocklinear.pid"
unset MOCK_TOKEN
for _ in $(seq 1 60); do
    if curl -s -o /dev/null "http://127.0.0.1:4570/healthz"; then break; fi
    sleep 0.5
done
if ! curl -s -o /dev/null "http://127.0.0.1:4570/healthz"; then
    echo "mocklinear failed to start; see $MOCK_INFRA/mocklinear.log" >&2
    cat "$MOCK_INFRA/mocklinear.log" >&2 || true
    exit 1
fi
echo "linear workspace ready on port 4570"

touch "$SETUP_MARKER"
echo "[entrypoint] ready"

exec "$@"
