# Task 12 — read-model rebuild

## Repository history

The box serves a copy of `ExampleCo/event-feed` on `127.0.0.1:4570`. Pull requests
#576, #578 and #581 preserve the previous cutover, declare generation v2 and
add its delivery fold. Five adjacent issues and unrelated repository work make
the relevant history discoverable rather than preselected.

It is context only. The cutover invariants, schemas and raw operational record
remain in `instruction.md` and the workspace, and no graded check reads the
GitHub journal.

The service is available as the MCP server `github` and the `github` command.
`task-init.sh` journals calls to a root-only path, and `tests/test.sh` copies
that journal to `/logs/verifier/github-calls.jsonl` as evidence only.
