# Task 02 — recurring event series

## Linear workspace

The box serves a copy of the team's Linear workspace on `127.0.0.1:4570`.
`IOS-2912`, `PRD-145` and `WEB-915` carry the product history and the broken
backend seam, alongside nine unrelated or adjacent issues across three teams.

It is context only. The tickets identify where the work starts and what hosts
reported; the recurrence rules remain in `instruction.md` and the workspace,
and no graded check reads the Linear journal.

The service is available as the MCP server `linear` and the `linear` command.
The entrypoint journals calls to a root-only path, and `tests/test.sh` copies
that journal to `/logs/verifier/linear-calls.jsonl` as evidence only.
