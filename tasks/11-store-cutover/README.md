# Task 11 — store cutover

## Repository history

The box serves a copy of the `ExampleCo/membership-ledger` repository on
`127.0.0.1:4570`: the pull request that carried ap-2's move, #46, with the
reviews, review comments and check runs it collected, the commit history that
put `docs/prior-cutover/` and the rest of the workspace in the tree, and the
six unrelated pull requests and seven issues around them.

It is context and nothing else. The reviews describe what the archived files
are; none states a rule or paraphrases `instruction.md`, and no graded check
reads any of it — `tests/test.sh` and the independent model are unchanged, and
nothing in a verdict depends on whether the repository was opened at all.

Under Claude Code it arrives as the MCP server `github` declared in
`task.toml`; under any harness with a shell it is the `github` command
(`github tools` lists what it answers). Both forward to the single daemon
`task-init.sh` starts, which journals every call to a root-only path;
`tests/test.sh` keeps a copy at `/logs/verifier/github-calls.jsonl` as evidence
of what was consulted, and never reads it back.
