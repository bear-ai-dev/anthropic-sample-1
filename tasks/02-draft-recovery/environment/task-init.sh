#!/usr/bin/env bash
set -euo pipefail

INFRA=/tmp/task-infra
install -d -m 0777 "$INFRA"
install -d -m 0700 -o root -g root /var/lib/task-data /var/lib/task-data/run /var/lib/task-data/journal

MOCK_TOKEN=$(head -c 18 /dev/urandom | od -An -tx1 | tr -d ' \n')
printf '%s' "$MOCK_TOKEN" > /var/lib/task-data/run/linear-admin-token
chmod 0600 /var/lib/task-data/run/linear-admin-token
MOCKLINEAR_ADMIN_TOKEN="$MOCK_TOKEN" \
MOCKLINEAR_JOURNAL=/var/lib/task-data/journal/linear-calls.jsonl \
PYTHONPATH=/opt/mocklinear PYTHONDONTWRITEBYTECODE=1 \
  python3 -m mocklinear --scenario /opt/linear-sandbox/public.json \
    --host 127.0.0.1 --port 4570 --seed 7 > "$INFRA/mocklinear.log" 2>&1 &
echo $! > "$INFRA/mocklinear.pid"

for _ in $(seq 1 60); do
  python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:4570/healthz", timeout=1)' >/dev/null 2>&1 && exec "$@"
  sleep 0.25
done

printf 'mocklinear failed to start\n' >&2
exit 1
