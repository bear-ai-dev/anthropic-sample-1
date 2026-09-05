#!/usr/bin/env bash
# Grade the candidate workspace.
#
# Everything held out travels with this script: the suite, the harness that
# drives the app, the fixtures, and the independent model. Harbor uploads this
# tree and mounts it only when grading runs, so the container the solver worked
# in never contained the graded scenarios -- not readable by them, not readable
# by root, not present. The suite drives the app in /workspace through its own
# controls and compares what the page ends up showing against the model.
# Nothing here reads the candidate's source.
#
# Fail closed: the reward is 0.0 unless a complete, passing run says otherwise,
# and every exit path writes the numbers-only split that Harbor requires.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRADE_DIR=${GRADE_DIR:-$HERE/verifier-data}
WORKSPACE=${WORKSPACE:-/workspace}
LOG_DIR=${LOG_DIR:-/logs/verifier}
REPORTS=/tmp/verifier-reports
OUTPUT=/tmp/verifier-output.txt
SCORER="$HERE/score.py"

# Remove whatever is here before claiming it, and do that before the mkdir.
# `mkdir -p` succeeds against a symlink that resolves to a directory, and the
# chown and chmod below have no -h, so they would land on the link's *target*:
# an agent-owned link planted here pointing at /home/agent ends with the agent's
# own home turned root:root 0700, the solver's build cache under it gone, and
# the verdict written somewhere nobody intended. That is a worse fault than the
# leak this block exists to close, and it is not hypothetical -- it is what this
# task did until the containment check was re-run on a real ext4 volume, where
# ownership and mode are enforced. A path here that is not a directory is not
# something to adopt.
if [ -L "$LOG_DIR" ] || { [ -e "$LOG_DIR" ] && [ ! -d "$LOG_DIR" ]; }; then
    rm -rf -- "$LOG_DIR"
fi
mkdir -p "$LOG_DIR"

# The image builds this directory root-owned and 700; re-assert it, because a
# platform that recreates the path gets it with root's default umask, and that
# is world-readable. The agent account must not be able to read the record it is
# graded from -- reward, per-rule detail and the deliverable snapshot all land
# here -- let alone write one.
chown root:root "$LOG_DIR" 2>/dev/null || true
chmod 700 "$LOG_DIR"

# The floor, written before anything else can go wrong. Every path below
# rewrites it; one that dies without reaching them leaves a failing score
# rather than no score at all.
printf '{"reward": 0.0, "harness_failure": 0}' >"$LOG_DIR/reward.json"

# The one place a result is written. It takes numbers and nothing else — a
# string, a bool or a nested value there is not a zero, it is a trial recorded
# as an exception with no score at all.
emit() {
    local reward="$1" harness="$2" note="$3" passed="${4:-0}" total="${5:-0}"
    python3 - "$LOG_DIR" "$reward" "$harness" "$note" "$passed" "$total" <<'PY'
import json, sys
log_dir, reward, harness, note, passed, total = sys.argv[1:7]
# A reward goes in alongside the flag, never the flag on its own: the flag is
# what says downstream that this was not a wrong answer, but a file with no
# reward in it is a second failure stacked on the first, and it hides the first.
numbers = {"reward": float(reward), "harness_failure": int(harness)}
with open(f"{log_dir}/reward.json", "w") as fh:
    json.dump(numbers, fh)
with open(f"{log_dir}/reward-detail.json", "w") as fh:
    json.dump({"note": note, "rules_passed": int(passed), "rules_total": int(total)}, fh, indent=2)
PY
    # Files land with root's umask, which is world-readable, so if the directory
    # mode is ever loosened by the platform this is the difference between one
    # exposed path and all of them. Done here rather than once at the end
    # because every exit path goes through this function.
    chown -R root:root "$LOG_DIR" 2>/dev/null || true
    chmod -R go-rwx "$LOG_DIR" 2>/dev/null || true
    echo "== $note (reward=$reward harness_failure=$harness rules=$passed/$total)"
}

fail_with() {
    emit 0.0 0 "$1" "${2:-0}" "${3:-0}"
    exit 0
}

harness_failure() {
    emit 0.0 1 "$1" "${2:-0}" "${3:-0}"
    exit 0
}

emit 0.0 0 "grader did not finish"

# Held-out material and the shared dependency tree have to be there. If they
# are not, that is ours, not the candidate's.
for required in "$GRADE_DIR/vitest.config.ts" "$GRADE_DIR/spec/rules-media.spec.tsx" \
    "$GRADE_DIR/spec/rules-sections.spec.tsx" "$GRADE_DIR/spec/rules-documents.spec.tsx" \
    "$GRADE_DIR/spec/rules-scope.spec.tsx" "$GRADE_DIR/spec/rules-timing.spec.tsx" \
    "$GRADE_DIR/spec/rules-lifecycle.spec.tsx" \
    "$GRADE_DIR/harness/setup.ts" "$GRADE_DIR/model/draftModel.ts"; do
    [ -f "$required" ] || harness_failure "held-out material missing: $required"
done

# The dependency tree is in the image; this tree arrived from outside it and may
# be mounted read-only, so the runner is found rather than linked to. A link
# beside the suite is still worth having where the mount allows one: it is what
# the transform's own resolution walks up to first.
ln -sfn /deps/node_modules "$GRADE_DIR/node_modules" 2>/dev/null || true
VITEST=""
for path in /node_modules/.bin/vitest /deps/node_modules/.bin/vitest "$GRADE_DIR/node_modules/.bin/vitest"; do
    [ -x "$path" ] && VITEST="$path" && break
done
[ -n "$VITEST" ] || harness_failure "the shared dependency tree holds no runner"
[ -d "$WORKSPACE/src" ] || harness_failure "no candidate workspace at $WORKSPACE"

# Keep the graded tree beside the reward. Evidence, never an input to the
# verdict -- the suite below reads $WORKSPACE, not this copy.
#
# A replay stages this snapshot into a fresh sandbox, and looks for it at exactly
# `verifier/deliverable`. Without it the replay stages an untouched workspace,
# reports `missing_workspace` with a zero-byte diff, and returns
# INFRASTRUCTURE_FAILURE however good this grader is.
echo "=== Snapshot the deliverable ==="
mkdir -p "$LOG_DIR/deliverable"
tar -C "$WORKSPACE" --exclude=./node_modules --exclude=./.git --exclude=./dist \
    -cf - . 2>/dev/null \
    | tar -C "$LOG_DIR/deliverable" -xf - 2>/dev/null || true

cp /var/lib/task-data/journal/linear-calls.jsonl "$LOG_DIR/linear-calls.jsonl" 2>/dev/null || true
cp /tmp/task-infra/mocklinear.log "$LOG_DIR/mocklinear.log" 2>/dev/null || true
if [ -f /tmp/task-infra/mocklinear.pid ]; then
    kill "$(cat /tmp/task-infra/mocklinear.pid)" 2>/dev/null || true
fi
pkill -f 'python3 -m mocklinear --scenario' 2>/dev/null || true

rm -rf "$REPORTS" "$OUTPUT"
mkdir -p "$REPORTS"

# The rules are split across six files, one worker per file: every page the
# suite opens leaves something the process cannot reclaim, and sixty of them in
# one process is more than the sandbox has. The whole suite goes in one
# invocation because the transform of the candidate's module graph is paid once
# there and once per invocation otherwise, but each file still gets a worker
# that has never opened a page.
#
# Then the files that came back with cases nobody reached are run again on their
# own, twice. A worker the kernel took for memory is a fact about the machine,
# not about the candidate, and it must not decide a trial while there is a cheap
# way to find out. The scorer treats a case with no verdict as unreached rather
# than failed, so the worst a starved run can do is report a harness failure.
run_vitest() {
    local report="$1"
    shift
    env -i \
        PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        HOME=/tmp \
        TZ=Etc/UTC \
        LANG=C.UTF-8 \
        NODE_OPTIONS=--max-old-space-size=1536 \
        WORKSPACE_DIR="$WORKSPACE" \
        "$VITEST" run \
        --root "$GRADE_DIR" \
        --config "$GRADE_DIR/vitest.config.ts" \
        --reporter=json --outputFile="$report" \
        "$@" \
        >>"$OUTPUT" 2>&1
    echo "== ${report##*/} exit $?" >>"$OUTPUT"
}

run_vitest "$REPORTS/all.json"

for attempt in 1 2; do
    todo=$(python3 "$SCORER" --unfinished "$REPORTS" 2>/dev/null)
    [ -n "$todo" ] || break
    for name in $todo; do
        run_vitest "$REPORTS/$name.$attempt.json" "spec/$name.spec.tsx"
    done
done

cp -f "$OUTPUT" "$LOG_DIR/verifier-output.txt" 2>/dev/null || true
python3 - "$REPORTS" "$LOG_DIR/verifier-report.json" <<'PY' || true
import json, pathlib, sys
reports = sorted(pathlib.Path(sys.argv[1]).glob("*.json"))
merged = {"testResults": []}
for path in reports:
    try:
        merged["testResults"].extend(json.loads(path.read_text()).get("testResults") or [])
    except Exception:
        continue
pathlib.Path(sys.argv[2]).write_text(json.dumps(merged, indent=1))
PY

ls "$REPORTS"/*.json >/dev/null 2>&1 ||
    harness_failure "the suite produced no report at all; see verifier-output.txt"

# A seam the harness could not resolve is a harness failure, not a wrong
# answer. It has to be looked for in the reports as well as in the console:
# with `--reporter=json` the console carries nothing, so the message that says
# the suite could not find a control it drives is only ever in a report.
if grep -q "SeamError" "$OUTPUT" "$LOG_DIR/verifier-report.json"; then
    harness_failure "a control the suite drives could not be found in the rendered page"
fi

summary=$(python3 "$SCORER" "$LOG_DIR/verifier-report.json" "$LOG_DIR")
score_status=$?
read -r passed total failed <<<"${summary:-0 12 all}"

case "$score_status" in
0)
    emit 1.0 0 "every graded rule held" "$passed" "$total"
    exit 0
    ;;
1)
    fail_with "graded rules that did not hold: $failed" "$passed" "$total"
    ;;
2)
    harness_failure "the suite's report could not be read"
    ;;
3)
    # Cases left with nothing to say about them, three attempts in: the runs
    # were cut short, most likely by the kernel taking a worker for memory.
    # Not a wrong answer.
    harness_failure "the suite did not reach every rule; see verifier-output.txt"
    ;;
*)
    harness_failure "the scorer failed unexpectedly (exit $score_status)"
    ;;
esac
