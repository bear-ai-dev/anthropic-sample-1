#!/bin/bash
# Bring the stack up before handing over. Whoever opens this container -- the
# solver or the grader -- finds Gel listening, Redis listening, and the fixture
# loaded, because the task is about what the service does with that data and not
# about assembling the environment.
set -u

source /opt/harness/lib.sh

mkdir -p /var/log/task "$(dirname "$SETUP_MARKER")"
install -d -m 0700 -o root -g root /var/lib/task-data /var/lib/task-data/run /var/lib/task-data/journal

# Close the reward directory and the two mount points before anyone is let in.
# This runs as root, before the solver's shell exists, and it is the last moment
# at which the modes can be set: Harbor creates /logs/verifier itself if nobody
# else has, with a default mode, and whoever creates a directory sets what it
# allows.
#
# Take what is there apart first. `install -d` and `mkdir -p` both follow a
# symlink, so a solver who leaves an agent-owned symlink at one of these paths
# would have this loop apply root:root 0700 to whatever it points at -- their
# own home directory, say, which on a sibling task locked the solver out of its
# own build cache -- and leave the writable link in place at the name that
# matters. Anything at these paths that is not a real directory is removed
# rather than adjusted.
for d in /logs/verifier /tests /solution; do
  if [ -L "$d" ] || { [ -e "$d" ] && [ ! -d "$d" ]; }; then
    echo "[entrypoint] removing a non-directory at $d before closing it" >&2
    rm -f "$d"
  fi
done
install -d -m 0755 -o root -g root /logs 2>/dev/null || true
install -d -m 0700 -o root -g root /logs/verifier /tests /solution 2>/dev/null || true

# Clear the marker first. It is the grader's handover signal, and a stale one
# from a previous container start would let grading begin against a database
# that is still being seeded.
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
  count=$(gelj 'select count(EventSeries)' 2>/dev/null | tr -dc '0-9')
  if [ "${count:-0}" = "0" ]; then
    if reset_db; then
      echo "[entrypoint] fixture loaded"
    else
      echo "[entrypoint] fixture did NOT load cleanly; see the messages above" >&2
    fi
  else
    echo "[entrypoint] database already populated; left alone"
  fi
fi

MOCK_TOKEN=$(head -c 18 /dev/urandom | od -An -tx1 | tr -d ' \n')
printf '%s' "$MOCK_TOKEN" > /var/lib/task-data/run/linear-admin-token
chmod 0600 /var/lib/task-data/run/linear-admin-token
MOCKLINEAR_ADMIN_TOKEN="$MOCK_TOKEN" \
MOCKLINEAR_JOURNAL=/var/lib/task-data/journal/linear-calls.jsonl \
PYTHONPATH=/opt/mocklinear PYTHONDONTWRITEBYTECODE=1 \
  python3 -m mocklinear --scenario /opt/linear-sandbox/public.json \
    --host 127.0.0.1 --port 4570 --seed 7 > /var/log/task/mocklinear.log 2>&1 &
echo $! > /var/log/task/mocklinear.pid
for _ in $(seq 1 60); do
  python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:4570/healthz", timeout=1)' >/dev/null 2>&1 && break
  sleep 0.25
done
python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:4570/healthz", timeout=1)' >/dev/null 2>&1 \
  || {
    echo "[entrypoint] mocklinear did not start; see /var/log/task/mocklinear.log" >&2
    exit 1
  }

touch "$SETUP_MARKER"
echo "[entrypoint] ready"

exec "$@"
