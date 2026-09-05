#!/usr/bin/env python3
"""Builds the recorded stretch the sandbox ships, and proves it cannot drift.

The workspace has no upstream sibling to read, so the recording does the
sibling's job: it is a stretch of two desks' tickets as intake produced them,
and most of the routing conventions are recoverable from it by comparing one
stored ticket with another.

Two commands, and the second is the point:

    python3 gen_recording.py --spec .local/recording-spec.json
    python3 gen_recording.py --spec .local/recording-spec.json \\
        --validate workspace/sandbox/recorded/tickets.json

`--spec` writes the deliveries and the reference data. The documents that ship
are produced by driving the *reference implementation* over that spec, so every
field -- including `conversation_id`, which is a hash the reference computes and
nothing here reimplements -- is what the shipped algorithm actually answers.

`--validate` then reads those documents back and checks them against
`verifier-data/model/intake_model.py`, the independent model the scorer grades
with. That is the guarantee that matters: the sandbox teaches what the holdout
tests, and if the two ever disagree this exits non-zero rather than shipping a
recording that contradicts the grader. A sandbox record that teaches the
opposite of what is graded punishes a solver for reading it, which is the worst
defect available.

Nothing here enters the image, and the reason is the Dockerfile rather than an
ignore file: every `COPY` in it names a path, and none of them names this one or
any other builder-side script at the context root. (This paragraph used to
credit an `environment/.dockerignore` that does not exist. The containment was
real, the reason given for it was not.)

## What is in the stretch, and what is deliberately not

One instance per case class a stored ticket can carry, and no repetitions: a
second example of a case the solver has already seen buys fluency, not
discoverability. The case classes a *snapshot* cannot carry -- a redelivery,
which by definition records nothing; a pair arriving together; a reply held for
a parent; a reopen, which clears `closed_at` and so leaves no trace; a restart
-- are routed through the prompt or through surviving code instead.

The desk's own deliveries are in here as four of those classes, because that is
where they are visible at all: the desk answering a live case, the desk opening
one by writing first, and the desk following up on a closed case both inside and
outside the window. What each of those did to the ticket is in the ticket, and
whose case the ticket is is in the same record.

There is no narration shipped beside the records. An earlier sandbox labelled
one fixture per graded rule and wrote the outcome and the reason next to it,
which is an answer key sitting next to the evidence.
"""

from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import sys
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent

HOUR_MS = 3_600_000
# 2025-09-01T00:00:00Z. The graded run sits in 2026 and shares no instant with
# this one, which is one of the axes on which sandbox and holdout are disjoint.
BASE_MS = 1756684800000

DESK_A = "tnt-2d7e4b10-c001"
DESK_B = "tnt-2d7e4b10-c002"
DESK_ADDRESS = "inbox@desk.internal"

# Reference data for the two recorded desks. Provisioned outside intake, which
# reads it and never writes it.
IDENTITIES: list[tuple[str, str, str]] = [
    (DESK_A, "idn-r-5501", "Wren Halloway"),
    (DESK_A, "idn-r-5502", "Emeka Nduka"),
    (DESK_A, "idn-r-5503", "Ilse Vogt"),
    # The desk's own staffed identity. It has an alias row like anybody else,
    # which is the point: the alias table answers "who is this address" and not
    # "whose case is this".
    (DESK_A, "idn-r-5504", "Fieldstone Desk"),
    (DESK_B, "idn-r-5511", "Wren Halloway"),
    (DESK_B, "idn-r-5512", "Marchmont Desk"),
]

ALIASES: list[tuple[str, str, str]] = [
    (DESK_A, "wren.halloway@fieldstone.example", "idn-r-5501"),
    (DESK_A, "w.halloway@fieldstone-mail.example", "idn-r-5501"),
    (DESK_A, "wren@halloway.example", "idn-r-5501"),
    (DESK_A, "emeka.nduka@brightwater.example", "idn-r-5502"),
    (DESK_A, "ilse.vogt@marchmont.example", "idn-r-5503"),
    (DESK_A, "i.vogt@marchmont.example", "idn-r-5503"),
    (DESK_A, DESK_ADDRESS, "idn-r-5504"),
    # The same address at the other desk is a different person. Addresses are
    # not identities and identities do not cross desks.
    (DESK_B, "wren.halloway@fieldstone.example", "idn-r-5511"),
    (DESK_B, DESK_ADDRESS, "idn-r-5512"),
]

# The desks' own addresses. Both desks answer from the address they receive at.
DESK_ADDRESSES: list[tuple[str, str]] = [
    (DESK_A, DESK_ADDRESS),
    (DESK_B, DESK_ADDRESS),
]

# How each recorded desk's transport is wired. One of each, on purpose: the
# recording is the only place a solver can see that both kinds exist and that
# they leave different traces, and a stretch where both desks were the same kind
# would teach that the column does not matter.
DESK_GATEWAYS: list[tuple[str, int]] = [
    (DESK_A, 1),
    (DESK_B, 0),
]


def instant(hours: float) -> str:
    """An ISO-8601 UTC instant, whole seconds, `hours` after the base."""
    total = BASE_MS + int(round(hours * HOUR_MS))
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

    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"


class Stretch:
    def __init__(self) -> None:
        self.operations: list[dict[str, Any]] = []
        self._transport = 0

    def post(
        self,
        tenant: str,
        hours: float,
        message: str,
        sender: str,
        references: list[str] | None = None,
        in_reply_to: str | None = None,
        transport: str | None = None,
        to: str | None = None,
    ) -> str:
        if transport is None:
            self._transport += 1
            transport = f"trn-r-{self._transport:04d}"
        self.operations.append(
            {
                "op": "post",
                "envelope": {
                    "transport_id": transport,
                    "tenant_id": tenant,
                    "message_id": message,
                    "from_address": sender,
                    "to_addresses": [to or DESK_ADDRESS],
                    "in_reply_to": in_reply_to,
                    "references": references or [],
                    "subject_token": None,
                    "received_at": instant(hours),
                },
            }
        )
        return transport

    def close(self, tenant: str, of: str, hours: float) -> None:
        self.operations.append(
            {"op": "close", "tenant_id": tenant, "of": of, "closed_at": instant(hours)}
        )

    def compose(
        self,
        tenant: str,
        of: str,
        reply_id: str,
        message: str,
        in_reply_to: str,
        hours: float,
        to: str | None,
    ) -> str:
        """The console composing a reply on the ticket holding `of`.

        `to` of None is a reply with no recipient, which the transport will not
        carry. It is in the stretch because a refused reply leaves a trace and
        there is nowhere else to see one.
        """
        self.operations.append(
            {
                "op": "reply",
                "tenant_id": tenant,
                "ticket_of": of,
                "reply": {
                    "reply_id": reply_id,
                    "message_id": message,
                    "from_address": DESK_ADDRESS,
                    "to_addresses": [] if to is None else [to],
                    "in_reply_to": in_reply_to,
                    "references": [],
                    "composed_at": instant(hours),
                },
            }
        )
        return reply_id

    def tick(self, tenant: str) -> None:
        self.operations.append({"op": "dispatch", "tenant_id": tenant})


# Addresses, spelled once.
WREN = "wren.halloway@fieldstone.example"
WREN_ALT = "w.halloway@fieldstone-mail.example"
WREN_ALT2 = "wren@halloway.example"
EMEKA = "emeka.nduka@brightwater.example"
ILSE = "ilse.vogt@marchmont.example"
ILSE_ALT = "i.vogt@marchmont.example"


def build() -> dict[str, Any]:
    """The recorded stretch: one instance of each case class a ticket can show."""
    s = Stretch()

    # -- a conversation that ran normally, from three of one person's addresses.
    a1_root = "<r-a1-1@fieldstone.example>"
    a1_second = "<r-a1-2@fieldstone-mail.example>"
    s.post(DESK_A, 0, a1_root, WREN)
    s.post(DESK_A, 3, a1_second, WREN_ALT, references=[a1_root], in_reply_to=a1_root)
    s.post(
        DESK_A,
        27,
        "<r-a1-3@halloway.example>",
        WREN_ALT2,
        references=[a1_root, a1_second],
        in_reply_to=a1_second,
    )

    # -- a conversation where one message identifier arrives on two deliveries.
    a2_root = "<r-a2-1@brightwater.example>"
    a2_reply = "<r-a2-2@brightwater.example>"
    s.post(DESK_A, 50, a2_root, EMEKA)
    s.post(DESK_A, 52, a2_reply, EMEKA, references=[a2_root], in_reply_to=a2_root)
    s.post(DESK_A, 55, a2_reply, EMEKA, references=[a2_root], in_reply_to=a2_root)

    # -- a conversation that outlived its ticket. 760 hours after the close.
    a3_root = "<r-a3-1@marchmont.example>"
    first = s.post(DESK_A, 100, a3_root, ILSE)
    s.close(DESK_A, first, 140)
    s.post(DESK_A, 900, "<r-a3-2@marchmont.example>", ILSE_ALT, references=[a3_root], in_reply_to=a3_root)

    # -- two conversations, each with an open ticket, turning out to be one.
    a4_root = "<r-a4-1@fieldstone.example>"
    a4_other = "<r-a4-9@brightwater.example>"
    s.post(DESK_A, 200, a4_root, WREN)
    s.post(DESK_A, 205, a4_other, EMEKA)
    s.post(DESK_A, 210, "<r-a4-2@fieldstone.example>", WREN, references=[a4_root], in_reply_to=a4_root)
    s.post(
        DESK_A,
        215,
        "<r-a4-link@fieldstone.example>",
        WREN,
        references=[a4_root, a4_other],
        in_reply_to=a4_other,
    )

    # -- two conversations turning out to be one when neither has an open
    #    ticket, and a reply long afterwards. The ticket that opened first is
    #    not the one that closed last here, and only one of them is the anchor.
    a5_root = "<r-a5-1@marchmont.example>"
    a5_other = "<r-a5-9@brightwater.example>"
    p = s.post(DESK_A, 300, a5_root, ILSE)
    q = s.post(DESK_A, 400, a5_other, EMEKA)
    s.close(DESK_A, q, 450)
    s.close(DESK_A, p, 500)
    s.post(
        DESK_A,
        1300,
        "<r-a5-link@marchmont.example>",
        ILSE,
        references=[a5_root, a5_other],
        in_reply_to=a5_other,
    )

    # -- the desk's own answer, in the middle of a live conversation. It came
    #    over the same gateway as the rest and the ticket holds it.
    a6_root = "<r-a6-1@brightwater.example>"
    a6_answer = "<r-a6-2@desk.internal>"
    s.post(DESK_A, 1400, a6_root, EMEKA)
    s.post(
        DESK_A, 1401, a6_answer, DESK_ADDRESS,
        references=[a6_root], in_reply_to=a6_root, to=EMEKA,
    )
    s.post(
        DESK_A, 1410, "<r-a6-3@brightwater.example>", EMEKA,
        references=[a6_root, a6_answer], in_reply_to=a6_answer,
    )

    # -- a case the desk opened by writing first, answered afterwards.
    a7_root = "<r-a7-1@desk.internal>"
    s.post(DESK_A, 1500, a7_root, DESK_ADDRESS, to=ILSE)
    s.post(
        DESK_A, 1520, "<r-a7-2@marchmont.example>", ILSE,
        references=[a7_root], in_reply_to=a7_root,
    )

    # -- a closed case the desk followed up on, ninety hours after the close.
    a8_root = "<r-a8-1@fieldstone.example>"
    a8 = s.post(DESK_A, 1600, a8_root, WREN)
    s.close(DESK_A, a8, 1610)
    s.post(
        DESK_A, 1700, "<r-a8-2@desk.internal>", DESK_ADDRESS,
        references=[a8_root], in_reply_to=a8_root, to=WREN,
    )

    # -- and one the desk followed up on seven hundred and ninety hours after
    #    the close.
    a9_root = "<r-a9-1@marchmont.example>"
    a9 = s.post(DESK_A, 1800, a9_root, ILSE)
    s.close(DESK_A, a9, 1810)
    s.post(
        DESK_A, 2600, "<r-a9-2@desk.internal>", DESK_ADDRESS,
        references=[a9_root], in_reply_to=a9_root, to=ILSE,
    )

    # -- two conversations turning out to be one, on the desk's own delivery:
    #    the agent replied to both threads at once, which is the assertion.
    a10_left = "<r-a10-left@brightwater.example>"
    a10_right = "<r-a10-right@fieldstone.example>"
    s.post(DESK_A, 1900, a10_left, EMEKA)
    s.post(DESK_A, 1905, a10_right, WREN)
    s.post(
        DESK_A, 1910, "<r-a10-link@desk.internal>", DESK_ADDRESS,
        references=[a10_left, a10_right], in_reply_to=a10_right, to=EMEKA,
    )

    # -- the console's own replies, which is the other half of the wire. One
    #    instance per state a reply can be in, and one of each kind of gateway.
    #
    #    a11: composed and sent, on the desk whose transport reflects. The
    #    message went out and then came back over intake with an identifier the
    #    gateway had just made up; the ticket holds it once and the identifier it
    #    holds it under is the console's. A customer's answer to it lands on the
    #    same ticket, which it only can if the outgoing message's identifier is
    #    in the conversation.
    a11_root = "<r-a11-1@fieldstone.example>"
    a11_out = "<r-a11-2@desk.internal>"
    a11 = s.post(DESK_A, 2700, a11_root, WREN)
    s.compose(DESK_A, a11, "rpl-r-0001", a11_out, a11_root, 2702, WREN)
    s.tick(DESK_A)
    s.post(
        DESK_A, 2702, a11_out, DESK_ADDRESS,
        transport="trn-g-0091", in_reply_to=a11_root, to=WREN,
    )
    s.post(
        DESK_A, 2710, "<r-a11-3@fieldstone.example>", WREN,
        in_reply_to=a11_out,
    )

    # a13: composed with nobody to send it to, and offered to the transport,
    # which would not take it. Nothing went out and the ticket holds nothing.
    a13_root = "<r-a13-1@marchmont.example>"
    a13 = s.post(DESK_A, 2900, a13_root, ILSE)
    s.compose(DESK_A, a13, "rpl-r-0003", "<r-a13-2@desk.internal>", a13_root, 2901, None)
    s.tick(DESK_A)

    # a14: a reply composed on a closed case and sent. The desk answering its
    # own closed ticket does not reopen it, and going out through the transport
    # does not either.
    a14_root = "<r-a14-1@fieldstone.example>"
    a14 = s.post(DESK_A, 3000, a14_root, WREN)
    s.close(DESK_A, a14, 3010)
    s.compose(
        DESK_A, a14, "rpl-r-0004", "<r-a14-2@desk.internal>", a14_root, 3020, WREN
    )
    s.tick(DESK_A)

    # -- the other desk, using the first desk's message identifiers and one of
    #    its addresses.
    s.post(DESK_B, 500, a1_root, WREN)
    s.post(DESK_B, 505, a1_second, WREN, references=[a1_root], in_reply_to=a1_root)

    # b3: the same send on the desk whose transport does not reflect. It is on
    # the ticket for the same reason -- the tick put it there -- and nothing
    # arrives afterwards. Comparing this ticket with a11's is the only way to see
    # that the reflection is not what records a send.
    b3_root = "<r-b3-1@fieldstone.example>"
    b3 = s.post(DESK_B, 2700, b3_root, WREN)
    s.compose(DESK_B, b3, "rpl-r-0005", "<r-b3-2@desk.internal>", b3_root, 2703, WREN)
    s.tick(DESK_B)

    # a12, last of all, because a tick drains a desk rather than a reply: this is
    # a reply the console has composed and no tick has been near. It is not on
    # the wire and it is not on its ticket either.
    a12_root = "<r-a12-1@brightwater.example>"
    a12 = s.post(DESK_A, 2800, a12_root, EMEKA)
    s.compose(DESK_A, a12, "rpl-r-0002", "<r-a12-2@desk.internal>", a12_root, 2801, EMEKA)

    return {
        "operations": s.operations,
        "identities": [
            {"tenant_id": tenant, "identity_id": identity, "display_name": name}
            for tenant, identity, name in IDENTITIES
        ],
        "aliases": [
            {"tenant_id": tenant, "address": address, "identity_id": identity}
            for tenant, address, identity in ALIASES
        ],
        "desk_addresses": [
            {"tenant_id": tenant, "address": address}
            for tenant, address in DESK_ADDRESSES
        ],
        "desk_gateways": [
            {"tenant_id": tenant, "reflects_own_sends": reflects}
            for tenant, reflects in DESK_GATEWAYS
        ],
    }


# --------------------------------------------------------------------------
# validation against the model the scorer grades with
# --------------------------------------------------------------------------


def validate_outbox(
    spec: dict[str, Any],
    recorded: list[dict[str, Any]],
    outbox: list[dict[str, Any]],
) -> list[str]:
    """The shipped outbox against the model, and against the recording itself.

    Two things are checked and they are checked differently.

    Every reply the console composed has a key the console chose, so the model
    knows it by name and its state is compared directly.

    Every other row is the migration's work: the desk's own messages that were
    on tickets before there was an outbox to hold them, which the backfill
    accounts for as sent. Those are compared against the recording rather than
    against the model -- the recording is where they exist -- and the check is
    the one the rule is about: a message the desk sent is there and marked sent,
    a message sent to the desk is not there at all.
    """
    sys.path.insert(0, str(HERE / "verifier-data" / "model"))
    from intake_model import evaluate  # noqa: PLC0415

    expected = evaluate(spec)
    replies: dict[str, dict[str, Any]] = expected["replies"]
    problems: list[str] = []

    by_key = {entry["reply_id"]: entry for entry in outbox}
    for reply_id, wanted in sorted(replies.items()):
        got = by_key.get(reply_id)
        if got is None:
            problems.append(f"the shipped outbox has no reply {reply_id}")
            continue
        if got.get("state") != wanted["state"]:
            problems.append(
                f"{reply_id}: shipped as {got.get('state')}, model says {wanted['state']}"
            )
        if got.get("message_id") != wanted["message_id"]:
            problems.append(
                f"{reply_id}: shipped message {got.get('message_id')}, "
                f"model says {wanted['message_id']}"
            )

    desk = {
        (entry["tenant_id"], entry["address"].strip().lower())
        for entry in spec.get("desk_addresses") or []
    }
    listed = {entry.get("message_id") for entry in outbox}
    states = {entry.get("message_id"): entry.get("state") for entry in outbox}
    for ticket in recorded:
        for envelope in ticket["envelopes"]:
            sent_by_desk = (
                ticket["tenant_id"],
                envelope["from_address"].strip().lower(),
            ) in desk
            message = envelope["message_id"]
            if sent_by_desk:
                if message not in listed:
                    problems.append(
                        f"{message} is on {ticket['ticket_id'][:8]} from the desk's own "
                        "address and is not in the shipped outbox"
                    )
                elif states[message] != "sent":
                    problems.append(
                        f"{message} went out and the shipped outbox calls it "
                        f"{states[message]}"
                    )
            elif message in listed:
                problems.append(
                    f"{message} was sent to the desk and is in the shipped outbox"
                )
    return problems


def validate(spec: dict[str, Any], recorded: list[dict[str, Any]]) -> list[str]:
    """Every graded fact about the shipped documents, per the scorer's model.

    The model names tickets by label and the recording names them by the
    identifier the reference minted, so the two are matched through the
    deliveries they hold, which is the same way `compute_reward.py` does it: a
    ticket is identified by its contents, never by its name.
    """
    sys.path.insert(0, str(HERE / "verifier-data" / "model"))
    from intake_model import evaluate  # noqa: PLC0415

    expected = evaluate(spec)
    groups: dict[str, dict[str, Any]] = expected["groups"]
    problems: list[str] = []

    if len(recorded) != len(groups):
        problems.append(
            f"the recording ships {len(recorded)} tickets and the model accounts for {len(groups)}"
        )

    # Match on the set of deliveries held, which names a ticket uniquely for
    # every ticket that holds one.
    by_envelopes: dict[tuple[str, ...], list[str]] = {}
    for label, group in groups.items():
        by_envelopes.setdefault(tuple(group["envelopes"]), []).append(label)

    identifier_of_label: dict[str, str] = {}
    for ticket in recorded:
        held = tuple(entry["transport_id"] for entry in ticket["envelopes"])
        candidates = by_envelopes.get(held) or []
        if len(candidates) == 1:
            identifier_of_label[candidates[0]] = ticket["ticket_id"]

    # A merged-away ticket holds nothing, so the deliveries do not name it and
    # two of them in one desk are indistinguishable that way. Rather than pick
    # one and report the crossed pairing as a disagreement, every pairing is
    # tried and the one that agrees is taken; if none agrees, the fewest
    # problems are reported, which is the real disagreement.
    empty_labels = sorted(
        label
        for label, group in groups.items()
        if label not in identifier_of_label and not group["envelopes"]
    )
    empty_tickets = [
        ticket["ticket_id"]
        for ticket in recorded
        if not ticket["envelopes"] and ticket["ticket_id"] not in identifier_of_label.values()
    ]
    if len(empty_labels) != len(empty_tickets):
        problems.append(
            f"the recording ships {len(empty_tickets)} tickets holding no delivery "
            f"and the model accounts for {len(empty_labels)}"
        )
        return problems
    if len(empty_labels) > 6:
        problems.append("too many merged-away tickets to pair up unambiguously")
        return problems

    recorded_by_id = {ticket["ticket_id"]: ticket for ticket in recorded}

    def compare(mapping: dict[str, str]) -> list[str]:
        found: list[str] = []
        for label, group in sorted(groups.items()):
            ticket = recorded_by_id[mapping[label]]
            where = f"{label} (shipped as {ticket['ticket_id'][:8]})"

            if ticket["tenant_id"] != group["tenant_id"]:
                found.append(
                    f"{where}: desk {ticket['tenant_id']}, model says {group['tenant_id']}"
                )
            if ticket["status"] != group["status"]:
                found.append(f"{where}: {ticket['status']}, model says {group['status']}")
            if ticket.get("requester_identity_id") != group["requester_identity_id"]:
                found.append(
                    f"{where}: requester {ticket.get('requester_identity_id')}, "
                    f"model says {group['requester_identity_id']}"
                )

            held = [entry["transport_id"] for entry in ticket["envelopes"]]
            if held != group["envelopes"]:
                found.append(f"{where}: holds {held}, model says {group['envelopes']}")

            for field, label_field in (
                ("prior_ticket_id", "prior_group"),
                ("merged_into_ticket_id", "merged_into_group"),
            ):
                wanted_label = group[label_field]
                got = ticket.get(field)
                if wanted_label is None:
                    if got:
                        found.append(f"{where}: {field} is {got}, model says nothing")
                else:
                    wanted = mapping.get(wanted_label)
                    if got != wanted:
                        found.append(
                            f"{where}: {field} is {got}, model says {wanted_label} ({wanted})"
                        )
        return found

    best: list[str] | None = None
    for order in itertools.permutations(empty_tickets):
        mapping = dict(identifier_of_label)
        mapping.update(dict(zip(empty_labels, order)))
        if len(mapping) != len(groups):
            missing = sorted(set(groups) - set(mapping))
            problems.append(f"no shipped ticket matches the model's {', '.join(missing)}")
            return problems
        found = compare(mapping)
        if not found:
            best = []
            break
        if best is None or len(found) < len(best):
            best = found
    problems.extend(best or [])

    # Sandbox and holdout must share no identifier. Checked here rather than
    # promised, because it is the sort of thing that survives a rewrite.
    graded = HERE / "verifier-data" / "run-spec.json"
    if graded.exists():
        held_out = json.loads(graded.read_text(encoding="utf-8"))
        theirs: set[str] = set()
        for operation in held_out["operations"]:
            for envelope in (
                [operation["envelope"]]
                if operation["op"] == "post"
                else operation.get("envelopes") or []
            ):
                theirs.update(
                    {
                        envelope["tenant_id"],
                        envelope["transport_id"],
                        envelope["message_id"],
                        envelope["from_address"],
                        envelope["received_at"],
                    }
                )
        for entry in held_out["identities"]:
            theirs.add(entry["identity_id"])
        for entry in held_out["aliases"]:
            theirs.add(entry["address"])

        ours: set[str] = set()
        for operation in spec["operations"]:
            if operation["op"] != "post":
                continue
            envelope = operation["envelope"]
            ours.update(
                {
                    envelope["tenant_id"],
                    envelope["transport_id"],
                    envelope["message_id"],
                    envelope["from_address"],
                    envelope["received_at"],
                }
            )
        for entry in spec["identities"]:
            ours.add(entry["identity_id"])
        for entry in spec["aliases"]:
            ours.add(entry["address"])

        shared = ours & theirs
        if shared:
            problems.append(f"sandbox and holdout share identifiers: {sorted(shared)[:8]}")

    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", help="write the stretch here")
    parser.add_argument("--reference", help="write the recorded desks' reference data here")
    parser.add_argument("--validate", help="check this tickets.json against the model")
    parser.add_argument("--outbox", help="check this outbox.json alongside it")
    arguments = parser.parse_args()

    spec = build()

    if arguments.reference:
        path = pathlib.Path(arguments.reference)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "identities": spec["identities"],
                    "aliases": spec["aliases"],
                    "desk_addresses": spec["desk_addresses"],
                    "desk_gateways": spec["desk_gateways"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            f"{len(spec['identities'])} identities, {len(spec['aliases'])} aliases and "
            f"{len(spec['desk_addresses'])} desk addresses -> {path}"
        )

    if arguments.spec:
        path = pathlib.Path(arguments.spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        posts = sum(1 for operation in spec["operations"] if operation["op"] == "post")
        print(f"{posts} deliveries, {len(spec['operations'])} operations -> {path}")

    if arguments.validate:
        recorded = json.loads(pathlib.Path(arguments.validate).read_text(encoding="utf-8"))
        tickets = recorded["tickets"] if isinstance(recorded, dict) else recorded
        problems = validate(spec, tickets)
        if arguments.outbox:
            shipped = json.loads(
                pathlib.Path(arguments.outbox).read_text(encoding="utf-8")
            )
            rows = shipped["replies"] if isinstance(shipped, dict) else shipped
            problems.extend(validate_outbox(spec, tickets, rows))
            print(f"{len(rows)} recorded outbox rows checked")
        if problems:
            print("the recording does not agree with the model the scorer uses:")
            for problem in problems:
                print(f"  - {problem}")
            raise SystemExit(1)
        print(f"{len(recorded['tickets'] if isinstance(recorded, dict) else recorded)} "
              "recorded tickets agree with the model, and share no identifier with the holdout")


if __name__ == "__main__":
    main()
