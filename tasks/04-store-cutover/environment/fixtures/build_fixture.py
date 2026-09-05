#!/usr/bin/env python3
"""Build a legacy ledger database and the canonical append log beside it.

The database is what the service starts from. The log is the only statement of
what the ledger means: one line per committed entry, in commit order. Nothing
downstream of here reads the database to decide what is correct.

Three datasets are built from this one generator with different parameters: the
one the box develops against, the one the archived cutover in
`docs/prior-cutover/` was recorded from, and the one a graded run uses. They
have the same shape and no values in common — `--first-member` puts each in its
own member id range as well — so nothing about one can be assumed of another.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

TIERS = ("basic", "plus", "pro")
REASONS = ("topup", "refund", "promo", "chargeback", "adjustment", "settlement")

SCHEMA = """
CREATE TABLE members (
    member_id     TEXT PRIMARY KEY,
    tier          TEXT NOT NULL,
    balance_cents INTEGER NOT NULL,
    version       INTEGER NOT NULL,
    deleted       INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL
);
CREATE TABLE ledger_entries (
    entry_id    TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL REFERENCES members(member_id),
    seq         INTEGER NOT NULL,
    global_seq  INTEGER NOT NULL UNIQUE,
    delta_cents INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    written_at  TEXT NOT NULL,
    UNIQUE (member_id, seq)
);
CREATE INDEX idx_entries_global_seq ON ledger_entries (global_seq);
CREATE INDEX idx_entries_member ON ledger_entries (member_id);
"""


def build(seed: int, members: int, entries: int, base_epoch: int, out_db: str, out_log: str,
          first_member: int = 1) -> dict:
    rng = random.Random(seed)
    base = datetime.fromtimestamp(base_epoch, tz=timezone.utc)

    member_ids = [f"mbr-{index:06d}" for index in range(first_member, first_member + members)]
    tiers = {mid: TIERS[rng.randrange(len(TIERS))] for mid in member_ids}
    # A tenth of the book is closed. Closed members keep their history and are
    # part of the ledger; they are not a subset anything is allowed to skip.
    deleted = {mid: (rng.random() < 0.10) for mid in member_ids}

    # Every member gets at least one entry, then the rest are spread with a
    # bias so some members are busy and some are nearly idle.
    order = list(member_ids)
    rng.shuffle(order)
    owners = list(order)
    while len(owners) < entries:
        owners.append(order[min(int(abs(rng.gauss(0, 0.35)) * len(order)), len(order) - 1)])
    rng.shuffle(owners)
    owners = owners[:entries]

    per_member_seq: dict[str, int] = {mid: 0 for mid in member_ids}
    balance: dict[str, int] = {mid: 0 for mid in member_ids}
    log = []
    for index, mid in enumerate(owners, start=1):
        per_member_seq[mid] += 1
        delta = rng.randrange(-4_000, 25_000)
        if rng.random() < 0.05:
            delta = -abs(delta) * 3
        balance[mid] += delta
        written_at = (base + timedelta(seconds=index * 7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        log.append(
            {
                "entry_id": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
                "member_id": mid,
                "seq": per_member_seq[mid],
                "global_seq": index,
                "delta_cents": delta,
                "reason": REASONS[rng.randrange(len(REASONS))],
                "written_at": written_at,
                "origin": "seed",
            }
        )

    last_touch = {mid: base.strftime("%Y-%m-%dT%H:%M:%SZ") for mid in member_ids}
    for row in log:
        last_touch[row["member_id"]] = row["written_at"]

    if os.path.exists(out_db):
        os.remove(out_db)
    db = sqlite3.connect(out_db)
    db.executescript(SCHEMA)
    db.executemany(
        "INSERT INTO members (member_id, tier, balance_cents, version, deleted, updated_at)"
        " VALUES (?,?,?,?,?,?)",
        [
            (mid, tiers[mid], balance[mid], per_member_seq[mid], 1 if deleted[mid] else 0, last_touch[mid])
            for mid in member_ids
        ],
    )
    db.executemany(
        "INSERT INTO ledger_entries"
        " (entry_id, member_id, seq, global_seq, delta_cents, reason, written_at)"
        " VALUES (?,?,?,?,?,?,?)",
        [
            (
                row["entry_id"],
                row["member_id"],
                row["seq"],
                row["global_seq"],
                row["delta_cents"],
                row["reason"],
                row["written_at"],
            )
            for row in log
        ],
    )
    db.commit()
    db.execute("PRAGMA journal_mode=WAL")
    db.close()

    with open(out_log, "w", encoding="utf-8") as handle:
        for row in log:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    return {
        "seed": seed,
        "members": members,
        "entries": entries,
        "base_epoch": base_epoch,
        "first_member": member_ids[0],
        "deleted_members": sum(1 for mid in member_ids if deleted[mid]),
        "busiest_member": max(per_member_seq, key=lambda mid: per_member_seq[mid]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--members", type=int, required=True)
    parser.add_argument("--entries", type=int, required=True)
    parser.add_argument("--base-epoch", type=int, default=1_742_000_000)
    parser.add_argument("--first-member", type=int, default=1)
    parser.add_argument("--out-db", required=True)
    parser.add_argument("--out-log", required=True)
    parser.add_argument("--out-summary", default="")
    args = parser.parse_args()

    summary = build(
        args.seed, args.members, args.entries, args.base_epoch, args.out_db, args.out_log,
        first_member=args.first_member,
    )
    if args.out_summary:
        with open(args.out_summary, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
