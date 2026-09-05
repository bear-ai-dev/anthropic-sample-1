"""Read the suite's reports and say how many graded rules held.

Two jobs, one file:

  score.py REPORT LOG_DIR   print `passed total failed-rule-names` and exit 0
                            when every rule held, 1 when one did not, 2 when
                            the report could not be read, 3 when the runs did
                            not get far enough to have an opinion.

  score.py --unfinished DIR print the name of every spec file that, across all
                            the reports in DIR, still has a case nobody reached.
                            That is the list worth running again.

That last distinction matters more than it looks. A run the kernel killed for
memory leaves its unreached cases in the report as `pending` with nothing to say
about them. Counting those as wrong answers turns a starved container into a
graded zero against a submission that was never asked, which is the failure this
guards against: a broken harness and a wrong answer look identical from the
verdict alone. A case that genuinely failed carries the assertion that
failed; one that never ran carries nothing, and that is the discriminator used
here.

Cases can appear more than once, because a file that came back incomplete is
tried again and every attempt's report is merged. The definitive outcome wins
over silence, and a failure wins over a pass: a rule that broke on any attempt
that reached it did not hold.
"""

import json
import pathlib
import sys

EXPECTED_RULES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12", "R13"]

# The graded rules are split across these six files, one worker per file.
EXPECTED_FILES = [
    "rules-media",
    "rules-sections",
    "rules-documents",
    "rules-scope",
    "rules-timing",
    "rules-lifecycle",
    "rules-concurrency",
]

PASSED, FAILED, UNRUN = "passed", "failed", "unrun"


def rule_of(name: str) -> str:
    head = name.strip().split(" ", 1)[0]
    return head if head in EXPECTED_RULES else "?"


def outcome_of(case: dict) -> str:
    if case.get("status") == "passed":
        return PASSED
    messages = case.get("failureMessages") or []
    # A case that ran out of clock says nothing about the candidate. The suite
    # drives a real page and a scenario that opens four of them takes seconds on
    # a machine of its own and minutes on a host running ten other suites, so a
    # timeout here is a starved container and is treated the way a killed worker
    # is: the case is tried again, and a run that never gets past it reports a
    # harness failure rather than a rule that did not hold.
    if any("Test timed out" in str(message) for message in messages):
        return UNRUN
    if messages:
        return FAILED
    # Not passed, and nothing to say about why: this case never ran.
    return UNRUN


def read(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def cases_of(report: dict):
    for suite in report.get("testResults") or []:
        for case in suite.get("assertionResults") or []:
            where = " ".join(case.get("ancestorTitles") or [])
            yield rule_of(where), f"{where} :: {case.get('title', '')}", outcome_of(case)


def unfinished(directory: str) -> int:
    """Which spec files still have a case nobody reached?"""
    rank = {UNRUN: 0, PASSED: 1, FAILED: 2}
    best: dict[str, dict[str, str]] = {name: {} for name in EXPECTED_FILES}
    for path in sorted(pathlib.Path(directory).glob("*.json")):
        try:
            report = read(str(path))
        except Exception:  # noqa: BLE001
            continue
        for suite in report.get("testResults") or []:
            stem = pathlib.Path(suite.get("name") or "").name.split(".")[0]
            if stem not in best:
                continue
            for case in suite.get("assertionResults") or []:
                title = f"{' '.join(case.get('ancestorTitles') or [])} :: {case.get('title', '')}"
                outcome = outcome_of(case)
                held = best[stem].get(title)
                if held is None or rank[outcome] > rank[held]:
                    best[stem][title] = outcome
    for name in EXPECTED_FILES:
        cases = best[name]
        if not cases or any(outcome == UNRUN for outcome in cases.values()):
            print(name)
    return 0


def main() -> int:
    if sys.argv[1:2] == ["--unfinished"]:
        return unfinished(sys.argv[2])

    report_path, _log_dir = sys.argv[1], sys.argv[2]
    try:
        report = read(report_path)
    except Exception as exc:  # noqa: BLE001
        print(f"unreadable report: {exc}", file=sys.stderr)
        return 2

    if not (report.get("testResults") or []):
        print("report holds no test results", file=sys.stderr)
        return 2

    # The best answer anyone got for each case, across every attempt.
    rank = {UNRUN: 0, PASSED: 1, FAILED: 2}
    best: dict[str, tuple[str, str]] = {}
    for rule, case, outcome in cases_of(report):
        if rule == "?":
            continue
        held = best.get(case)
        if held is None or rank[outcome] > rank[held[1]]:
            best[case] = (rule, outcome)

    outcome_by_rule = {rule: True for rule in EXPECTED_RULES}
    reached: set[str] = set()
    unrun: list[str] = []
    for case, (rule, outcome) in sorted(best.items()):
        if outcome == UNRUN:
            unrun.append(case[:60])
            continue
        reached.add(rule)
        if outcome == FAILED:
            outcome_by_rule[rule] = False

    missing = [rule for rule in EXPECTED_RULES if rule not in reached]
    if unrun or missing or not best:
        detail = ",".join(unrun[:6]) or ",".join(missing) or "no cases at all"
        print(f"the suite did not reach every rule: {detail}", file=sys.stderr)
        return 3

    failed = [rule for rule in EXPECTED_RULES if not outcome_by_rule[rule]]
    passed = len(EXPECTED_RULES) - len(failed)
    print(f"{passed} {len(EXPECTED_RULES)} {','.join(failed) if failed else '-'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
