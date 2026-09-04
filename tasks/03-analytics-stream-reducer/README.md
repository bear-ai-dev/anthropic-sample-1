# Task 03 — live analytics stream

## Linear workspace

The box serves a copy of the team's Linear workspace on `127.0.0.1:4570`.
`IOS-2882`, `IOS-1223` and `WEB-607` carry the field reports and identify the
missing browser-side stream seam, alongside nine unrelated or adjacent issues.

It is context only. Stream ordering, snapshot and fallback behavior remain in
`instruction.md` and the shipped recordings, and no graded check reads the
Linear journal.

The service is available as the MCP server `linear` and the `linear` command.
The entrypoint journals calls to a root-only path, and `tests/test.sh` copies
that journal to `/logs/verifier/linear-calls.jsonl` as evidence only.
