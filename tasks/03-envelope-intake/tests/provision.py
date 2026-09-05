#!/usr/bin/env python3
"""Provisions the graded desks: reference data, the history they already had,
and the transport's spool.

Identities, addresses, the desks' own addresses and how each desk's gateway is
wired are provisioned outside intake -- the workspace says so and its own sandbox
seed does the same thing -- so they are written straight into the tables the
shipped schema defines. None of this data appears in the workspace: a submission
that leans on the sandbox seed resolves no requester at all, knows none of the
desks' own addresses and does not know which gateway reflects.

The history is written the same way, into `tickets` and `envelopes` and nothing
else. Those are the only two tables the shipped schema has for a desk's past, and
the verifier does not know what a submission adds beside them -- so a store "that
has been in service" is exactly a store with rows in those two tables and no
trace of whatever the submission invented. What the submission's own migrations
make of that history is the graded question.

The spool is the transport's side of the outbound wire (`src/egress/handoff.ts`).
It is created empty, and the flake file is written from the specification so that
the `unknown` outcome happens on the deliveries the run means it to happen on
rather than by luck.

Exits non-zero if the tables are not there to write to. That is not a reason to
stop the run: the rest of the specification is still gradeable, and the rules
that depend on this data fail on their own account.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--spool", help="the transport's spool directory")
    parser.add_argument("--flake", help="where to write the handoff instructions")
    arguments = parser.parse_args()

    with open(arguments.spec, encoding="utf-8") as handle:
        spec = json.load(handle)

    connection = sqlite3.connect(arguments.store)
    problems: list[str] = []
    try:
        writes = (
            (
                "identities",
                "INSERT OR REPLACE INTO identities (tenant_id, identity_id, display_name)"
                " VALUES (:tenant_id, :identity_id, :display_name)",
                spec["identities"],
            ),
            (
                "aliases",
                "INSERT OR REPLACE INTO aliases (tenant_id, address, identity_id)"
                " VALUES (:tenant_id, :address, :identity_id)",
                spec["aliases"],
            ),
            (
                "desk_addresses",
                "INSERT OR REPLACE INTO desk_addresses (tenant_id, address)"
                " VALUES (:tenant_id, :address)",
                spec.get("desk_addresses") or [],
            ),
            (
                "desk_gateways",
                "INSERT OR REPLACE INTO desk_gateways (tenant_id, reflects_own_sends)"
                " VALUES (:tenant_id, :reflects_own_sends)",
                spec.get("desk_gateways") or [],
            ),
            (
                "tickets",
                "INSERT OR REPLACE INTO tickets"
                " (ticket_id, tenant_id, status, requester_identity_id, created_at, closed_at)"
                " VALUES (:ticket_id, :tenant_id, :status, :requester_identity_id,"
                "         :created_at, :closed_at)",
                spec.get("legacy_tickets") or [],
            ),
            (
                "envelopes",
                "INSERT OR REPLACE INTO envelopes"
                " (transport_id, tenant_id, ticket_id, message_id, from_address,"
                "  to_addresses, in_reply_to, references_json, subject_token, received_at)"
                " VALUES (:transport_id, :tenant_id, :ticket_id, :message_id, :from_address,"
                "         :to_addresses, :in_reply_to, :references_json, :subject_token,"
                "         :received_at)",
                spec.get("legacy_envelopes") or [],
            ),
        )
        for label, statement, rows in writes:
            try:
                connection.executemany(statement, rows)
            except sqlite3.Error as error:
                problems.append(f"{label}: {error}")
        connection.commit()

        for table in (
            "identities",
            "aliases",
            "desk_addresses",
            "desk_gateways",
            "tickets",
            "envelopes",
        ):
            try:
                count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                print(f"{table}: {count} rows")
            except sqlite3.Error as error:
                problems.append(f"{table} count: {error}")
    finally:
        connection.close()

    if arguments.spool:
        os.makedirs(arguments.spool, exist_ok=True)
        os.chmod(arguments.spool, 0o777)
        print(f"spool: {arguments.spool}")

    if arguments.flake:
        instructions = [
            f"{item['message_id']} {item['outcome']}"
            for item in (spec.get("handoff_instructions") or [])
        ]
        with open(arguments.flake, "w", encoding="utf-8") as handle:
            handle.write("\n".join(instructions) + ("\n" if instructions else ""))
        os.chmod(arguments.flake, 0o666)
        print(f"handoff instructions: {len(instructions)}")

    for problem in problems:
        print(f"could not provision {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
