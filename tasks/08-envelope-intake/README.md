# Task 08 — envelope intake router

## Desk mailbox

The box serves a copy of the smoke desk's own mailbox (`inbox@desk.internal`)
on `127.0.0.1:4570`: seventeen threads, forty-one messages at the scenario clock,
built around the same addresses and Message-IDs `sandbox/seed.ts` and
`sandbox/smoke.jsonl` already carry — Pat Ryan's and Dana Ekwueme's exchanges
continued past them — plus an internal intake handover, other customers writing
in, the desk's own replies, and machine mail down to a venue newsletter and a
statement notice.

It is context and nothing else. The handover identifies the incomplete seams
but does not replace the policy in `instruction.md`; grading is unchanged —
`tests/compute_reward.py` and the graded run read none of it — and a solver who
never opens the mailbox can still score 1.0.

Under Claude Code it arrives as the MCP server `gmail` declared in `task.toml`;
under any harness with a shell it is the `gmail` command (`gmail tools` lists
what it answers). Both forward to the single daemon `task-init.sh` starts,
which journals every call to a root-only path; `tests/test.sh` keeps a copy at
`/logs/verifier/gmail-calls.jsonl` as evidence of what was consulted, and never
reads it back.
