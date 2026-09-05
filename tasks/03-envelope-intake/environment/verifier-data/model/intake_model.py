"""An independent model of the envelope intake specification.

This is not a port of the service and shares no code with it. The service in the
workspace is an online dispatcher: one delivery at a time, a row lock per desk, a
lookup per parent, a table of deliveries it could not place, hashed conversation
keys, minted identifiers, and a decision committed in a transaction before the
next delivery is looked at. This model works the other way round:

  * Conversations come from a disjoint-set union over message-identifier tokens.
    Every delivery contributes every token it mentions and they are merged
    blindly, so a chain of replies collapses into one component without anything
    ever being looked up or held -- and so does a pair of chains that turn out to
    share a token, which is the whole of the retroactive case.

  * Whether a delivery could be placed when it arrived is arithmetic on indices,
    not a queue. Each delivery has an index at which it became placeable -- its
    own, or its parent's, whichever is later -- solved to a fixed point by
    repeated relaxation. A delivery whose placeable index is past its own arrival
    is one that had to wait.

  * Tickets are integer labels handed out by a fold over one event list. There is
    no hash anywhere in this file and nothing is keyed by a conversation
    identifier: a thread here is an integer, and two threads becoming one is an
    assignment over a dict of tokens.

The fold is ordered because the specification is: which of two tickets survives
depends on which opened first, and what a redelivery is answered with depends on
where its delivery is at the moment it is asked. What the fold never does is look
anything up in a store or revise a decision it has already recorded.

Everything lives in dicts and lists. There is no store, no transaction and no
concurrency: the concurrent pair in a run is two deliveries that became placeable
at the same index, which the fold handles like any other pair.

The service and this model must agree. Where they do not, one of them has
misread the specification, and which one is a question to be answered rather
than papered over.

Reference: the specification is `instruction.md`, the field meanings in
`docs/envelope-catalog.json`, the wire contract in `docs/openapi.json`, what a
delivery asserts about threading in `src/intake/threading.ts`, and which way it
was going in `src/intake/direction.ts`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

REOPEN_WINDOW_HOURS = 720
_MS_PER_HOUR = 3_600_000


# --------------------------------------------------------------------------
# instants
# --------------------------------------------------------------------------


def parse_instant(text: str) -> int:
    """Milliseconds since the epoch for an ISO-8601 UTC instant ending in Z.

    Written out rather than delegated, so that a disagreement about time between
    the service and this model is a disagreement about the specification and not
    about two libraries' idea of a fractional second.
    """
    body = text.strip()
    if not body.endswith("Z"):
        raise ValueError(f"instant must end in Z: {text!r}")
    body = body[:-1]
    fraction_ms = 0
    if "." in body:
        body, fraction = body.split(".", 1)
        digits = (fraction + "000000")[:6]
        fraction_ms = int(digits) // 1000
    date_part, time_part = body.split("T")
    year, month, day = (int(piece) for piece in date_part.split("-"))
    hour, minute, second = (int(piece) for piece in time_part.split(":"))

    # Days since 1970-01-01 by the civil-from-days algorithm, so no calendar
    # library is involved.
    shifted_year = year - (1 if month <= 2 else 0)
    era = (shifted_year if shifted_year >= 0 else shifted_year - 399) // 400
    year_of_era = shifted_year - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    days = era * 146097 + day_of_era - 719468

    return ((days * 24 + hour) * 60 + minute) * 60_000 + second * 1000 + fraction_ms


def instant_key(text: str) -> tuple[int, int]:
    """An orderable key for `received_at`, exact to the microsecond.

    Separate from `parse_instant`, which rounds to milliseconds and is right to:
    it answers a 720-hour question and a sub-millisecond difference cannot change
    that answer. Ordering is the opposite case -- a single microsecond decides
    which of two deliveries a ticket lists first -- so rounding here would make
    the model agree with the wrong readings it exists to separate.

    The two obvious ways to compare these values are both wrong, which is R28:

      * as text. `ORDER BY received_at` under SQLite's BINARY collation, and `<`
        in JavaScript, compare bytes. `"…T12:00:00Z"` then sorts AFTER
        `"…T12:00:00.000001Z"`, because `Z` (0x5A) is greater than `.` (0x2E) --
        so a delivery with no fraction lands last in its second instead of first.
      * as a `Date`. `Date.parse` and `new Date(...)` keep milliseconds and drop
        everything below, so `.000001Z` and `.000002Z` become the same instant
        and a stable sort falls back to the order the rows were inserted in.

    Whole seconds are the fraction `000000`, which is arithmetic and not a
    convention: a delivery stamped without a fraction is the earliest instant in
    its second.
    """
    body = text.strip()
    if not body.endswith("Z"):
        raise ValueError(f"instant must end in Z: {text!r}")
    body = body[:-1]
    fraction = "0"
    if "." in body:
        body, fraction = body.split(".", 1)
    # Right-pad rather than left-pad: `.5` is five hundred thousand microseconds,
    # not five. Getting this backwards is the third wrong reading and it is the
    # one that looks correct on data where every fraction has the same width.
    return parse_instant(body + "Z"), int((fraction + "000000")[:6])


def within_reopen_window(closed_at: str, received_at: str) -> bool:
    """Whether a delivery falls inside the window of a close.

    The anchor is the close. Nothing else in the ticket's history is an anchor:
    not when it was created, not when the conversation started, not when the
    previous delivery arrived, and not the close of some other ticket the
    conversation happens to hold.
    """
    return parse_instant(received_at) - parse_instant(closed_at) <= (
        REOPEN_WINDOW_HOURS * _MS_PER_HOUR
    )


# --------------------------------------------------------------------------
# what a delivery says about threading
# --------------------------------------------------------------------------


def is_outbound(envelope: dict[str, Any], desk: set[tuple[str, str]]) -> bool:
    """Whether the desk sent this delivery rather than received it.

    The gateway is on the transport, so both halves of a conversation come over
    it. The sender settles which half: the desk's own addresses are the desk's,
    and they are also in the alias table, so resolving a sender to an identity
    does not answer this question.
    """
    address = str(envelope.get("from_address") or "").strip().lower()
    return (envelope["tenant_id"], address) in desk


def root_reference(envelope: dict[str, Any]) -> tuple[str, str]:
    """Which message identifier roots this delivery, and how it was found.

    Returns ``("root", message_id)`` when the headers state the root, and
    ``("parent", message_id)`` when they only name the delivery this one
    replies to. `subject_token` is not consulted; it is advisory and frequently
    wrong.
    """
    references = envelope.get("references") or []
    if references:
        return ("root", references[0])
    in_reply_to = envelope.get("in_reply_to")
    if in_reply_to:
        return ("parent", in_reply_to)
    return ("root", envelope["message_id"])


def _as_envelope(row: dict[str, Any]) -> dict[str, Any]:
    """A stored envelope row as the rest of this file expects an envelope.

    Rows that were in the store before the run began arrive in the shape the
    table holds them in, where `references` is a JSON string. Everything else
    here reads a delivery as the intake route received it.
    """
    references = row.get("references")
    if references is None:
        try:
            parsed = json.loads(row.get("references_json") or "[]")
        except (TypeError, ValueError):
            parsed = []
        references = parsed if isinstance(parsed, list) else []
    return {
        "tenant_id": row["tenant_id"],
        "transport_id": row["transport_id"],
        "message_id": row["message_id"],
        "from_address": row["from_address"],
        "in_reply_to": row.get("in_reply_to"),
        "references": [item for item in references if isinstance(item, str)],
        "received_at": row["received_at"],
    }


def linked_identifiers(envelope: dict[str, Any]) -> list[str]:
    """Every message identifier this delivery asserts to be one conversation.

    Its own, its reference chain, and the message it replies to, deduplicated in
    first-seen order. This is the assertion; what it implies about grouping is
    the union below.
    """
    linked: list[str] = []
    for candidate in (
        [envelope.get("message_id")]
        + list(envelope.get("references") or [])
        + [envelope.get("in_reply_to")]
    ):
        if not isinstance(candidate, str):
            continue
        trimmed = candidate.strip()
        if trimmed == "" or trimmed in linked:
            continue
        linked.append(trimmed)
    return linked


# --------------------------------------------------------------------------
# disjoint set over message-identifier tokens
# --------------------------------------------------------------------------


class Components:
    """Union-find over opaque tokens, with path halving and union by size."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._size: dict[str, int] = {}

    def add(self, token: str) -> str:
        if token not in self._parent:
            self._parent[token] = token
            self._size[token] = 1
        return token

    def find(self, token: str) -> str:
        self.add(token)
        root = token
        while self._parent[root] != root:
            self._parent[root] = self._parent[self._parent[root]]
            root = self._parent[root]
        return root

    def union(self, left: str, right: str) -> str:
        a, b = self.find(left), self.find(right)
        if a == b:
            return a
        if self._size[a] < self._size[b]:
            a, b = b, a
        self._parent[b] = a
        self._size[a] += self._size[b]
        return a


# --------------------------------------------------------------------------
# the pieces of a run
# --------------------------------------------------------------------------


@dataclass
class Delivery:
    """One accepted transport delivery, with where it sits in the run."""

    index: int
    tenant_id: str
    transport_id: str
    message_id: str
    from_address: str
    received_at: str
    kind: str
    anchor: str
    linked: list[str]
    #: True when the desk sent it rather than received it.
    outbound: bool = False
    #: Index at which this delivery could first be placed. Its own, unless it
    #: waits on a parent.
    placeable: int = -1
    #: How many replies deep it sits behind the delivery that released it.
    depth: int = 0


@dataclass
class Ticket:
    """A ticket, as this model accounts for one. Identity is the label."""

    label: str
    tenant_id: str
    sequence: int
    created_at: str
    status: str = "open"
    closed_at: str | None = None
    prior: str | None = None
    merged_into: str | None = None
    requester: str | None = None
    transports: list[str] = field(default_factory=list)


@dataclass
class Response:
    """What the intake route answered for one posted delivery."""

    index: int
    transport_id: str
    action: str
    group: str | None


@dataclass
class Composed:
    """A reply the console handed over, and where it got to.

    `order` is the position in the run at which it was composed, which is what
    the desk offers the transport in. `dispatched_at` is the operation index of
    the tick that got it onto the wire, and is -1 while it is still queued.
    """

    reply_id: str
    tenant_id: str
    ticket_of: str | None
    message_id: str
    from_address: str
    to_addresses: list[str]
    in_reply_to: str
    references: list[str]
    composed_at: str
    order: int
    state: str = "queued"
    dispatched_at: int = -1
    #: True for a row that came out of the history rather than the console, so
    #: its key is the migration's invention and is not graded.
    historical: bool = False
    #: Answers the console got, by operation index, when it handed this over.
    answered: dict[int, str] = field(default_factory=dict)


class Threads:
    """The threads of one desk, and the tickets each one holds.

    A thread is an integer. Identifiers point at one; tickets belong to one; two
    threads becoming one is a reassignment of both. Nothing here is derived from
    a message identifier's text, which is the point: the service reaches the same
    grouping through hashes and this model reaches it through labels.
    """

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.owner: dict[str, int] = {}
        self.tickets: dict[int, list[Ticket]] = {}
        self._next_thread = 0
        self._next_sequence = 0

    def open_thread(self) -> int:
        self._next_thread += 1
        self.tickets[self._next_thread] = []
        return self._next_thread

    def thread_of(self, identifier: str) -> int | None:
        return self.owner.get(identifier)

    def opened(self, thread: int) -> tuple[int, str, int]:
        """How early this thread opened, as a sort key.

        A thread with no ticket has not opened at all and sorts last: a delivery
        that is the first to mention it cannot make it the survivor of a merge.
        Tickets merged away are not counted -- they belong to whichever thread
        absorbed them, and a thread does not get credit for opening early on the
        strength of a ticket it no longer holds.
        """
        standing = [
            ticket for ticket in self.tickets[thread] if ticket.merged_into is None
        ]
        if not standing:
            return (1, "", 0)
        first = min(standing, key=lambda ticket: ticket.sequence)
        return (0, first.created_at, first.sequence)

    def absorb(self, survivor: int, other: int) -> None:
        for identifier, thread in list(self.owner.items()):
            if thread == other:
                self.owner[identifier] = survivor
        self.tickets[survivor].extend(self.tickets[other])
        self.tickets[other] = []

    def mint(self, thread: int, created_at: str, prior: str | None) -> Ticket:
        self._next_sequence += 1
        ticket = Ticket(
            label=f"{self.tenant_id}#{self._next_sequence}",
            tenant_id=self.tenant_id,
            sequence=self._next_sequence,
            created_at=created_at,
            prior=prior,
        )
        self.tickets[thread].append(ticket)
        return ticket

    def live(self, thread: int) -> Ticket | None:
        """The ticket a decision is taken against.

        The open one while there is one. Otherwise the ticket holding the
        thread's most recent close, which is not the same as its newest ticket:
        a merge can hand a thread a ticket that opened later and closed earlier.
        Tickets merged away are not candidates for anything.
        """
        standing = [
            ticket for ticket in self.tickets[thread] if ticket.merged_into is None
        ]
        for ticket in standing:
            if ticket.status == "open":
                return ticket
        if not standing:
            return None
        return max(standing, key=lambda ticket: (ticket.closed_at or "", ticket.sequence))


# --------------------------------------------------------------------------
# the fold
# --------------------------------------------------------------------------


class Model:
    """Computes the outcome of a run of operations.

    ``operations`` is the same list the driver executes, in the order it
    executes them:

        {"op": "post",  "envelope": {...}}
        {"op": "pair",  "envelopes": [{...}, {...}]}
        {"op": "close", "tenant_id": ..., "of": <transport_id>, "closed_at": ...}
        {"op": "read",  "tenant_id": ..., "of": <transport_id>}
        {"op": "reply", "tenant_id": ..., "ticket_of": <transport_id>,
                        "reply": {...}}
        {"op": "dispatch", "tenant_id": ...}
        {"op": "tick_pair", "tenant_id": ..., "count": 2}
        {"op": "outbox", "tenant_id": ..., "state": ...}
        {"op": "spool",  "tenant_id": ...}
        {"op": "restart"}

    ``aliases`` maps ``(tenant_id, address)`` to an identity. ``desk`` holds the
    ``(tenant_id, address)`` pairs that are the desks' own addresses; the two
    overlap, and are asked different questions.
    """

    def __init__(
        self,
        operations: Iterable[dict[str, Any]],
        aliases: dict[tuple[str, str], str],
        desk: set[tuple[str, str]] | None = None,
        instructions: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        held_tickets: list[dict[str, Any]] | None = None,
    ) -> None:
        self.operations = list(operations)
        self.aliases = aliases
        self.desk = desk or set()
        self.instructions = list(instructions or [])
        self.history = list(history or [])
        #: The tickets the store already held when the run began.
        self.held_tickets = list(held_tickets or [])
        #: (tenant, reply_id) -> the composed reply.
        self.outbox: dict[tuple[str, str], Composed] = {}
        #: (tenant, message_id) for every message the transport has on the wire.
        self.wire: set[tuple[str, str]] = set()
        #: operation index of every outbox read -> what it should have listed.
        self.outbox_reads: dict[str, list[dict[str, Any]]] = {}
        #: operation index of every spool read -> the messages on the wire then.
        self.spool_reads: dict[str, list[str]] = {}
        self.responses: list[Response] = []
        self.threads: dict[str, Threads] = {}
        self.tickets: dict[str, Ticket] = {}
        #: (tenant, transport) -> the delivery, for accepted deliveries only.
        self.deliveries: dict[tuple[str, str], Delivery] = {}
        #: The deliveries the store already held, in the same shape. They are not
        #: placed by this run -- they were placed before it began -- but a
        #: delivery of this run's that names one of them as its parent is
        #: waiting on a message that has already arrived, so they answer that
        #: question and are kept apart for it.
        self.adopted: list[Delivery] = []
        #: (tenant, transport) -> the ticket the run was last told it is on.
        #: The driver keeps exactly this and closes and reads through it, so the
        #: model has to keep it too or it would be grading a different run.
        self.named: dict[tuple[str, str], str] = {}
        #: operation index of every read -> the ticket it landed on.
        self.read_groups: dict[str, str | None] = {}
        #: operation index of every read -> that ticket as it stood *then*.
        #:
        #: A ticket is not finished when it is read. It can be reopened later, or
        #: merged away, or take another delivery, and a rule whose whole content
        #: is what the ticket looked like at one moment -- a reply the console
        #: has composed and nobody has sent yet -- can only be judged against
        #: that moment. The rules that want the finished ticket ask for it
        #: instead; both are available and each check says which it means.
        self.read_snapshots: dict[str, dict[str, Any]] = {}

    # -- pass zero: the outbound half -------------------------------------

    def _egress(self) -> None:
        """Simulates the desk's outbox and the transport's wire.

        Independent of the tickets, and therefore done first: what the console
        composed, what each tick offered the transport, what the transport said
        and what ended up on the wire are settled by the operations and the
        transport's own behaviour, and the placements follow from the answer
        rather than the other way round.

        The transport's rules are the ones `src/egress/handoff.ts` implements, in
        its order: a message with no recipient is refused before anything else
        happens; a message already on the wire is `already_sent` and the flake
        instruction is not consumed; otherwise the next instruction for that
        message fires, once.
        """
        # History first. A desk that has been in service has its own messages on
        # its tickets already, and they went out to get there: they belong in the
        # outbox as sent, and the key they carry is whatever the migration made
        # up, which is why it is not graded.
        for entry in self.history:
            if (entry["tenant_id"], entry["from_address"].strip().lower()) not in self.desk:
                continue
            key = (entry["tenant_id"], entry["transport_id"])
            self.outbox[key] = Composed(
                reply_id=entry["transport_id"],
                tenant_id=entry["tenant_id"],
                ticket_of=None,
                message_id=entry["message_id"],
                from_address=entry["from_address"],
                to_addresses=[],
                in_reply_to=entry.get("in_reply_to") or "",
                references=[],
                composed_at=entry["received_at"],
                order=-1,
                state="sent",
                historical=True,
            )

        pending_instructions: dict[str, list[str]] = {}
        for item in self.instructions:
            pending_instructions.setdefault(item["message_id"], []).append(item["outcome"])

        order = 0
        for index, operation in enumerate(self.operations):
            kind = operation["op"]
            if kind == "reply":
                order += 1
                self._on_compose(index, operation, order)
            elif kind in ("dispatch", "tick_pair"):
                # Several ticks at once come to the same thing as one, and that
                # is the whole of what the run asserts about them. Each queued
                # reply is offered, the wire is keyed on the message so a second
                # offer of it is not a second message, and a reply that went out
                # is sent whichever call put it there. The generator keeps the
                # transport's flakiness away from concurrent ticks precisely so
                # that this stays true.
                self._on_tick(index, operation, pending_instructions)
            elif kind == "outbox":
                self.outbox_reads[str(index)] = self._outbox_view(
                    operation["tenant_id"], operation.get("state")
                )
            elif kind == "spool":
                tenant = operation["tenant_id"]
                self.spool_reads[str(index)] = sorted(
                    message for owner, message in self.wire if owner == tenant
                )

    def _on_compose(self, index: int, operation: dict[str, Any], order: int) -> None:
        """The console handing a reply over, including handing it over again.

        A retry is answered from where the reply is, which after a tick is not
        where the console left it. A retry that re-queued a reply that has gone
        out would send it twice; a retry answered `queued` when it has already
        gone out tells the console to keep trying.
        """
        tenant = operation["tenant_id"]
        body = operation["reply"]
        owner = operation.get("ticket_tenant", tenant)
        if operation.get("ticket_id") is not None or owner != tenant:
            # A ticket that is not this desk's. Nothing is taken, and nothing
            # about the outbox changes.
            return

        key = (tenant, body["reply_id"])
        existing = self.outbox.get(key)
        if existing is not None:
            existing.answered[index] = existing.state
            return
        composed = Composed(
            reply_id=body["reply_id"],
            tenant_id=tenant,
            ticket_of=operation.get("ticket_of"),
            message_id=body["message_id"],
            from_address=body["from_address"],
            to_addresses=list(body.get("to_addresses") or []),
            in_reply_to=body["in_reply_to"],
            references=list(body.get("references") or []),
            composed_at=body["composed_at"],
            order=order,
        )
        composed.answered[index] = "queued"
        self.outbox[key] = composed

    def _on_tick(
        self,
        index: int,
        operation: dict[str, Any],
        pending_instructions: dict[str, list[str]],
    ) -> None:
        tenants = (
            [operation["tenant_id"]]
            if operation.get("tenant_id")
            else sorted({tenant for tenant, _ in self.outbox})
        )
        for tenant in tenants:
            queued = [
                composed
                for (owner, _), composed in self.outbox.items()
                if owner == tenant and composed.state == "queued"
            ]
            queued.sort(key=lambda composed: (composed.composed_at, composed.reply_id))
            for composed in queued:
                outcome = self._hand_off(composed, pending_instructions)
                if outcome == "refused":
                    composed.state = "refused"
                elif outcome in ("sent", "already_sent"):
                    composed.state = "sent"
                    composed.dispatched_at = index
                # `unknown` leaves it queued, which is where it already is.

    def _hand_off(
        self, composed: Composed, pending_instructions: dict[str, list[str]]
    ) -> str:
        if not composed.to_addresses:
            return "refused"
        on_wire = (composed.tenant_id, composed.message_id)
        if on_wire in self.wire:
            return "already_sent"
        waiting = pending_instructions.get(composed.message_id) or []
        if waiting:
            instruction = waiting.pop(0)
            if instruction == "unknown-lost":
                return "unknown"
            if instruction == "unknown-landed":
                self.wire.add(on_wire)
                return "unknown"
        self.wire.add(on_wire)
        return "sent"

    def _outbox_view(self, tenant: str, state: str | None) -> list[dict[str, Any]]:
        rows = [
            composed
            for (owner, _), composed in self.outbox.items()
            if owner == tenant and (state is None or composed.state == state)
        ]
        rows.sort(key=lambda composed: (composed.order, composed.reply_id))
        return [
            {
                "reply_id": None if composed.historical else composed.reply_id,
                "message_id": composed.message_id,
                "state": composed.state,
            }
            for composed in rows
        ]

    # -- pass one: who is in which conversation ---------------------------

    def _collect(self) -> list[tuple[int, dict[str, Any]]]:
        """Every posted delivery, paired with the index of the op that posted it.

        A delivery presented twice is one delivery; the repeats are answered from
        where that delivery is when they arrive and contribute nothing to the
        accounting. The two halves of a concurrent pair share one index, because
        neither can see the other's effect.
        """
        posted: list[tuple[int, dict[str, Any]]] = []
        for index, operation in enumerate(self.operations):
            if operation["op"] == "post":
                posted.append((index, operation["envelope"]))
            elif operation["op"] == "pair":
                for envelope in operation["envelopes"]:
                    posted.append((index, envelope))
        return posted

    def _relax(self, deliveries: list[Delivery]) -> None:
        """Solve for the index at which each delivery could first be placed.

        A delivery that states its own root is placeable when it arrives. A
        delivery that only names its parent is placeable when the parent is --
        which may itself be waiting. Relax until nothing moves; a delivery whose
        parent never arrives stays unplaceable and is reported as such.

        A parent the store already held counts as arrived, because it did. Those
        deliveries are seeded here on the same footing as this run's, and the
        earliest carrier of an identifier wins either way.
        """
        by_message: dict[tuple[str, str], Delivery] = {}
        for delivery in self.adopted:
            by_message[(delivery.tenant_id, delivery.message_id)] = delivery
        for delivery in deliveries:
            key = (delivery.tenant_id, delivery.message_id)
            existing = by_message.get(key)
            if existing is None or (instant_key(delivery.received_at), delivery.transport_id) < (
                instant_key(existing.received_at),
                existing.transport_id,
            ):
                by_message[key] = delivery

        for delivery in deliveries:
            delivery.placeable = delivery.index if delivery.kind == "root" else -1
            delivery.depth = 0

        for _ in range(len(deliveries) + 1):
            moved = False
            for delivery in deliveries:
                if delivery.kind != "parent":
                    continue
                parent = by_message.get((delivery.tenant_id, delivery.anchor))
                if parent is None or parent.placeable < 0:
                    continue
                candidate = max(delivery.index, parent.placeable)
                depth = parent.depth + (1 if candidate > delivery.index else 0)
                if delivery.placeable != candidate or delivery.depth != depth:
                    delivery.placeable = candidate
                    delivery.depth = depth
                    moved = True
            if not moved:
                break
        else:
            raise ValueError("placement did not settle")

    # -- pass two: the fold -----------------------------------------------

    def _threads_for(self, tenant_id: str) -> Threads:
        threads = self.threads.get(tenant_id)
        if threads is None:
            threads = Threads(tenant_id)
            self.threads[tenant_id] = threads
        return threads

    def _stated_thread(self, threads: Threads, delivery: Delivery) -> int | None:
        """The thread the delivery's own headers point at, before reconciling.

        A stated root names one outright: whichever thread already holds that
        identifier, or a new one. A delivery that names only a parent does not
        name a thread at all -- its conversation is the parent's, whatever that
        turns out to be -- so until a delivery carrying that identifier has been
        placed this is None and the delivery waits.
        """
        existing = threads.thread_of(delivery.anchor)
        if existing is not None:
            return existing
        if delivery.kind == "parent":
            return None
        return threads.open_thread()

    def _reconcile(self, threads: Threads, thread: int, closed_at: str) -> None:
        """Leaves a merged thread with at most one open ticket.

        Each side of a merge could have had one, so all but the earliest to open
        are folded into it: their deliveries move across, they close at the
        instant of the delivery that brought them together, and each records the
        ticket it went into. Tickets already closed are left exactly as they are.
        They are history, and this thread's history is now longer than it looked.
        """
        standing = [
            ticket
            for ticket in threads.tickets[thread]
            if ticket.merged_into is None and ticket.status == "open"
        ]
        if len(standing) < 2:
            return
        standing.sort(key=lambda ticket: (ticket.created_at, ticket.sequence))
        survivor = standing[0]
        for ticket in standing[1:]:
            survivor.transports.extend(ticket.transports)
            ticket.transports = []
            ticket.status = "closed"
            ticket.closed_at = closed_at
            ticket.merged_into = survivor.label

    def _attach(self, threads: Threads, thread: int, delivery: Delivery) -> tuple[str, Ticket]:
        """Places a delivery on a ticket, and says what that was.

        Which ticket the thread is on is direction-blind: a delivery is recorded
        on the thread's live ticket whoever sent it. What direction settles is
        whether the delivery moves that ticket's lifecycle on. Coming back from a
        close, and starting a fresh ticket once the window has run out, are
        answers to a customer getting back in touch; the desk following up on its
        own case is not the case starting again, and a desk that could reopen its
        own closed tickets by answering them could never close one. So an
        outbound delivery lands on the ticket exactly as it finds it.

        A thread with no ticket at all is the exception, and it is not one: there
        is no lifecycle to leave alone, and the delivery has to be recorded
        somewhere. The desk writing first opens a case with nobody's name on it
        yet.
        """
        live = threads.live(thread)
        if live is None:
            ticket = threads.mint(thread, delivery.received_at, None)
            self._land(ticket, delivery)
            self.tickets[ticket.label] = ticket
            return ("created", ticket)
        if live.status == "open":
            self._land(live, delivery)
            return ("appended", live)
        if delivery.outbound:
            self._land(live, delivery)
            return ("appended", live)
        if within_reopen_window(live.closed_at or "", delivery.received_at):
            live.status = "open"
            live.closed_at = None
            self._land(live, delivery)
            return ("reopened", live)
        ticket = threads.mint(thread, delivery.received_at, live.label)
        self._land(ticket, delivery)
        self.tickets[ticket.label] = ticket
        return ("created", ticket)

    def _land(self, ticket: Ticket, delivery: Delivery) -> None:
        """Records the delivery on the ticket, and whose case that makes it.

        A ticket is one requester's, and the requester is whoever wrote in: the
        desk's own addresses resolve to an identity like anybody else's, and it
        is not the identity whose case this is. Once a ticket has a requester it
        keeps it -- a case does not change hands because a colleague of the
        requester wrote in on it.
        """
        ticket.transports.append(delivery.transport_id)
        if delivery.outbound or ticket.requester is not None:
            return
        resolved = self.aliases.get(
            (delivery.tenant_id, delivery.from_address.strip().lower())
        )
        if resolved is not None:
            ticket.requester = resolved

    def _place(self, delivery: Delivery) -> tuple[str, Ticket]:
        """Reconcile the threads this delivery names, then place it on one."""
        threads = self._threads_for(delivery.tenant_id)
        stated = self._stated_thread(threads, delivery)
        if stated is None:
            raise ValueError(f"{delivery.transport_id} was placed before its parent")

        candidates = [stated]
        for identifier in delivery.linked:
            thread = threads.thread_of(identifier)
            if thread is not None and thread not in candidates:
                candidates.append(thread)

        survivor = stated
        if len(candidates) > 1:
            ranked = sorted(candidates, key=threads.opened)
            survivor = ranked[0]
            for other in ranked[1:]:
                threads.absorb(survivor, other)
            self._reconcile(threads, survivor, delivery.received_at)

        action, ticket = self._attach(threads, survivor, delivery)
        for identifier in delivery.linked:
            threads.owner[identifier] = survivor
        return (action, ticket)

    # -- driving ----------------------------------------------------------

    def _adopt(self) -> None:
        """The tickets the store already held, primed into the fold.

        A desk that has been open for a while is handed over with rows in
        `tickets` and `envelopes` and nothing else, and the conversations those
        rows describe are the conversations they always were: the identifiers
        their deliveries mention belong to them, the ticket is in the state its
        own row says, and it belongs to the requester its own row names. Nothing
        about that is derived here -- the store is the authority for its own
        past, and this model reads it rather than recomputing it.

        The consequence is the whole of what makes history routable. A delivery
        arriving afterwards that names one of those identifiers finds a thread
        that already has a ticket on it, and so appends to it, reopens it or
        succeeds it exactly as it would for a conversation that arrived over
        intake. A run in which nothing was adopted answers those deliveries with
        a second ticket beside the one they belong on.

        Ordered by the instant each ticket opened, because `sequence` is what
        decides which of two tickets survives a merge and the desk's past opened
        before anything in this run did.
        """
        held: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for entry in self.history:
            key = (entry["tenant_id"], entry.get("ticket_id") or "")
            held.setdefault(key, []).append(entry)

        for row in sorted(
            self.held_tickets,
            key=lambda item: (item["tenant_id"], item["created_at"], item["ticket_id"]),
        ):
            tenant = row["tenant_id"]
            threads = self._threads_for(tenant)
            thread = threads.open_thread()
            ticket = threads.mint(thread, row["created_at"], None)
            ticket.status = row["status"]
            ticket.closed_at = row.get("closed_at")
            ticket.requester = row.get("requester_identity_id")
            self.tickets[ticket.label] = ticket

            entries = sorted(
                held.get((tenant, row["ticket_id"])) or [],
                key=lambda item: (instant_key(item["received_at"]), item["transport_id"]),
            )
            for entry in entries:
                envelope = _as_envelope(entry)
                delivery = Delivery(
                    index=-1,
                    tenant_id=tenant,
                    transport_id=entry["transport_id"],
                    message_id=entry["message_id"],
                    from_address=entry["from_address"],
                    received_at=entry["received_at"],
                    kind="root",
                    anchor=entry["message_id"],
                    linked=linked_identifiers(envelope),
                    outbound=is_outbound(envelope, self.desk),
                    # Placeable from the beginning of the run, because it was
                    # placed before the beginning of the run. A delivery of this
                    # run's that replies to it is held up by nothing.
                    placeable=0,
                )
                self.deliveries[(tenant, entry["transport_id"])] = delivery
                self.adopted.append(delivery)
                ticket.transports.append(entry["transport_id"])
                for identifier in delivery.linked:
                    threads.owner.setdefault(identifier, thread)

    def run(self) -> dict[str, Any]:
        self._egress()
        self._adopt()
        posted = self._collect()

        # Every message the desk itself put on the wire, and the key it went out
        # under. A delivery carrying one of these identifiers under any other
        # transport identifier is the gateway showing the desk its own send: a
        # message intake has already accounted for, on a delivery it has never
        # seen. Neither identifier answers that on its own, which is the whole of
        # the difficulty -- the transport identifier is new, and a message
        # arriving twice is ordinarily two deliveries.
        own_sends: dict[tuple[str, str], str] = {
            (composed.tenant_id, composed.message_id): composed.reply_id
            for composed in self.outbox.values()
        }

        first_seen: dict[tuple[str, str], int] = {}
        deliveries: list[Delivery] = []
        reflections: list[tuple[int, dict[str, Any]]] = []
        for index, envelope in posted:
            tenant = envelope["tenant_id"]
            key = (tenant, envelope["transport_id"])
            if key in first_seen:
                continue
            sent_under = own_sends.get((tenant, envelope["message_id"]))
            if sent_under is not None and sent_under != envelope["transport_id"]:
                reflections.append((index, envelope))
                continue
            first_seen[key] = index
            kind, anchor = root_reference(envelope)
            delivery = Delivery(
                index=index,
                tenant_id=tenant,
                transport_id=envelope["transport_id"],
                message_id=envelope["message_id"],
                from_address=envelope["from_address"],
                received_at=envelope["received_at"],
                kind=kind,
                anchor=anchor,
                linked=linked_identifiers(envelope),
                outbound=is_outbound(envelope, self.desk),
            )
            deliveries.append(delivery)
            self.deliveries[key] = delivery

        # A reply that reached the wire is a delivery on the conversation, placed
        # by the tick that sent it rather than by the console that wrote it. Its
        # transport identifier is its own key: the gateway did not deliver it, so
        # there is no identifier from the gateway for it to have.
        for composed in sorted(
            self.outbox.values(), key=lambda item: (item.composed_at, item.reply_id)
        ):
            if composed.dispatched_at < 0 or composed.historical:
                continue
            key = (composed.tenant_id, composed.reply_id)
            first_seen[key] = composed.dispatched_at
            envelope = {
                "tenant_id": composed.tenant_id,
                "transport_id": composed.reply_id,
                "message_id": composed.message_id,
                "from_address": composed.from_address,
                "to_addresses": composed.to_addresses,
                "in_reply_to": composed.in_reply_to,
                "references": composed.references,
                "received_at": composed.composed_at,
            }
            kind, anchor = root_reference(envelope)
            delivery = Delivery(
                index=composed.dispatched_at,
                tenant_id=composed.tenant_id,
                transport_id=composed.reply_id,
                message_id=composed.message_id,
                from_address=composed.from_address,
                received_at=composed.composed_at,
                kind=kind,
                anchor=anchor,
                linked=linked_identifiers(envelope),
                outbound=True,
            )
            deliveries.append(delivery)
            self.deliveries[key] = delivery

        self._relax(deliveries)

        # One event list, in the order the run performs it. Placements sort
        # before nothing and after nothing in particular except that a delivery
        # released by another sorts after the delivery that released it, which is
        # what `depth` is for.
        events: list[tuple[int, int, int, str, str, Any]] = []
        for delivery in deliveries:
            if delivery.placeable < 0:
                continue
            events.append(
                (
                    delivery.placeable,
                    1,
                    delivery.depth,
                    delivery.received_at,
                    delivery.transport_id,
                    ("place", delivery),
                )
            )
        reflected_keys = {
            (envelope["tenant_id"], envelope["transport_id"])
            for _, envelope in reflections
        }
        for index, envelope in reflections:
            events.append(
                (
                    index,
                    2,
                    0,
                    "",
                    envelope["transport_id"],
                    ("reflect", index, envelope),
                )
            )
        for index, operation in enumerate(self.operations):
            if operation["op"] == "close":
                events.append((index, 0, 0, "", "", ("close", index, operation)))
            elif operation["op"] == "read":
                events.append((index, 2, 0, "", "", ("read", index, operation)))
            elif operation["op"] in ("post", "pair"):
                for envelope in (
                    [operation["envelope"]]
                    if operation["op"] == "post"
                    else operation["envelopes"]
                ):
                    key = (envelope["tenant_id"], envelope["transport_id"])
                    if key in reflected_keys:
                        # Answered as a reflection, above. Presenting one again
                        # is answered the same way, which the reflection event
                        # for this index already covers.
                        continue
                    if first_seen.get(key) != index:
                        events.append(
                            (
                                index,
                                2,
                                0,
                                "",
                                envelope["transport_id"],
                                ("repeat", index, envelope),
                            )
                        )
        events.sort(key=lambda entry: entry[:5])

        unplaceable = {
            delivery.transport_id: delivery
            for delivery in deliveries
            if delivery.placeable < 0
        }
        for delivery in unplaceable.values():
            # Held for a parent that never arrived: accepted, never placed.
            self.responses.append(
                Response(
                    index=delivery.index,
                    transport_id=delivery.transport_id,
                    action="pending",
                    group=None,
                )
            )

        for _, _, _, _, _, entry in events:
            kind = entry[0]
            if kind == "place":
                self._on_place(entry[1])
            elif kind == "close":
                self._on_close(entry[2])
            elif kind == "read":
                self._on_read(entry[1], entry[2])
            elif kind == "reflect":
                self._on_reflect(entry[1], entry[2])
            else:
                self._on_repeat(entry[1], entry[2])

        self.responses.sort(key=lambda response: (response.index, response.transport_id))
        return self._report()

    def _on_place(self, delivery: Delivery) -> None:
        action, ticket = self._place(delivery)
        # A delivery placed later than it arrived was answered `pending` at the
        # time, with no ticket: what it eventually joined is visible on the
        # ticket, not in that response.
        waited = delivery.placeable > delivery.index
        self.responses.append(
            Response(
                index=delivery.index,
                transport_id=delivery.transport_id,
                action="pending" if waited else action,
                group=None if waited else ticket.label,
            )
        )
        if not waited:
            self.named[(delivery.tenant_id, delivery.transport_id)] = ticket.label

    def _on_repeat(self, index: int, envelope: dict[str, Any]) -> None:
        """A delivery presented again, answered from where it is now.

        Not from where it was when it was first accepted: a ticket it was merged
        away from is not where that delivery is any more.
        """
        tenant = envelope["tenant_id"]
        transport = envelope["transport_id"]
        holder = self._holder(tenant, transport)
        self.responses.append(
            Response(
                index=index,
                transport_id=transport,
                action="duplicate",
                group=holder,
            )
        )
        if holder is not None:
            self.named[(tenant, transport)] = holder

    def _on_reflect(self, index: int, envelope: dict[str, Any]) -> None:
        """A message of the desk's own, handed back by a gateway that reflects.

        Recorded already, by the tick that sent it, so there is nothing to
        record and nothing to decide: the answer names the ticket the message is
        on. A submission that recorded it instead has the ticket holding one
        message twice under two transport identifiers, which the ticket read
        shows whatever this answer says.
        """
        tenant = envelope["tenant_id"]
        transport = envelope["transport_id"]
        holder = self._holder_of_message(tenant, envelope["message_id"])
        self.responses.append(
            Response(index=index, transport_id=transport, action="duplicate", group=holder)
        )
        if holder is not None:
            self.named[(tenant, transport)] = holder

    def _holder_of_message(self, tenant: str, message_id: str) -> str | None:
        for label, ticket in self.tickets.items():
            if ticket.tenant_id != tenant:
                continue
            for transport in ticket.transports:
                delivery = self.deliveries.get((tenant, transport))
                if delivery is not None and delivery.message_id == message_id:
                    return label
        return None

    def _holder(self, tenant: str, transport: str) -> str | None:
        """The ticket a delivery is on now, or None while it is still held."""
        for label, ticket in self.tickets.items():
            if ticket.tenant_id == tenant and transport in ticket.transports:
                return label
        return None

    def _on_close(self, operation: dict[str, Any]) -> None:
        tenant = operation["tenant_id"]
        label = self._named_for(tenant, operation["of"])
        if label is None:
            raise ValueError(f"close names a delivery on no ticket: {operation['of']}")
        ticket = self.tickets[label]
        if ticket.status != "open":
            raise ValueError(
                f"close names a ticket that is not open: {operation['of']} on {label}"
            )
        ticket.status = "closed"
        ticket.closed_at = operation["closed_at"]

    def _on_read(self, index: int, operation: dict[str, Any]) -> None:
        label = self._named_for(operation["tenant_id"], operation["of"])
        self.read_groups[str(index)] = label
        if label is None:
            return
        ticket = self.tickets[label]
        entries = [
            self.deliveries[(ticket.tenant_id, transport)]
            for transport in ticket.transports
        ]
        entries.sort(key=lambda delivery: (instant_key(delivery.received_at), delivery.transport_id))
        self.read_snapshots[str(index)] = {
            "status": ticket.status,
            "prior_group": ticket.prior,
            "merged_into_group": ticket.merged_into,
            "requester_identity_id": ticket.requester,
            "envelopes": [delivery.transport_id for delivery in entries],
            "messages": [delivery.message_id for delivery in entries],
        }

    def _named_for(self, tenant: str, transport: str) -> str | None:
        """The ticket the run was last told this delivery is on.

        The driver keeps this and nothing else: it closes and reads through the
        identifier the service handed back. Preferring the asking desk and
        falling back to any is what the driver does, and is how a cross-desk read
        gets a ticket identifier to be refused.
        """
        direct = self.named.get((tenant, transport))
        if direct is not None:
            return direct
        for (owner, held), label in self.named.items():
            if held == transport:
                return label
        return None

    def _report(self) -> dict[str, Any]:
        def arrival_order(ticket: Ticket) -> list[str]:
            entries = [
                self.deliveries[(ticket.tenant_id, transport)]
                for transport in ticket.transports
            ]
            entries.sort(key=lambda delivery: (instant_key(delivery.received_at), delivery.transport_id))
            return [delivery.transport_id for delivery in entries]

        def messages_on(ticket: Ticket) -> list[str]:
            entries = [
                self.deliveries[(ticket.tenant_id, transport)]
                for transport in ticket.transports
            ]
            entries.sort(key=lambda delivery: (instant_key(delivery.received_at), delivery.transport_id))
            return [delivery.message_id for delivery in entries]

        return {
            "responses": [
                {
                    "transport_id": response.transport_id,
                    "action": response.action,
                    "group": response.group,
                }
                for response in self.responses
            ],
            "groups": {
                label: {
                    "tenant_id": ticket.tenant_id,
                    "status": ticket.status,
                    "prior_group": ticket.prior,
                    "merged_into_group": ticket.merged_into,
                    "requester_identity_id": ticket.requester,
                    "envelopes": arrival_order(ticket),
                    "messages": messages_on(ticket),
                }
                for label, ticket in sorted(self.tickets.items())
            },
            "read_groups": self.read_groups,
            "read_snapshots": self.read_snapshots,
            "reply_answers": {
                f"{index}": {
                    "tenant_id": composed.tenant_id,
                    "reply_id": composed.reply_id,
                    "state": state,
                }
                for composed in self.outbox.values()
                for index, state in composed.answered.items()
            },
            "outbox_reads": self.outbox_reads,
            "spool_reads": self.spool_reads,
            "replies": {
                composed.reply_id: {
                    "tenant_id": composed.tenant_id,
                    "message_id": composed.message_id,
                    "state": composed.state,
                    "dispatched_at": composed.dispatched_at,
                    "historical": composed.historical,
                }
                for composed in sorted(
                    self.outbox.values(), key=lambda item: (item.tenant_id, item.reply_id)
                )
            },
        }


def evaluate(run_spec: dict[str, Any]) -> dict[str, Any]:
    """Expected outcome of a run described by a run spec."""
    aliases = {
        (entry["tenant_id"], entry["address"].strip().lower()): entry["identity_id"]
        for entry in run_spec["aliases"]
    }
    desk = {
        (entry["tenant_id"], entry["address"].strip().lower())
        for entry in run_spec.get("desk_addresses") or []
    }
    return Model(
        run_spec["operations"],
        aliases,
        desk,
        instructions=run_spec.get("handoff_instructions") or [],
        history=run_spec.get("legacy_envelopes") or [],
        held_tickets=run_spec.get("legacy_tickets") or [],
    ).run()


if __name__ == "__main__":
    import sys

    with open(sys.argv[1], encoding="utf-8") as handle:
        spec = json.load(handle)
    print(json.dumps(evaluate(spec), indent=2, sort_keys=True))
