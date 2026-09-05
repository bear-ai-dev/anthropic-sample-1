#!/usr/bin/env python3
"""Builds the graded run.

Writes `verifier-data/run-spec.json`: the desks, the reference data those desks
are provisioned with, the operations the driver performs in order, and which
graded rule each observation belongs to.

This never enters the task image. The document it produces does, held out from
the workspace.

Every instant is written into the run, so nothing depends on when it is
executed. Filler traffic is drawn from a seeded generator, so two builds of the
same seed produce the same run.

    python3 gen_intake.py --seed 8 --out verifier-data/run-spec.json

Two deliberate constraints on the data, both about keeping rules separable:

*   The 720-hour boundary is never exercised at exactly 720 hours. Whether
    "within seven hundred twenty hours" includes the instant itself is a
    question a competent engineer could answer either way, and grading it would
    be grading a coin flip rather than a rule. The nearest graded cases sit an
    hour either side.

*   Scenarios for one rule avoid disturbing the observations belonging to
    another. The window rule (R5) is exercised only where anchoring on the close
    and anchoring on the conversation's first delivery agree, so that it tests
    the window and not the anchor; the anchor rule (R14) is exercised only where
    they disagree. `subject_token` is consistent within every filler
    conversation, so an implementation that wrongly routes on it still groups
    the filler correctly and fails only the scenarios that set the token
    against the threading. The desk's own deliveries appear in the filler only
    on tickets that are open, where they are ordinary appends whichever way they
    were going, so a submission that never asks about direction still groups all
    of the filler correctly and fails only R16 and R17.
"""

from __future__ import annotations

import argparse
import json
import random
from typing import Any

HOUR_MS = 3_600_000

# Five desks. The identifiers are opaque to the service; nothing derives meaning
# from their shape.
TENANTS = [
    "tnt-4f1a9c20-a001",
    "tnt-4f1a9c20-a002",
    "tnt-4f1a9c20-a003",
    "tnt-4f1a9c20-a004",
    "tnt-4f1a9c20-a005",
]

# Held-out reference data: none of this appears in the workspace, so an
# implementation that leans on the sandbox seed resolves no requester at all.
REQUESTERS = [
    ("idn-h-4820", ["mira.okonjo@northgate.example", "m.okonjo@northgate-mail.example", "mira@okonjo.example"]),
    ("idn-h-4821", ["tobias.reiner@vantage.example", "t.reiner@vantage.example"]),
    ("idn-h-4822", ["sun.park@lattice.example", "sun.park@lattice-eu.example", "spark@lattice.example"]),
    ("idn-h-4823", ["dara.abiola@quill.example"]),
    ("idn-h-4824", ["yusuf.demir@harborline.example", "y.demir@harborline.example"]),
    ("idn-h-4825", ["nell.brannigan@ridgeway.example"]),
    ("idn-h-4826", ["ines.saldana@copperfield.example", "i.saldana@copperfield.example"]),
]

DESK_ADDRESS = "help@desk.internal"

# The desks' own addresses, and the identity behind them. Every desk here is
# staffed by one queue account with an alias row of its own, so an address the
# desk sends from resolves to an identity exactly as a requester's does. The
# alias table answers "who is this address"; it does not answer "whose case is
# this", and these rows are what makes the difference measurable.
DESK_IDENTITY = "idn-h-4890"
DESK_ADDRESSES = [DESK_ADDRESS, "agents@desk.internal"]

# Which desks' transports put the desk's own traffic back on the wire in front
# of the gateway. Deliberately not uniform, and deliberately not in a pattern
# that can be guessed from the first desk read: two of the five reflect, and the
# graded egress scenarios are spread across both kinds so that a submission
# which handles one kind and generalises fails the other.
DESK_GATEWAYS = {
    TENANTS[0]: 1,
    TENANTS[1]: 0,
    TENANTS[2]: 1,
    TENANTS[3]: 0,
    TENANTS[4]: 0,
}

# The history the desks already had, in the two tables the shipped schema
# defines and nothing else. Written before the submission's migrations are run
# for the second time, so a migration that moves existing state has state to
# move -- and the desk's own messages here went out to get onto these tickets,
# which is a fact about them that the outbox has to agree with.
#
# Asymmetric on purpose: one desk that reflects and one that does not, one ticket
# open and one closed, one with a single outbound message and one with two, and
# an inbound-only ticket on a third desk whose deliveries must not be mistaken
# for sends. Nothing here shares an identifier with anything else in the run.
LEGACY_TICKETS = [
    {
        "ticket_id": "lgc-6c1f0e42-0001",
        "tenant_id": TENANTS[0],
        "status": "open",
        "requester_identity_id": "idn-h-4820",
        "created_at": "2025-08-04T09:00:00Z",
        "closed_at": None,
    },
    {
        "ticket_id": "lgc-6c1f0e42-0002",
        "tenant_id": TENANTS[3],
        "status": "closed",
        "requester_identity_id": "idn-h-4824",
        "created_at": "2025-08-11T14:00:00Z",
        "closed_at": "2025-08-19T08:00:00Z",
    },
    {
        "ticket_id": "lgc-6c1f0e42-0003",
        "tenant_id": TENANTS[2],
        "status": "open",
        "requester_identity_id": "idn-h-4822",
        "created_at": "2025-09-02T11:00:00Z",
        "closed_at": None,
    },
    # Closed long enough ago that a customer coming back is a fresh case. The
    # instant is on the ticket row and nowhere else, so a run that did not adopt
    # the history has no anchor to measure against.
    {
        "ticket_id": "lgc-6c1f0e42-0004",
        "tenant_id": TENANTS[4],
        "status": "closed",
        "requester_identity_id": "idn-h-4825",
        "created_at": "2025-08-15T07:00:00Z",
        "closed_at": "2025-08-20T10:00:00Z",
    },
]


def _legacy(
    transport: str,
    ticket: str,
    tenant: str,
    message: str,
    sender: str,
    received: str,
    to: str,
    in_reply_to: str | None = None,
) -> dict[str, Any]:
    return {
        "transport_id": transport,
        "tenant_id": tenant,
        "ticket_id": ticket,
        "message_id": message,
        "from_address": sender,
        "to_addresses": json.dumps([to]),
        "in_reply_to": in_reply_to,
        "references_json": json.dumps([]),
        "subject_token": None,
        "received_at": received,
    }


LEGACY_ENVELOPES = [
    # lgc-0001, on a desk that reflects: customer, desk, desk.
    _legacy(
        "trn-lgc-0001", "lgc-6c1f0e42-0001", TENANTS[0], "<m-lgc-a-root@old>",
        "mira.okonjo@northgate.example", "2025-08-04T09:00:00Z", DESK_ADDRESS,
    ),
    _legacy(
        "trn-lgc-0002", "lgc-6c1f0e42-0001", TENANTS[0], "<m-lgc-a-desk1@old>",
        DESK_ADDRESS, "2025-08-04T13:00:00Z", "mira.okonjo@northgate.example",
        in_reply_to="<m-lgc-a-root@old>",
    ),
    _legacy(
        "trn-lgc-0003", "lgc-6c1f0e42-0001", TENANTS[0], "<m-lgc-a-desk2@old>",
        "agents@desk.internal", "2025-08-05T10:00:00Z", "mira.okonjo@northgate.example",
        in_reply_to="<m-lgc-a-root@old>",
    ),
    # lgc-0002, on a desk that does not reflect, and closed: customer, desk.
    _legacy(
        "trn-lgc-0004", "lgc-6c1f0e42-0002", TENANTS[3], "<m-lgc-b-root@old>",
        "yusuf.demir@harborline.example", "2025-08-11T14:00:00Z", DESK_ADDRESS,
    ),
    _legacy(
        "trn-lgc-0005", "lgc-6c1f0e42-0002", TENANTS[3], "<m-lgc-b-desk@old>",
        DESK_ADDRESS, "2025-08-12T09:30:00Z", "yusuf.demir@harborline.example",
        in_reply_to="<m-lgc-b-root@old>",
    ),
    # lgc-0003: two customer deliveries and nothing from the desk. A migration
    # that puts every historical delivery in the outbox rather than the desk's
    # own puts these there, and there is no other way to notice.
    _legacy(
        "trn-lgc-0006", "lgc-6c1f0e42-0003", TENANTS[2], "<m-lgc-c-root@old>",
        "sun.park@lattice.example", "2025-09-02T11:00:00Z", DESK_ADDRESS,
    ),
    _legacy(
        "trn-lgc-0007", "lgc-6c1f0e42-0003", TENANTS[2], "<m-lgc-c-more@old>",
        "spark@lattice.example", "2025-09-03T08:00:00Z", DESK_ADDRESS,
        in_reply_to="<m-lgc-c-root@old>",
    ),
    # lgc-0004: one customer delivery on a ticket that was closed. Nothing
    # outbound, so it says nothing about the outbox and everything about the
    # anchor.
    _legacy(
        "trn-lgc-0008", "lgc-6c1f0e42-0004", TENANTS[4], "<m-lgc-d-root@old>",
        "nell.brannigan@ridgeway.example", "2025-08-15T07:00:00Z", DESK_ADDRESS,
    ),
]

# Which fields of a ticket read each rule is entitled to be judged on. Keeping
# these narrow is what lets one wrong reading fail one rule: a ticket read is
# consulted by several rules at once, and comparing everything on every read
# would make every candidate fail everything.
READ_FIELDS = {
    "R1": ["ticket", "envelopes_set"],
    "R2": ["ticket", "envelopes_set"],
    "R3": ["ticket", "status", "envelopes_set"],
    "R4": ["ticket", "status", "envelopes_set"],
    "R5": ["ticket", "status", "envelopes_set"],
    "R6": ["ticket", "status", "prior", "envelopes_set"],
    "R7": ["requester"],
    "R8": ["ticket", "envelopes_set"],
    "R9": ["ticket", "envelopes_set"],
    "R11": ["ticket", "status", "envelopes_set", "merged"],
    "R12": ["envelopes_order"],
    # Same field as R12, different content: R12 is arrival order against the
    # order of handoff, R28 is arrival order against the order of the TEXT.
    "R28": ["envelopes_order"],
    "R13": ["ticket", "envelopes_set"],
    "R14": ["ticket", "status", "envelopes_set"],
    "R15": ["ticket", "status", "envelopes_set"],
    "R16": ["ticket", "status", "envelopes_set"],
    "R17": ["requester"],
    # The outbound half. `messages` rather than `envelopes_set` wherever what
    # matters is how many distinct messages a ticket holds: a reply the desk sent
    # and the gateway handed back is one message, and the transport identifier it
    # is recorded under is a choice nothing visible settles.
    "R19": ["ticket", "messages"],
    "R20": ["ticket", "status", "messages"],
    "R21": ["ticket", "messages"],
    "R22": ["ticket", "messages"],
    "R23": ["ticket", "status", "messages"],
    "R25": ["ticket", "messages"],
    # A conversation the store already held. `envelopes_order` because what the
    # ticket holds is the whole point -- the deliveries that were already on it,
    # the new one, and the order the two sets interleave in.
    "R26": ["ticket", "status", "requester", "envelopes_order"],
    "R27": ["ticket", "status", "prior", "envelopes_set"],
}

# Which rules are entitled to be judged on the outcome word a delivery is
# answered with, for the same reason READ_FIELDS is narrow.
#
# Every scenario has to open a conversation before it can exercise anything, so
# nearly every rule has a create in it and most have an append. Asserting those
# labels in every rule that merely passes through them makes a single mislabel
# fail most of the rule set, which tells a solver nothing about which reading was
# wrong -- and, worse, leaves the rule the label actually belongs to with no
# candidate that fails it alone. So the label is asserted only where it is the
# point: the create in R3, the append in R4, the reopen in R5, the new ticket
# after the window in R6 and R14, the redelivery in R1, the wait in R9. R2, R7,
# R8, R11, R12 and R13 are judged on where deliveries ended up, which is their
# actual content, and are silent about what the service called it.
#
# R11 is the strongest case for that. A delivery that brings two conversations
# together is not a sixth kind of delivery -- it appended, or it created, by the
# same rules as any other -- so asserting a label there would be asserting a
# label the service is free to choose, and the merge itself would go unmeasured
# behind it.
ACTION_RULES = {"R1", "R3", "R4", "R5", "R6", "R9", "R14", "R15", "R26", "R27"}

RULES = [
    ("R1", "A redelivery of the same transport delivery is answered with the ticket that delivery is on when it is presented again and records nothing further, on the create path and on the append path alike; a different delivery carrying a message identifier already seen is not a redelivery"),
    # This rule used to claim the whole of the conversation key, including which
    # end of a reference chain roots it. It cannot: the key itself is not
    # observable, and a delivery asserts *every* identifier it names to be one
    # conversation, so the grouping is the closure of those assertions and is the
    # same whichever named identifier is called the root. A submission that takes
    # the last reference rather than the first groups the run identically, and a
    # rule that failed it would be grading a hash rather than a behaviour. The
    # matrix has that candidate and it scores full reward.
    #
    # What is observable, and what is graded here, is the desk boundary: two
    # desks using the same message identifiers are two conversations, and no
    # assertion made at one desk reaches the other.
    ("R2", "Identifiers are grouped within the desk that named them; two desks using the same identifiers never share a conversation or a ticket"),
    ("R3", "The first delivery of a conversation opens one ticket, and it is open"),
    ("R4", "A later delivery joins the conversation's open ticket rather than opening another"),
    ("R5", "A reply inside the window of the close returns the same ticket to open"),
    ("R6", "A reply outside the window opens a new ticket, on the same conversation, recording the one it continues"),
    ("R7", "Addresses that alias to one requester resolve to one identity"),
    ("R8", "Two first deliveries in one conversation arriving together yield exactly one ticket"),
    ("R9", "A reply that arrives before the delivery it replies to waits, and is then placed on that delivery's ticket"),
    ("R10", "A read is scoped to the desk that asks: another desk's ticket is not found, and another desk's replies are not in this desk's outbox"),
    ("R11", "A delivery naming identifiers from more than one conversation makes them one: the ticket that opened first keeps the case, the others' deliveries move onto it and they close recording what they went into, and the window is then measured against the merged history's most recent close"),
    ("R12", "A ticket lists its deliveries in the order they arrived, whatever order they were handed over in"),
    ("R13", "subject_token decides nothing, whether it agrees with the threading or contradicts it"),
    ("R14", "The window is anchored on the instant the ticket closed, and on the close it is currently sitting in"),
    ("R15", "Nothing already recorded is forgotten because the process was restarted, including deliveries still waiting for a parent and which conversation an identifier belongs to"),
    # The two rules about the deliveries the desk itself sent. They are one
    # reading -- a delivery from one of the desk's own addresses is the desk
    # talking, not the case moving -- applied to the two things a delivery
    # otherwise decides: the ticket's lifecycle, and whose case it is.
    #
    # Neither is graded on the outcome word. What an outbound delivery is called
    # is the submission's choice among words that mean "recorded, nothing moved";
    # what is graded is that nothing moved. The one label assertion is negative:
    # it was not called a reopen.
    ("R16", "A delivery the desk sent is recorded on the conversation's current ticket and leaves that ticket's state alone: it does not bring a closed ticket back to open, it does not open a successor to one, and the window the next delivery is measured against is unchanged"),
    ("R17", "A ticket belongs to the requester who wrote in on it, never to the desk's own address, and once it has one it keeps it"),
    # ---------------------------------------------------------------------
    # The outbound half. None of these are graded on the outcome word a
    # delivery is answered with: what a reply going out is called when it lands
    # on its ticket is the submission's choice among words that mean "recorded",
    # and the graded content is what is on the wire, what the outbox says, and
    # what the ticket holds.
    ("R18", "A composed reply is taken once however many times the console hands it over, and the answer says where that reply is at that moment rather than where the console left it"),
    ("R19", "Taking a reply is not sending it: before any tick the transport has nothing and the ticket holds nothing for it"),
    ("R20", "A tick offers each queued reply to the transport, and a reply the transport took is on the wire once and recorded on the conversation's ticket once, however many ticks follow"),
    ("R21", "A handoff the transport did not answer leaves the reply queued and is offered again, and the message ends up on the wire once and on its ticket once -- whether the lost answer had reached the wire or not, and across a restart in between"),
    ("R22", "A handoff the transport refused is terminal: the reply is refused, nothing is on the wire for it, nothing is recorded on the ticket, and no later tick offers it again"),
    ("R23", "A message the desk sent that a reflecting gateway hands back is not a second delivery: the ticket holds that message once, and a desk whose gateway does not reflect holds it once as well"),
    ("R24", "History that predates the outbox is already sent: the desk's own messages on existing tickets are in the outbox as sent, deliveries that were sent to the desk are not in it at all, and no tick offers any of them to the transport"),
    ("R25", "A customer's answer to something the desk sent joins the conversation it was sent on"),
    # The two rules about a store that was already in service. Neither is a new
    # convention: R26 is R4 and R17 and R12 asked of a conversation the store
    # already held, and R27 is R5, R6 and R14 asked of a close that was recorded
    # before this service existed. What is new is that the answers are not in any
    # table the routing built -- they are in `tickets` and `envelopes`, which is
    # all a desk arrives with, and getting at them is the migration's job.
    ("R26", "A conversation the store already held is the conversation it was: a delivery continuing it joins the ticket that conversation is on, that ticket keeps the requester it arrived with, and it lists the deliveries it already had beside the new one in arrival order"),
    ("R27", "A ticket the store already held is closed at the instant its own row says: a customer's reply inside the window returns that ticket to open, and one outside it opens a successor recording the ticket it continues"),
    ("R28", "A ticket lists its deliveries in the order of the instants they arrived at: the fraction of a second is part of the instant, whatever width the gateway stamped it to, and a delivery stamped with no fraction is the earliest in its second"),
]


def instant(base_ms: int, hours: float = 0.0, fraction: str | None = None) -> str:
    """An ISO-8601 UTC instant `hours` after `base_ms`.

    Whole seconds unless `fraction` is given, which is the digits after the
    decimal point and is written out exactly as passed -- one digit or six, not
    normalised. That is the point of the parameter: `src/intake/parseEnvelope.ts`
    accepts `\\.\\d{1,6}` and the width a gateway stamps is its own business, so
    two deliveries in one second can carry fractions of different widths and the
    text order of the two values is not the order of the two instants.
    """
    total = base_ms + int(round(hours * HOUR_MS))
    seconds, _ = divmod(total, 1000)
    days, rest = divmod(seconds, 86400)
    hour, rest = divmod(rest, 3600)
    minute, second = divmod(rest, 60)

    z = days + 719468
    era = (z if z >= 0 else z - 146096) // 146097
    day_of_era = z - era * 146097
    year_of_era = (
        day_of_era - day_of_era // 1460 + day_of_era // 36524 - day_of_era // 146096
    ) // 365
    year = year_of_era + era * 400
    day_of_year = day_of_era - (365 * year_of_era + year_of_era // 4 - year_of_era // 100)
    month_prime = (5 * day_of_year + 2) // 153
    day = day_of_year - (153 * month_prime + 2) // 5 + 1
    month = month_prime + (3 if month_prime < 10 else -9)
    year += 1 if month <= 2 else 0

    stamp = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"
    if fraction is None:
        return f"{stamp}Z"
    if not (1 <= len(fraction) <= 6) or not fraction.isdigit():
        raise SystemExit(
            f"fraction must be one to six digits, the domain the shipped"
            f" validation accepts; got {fraction!r}"
        )
    return f"{stamp}.{fraction}Z"


# 2026-01-05T00:00:00Z, as milliseconds since the epoch.
EPOCH_BASE = 1767571200000


class Run:
    """Accumulates operations and the rule each observation belongs to."""

    def __init__(self, seed: int) -> None:
        self.random = random.Random(seed)
        self.operations: list[dict[str, Any]] = []
        self.rules: dict[str, dict[str, Any]] = {}
        self._transport = 0
        self._reply = 0
        #: Handoff instructions, written into the transport's flake file so the
        #: `unknown` outcome happens where the run means it to.
        self.instructions: list[dict[str, Any]] = []

    def transport(self, tag: str) -> str:
        self._transport += 1
        return f"trn-{self._transport:05d}-{tag}"

    def reply_key(self, tag: str) -> str:
        self._reply += 1
        return f"rpl-{self._reply:04d}-{tag}"

    # -- operations -------------------------------------------------------

    def envelope(
        self,
        tenant: str,
        transport: str,
        message: str,
        sender: str,
        received: str,
        in_reply_to: str | None = None,
        references: list[str] | None = None,
        subject_token: str | None = None,
        to: str | None = None,
    ) -> dict[str, Any]:
        return {
            "transport_id": transport,
            "tenant_id": tenant,
            "message_id": message,
            "from_address": sender,
            "to_addresses": [to or DESK_ADDRESS],
            "in_reply_to": in_reply_to,
            "references": references or [],
            "subject_token": subject_token,
            "received_at": received,
        }

    def post(self, *args: Any, **kwargs: Any) -> str:
        envelope = self.envelope(*args, **kwargs)
        self.operations.append({"op": "post", "envelope": envelope})
        return envelope["transport_id"]

    def repost(self, transport: str) -> None:
        """Presents an already-posted delivery again, field for field."""
        for operation in self.operations:
            candidates = (
                [operation["envelope"]]
                if operation["op"] == "post"
                else operation["envelopes"] if operation["op"] == "pair" else []
            )
            for envelope in candidates:
                if envelope["transport_id"] == transport:
                    self.operations.append({"op": "post", "envelope": dict(envelope)})
                    return
        raise ValueError(f"nothing posted with transport {transport}")

    def pair(self, left: dict[str, Any], right: dict[str, Any]) -> None:
        """Two deliveries handed over together, neither seeing the other."""
        self.operations.append({"op": "pair", "envelopes": [left, right]})

    def close(self, tenant: str, of: str, closed_at: str) -> None:
        self.operations.append(
            {"op": "close", "tenant_id": tenant, "of": of, "closed_at": closed_at}
        )

    def read(self, tenant: str, of: str) -> None:
        self.operations.append({"op": "read", "tenant_id": tenant, "of": of})

    def restart(self) -> None:
        """Stops the service and starts it again before the next operation.

        Nothing about the run changes here and the model does not model it: the
        same deliveries are handed over on either side and the same answers are
        expected. What does not survive is whatever the service was holding in
        memory rather than in its store.
        """
        self.operations.append({"op": "restart"})

    # -- the outbound half ------------------------------------------------

    def compose(
        self,
        tenant: str,
        ticket_of: str,
        reply_key: str,
        message: str,
        in_reply_to: str,
        composed_at: str,
        sender: str = DESK_ADDRESS,
        to: list[str] | None = None,
        references: list[str] | None = None,
        ticket_tenant: str | None = None,
        ticket_id: str | None = None,
    ) -> int:
        """The console handing a composed reply over. Returns the op index."""
        operation: dict[str, Any] = {
            "op": "reply",
            "tenant_id": tenant,
            "ticket_of": ticket_of,
            "reply": {
                "reply_id": reply_key,
                "message_id": message,
                "from_address": sender,
                "to_addresses": ["someone@example.invalid"] if to is None else to,
                "in_reply_to": in_reply_to,
                "references": references or [],
                "composed_at": composed_at,
            },
        }
        if ticket_tenant is not None:
            operation["ticket_tenant"] = ticket_tenant
        if ticket_id is not None:
            operation["ticket_id"] = ticket_id
        self.operations.append(operation)
        return len(self.operations) - 1

    def tick(self, tenant: str | None = None) -> int:
        operation: dict[str, Any] = {"op": "dispatch"}
        if tenant is not None:
            operation["tenant_id"] = tenant
        self.operations.append(operation)
        return len(self.operations) - 1

    def tick_pair(self, tenant: str | None = None, count: int = 2) -> int:
        """Two ticks in flight at once, neither having seen the other's effect.

        The desk's timer does not wait for the previous tick and an operator
        does not either, so this is the ordinary case. Both calls see the same
        queued replies and the run asserts only what is settled whichever way
        they interleave: the message is on the wire once, on its ticket once, and
        the reply is sent.

        Deliberately never used on a reply the transport is going to be flaky
        about. With a lost answer in the mix, "queued" and "sent" are both
        defensible after a pair -- one implementation re-offers inside the pair,
        another leaves it for the next tick -- and grading either would be
        grading a choice nothing visible settles.
        """
        operation: dict[str, Any] = {"op": "tick_pair", "count": count}
        if tenant is not None:
            operation["tenant_id"] = tenant
        self.operations.append(operation)
        return len(self.operations) - 1

    def flake(self, message: str, outcome: str) -> None:
        """Makes the transport lose its answer once, for this message.

        `unknown-landed` reaches the wire and the answer is lost; `unknown-lost`
        does not reach it. Both are reported as `unknown`, and the difference is
        the point: nothing the service can see tells it which happened.
        """
        self.instructions.append({"message_id": message, "outcome": outcome})

    # -- rules ------------------------------------------------------------

    def rule(self, rule_id: str, title: str) -> None:
        self.rules.setdefault(rule_id, {"title": title, "checks": []})

    def check(self, rule_id: str, check: dict[str, Any]) -> None:
        self.rules[rule_id]["checks"].append(check)

    def expect_response(self, rule_id: str, transport: str, occurrence: int = 0) -> None:
        if rule_id not in ACTION_RULES:
            return
        self.check(
            rule_id,
            {"kind": "response", "transport_id": transport, "occurrence": occurrence},
        )

    def expect_not_duplicate(self, rule_id: str, transport: str) -> None:
        """Accepted as a delivery of its own, whatever it was then called.

        Which of the accepting outcomes it is belongs to whichever rule owns that
        label, so this asserts only the part that is R1's: it was not mistaken
        for a redelivery.
        """
        self.check(
            rule_id, {"kind": "response_not_duplicate", "transport_id": transport}
        )

    def expect_response_ticket(
        self, rule_id: str, transport: str, occurrence: int = 0
    ) -> None:
        """The ticket a delivery was answered with, and not what it was called.

        Used where the ticket is the point and the outcome word belongs to
        another rule: a delivery that joins a merged conversation is an append,
        and R4 owns appends.
        """
        self.check(
            rule_id,
            {
                "kind": "response_ticket",
                "transport_id": transport,
                "occurrence": occurrence,
            },
        )

    def expect_response_multiset(self, rule_id: str, transports: list[str]) -> None:
        if rule_id not in ACTION_RULES:
            return
        self.check(rule_id, {"kind": "response_multiset", "transports": transports})

    def expect_action_not(
        self, rule_id: str, transport: str, forbidden: list[str]
    ) -> None:
        """Rules out an outcome word without demanding a particular one.

        Used where the interesting thing is a decision the submission did *not*
        take. A delivery the desk sent and the ticket recorded is 'appended' by
        the documented vocabulary, but nothing turns on the word, and a
        submission that spells it its own way is not wrong. A submission that
        answers 'reopened' has told us it brought the ticket back.
        """
        self.check(
            rule_id,
            {
                "kind": "response_action_not",
                "transport_id": transport,
                "forbidden": forbidden,
            },
        )

    def expect_read(
        self,
        rule_id: str,
        tenant: str,
        of: str,
        fields: list[str] | None = None,
        snapshot: bool = False,
    ) -> None:
        """Reads a ticket and asserts about it.

        `snapshot` asks about the ticket as it stood at that moment rather than
        when the run finished. Used where the moment is the rule: a reply the
        console has composed and nobody has sent, a ticket still closed because
        what went out was the desk's own.
        """
        self.read(tenant, of)
        self.check(
            rule_id,
            {
                "kind": "read",
                "snapshot": snapshot,
                # The operation, not the delivery. A read lands on the ticket the
                # service last named for that delivery, and after a merge that is
                # not the ticket the delivery is on -- so which read this is has
                # to be identified by when it happened.
                "index": len(self.operations) - 1,
                "tenant_id": tenant,
                "of": of,
                "fields": fields if fields is not None else READ_FIELDS[rule_id],
            },
        )

    def expect_read_denied(self, rule_id: str, tenant: str, of: str) -> None:
        self.read(tenant, of)
        self.check(
            rule_id,
            {
                "kind": "read_denied",
                "index": len(self.operations) - 1,
                "tenant_id": tenant,
                "of": of,
            },
        )

    def expect_partition(self, rule_id: str, transports: list[str]) -> None:
        self.check(rule_id, {"kind": "partition", "transports": transports})

    def expect_reply_state(self, rule_id: str, index: int) -> None:
        """The answer the console got at that handover."""
        self.check(rule_id, {"kind": "reply_state", "index": index})

    def expect_reply_denied(self, rule_id: str, index: int) -> None:
        self.check(rule_id, {"kind": "reply_denied", "index": index})

    def expect_outbox(
        self,
        rule_id: str,
        tenant: str,
        messages: list[str] | None = None,
        absent: list[str] | None = None,
        state: str | None = None,
    ) -> None:
        """Reads a desk's outbox, and asserts about the messages named.

        Scoped rather than whole: a desk's outbox holds every reply that desk
        ever composed, and comparing all of it would make one wrong reading fail
        every rule that reads that desk.
        """
        operation: dict[str, Any] = {"op": "outbox", "tenant_id": tenant}
        if state is not None:
            operation["state"] = state
        self.operations.append(operation)
        self.check(
            rule_id,
            {
                "kind": "outbox",
                "index": len(self.operations) - 1,
                "tenant_id": tenant,
                "messages": messages or [],
                "absent": absent or [],
            },
        )

    def expect_spool(
        self,
        rule_id: str,
        tenant: str,
        messages: list[str] | None = None,
        absent: list[str] | None = None,
    ) -> None:
        """What is actually on the wire, read from the transport's own side."""
        self.operations.append({"op": "spool", "tenant_id": tenant})
        self.check(
            rule_id,
            {
                "kind": "spool",
                "index": len(self.operations) - 1,
                "tenant_id": tenant,
                "messages": messages or [],
                "absent": absent or [],
            },
        )


def build(seed: int) -> dict[str, Any]:
    run = Run(seed)
    identities: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    desk_addresses: list[dict[str, Any]] = []
    for tenant in TENANTS:
        for identity, addresses in REQUESTERS:
            identities.append(
                {
                    "tenant_id": tenant,
                    "identity_id": identity,
                    "display_name": identity.replace("idn-h-", "Requester "),
                }
            )
            for address in addresses:
                aliases.append(
                    {"tenant_id": tenant, "address": address, "identity_id": identity}
                )
        identities.append(
            {
                "tenant_id": tenant,
                "identity_id": DESK_IDENTITY,
                "display_name": "Desk queue",
            }
        )
        for address in DESK_ADDRESSES:
            aliases.append(
                {"tenant_id": tenant, "address": address, "identity_id": DESK_IDENTITY}
            )
            desk_addresses.append({"tenant_id": tenant, "address": address})

    for rule_id, title in RULES:
        run.rule(rule_id, title)

    # ------------------------------------------------------------------ R3
    # Conversations of one delivery, so the rule that a first delivery opens one
    # open ticket has observations of its own.
    for index in range(6):
        tenant = TENANTS[index % len(TENANTS)]
        base = EPOCH_BASE + (100 + index * 40) * HOUR_MS
        _, addresses = REQUESTERS[index % len(REQUESTERS)]
        opener = run.post(
            tenant,
            run.transport(f"solo{index}"),
            f"<m-solo-{index}@desk>",
            addresses[0],
            instant(base, 0),
        )
        run.expect_response("R3", opener)
        run.expect_partition("R3", [opener])
        run.expect_read("R3", tenant, opener)

    # ------------------------------------------------------------------ R4
    # A root and its replies, all carrying the chain.
    for index, tenant in enumerate(TENANTS):
        base = EPOCH_BASE + (500 + index * 200) * HOUR_MS
        _, addresses = REQUESTERS[index % len(REQUESTERS)]
        root_message = f"<m-basic-{index}-root@desk>"
        first = run.post(
            tenant,
            run.transport(f"basic{index}a"),
            root_message,
            addresses[0],
            instant(base, 0),
        )
        members = [first]
        for step in range(1, 4):
            reply = run.post(
                tenant,
                run.transport(f"basic{index}r{step}"),
                f"<m-basic-{index}-r{step}@desk>",
                addresses[0],
                instant(base, step * 3),
                in_reply_to=root_message,
                references=[root_message],
            )
            members.append(reply)
            run.expect_response("R4", reply)
        run.expect_partition("R4", members)
        run.expect_read("R4", tenant, first)

    # ------------------------------------------------------------------ R2
    # The same identifiers, and the same reference chains, under two desks. Each
    # desk has to reach its own grouping from them and neither may see the
    # other's, so an implementation that keys or looks up identifiers without the
    # desk puts these on one ticket.
    tenant_a, tenant_b = TENANTS[0], TENANTS[1]
    base = EPOCH_BASE + 1600 * HOUR_MS
    tenanted_root = "<m-key-tenanted@desk>"
    tenanted_mid = "<m-key-tenanted-mid@desk>"
    key_ta = run.post(
        tenant_a, run.transport("key-ta"), tenanted_root, REQUESTERS[2][1][0], instant(base, 5)
    )
    key_tb = run.post(
        tenant_b, run.transport("key-tb"), tenanted_root, REQUESTERS[2][1][0], instant(base, 6)
    )
    key_tar = run.post(
        tenant_a, run.transport("key-tar"), tenanted_mid, REQUESTERS[2][1][0],
        instant(base, 7), in_reply_to=tenanted_root, references=[tenanted_root],
    )
    key_tbr = run.post(
        tenant_b, run.transport("key-tbr"), tenanted_mid, REQUESTERS[2][1][0],
        instant(base, 8), in_reply_to=tenanted_root, references=[tenanted_root],
    )
    run.expect_partition("R2", [key_ta, key_tb, key_tar, key_tbr])
    run.expect_read("R2", tenant_a, key_ta)
    run.expect_read("R2", tenant_b, key_tb)

    # ----------------------------------------------------------------- R10
    # Its own pair of conversations, sharing no identifier with anything else in
    # the run. R2's scenario would have done, but the two rules would then fail
    # together: a submission whose lookups ignore the desk puts both desks'
    # deliveries on one ticket, and a cross-desk read of that ticket is served
    # because it really does belong to the desk asking. Separate scenarios keep
    # "grouping respects the desk" and "reads respect the desk" separately
    # falsifiable.
    scope_a = run.post(
        tenant_a, run.transport("scope-a"), "<m-scope-a@desk>", REQUESTERS[5][1][0],
        instant(base, 20),
    )
    scope_b = run.post(
        tenant_b, run.transport("scope-b"), "<m-scope-b@desk>", REQUESTERS[5][1][0],
        instant(base, 21),
    )
    run.expect_read_denied("R10", tenant_b, scope_a)
    run.expect_read_denied("R10", tenant_a, scope_b)

    # ------------------------------------------------------------------ R1
    # Redeliveries on the create path and on the append path, and a distinct
    # delivery carrying a message identifier the desk has already seen. All of
    # the run's duplicate traffic is here, so an implementation that mishandles
    # it fails this rule and disturbs nothing else.
    tenant = TENANTS[2]
    base = EPOCH_BASE + 1800 * HOUR_MS
    _, addresses = REQUESTERS[3]
    dup_root_message = "<m-dup-root@desk>"
    dup_root = run.post(
        tenant, run.transport("dup-root"), dup_root_message, addresses[0], instant(base, 0)
    )
    run.repost(dup_root)
    # Only the redelivery is asserted. What the first handover was called is R3's
    # business, and the redelivery is compared against the ticket the service
    # itself answered with, so nothing here needs that label to be right.
    run.expect_response("R1", dup_root, occurrence=1)

    dup_reply_message = "<m-dup-reply@desk>"
    dup_reply = run.post(
        tenant, run.transport("dup-reply"), dup_reply_message, addresses[0],
        instant(base, 4), in_reply_to=dup_root_message, references=[dup_root_message],
    )
    run.repost(dup_reply)
    run.repost(dup_reply)
    run.expect_response("R1", dup_reply, occurrence=1)
    run.expect_response("R1", dup_reply, occurrence=2)

    resend = run.post(
        tenant, run.transport("dup-resend"), dup_reply_message, addresses[0],
        instant(base, 9), in_reply_to=dup_root_message, references=[dup_root_message],
    )
    run.expect_not_duplicate("R1", resend)
    run.expect_partition("R1", [dup_root, dup_reply, resend])
    run.expect_read("R1", tenant, dup_root)

    # ------------------------------------------------------------------ R5
    # Replies 1 hour and 719 hours after the close. The ticket is closed a
    # quarter of an hour after it opened, so both replies are inside the window
    # whether it is measured from the close or from the conversation's first
    # delivery: this rule tests the window, and R14 tests the anchor.
    for index, hours_after_close in enumerate([1, 719]):
        tenant = TENANTS[index % len(TENANTS)]
        base = EPOCH_BASE + (2200 + index * 2000) * HOUR_MS
        _, addresses = REQUESTERS[(index + 4) % len(REQUESTERS)]
        root_message = f"<m-reopen-in-{index}-root@desk>"
        opener = run.post(
            tenant, run.transport(f"reopin{index}"), root_message, addresses[0], instant(base, 0)
        )
        run.close(tenant, opener, instant(base, 0.25))
        reply = run.post(
            tenant, run.transport(f"reopin{index}r"), f"<m-reopen-in-{index}-r@desk>",
            addresses[0], instant(base, 0.25 + hours_after_close),
            in_reply_to=root_message, references=[root_message],
        )
        run.expect_response("R5", reply)
        run.expect_partition("R5", [opener, reply])
        run.expect_read("R5", tenant, opener)

    # ------------------------------------------------------------------ R6
    # Replies 721 hours and 2000 hours after the close, outside the window on
    # either anchor.
    for index, hours_after_close in enumerate([721, 2000]):
        tenant = TENANTS[(index + 2) % len(TENANTS)]
        base = EPOCH_BASE + (6500 + index * 4000) * HOUR_MS
        _, addresses = REQUESTERS[(index + 5) % len(REQUESTERS)]
        root_message = f"<m-reopen-out-{index}-root@desk>"
        opener = run.post(
            tenant, run.transport(f"reopout{index}"), root_message, addresses[0], instant(base, 0)
        )
        run.close(tenant, opener, instant(base, 0.25))
        reply = run.post(
            tenant, run.transport(f"reopout{index}r"), f"<m-reopen-out-{index}-r@desk>",
            addresses[0], instant(base, 0.25 + hours_after_close),
            in_reply_to=root_message, references=[root_message],
        )
        run.expect_response("R6", reply)
        run.expect_partition("R6", [opener, reply])
        run.expect_read("R6", tenant, opener)
        run.expect_read("R6", tenant, reply)

    # ----------------------------------------------------------------- R14
    # Where the two anchors disagree. The ticket sat open for a long time before
    # it closed, so measuring from the conversation's first delivery puts the
    # reply outside the window while measuring from the close puts it inside.
    tenant = TENANTS[3]
    base = EPOCH_BASE + 15000 * HOUR_MS
    _, addresses = REQUESTERS[0]
    anchor_root = "<m-anchor-late-close-root@desk>"
    anchor_open = run.post(
        tenant, run.transport("anchor-a"), anchor_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, anchor_open, instant(base, 700))
    anchor_reply = run.post(
        tenant, run.transport("anchor-ar"), "<m-anchor-late-close-r@desk>", addresses[0],
        instant(base, 1300), in_reply_to=anchor_root, references=[anchor_root],
    )
    run.expect_response("R14", anchor_reply)
    run.expect_partition("R14", [anchor_open, anchor_reply])
    run.expect_read("R14", tenant, anchor_open)

    # And the close the ticket is currently sitting in: closed, brought back,
    # closed again, then a reply inside the window of the second close and
    # outside the window of the first. The second close names the delivery that
    # brought the ticket back, so it closes whichever ticket that delivery
    # landed on rather than assuming which one that was.
    tenant = TENANTS[4]
    base = EPOCH_BASE + 17000 * HOUR_MS
    _, addresses = REQUESTERS[6]
    recl_root = "<m-anchor-recl-root@desk>"
    recl_open = run.post(
        tenant, run.transport("anchor-b"), recl_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, recl_open, instant(base, 2))
    recl_first = run.post(
        tenant, run.transport("anchor-br1"), "<m-anchor-recl-r1@desk>", addresses[0],
        instant(base, 100), in_reply_to=recl_root, references=[recl_root],
    )
    run.close(tenant, recl_first, instant(base, 900))
    recl_second = run.post(
        tenant, run.transport("anchor-br2"), "<m-anchor-recl-r2@desk>", addresses[0],
        instant(base, 1000), in_reply_to=recl_root, references=[recl_root],
    )
    run.expect_response("R14", recl_first)
    run.expect_response("R14", recl_second)
    run.expect_partition("R14", [recl_open, recl_first, recl_second])
    run.expect_read("R14", tenant, recl_open)

    # ------------------------------------------------------------------ R7
    # One requester writing in from every address they have, on two desks.
    for index, requester_index in enumerate([0, 2, 4]):
        tenant = TENANTS[index % len(TENANTS)]
        base = EPOCH_BASE + (19000 + index * 300) * HOUR_MS
        _, addresses = REQUESTERS[requester_index]
        alias_root = f"<m-alias-{index}-root@desk>"
        first = run.post(
            tenant, run.transport(f"alias{index}a"), alias_root,
            addresses[-1], instant(base, 0),
        )
        run.expect_response("R7", first)
        members = [first]
        for step, address in enumerate(addresses):
            reply = run.post(
                tenant, run.transport(f"alias{index}r{step}"), f"<m-alias-{index}-r{step}@desk>",
                address, instant(base, 2 + step),
                in_reply_to=alias_root, references=[alias_root],
            )
            members.append(reply)
        run.expect_partition("R7", members)
        run.expect_read("R7", tenant, first)

    # ------------------------------------------------------------------ R8
    # Ten conversations whose first two deliveries are handed over together.
    # Neither is the root: the root went out from the desk and never arrived, so
    # both are first deliveries of a conversation that does not exist yet.
    for index in range(10):
        tenant = TENANTS[index % len(TENANTS)]
        base = EPOCH_BASE + (21000 + index * 100) * HOUR_MS
        _, addresses = REQUESTERS[index % len(REQUESTERS)]
        root_message = f"<m-conc-{index}-root@desk>"
        left = run.transport(f"conc{index}l")
        right = run.transport(f"conc{index}r")
        run.pair(
            run.envelope(
                tenant, left, f"<m-conc-{index}-l@desk>", addresses[0], instant(base, 1),
                in_reply_to=root_message, references=[root_message],
            ),
            run.envelope(
                tenant, right, f"<m-conc-{index}-r@desk>", addresses[0], instant(base, 2),
                in_reply_to=root_message, references=[root_message],
            ),
        )
        run.expect_response_multiset("R8", [left, right])
        run.expect_partition("R8", [left, right])
        run.expect_read("R8", tenant, left)

    # ------------------------------------------------------------------ R9
    # Replies with no reference chain, handed over before the delivery they
    # reply to: one child, a chain of two, and a child whose parent never comes.
    tenant = TENANTS[1]
    base = EPOCH_BASE + 23000 * HOUR_MS
    _, addresses = REQUESTERS[4]
    late_parent_message = "<m-late-parent@desk>"
    late_child = run.post(
        tenant, run.transport("late-child"), "<m-late-child@desk>", addresses[0],
        instant(base, 5), in_reply_to=late_parent_message,
    )
    run.expect_response("R9", late_child)
    late_parent = run.post(
        tenant, run.transport("late-parent"), late_parent_message, addresses[0], instant(base, 0)
    )
    # The parent is an ordinary opener and its label is R3's; what R9 is about is
    # that the child waited and then landed on the parent's ticket.
    run.expect_partition("R9", [late_parent, late_child])
    run.expect_read("R9", tenant, late_parent)

    tenant = TENANTS[3]
    base = EPOCH_BASE + 23500 * HOUR_MS
    _, addresses = REQUESTERS[5]
    chain_root_message = "<m-chain-root@desk>"
    chain_mid_message = "<m-chain-mid@desk>"
    chain_leaf = run.post(
        tenant, run.transport("chain-leaf"), "<m-chain-leaf@desk>", addresses[0],
        instant(base, 9), in_reply_to=chain_mid_message,
    )
    chain_mid = run.post(
        tenant, run.transport("chain-mid"), chain_mid_message, addresses[0],
        instant(base, 5), in_reply_to=chain_root_message,
    )
    chain_root = run.post(
        tenant, run.transport("chain-root"), chain_root_message, addresses[0], instant(base, 0)
    )
    for transport in (chain_leaf, chain_mid):
        run.expect_response("R9", transport)
    run.expect_partition("R9", [chain_root, chain_mid, chain_leaf])
    run.expect_read("R9", tenant, chain_root)

    tenant = TENANTS[4]
    base = EPOCH_BASE + 24000 * HOUR_MS
    _, addresses = REQUESTERS[3]
    orphan = run.post(
        tenant, run.transport("orphan"), "<m-orphan@desk>", addresses[0],
        instant(base, 0), in_reply_to="<m-never-arrives@desk>",
    )
    run.expect_response("R9", orphan)

    # ----------------------------------------------------------------- R11
    # Retroactive merging. Every scenario here turns on a delivery that names
    # identifiers belonging to more than one conversation, which is the assertion
    # that they were one conversation before it arrived.
    #
    # R11 is judged on where deliveries ended up and on what the tickets say
    # about themselves, and is silent about the outcome word: a merge is not a
    # sixth outcome, and asserting the word here would take the append label away
    # from R4, which is the rule it belongs to.

    # Two chains that share an identifier no earlier delivery had put in common.
    tenant = TENANTS[0]
    base = EPOCH_BASE + 40000 * HOUR_MS
    _, addresses = REQUESTERS[1]
    left_root = "<m-link-left-root@desk>"
    right_root = "<m-link-right-root@desk>"
    shared_mid = "<m-link-shared-mid@desk>"
    link_a = run.post(
        tenant, run.transport("link-a"), "<m-link-a@desk>", addresses[0],
        instant(base, 0), in_reply_to=shared_mid, references=[left_root, shared_mid],
    )
    link_b = run.post(
        tenant, run.transport("link-b"), "<m-link-b@desk>", addresses[0],
        instant(base, 1), in_reply_to=shared_mid, references=[left_root],
    )
    link_c = run.post(
        tenant, run.transport("link-c"), "<m-link-c@desk>", addresses[0],
        instant(base, 2), in_reply_to=right_root, references=[right_root],
    )
    link_d = run.post(
        tenant, run.transport("link-d"), "<m-link-d@desk>", addresses[0],
        instant(base, 3), in_reply_to=right_root, references=[right_root, shared_mid],
    )
    run.expect_partition("R11", [link_a, link_b, link_c, link_d])
    run.expect_response_ticket("R11", link_d)
    # The survivor first, then the ticket that was folded away: the read lands on
    # whichever ticket the service last named for that delivery, so reading the
    # absorbed one has to happen before the redelivery below moves the name on.
    run.expect_read("R11", tenant, link_a)
    run.expect_read("R11", tenant, link_c)
    # And the redelivery of a delivery that has moved: it is answered with the
    # ticket it is on now, which is not the one it was first answered with.
    run.repost(link_c)
    run.expect_response_ticket("R11", link_c, occurrence=1)

    # A merge lengthens the conversation's history, so the close the window is
    # measured against can be a close the conversation did not have before. The
    # ticket that opened first is not the one holding the most recent close.
    #
    # Both tickets here closed shortly after they opened, so anchoring on the
    # close and anchoring on the ticket's own creation agree: this scenario tests
    # which close is the anchor, and R14 tests that the anchor is a close at all.
    tenant = TENANTS[1]
    base = EPOCH_BASE + 41000 * HOUR_MS
    _, addresses = REQUESTERS[4]
    early_root = "<m-mrg-early-root@desk>"
    late_root = "<m-mrg-late-root@desk>"
    merge_early = run.post(
        tenant, run.transport("mrg-early"), early_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, merge_early, instant(base, 5))
    merge_late = run.post(
        tenant, run.transport("mrg-late"), late_root, addresses[0], instant(base, 690)
    )
    run.close(tenant, merge_late, instant(base, 700))
    merge_reply = run.post(
        tenant, run.transport("mrg-reply"), "<m-mrg-reply@desk>", addresses[0],
        instant(base, 800), in_reply_to=late_root, references=[early_root, late_root],
    )
    run.expect_partition("R11", [merge_early, merge_late, merge_reply])
    run.expect_response_ticket("R11", merge_reply)
    run.expect_read("R11", tenant, merge_late)
    run.expect_read("R11", tenant, merge_early)

    # Three conversations at once, so the survivor is the earliest of three
    # rather than the earlier of two.
    tenant = TENANTS[2]
    base = EPOCH_BASE + 42000 * HOUR_MS
    _, addresses = REQUESTERS[6]
    three_roots = [f"<m-mrg3-{letter}-root@desk>" for letter in ("a", "b", "c")]
    three_openers = [
        run.post(
            tenant, run.transport(f"mrg3-{letter}"), root, addresses[0], instant(base, offset)
        )
        for offset, (letter, root) in enumerate(zip(("a", "b", "c"), three_roots))
    ]
    three_link = run.post(
        tenant, run.transport("mrg3-link"), "<m-mrg3-link@desk>", addresses[0],
        instant(base, 3), in_reply_to=three_roots[2], references=three_roots,
    )
    run.expect_partition("R11", three_openers + [three_link])
    run.expect_response_ticket("R11", three_link)
    for opener in three_openers:
        run.expect_read("R11", tenant, opener)

    # A merge where only one side has an open ticket. Nothing is reconciled --
    # there is only one open ticket between them -- so the delivery joins it,
    # and the closed ticket keeps its deliveries and was merged into nothing.
    # The plausible shortcut is "the earlier ticket wins and the later one is
    # folded into it", which here folds an open ticket into a closed one.
    tenant = TENANTS[3]
    base = EPOCH_BASE + 43000 * HOUR_MS
    _, addresses = REQUESTERS[0]
    shut_root = "<m-mrg-shut-root@desk>"
    live_root = "<m-mrg-live-root@desk>"
    mrg_shut = run.post(
        tenant, run.transport("mrg-shut"), shut_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, mrg_shut, instant(base, 2))
    mrg_live = run.post(
        tenant, run.transport("mrg-live"), live_root, addresses[0], instant(base, 10)
    )
    mrg_join = run.post(
        tenant, run.transport("mrg-join"), "<m-mrg-join@desk>", addresses[0],
        instant(base, 20), in_reply_to=live_root, references=[shut_root, live_root],
    )
    run.expect_partition("R11", [mrg_shut, mrg_live, mrg_join])
    run.expect_response_ticket("R11", mrg_join)
    run.expect_read("R11", tenant, mrg_shut)
    run.expect_read("R11", tenant, mrg_live)
    # And the delivery that brought them together, handed over again.
    run.repost(mrg_join)
    run.expect_response("R1", mrg_join, occurrence=1)

    # A merge between a conversation that has already had two tickets and one
    # that has had one. Which conversation is the older is settled by the
    # earliest ticket either of them holds, closed ones included; which *ticket*
    # survives is settled among the open ones only. Here those point opposite
    # ways: the older conversation's open ticket is the younger of the two, so
    # the ticket that survives belongs to the conversation that did not.
    tenant = TENANTS[4]
    base = EPOCH_BASE + 44000 * HOUR_MS
    _, addresses = REQUESTERS[2]
    succ_root = "<m-mrg-succ-root@desk>"
    side_root = "<m-mrg-side-root@desk>"
    succ_open = run.post(
        tenant, run.transport("mrg-succ"), succ_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, succ_open, instant(base, 1))
    side_open = run.post(
        tenant, run.transport("mrg-side"), side_root, addresses[0], instant(base, 100)
    )
    succ_next = run.post(
        tenant, run.transport("mrg-succ2"), "<m-mrg-succ-r@desk>", addresses[0],
        instant(base, 900), in_reply_to=succ_root, references=[succ_root],
    )
    run.expect_response("R6", succ_next)
    mrg_bridge = run.post(
        tenant, run.transport("mrg-bridge"), "<m-mrg-bridge@desk>", addresses[0],
        instant(base, 1000), in_reply_to=side_root, references=[succ_root, side_root],
    )
    run.expect_partition("R11", [succ_open, side_open, succ_next, mrg_bridge])
    run.expect_response_ticket("R11", mrg_bridge)
    run.expect_read("R11", tenant, succ_open)
    run.expect_read("R11", tenant, succ_next)
    run.expect_read("R11", tenant, side_open)

    # A merge brought about by a delivery that was itself waiting. It was held
    # for a parent that had not arrived; by the time it arrived, another
    # delivery had claimed the held delivery's own message identifier for a
    # different conversation. Releasing it makes those two conversations one.
    tenant = TENANTS[0]
    base = EPOCH_BASE + 45000 * HOUR_MS
    _, addresses = REQUESTERS[3]
    held_root = "<m-mrg-held-root@desk>"
    absent_root = "<m-mrg-absent-root@desk>"
    held_message = "<m-mrg-held-child@desk>"
    held_open = run.post(
        tenant, run.transport("mrg-hopen"), held_root, addresses[0], instant(base, 0)
    )
    held_child = run.post(
        tenant, run.transport("mrg-hchild"), held_message, addresses[0],
        instant(base, 9), in_reply_to=absent_root,
    )
    run.expect_response("R9", held_child)
    held_claim = run.post(
        tenant, run.transport("mrg-hclaim"), "<m-mrg-hclaim@desk>", addresses[0],
        instant(base, 6), in_reply_to=held_root, references=[held_root, held_message],
    )
    held_parent = run.post(
        tenant, run.transport("mrg-hparent"), absent_root, addresses[0], instant(base, 8)
    )
    run.expect_partition(
        "R11", [held_open, held_claim, held_parent, held_child]
    )
    run.expect_read("R11", tenant, held_open)
    run.expect_read("R11", tenant, held_parent)
    # Handed over again, a delivery that was never answered with a ticket of its
    # own is still on one now.
    run.repost(held_child)
    run.expect_response("R1", held_child, occurrence=1)

    # A merge where neither side is open and the delivery falls outside the
    # window of the merged history's most recent close. The new ticket
    # continues that close's ticket, which belongs to the conversation that did
    # not survive.
    tenant = TENANTS[1]
    base = EPOCH_BASE + 46000 * HOUR_MS
    _, addresses = REQUESTERS[5]
    cold_first_root = "<m-mrg-cold-a-root@desk>"
    cold_second_root = "<m-mrg-cold-b-root@desk>"
    cold_first = run.post(
        tenant, run.transport("mrg-colda"), cold_first_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, cold_first, instant(base, 1))
    cold_second = run.post(
        tenant, run.transport("mrg-coldb"), cold_second_root, addresses[0], instant(base, 200)
    )
    run.close(tenant, cold_second, instant(base, 210))
    cold_revive = run.post(
        tenant, run.transport("mrg-coldr"), "<m-mrg-cold-r@desk>", addresses[0],
        instant(base, 1000), in_reply_to=cold_second_root,
        references=[cold_first_root, cold_second_root],
    )
    run.expect_partition("R11", [cold_first, cold_second, cold_revive])
    run.expect_read("R11", tenant, cold_first)
    run.expect_read("R11", tenant, cold_second)
    run.expect_read(
        "R11", tenant, cold_revive,
        fields=["ticket", "status", "prior", "envelopes_set"],
    )

    # Three conversations again, but one of them is closed. The conversation
    # that opened first is the closed one, and the ticket that survives is the
    # earlier of the two open ones -- which is neither the first conversation's
    # nor the one the delivery named.
    tenant = TENANTS[2]
    base = EPOCH_BASE + 47000 * HOUR_MS
    _, addresses = REQUESTERS[1]
    mixed_roots = [f"<m-mrg-mix-{letter}-root@desk>" for letter in ("a", "b", "c")]
    mixed_shut = run.post(
        tenant, run.transport("mrg-mixa"), mixed_roots[0], addresses[0], instant(base, 0)
    )
    run.close(tenant, mixed_shut, instant(base, 1))
    mixed_late = run.post(
        tenant, run.transport("mrg-mixb"), mixed_roots[1], addresses[0], instant(base, 5)
    )
    mixed_early = run.post(
        tenant, run.transport("mrg-mixc"), mixed_roots[2], addresses[0], instant(base, 2)
    )
    mixed_link = run.post(
        tenant, run.transport("mrg-mixl"), "<m-mrg-mix-link@desk>", addresses[0],
        instant(base, 30), in_reply_to=mixed_roots[2], references=mixed_roots,
    )
    run.expect_partition("R11", [mixed_shut, mixed_late, mixed_early, mixed_link])
    run.expect_response_ticket("R11", mixed_link)
    for opener in (mixed_shut, mixed_late, mixed_early):
        run.expect_read("R11", tenant, opener)

    # ------------------------------------------------------------ R9, wider
    # A chain five deep, handed over leaf first. Every link waits on the one
    # above it and the whole chain is released by one delivery.
    tenant = TENANTS[0]
    base = EPOCH_BASE + 48000 * HOUR_MS
    _, addresses = REQUESTERS[6]
    deep = [f"<m-deep-{step}@desk>" for step in range(5)]
    deep_posts: list[str] = []
    for step in range(4, 0, -1):
        deep_posts.append(
            run.post(
                tenant, run.transport(f"deep{step}"), deep[step], addresses[0],
                instant(base, step * 2), in_reply_to=deep[step - 1],
            )
        )
    deep_root = run.post(
        tenant, run.transport("deep0"), deep[0], addresses[0], instant(base, 0)
    )
    for transport in deep_posts:
        run.expect_response("R9", transport)
    run.expect_partition("R9", deep_posts + [deep_root])
    run.expect_read("R9", tenant, deep_root)

    # Two children of one absent parent and a grandchild of one of them, all
    # released by the same delivery. They are three separate waits, not a
    # queue drained in the order it was filled.
    tenant = TENANTS[2]
    base = EPOCH_BASE + 48500 * HOUR_MS
    _, addresses = REQUESTERS[4]
    fan_parent_message = "<m-fan-parent@desk>"
    fan_first_message = "<m-fan-first@desk>"
    fan_first = run.post(
        tenant, run.transport("fan-a"), fan_first_message, addresses[0],
        instant(base, 10), in_reply_to=fan_parent_message,
    )
    fan_second = run.post(
        tenant, run.transport("fan-b"), "<m-fan-second@desk>", addresses[0],
        instant(base, 12), in_reply_to=fan_parent_message,
    )
    fan_grand = run.post(
        tenant, run.transport("fan-c"), "<m-fan-grand@desk>", addresses[0],
        instant(base, 14), in_reply_to=fan_first_message,
    )
    fan_parent = run.post(
        tenant, run.transport("fan-p"), fan_parent_message, addresses[0], instant(base, 0)
    )
    for transport in (fan_first, fan_second, fan_grand):
        run.expect_response("R9", transport)
    run.expect_partition("R9", [fan_parent, fan_first, fan_second, fan_grand])
    run.expect_read("R9", tenant, fan_parent)

    # A delivery whose parent exists, but at another desk. It waits for ever:
    # nothing said at one desk releases anything at another.
    tenant_a, tenant_b = TENANTS[1], TENANTS[3]
    base = EPOCH_BASE + 49000 * HOUR_MS
    _, addresses = REQUESTERS[0]
    across_message = "<m-across-parent@desk>"
    across_child = run.post(
        tenant_a, run.transport("across-c"), "<m-across-child@desk>", addresses[0],
        instant(base, 5), in_reply_to=across_message,
    )
    across_parent = run.post(
        tenant_b, run.transport("across-p"), across_message, addresses[0], instant(base, 0)
    )
    run.expect_response("R9", across_child)
    run.expect_partition("R2", [across_child, across_parent])
    run.expect_read("R2", tenant_b, across_parent)

    # ------------------------------------------------------ R5, R14, wider
    # A reply at the instant of the close, and one a long way inside the window.
    for index, hours_after_close in enumerate([0, 300, 700]):
        tenant = TENANTS[(index + 1) % len(TENANTS)]
        base = EPOCH_BASE + (50000 + index * 1500) * HOUR_MS
        _, addresses = REQUESTERS[index % len(REQUESTERS)]
        root_message = f"<m-reop-edge-{index}-root@desk>"
        opener = run.post(
            tenant, run.transport(f"reopedge{index}"), root_message, addresses[0],
            instant(base, 0),
        )
        run.close(tenant, opener, instant(base, 0.25))
        reply = run.post(
            tenant, run.transport(f"reopedge{index}r"), f"<m-reop-edge-{index}-r@desk>",
            addresses[0], instant(base, 0.25 + hours_after_close),
            in_reply_to=root_message, references=[root_message],
        )
        run.expect_response("R5", reply)
        run.expect_partition("R5", [opener, reply])
        run.expect_read("R5", tenant, opener)

    # An open ticket has no window. This one was brought back and left open, and
    # the next reply arrives years after the close it was brought back from: it
    # joins the open ticket, because the window is a question about a ticket
    # that is sitting in a close and this one is not.
    tenant = TENANTS[0]
    base = EPOCH_BASE + 55000 * HOUR_MS
    _, addresses = REQUESTERS[2]
    stale_root = "<m-stale-root@desk>"
    stale_open = run.post(
        tenant, run.transport("stale-a"), stale_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, stale_open, instant(base, 2))
    stale_back = run.post(
        tenant, run.transport("stale-b"), "<m-stale-back@desk>", addresses[0],
        instant(base, 100), in_reply_to=stale_root, references=[stale_root],
    )
    stale_much_later = run.post(
        tenant, run.transport("stale-c"), "<m-stale-late@desk>", addresses[0],
        instant(base, 9000), in_reply_to=stale_root, references=[stale_root],
    )
    run.expect_response("R14", stale_much_later)
    run.expect_partition("R14", [stale_open, stale_back, stale_much_later])
    run.expect_read("R14", tenant, stale_open)

    # Closed, brought back, closed again, brought back again: four closes deep,
    # each named through the delivery that landed on the ticket last.
    tenant = TENANTS[2]
    base = EPOCH_BASE + 57000 * HOUR_MS
    _, addresses = REQUESTERS[5]
    cycle_root = "<m-cycle-root@desk>"
    cycle_open = run.post(
        tenant, run.transport("cycle-a"), cycle_root, addresses[0], instant(base, 0)
    )
    cycle_members = [cycle_open]
    handle = cycle_open
    at = 0.0
    for step in range(4):
        at += 1
        run.close(tenant, handle, instant(base, at))
        at += 500
        handle = run.post(
            tenant, run.transport(f"cycle-r{step}"), f"<m-cycle-r{step}@desk>",
            addresses[0], instant(base, at),
            in_reply_to=cycle_root, references=[cycle_root],
        )
        cycle_members.append(handle)
        run.expect_response("R5", handle)
    run.expect_partition("R5", cycle_members)
    run.expect_read("R5", tenant, cycle_open)

    # A conversation that has run past the window and started a second ticket,
    # and then closes and reopens *that* one. The window belongs to the ticket
    # the conversation is on now, not to the one it started with.
    tenant = TENANTS[3]
    base = EPOCH_BASE + 59000 * HOUR_MS
    _, addresses = REQUESTERS[3]
    second_root = "<m-second-root@desk>"
    second_open = run.post(
        tenant, run.transport("second-a"), second_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, second_open, instant(base, 1))
    second_new = run.post(
        tenant, run.transport("second-b"), "<m-second-b@desk>", addresses[0],
        instant(base, 900), in_reply_to=second_root, references=[second_root],
    )
    run.expect_response("R6", second_new)
    run.close(tenant, second_new, instant(base, 910))
    second_back = run.post(
        tenant, run.transport("second-c"), "<m-second-c@desk>", addresses[0],
        instant(base, 1000), in_reply_to=second_root, references=[second_root],
    )
    run.expect_response("R5", second_back)
    run.expect_partition("R6", [second_open, second_new, second_back])
    run.expect_read("R6", tenant, second_open)
    run.expect_read("R6", tenant, second_new)

    # Three tickets in succession, each recording the one before it.
    tenant = TENANTS[4]
    base = EPOCH_BASE + 61000 * HOUR_MS
    _, addresses = REQUESTERS[6]
    chain_succ_root = "<m-succ-chain-root@desk>"
    succ_handles = [
        run.post(
            tenant, run.transport("succ-a"), chain_succ_root, addresses[0], instant(base, 0)
        )
    ]
    at = 0.0
    for step in range(2):
        at += 1
        run.close(tenant, succ_handles[-1], instant(base, at))
        at += 900
        succ_handles.append(
            run.post(
                tenant, run.transport(f"succ-r{step}"), f"<m-succ-chain-r{step}@desk>",
                addresses[0], instant(base, at),
                in_reply_to=chain_succ_root, references=[chain_succ_root],
            )
        )
        run.expect_response("R6", succ_handles[-1])
    run.expect_partition("R6", succ_handles)
    for handle in succ_handles:
        run.expect_read("R6", tenant, handle)

    # ------------------------------------------------------------ R7, wider
    # An address the desk's alias table does not know. It resolves to no
    # requester at all, which is not the same as resolving to any of them.
    tenant = TENANTS[1]
    base = EPOCH_BASE + 62000 * HOUR_MS
    stranger_root = "<m-stranger-root@desk>"
    stranger = run.post(
        tenant, run.transport("stranger-a"), stranger_root,
        "unknown.caller@nowhere.example", instant(base, 0),
    )
    stranger_reply = run.post(
        tenant, run.transport("stranger-b"), "<m-stranger-r@desk>",
        "unknown.caller@nowhere.example", instant(base, 3),
        in_reply_to=stranger_root, references=[stranger_root],
    )
    run.expect_partition("R7", [stranger, stranger_reply])
    run.expect_read("R7", tenant, stranger)

    # The remaining requesters, each writing in from every address they hold, so
    # the alias table is exercised end to end rather than in samples.
    for index, requester_index in enumerate([1, 3, 5, 6]):
        tenant = TENANTS[(index + 2) % len(TENANTS)]
        base = EPOCH_BASE + (63000 + index * 400) * HOUR_MS
        _, addresses = REQUESTERS[requester_index]
        alias_root = f"<m-alias-more-{index}-root@desk>"
        first = run.post(
            tenant, run.transport(f"aliasx{index}a"), alias_root,
            addresses[-1], instant(base, 0),
        )
        members = [first]
        for step, address in enumerate(addresses):
            members.append(
                run.post(
                    tenant, run.transport(f"aliasx{index}r{step}"),
                    f"<m-alias-more-{index}-r{step}@desk>", address,
                    instant(base, 2 + step),
                    in_reply_to=alias_root, references=[alias_root],
                )
            )
        run.expect_partition("R7", members)
        run.expect_read("R7", tenant, first)

    # ------------------------------------------------------------ R1, wider
    # A redelivery of a delivery whose ticket has since closed. It is answered
    # with that ticket and changes nothing: a redelivery is not a reply, and
    # answering it by reopening would bring a closed ticket back on no new
    # information at all.
    tenant = TENANTS[4]
    base = EPOCH_BASE + 65000 * HOUR_MS
    _, addresses = REQUESTERS[1]
    shutdup_root = "<m-shutdup-root@desk>"
    shutdup = run.post(
        tenant, run.transport("shutdup-a"), shutdup_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, shutdup, instant(base, 5))
    run.repost(shutdup)
    run.expect_response("R1", shutdup, occurrence=1)
    run.expect_read(
        "R1", tenant, shutdup, fields=["ticket", "status", "envelopes_set"]
    )

    # A redelivery of a delivery that sits on a ticket the conversation has
    # since moved on from. It is answered with the ticket that delivery is on,
    # which is the old one -- not the conversation's current ticket.
    tenant = TENANTS[0]
    base = EPOCH_BASE + 66000 * HOUR_MS
    _, addresses = REQUESTERS[4]
    moved_root = "<m-moved-root@desk>"
    moved_first = run.post(
        tenant, run.transport("moved-a"), moved_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, moved_first, instant(base, 1))
    moved_next = run.post(
        tenant, run.transport("moved-b"), "<m-moved-b@desk>", addresses[0],
        instant(base, 900), in_reply_to=moved_root, references=[moved_root],
    )
    run.repost(moved_first)
    run.expect_response("R1", moved_first, occurrence=1)
    run.expect_partition("R1", [moved_first, moved_next])
    run.expect_read("R1", tenant, moved_first)
    run.expect_read("R1", tenant, moved_next)

    # Both halves of a concurrent pair, handed over again afterwards.
    tenant = TENANTS[3]
    base = EPOCH_BASE + 67000 * HOUR_MS
    _, addresses = REQUESTERS[2]
    twin_root = "<m-twin-root@desk>"
    twin_left = run.transport("twin-l")
    twin_right = run.transport("twin-r")
    run.pair(
        run.envelope(
            tenant, twin_left, "<m-twin-l@desk>", addresses[0], instant(base, 1),
            in_reply_to=twin_root, references=[twin_root],
        ),
        run.envelope(
            tenant, twin_right, "<m-twin-r@desk>", addresses[0], instant(base, 2),
            in_reply_to=twin_root, references=[twin_root],
        ),
    )
    run.repost(twin_left)
    run.repost(twin_right)
    run.expect_response("R1", twin_left, occurrence=1)
    run.expect_response("R1", twin_right, occurrence=1)
    run.expect_partition("R8", [twin_left, twin_right])

    # ----------------------------------------------------------------- R15
    # The process is stopped and started again in the middle of the run.
    # Everything either side of it is ordinary traffic, and the answers do not
    # change: what a restart takes away is whatever was only ever in memory.

    # A conversation that continues across a restart.
    tenant = TENANTS[0]
    base = EPOCH_BASE + 70000 * HOUR_MS
    _, addresses = REQUESTERS[0]
    boot_root = "<m-boot-root@desk>"
    boot_open = run.post(
        tenant, run.transport("boot-a"), boot_root, addresses[0], instant(base, 0)
    )
    # Held for a parent that has not arrived, and still held when the process
    # goes away: a table of waiting deliveries kept in memory does not survive.
    boot_absent = "<m-boot-absent@desk>"
    boot_child = run.post(
        tenant, run.transport("boot-c"), "<m-boot-child@desk>", addresses[0],
        instant(base, 12), in_reply_to=boot_absent,
    )
    run.expect_response("R15", boot_child)
    # A ticket closed before the restart, replied to after it, inside the
    # window: the close and its instant have to have been written down.
    shutter_root = "<m-boot-shut-root@desk>"
    boot_shut = run.post(
        tenant, run.transport("boot-s"), shutter_root, addresses[0], instant(base, 1)
    )
    run.close(tenant, boot_shut, instant(base, 3))

    run.restart()

    boot_reply = run.post(
        tenant, run.transport("boot-b"), "<m-boot-b@desk>", addresses[0],
        instant(base, 20), in_reply_to=boot_root, references=[boot_root],
    )
    run.expect_response("R15", boot_reply)
    boot_parent = run.post(
        tenant, run.transport("boot-p"), boot_absent, addresses[0], instant(base, 10)
    )
    boot_shut_reply = run.post(
        tenant, run.transport("boot-sr"), "<m-boot-shut-r@desk>", addresses[0],
        instant(base, 400), in_reply_to=shutter_root, references=[shutter_root],
    )
    run.expect_response("R15", boot_shut_reply)
    run.repost(boot_open)
    run.expect_response("R15", boot_open, occurrence=1)
    run.expect_partition("R15", [boot_open, boot_reply])
    run.expect_partition("R15", [boot_parent, boot_child])
    run.expect_partition("R15", [boot_shut, boot_shut_reply])
    run.expect_read("R15", tenant, boot_open)
    run.expect_read("R15", tenant, boot_parent)
    run.expect_read("R15", tenant, boot_shut)

    # A merge, then a restart, then a redelivery of a delivery the merge moved.
    # Where a delivery is has to be a fact in the store, not a map that was
    # rebuilt from the last thing the process happened to see.
    tenant = TENANTS[2]
    base = EPOCH_BASE + 71000 * HOUR_MS
    _, addresses = REQUESTERS[5]
    boot_left_root = "<m-bootmrg-left@desk>"
    boot_right_root = "<m-bootmrg-right@desk>"
    boot_left = run.post(
        tenant, run.transport("bootm-l"), boot_left_root, addresses[0], instant(base, 0)
    )
    boot_right = run.post(
        tenant, run.transport("bootm-r"), boot_right_root, addresses[0], instant(base, 5)
    )
    boot_merge = run.post(
        tenant, run.transport("bootm-m"), "<m-bootmrg-link@desk>", addresses[0],
        instant(base, 10), in_reply_to=boot_right_root,
        references=[boot_left_root, boot_right_root],
    )

    run.restart()

    run.repost(boot_right)
    run.expect_response("R15", boot_right, occurrence=1)
    boot_after = run.post(
        tenant, run.transport("bootm-a"), "<m-bootmrg-after@desk>", addresses[0],
        instant(base, 30), in_reply_to=boot_right_root, references=[boot_right_root],
    )
    run.expect_response("R15", boot_after)
    run.expect_partition("R15", [boot_left, boot_right, boot_merge, boot_after])
    run.expect_read("R15", tenant, boot_left)

    # A restart between a delivery and the redelivery of it, at a desk whose
    # conversation is one delivery long. The delivery is not a new one just
    # because nothing in the process remembers it.
    tenant = TENANTS[4]
    base = EPOCH_BASE + 72000 * HOUR_MS
    _, addresses = REQUESTERS[3]
    solo_boot = run.post(
        tenant, run.transport("bootsolo"), "<m-bootsolo@desk>", addresses[0],
        instant(base, 0),
    )

    run.restart()

    run.repost(solo_boot)
    run.expect_response("R15", solo_boot, occurrence=1)
    run.expect_partition("R15", [solo_boot])
    run.expect_read("R15", tenant, solo_boot)

    # ----------------------------------------------------------------- R12
    # Handed over newest first, so a ticket that lists its deliveries in the
    # order they were handed over lists them backwards.
    tenant = TENANTS[2]
    base = EPOCH_BASE + 25000 * HOUR_MS
    _, addresses = REQUESTERS[1]
    order_root_message = "<m-order-root@desk>"
    order_root = run.post(
        tenant, run.transport("order-root"), order_root_message, addresses[0], instant(base, 0)
    )
    for step in reversed(range(1, 6)):
        run.post(
            tenant, run.transport(f"order-r{step}"), f"<m-order-r{step}@desk>",
            addresses[0], instant(base, step * 7),
            in_reply_to=order_root_message, references=[order_root_message],
        )
    run.expect_read("R12", tenant, order_root)

    # A merged ticket lists everything it now holds in the order it arrived,
    # interleaved -- not one conversation's deliveries and then the other's.
    tenant = TENANTS[4]
    base = EPOCH_BASE + 68000 * HOUR_MS
    _, addresses = REQUESTERS[0]
    weave_left_root = "<m-weave-left@desk>"
    weave_right_root = "<m-weave-right@desk>"
    weave_left = run.post(
        tenant, run.transport("weave-l"), weave_left_root, addresses[0], instant(base, 0)
    )
    weave_right = run.post(
        tenant, run.transport("weave-r"), weave_right_root, addresses[0], instant(base, 10)
    )
    for step, (root, when) in enumerate(
        [
            (weave_left_root, 20),
            (weave_right_root, 30),
            (weave_left_root, 40),
            (weave_right_root, 50),
        ]
    ):
        run.post(
            tenant, run.transport(f"weave-{step}"), f"<m-weave-{step}@desk>",
            addresses[0], instant(base, when), in_reply_to=root, references=[root],
        )
    run.post(
        tenant, run.transport("weave-link"), "<m-weave-link@desk>", addresses[0],
        instant(base, 60), in_reply_to=weave_right_root,
        references=[weave_left_root, weave_right_root],
    )
    run.expect_read("R12", tenant, weave_left)
    run.expect_read("R11", tenant, weave_right)

    # A delivery that waited is listed where it arrived, not where it was
    # placed. This one arrived before the delivery it replies to and was handed
    # over after it, so placement order and arrival order disagree.
    tenant = TENANTS[1]
    base = EPOCH_BASE + 69000 * HOUR_MS
    _, addresses = REQUESTERS[6]
    waited_parent_message = "<m-waited-parent@desk>"
    waited_child = run.post(
        tenant, run.transport("waited-c"), "<m-waited-child@desk>", addresses[0],
        instant(base, 20), in_reply_to=waited_parent_message,
    )
    waited_parent = run.post(
        tenant, run.transport("waited-p"), waited_parent_message, addresses[0],
        instant(base, 50),
    )
    run.post(
        tenant, run.transport("waited-e"), "<m-waited-extra@desk>", addresses[0],
        instant(base, 35), in_reply_to=waited_parent_message,
        references=[waited_parent_message],
    )
    run.expect_partition("R9", [waited_parent, waited_child])
    run.expect_read("R12", tenant, waited_parent)

    # ----------------------------------------------------------------- R28
    # Five deliveries inside one second. `received_at` is an instant and the
    # fraction is part of it; the width of the fraction is the gateway's business
    # and `src/intake/parseEnvelope.ts` accepts one digit through six.
    #
    # Handed over in an order that separates every reading at once. True instant
    # order is no-fraction, .000001, .000002, .000009, .5 -- so the ticket must
    # list frac-b, frac-c, frac-a, frac-e, frac-d. Each wrong reading gives a
    # different order and none of them gives that one:
    #
    #   as text        c, a, e, d, b    `Z` (0x5A) sorts after `.` (0x2E) under
    #                                   BINARY collation, so the whole-second
    #                                   delivery lands last instead of first
    #   as a Date      a, b, c, e, d    everything below a millisecond is dropped,
    #                                   so the first four tie and a stable sort
    #                                   falls back to the order they were written
    #   fraction as    b, c, a, d, e    ".5" read as five microseconds rather than
    #   an integer                      five hundred thousand: d and e swap
    #   as handed over a, b, c, d, e
    #
    # frac-e exists only to separate the third of those. With .000001, .000002 and
    # .5 alone, left-padding the fraction happens to give the right order (0, 1, 2,
    # 5), so that reading would have scored as correct on a scenario built to catch
    # it. A nine in the last place is what makes the padding direction observable.
    tenant = TENANTS[3]
    base = EPOCH_BASE + 71000 * HOUR_MS
    _, addresses = REQUESTERS[2]
    frac_root_message = "<m-frac-root@desk>"
    frac_a = run.post(
        tenant, run.transport("frac-a"), frac_root_message, addresses[0],
        instant(base, 0, "000002"),
    )
    for tag, message, fraction in [
        ("frac-b", "<m-frac-b@desk>", None),
        ("frac-c", "<m-frac-c@desk>", "000001"),
        ("frac-d", "<m-frac-d@desk>", "5"),
        ("frac-e", "<m-frac-e@desk>", "000009"),
    ]:
        run.post(
            tenant, run.transport(tag), message, addresses[0],
            instant(base, 0, fraction),
            in_reply_to=frac_root_message, references=[frac_root_message],
        )
    run.expect_read("R28", tenant, frac_a)

    # ----------------------------------------------------------------- R13
    # A token shared by two conversations, a token that changes inside one, and
    # a token on a delivery that reopens a closed ticket.
    tenant = TENANTS[0]
    base = EPOCH_BASE + 26000 * HOUR_MS
    _, addresses = REQUESTERS[6]
    decoy_left_message = "<m-decoy-left@desk>"
    decoy_right_message = "<m-decoy-right@desk>"
    decoy_left = run.post(
        tenant, run.transport("decoy-l"), decoy_left_message, addresses[0],
        instant(base, 0), subject_token="TKT-88120",
    )
    decoy_right = run.post(
        tenant, run.transport("decoy-r"), decoy_right_message, addresses[0],
        instant(base, 1), subject_token="TKT-88120",
    )
    decoy_left_reply = run.post(
        tenant, run.transport("decoy-lr"), "<m-decoy-left-r@desk>", addresses[0],
        instant(base, 2), in_reply_to=decoy_left_message, references=[decoy_left_message],
        subject_token="TKT-99001",
    )
    decoy_right_reply = run.post(
        tenant, run.transport("decoy-rr"), "<m-decoy-right-r@desk>", addresses[0],
        instant(base, 3), in_reply_to=decoy_right_message, references=[decoy_right_message],
        subject_token="TKT-88120",
    )
    for transport in (decoy_left, decoy_right, decoy_left_reply, decoy_right_reply):
        run.expect_response("R13", transport)
    run.expect_partition(
        "R13", [decoy_left, decoy_right, decoy_left_reply, decoy_right_reply]
    )
    run.expect_read("R13", tenant, decoy_left)
    run.expect_read("R13", tenant, decoy_right)

    tenant = TENANTS[1]
    base = EPOCH_BASE + 27000 * HOUR_MS
    _, addresses = REQUESTERS[2]
    decoy_closed_message = "<m-decoy-closed@desk>"
    decoy_closed = run.post(
        tenant, run.transport("decoy-c"), decoy_closed_message, addresses[0],
        instant(base, 0), subject_token="TKT-70001",
    )
    run.close(tenant, decoy_closed, instant(base, 0.25))
    decoy_closed_reply = run.post(
        tenant, run.transport("decoy-cr"), "<m-decoy-closed-r@desk>", addresses[0],
        instant(base, 50), in_reply_to=decoy_closed_message,
        references=[decoy_closed_message], subject_token="TKT-70999",
    )
    run.expect_response("R13", decoy_closed_reply)
    run.expect_partition("R13", [decoy_closed, decoy_closed_reply])
    run.expect_read("R13", tenant, decoy_closed)

    # ------------------------------------------------------------ R16, R17
    # The deliveries the desk itself sent. They arrive on the same route, are
    # threaded by the same headers and are recorded on the same tickets as
    # everything else; what they are not is the customer getting back in touch.
    #
    # Judged on where the delivery landed and what state that left the ticket
    # in. The only label assertion is negative -- it was not answered 'reopened'
    # or 'created' -- because what an outbound delivery is *called* is a choice
    # among words that all mean "recorded, nothing moved", and grading the choice
    # would be grading vocabulary. R16 and R17 have separate scenarios, so a
    # submission that gets the lifecycle right and the requester wrong fails one
    # rule rather than both.

    # The desk answering a case it had closed, inside the window and well
    # outside it. Either way the delivery goes on that ticket and the close it
    # is sitting in is untouched.
    for index, hours_after_close in enumerate([90, 900]):
        tenant = TENANTS[index % len(TENANTS)]
        base = EPOCH_BASE + (75000 + index * 2000) * HOUR_MS
        _, addresses = REQUESTERS[index % len(REQUESTERS)]
        root_message = f"<m-desk-shut-{index}-root@desk>"
        opener = run.post(
            tenant, run.transport(f"dskshut{index}"), root_message, addresses[0],
            instant(base, 0),
        )
        run.close(tenant, opener, instant(base, 1))
        answer = run.post(
            tenant, run.transport(f"dskshut{index}a"),
            f"<m-desk-shut-{index}-a@desk>",
            DESK_ADDRESSES[index % len(DESK_ADDRESSES)],
            instant(base, 1 + hours_after_close),
            in_reply_to=root_message, references=[root_message], to=addresses[0],
        )
        run.expect_action_not("R16", answer, ["reopened", "created"])
        run.expect_partition("R16", [opener, answer])
        run.expect_read("R16", tenant, opener)
        # The case is still the customer's after the desk has written on it.
        run.expect_read("R17", tenant, opener)

    # The desk's follow-up does not restart the clock. It arrives well inside
    # the window and the customer's reply after it arrives outside, measured
    # from the close it was always going to be measured from -- so that reply
    # opens a successor. A submission whose follow-up reopened the ticket has an
    # open ticket here and appends to it instead.
    tenant = TENANTS[2]
    base = EPOCH_BASE + 79000 * HOUR_MS
    _, addresses = REQUESTERS[2]
    clock_root = "<m-desk-clock-root@desk>"
    clock_open = run.post(
        tenant, run.transport("dskclock"), clock_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, clock_open, instant(base, 1))
    clock_answer = run.post(
        tenant, run.transport("dskclock-a"), "<m-desk-clock-a@desk>", DESK_ADDRESS,
        instant(base, 701), in_reply_to=clock_root, references=[clock_root],
        to=addresses[0],
    )
    clock_back = run.post(
        tenant, run.transport("dskclock-b"), "<m-desk-clock-b@desk>", addresses[0],
        instant(base, 901), in_reply_to=clock_root, references=[clock_root],
    )
    run.expect_action_not("R16", clock_answer, ["reopened", "created"])
    run.expect_partition("R16", [clock_open, clock_answer, clock_back])
    run.expect_read("R16", tenant, clock_open)
    run.expect_read("R16", tenant, clock_back)

    # And the same shape inside the window: the customer's reply after the
    # desk's follow-up brings back the ticket the follow-up is recorded on.
    tenant = TENANTS[3]
    base = EPOCH_BASE + 81000 * HOUR_MS
    _, addresses = REQUESTERS[5]
    warm_root = "<m-desk-warm-root@desk>"
    warm_open = run.post(
        tenant, run.transport("dskwarm"), warm_root, addresses[0], instant(base, 0)
    )
    run.close(tenant, warm_open, instant(base, 1))
    warm_answer = run.post(
        tenant, run.transport("dskwarm-a"), "<m-desk-warm-a@desk>",
        DESK_ADDRESSES[1], instant(base, 101),
        in_reply_to=warm_root, references=[warm_root], to=addresses[0],
    )
    warm_back = run.post(
        tenant, run.transport("dskwarm-b"), "<m-desk-warm-b@desk>", addresses[0],
        instant(base, 201), in_reply_to=warm_root, references=[warm_root],
    )
    run.expect_action_not("R16", warm_answer, ["reopened", "created"])
    run.expect_partition("R16", [warm_open, warm_answer, warm_back])
    run.expect_read("R16", tenant, warm_open)

    # A case the desk opened by writing first. There is no ticket and no
    # lifecycle to leave alone, so the delivery opens one -- with nobody's name
    # on it, because the address it came from is the desk's own. The customer's
    # answer settles whose case it is.
    tenant = TENANTS[4]
    base = EPOCH_BASE + 83000 * HOUR_MS
    _, addresses = REQUESTERS[3]
    reach_root = "<m-desk-reach-root@desk>"
    reach = run.post(
        tenant, run.transport("dskreach"), reach_root, DESK_ADDRESS,
        instant(base, 0), to=addresses[0],
    )
    run.expect_not_duplicate("R16", reach)
    reach_reply = run.post(
        tenant, run.transport("dskreach-r"), "<m-desk-reach-r@desk>", addresses[0],
        instant(base, 5), in_reply_to=reach_root, references=[reach_root],
    )
    run.expect_partition("R16", [reach, reach_reply])
    run.expect_read("R16", tenant, reach)
    run.expect_read("R17", tenant, reach)

    # Outreach nobody answered. The desk wrote twice, the second time replying
    # to its own first delivery, and the case is still nobody's: the address
    # both came from resolves to an identity, and it is not a requester.
    tenant = TENANTS[1]
    base = EPOCH_BASE + 84000 * HOUR_MS
    quiet_root = "<m-desk-quiet-root@desk>"
    quiet = run.post(
        tenant, run.transport("dskquiet"), quiet_root, DESK_ADDRESS,
        instant(base, 0), to=REQUESTERS[2][1][0],
    )
    quiet_again = run.post(
        tenant, run.transport("dskquiet-b"), "<m-desk-quiet-b@desk>",
        DESK_ADDRESSES[1], instant(base, 48),
        in_reply_to=quiet_root, references=[quiet_root], to=REQUESTERS[2][1][0],
    )
    run.expect_partition("R16", [quiet, quiet_again])
    run.expect_read("R17", tenant, quiet)

    # A case that already has a requester. The desk answering it does not take
    # it over, and neither does a colleague of the requester joining the thread
    # from an address of their own.
    tenant = TENANTS[0]
    base = EPOCH_BASE + 85000 * HOUR_MS
    _, addresses = REQUESTERS[4]
    _, other_addresses = REQUESTERS[6]
    keep_root = "<m-desk-keep-root@desk>"
    keep_open = run.post(
        tenant, run.transport("dskkeep"), keep_root, addresses[0], instant(base, 0)
    )
    keep_answer = run.post(
        tenant, run.transport("dskkeep-a"), "<m-desk-keep-a@desk>",
        DESK_ADDRESSES[1], instant(base, 2),
        in_reply_to=keep_root, references=[keep_root], to=addresses[0],
    )
    keep_third = run.post(
        tenant, run.transport("dskkeep-c"), "<m-desk-keep-c@desk>",
        other_addresses[0], instant(base, 4),
        in_reply_to=keep_root, references=[keep_root],
    )
    run.expect_partition("R16", [keep_open, keep_answer, keep_third])
    run.expect_read("R17", tenant, keep_open)

    # The desk's own delivery bringing two conversations together: an agent
    # answered both threads at once, which is the same assertion as anybody
    # else's delivery naming both. Direction settles what a delivery does to a
    # ticket's lifecycle, not which conversation it belongs to.
    tenant = TENANTS[1]
    base = EPOCH_BASE + 87000 * HOUR_MS
    _, addresses = REQUESTERS[1]
    dlink_left = "<m-desk-link-left@desk>"
    dlink_right = "<m-desk-link-right@desk>"
    dlink_a = run.post(
        tenant, run.transport("dsklink-a"), dlink_left, addresses[0], instant(base, 0)
    )
    dlink_b = run.post(
        tenant, run.transport("dsklink-b"), dlink_right, addresses[0], instant(base, 5)
    )
    dlink_join = run.post(
        tenant, run.transport("dsklink-j"), "<m-desk-link-j@desk>", DESK_ADDRESS,
        instant(base, 10), in_reply_to=dlink_right,
        references=[dlink_left, dlink_right], to=addresses[0],
    )
    run.expect_partition("R16", [dlink_a, dlink_b, dlink_join])
    run.expect_read("R16", tenant, dlink_a)
    run.expect_read("R16", tenant, dlink_b)

    # And the hardest corner of the two put together: the desk's delivery links
    # two conversations that are both closed, and it is outside both windows.
    # There is nothing to reconcile -- neither has an open ticket -- and nothing
    # for the delivery to move: it is recorded on the merged history's most
    # recent close, which stays closed.
    tenant = TENANTS[2]
    base = EPOCH_BASE + 89000 * HOUR_MS
    _, addresses = REQUESTERS[0]
    dcold_first_root = "<m-desk-cold-a@desk>"
    dcold_second_root = "<m-desk-cold-b@desk>"
    dcold_first = run.post(
        tenant, run.transport("dskcold-a"), dcold_first_root, addresses[0],
        instant(base, 0),
    )
    run.close(tenant, dcold_first, instant(base, 1))
    dcold_second = run.post(
        tenant, run.transport("dskcold-b"), dcold_second_root, addresses[0],
        instant(base, 200),
    )
    run.close(tenant, dcold_second, instant(base, 210))
    dcold_join = run.post(
        tenant, run.transport("dskcold-j"), "<m-desk-cold-j@desk>",
        DESK_ADDRESSES[1], instant(base, 1000), in_reply_to=dcold_second_root,
        references=[dcold_first_root, dcold_second_root], to=addresses[0],
    )
    run.expect_action_not("R16", dcold_join, ["reopened", "created"])
    run.expect_partition("R16", [dcold_first, dcold_second, dcold_join])
    run.expect_read("R16", tenant, dcold_first)
    run.expect_read("R16", tenant, dcold_second)
    run.expect_read("R17", tenant, dcold_second)

    # ------------------------------------------------------ R18, R19, R20
    # The plainest outbound case, on a desk whose gateway does not reflect: the
    # console composes, nothing has gone out, a tick sends it, and a second tick
    # does not send it again.
    #
    # The desk is TENANTS[1], which does not reflect, so the reply reaches the
    # ticket only because the tick put it there. A submission that records an
    # outgoing message when the gateway hands it back has an empty ticket here
    # and there is nothing else that would tell it so.
    tenant = TENANTS[1]
    base = EPOCH_BASE + 20000 * HOUR_MS
    _, addresses = REQUESTERS[0]
    plain_root_message = "<m-out-plain-root@desk>"
    plain_desk_message = "<m-out-plain-desk@desk>"
    plain_root = run.post(
        tenant, run.transport("out-plain"), plain_root_message, addresses[0],
        instant(base, 0),
    )
    plain_key = run.reply_key("plain")
    taken = run.compose(
        tenant, plain_root, plain_key, plain_desk_message,
        in_reply_to=plain_root_message, composed_at=instant(base, 2),
        to=[addresses[0]],
    )
    run.expect_reply_state("R18", taken)
    # Handed over again before anything has been sent. One reply, still queued.
    taken_again = run.compose(
        tenant, plain_root, plain_key, plain_desk_message,
        in_reply_to=plain_root_message, composed_at=instant(base, 2),
        to=[addresses[0]],
    )
    run.expect_reply_state("R18", taken_again)
    run.expect_outbox("R19", tenant, messages=[plain_desk_message])
    run.expect_spool("R19", tenant, absent=[plain_desk_message])
    run.expect_read("R19", tenant, plain_root, snapshot=True)

    run.tick(tenant)
    run.expect_spool("R20", tenant, messages=[plain_desk_message])
    run.expect_outbox("R20", tenant, messages=[plain_desk_message])
    run.expect_read("R20", tenant, plain_root, snapshot=True)
    # The console retrying after the reply has gone out. Not re-queued, not sent
    # again, and answered with where it actually is.
    taken_after = run.compose(
        tenant, plain_root, plain_key, plain_desk_message,
        in_reply_to=plain_root_message, composed_at=instant(base, 2),
        to=[addresses[0]],
    )
    run.expect_reply_state("R18", taken_after)
    run.tick(tenant)
    run.expect_spool("R20", tenant, messages=[plain_desk_message])
    run.expect_read("R20", tenant, plain_root, snapshot=True)

    # ------------------------------------------------------------------ R25
    # The customer answers what the desk sent, naming it and nothing else. That
    # only lands on the same ticket if the outgoing message's identifier is in
    # the conversation -- which it is not, if the reply was written into the
    # store as a row rather than put through the routing decision.
    answer_back = run.post(
        tenant, run.transport("out-plain-back"), "<m-out-plain-back@desk>",
        addresses[1], instant(base, 30),
        in_reply_to=plain_desk_message,
    )
    # The two customer deliveries only. The outgoing message is between them and
    # the read below checks it is there, by `message_id`: which transport
    # identifier a submission records its own send under is a choice nothing
    # visible settles, and a partition naming the reply's key would be grading
    # that choice.
    run.expect_partition("R25", [plain_root, answer_back])
    run.expect_read("R25", tenant, plain_root, snapshot=True)

    # ------------------------------------------------------------ R23, R20
    # The same shape on a desk whose gateway reflects, which is the asymmetry:
    # here the message comes back over intake a moment after it went out, with a
    # transport identifier the gateway has just generated and the identifier the
    # console chose. It is one message and the ticket holds it once.
    #
    # A submission that recognises it by the transport identifier records it
    # twice. One that recognises it by the message identifier alone breaks R1,
    # which has a delivery of somebody else's carrying an identifier already
    # seen, and that has to stay a delivery.
    tenant = TENANTS[0]
    base = EPOCH_BASE + 20400 * HOUR_MS
    _, addresses = REQUESTERS[1]
    echo_root_message = "<m-out-echo-root@desk>"
    echo_desk_message = "<m-out-echo-desk@desk>"
    echo_root = run.post(
        tenant, run.transport("out-echo"), echo_root_message, addresses[0],
        instant(base, 0),
    )
    echo_key = run.reply_key("echo")
    run.compose(
        tenant, echo_root, echo_key, echo_desk_message,
        in_reply_to=echo_root_message, composed_at=instant(base, 3),
        to=[addresses[0]],
    )
    run.tick(tenant)
    run.expect_spool("R20", tenant, messages=[echo_desk_message])
    # The gateway hands it back.
    echoed = run.post(
        tenant, run.transport("out-echo-back"), echo_desk_message,
        DESK_ADDRESS, instant(base, 3),
        in_reply_to=echo_root_message, to=addresses[0],
    )
    run.expect_read("R23", tenant, echo_root, snapshot=True)
    run.expect_outbox("R23", tenant, messages=[echo_desk_message])
    # And hands it back again, because the gateway is the gateway.
    run.repost(echoed)
    run.expect_read("R23", tenant, echo_root, snapshot=True)

    # The other side of R23: the desk that does not reflect holds its own send
    # once as well, and nothing arrives to make it so.
    quiet_tenant = TENANTS[4]
    quiet_base = EPOCH_BASE + 20600 * HOUR_MS
    _, quiet_addresses = REQUESTERS[6]
    quiet_root_message = "<m-out-quiet-root@desk>"
    quiet_desk_message = "<m-out-quiet-desk@desk>"
    quiet_root = run.post(
        quiet_tenant, run.transport("out-quiet"), quiet_root_message,
        quiet_addresses[0], instant(quiet_base, 0),
    )
    quiet_key = run.reply_key("quiet")
    run.compose(
        quiet_tenant, quiet_root, quiet_key, quiet_desk_message,
        in_reply_to=quiet_root_message, composed_at=instant(quiet_base, 4),
        to=[quiet_addresses[0]],
    )
    run.tick(quiet_tenant)
    run.expect_read("R23", quiet_tenant, quiet_root, snapshot=True)
    run.expect_spool("R23", quiet_tenant, messages=[quiet_desk_message])

    # ------------------------------------------------------------------ R21
    # The transport losing its answer, both ways round, on two different desks
    # so that neither is the first thing a solver reads.
    #
    # `unknown-landed`: the message reached the wire and the answer was lost. The
    # reply is still queued, and offering it again gets `already_sent`, so the
    # settled state is sent with one message on the wire.
    tenant = TENANTS[2]
    base = EPOCH_BASE + 20800 * HOUR_MS
    _, addresses = REQUESTERS[2]
    landed_root_message = "<m-out-landed-root@desk>"
    landed_desk_message = "<m-out-landed-desk@desk>"
    run.flake(landed_desk_message, "unknown-landed")
    landed_root = run.post(
        tenant, run.transport("out-landed"), landed_root_message, addresses[0],
        instant(base, 0),
    )
    landed_key = run.reply_key("landed")
    run.compose(
        tenant, landed_root, landed_key, landed_desk_message,
        in_reply_to=landed_root_message, composed_at=instant(base, 5),
        to=[addresses[0]],
    )
    run.tick(tenant)
    # The tick has been and the transport said nothing. The message is on the
    # wire -- nothing the service can see says so -- and the reply is not sent.
    run.expect_outbox("R21", tenant, messages=[landed_desk_message])
    run.expect_read("R21", tenant, landed_root, snapshot=True)
    # This desk's gateway reflects, and the message did reach the wire, so it
    # comes back now -- while the reply that produced it is still queued and
    # nothing of it is on the ticket. The two facts a submission can key its echo
    # check on disagree here for the only time in the run: the outbox knows this
    # message, and the store has no envelope for it. It is still the desk's own
    # send, and after the next tick the ticket holds it once either way -- placed
    # by the tick, or placed by the reflection and left alone by the tick.
    #
    # The answer to this delivery is not graded: which ticket a reflection names
    # while its reply is unplaced is not settled by anything visible. What is
    # graded is the state afterwards.
    run.post(
        tenant, run.transport("out-landed-back"), landed_desk_message,
        DESK_ADDRESS, instant(base, 6),
        in_reply_to=landed_root_message, to=addresses[0],
    )
    # And the process goes away in between, so a reply held in memory is gone.
    run.restart()
    run.tick(tenant)
    run.expect_outbox("R21", tenant, messages=[landed_desk_message])
    run.expect_spool("R21", tenant, messages=[landed_desk_message])
    run.expect_read("R21", tenant, landed_root, snapshot=True)

    # `unknown-lost`: the answer was lost and the message never reached the wire.
    # Identical from the service's side and the opposite underneath, which is why
    # neither "assume it went" nor "assume it did not" is an answer.
    tenant = TENANTS[3]
    base = EPOCH_BASE + 21000 * HOUR_MS
    _, addresses = REQUESTERS[4]
    lost_root_message = "<m-out-lost-root@desk>"
    lost_desk_message = "<m-out-lost-desk@desk>"
    run.flake(lost_desk_message, "unknown-lost")
    lost_root = run.post(
        tenant, run.transport("out-lost"), lost_root_message, addresses[0],
        instant(base, 0),
    )
    lost_key = run.reply_key("lost")
    run.compose(
        tenant, lost_root, lost_key, lost_desk_message,
        in_reply_to=lost_root_message, composed_at=instant(base, 6),
        to=[addresses[0]],
    )
    run.tick(tenant)
    run.expect_outbox("R21", tenant, messages=[lost_desk_message])
    run.expect_spool("R21", tenant, absent=[lost_desk_message])
    run.expect_read("R21", tenant, lost_root, snapshot=True)
    run.restart()
    run.tick(tenant)
    run.expect_outbox("R21", tenant, messages=[lost_desk_message])
    run.expect_spool("R21", tenant, messages=[lost_desk_message])
    run.expect_read("R21", tenant, lost_root, snapshot=True)

    # ------------------------------------------------------------------ R22
    # A reply the transport will not carry. Refused is not queued and it is not
    # sent: nothing is on the wire, nothing is on the ticket, and the tick after
    # it does not try again.
    tenant = TENANTS[4]
    base = EPOCH_BASE + 21200 * HOUR_MS
    _, addresses = REQUESTERS[5]
    refused_root_message = "<m-out-refused-root@desk>"
    refused_desk_message = "<m-out-refused-desk@desk>"
    refused_root = run.post(
        tenant, run.transport("out-refused"), refused_root_message, addresses[0],
        instant(base, 0),
    )
    refused_key = run.reply_key("refused")
    run.compose(
        tenant, refused_root, refused_key, refused_desk_message,
        in_reply_to=refused_root_message, composed_at=instant(base, 2),
        to=[],
    )
    run.tick(tenant)
    run.expect_outbox("R22", tenant, messages=[refused_desk_message])
    run.expect_spool("R22", tenant, absent=[refused_desk_message])
    run.expect_read("R22", tenant, refused_root, snapshot=True)
    run.tick(tenant)
    run.expect_outbox("R22", tenant, messages=[refused_desk_message])
    run.expect_spool("R22", tenant, absent=[refused_desk_message])

    # ------------------------------------------------------------------ R18
    # A reply composed on a ticket that is not this desk's. The identifier is
    # real -- the run watched the ticket being created under another desk -- so
    # the refusal is about whose ticket it is and not about whether it exists.
    denied = run.compose(
        TENANTS[1], refused_root, run.reply_key("cross"), "<m-out-cross@desk>",
        in_reply_to=refused_root_message, composed_at=instant(base, 3),
        to=[addresses[0]], ticket_tenant=TENANTS[4],
    )
    run.expect_reply_denied("R18", denied)
    absent = run.compose(
        TENANTS[1], refused_root, run.reply_key("absent"), "<m-out-absent@desk>",
        in_reply_to=refused_root_message, composed_at=instant(base, 4),
        to=[addresses[0]], ticket_id="tkt-does-not-exist-0000",
    )
    run.expect_reply_denied("R18", absent)

    # ------------------------------------------------------------ R16, R20
    # A reply composed on a ticket that is closed. The desk following up does not
    # bring the case back, and the reply going out does not either -- it is a
    # delivery the desk sent, and R16 is about what those do to a lifecycle. This
    # is the one place the two halves meet, and it is the case a submission that
    # routes outgoing messages through its own path rather than the routing
    # decision gets wrong without noticing.
    tenant = TENANTS[1]
    base = EPOCH_BASE + 21400 * HOUR_MS
    _, addresses = REQUESTERS[3]
    shut_root_message = "<m-out-shut-root@desk>"
    shut_desk_message = "<m-out-shut-desk@desk>"
    shut_root = run.post(
        tenant, run.transport("out-shut"), shut_root_message, addresses[0],
        instant(base, 0),
    )
    run.close(tenant, shut_root, instant(base, 10))
    shut_key = run.reply_key("shut")
    run.compose(
        tenant, shut_root, shut_key, shut_desk_message,
        in_reply_to=shut_root_message, composed_at=instant(base, 20),
        to=[addresses[0]],
    )
    run.tick(tenant)
    run.expect_read("R16", tenant, shut_root, snapshot=True)
    run.expect_spool("R20", tenant, messages=[shut_desk_message])
    # And the customer coming back inside the window of the original close, which
    # the desk's own message did not move.
    shut_back = run.post(
        tenant, run.transport("out-shut-back"), "<m-out-shut-back@desk>",
        addresses[0], instant(base, 40),
        in_reply_to=shut_desk_message,
    )
    run.expect_response("R5", shut_back)
    run.expect_partition("R25", [shut_root, shut_back])

    # ------------------------------------------------------------------ R24
    # The history. Every desk's own message on a ticket that predates the outbox
    # is in the outbox as sent, every delivery that was sent *to* the desk is not
    # in it at all, and no tick offers any of them to the transport.
    #
    # Three desks, because the history is not uniform: one open ticket with two
    # outbound messages on a reflecting gateway, one closed ticket with one on a
    # gateway that does not reflect, and one ticket with nothing outbound at all.
    run.tick(TENANTS[0])
    run.expect_outbox(
        "R24",
        TENANTS[0],
        messages=["<m-lgc-a-desk1@old>", "<m-lgc-a-desk2@old>"],
        absent=["<m-lgc-a-root@old>"],
    )
    run.expect_spool(
        "R24",
        TENANTS[0],
        absent=["<m-lgc-a-desk1@old>", "<m-lgc-a-desk2@old>", "<m-lgc-a-root@old>"],
    )
    run.tick(TENANTS[3])
    run.expect_outbox(
        "R24",
        TENANTS[3],
        messages=["<m-lgc-b-desk@old>"],
        absent=["<m-lgc-b-root@old>"],
    )
    run.expect_spool(
        "R24", TENANTS[3], absent=["<m-lgc-b-desk@old>", "<m-lgc-b-root@old>"]
    )
    run.tick(TENANTS[2])
    run.expect_outbox(
        "R24",
        TENANTS[2],
        absent=["<m-lgc-c-root@old>", "<m-lgc-c-more@old>"],
    )
    run.expect_spool(
        "R24", TENANTS[2], absent=["<m-lgc-c-root@old>", "<m-lgc-c-more@old>"]
    )

    # ------------------------------------------------------------ R26, R27
    # The history, routed rather than merely moved. Nothing here is a convention
    # the rest of the run does not already use: a delivery continuing a
    # conversation joins the ticket that conversation is on (R4), a ticket keeps
    # the requester it has (R17), a ticket lists its deliveries in arrival order
    # (R12), and the window is measured from the close (R5, R6, R14). What is
    # different is where the answers are. A conversation the store already held
    # is described by rows in `tickets` and `envelopes` and by nothing else,
    # because that is all a desk arrives with, and a run that leaves those rows
    # where it found them has no thread for these deliveries to join.
    #
    # Replying to a message the *desk* sent, from a different customer than the
    # one whose case it is. A run that adopts loosely enough to miss either fact
    # answers with a ticket of its own, or hands the case to the newcomer.
    carry_on = run.post(
        TENANTS[0], run.transport("lgc-carry"), "<m-lgc-a-back@old>",
        "t.reiner@vantage.example", "2025-10-02T09:00:00Z",
        in_reply_to="<m-lgc-a-desk1@old>",
    )
    run.expect_response("R26", carry_on)
    run.expect_read("R26", TENANTS[0], carry_on)

    # The same question on the desk whose historical ticket is inbound-only, so
    # that adopting a conversation is not something a submission can do only
    # where the outbox backfill has already touched the ticket.
    carry_quiet = run.post(
        TENANTS[2], run.transport("lgc-quiet"), "<m-lgc-c-back@old>",
        "sun.park@lattice-eu.example", "2025-10-04T15:00:00Z",
        references=["<m-lgc-c-root@old>"],
    )
    run.expect_response("R26", carry_quiet)
    run.expect_read("R26", TENANTS[2], carry_quiet)

    # A close the store already held, on both sides of the window. The instant
    # is on the ticket row and nowhere else, so a run with no anchor either
    # never reopens or always does.
    back_inside = run.post(
        TENANTS[3], run.transport("lgc-warm"), "<m-lgc-b-back@old>",
        "y.demir@harborline.example", "2025-09-01T08:00:00Z",
        references=["<m-lgc-b-root@old>"],
    )
    run.expect_response("R27", back_inside)
    run.expect_read("R27", TENANTS[3], back_inside)

    back_outside = run.post(
        TENANTS[4], run.transport("lgc-cold"), "<m-lgc-d-back@old>",
        "nell.brannigan@ridgeway.example", "2025-09-25T10:00:00Z",
        references=["<m-lgc-d-root@old>"],
    )
    run.expect_response("R27", back_outside)
    run.expect_read("R27", TENANTS[4], back_outside)

    # ------------------------------------------------------------------ R20
    # A tick with no desk named drains every desk. Two replies on two desks, one
    # call, and the wire has both.
    both_a, both_b = TENANTS[0], TENANTS[3]
    base = EPOCH_BASE + 21600 * HOUR_MS
    _, addresses = REQUESTERS[0]
    all_a_root_message = "<m-out-all-a-root@desk>"
    all_a_desk_message = "<m-out-all-a-desk@desk>"
    all_b_root_message = "<m-out-all-b-root@desk>"
    all_b_desk_message = "<m-out-all-b-desk@desk>"
    all_a_root = run.post(
        both_a, run.transport("out-all-a"), all_a_root_message, addresses[0],
        instant(base, 0),
    )
    all_b_root = run.post(
        both_b, run.transport("out-all-b"), all_b_root_message, addresses[1],
        instant(base, 1),
    )
    run.compose(
        both_a, all_a_root, run.reply_key("all-a"), all_a_desk_message,
        in_reply_to=all_a_root_message, composed_at=instant(base, 2),
        to=[addresses[0]],
    )
    run.compose(
        both_b, all_b_root, run.reply_key("all-b"), all_b_desk_message,
        in_reply_to=all_b_root_message, composed_at=instant(base, 3),
        to=[addresses[1]],
    )
    run.tick()
    run.expect_spool("R20", both_a, messages=[all_a_desk_message])
    run.expect_spool("R20", both_b, messages=[all_b_desk_message])
    run.expect_read("R20", both_a, all_a_root, snapshot=True)
    run.expect_read("R20", both_b, all_b_root, snapshot=True)

    # ------------------------------------------------------------------ R20
    # Two ticks at once, on one desk, with two replies queued and the transport
    # answering both plainly. Whatever the two calls do about each other, each
    # message is on the wire once, on its ticket once, and its reply is sent.
    # A desk that offers a reply the other call is already holding, and records
    # what comes back, has these messages twice.
    tenant = TENANTS[3]
    base = EPOCH_BASE + 21800 * HOUR_MS
    _, addresses = REQUESTERS[1]
    twin_left_root_message = "<m-out-twin-left-root@desk>"
    twin_left_desk_message = "<m-out-twin-left-desk@desk>"
    twin_right_root_message = "<m-out-twin-right-root@desk>"
    twin_right_desk_message = "<m-out-twin-right-desk@desk>"
    twin_left_root = run.post(
        tenant, run.transport("out-twin-left"), twin_left_root_message, addresses[0],
        instant(base, 0),
    )
    twin_right_root = run.post(
        tenant, run.transport("out-twin-right"), twin_right_root_message, addresses[1],
        instant(base, 1),
    )
    run.compose(
        tenant, twin_left_root, run.reply_key("twin-left"), twin_left_desk_message,
        in_reply_to=twin_left_root_message, composed_at=instant(base, 2),
        to=[addresses[0]],
    )
    run.compose(
        tenant, twin_right_root, run.reply_key("twin-right"), twin_right_desk_message,
        in_reply_to=twin_right_root_message, composed_at=instant(base, 3),
        to=[addresses[1]],
    )
    run.tick_pair(tenant)
    run.expect_outbox(
        "R20", tenant, messages=[twin_left_desk_message, twin_right_desk_message]
    )
    run.expect_spool(
        "R20", tenant, messages=[twin_left_desk_message, twin_right_desk_message]
    )
    run.expect_read("R20", tenant, twin_left_root, snapshot=True)
    run.expect_read("R20", tenant, twin_right_root, snapshot=True)
    # And the customer answering one of them, so a double-recorded send shows up
    # in the grouping as well as in the count.
    twin_back = run.post(
        tenant, run.transport("out-twin-back"), "<m-out-twin-back@desk>",
        addresses[0], instant(base, 20),
        in_reply_to=twin_left_desk_message,
    )
    run.expect_partition("R20", [twin_left_root, twin_back])
    run.expect_read("R20", tenant, twin_left_root, snapshot=True)

    # ------------------------------------------------------------------ R10
    # The other half of the scoped read, now that there is a second thing to
    # read: this desk's outbox holds this desk's replies and not another desk's,
    # and the path says whose outbox it is the same way the ticket read does.
    run.expect_outbox(
        "R10",
        tenant,
        messages=[twin_left_desk_message],
        absent=[plain_desk_message, echo_desk_message, quiet_desk_message],
    )
    run.expect_outbox(
        "R10",
        TENANTS[1],
        messages=[plain_desk_message],
        absent=[twin_left_desk_message, echo_desk_message, quiet_desk_message],
    )

    # -------------------------------------------------------------- filler
    # Ordinary traffic, so the graded scenarios are not the only thing in the
    # store and a ticket lookup has to discriminate. Seeded, so the run is the
    # same every time it is built. `subject_token` is constant within a
    # conversation here: routing on it wrongly still groups this traffic
    # correctly, which keeps R13's scenarios the only place that rule bites.
    for index in range(70):
        tenant = TENANTS[run.random.randrange(len(TENANTS))]
        _, addresses = REQUESTERS[run.random.randrange(len(REQUESTERS))]
        base = EPOCH_BASE + (30000 + index * 60) * HOUR_MS
        token = (
            f"TKT-{40000 + index}" if run.random.random() < 0.4 else None
        )
        root_message = f"<m-fill-{index}-root@desk>"
        opener = run.post(
            tenant, run.transport(f"fill{index}"), root_message,
            addresses[run.random.randrange(len(addresses))], instant(base, 0),
            subject_token=token,
        )
        run.expect_response("R3", opener)
        members = [opener]
        for step in range(run.random.randrange(1, 5)):
            reply = run.post(
                tenant, run.transport(f"fill{index}r{step}"),
                f"<m-fill-{index}-r{step}@desk>",
                addresses[run.random.randrange(len(addresses))],
                instant(base, 1 + step * 2),
                in_reply_to=root_message, references=[root_message],
                subject_token=token,
            )
            members.append(reply)
            run.expect_response("R4", reply)
        # The desk answers some of them. On an open ticket that is an ordinary
        # append whichever way the delivery was going, so this is traffic and not
        # a scenario: it puts the desk's own deliveries throughout the run rather
        # than only where they are graded, and a submission that never looks at
        # direction still groups every one of them correctly.
        if run.random.random() < 0.35:
            members.append(
                run.post(
                    tenant, run.transport(f"fill{index}d"),
                    f"<m-fill-{index}-desk@desk>",
                    DESK_ADDRESSES[index % len(DESK_ADDRESSES)],
                    instant(base, 20),
                    in_reply_to=root_message, references=[root_message],
                    subject_token=token, to=addresses[0],
                )
            )
        run.expect_partition("R4", members)
        run.expect_read("R4", tenant, opener)

    posts = sum(
        1 if operation["op"] == "post" else (2 if operation["op"] == "pair" else 0)
        for operation in run.operations
    )
    checks = sum(len(rule["checks"]) for rule in run.rules.values())

    return {
        "seed": seed,
        "posts": posts,
        "checks": checks,
        "operations": run.operations,
        "identities": identities,
        "aliases": aliases,
        "desk_addresses": desk_addresses,
        "desk_gateways": [
            {"tenant_id": tenant, "reflects_own_sends": reflects}
            for tenant, reflects in DESK_GATEWAYS.items()
        ],
        "legacy_tickets": LEGACY_TICKETS,
        "legacy_envelopes": LEGACY_ENVELOPES,
        "handoff_instructions": run.instructions,
        "rules": run.rules,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=8)
    parser.add_argument("--out", default="verifier-data/run-spec.json")
    arguments = parser.parse_args()

    spec = build(arguments.seed)
    with open(arguments.out, "w", encoding="utf-8") as handle:
        json.dump(spec, handle, indent=1, sort_keys=False)
        handle.write("\n")
    print(
        f"{arguments.out}: {spec['posts']} deliveries, "
        f"{len(spec['operations'])} operations, {len(spec['rules'])} rules, "
        f"{spec['checks']} checks"
    )


if __name__ == "__main__":
    main()
