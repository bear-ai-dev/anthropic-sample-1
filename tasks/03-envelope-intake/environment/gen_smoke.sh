#!/bin/bash
# Regenerates sandbox/smoke.out.json, the answer the sandbox ships.
#
#   environment/gen_smoke.sh
#
# Runs inside the shipped image, against a workspace with the reference applied,
# exactly as `sandbox/notes.md` tells a solver to run it: migrate, seed, start,
# `npm run smoke`. So the golden is what the reference answers rather than what
# anyone believes it would answer.
#
# It had been the other thing. The file shipped with an outbox holding only the
# reply the smoke script composes, which is the answer a service that leaves a
# handed-over desk's own past out of the outbox gives -- so a solver who got
# R24 right saw `npm run smoke` disagree with the shipped answer and took the
# code back out. One did. Hence this script: a golden nobody can hand-edit
# cannot drift away from the reference again.
#
# The runner's own stdout goes through `environment/smoke_format.py`, which is the
# house layout and nothing else; it is checked here against a reparse, so a
# formatting bug cannot change what the golden says.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TASK="$(cd "$HERE/.." && pwd)"
IMAGE="${MATRIX_IMAGE:-sample-08:v9}"
BOX="${SMOKE_BOX:-s-08-smoke}"
OUT="$TASK/environment/workspace/sandbox/smoke.out.json"

docker rm -f "$BOX" > /dev/null 2>&1 || true
docker run -d --name "$BOX" --network none --cpus 4 --memory 4g "$IMAGE" --wait > /dev/null
for _ in $(seq 1 120); do
    docker exec "$BOX" test -f /tmp/task-infra/.ready 2>/dev/null && break
    sleep 2
done

docker cp "$TASK/solution" "$BOX:/solution" > /dev/null
# The sandbox from the tree rather than from the image. The image is built from
# this directory but is rebuilt on its own schedule, and a golden generated
# against a stale runner is the failure this script exists to prevent -- it
# happened once already, on the run that first put a neutral key in the outbox
# listing and then read the old runner's literal one back out.
docker cp "$TASK/environment/workspace/sandbox" "$BOX:/tmp/sandbox" > /dev/null

docker exec "$BOX" bash -c '
set -euo pipefail
cp -a /solution/files/. /app/
cp -a /tmp/sandbox/. /app/sandbox/
chown -R agent:agent /app
export INTAKE_DB=/tmp/smoke.db PORT=8392
rm -f /tmp/smoke.db*
cd /app

# The three commands `sandbox/notes.md` documents, in that order. `seed:sandbox`
# migrates, writes the desk it hands over its past, and migrates again, so the
# store the smoke operations run against is the store an upgrade leaves.
sudo -u agent env INTAKE_DB=$INTAKE_DB npm run migrate > /dev/null
sudo -u agent env INTAKE_DB=$INTAKE_DB npm run seed:sandbox > /dev/null

sudo -u agent env INTAKE_DB=$INTAKE_DB PORT=$PORT nohup tsx src/server.ts \
    > /tmp/service.log 2>&1 &
for _ in $(seq 1 60); do
    curl -sf "http://127.0.0.1:$PORT/health" > /dev/null 2>&1 && break
    sleep 0.5
done
curl -sf "http://127.0.0.1:$PORT/health" > /dev/null || { cat /tmp/service.log; exit 1; }

# The runner rather than `npm run smoke`, which is the same command with a
# banner on stdout in front of the JSON.
sudo -u agent env PORT=$PORT tsx sandbox/run-fixture.ts sandbox/smoke.jsonl \
    > /tmp/smoke.raw.json
# No teardown: the container is destroyed below, and a `pkill -f` here is the
# pattern that matches its own command line -- see gen_recording.py.
' 2>&1 | sed 's/^/  /'

docker cp "$BOX:/tmp/smoke.raw.json" /tmp/s08-smoke.raw.json > /dev/null
docker rm -f "$BOX" > /dev/null 2>&1 || true

python3 "$HERE/smoke_format.py" < /tmp/s08-smoke.raw.json > "$OUT"
python3 - "$OUT" /tmp/s08-smoke.raw.json <<'PY'
import json, sys
written, raw = (json.load(open(path)) for path in sys.argv[1:3])
if written != raw:
    raise SystemExit("the formatter changed the report; refusing to ship it")
print(f"{sys.argv[1]}: {len(written['outboxes'][0]['replies'])} outbox row(s)")
for row in written["outboxes"][0]["replies"]:
    print(f"  {row['message_id']}  {row['state']}")
PY
