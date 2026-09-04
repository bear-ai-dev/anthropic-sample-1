# Task 04 — draft recovery

## Linear workspace

The box serves a copy of the team's Linear workspace on `127.0.0.1:4570`.
Three host reports and `WEB-565` identify the outdated draft layer, alongside
the form-revamp history and unrelated host work.

It is context only. Ownership, migration, lifecycle, media and concurrency
rules remain in `instruction.md` and the workspace recording, and no graded
check reads the Linear journal.

The service is available as the MCP server `linear` and the `linear` command.
The entrypoint journals calls to a root-only path, and `tests/test.sh` copies
that journal to `/logs/verifier/linear-calls.jsonl` as evidence only.
