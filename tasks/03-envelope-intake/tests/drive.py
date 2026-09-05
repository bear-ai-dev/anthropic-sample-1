#!/usr/bin/env python3
"""Drives the submitted service through the graded run and records what it did.

This process loads no submitted code. It speaks HTTP to the service the way the
mail gateway and the desk would, and writes down the answers. Nothing here
decides anything: what the answers should have been is worked out afterwards by
compute_reward.py from an independent model, which never sees this file.

Two things it is careful about.

The pair operation hands over two deliveries concurrently, and it does so by
writing both requests onto two sockets before reading either response. There is
no sleep anywhere in this file: a graded outcome that depended on one would be
a coin flip dressed up as a concurrency test.

Where it reads the service's answers it prefers the field names in
docs/openapi.json and falls back to searching the response for the same
information under another name. Grading is on behaviour, and a submission that
answered correctly in a shape of its own should not be failed for the shape.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request, urlopen

# Per-request budget. Generous on purpose, and it has to be: nothing visible
# settles how quickly a delivery is answered, so a slow submission is a slow
# submission and not a wrong one. A correct implementation may open a connection
# per transaction with no `busy_timeout` and retry on SQLITE_BUSY; at thirty
# seconds the contending half of the concurrent pair times out and it scores zero
# on a rule it implements correctly. A submission that has
# genuinely wedged still fails: it fails every delivery after it, and the
# verifier's own timeout is the backstop.
TIMEOUT_S = 120.0


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def request(
    base: str, method: str, path: str, body: dict[str, Any] | None = None
) -> tuple[int, Any, str]:
    """Returns (status, decoded body or None, raw text). Never raises for HTTP."""
    data = None
    headers = {"accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"
    call = Request(f"{base}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(call, timeout=TIMEOUT_S) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
    except HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        status = error.code
    except (URLError, OSError, TimeoutError) as error:
        return (0, None, f"transport error: {error}")
    try:
        return (status, json.loads(raw), raw)
    except json.JSONDecodeError:
        return (status, None, raw)


def post_pair(host: str, port: int, path: str, bodies: list[dict[str, Any]]) -> list[tuple[int, Any, str]]:
    """Hands over several deliveries at once.

    Every request is written in full before any response is read, so the service
    has them all in hand before it has answered any of them. That is what makes
    the concurrent case concurrent, and it is decided by the order of the writes
    rather than by how long anything took.

    A service that is not listening is a wrong answer and not a broken run. Every
    other call in this file returns `(0, ...)` for a refused connection; this one
    used to raise, so a submission that fell over anywhere before a concurrent
    handoff took the whole trial down with it and was recorded as an exception
    with no score rather than as the nought it is.
    """
    # One slot per body, filled in place, so the answers stay in the order the
    # bodies were given however many of the handoffs got anywhere.
    results: list[tuple[int, Any, str]] = [
        (0, None, "no response") for _ in bodies
    ]
    connections: list[tuple[int, socket.socket]] = []
    try:
        for position, body in enumerate(bodies):
            payload = json.dumps(body).encode("utf-8")
            head = (
                f"POST {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Content-Type: application/json\r\n"
                "Accept: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            try:
                connection = socket.create_connection((host, port), timeout=TIMEOUT_S)
                connection.sendall(head + payload)
            except OSError as error:
                results[position] = (0, None, f"transport error: {error}")
                continue
            connections.append((position, connection))

        for position, connection in connections:
            chunks: list[bytes] = []
            while True:
                try:
                    chunk = connection.recv(65536)
                except (TimeoutError, OSError):
                    break
                if not chunk:
                    break
                chunks.append(chunk)
            results[position] = parse_http_response(b"".join(chunks))
        return results
    finally:
        for _, connection in connections:
            try:
                connection.close()
            except OSError:
                pass


def parse_http_response(raw: bytes) -> tuple[int, Any, str]:
    if not raw:
        return (0, None, "no response")
    head, _, rest = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    try:
        status = int(lines[0].split(b" ")[1])
    except (IndexError, ValueError):
        return (0, None, raw.decode("utf-8", "replace"))

    chunked = any(
        line.lower().startswith(b"transfer-encoding:") and b"chunked" in line.lower()
        for line in lines[1:]
    )
    body = dechunk(rest) if chunked else rest
    text = body.decode("utf-8", "replace")
    try:
        return (status, json.loads(text), text)
    except json.JSONDecodeError:
        return (status, None, text)


def dechunk(raw: bytes) -> bytes:
    out = bytearray()
    rest = raw
    while True:
        line, _, rest = rest.partition(b"\r\n")
        try:
            size = int(line.split(b";")[0].strip(), 16)
        except ValueError:
            return bytes(out) if out else raw
        if size == 0:
            return bytes(out)
        out += rest[:size]
        rest = rest[size + 2 :]


# --------------------------------------------------------------------------
# tolerant reading of the service's answers
# --------------------------------------------------------------------------

ACTIONS = {"created", "appended", "reopened", "duplicate", "pending"}


def find_action(body: Any) -> str | None:
    """The action the service reported, by the documented name or otherwise."""
    if not isinstance(body, dict):
        return None
    value = body.get("action")
    if isinstance(value, str) and value.lower() in ACTIONS:
        return value.lower()
    for candidate in walk(body):
        if isinstance(candidate, str) and candidate.lower() in ACTIONS:
            return candidate.lower()
    return None


def find_ticket_id(body: Any) -> str | None:
    """The ticket the service put the delivery on, if it named one."""
    if not isinstance(body, dict):
        return None
    for key in ("ticket_id", "ticketId", "ticket"):
        value = body.get(key)
        if isinstance(value, str) and value != "":
            return value
        if isinstance(value, dict):
            inner = find_ticket_id(value)
            if inner is not None:
                return inner
    for key, value in body.items():
        lowered = key.lower()
        if "ticket" in lowered and not any(
            word in lowered for word in ("prior", "merge", "absorb", "supersede")
        ):
            if isinstance(value, str) and value != "":
                return value
    # An answer that wraps its content in an envelope of its own -- `result`,
    # `data`, `outcome` -- is answering; it is answering in a shape of its own.
    # Grading is on behaviour, so the wrapper is looked through rather than
    # treated as an absent ticket. Only after the two passes above, so a
    # documented field at this level always wins over one further down.
    for value in body.values():
        if isinstance(value, dict):
            inner = find_ticket_id(value)
            if inner is not None:
                return inner
    return None


def find_prior_ticket_id(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    for key in ("prior_ticket_id", "priorTicketId", "prior_ticket", "continues"):
        value = body.get(key)
        if isinstance(value, str) and value != "":
            return value
    return None


def find_merged_into(body: Any) -> str | None:
    """The ticket this one was folded into, by the documented name or otherwise."""
    if not isinstance(body, dict):
        return None
    for key in (
        "merged_into_ticket_id",
        "mergedIntoTicketId",
        "merged_into",
        "mergedInto",
        "merged_ticket_id",
        "absorbed_into",
        "superseded_by",
    ):
        value = body.get(key)
        if isinstance(value, str) and value != "":
            return value
    return None


def find_strings(body: Any) -> list[str]:
    """Every string value in the answer, deduplicated.

    Recorded so that a ticket which names the one it was merged into under a
    field nobody thought of is still credited with naming it. Grading is on
    behaviour and this is the widest possible reading of "it says so".
    """
    seen: list[str] = []
    for value in walk_values(body):
        if isinstance(value, str) and value != "" and value not in seen:
            seen.append(value)
        if len(seen) >= 200:
            break
    return seen


def find_status(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    value = body.get("status")
    if isinstance(value, str) and value.lower() in {"open", "closed"}:
        return value.lower()
    for candidate in walk(body):
        if isinstance(candidate, str) and candidate.lower() in {"open", "closed"}:
            return candidate.lower()
    return None


def find_requester(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    for key in (
        "requester_identity_id",
        "requesterIdentityId",
        "identity_id",
        "requester",
    ):
        value = body.get(key)
        if isinstance(value, str) and value != "":
            return value
        if isinstance(value, dict):
            for inner_key in ("identity_id", "identityId", "id"):
                inner = value.get(inner_key)
                if isinstance(inner, str) and inner != "":
                    return inner
    return None


STATES = {"queued", "sent", "refused"}


def find_state(body: Any) -> str | None:
    """Where the service says a reply is, by the documented name or otherwise."""
    if not isinstance(body, dict):
        return None
    value = body.get("state")
    if isinstance(value, str) and value.lower() in STATES:
        return value.lower()
    for key in ("status", "outbox_state", "outboxState", "delivery_state"):
        value = body.get(key)
        if isinstance(value, str) and value.lower() in STATES:
            return value.lower()
    for candidate in walk(body):
        if isinstance(candidate, str) and candidate.lower() in STATES:
            return candidate.lower()
    return None


def find_reply_id(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    for key in ("reply_id", "replyId", "id"):
        value = body.get(key)
        if isinstance(value, str) and value != "":
            return value
    for value in body.values():
        if isinstance(value, dict):
            inner = find_reply_id(value)
            if inner is not None:
                return inner
    return None


def find_outbox_entries(body: Any) -> list[dict[str, Any]] | None:
    """Every outbox entry the service listed, as reply/message/ticket/state.

    Prefers a documented `replies` array and otherwise takes the first list
    whose entries carry a state and something that looks like a key.
    """
    if not isinstance(body, dict):
        return None
    for key in ("replies", "outbox", "entries", "items"):
        found = as_outbox_list(body.get(key))
        if found is not None:
            return found
    for value in walk_values(body):
        found = as_outbox_list(value)
        if found is not None:
            return found
    return None


def as_outbox_list(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    entries: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        state = find_state(item)
        if state is None:
            return None
        entries.append(
            {
                "reply_id": find_reply_id(item),
                "message_id": find_message_id(item),
                "ticket_id": find_ticket_id(item),
                "state": state,
            }
        )
    return entries


def find_message_id(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    for key in ("message_id", "messageId", "message"):
        value = body.get(key)
        if isinstance(value, str) and value != "":
            return value
    return None


def find_envelope_messages(body: Any) -> list[str] | None:
    """The message identifiers the ticket lists, in the order it listed them.

    Read separately from the transport identifiers because the two answer
    different questions: how many *deliveries* a ticket holds, and how many
    distinct *messages* they are. A ticket showing one message twice under two
    transports is a different mistake from a ticket missing it.
    """
    if not isinstance(body, dict):
        return None
    for key in ("envelopes", "deliveries", "messages", "items"):
        found = as_message_list(body.get(key))
        if found is not None:
            return found
    for value in walk_values(body):
        found = as_message_list(value)
        if found is not None:
            return found
    return None


def as_message_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    messages: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            return None
        found = find_message_id(entry)
        if found is None:
            return None
        messages.append(found)
    return messages


def find_envelope_list(body: Any) -> list[str] | None:
    """The transport identifiers on the ticket, in the order they were listed.

    Prefers a documented `envelopes` array and otherwise takes the first list of
    objects that carry a transport identifier, at any depth.
    """
    if not isinstance(body, dict):
        return None
    for key in ("envelopes", "deliveries", "messages", "items"):
        found = as_transport_list(body.get(key))
        if found is not None:
            return found
    for value in walk_values(body):
        found = as_transport_list(value)
        if found is not None:
            return found
    return None


def as_transport_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    transports: list[str] = []
    for entry in value:
        if isinstance(entry, str):
            transports.append(entry)
            continue
        if not isinstance(entry, dict):
            return None
        found = None
        for key in ("transport_id", "transportId"):
            if isinstance(entry.get(key), str):
                found = entry[key]
                break
        if found is None:
            return None
        transports.append(found)
    return transports


def walk(node: Any) -> Any:
    for value in walk_values(node):
        yield value


def walk_values(node: Any) -> Any:
    if isinstance(node, dict):
        for value in node.values():
            yield value
            yield from walk_values(value)
    elif isinstance(node, list):
        for value in node:
            yield value
            yield from walk_values(value)


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

INTAKE_PATHS = [
    "/v1/intake/envelope",
    "/v1/intake/envelopes",
    "/intake/envelope",
    "/v1/envelopes",
    "/v1/intake",
]

READ_PATH_TEMPLATES = [
    "/v1/tenants/{tenant}/tickets/{ticket}",
    "/v1/tenants/{tenant}/ticket/{ticket}",
    "/tenants/{tenant}/tickets/{ticket}",
    "/v1/tickets/{ticket}?tenant_id={tenant}",
]

REPLY_PATH_TEMPLATES = [
    "/v1/tenants/{tenant}/tickets/{ticket}/replies",
    "/v1/tenants/{tenant}/tickets/{ticket}/reply",
    "/tenants/{tenant}/tickets/{ticket}/replies",
    "/v1/tickets/{ticket}/replies?tenant_id={tenant}",
]

DISPATCH_PATHS = [
    "/v1/egress/dispatch",
    "/v1/egress/tick",
    "/egress/dispatch",
    "/v1/dispatch",
    "/v1/outbox/dispatch",
]

OUTBOX_PATH_TEMPLATES = [
    "/v1/tenants/{tenant}/outbox",
    "/tenants/{tenant}/outbox",
    "/v1/outbox?tenant_id={tenant}",
]


class Driver:
    def __init__(
        self,
        base: str,
        host: str,
        port: int,
        restart_command: str | None = None,
        health_budget: float = 60.0,
        spool: str | None = None,
    ) -> None:
        self.base = base
        self.host = host
        self.port = port
        self.restart_command = restart_command
        self.health_budget = health_budget
        self.spool = spool
        self.intake_path: str | None = None
        self.read_template: str | None = None
        self.reply_template: str | None = None
        self.dispatch_path: str | None = None
        self.outbox_template: str | None = None
        self.close_template = "/v1/tenants/{tenant}/tickets/{ticket}/close"
        self.responses: list[dict[str, Any]] = []
        self.reads: list[dict[str, Any]] = []
        self.closes: list[dict[str, Any]] = []
        self.restarts: list[dict[str, Any]] = []
        self.replies: list[dict[str, Any]] = []
        self.dispatches: list[dict[str, Any]] = []
        self.outboxes: list[dict[str, Any]] = []
        self.spools: list[dict[str, Any]] = []
        #: transport -> the ticket the service last named for it.
        self.ticket_of: dict[tuple[str, str], str] = {}
        self.notes: list[str] = []

    # -- seam ---------------------------------------------------------------

    def resolve_intake(self, probe: dict[str, Any]) -> dict[str, Any]:
        """Finds the route that accepts a delivery by presenting one.

        Candidates are tried in turn and a candidate is only accepted once it has
        answered a real delivery with a real outcome. Nothing is resolved by
        matching a name.
        """
        attempts = []
        for path in INTAKE_PATHS:
            status, body, raw = request(self.base, "POST", path, probe)
            attempts.append({"path": path, "status": status, "body": raw[:400]})
            if status == 501:
                continue
            if 200 <= status < 300 and (
                find_action(body) is not None or find_ticket_id(body) is not None
            ):
                self.intake_path = path
                break
        return {"resolved": self.intake_path, "attempts": attempts}

    def resolve_read(self, tenant: str, ticket: str) -> dict[str, Any]:
        """Finds the ticket read route by reading a ticket that exists."""
        attempts = []
        for template in READ_PATH_TEMPLATES:
            path = template.format(tenant=tenant, ticket=ticket)
            status, body, raw = request(self.base, "GET", path)
            attempts.append({"path": path, "status": status, "body": raw[:400]})
            if 200 <= status < 300 and find_envelope_list(body) is not None:
                self.read_template = template
                break
        return {"resolved": self.read_template, "attempts": attempts}

    def resolve_close(self, tenant: str, ticket: str) -> dict[str, Any]:
        """Confirms the close route by closing a ticket and reopening nothing.

        The probe's own ticket is used, so the graded run is untouched.
        """
        path = self.close_template.format(tenant=tenant, ticket=ticket)
        status, _, raw = request(
            self.base, "POST", path, {"closed_at": "2020-01-01T00:00:00Z"}
        )
        return {"path": path, "status": status, "body": raw[:400], "ok": 200 <= status < 300}

    # -- operations ---------------------------------------------------------

    def post(self, index: int, envelope: dict[str, Any]) -> None:
        status, body, raw = request(self.base, "POST", self.intake_path or "", envelope)
        self.record_response(index, envelope, status, body, raw)

    def pair(self, index: int, envelopes: list[dict[str, Any]]) -> None:
        results = post_pair(self.host, self.port, self.intake_path or "", envelopes)
        for envelope, (status, body, raw) in zip(envelopes, results):
            self.record_response(index, envelope, status, body, raw)

    def record_response(
        self, index: int, envelope: dict[str, Any], status: int, body: Any, raw: str
    ) -> None:
        ticket = find_ticket_id(body) if 200 <= status < 300 else None
        if ticket is not None:
            self.ticket_of[(envelope["tenant_id"], envelope["transport_id"])] = ticket
        self.responses.append(
            {
                "index": index,
                "tenant_id": envelope["tenant_id"],
                "transport_id": envelope["transport_id"],
                "http_status": status,
                "action": find_action(body) if 200 <= status < 300 else None,
                "ticket_id": ticket,
                "raw": raw[:400],
            }
        )

    def close(self, index: int, tenant: str, of: str, closed_at: str) -> None:
        ticket = self.ticket_of.get((tenant, of))
        if ticket is None:
            self.closes.append(
                {"index": index, "of": of, "http_status": 0, "note": "no ticket known"}
            )
            return
        path = self.close_template.format(tenant=tenant, ticket=ticket)
        status, _, raw = request(self.base, "POST", path, {"closed_at": closed_at})
        self.closes.append(
            {
                "index": index,
                "tenant_id": tenant,
                "of": of,
                "ticket_id": ticket,
                "http_status": status,
                "raw": raw[:200],
            }
        )

    def read(self, index: int, tenant: str, of: str) -> None:
        ticket = None
        for (owner, transport), value in self.ticket_of.items():
            if transport == of:
                ticket = value
                if owner == tenant:
                    break
        entry: dict[str, Any] = {
            "index": index,
            "tenant_id": tenant,
            "of": of,
            "requested_ticket_id": ticket,
        }
        if ticket is None or self.read_template is None:
            entry["http_status"] = 0
            entry["note"] = "no ticket known" if ticket is None else "no read route"
            self.reads.append(entry)
            return
        path = self.read_template.format(tenant=tenant, ticket=ticket)
        status, body, raw = request(self.base, "GET", path)
        entry["http_status"] = status
        if 200 <= status < 300:
            entry["ticket_id"] = find_ticket_id(body) or ticket
            entry["status"] = find_status(body)
            entry["prior_ticket_id"] = find_prior_ticket_id(body)
            entry["merged_into_ticket_id"] = find_merged_into(body)
            entry["requester_identity_id"] = find_requester(body)
            entry["envelopes"] = find_envelope_list(body)
            entry["envelope_messages"] = find_envelope_messages(body)
            entry["strings"] = find_strings(body)
        else:
            entry["raw"] = raw[:300]
        self.reads.append(entry)

    # -- the outbound half --------------------------------------------------

    def reply(self, index: int, operation: dict[str, Any]) -> None:
        """Hands a composed reply over the way the desk's console would.

        The console knows the ticket it is composing on. The run names it the
        way it names everything else -- by a delivery already on it -- and the
        literal `ticket_id` form is for the case where the ticket is not the
        desk's, which is the only case that has no delivery to name it by.
        """
        tenant = operation["tenant_id"]
        body = dict(operation["reply"])
        ticket = operation.get("ticket_id")
        if ticket is None:
            # `ticket_tenant` is for the cross-desk case: the run watched this
            # ticket being created under another desk, so it has an identifier
            # to present here, which is what makes the refusal meaningful.
            owner = operation.get("ticket_tenant", tenant)
            ticket = self.ticket_of.get((owner, operation["ticket_of"]))
        entry: dict[str, Any] = {
            "index": index,
            "tenant_id": tenant,
            "reply_id": body.get("reply_id"),
            "message_id": body.get("message_id"),
            "requested_ticket_id": ticket,
        }
        if ticket is None:
            entry["http_status"] = 0
            entry["note"] = "no ticket known"
            self.replies.append(entry)
            return

        for template in [self.reply_template] if self.reply_template else REPLY_PATH_TEMPLATES:
            path = template.format(tenant=tenant, ticket=ticket)
            status, answer, raw = request(self.base, "POST", path, body)
            if status == 501 or status == 404 and self.reply_template is None:
                # 404 from an unresolved template is ambiguous: it may be the
                # route or it may be the ticket. Keep looking, and if nothing
                # else answers, the last answer stands.
                entry["http_status"] = status
                entry["raw"] = raw[:300]
                continue
            self.reply_template = template
            entry["http_status"] = status
            entry["state"] = find_state(answer) if 200 <= status < 300 else None
            entry["ticket_id"] = find_ticket_id(answer) if 200 <= status < 300 else None
            entry["raw"] = raw[:300]
            break

        named = entry.get("ticket_id") or ticket
        if 200 <= int(entry.get("http_status") or 0) < 300 and body.get("reply_id"):
            # A reply the desk sends is a delivery on the conversation like any
            # other, so the run can name it later the same way -- by its key.
            self.ticket_of[(tenant, str(body["reply_id"]))] = named
        self.replies.append(entry)

    def dispatch(self, index: int, operation: dict[str, Any]) -> None:
        """Asks the desk to offer the transport what it is holding."""
        body: dict[str, Any] = {}
        if operation.get("tenant_id"):
            body["tenant_id"] = operation["tenant_id"]
        entry: dict[str, Any] = {"index": index, "tenant_id": operation.get("tenant_id")}
        for path in [self.dispatch_path] if self.dispatch_path else DISPATCH_PATHS:
            status, answer, raw = request(self.base, "POST", path, body)
            if status in (404, 501):
                entry["http_status"] = status
                entry["raw"] = raw[:300]
                continue
            self.dispatch_path = path
            entry["http_status"] = status
            entry["raw"] = raw[:300]
            entry["report"] = answer if isinstance(answer, dict) else None
            break
        self.dispatches.append(entry)

    def tick_pair(self, index: int, operation: dict[str, Any]) -> None:
        """Two ticks against one desk, both in flight before either answers.

        The desk's timer does not wait for the last tick to finish and an
        operator does not ask it to, so this is the ordinary case rather than an
        exotic one. Both calls see the same queued replies, so whatever the desk
        does about that is what decides whether a message goes onto the wire
        twice, gets recorded twice, or neither.

        The path has to be known before this runs: it is resolved by an ordinary
        tick earlier in the run, and if it is not, the pair is recorded as
        unanswered rather than probed twice over.
        """
        body: dict[str, Any] = {}
        if operation.get("tenant_id"):
            body["tenant_id"] = operation["tenant_id"]
        howmany = int(operation.get("count", 2))
        if not self.dispatch_path:
            for _ in range(howmany):
                self.dispatches.append(
                    {
                        "index": index,
                        "tenant_id": operation.get("tenant_id"),
                        "http_status": 0,
                        "note": "no dispatch route was resolved before the pair",
                    }
                )
            return
        results = post_pair(self.host, self.port, self.dispatch_path, [body] * howmany)
        for status, answer, raw in results:
            self.dispatches.append(
                {
                    "index": index,
                    "tenant_id": operation.get("tenant_id"),
                    "http_status": status,
                    "raw": raw[:300],
                    "report": answer if isinstance(answer, dict) else None,
                }
            )

    def outbox(self, index: int, operation: dict[str, Any]) -> None:
        tenant = operation["tenant_id"]
        state = operation.get("state")
        entry: dict[str, Any] = {"index": index, "tenant_id": tenant, "state": state}
        templates = [self.outbox_template] if self.outbox_template else OUTBOX_PATH_TEMPLATES
        for template in templates:
            path = template.format(tenant=tenant)
            if state:
                path += ("&" if "?" in path else "?") + f"state={state}"
            status, body, raw = request(self.base, "GET", path)
            if status in (404, 501):
                entry["http_status"] = status
                entry["raw"] = raw[:300]
                continue
            self.outbox_template = template
            entry["http_status"] = status
            if 200 <= status < 300:
                entry["entries"] = find_outbox_entries(body)
                entry["strings"] = find_strings(body)
            else:
                entry["raw"] = raw[:300]
            break
        self.outboxes.append(entry)

    def read_spool(self, index: int, operation: dict[str, Any]) -> None:
        """What is actually on the wire, read from the transport's own side.

        The one observation in the run that does not come from the submission.
        Everything else it says about the outbound path can be self-consistent
        and wrong; this cannot.
        """
        tenant = operation["tenant_id"]
        entry: dict[str, Any] = {"index": index, "tenant_id": tenant}
        if not self.spool:
            entry["note"] = "no spool configured"
            self.spools.append(entry)
            return
        directory = os.path.join(self.spool, tenant)
        messages: list[str] = []
        try:
            for name in sorted(os.listdir(directory)):
                if not name.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(directory, name), encoding="utf-8") as handle:
                        payload = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    # The name is the message identifier, percent-encoded by
                    # handoff.ts. Unreadable contents are still an arrival.
                    messages.append(unquote(name[: -len(".json")]))
                    continue
                found = find_message_id(payload)
                messages.append(found or unquote(name[: -len(".json")]))
        except FileNotFoundError:
            messages = []
        except OSError as error:
            entry["note"] = f"could not read the spool: {error}"
        entry["messages"] = messages
        self.spools.append(entry)

    def restart(self, index: int) -> None:
        """Stops the service and starts it again, in the middle of the run.

        Nothing about the run changes across this: the same deliveries are handed
        over on either side and the same answers are expected. What does not
        survive is anything the service was holding in memory rather than in its
        store -- a table of deliveries waiting for a parent, a map of message
        identifiers to conversations, a cache of which ticket is open.

        The command's own exit status is the only thing treated as ours. A
        service that does not answer afterwards is not a harness fault: it is a
        service that did not come back, and the deliveries after this point say
        so on their own.

        With one qualification. A stop and
        a start on a loaded box can lose the race with each other -- the old
        listener's socket outlives the process that held it just long enough for
        the new one to fail its bind -- and the reference implementation itself
        came back from four restarts and not the fifth, which put a hundred and
        thirteen connection-refused answers into a transcript that was then
        graded as wrong. A service that cannot start is deterministic and will
        not start on a second attempt either, so the start is made twice before
        the silence is read as the submission's. Both attempts are recorded.
        This is bounded readiness, not a sleep: nothing here waits a fixed time
        and nothing compares one execution against another.
        """
        entry: dict[str, Any] = {"index": index}
        if not self.restart_command:
            entry["skipped"] = True
            self.notes.append(f"op {index}: no restart command was configured")
            self.restarts.append(entry)
            return
        attempts: list[dict[str, Any]] = []
        for attempt in range(2):
            record: dict[str, Any] = {"attempt": attempt}
            try:
                completed = subprocess.run(
                    [self.restart_command],
                    capture_output=True,
                    text=True,
                    timeout=240,
                )
                record["exit"] = completed.returncode
                record["stderr"] = (completed.stderr or "")[-400:]
            except (OSError, subprocess.SubprocessError) as error:
                record["exit"] = -1
                record["stderr"] = f"{error}"
            record["healthy"] = wait_for_health(self.base, self.health_budget)
            attempts.append(record)
            if record["healthy"]:
                break
        entry["attempts"] = attempts
        entry["exit"] = attempts[-1]["exit"]
        entry["stderr"] = attempts[-1]["stderr"]
        entry["healthy"] = attempts[-1]["healthy"]
        if len(attempts) > 1:
            self.notes.append(
                f"op {index}: the service needed a second start after the restart"
            )
        if not entry["healthy"]:
            self.notes.append(f"op {index}: the service did not answer after a restart")
        self.restarts.append(entry)

    # -- everything ---------------------------------------------------------

    def execute(self, operations: list[dict[str, Any]]) -> None:
        for index, operation in enumerate(operations):
            kind = operation["op"]
            if kind == "post":
                self.post(index, operation["envelope"])
            elif kind == "pair":
                self.pair(index, operation["envelopes"])
            elif kind == "close":
                self.close(
                    index, operation["tenant_id"], operation["of"], operation["closed_at"]
                )
            elif kind == "read":
                self.read(index, operation["tenant_id"], operation["of"])
            elif kind == "restart":
                self.restart(index)
            elif kind == "reply":
                self.reply(index, operation)
            elif kind == "dispatch":
                self.dispatch(index, operation)
            elif kind == "tick_pair":
                self.tick_pair(index, operation)
            elif kind == "outbox":
                self.outbox(index, operation)
            elif kind == "spool":
                self.read_spool(index, operation)
            else:
                raise ValueError(f"unknown operation {kind!r}")

    def report(self) -> dict[str, Any]:
        return {
            "intake_path": self.intake_path,
            "read_template": self.read_template,
            "reply_template": self.reply_template,
            "dispatch_path": self.dispatch_path,
            "outbox_template": self.outbox_template,
            "responses": self.responses,
            "reads": self.reads,
            "closes": self.closes,
            "restarts": self.restarts,
            "replies": self.replies,
            "dispatches": self.dispatches,
            "outboxes": self.outboxes,
            "spools": self.spools,
            "notes": self.notes,
        }


def wait_for_health(base: str, budget_s: float) -> bool:
    """Polls until the service answers, with backoff. Never a fixed sleep."""
    deadline = time.monotonic() + budget_s
    delay = 0.05
    while time.monotonic() < deadline:
        status, _, _ = request(base, "GET", "/health")
        if 200 <= status < 300:
            return True
        time.sleep(min(delay, max(0.0, deadline - time.monotonic())))
        delay = min(delay * 1.6, 1.0)
    return False


PROBE_TENANT = "tnt-probe-0000-0000"


def probe_envelope(index: int) -> dict[str, Any]:
    return {
        "transport_id": f"trn-probe-{index:03d}",
        "tenant_id": PROBE_TENANT,
        "message_id": f"<m-probe-{index}@probe>",
        "from_address": "probe@probe.invalid",
        "to_addresses": ["help@desk.internal"],
        "in_reply_to": None,
        "references": [],
        "subject_token": None,
        "received_at": "2026-02-01T00:00:00Z",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--health-budget", type=float, default=45.0)
    parser.add_argument(
        "--spool",
        help="The transport's spool directory, read directly by the run's spool "
        "operations. Without it they are recorded and skipped.",
    )
    parser.add_argument(
        "--restart-command",
        help="Executable that stops the service and starts it again. Used by the "
        "run's restart operations; without it they are recorded and skipped.",
    )
    arguments = parser.parse_args()

    base = f"http://{arguments.host}:{arguments.port}"
    with open(arguments.spec, encoding="utf-8") as handle:
        spec = json.load(handle)

    outcome: dict[str, Any] = {"healthy": False}

    if not wait_for_health(base, arguments.health_budget):
        outcome["note"] = "the service never answered /health"
        write(arguments.out, outcome)
        return
    outcome["healthy"] = True

    driver = Driver(
        base,
        arguments.host,
        arguments.port,
        restart_command=arguments.restart_command,
        health_budget=arguments.health_budget,
        spool=arguments.spool,
    )

    # Resolve the seam by exercising it: post a delivery of our own, in a desk
    # that appears nowhere in the graded run, and require a real outcome back.
    outcome["intake_probe"] = driver.resolve_intake(probe_envelope(1))
    if driver.intake_path is None:
        outcome["note"] = "no route accepted a delivery"
        write(arguments.out, outcome)
        return

    # Confirm the route did something, rather than merely answering: a second
    # delivery in the same conversation has to come back on the same ticket.
    first = driver.responses  # empty; the probe went through resolve_intake
    status, body, _ = request(driver.base, "POST", driver.intake_path, probe_envelope(2))
    probe_ticket = find_ticket_id(body) if 200 <= status < 300 else None
    outcome["intake_effect"] = {"status": status, "ticket_id": probe_ticket}
    del first

    if probe_ticket is not None:
        outcome["read_probe"] = driver.resolve_read(PROBE_TENANT, probe_ticket)
        outcome["close_probe"] = driver.resolve_close(PROBE_TENANT, probe_ticket)
    else:
        outcome["read_probe"] = {"resolved": None, "attempts": []}
        outcome["close_probe"] = {"ok": False, "note": "no probe ticket to close"}

    driver.execute(spec["operations"])
    outcome.update(driver.report())
    outcome["alive_after"] = wait_for_health(base, 5.0)
    write(arguments.out, outcome)


def write(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
