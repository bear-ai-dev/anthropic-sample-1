# mockgmail

A self-contained, dependency-free fake of Gmail that answers the read tools of the common
Gmail MCP server (GongRzhe/Gmail-MCP-Server). It exists so an RL task can put a believable
mailbox inside its sandbox: the agent searches and reads mail through the same tool names,
argument names and plain-text result templates it would see against the real server, and
the verifier can watch what was consulted without the agent ever holding a credential.

Everything here is Python 3.11 standard library. Nothing is installed; the package is
copied into an image and run with `PYTHONPATH`. It is the sibling of `shared/mocklinear`
and shares its core (daemon, engine, faults, journal, admin plane, clients) file for file.

## What it answers

Four read tools, one file each under `gmail/tools/`:

| tool | arguments | answer |
| --- | --- | --- |
| `search_emails` | `query` (required), `maxResults` (default 10) | `ID: …\nSubject: …\nFrom: …\nDate: …\n` per message, newest first, joined by blank lines; `No emails found matching the query` when nothing matches |
| `read_email` | `messageId` | `Thread ID: …\nSubject: …\nFrom: …\nTo: …\nDate: …\n\n<body>` then, when there are attachments, `\n\nAttachments (N):\n- <filename> (<mimeType>, <KB> KB, ID: <attachmentId>)` |
| `list_email_labels` | — | `Found N labels (S system, U user):` followed by `System Labels:` and `User Labels:` blocks of `ID:`/`Name:`/`Type:` lines |
| `download_attachment` | `messageId`, `attachmentId`, `savePath?`, `filename?` | the daemon answers a JSON text block `{"mockgmail_attachment": {filename, mimeType, size, data_b64, savePath}}`; the client (stdio shim or CLI, running as the invoking user) writes the bytes under `savePath` (default: the working directory) and prints `Attachment downloaded successfully:\nFile: …\nSize: … bytes\nSaved to: <absolute path>` |

Every result is one plain-text block, exactly as the real server renders it. Errors are
text too, `Error: <message>`, and the `isError` flag is never set, because the real server
never sets it:

```
Error: Requested entity was not found.
Error: missing required parameter: query
Error: Rate Limit Exceeded
Error: Backend Error
```

An id nobody minted always reads as the same not-found text, so a holdout estate cannot be
fingerprinted by asking for a sandbox id. Through the CLI a Gmail error is the same text on
stdout with exit 1: the command recognises a single `Error: …` block (no legitimate Gmail
answer starts that way), so `set -e` and `$?` see a throttled or failed call.

### Query language

`search_emails` understands the usual Gmail operators, case-insensitively:

| operator | meaning |
| --- | --- |
| `from:` `to:` `cc:` `subject:` | substring of that header (`to:` and `cc:` over every recipient) |
| `has:attachment` | at least one attachment |
| `filename:` | substring of an attachment name (`filename:pdf` works) |
| `label:` | a label by id, key or name (`label:Label_1`, `label:support`, `label:Support`) |
| `in:inbox` `in:sent` `in:trash` `in:spam` `in:draft` `in:anywhere` | mailbox (`in:<label>` also works) |
| `is:unread` `is:read` `is:starred` `is:important` | flags |
| `after:` `before:` `newer:` `older:` | `YYYY/MM/DD` or `YYYY-MM-DD`, UTC midnight; `before` is exclusive |
| `newer_than:` `older_than:` | `Nh`, `Nd`, `Nw`, `Nm` (30 days), `Ny`, resolved against the scenario clock |
| bare word, `"quoted phrase"` | substring over subject, body, sender and recipients |
| `-term`, `-(…)` | negation |
| `a OR b`, `{a b}` | alternatives; `(a b)` groups; terms side by side are ANDed, and `OR` binds tighter than the implicit AND, as in Gmail |

An unknown operator is searched as plain text. An operator without a value, an unparseable
date or an unparseable age matches nothing rather than raising.

## Why one daemon and stateless shims

State lives in exactly one place. `python3 -m mockgmail` owns the mailbox on
`127.0.0.1:4570`: one immutable `World` built from one scenario JSON, one deterministic
`FaultInjector`, one `Journal`. Every client is a stateless forwarder:

- an MCP client (Claude Code) spawns `mockgmail` with no arguments and speaks JSON-RPC
  over stdio; the shim POSTs each message to `/mcp/gmail` and writes the answer back;
- a shell agent runs `gmail <tool> --name value`, which posts one `tools/call` and prints
  the text blocks.

The one client-side behaviour is `download_attachment`: the daemon (root) never touches the
agent's filesystem, so it hands the bytes to the shim or CLI, which resolves `savePath`
against its own working directory, refuses a `filename` that escapes it
(`resolve().is_relative_to()`), and writes the file as the invoking user. A write the
filesystem refuses (`savePath` is an existing file, a read-only directory, a full disk)
comes back as `Error: <os error>` text like every other Gmail error, and the shim keeps
serving.

Because no shim holds state, per-tool fault counters keep counting across processes, the
journal survives every shim exiting, and the verifier has exactly one process to kill,
one port to prove free, and one daemon to restart on the holdout estate.

## Running it

```
PYTHONPATH=/opt/mockgmail python3 -m mockgmail \
  --scenario /opt/gmail-sandbox/public.json --host 127.0.0.1 --port 4570 --seed 7
```

It prints one line (`mockgmail listening on http://127.0.0.1:4570 (scenario=..., seed=7)`)
and serves:

| route | who | answer |
| --- | --- | --- |
| `POST /mcp/gmail` | agent | JSON-RPC: `initialize`, `ping`, `tools/list`, `tools/call`, `prompts/list`, `resources/list` |
| `POST /mcp/<other>` | agent | `404 {"error": "unknown service: <other>"}` |
| `GET /healthz` | anyone | `{"ok": true, "services": ["gmail"]}` |
| `/_admin/{health,snapshot,calls,reseed,faults}` | verifier | token-gated, see below |

Environment:

| variable | meaning |
| --- | --- |
| `MOCKGMAIL_ADMIN_TOKEN` | the only credential in the system; gates `/_admin/*` |
| `MOCKGMAIL_JOURNAL` | append every call as JSONL to this path |
| `MOCKGMAIL_URL` | where the client looks for the daemon (default `http://127.0.0.1:4570`) |
| `MOCKGMAIL_STDIO_IDLE_SEC` | seconds the stdio shim waits for a first request (default 10) |
| `MOCKGMAIL_PYTHONPATH` | where `bin/mockgmail` finds the package (default `/opt/mockgmail`) |
| `MOCKGMAIL_VERBOSE` | log every HTTP request to stderr |

## The command

`bin/mockgmail` is the wrapper a task installs on `PATH` (usually also symlinked as `gmail`):

```
gmail                        speak MCP over stdio; this is how an MCP client runs it
gmail tools                  list the tools with their JSON schemas
gmail search_emails --query "from:pat.ryan is:unread" --maxResults 20
gmail read_email --messageId 3f9c1a2b7d4e5f60
gmail list_email_labels
gmail download_attachment --json '{"messageId": "...", "attachmentId": "...", "savePath": "mail"}'
gmail search_emails --query -- "-in:sent newer_than:7d"
```

Flag values are typed the way a JSON client would send them: `20` becomes a number,
`true` a boolean, everything else a string; `--json` merges over the flags. A value that
begins with a dash is refused unless it comes after `--`, so a negated query can never be
swallowed as a flag. The command exits 0 when the tool answered, 1 when the answer is a
Gmail `Error: …` text (a fault, a missing entity, a bad argument, or a download the client
could not write), and 2 for a usage error, an unknown tool, or a daemon that is not
listening.

Run with no arguments it becomes the stdio MCP server. To keep a bash agent from hanging
on it, it prints the usage and exits 0 when stdin is a terminal, when stdin reaches EOF
before the first request, or when no request arrives within `MOCKGMAIL_STDIO_IDLE_SEC`
seconds. A real MCP client sends `initialize` immediately, so it never trips.

## The scenario

One JSON file per estate. Authors write human keys; the loader derives every opaque id
from `sha1(f"{seed}:gmail:{kind}:{key}")`: message and thread ids are the first 16 hex
characters, an attachment id is the base64url of 48 hex characters. Two estates built with
different seeds share no identifier; the same estate and seed always produce the same ids.

```json
{
  "version": 1,
  "clock": "2026-03-04T10:00:00Z",
  "faults": {"enabled": true, "rules": []},
  "gmail": {
    "profile": {"emailAddress": "inbox@desk.internal"},
    "labels": [{"key": "support", "name": "Support", "type": "user"}],
    "threads": [{"key": "t-pat-marden-seat-block",
                 "messages": [{"key": "pat-marden-1",
                               "message_id": "<h-old-a1@lowfield.example>",
                               "from": "Pat Ryan <pat.ryan@lowfield.example>",
                               "to": ["inbox@desk.internal"], "cc": [],
                               "subject": "Seat block for the Marden Hall run",
                               "date": "2025-06-02T09:00:00Z",
                               "labels": ["INBOX", "support"],
                               "body_text": "Morning, ...", "body_html": null,
                               "in_reply_to": null, "references": [],
                               "attachments": [{"key": "att-plan", "filename": "plan.pdf",
                                                "mime_type": "application/pdf",
                                                "size": 143220, "size_only": true}]}]}]
  }
}
```

Notes:

- `clock` is the mock's "now"; `newer_than:` and `older_than:` resolve against it. The
  `Date` header is rendered from `date` in RFC 2822 form (`Mon, 02 Jun 2025 09:00:00 +0000`).
- The system labels `INBOX`, `SENT`, `UNREAD`, `STARRED`, `IMPORTANT`, `TRASH`, `SPAM`,
  `DRAFT` always exist (their id is their name). User labels get ids `Label_1`, `Label_2`,
  … in scenario order. A message names labels by system name, user key or user name; a
  label the mailbox does not have fails the load, so a broken fixture never reaches the
  agent.
- Messages are served newest first whatever order they are written in.
- `message_id`, `in_reply_to` and `references` are kept verbatim so a corpus can carry the
  same RFC headers as a recording; no tool exposes them.
- An attachment carries either `data_b64` (real bytes; `size` defaults to their length) or
  `size_only: true` with a `size`, in which case a download produces deterministic filler:
  `sha256(key)` repeated to the declared size.
- `body_html` is optional; `read_email` prints `body_text` and falls back to `body_html`.
- The section may be omitted entirely; the daemon then serves an empty mailbox with the
  system labels.

Validate estates, and prove a sandbox and a holdout share no human key, with:

```
PYTHONPATH=/opt/mockgmail python3 -m mockgmail.check public.json holdout.json
```

It exits 1 printing `shared <kind>: <value>` for every thread key, message key, RFC
message id, subject, sender address, attachment key or attachment filename the two have in
common, and exits 0 printing `ok: 2 scenarios, disjoint` otherwise. Run it at image build
time.

## Faults

Real APIs misbehave. Rules are matched on `(service, tool)` with `*` wildcards, and every
decision is a pure function of `(seed, service, tool, call count)` — the phase comes from
`sha256(f"{seed}:gmail:{tool}")` — so a given agent behaviour always meets the same
sequence of faults. Counters advance on every call whether or not a rule matches.

```json
"faults": {"enabled": true,
           "rules": [{"service": "gmail", "tool": "search_emails",
                      "throttle_every": 5, "throttle_burst": 2,
                      "server_error_every": 0, "max_page_size": 5,
                      "latency_seconds": 0.0}]}
```

| rule | effect |
| --- | --- |
| `throttle_every` N, `throttle_burst` K | every Nth call is refused, K in a row, as `Error: Rate Limit Exceeded` |
| `server_error_every` N | every Nth call answers `Error: Backend Error` |
| `max_page_size` K | caps `maxResults` (the newest K matches are still the newest K) |
| `latency_seconds` S | sleeps before answering |

`POST /_admin/faults {"enabled": false}` switches them off for the verifier's own drive.

## The admin plane

Everything under `/_admin/` requires the header `x-mockgmail-admin-token` to equal
`$MOCKGMAIL_ADMIN_TOKEN`. A missing header, a wrong token and a daemon started with no
token configured all answer the identical `403 {"error": "forbidden"}`.

| request | answer |
| --- | --- |
| `GET /_admin/health` | `{"ok": true}` |
| `GET /_admin/snapshot` | `{clock, seed, scenario_sha256, services, gmail: {messages: {key: {id, threadId}}, attachments: {key: id}, labels: {key: id}}}` |
| `GET /_admin/calls` | `{"calls": [{seq, at, service, tool, args, via, outcome, error_kind, duration_ms, result_chars, page}], "fault_counters": {"gmail:search_emails": 3}}` |
| `POST /_admin/reseed` | `{"scenario": {...}, "seed": 41}` → new world, new fault counters, empty journal |
| `POST /_admin/faults` | `{"enabled": false}` |

The snapshot lets a scorer map human keys to the opaque ids the tools returned without
importing this package. `via` is `mcp`, `cli` or `http`, so the journal shows how the
agent reached the mailbox. A `search_emails` record's `page` is
`{maxResults, matched, returned}`. Agent-phase journals are evidence, never a reward input:
the trajectory is not gradeable, so a task grades the behaviour of the submitted artifact
re-driven against a holdout estate.

### Token lifecycle

The token is minted by the task's init script into a root-only file and passed to the
daemon in its environment, never on a command line, so `ps` shows nothing and
`/proc/<pid>/environ` is unreadable by the agent user. The agent needs no credential at
all: `POST /mcp/gmail` is open on loopback. The verifier reads the token from its
root-only file, and mints a fresh one when it restarts the daemon on the holdout.

## Wiring a task

Copy the package into the image and install the wrapper. A task vendors
`shared/mockgmail/` into its own `environment/` without `tests/` (nothing outside
`tests/` needs it), and copies `bin/mockgmail` alongside it as `mockgmail-bin/mockgmail`:

```dockerfile
COPY --chown=root:root mockgmail/ /opt/mockgmail/mockgmail/
RUN chmod -R a+rX /opt/mockgmail && find /opt/mockgmail -name __pycache__ -prune -exec rm -rf {} +
COPY --chown=root:root --chmod=0755 mockgmail-bin/mockgmail /usr/local/bin/mockgmail
RUN ln -s /usr/local/bin/mockgmail /usr/local/bin/gmail
RUN install -d -m 0700 -o root -g root /var/lib/task-data /var/lib/task-data/run /var/lib/task-data/journal
RUN install -d -m 0755 -o root -g root /opt/gmail-sandbox
COPY --chown=root:root --chmod=0444 sandbox/gmail/ /opt/gmail-sandbox/
COPY --chown=root:root --chmod=0600 verifier-data/ /var/lib/task-data/verifier/
RUN PYTHONPATH=/opt/mockgmail python3 -m mockgmail.check \
      /opt/gmail-sandbox/public.json /var/lib/task-data/verifier/holdout.json
ENV MOCKGMAIL_URL=http://127.0.0.1:4570 TZ=Etc/UTC PYTHONDONTWRITEBYTECODE=1
```

Start it from the image entrypoint, before readiness is signalled:

```sh
TOKEN=$(head -c 18 /dev/urandom | od -An -tx1 | tr -d ' \n')
printf '%s' "$TOKEN" > /var/lib/task-data/run/admin-token
chmod 0600 /var/lib/task-data/run/admin-token
MOCKGMAIL_ADMIN_TOKEN="$TOKEN" \
MOCKGMAIL_JOURNAL=/var/lib/task-data/journal/gmail-calls.jsonl \
PYTHONPATH=/opt/mockgmail python3 -m mockgmail \
  --scenario "${MOCKGMAIL_SCENARIO:-/opt/gmail-sandbox/public.json}" \
  --host 127.0.0.1 --port "${MOCKGMAIL_PORT:-4570}" --seed "${MOCKGMAIL_SEED:-7}" \
  > /tmp/task-infra/mockgmail.log 2>&1 &
echo $! > /tmp/task-infra/mockgmail.pid
# poll GET /healthz for up to 30 s, then touch /tmp/task-infra/.ready
```

Register it for an MCP-speaking harness and tell a bash harness the command exists:

```toml
[environment.env]
MOCKGMAIL_URL = "http://127.0.0.1:4570"

[[environment.mcp_servers]]
name = "gmail"
transport = "stdio"
command = "/usr/local/bin/gmail"

[environment.healthcheck]
command = "test -f /tmp/task-infra/.ready"
```

And in `tests/test.sh`, near the top, keep the evidence and take the mailbox back:

```sh
cp /var/lib/task-data/journal/gmail-calls.jsonl "$REWARD_DIR/gmail-calls.jsonl" 2>/dev/null || true
kill "$(cat /tmp/task-infra/mockgmail.pid)" 2>/dev/null || true
pkill -f 'python3 -m mockgmail --scenario' || true
# loop until a Python bind probe on 4570 succeeds, then restart on the holdout with a
# fresh token and --seed 41 before driving the submitted artifact
```

The `pkill` pattern is anchored on `--scenario` so it never matches a `mockgmail.client`
shim (or another mock's daemon on another port).

## Working on it

From `shared/`:

```
uv venv .venv-mockgmail && uv pip install --python .venv-mockgmail/bin/python pytest pytest-cov ruff mypy mcp
.venv-mockgmail/bin/pytest mockgmail/tests --cov=mockgmail --cov-fail-under=100 -q
.venv-mockgmail/bin/ruff check mockgmail
.venv-mockgmail/bin/ruff format --check mockgmail
.venv-mockgmail/bin/mypy --strict mockgmail
python3 mockgmail/tests/smoke_test.py
```

`mcp` is a development dependency only: `tests/integration/test_stdio_shim.py` drives the
stdio shim with the official MCP Python client, which is the only honest way to know the
shim really speaks the protocol. Nothing under `mockgmail/` imports it, and nothing
outside `tests/` imports anything but the standard library.

House rules for this package: no comments and no docstrings (prose lives here), every file
at most 200 lines, one responsibility per file and one tool per file, all intra-package
imports relative, and 100% line coverage with no `pragma: no cover`. `tests/unit` touches
no sockets and no subprocesses; `tests/integration` runs the daemon in a thread on port 0
and drives it the way a task will.
