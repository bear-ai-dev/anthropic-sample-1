#!/usr/bin/env bash
# Verifier entry point. Runs as root; the workspace it grades belongs to the
# solver.
#
# Fail closed, and fail LOUD. What is on disk before grading starts is not a
# zero but a harness failure, because that is what an unexplained exit actually
# means: nobody looked at the candidate. A bare zero here would be
# indistinguishable from a graded rejection, and a zero that secretly means "the
# grader broke" is the most expensive result this campaign can produce -- it
# reads as a hard task. Only the grader itself, having reached a verdict, is
# allowed to write a plain `reward`.
set -euo pipefail

LOG_DIR="${VERIFIER_LOG_DIR:-/logs/verifier}"
mkdir -p "$LOG_DIR"
# The verdict, the per-rule detail and the deliverable snapshot all land here, so
# the account being graded must not be able to read any of it. The image ships
# this directory root-owned and 700; re-assert it, because a platform that
# recreates the path gets it with root's default umask and that is world-readable.
chown root:root "$LOG_DIR" 2>/dev/null || true
chmod 700 "$LOG_DIR"
printf '{"reward": 0.0, "harness_failure": 1}\n' > "$LOG_DIR/reward.json"
printf '{"summary": "the verifier did not finish; no verdict was reached"}\n' \
    > "$LOG_DIR/reward-detail.json"

OUT_DIR=/tmp/verify-out
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# Keep the graded tree beside the reward. Evidence, never an input to the
# verdict -- the grader below reads /workspace, not this copy.
#
# A replay stages this snapshot into a fresh sandbox, and looks for it at exactly
# `verifier/deliverable`. Without it the replay stages an untouched workspace,
# reports `missing_workspace` with a zero-byte diff, and returns
# INFRASTRUCTURE_FAILURE, so a clean result is indistinguishable from broken
# infrastructure because nothing was ever shown the code it was reading.
echo "=== Snapshot the deliverable ==="
mkdir -p "$LOG_DIR/deliverable"
tar -C /workspace --exclude=./node_modules --exclude=./.git --exclude=./dist \
    -cf - . 2>/dev/null \
    | tar -C "$LOG_DIR/deliverable" -xf - 2>/dev/null || true

# An empty snapshot is the failure mode that produced two INFRASTRUCTURE_FAILURE
# audits, and it is silent by nature: the copy "succeeded", the grader runs, a
# reward is written, and the evidence is missing. Say so on stderr where the
# platform's own logs will carry it, and count files rather than trusting tar.
SNAPPED="$(find "$LOG_DIR/deliverable" -mindepth 1 -type f 2>/dev/null | head -200 | wc -l | tr -d ' ')"
if [ "${SNAPPED:-0}" -lt 1 ]; then
    echo "WARNING: the deliverable snapshot is empty; /workspace held no files to copy." >&2
    echo "WARNING: a rollout graded from here cannot be audited." >&2
else
    echo "snapshot: ${SNAPPED} file(s) (counted to 200)"
fi

cp /var/lib/task-data/journal/linear-calls.jsonl "$LOG_DIR/linear-calls.jsonl" 2>/dev/null || true
cp /tmp/task-infra/mocklinear.log "$LOG_DIR/mocklinear.log" 2>/dev/null || true
if [ -f /tmp/task-infra/mocklinear.pid ]; then
    kill "$(cat /tmp/task-infra/mocklinear.pid)" 2>/dev/null || true
fi
pkill -f 'python3 -m mocklinear --scenario' 2>/dev/null || true

# The grader gets an explicit, minimal environment so it cannot inherit anything
# the agent left behind: no NODE_OPTIONS, no NODE_PATH, no npm config, no proxy.
env -i \
    PATH=/usr/local/bin:/usr/bin:/bin \
    HOME=/root \
    TERM=dumb \
    LANG=C.UTF-8 \
    TZ=UTC \
    CI=1 \
    NODE_ENV=test \
    VERIFY_WORKSPACE=/workspace \
    VERIFY_GRADE_DIR=/grade \
    VERIFY_OUT_DIR="$OUT_DIR" \
    VERIFY_SPEC_TIMEOUT_MS=600000 \
    /usr/local/bin/node /grade/run.mjs || true

if [ -f "$OUT_DIR/reward.json" ]; then
    cp "$OUT_DIR/reward.json" "$LOG_DIR/reward.json"
fi
if [ -f "$OUT_DIR/reward-detail.json" ]; then
    cp "$OUT_DIR/reward-detail.json" "$LOG_DIR/reward-detail.json"
fi

# Net, not the mechanism: the split is done where the grader writes. This only
# catches a value that slipped through, and leaves the file parseable either way.
# Note what an unreadable or empty reward file collapses to -- a harness failure,
# not a zero. If this file cannot be understood then no verdict was reached, and
# saying so is the whole point of the file.
/usr/local/bin/node -e '
const fs = require("fs");
const file = process.argv[1];
const broken = { reward: 0.0, harness_failure: 1 };
let out = broken;
try {
    const raw = JSON.parse(fs.readFileSync(file, "utf8"));
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
        out = {};
        for (const [k, v] of Object.entries(raw)) {
            if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
        }
        // A verdict is a reward. Anything else did not reach one.
        if (typeof out.reward !== "number") out = { ...out, ...broken };
    }
} catch {
    out = broken;
}
fs.writeFileSync(file, JSON.stringify(out, null, 2) + "\n");
' "$LOG_DIR/reward.json"

# Everything is written now, so close the whole tree rather than only its top
# directory. The 700 above is what actually stops the agent, but the snapshot is
# unpacked with the workspace's own ownership and the reward files land with
# root's umask, so if the directory mode is ever loosened by the platform this is
# the difference between one exposed path and all of them.
chown -R root:root "$LOG_DIR" 2>/dev/null || true
chmod -R go-rwx "$LOG_DIR" 2>/dev/null || true

cat "$LOG_DIR/reward.json"
