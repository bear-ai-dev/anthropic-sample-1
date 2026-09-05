# mocklinear

A self-contained, dependency-free fake of Linear that answers the official Linear MCP
server's read-only tool surface. It exists so an RL task can put a believable Linear
workspace inside its sandbox: the agent consults tickets, comments, projects and
documents through the same tool names, argument names and result shapes it would see
against the real server, and the verifier can watch what was consulted without the agent
ever holding a credential.

Everything here is Python 3.11 standard library. Nothing is installed; the package is
copied into an image and run with `PYTHONPATH`.

## What it answers

Twenty read tools, one file each under `linear/tools/`:

| | |
| --- | --- |
| issues | `list_issues`, `get_issue`, `list_comments`, `get_attachment` |
| workflow | `list_issue_statuses`, `get_issue_status`, `list_issue_labels` |
| projects | `list_projects`, `get_project`, `list_project_labels`, `list_milestones`, `get_milestone` |
| planning | `list_cycles` |
| documents | `list_documents`, `get_document` |
| people | `list_teams`, `get_team`, `list_users`, `get_user` |
| help | `search_documentation` |

An issue carries its `state`, `team`, `assignee`, `creator`, `labels`, `project`,
`projectMilestone`, `cycle` and `parent`; a team carries its `members`; a label says which
`team` owns it (null for a workspace label).

Every result is `json.dumps(payload, indent=2)` inside one `text` block, which is how the
real Linear server returns its JSON. List tools answer
`{"<plural>": [...], "pageInfo": {hasNextPage, hasPreviousPage, startCursor, endCursor}}`
and page through Linear-style cursors, which are item ids: pass `after` the last id of a
page, or `before` the first. `limit` defaults to 50. Get tools answer the bare entity.

Errors arrive the way the real server sends them, as an `isError` result whose text is
vendor-shaped rather than a protocol error:

```
Entity not found: Issue - Could not find referenced Issue.
Invalid arguments: parameter orderBy must be one of createdAt, updatedAt
Linear API rate limit exceeded. Please retry after a short delay.
Linear API error (INTERNAL_ERROR): Something went wrong
```

An id nobody minted always reads as the same "entity not found" text, so a holdout estate
cannot be fingerprinted by asking for a sandbox id.

## Why one daemon and stateless shims

State lives in exactly one place. `python3 -m mocklinear` owns the world on
`127.0.0.1:4570`: one immutable `World` built from one scenario JSON, one deterministic
`FaultInjector`, one `Journal`. Every client is a stateless forwarder:

- an MCP client (Claude Code) spawns `mocklinear` with no arguments and speaks JSON-RPC
  over stdio; the shim POSTs each message to `/mcp/linear` and writes the answer back;
- a shell agent runs `linear <tool> --name value`, which posts one `tools/call` and prints
  the text blocks.

Because no shim holds state, per-tool fault counters keep counting across processes, the
journal survives every shim exiting, and the verifier has exactly one process to kill,
one port to prove free, and one daemon to restart on the holdout estate.

## Running it

```
PYTHONPATH=/opt/mocklinear python3 -m mocklinear \
  --scenario /opt/linear-sandbox/public.json --host 127.0.0.1 --port 4570 --seed 7
```

It prints one line (`mocklinear listening on http://127.0.0.1:4570 (scenario=..., seed=7)`)
and serves:

| route | who | answer |
| --- | --- | --- |
| `POST /mcp/linear` | agent | JSON-RPC: `initialize`, `ping`, `tools/list`, `tools/call`, `prompts/list`, `resources/list` |
| `POST /mcp/<other>` | agent | `404 {"error": "unknown service: <other>"}` |
| `GET /healthz` | anyone | `{"ok": true, "services": ["linear"]}` |
| `/_admin/{health,snapshot,calls,reseed,faults}` | verifier | token-gated, see below |

Environment:

| variable | meaning |
| --- | --- |
| `MOCKLINEAR_ADMIN_TOKEN` | the only credential in the system; gates `/_admin/*` |
| `MOCKLINEAR_JOURNAL` | append every call as JSONL to this path |
| `MOCKLINEAR_URL` | where the client looks for the daemon (default `http://127.0.0.1:4570`) |
| `MOCKLINEAR_STDIO_IDLE_SEC` | seconds the stdio shim waits for a first request (default 10) |
| `MOCKLINEAR_PYTHONPATH` | where `bin/mocklinear` finds the package (default `/opt/mocklinear`) |
| `MOCKLINEAR_VERBOSE` | log every HTTP request to stderr |

## The command

`bin/mocklinear` is the wrapper a task installs on `PATH` (usually also symlinked as
`linear`):

```
linear                       speak MCP over stdio; this is how an MCP client runs it
linear tools                 list the tools with their JSON schemas
linear get_issue --id WEB-611
linear list_issues --assignee me --state started --limit 20
linear list_issues --json '{"team": "WEB", "updatedAt": "-P1W"}'
linear list_issues --updatedAt -- -P1W
```

Flag values are typed the way a JSON client would send them: `20` becomes a number,
`true` a boolean, everything else a string; `--json` merges over the flags. A value that
begins with a dash is refused unless it comes after `--`, so a filter can never be
swallowed as a flag. The command exits 0 on success, 1 when the tool answered `isError`
(the vendor text still goes to stdout), and 2 for a usage error, an unknown tool, or a
daemon that is not listening.

Run with no arguments it becomes the stdio MCP server. To keep a bash agent from hanging
on it, it prints the usage and exits 0 when stdin is a terminal, when stdin reaches EOF
before the first request, or when no request arrives within `MOCKLINEAR_STDIO_IDLE_SEC`
seconds. A real MCP client sends `initialize` immediately, so it never trips.

## The scenario

One JSON file per estate. Authors write human keys; the loader derives every opaque id as
a uuid formatted from `sha1(f"{seed}:linear:{kind}:{key}")`, so two estates built with
different seeds share no identifier, and the same estate and seed always produce the same
ids.

```json
{
  "version": 1,
  "clock": "2026-03-04T10:00:00Z",
  "faults": {"enabled": true, "rules": []},
  "linear": {
    "organization": {"name": "ExampleCo", "urlKey": "ExampleCo"},
    "viewer": "u-dana",
    "users": [{"key": "u-dana", "name": "Dana Whitfield", "displayName": "dana",
               "email": "dana@ExampleCo.example", "active": true}],
    "teams": [{"key": "WEB", "name": "Web", "description": "...", "members": ["dana"],
               "states": [{"key": "web-progress", "name": "In Progress", "type": "started",
                           "position": 2, "color": "#f2c94c"}],
               "labels": [{"key": "web-regression", "name": "Regression", "color": "#f2994a"}],
               "cycles": [{"number": 43, "name": "Cycle 43",
                           "startsAt": "2026-03-02T00:00:00Z", "endsAt": "2026-03-16T00:00:00Z"}]}],
    "labels": [{"key": "bug", "name": "Bug", "color": "#eb5757"}],
    "projects": [{"key": "door-ops", "name": "Door operations", "description": "...",
                  "state": "started", "lead": "u-dana", "teams": ["WEB"],
                  "startDate": "2026-02-02", "targetDate": "2026-03-27",
                  "createdAt": "...", "updatedAt": "...", "labels": ["bug"],
                  "milestones": [{"key": "m-scan", "name": "Scanner reliability",
                                  "targetDate": "2026-03-20"}]}],
    "documents": [{"key": "door-runbook", "title": "Door night runbook", "content": "# ...",
                   "project": "door-ops", "issue": "WEB-611", "creator": "u-dana",
                   "createdAt": "...", "updatedAt": "..."}],
    "issues": [{"identifier": "WEB-611", "title": "...", "description": "...",
                "team": "WEB", "state": "In Progress", "assignee": "u-dana",
                "creator": "u-milo",
                "priority": 1, "estimate": 3, "labels": ["bug"], "project": "door-ops",
                "milestone": "m-scan", "cycle": 43, "parent": null,
                "createdAt": "...", "updatedAt": "...", "startedAt": "...",
                "completedAt": null, "canceledAt": null, "dueDate": "2026-03-10",
                "branchName": "dana/web-611-reentry-scan",
                "attachments": [{"key": "att-door-scan", "title": "door-scan.mov",
                                 "subtitle": "...", "url": "https://..."}],
                "comments": [{"key": "c-611-1", "body": "...", "user": "u-milo",
                              "createdAt": "...", "parent": null}]}]
  }
}
```

Notes:

- `clock` is the mock's "now". Every relative filter resolves against it, and
  `list_cycles --type current|previous|next` is decided by it. A relative value is an
  ISO 8601 duration (`-P1W`, `-P1M`, `-P2Y`, `-P1Y2M1DT2H`, where a month is 30 days and a
  year 365) or a short form (`7d`, `-30m`).
- Fixture keys are for the author, not the agent. Inside the scenario a `state` is matched
  by its key or its name within the issue's team, and a `cycle` by its number; but a tool
  argument only ever accepts what a real Linear client could know — an id, an issue
  identifier, a user name, display name, email or `me`, a status name or type, a team key,
  name or id, a project, milestone or label name, a document slug or title. Asking for
  `web-progress` or `door-ops` finds nothing, exactly as it would against Linear. An issue that names a team, state, cycle, assignee or creator the workspace does
  not have fails the load, so a broken fixture never reaches the agent.
- `branchName` is optional. Without it the loader derives
  `<assignee displayName>/<identifier lowercased>-<slugged title, 40 chars>`, which is what
  Linear does.
- `documents[].issue` is optional and only feeds `list_documents --issue`.
- `labels` at the top level are workspace-wide; labels inside a team belong to that team.
  `list_issue_labels --team WEB` answers the workspace labels plus WEB's own.
- The section may be omitted entirely; the daemon then serves an empty workspace.

Validate estates, and prove a sandbox and a holdout share no human key, with:

```
PYTHONPATH=/opt/mocklinear python3 -m mocklinear.check public.json holdout.json
```

It exits 1 printing `shared <kind>: <value>` for every issue identifier, user key, email,
name, team key, project key, document key or attachment key the two have in common, and
exits 0 printing `ok: 2 scenarios, disjoint` otherwise. Run it at image build time.

## Faults

Real APIs misbehave. Rules are matched on `(service, tool)` with `*` wildcards, and every
decision is a pure function of `(seed, service, tool, call count)` — the phase comes from
`sha256(f"{seed}:linear:{tool}")` — so a given agent behaviour always meets the same
sequence of faults. Counters advance on every call whether or not a rule matches.

```json
"faults": {"enabled": true,
           "rules": [{"service": "linear", "tool": "list_issues",
                      "throttle_every": 5, "throttle_burst": 2,
                      "server_error_every": 0, "max_page_size": 25,
                      "latency_seconds": 0.0}]}
```

| rule | effect |
| --- | --- |
| `throttle_every` N, `throttle_burst` K | every Nth call is refused, K in a row, as the rate-limit text |
| `server_error_every` N | every Nth call answers the internal-error text |
| `max_page_size` K | caps `limit` (correct cursors are still returned, so paging still reaches the end) |
| `latency_seconds` S | sleeps before answering |

Through the CLI a fault is the same text on stdout with exit 1. `POST /_admin/faults
{"enabled": false}` switches them off for the verifier's own drive.

## The admin plane

Everything under `/_admin/` requires the header `x-mocklinear-admin-token` to equal
`$MOCKLINEAR_ADMIN_TOKEN`. A missing header, a wrong token and a daemon started with no
token configured all answer the identical `403 {"error": "forbidden"}`.

| request | answer |
| --- | --- |
| `GET /_admin/health` | `{"ok": true}` |
| `GET /_admin/snapshot` | `{clock, seed, scenario_sha256, services, linear: {issues: {identifier: id}, users, teams, projects, milestones, documents, attachments}}` |
| `GET /_admin/calls` | `{"calls": [{seq, at, service, tool, args, via, outcome, error_kind, duration_ms, result_chars, page}], "fault_counters": {"linear:list_issues": 3}}` |
| `POST /_admin/reseed` | `{"scenario": {...}, "seed": 41}` → new world, new fault counters, empty journal |
| `POST /_admin/faults` | `{"enabled": false}` |

The snapshot lets a scorer map human keys to the opaque ids the tools returned without
importing this package. `via` is `mcp`, `cli` or `http`, so the journal shows how the
agent reached the workspace. `via` is client-supplied — it comes from the
`x-mocklinear-via` header the shim or the CLI sets, and any caller can set it to anything —
so it is evidence about how a call arrived, never a fact to score. Agent-phase journals are evidence, never a reward input: the
trajectory is not gradeable, so a task grades the behaviour of the submitted artifact
re-driven against a holdout estate.

### Token lifecycle

The token is minted by the task's init script into a root-only file and passed to the
daemon in its environment, never on a command line, so `ps` shows nothing and
`/proc/<pid>/environ` is unreadable by the agent user. The agent needs no credential at
all: `POST /mcp/linear` is open on loopback. The verifier reads the token from its
root-only file, and mints a fresh one when it restarts the daemon on the holdout.

## Wiring a task

Copy the package into the image and install the wrapper. A task vendors
`shared/mocklinear/` into its own `environment/` without `tests/` (nothing outside
`tests/` needs it), and copies `bin/mocklinear` alongside it as `mocklinear-bin/mocklinear`:

```dockerfile
COPY --chown=root:root mocklinear/ /opt/mocklinear/mocklinear/
RUN rm -rf /opt/mocklinear/mocklinear/tests \
 && find /opt/mocklinear -name __pycache__ -prune -exec rm -rf {} + \
 && chmod -R a+rX /opt/mocklinear
COPY --chown=root:root --chmod=0755 mocklinear-bin/mocklinear /usr/local/bin/mocklinear
RUN ln -s /usr/local/bin/mocklinear /usr/local/bin/linear
RUN install -d -m 0700 -o root -g root /var/lib/task-data /var/lib/task-data/run /var/lib/task-data/journal
RUN install -d -m 0755 -o root -g root /opt/linear-sandbox
COPY --chown=root:root --chmod=0444 sandbox/linear/ /opt/linear-sandbox/
COPY --chown=root:root --chmod=0600 verifier-data/ /var/lib/task-data/verifier/
RUN PYTHONPATH=/opt/mocklinear python3 -m mocklinear.check \
      /opt/linear-sandbox/public.json /var/lib/task-data/verifier/holdout.json
ENV MOCKLINEAR_URL=http://127.0.0.1:4570 TZ=Etc/UTC PYTHONDONTWRITEBYTECODE=1
```

Start it from the image entrypoint, before readiness is signalled:

```sh
TOKEN=$(head -c 18 /dev/urandom | od -An -tx1 | tr -d ' \n')
printf '%s' "$TOKEN" > /var/lib/task-data/run/admin-token
chmod 0600 /var/lib/task-data/run/admin-token
MOCKLINEAR_ADMIN_TOKEN="$TOKEN" \
MOCKLINEAR_JOURNAL=/var/lib/task-data/journal/linear-calls.jsonl \
PYTHONPATH=/opt/mocklinear python3 -m mocklinear \
  --scenario "${MOCKLINEAR_SCENARIO:-/opt/linear-sandbox/public.json}" \
  --host 127.0.0.1 --port "${MOCKLINEAR_PORT:-4570}" --seed "${MOCKLINEAR_SEED:-7}" \
  > /tmp/task-infra/mocklinear.log 2>&1 &
echo $! > /tmp/task-infra/mocklinear.pid
# poll GET /healthz for up to 30 s, then touch /tmp/task-infra/.ready
```

Register it for an MCP-speaking harness and tell a bash harness the command exists:

```toml
[environment.env]
MOCKLINEAR_URL = "http://127.0.0.1:4570"

[[environment.mcp_servers]]
name = "linear"
transport = "stdio"
command = "/usr/local/bin/linear"

[environment.healthcheck]
command = "test -f /tmp/task-infra/.ready"
```

And in `tests/test.sh`, near the top, keep the evidence and take the workspace back:

```sh
cp /var/lib/task-data/journal/linear-calls.jsonl "$REWARD_DIR/linear-calls.jsonl" 2>/dev/null || true
kill "$(cat /tmp/task-infra/mocklinear.pid)" 2>/dev/null || true
pkill -f 'python3 -m mocklinear --scenario' || true
# loop until a Python bind probe on 4570 succeeds, then restart on the holdout with a
# fresh token and --seed 41 before driving the submitted artifact
```

The `pkill` pattern is anchored on `--scenario` so it never matches a `mocklinear.client`
shim (or another mock's daemon on another port).

## Working on it

From `shared/`:

```
uv venv .venv && uv pip install --python .venv/bin/python pytest pytest-cov ruff mypy mcp
.venv/bin/pytest --cov=mocklinear --cov-fail-under=100 -q
.venv/bin/ruff check mocklinear conftest.py
.venv/bin/ruff format --check mocklinear conftest.py
.venv/bin/mypy --strict mocklinear conftest.py
python3 mocklinear/tests/smoke_test.py
```

`mcp` is a development dependency only: `tests/integration/test_stdio_shim.py` drives the
stdio shim with the official MCP Python client, which is the only honest way to know the
shim really speaks the protocol. Nothing under `mocklinear/` imports it, and nothing
outside `tests/` imports anything but the standard library.

House rules for this package: no comments and no docstrings (prose lives here), every file
at most 200 lines, one responsibility per file and one tool per file, all intra-package
imports relative, and 100% line coverage with no `pragma: no cover`. `tests/unit` touches
no sockets and no subprocesses; `tests/integration` runs the daemon in a thread on port 0
and drives it the way a task will.
