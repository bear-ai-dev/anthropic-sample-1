#!/usr/bin/env node
// Grading orchestrator.
//
// Contract:
//   * reward.json holds numbers and nothing else.
//   * the split between numeric reward and human-readable detail happens inside
//     `finish`, which every exit path goes through.
//   * a workspace that implements nothing takes a graded 0.0, whether or not it
//     was edited -- an absent capability is a wrong answer, not a broken grader.
//   * a harness that could not drive what is there reports harness_failure.

import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const WORKSPACE = process.env.VERIFY_WORKSPACE ?? "/workspace";
const GRADE_DIR = process.env.VERIFY_GRADE_DIR ?? "/grade";
const OUT_DIR = process.env.VERIFY_OUT_DIR ?? "/tmp/verify-out";
const MANIFEST = process.env.VERIFY_PRISTINE_MANIFEST ?? path.join(GRADE_DIR, "pristine-manifest.json");
const REPORT = path.join(OUT_DIR, "vitest-report.json");

fs.mkdirSync(OUT_DIR, { recursive: true });

let finished = false;

/** The single place reward.json and reward-detail.json are written. */
function finish({ reward, harnessFailure, summary, detail }) {
    if (finished) return;
    finished = true;

    const numeric = {};
    // A harness failure still carries a reward of 0, so a consumer that only
    // knows about `reward` is not handed a file without one -- but it carries
    // the flag beside it, so a consumer that reads further can tell "wrong" from
    // "never assessed". These two must never be confusable.
    numeric.reward = harnessFailure ? 0 : reward === 1 ? 1 : 0;
    if (harnessFailure) numeric.harness_failure = 1;
    for (const [k, v] of Object.entries(detail?.counters ?? {})) {
        if (typeof v === "number" && Number.isFinite(v)) numeric[k] = v;
    }

    // Belt and braces: strip anything that is not a finite number.
    for (const k of Object.keys(numeric)) {
        const v = numeric[k];
        if (typeof v !== "number" || typeof v === "boolean" || !Number.isFinite(v)) delete numeric[k];
    }

    fs.writeFileSync(path.join(OUT_DIR, "reward.json"), JSON.stringify(numeric, null, 2) + "\n");
    fs.writeFileSync(
        path.join(OUT_DIR, "reward-detail.json"),
        JSON.stringify({ summary, ...detail }, null, 2) + "\n"
    );
    process.stdout.write(`VERDICT ${JSON.stringify(numeric)}\n`);
    process.stdout.write(`SUMMARY ${summary}\n`);
}

const died = (kind) => (err) => {
    finish({
        harnessFailure: true,
        summary: `the grader itself ${kind}`,
        detail: { error: String(err && err.stack ? err.stack : err) },
    });
    process.exit(0);
};

process.on("uncaughtException", died("threw"));
process.on("unhandledRejection", died("rejected a promise nobody awaited"));

// Nothing below is allowed to end the process quietly. If some path returns
// without a verdict having been written, that is a harness failure by
// definition, and this is the last chance to say so.
process.on("exit", () => {
    if (finished) return;
    finish({
        harnessFailure: true,
        summary: "the grader exited without reaching a verdict",
        detail: {},
    });
});

// --- untouched-workspace detection --------------------------------------

function hashTree(root) {
    const out = {};
    const walk = (dir) => {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            if (entry.name === "node_modules" || entry.name === ".git") continue;
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) walk(full);
            else if (entry.isFile()) {
                const rel = path.relative(root, full);
                out[rel] = createHash("sha256").update(fs.readFileSync(full)).digest("hex");
            }
        }
    };
    if (fs.existsSync(root)) walk(root);
    return out;
}

function isUntouched() {
    if (!fs.existsSync(MANIFEST)) return false;
    const pristine = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
    const current = hashTree(path.join(WORKSPACE, "src"));
    const keys = new Set([...Object.keys(pristine), ...Object.keys(current)]);
    for (const k of keys) if (pristine[k] !== current[k]) return false;
    return true;
}

if (isUntouched()) {
    finish({
        reward: 0,
        summary: "the workspace is byte-identical to the starting state; nothing was implemented",
        detail: { untouched: 1, counters: { rules_passed: 0 } },
    });
    process.exit(0);
}

// --- run the spec -------------------------------------------------------

const result = spawnSync(
    process.execPath,
    [
        path.join(GRADE_DIR, "node_modules", "vitest", "vitest.mjs"),
        "run",
        "--config",
        path.join(GRADE_DIR, "vitest.config.ts"),
        "--reporter=json",
        "--reporter=default",
        `--outputFile.json=${REPORT}`,
    ],
    {
        cwd: GRADE_DIR,
        encoding: "utf8",
        env: {
            ...process.env,
            VERIFY_WORKSPACE: WORKSPACE,
            CI: "1",
            NODE_OPTIONS: "--max-old-space-size=2048",
        },
        maxBuffer: 64 * 1024 * 1024,
        timeout: Number(process.env.VERIFY_SPEC_TIMEOUT_MS ?? 900000),
    }
);

const stdout = result.stdout ?? "";
const stderr = result.stderr ?? "";
fs.writeFileSync(path.join(OUT_DIR, "spec-stdout.txt"), stdout);
fs.writeFileSync(path.join(OUT_DIR, "spec-stderr.txt"), stderr);

// A killed runner is never graded, whatever it managed to leave on disk. The
// timeout path is the one that most wants to be mistaken for a verdict: vitest
// writes its report incrementally enough that a run cut off partway can leave a
// file naming real failures, and grading those would report "n rules failed"
// about tests that never ran. A wall clock is not evidence about a candidate.
if (result.error || result.signal) {
    finish({
        harnessFailure: true,
        summary:
            `the spec runner did not exit on its own (signal ${result.signal ?? "none"}` +
            `, error ${result.error ? String(result.error.code ?? result.error.message) : "none"}` +
            "); it was killed, most likely by the grader's own timeout",
        detail: {
            specTimeoutMs: Number(process.env.VERIFY_SPEC_TIMEOUT_MS ?? 900000),
            stdoutTail: stdout.slice(-4000),
            stderrTail: stderr.slice(-4000),
        },
    });
    process.exit(0);
}

if (!fs.existsSync(REPORT)) {
    finish({
        harnessFailure: true,
        summary: "the spec run produced no report; the candidate's module graph probably failed to load",
        detail: { stdoutTail: stdout.slice(-4000), stderrTail: stderr.slice(-4000) },
    });
    process.exit(0);
}

let report;
try {
    report = JSON.parse(fs.readFileSync(REPORT, "utf8"));
} catch (err) {
    finish({
        harnessFailure: true,
        summary: "the spec run left a report that is not readable JSON; it was cut off mid-write",
        detail: { error: String(err), stderrTail: stderr.slice(-4000) },
    });
    process.exit(0);
}
const assertions = [];
for (const file of report.testResults ?? []) {
    for (const a of file.assertionResults ?? []) {
        assertions.push({
            name: a.fullName ?? a.title ?? "",
            status: a.status,
            messages: (a.failureMessages ?? []).map((m) => String(m).split("\n").slice(0, 14).join("\n")),
        });
    }
}

if (assertions.length === 0) {
    finish({
        harnessFailure: true,
        summary: "no test ran; collection failed",
        detail: { stdoutTail: stdout.slice(-4000), stderrTail: stderr.slice(-4000) },
    });
    process.exit(0);
}

// Three classes of assertion, and the difference between the first two is the
// difference between "this submission is wrong" and "this grader is broken".
//
//   absent:: the capability is not present -- nothing opens a connection, or a
//            frame that arrives changes nothing. That is an answer, and a wrong
//            one. It is graded 0.0 like any other wrong answer, because a real
//            zero that reports itself as a harness failure is indistinguishable
//            from a verifier that fell over, and every partial submission that
//            never got as far as opening the stream would land there.
//   seam::   the harness could not drive the capability. Only the control
//            classification qualifies: it is the one step that has to infer the
//            candidate's shape rather than observe its behaviour.
//   rule::   a graded rule.
const absent = assertions.filter((a) => a.name.includes("absent::"));
const seam = assertions.filter((a) => a.name.includes("seam::"));
const rules = assertions.filter((a) => a.name.includes("rule::"));
const absentFailures = absent.filter((a) => a.status !== "passed");
const seamFailures = seam.filter((a) => a.status !== "passed");
const ruleFailures = rules.filter((a) => a.status !== "passed");

const counters = {
    seam_checks: seam.length + absent.length,
    seam_failures: seamFailures.length,
    capability_absent: absentFailures.length,
    rules_total: rules.length,
    rules_passed: rules.length - ruleFailures.length,
};

if (absentFailures.length > 0) {
    finish({
        reward: 0,
        summary:
            "the capability is not present: " +
            absentFailures.map((f) => f.name).join("; ") +
            ` (${ruleFailures.length} of ${rules.length} graded rules also failed)`,
        detail: { counters, absentFailures, ruleFailures },
    });
    process.exit(0);
}

if (seamFailures.length > 0) {
    finish({
        harnessFailure: true,
        summary: `could not drive the capability: ${seamFailures.map((f) => f.name).join("; ")}`,
        detail: { counters, seamFailures, ruleFailures },
    });
    process.exit(0);
}

if (rules.length === 0) {
    finish({
        harnessFailure: true,
        summary: "the seam resolved but no graded rule ran",
        detail: { counters },
    });
    process.exit(0);
}

// The suite declared, before it ran anything, how many rules it meant to grade.
// A shortfall means tests went missing rather than failing, and passing the
// survivors is not a verdict -- it is a smaller task nobody asked for.
const censusFile = path.join(OUT_DIR, "expected-rules.json");
if (fs.existsSync(censusFile)) {
    let expected = 0;
    try {
        expected = JSON.parse(fs.readFileSync(censusFile, "utf8")).expected_rules ?? 0;
    } catch {
        expected = 0;
    }
    counters.rules_expected = expected;
    if (expected > 0 && rules.length !== expected) {
        finish({
            harnessFailure: true,
            summary: `the suite meant to grade ${expected} rules but the reporter accounted for ${rules.length}`,
            detail: { counters, ruleFailures, stderrTail: stderr.slice(-4000) },
        });
        process.exit(0);
    }
} else {
    finish({
        harnessFailure: true,
        summary: "the suite never declared how many rules it grades; it did not reach its own setup",
        detail: { counters, stderrTail: stderr.slice(-4000) },
    });
    process.exit(0);
}

if (ruleFailures.length > 0) {
    finish({
        reward: 0,
        summary: `${ruleFailures.length} of ${rules.length} graded rules failed`,
        detail: { counters, ruleFailures },
    });
    process.exit(0);
}

finish({
    reward: 1,
    summary: `all ${rules.length} graded rules passed`,
    detail: { counters },
});
process.exit(0);
