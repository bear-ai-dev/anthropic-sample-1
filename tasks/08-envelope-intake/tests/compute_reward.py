#!/usr/bin/env python3
"""Works out what should have happened, and compares it with what did.

Runs as root, under `env -i`, and loads no submitted code. Its two inputs are the
transcript the driver recorded over HTTP and the run specification held out of
the workspace. What *should* have happened is computed here and now, by the
independent model in `model/intake_model.py`, which was written from the
specification rather than from the service and shares nothing with it.

Ticket identifiers are minted by the submission, so nothing is compared by
identifier. What is compared is which deliveries ended up together, which ticket
each one was answered with relative to the others, and what each ticket says
about itself. A submission that groups the deliveries correctly passes whatever
identifiers it chose.

The reward is binary and it fails closed: it starts at zero and is only raised if
every rule passed.

`reward.json` gets numbers and nothing else. Harbor loads the whole file as
`dict[str, float | int]`, and a string, list, dict or bool anywhere in it makes
the trial an exception with no score at all. Everything else goes to
`reward-detail.json` beside it, and the split is done here, at the point of
writing, on every path -- including the failure paths, which are exactly the
ones that never reach a sweep at the end of a script.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


# --------------------------------------------------------------------------
# writing the verdict
# --------------------------------------------------------------------------


def write_outcome(
    output_dir: str,
    numbers: dict[str, float],
    detail: dict[str, Any],
    summary: str,
) -> None:
    os.makedirs(output_dir, exist_ok=True)
    clean = {
        key: value
        for key, value in numbers.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    with open(os.path.join(output_dir, "reward.json"), "w", encoding="utf-8") as handle:
        json.dump(clean, handle)
        handle.write("\n")
    with open(
        os.path.join(output_dir, "reward-detail.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(detail, handle, indent=2, sort_keys=False, default=str)
        handle.write("\n")
    reward = clean.get("reward")
    with open(os.path.join(output_dir, "reward.txt"), "w", encoding="utf-8") as handle:
        handle.write(f"{reward if reward is not None else 0.0}\n")
    with open(os.path.join(output_dir, "report.txt"), "w", encoding="utf-8") as handle:
        handle.write(summary.rstrip() + "\n")


def graded_failure(output_dir: str, reason: str, detail: dict[str, Any] | None = None) -> None:
    body = {"verdict": "incorrect", "reason": reason}
    if detail:
        body.update(detail)
    write_outcome(output_dir, {"reward": 0.0, "score": 0.0}, body, f"FAIL: {reason}")


def harness_failure(output_dir: str, reason: str, detail: dict[str, Any] | None = None) -> None:
    body = {"verdict": "harness_failure", "reason": reason}
    if detail:
        body.update(detail)
    # A harness failure is not a wrong answer, and the flag is what says so. The
    # zero beside it is there because Harbor requires a reward on every path: a
    # reward.json without one is not a nought, it is a trial with no score at
    # all, which is an exception rather than a result.
    write_outcome(
        output_dir,
        {"reward": 0.0, "harness_failure": 1},
        body,
        f"HARNESS FAILURE: {reason}",
    )


# --------------------------------------------------------------------------
# the observed picture
# --------------------------------------------------------------------------


class Observed:
    """What the submission did, indexed for comparison.

    Where a delivery ended up is taken from the tickets that list it, and only
    from the response it was answered with when no ticket lists it at all. The
    two are not interchangeable: a delivery whose ticket was later merged away
    was answered with one identifier and lives under another, and the ticket that
    holds it now is the submission's current account of itself. Reading them the
    other way round would call a correct merge a contradiction.
    """

    def __init__(self, transcript: dict[str, Any]) -> None:
        self.transcript = transcript
        self.responses: dict[str, list[dict[str, Any]]] = {}
        for entry in transcript.get("responses") or []:
            self.responses.setdefault(entry["transport_id"], []).append(entry)

        #: read operation index -> what that read returned.
        self.reads: dict[int, dict[str, Any]] = {}
        for entry in transcript.get("reads") or []:
            self.reads[int(entry.get("index", -1))] = entry

        #: operation index -> what the console was told when it handed a reply
        #: over, what an outbox read listed, and what was on the wire.
        self.replies: dict[int, dict[str, Any]] = {}
        for entry in transcript.get("replies") or []:
            self.replies[int(entry.get("index", -1))] = entry
        self.outboxes: dict[int, dict[str, Any]] = {}
        for entry in transcript.get("outboxes") or []:
            self.outboxes[int(entry.get("index", -1))] = entry
        self.spools: dict[int, dict[str, Any]] = {}
        for entry in transcript.get("spools") or []:
            self.spools[int(entry.get("index", -1))] = entry

        by_read: dict[str, str] = {}
        self.conflicts: list[str] = []
        for entry in transcript.get("reads") or []:
            ticket = entry.get("ticket_id")
            if not ticket or not isinstance(entry.get("envelopes"), list):
                continue
            for transport in entry["envelopes"]:
                existing = by_read.get(transport)
                if existing is not None and existing != ticket:
                    self.conflicts.append(
                        f"{transport} is listed on {existing} and on {ticket}"
                    )
                    continue
                by_read[transport] = ticket

        by_response: dict[str, str] = {}
        for transport, entries in self.responses.items():
            for entry in entries:
                ticket = entry.get("ticket_id")
                if ticket:
                    # The last one, not the first: it is the more recent account.
                    by_response[transport] = ticket

        self.placed: dict[str, str] = dict(by_response)
        self.placed.update(by_read)

    def response(self, transport: str, occurrence: int) -> dict[str, Any] | None:
        entries = self.responses.get(transport) or []
        return entries[occurrence] if occurrence < len(entries) else None


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


class Judge:
    def __init__(self, expected: dict[str, Any], observed: Observed) -> None:
        self.expected = expected
        self.observed = observed
        self.groups: dict[str, dict[str, Any]] = expected["groups"]
        self.model_placed: dict[str, str] = {}
        for label, group in self.groups.items():
            for transport in group["envelopes"]:
                self.model_placed[transport] = label
        self.model_responses: dict[str, list[dict[str, Any]]] = {}
        for entry in expected["responses"]:
            self.model_responses.setdefault(entry["transport_id"], []).append(entry)
        #: read operation index -> the ticket the run would have asked for. The
        #: driver reads through the identifier the service last handed it, so
        #: which ticket a read lands on is a fact about the run and not about
        #: where the delivery ended up. After a merge those differ.
        self.read_groups: dict[str, str | None] = expected.get("read_groups") or {}
        self.reply_answers: dict[str, dict[str, Any]] = expected.get("reply_answers") or {}
        self.outbox_reads: dict[str, list[dict[str, Any]]] = (
            expected.get("outbox_reads") or {}
        )
        self.spool_reads: dict[str, list[str]] = expected.get("spool_reads") or {}
        self.read_snapshots: dict[str, dict[str, Any]] = (
            expected.get("read_snapshots") or {}
        )

    # -- helpers ----------------------------------------------------------

    def model_response(self, transport: str, occurrence: int) -> dict[str, Any] | None:
        entries = self.model_responses.get(transport) or []
        return entries[occurrence] if occurrence < len(entries) else None

    def observed_ticket_of_group(self, label: str) -> str | None:
        """A ticket identifier the submission used for this group, if any."""
        for transport in self.groups[label]["envelopes"]:
            ticket = self.observed.placed.get(transport)
            if ticket is not None:
                return ticket
        return None

    # -- check kinds ------------------------------------------------------

    def check_response(self, check: dict[str, Any]) -> list[str]:
        transport = check["transport_id"]
        occurrence = check.get("occurrence", 0)
        wanted = self.model_response(transport, occurrence)
        if wanted is None:
            return [f"the model has no response {occurrence} for {transport}"]
        got = self.observed.response(transport, occurrence)
        if got is None:
            return [f"{transport}[{occurrence}]: the service was never asked, or never answered"]

        problems: list[str] = []
        status = got.get("http_status") or 0
        if not 200 <= status < 300:
            return [f"{transport}[{occurrence}]: answered HTTP {status}, not an acceptance"]
        if got.get("action") != wanted["action"]:
            problems.append(
                f"{transport}[{occurrence}]: answered {got.get('action')!r}, "
                f"the specification says {wanted['action']!r}"
            )

        if wanted["action"] == "duplicate":
            # A redelivery has to be answered with the ticket the delivery is on
            # when it is asked -- not a fresh one, not nothing, and not
            # necessarily the one it was first answered with: a delivery whose
            # ticket has since been merged away is on the ticket that absorbed
            # it. Which identifier that is, is the submission's own choice, so it
            # is resolved through the ticket the submission used for the group
            # the specification places the delivery in.
            wanted_group = wanted.get("group")
            expected_ticket = (
                self.observed_ticket_of_group(wanted_group)
                if wanted_group is not None
                else None
            )
            if expected_ticket is not None and got.get("ticket_id") != expected_ticket:
                problems.append(
                    f"{transport}[{occurrence}]: redelivery answered ticket "
                    f"{got.get('ticket_id')!r}, the delivery is on {expected_ticket!r}"
                )
        elif wanted["action"] == "pending":
            named = got.get("ticket_id")
            if named is not None:
                eventual = self.observed.placed.get(transport)
                if eventual != named:
                    problems.append(
                        f"{transport}[{occurrence}]: held delivery answered ticket "
                        f"{named!r}, which is not where it ended up ({eventual!r})"
                    )
        return problems

    def check_response_not_duplicate(self, check: dict[str, Any]) -> list[str]:
        """Accepted as a delivery of its own, whatever it was then called.

        A delivery carrying a message identifier already seen is still a new
        delivery. Which accepting outcome it is answered with belongs to the rule
        that owns that label, so nothing here reads the label beyond ruling out
        the one answer that would be wrong.
        """
        transport = check["transport_id"]
        got = self.observed.response(transport, 0)
        if got is None:
            return [f"{transport}: the service was never asked, or never answered"]
        status = got.get("http_status") or 0
        if not 200 <= status < 300:
            return [f"{transport}: answered HTTP {status}, not an acceptance"]
        if got.get("action") == "duplicate":
            return [
                f"{transport}: answered 'duplicate'; it carries a message identifier "
                "already seen but it is a delivery of its own"
            ]
        if not got.get("ticket_id"):
            return [f"{transport}: accepted onto no ticket"]
        return []

    def check_response_action_not(self, check: dict[str, Any]) -> list[str]:
        """Accepted, and not answered with one of these words.

        For a decision whose content is what the submission did *not* do. More
        than one word can be right for a delivery that was recorded and moved
        nothing -- 'appended' is the documented one, and a submission that says
        so in its own vocabulary has not made a mistake -- so nothing here
        insists on a particular one. The words ruled out are the ones that would
        be a report of a decision that should not have been taken.
        """
        transport = check["transport_id"]
        occurrence = check.get("occurrence", 0)
        got = self.observed.response(transport, occurrence)
        if got is None:
            return [f"{transport}: the service was never asked, or never answered"]
        status = got.get("http_status") or 0
        if not 200 <= status < 300:
            return [f"{transport}: answered HTTP {status}, not an acceptance"]
        action = got.get("action")
        forbidden = [str(word).lower() for word in check.get("forbidden") or []]
        if isinstance(action, str) and action.lower() in forbidden:
            return [
                f"{transport}: answered {action!r}; this delivery belongs on the "
                "ticket the conversation was already on, in the state it was "
                "already in"
            ]
        return []

    def check_response_ticket(self, check: dict[str, Any]) -> list[str]:
        """The ticket a delivery was answered with, and not what it was called.

        The outcome word belongs to whichever rule that word is the point of, so
        nothing here reads it. What is checked is that the delivery was accepted
        onto the ticket the specification puts it on, resolved through the
        identifier the submission chose for that group.
        """
        transport = check["transport_id"]
        occurrence = check.get("occurrence", 0)
        wanted = self.model_response(transport, occurrence)
        if wanted is None:
            return [f"the model has no response {occurrence} for {transport}"]
        got = self.observed.response(transport, occurrence)
        if got is None:
            return [f"{transport}[{occurrence}]: the service was never asked, or never answered"]
        status = got.get("http_status") or 0
        if not 200 <= status < 300:
            return [f"{transport}[{occurrence}]: answered HTTP {status}, not an acceptance"]

        label = wanted.get("group")
        if label is None:
            return []
        expected_ticket = self.observed_ticket_of_group(label)
        if expected_ticket is None:
            return []
        if got.get("ticket_id") != expected_ticket:
            return [
                f"{transport}[{occurrence}]: answered ticket {got.get('ticket_id')!r}, "
                f"the delivery is on {expected_ticket!r}"
            ]
        return []

    def check_response_multiset(self, check: dict[str, Any]) -> list[str]:
        transports = check["transports"]
        wanted: list[str] = []
        got: list[str] = []
        for transport in transports:
            expected_entry = self.model_response(transport, 0)
            observed_entry = self.observed.response(transport, 0)
            if expected_entry is None:
                return [f"the model has no response for {transport}"]
            if observed_entry is None:
                return [f"{transport}: the service never answered"]
            status = observed_entry.get("http_status") or 0
            if not 200 <= status < 300:
                return [f"{transport}: answered HTTP {status}, not an acceptance"]
            wanted.append(expected_entry["action"])
            got.append(observed_entry.get("action") or "<none>")
        if sorted(wanted) != sorted(got):
            return [
                f"{', '.join(transports)}: answered {sorted(got)}, "
                f"the specification says {sorted(wanted)} in either order"
            ]
        return []

    def check_partition(self, check: dict[str, Any]) -> list[str]:
        """Whether these deliveries were grouped the way the specification says.

        Compared as an equivalence relation, never by identifier: the submission
        mints its own, and any consistent choice is correct.
        """
        transports = check["transports"]
        problems: list[str] = []
        for transport in transports:
            wanted_group = self.model_placed.get(transport)
            got_ticket = self.observed.placed.get(transport)
            if wanted_group is None and got_ticket is not None:
                problems.append(
                    f"{transport}: on ticket {got_ticket!r}; the specification places it on none"
                )
            if wanted_group is not None and got_ticket is None:
                problems.append(f"{transport}: on no ticket the service ever showed us")
        if problems:
            return problems

        for index, left in enumerate(transports):
            for right in transports[index + 1 :]:
                same_wanted = (
                    self.model_placed.get(left) is not None
                    and self.model_placed.get(left) == self.model_placed.get(right)
                )
                same_got = (
                    self.observed.placed.get(left) is not None
                    and self.observed.placed.get(left) == self.observed.placed.get(right)
                )
                if same_wanted and not same_got:
                    problems.append(f"{left} and {right} belong on one ticket and are on two")
                elif same_got and not same_wanted:
                    problems.append(f"{left} and {right} belong on two tickets and are on one")
        return problems

    def check_read(self, check: dict[str, Any]) -> list[str]:
        index = int(check["index"])
        name = f"read {check['tenant_id']}/{check['of']}"
        entry = self.observed.reads.get(index)
        if entry is None:
            return [f"{name}: never performed"]
        status = entry.get("http_status") or 0
        if not 200 <= status < 300:
            return [
                f"{name}: answered HTTP {status}"
                + (f" ({entry.get('note')})" if entry.get("note") else "")
            ]

        label = self.read_groups.get(str(index))
        if label is None:
            return [f"{name}: the specification puts no ticket in front of this read"]
        group = self.groups[label]
        if check.get("snapshot"):
            # The ticket as it stood when this read happened, rather than when
            # the run finished. For a rule whose content is a moment -- a reply
            # composed and not yet sent, a ticket that is still closed because
            # the message that went out was the desk's -- the finished ticket is
            # the wrong thing to compare against.
            snapshot = (self.read_snapshots or {}).get(str(index))
            if snapshot is None:
                return [f"{name}: the specification has no snapshot for this read"]
            group = snapshot
        key = (check["tenant_id"], check["of"])

        problems: list[str] = []
        for field in check.get("fields", []):
            if field == "ticket":
                if entry.get("ticket_id") != entry.get("requested_ticket_id"):
                    problems.append(
                        f"read {key[1]}: asked for ticket {entry.get('requested_ticket_id')!r} "
                        f"and was given {entry.get('ticket_id')!r}"
                    )
            elif field == "status":
                if entry.get("status") != group["status"]:
                    problems.append(
                        f"read {key[1]}: ticket is {entry.get('status')!r}, "
                        f"the specification says {group['status']!r}"
                    )
            elif field == "prior":
                wanted_prior_label = group["prior_group"]
                got_prior = entry.get("prior_ticket_id")
                if wanted_prior_label is None:
                    if got_prior:
                        problems.append(
                            f"read {key[1]}: continues {got_prior!r}; "
                            "the specification says it continues nothing"
                        )
                else:
                    wanted_prior = self.observed_ticket_of_group(wanted_prior_label)
                    if got_prior is None:
                        problems.append(
                            f"read {key[1]}: continues nothing; the specification says it "
                            f"continues the conversation's previous ticket"
                        )
                    elif wanted_prior is not None and got_prior != wanted_prior:
                        problems.append(
                            f"read {key[1]}: continues {got_prior!r}, "
                            f"which is not the ticket it followed ({wanted_prior!r})"
                        )
            elif field == "merged":
                problems.extend(self.check_merged(entry, group, key[1]))
            elif field == "requester":
                if entry.get("requester_identity_id") != group["requester_identity_id"]:
                    problems.append(
                        f"read {key[1]}: requester {entry.get('requester_identity_id')!r}, "
                        f"the specification says {group['requester_identity_id']!r}"
                    )
            elif field == "envelopes_set":
                got = entry.get("envelopes")
                if not isinstance(got, list):
                    problems.append(f"read {key[1]}: no list of deliveries in the answer")
                elif sorted(set(got)) != sorted(set(group["envelopes"])):
                    problems.append(
                        f"read {key[1]}: lists {sorted(set(got))}, "
                        f"the specification says {sorted(set(group['envelopes']))}"
                    )
                elif len(got) != len(set(got)):
                    problems.append(f"read {key[1]}: lists a delivery more than once ({got})")
            elif field == "messages":
                # How many distinct messages the ticket holds, rather than how
                # many deliveries. A message the desk sent and the gateway then
                # handed back is one message; a ticket showing it twice is a
                # different mistake from a ticket missing it, and this is the
                # field that tells them apart.
                got = entry.get("envelope_messages")
                if not isinstance(got, list):
                    problems.append(
                        f"read {key[1]}: the deliveries do not say which message each one is"
                    )
                elif sorted(got) != sorted(group["messages"]):
                    problems.append(
                        f"read {key[1]}: holds messages {sorted(got)}, "
                        f"the specification says {sorted(group['messages'])}"
                    )
            elif field == "envelopes_order":
                got = entry.get("envelopes")
                if not isinstance(got, list):
                    problems.append(f"read {key[1]}: no list of deliveries in the answer")
                elif got != group["envelopes"]:
                    problems.append(
                        f"read {key[1]}: lists {got}, "
                        f"the specification says {group['envelopes']}"
                    )
        return problems

    def check_merged(
        self, entry: dict[str, Any], group: dict[str, Any], of: str
    ) -> list[str]:
        """Whether a ticket says it was folded into another, and into which.

        The field name is not graded. The documented one is preferred, and
        failing that any value in the answer that is the survivor's identifier
        counts: what is being checked is that the ticket records where its
        history went, not that it spells it a particular way.
        """
        wanted_label = group.get("merged_into_group")
        stated = entry.get("merged_into_ticket_id")
        if wanted_label is None:
            if stated:
                return [
                    f"read {of}: says it was merged into {stated!r}; "
                    "the specification says it was not merged at all"
                ]
            return []

        wanted = self.observed_ticket_of_group(wanted_label)
        if wanted is None:
            # The submission never showed us a ticket for the survivor, so there
            # is no identifier to compare against. Whether the deliveries got
            # there is checked by the partition either way.
            return []
        if stated == wanted:
            return []
        if wanted in (entry.get("strings") or []):
            return []
        return [
            f"read {of}: records nothing that names the ticket it was merged "
            f"into ({wanted!r}); it says {stated!r}"
        ]

    # -- the outbound half ------------------------------------------------

    def check_reply_state(self, check: dict[str, Any]) -> list[str]:
        """What the console was told when it handed a reply over.

        The state is the whole of it. A reply is taken once however many times
        the console offers it, and the answer to an offer is where the reply is
        at that moment -- which after a tick is not where the console left it.
        """
        index = int(check["index"])
        entry = self.observed.replies.get(index)
        wanted = self.reply_answers.get(str(index))
        if wanted is None:
            return [f"the specification has no reply answer at operation {index}"]
        if entry is None:
            return [f"reply {wanted['reply_id']}: never handed over"]
        status = int(entry.get("http_status") or 0)
        if not 200 <= status < 300:
            return [
                f"reply {wanted['reply_id']}: answered HTTP {status}"
                + (f" ({entry.get('note')})" if entry.get("note") else "")
            ]
        got = entry.get("state")
        if got != wanted["state"]:
            return [
                f"reply {wanted['reply_id']}: answered state {got!r}, "
                f"the specification says {wanted['state']!r}"
            ]
        return []

    def check_reply_denied(self, check: dict[str, Any]) -> list[str]:
        """A reply composed on a ticket that is not this desk's is refused."""
        index = int(check["index"])
        entry = self.observed.replies.get(index)
        if entry is None:
            return [f"reply at operation {index}: never handed over"]
        status = int(entry.get("http_status") or 0)
        if 400 <= status < 500:
            return []
        if 200 <= status < 300:
            return [
                f"reply at operation {index}: taken (HTTP {status}) on a ticket "
                "that is not this desk's"
            ]
        return [
            f"reply at operation {index}: answered HTTP {status}, "
            "neither taken nor refused"
        ]

    def check_outbox(self, check: dict[str, Any]) -> list[str]:
        """What the desk says it is holding, and what state each reply is in.

        Compared on the message identifier, because that is the one key both
        sides of the wire agree on. A reply the console composed is also compared
        on the key the console gave it -- the console has to be able to ask about
        it -- but a row that came out of the history has no such key: whatever
        the migration invented for it is the migration's business, and grading it
        would be grading a name nothing settles.
        """
        index = int(check["index"])
        entry = self.observed.outboxes.get(index)
        wanted = self.outbox_reads.get(str(index))
        if wanted is None:
            return [f"the specification has no outbox read at operation {index}"]
        if entry is None:
            return [f"outbox read at operation {index}: never performed"]
        status = int(entry.get("http_status") or 0)
        if not 200 <= status < 300:
            return [
                f"outbox read at operation {index}: answered HTTP {status}"
                + (f" ({entry.get('raw')})" if entry.get("raw") else "")
            ]
        entries = entry.get("entries")
        if not isinstance(entries, list):
            return [f"outbox read at operation {index}: no list of replies in the answer"]

        # Scoped to the messages this check is about. One desk's outbox holds
        # every reply that desk ever composed, so comparing the whole of it would
        # make one wrong reading fail every rule that reads that desk -- and
        # would leave the rule the mistake belongs to with no candidate that
        # fails it alone. What is not named here belongs to another rule.
        problems: list[str] = []
        got_states = {
            item.get("message_id"): item.get("state")
            for item in entries
            if item.get("message_id")
        }
        want_states = {item["message_id"]: item["state"] for item in wanted}
        got_keys = {item.get("reply_id") for item in entries}

        for message in check.get("messages") or []:
            if message not in want_states:
                problems.append(
                    f"the specification does not put {message} in this desk's outbox"
                )
                continue
            if message not in got_states:
                problems.append(
                    f"outbox {index}: does not list {message}, which the desk "
                    f"composed or sent (it should be {want_states[message]!r})"
                )
            elif got_states[message] != want_states[message]:
                problems.append(
                    f"outbox {index}: {message} is {got_states[message]!r}, "
                    f"the specification says {want_states[message]!r}"
                )
            key = next(
                (
                    item["reply_id"]
                    for item in wanted
                    if item["message_id"] == message and item.get("reply_id") is not None
                ),
                None,
            )
            if key is not None and key not in got_keys:
                problems.append(
                    f"outbox {index}: nothing in the answer carries the key the "
                    f"console gave reply {key!r}"
                )

        for message in check.get("absent") or []:
            if message in got_states:
                problems.append(
                    f"outbox {index}: lists {message}, which the desk never sent"
                )
        return problems

    def check_spool(self, check: dict[str, Any]) -> list[str]:
        """What is actually on the wire, read from the transport's own side.

        The one observation the submission does not supply. Compared as a set of
        message identifiers: the transport keys the wire on the message, so a
        message on it twice is not a thing that can happen, and a message that is
        not on it did not go out however the service describes it.
        """
        index = int(check["index"])
        entry = self.observed.spools.get(index)
        wanted = self.spool_reads.get(str(index))
        if wanted is None:
            return [f"the specification has no spool read at operation {index}"]
        if entry is None:
            return [f"spool read at operation {index}: never performed"]
        if entry.get("note"):
            return [f"spool read at operation {index}: {entry['note']}"]
        got = entry.get("messages")
        if not isinstance(got, list):
            return [f"spool read at operation {index}: nothing was read"]

        on_wire = set(got)
        should_be = set(wanted)
        problems: list[str] = []
        # Scoped, for the same reason the outbox check is: the wire accumulates
        # everything the desk has ever sent.
        for message in check.get("messages") or []:
            if message not in should_be:
                problems.append(
                    f"the specification does not put {message} on this desk's wire"
                )
            elif message not in on_wire:
                problems.append(
                    f"the wire at operation {index} does not carry {message}"
                )
        for message in check.get("absent") or []:
            if message in on_wire:
                problems.append(
                    f"the wire at operation {index} carries {message}, "
                    "which nothing should have put there"
                )
        return problems

    def check_read_denied(self, check: dict[str, Any]) -> list[str]:
        index = int(check["index"])
        name = f"read {check['tenant_id']}/{check['of']}"
        entry = self.observed.reads.get(index)
        if entry is None:
            return [f"{name}: never performed"]
        status = entry.get("http_status") or 0
        if 400 <= status < 500:
            return []
        if 200 <= status < 300:
            if not entry.get("ticket_id") and not entry.get("envelopes"):
                # Answered, but disclosed nothing. Refusal in another shape.
                return []
            return [
                f"{name}: another desk's ticket was served "
                f"(HTTP {status}, ticket {entry.get('ticket_id')!r})"
            ]
        return [f"{name}: answered HTTP {status}, neither served nor refused"]

    # -- driving ----------------------------------------------------------

    def run(self, rules: dict[str, Any]) -> dict[str, Any]:
        kinds = {
            "response": self.check_response,
            "response_not_duplicate": self.check_response_not_duplicate,
            "response_action_not": self.check_response_action_not,
            "response_ticket": self.check_response_ticket,
            "response_multiset": self.check_response_multiset,
            "partition": self.check_partition,
            "read": self.check_read,
            "read_denied": self.check_read_denied,
            "reply_state": self.check_reply_state,
            "reply_denied": self.check_reply_denied,
            "outbox": self.check_outbox,
            "spool": self.check_spool,
        }
        verdicts: dict[str, Any] = {}
        for rule_id in sorted(rules, key=lambda name: (len(name), name)):
            rule = rules[rule_id]
            problems: list[str] = []
            for check in rule["checks"]:
                problems.extend(kinds[check["kind"]](check))
            verdicts[rule_id] = {
                "title": rule["title"],
                "checks": len(rule["checks"]),
                "passed": not problems,
                "problems": problems[:12],
                "problem_count": len(problems),
            }
        return verdicts


# --------------------------------------------------------------------------
# entry
# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--spec")
    parser.add_argument("--observed")
    parser.add_argument(
        "--model-dir",
        help="Directory holding intake_model.py. Held out of the workspace.",
    )
    parser.add_argument("--fail")
    parser.add_argument("--harness-failure")
    arguments = parser.parse_args()

    if arguments.harness_failure:
        harness_failure(arguments.output_dir, arguments.harness_failure)
        return
    if arguments.fail:
        graded_failure(arguments.output_dir, arguments.fail)
        return
    if not arguments.spec or not arguments.observed:
        harness_failure(arguments.output_dir, "compute_reward was given no run to score")
        return

    try:
        with open(arguments.spec, encoding="utf-8") as handle:
            spec = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        harness_failure(arguments.output_dir, f"the run specification would not load: {error}")
        return
    try:
        with open(arguments.observed, encoding="utf-8") as handle:
            transcript = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        harness_failure(arguments.output_dir, f"the transcript would not load: {error}")
        return

    if arguments.model_dir:
        sys.path.insert(0, arguments.model_dir)
    try:
        from intake_model import evaluate
    except ImportError as error:
        harness_failure(arguments.output_dir, f"the model would not import: {error}")
        return

    try:
        expected = evaluate(spec)
    except Exception as error:  # noqa: BLE001 - the model failing is ours, not theirs
        harness_failure(arguments.output_dir, f"the model would not run: {error}")
        return

    if not transcript.get("healthy"):
        # The submission's own answer, not the harness's. The service is the
        # submitted code: a submission that will not start is wrong about
        # everything the run asks, and it has to be scored as wrong rather than
        # reported as an exception. Everything that could make this ours has
        # already been checked -- the store was migrated, the port was free
        # before the launch, and the pristine workspace answers here.
        graded_failure(
            arguments.output_dir,
            "the service never answered /health, so nothing could be exercised",
            {"note": transcript.get("note")},
        )
        return

    # A restart the harness could not perform is the harness's, not the
    # submission's: the service was never stopped, so the run after that point
    # measured nothing. A restart that happened and left the service silent is
    # the opposite -- that is an answer about the submission, and the deliveries
    # after it are graded as they stand.
    broken = [
        entry
        for entry in (transcript.get("restarts") or [])
        if entry.get("skipped") or entry.get("exit") not in (0, None)
    ]
    if broken:
        harness_failure(
            arguments.output_dir,
            "a restart the run asked for could not be performed",
            {"restarts": transcript.get("restarts")},
        )
        return

    intake_path = transcript.get("intake_path")
    if not intake_path:
        attempts = (transcript.get("intake_probe") or {}).get("attempts") or []
        # Any 501 at all is the untouched workspace: the documented route is
        # there and answers "not implemented", and the other paths the driver
        # tries are 404 precisely because they were never real. Requiring every
        # attempt to be a 501 would never match, and the run would be reported
        # with the vaguer reason.
        every_unimplemented = any(attempt.get("status") == 501 for attempt in attempts)
        graded_failure(
            arguments.output_dir,
            (
                "the intake route answers 501: nothing routes a delivery onto a ticket"
                if every_unimplemented
                else "no route accepted a delivery and answered with an outcome"
            ),
            {"intake_probe": transcript.get("intake_probe")},
        )
        return

    observed = Observed(transcript)
    verdicts = Judge(expected, observed).run(spec["rules"])

    passed = sum(1 for verdict in verdicts.values() if verdict["passed"])
    total = len(verdicts)
    failed = [rule_id for rule_id, verdict in verdicts.items() if not verdict["passed"]]

    detail: dict[str, Any] = {
        "verdict": "correct" if not failed else "incorrect",
        "rules": verdicts,
        "rules_failed": failed,
        "seam": {
            "intake_path": intake_path,
            "read_template": transcript.get("read_template"),
            "close_probe_ok": (transcript.get("close_probe") or {}).get("ok"),
        },
        "placement_conflicts": observed.conflicts[:12],
        "restarts": transcript.get("restarts"),
        "alive_after": transcript.get("alive_after"),
        "deliveries": spec.get("posts"),
        "checks": spec.get("checks"),
    }

    numbers: dict[str, float] = {
        "reward": 1.0 if not failed else 0.0,
        "score": 1.0 if not failed else 0.0,
        "rules_total": total,
        "rules_passed": passed,
    }
    for rule_id, verdict in verdicts.items():
        numbers[f"rule_{rule_id}"] = 1 if verdict["passed"] else 0

    summary = (
        f"{'PASS' if not failed else 'FAIL'}: {passed}/{total} rules"
        + (f"; failed {', '.join(failed)}" if failed else "")
    )
    write_outcome(arguments.output_dir, numbers, detail, summary)


if __name__ == "__main__":
    main()
