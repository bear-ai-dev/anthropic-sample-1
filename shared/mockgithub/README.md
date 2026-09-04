# mockgithub

A self-contained, dependency-free fake of GitHub behind the read-only tool surface of the
official `github/github-mcp-server`, for RL task sandboxes. It is the sibling of `mocklinear`
and shares its core: one daemon owns the state, the stdio shim and the CLI are stateless
forwarders, the verifier reaches state through a token-gated admin plane.

## Process model

```
python3 -m mockgithub --scenario public.json --port 4570      (daemon, one per sandbox)
        ▲ HTTP loopback                        ▲
  bin/mockgithub  (stdio MCP shim,       bin/mockgithub github <tool> ...  (CLI)
   spawned by Claude Code)                (run from bash by mini-SWE or a person)
```

- `POST /mcp/github` speaks JSON-RPC 2.0: `initialize`, `ping`, `tools/list`, `tools/call`,
  `prompts/list`, `resources/list`; notifications answer `202`.
- `GET /healthz` answers `{"ok": true, "services": ["github"]}` without a token.
- `/_admin/{health,snapshot,calls,reseed,faults}` require the `x-mockgithub-admin-token`
  header to equal `MOCKGITHUB_ADMIN_TOKEN` from the daemon's environment; any other case is
  `403 {"error":"forbidden"}`.
- Every call is journalled in memory and, when `MOCKGITHUB_JOURNAL` is set, appended to that
  JSONL file: `service, tool, args, via (http|mcp|cli), outcome, error_kind, duration_ms,
  result_chars, page`. The file is created empty (mode 0600) when the daemon starts, so a
  missing file means the daemon never ran and an empty one means no tool was called.

## Running

```
cd shared
python3 -m mockgithub --scenario mockgithub/tests/fixtures/github.json --port 4570 --seed 7
MOCKGITHUB_URL=http://127.0.0.1:4570 python3 -m mockgithub.client github tools
MOCKGITHUB_URL=http://127.0.0.1:4570 python3 -m mockgithub.client github get_me
python3 -m mockgithub.client github list_issues --owner ExampleCo --repo membership-ledger --state OPEN
python3 -m mockgithub.client github search_issues --query -- "-label:docs is:open"
python3 -m mockgithub.client github issue_read --json '{"method":"get","owner":"ExampleCo","repo":"membership-ledger","issue_number":38}'
python3 -m mockgithub.check public.json holdout.json
```

`bin/mockgithub` is the shell wrapper the image installs (`PYTHONPATH` from
`MOCKGITHUB_PYTHONPATH`, default `/opt/mockgithub`). A bare `mockgithub` (or `mockgithub github`)
speaks MCP over stdio; when stdin is a TTY, hits EOF before a request, or stays silent for
`MOCKGITHUB_STDIO_IDLE_SEC` (default 10) it prints usage and exits 0. With arguments it is the
CLI: flag values are typed (`true`/`false`, integers), `--json` merges last, a value that starts
with a dash must follow `--`. The CLI prints exactly the text blocks the tool returned (a resource
block prints its text), exits 1 when the tool reports `isError` or answers a single block of
vendor error text starting `Error: ` (no GitHub answer does), 2 on misuse or when the daemon
is unreachable (`mockgithub daemon not reachable at <url>`) or does not serve GitHub
(`github is not available here`).

## Tools

The sixteen read-only tools of github-mcp-server's default toolsets: `get_me`, `issue_read`,
`list_issues`, `search_issues`, `get_label`, `pull_request_read`, `list_pull_requests`,
`search_pull_requests`, `get_file_contents`, `list_commits`, `get_commit`, `search_code`,
`list_branches`, `list_tags`, `list_releases`, `search_users`. Results are compact JSON in one
text block (`json.dumps(..., separators=(",", ":"))`); `pull_request_read get_diff` and
`get_commit detail=raw` return unified diff text; `get_file_contents` on a file returns the text
`successfully downloaded text file (SHA: <blob sha>)` plus an embedded resource
`repo://{owner}/{repo}/refs/heads/{ref}/contents/{path}` (or `.../sha/{sha}/contents/{path}`),
on a directory a compact JSON list of `{name, path, type, size, sha}`.

REST-style lists page with `page`/`perPage`; `list_issues` and `get_review_comments` are
GraphQL-shaped and page with `perPage`/`after` where cursors are `base64("cursor:N")`.
Search queries understand `is:issue|pr|open|closed|merged|unmerged|draft`, `type:`, `state:`,
`label:`, `author:`, `assignee:`, `repo:`, `org:`/`user:`, `in:title|body`, `-negation`,
`"quoted phrases"` and bare words over title and body; `search_code` adds `path:`, `filename:`,
`extension:` and matches bare words against file content at each default branch head.

Errors carry `isError: true` and github-mcp-server's texts: rate limit
`failed to <op>: GitHub API rate limit exceeded. Retry after 1m0s.`, transient failure
`failed to <op>: 502 Bad Gateway []`, bad arguments verbatim (`missing required parameter: owner`),
missing entities `failed to <op>: GET https://api.github.com/repos/<path>: 404 Not Found []`.
An unknown id answers the same text in every estate.

## Scenario format

```
{ "version": 1, "clock": "2026-03-04T10:00:00Z", "faults": {"enabled": true, "rules": [...]},
  "github": { "viewer": login, "users": [{login, name, email, company?, location?, bio?, created_at?}],
    "repos": [{ owner, name, default_branch, description, labels[{name,color,description}],
      milestones[{number,title,state,due_on}],
      commits[{key, message, author, date, parents[keys], files[{path, status, content|null}]}],
      branches[{name, head: key}], tags[{name, commit: key}], releases[{tag, name, body, created_at}],
      issues[{number, title, body, state, user?, labels[], assignees[], milestone, created_at,
              updated_at?, closed_at, comments[{key, user, body, created_at}], sub_issues[], parent}],
      pulls[{number, title, body, state, merged, draft, head{ref, sha: key}, base{ref}, user, labels[],
             created_at, updated_at?, merged_at, closed_at?, reviews[{user, state, body, submitted_at}],
             review_comments[{path, line, body, user, created_at, diff_hunk?}], comments[],
             check_runs[{name, status, conclusion}], statuses[{context, state, description?}]}] }] } }
```

Authors write human keys. Commit shas are `sha1(f"{seed}:github:commit:{owner}/{name}:{key}")`
(40 hex), blob shas derive from `{owner}/{name}:{commit key}:{path}`, every numeric id is
`ids.number_for(seed, "github", kind, key)`. A file's content at a ref is the newest version on
that line of history; a `content: null` entry removes it. Dangling references (unknown user,
label, milestone, commit) fail the load with the location that names them. `mockgithub.check`
validates scenarios and refuses estates that share repositories, logins, emails, issue or pull
numbers, branch names, commit keys or tag names.

## Faults

Rules match `(service, tool)` with `*` wildcards and are pure functions of
`(seed, service, tool, call count)`: `throttle_every`/`throttle_burst`, `server_error_every`,
`max_page_size` (caps `perPage`; cursors still walk to the end), `latency_seconds`.
`POST /_admin/faults {"enabled": false}` switches them off.

## Development

```
cd shared
uv venv .venv-mockgithub && uv pip install --python .venv-mockgithub/bin/python pytest pytest-cov ruff mypy mcp
.venv-mockgithub/bin/pytest mockgithub/tests --cov=mockgithub --cov-fail-under=100 -q
.venv-mockgithub/bin/ruff check mockgithub && .venv-mockgithub/bin/ruff format --check mockgithub
.venv-mockgithub/bin/mypy --strict mockgithub
.venv-mockgithub/bin/python mockgithub/tests/smoke_test.py
```

Runtime code imports only the standard library; every file is at most 200 lines, one tool per
file under `github/tools/`, no comments or docstrings (this file carries the prose).
