# Task 01 — linearizable ticket scanning

## Linear workspace

The box serves a copy of the team's Linear workspace on `127.0.0.1:4570`: the
four tickets this task was cut from — `WEB-615`, `WEB-621`, `IOS-1474` and
`IOS-1675` — plus twenty-two unrelated ones across the WEB and IOS teams, with
the projects, cycles, documents, comments and attachments around them.

It is context and nothing else. The tickets say what hosts and door staff saw;
none states a rule or paraphrases `instruction.md`, and no graded rule reads
any of it — `tests/grader.py` is unchanged, and a solver who never opens the
workspace can still score 1.0.

Under Claude Code it arrives as the MCP server `linear` declared in
`task.toml`; under any harness with a shell it is the `linear` command
(`linear tools` lists what it answers). Both forward to the single daemon the
entrypoint starts, which journals every call to a root-only path;
`tests/test.sh` keeps a copy at `/logs/verifier/linear-calls.jsonl` as evidence
of what was consulted, and never reads it back.
