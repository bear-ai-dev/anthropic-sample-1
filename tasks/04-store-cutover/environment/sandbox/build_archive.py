#!/usr/bin/env python3
"""Turn a recorded cutover into the archive the workspace ships.

The recording is not written by hand. `.local/record.sh` drives the reference
through `verifier-data/driver.py` — the same harness a graded run uses — against
a third dataset in its own member id range, and then certifies the result with
`verifier-data/model/model.py`, the same model the scorer uses. So the archive
cannot describe a migration the scorer would mark wrong, and it cannot drift
from what is graded when either side changes.

This script is the curation step, and curation is most of the work. A complete
write log of a correct migration is a transcript of the answer: read forward, it
gives away the control flow of every phase. What ships instead is:

  * the end states, which say what a correct migration produced without saying
    how it got there;
  * the migration record and the coordination keyspace as the store accepted
    them, which are the durable artefacts an operator would keep;
  * five short extracts from the store's write log, one per situation the
    archive exists to evidence, with the phase scaffolding around them removed
    and the ledger positions each write carried stripped out.

Everything else is dropped. `--audit` prints what each shipped file carries, so
what the archive is claimed to evidence can be checked against the data rather
than against an intention.

This script is deliberately not in the image: `environment/Dockerfile` copies
named subdirectories only, so `sandbox/` never reaches a layer.

    build_archive.py --run .local/archive-run --out environment/workspace/docs/prior-cutover
"""

from __future__ import annotations

import argparse
import json
import os
import shutil

# The archived deployment. These are the numbers `.local/record.sh` drove the
# recording with, and nothing here may disagree with them.
DEPLOYMENT = {
    "region": "ap-2",
    "shadow_boundary": 380,
    "lease_ttl_seconds": 15,
    "apply_batch_max": 200,
    "workers": ["membershipd-a", "membershipd-b"],
}

WRITE_OPS = ("entry_add", "entry_remove", "member_put", "meta_put", "kv_set", "kv_cas", "kv_del")


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True)
        handle.write("\n")
    return path


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def connections(oplog):
    """Map each writing process to a small stable number.

    The store's write log knows a connection, not a worker. Which connection
    was which worker is recoverable from the lease record's own contents, and
    that correlation is left to be made rather than made here.
    """
    order = []
    for record in oplog:
        pid = record.get("pid")
        if pid is not None and pid not in order:
            order.append(pid)
    return {pid: index + 1 for index, pid in enumerate(order)}


def extract(oplog, wanted, conns):
    """The shipped form of one write log row.

    `global_seqs` is dropped: where in the ledger sweep a fault landed is an
    accident of the harness, and a run that repeated it would land somewhere
    else. Which movements a write carried is kept, because that is what makes
    two writes comparable.
    """
    out = []
    for record in oplog:
        if record.get("n") not in wanted:
            continue
        row = {
            "n": record["n"],
            "conn": conns.get(record.get("pid")),
            "op": record.get("op"),
            "committed": bool(record.get("applied")),
            "acknowledged": record.get("action") in (None, "proceed"),
        }
        if record.get("count") is not None:
            row["rows"] = record["count"]
        keys = record.get("keys") or []
        if keys:
            row["movements"] = sorted(keys)
        detail = record.get("detail") or {}
        if record.get("op") in ("kv_set", "kv_cas", "kv_del"):
            row["key"] = detail.get("key")
            row["value"] = detail.get("value")
            if "swapped" in detail:
                row["swapped"] = detail["swapped"]
        if record.get("op") == "meta_put":
            row["record_before"] = detail.get("before")
            row["record_after"] = detail.get("meta")
        out.append(row)
    return out


def meta_history(oplog, conns):
    rows = []
    for record in oplog:
        if record.get("op") != "meta_put" or not record.get("applied"):
            continue
        detail = record.get("detail") or {}
        if not detail.get("meta"):
            continue
        rows.append({
            "n": record["n"],
            "conn": conns.get(record.get("pid")),
            "was": detail.get("before"),
            "became": detail["meta"],
        })
    return rows


def coordination(oplog, conns):
    rows = []
    for record in oplog:
        if record.get("op") not in ("kv_set", "kv_cas", "kv_del") or not record.get("applied"):
            continue
        detail = record.get("detail") or {}
        row = {
            "n": record["n"],
            "conn": conns.get(record.get("pid")),
            "op": record["op"],
            "key": detail.get("key"),
            "value": detail.get("value"),
        }
        if "swapped" in detail:
            row["swapped"] = detail["swapped"]
        rows.append(row)
    return rows


WINDOWS = (
    "a-batch-and-the-position-recorded-for-it",
    "a-write-the-store-did-not-answer-for",
    "a-writer-recycled-on-a-durable-write",
    "rows-the-ledger-did-not-have",
    "a-lease-that-moved-mid-write",
)


def find_windows(oplog):
    """Locate the five situations the extracts exist for.

    Each is found by what happened rather than by where it happened, so a
    re-recording finds them again, and each is cut to the rows that make the
    situation and its outcome legible and to no others. A window that stopped
    short of the outcome would be worse than no window: the four movements a
    passed-over worker duplicated are removed before they are put back, and an
    extract ending at the removal would read as a correct migration losing
    data.
    """
    windows = {}

    def faulted(action, op=None):
        return [r for r in oplog
                if r.get("action") == action and (op is None or r.get("op") == op)]

    def key_of(record):
        return (record.get("detail") or {}).get("key") or ""

    def movements(record):
        return frozenset(record.get("keys") or [])

    def after(n, predicate):
        return next((r for r in oplog if r["n"] > n and predicate(r)), None)

    # A batch of movements, the member rows folding them, and the position
    # recorded once both are durable.
    batch = next((r for r in oplog if r.get("op") == "entry_add"
                  and r.get("action") == "proceed" and (r.get("count") or 0) > 1), None)
    if batch:
        fold = after(batch["n"], lambda r: r.get("op") == "member_put"
                     and r.get("pid") == batch.get("pid"))
        mark = after(batch["n"], lambda r: r.get("op") == "kv_set"
                     and key_of(r).endswith("checkpoint"))
        if fold and mark:
            windows[WINDOWS[0]] = [batch["n"], fold["n"], mark["n"]]

    # Two writes the store accepted and never reported the outcome of: one that
    # had committed, one that had not, and the retry of the second. The pair is
    # the evidence; neither row on its own says anything.
    committed = faulted("unknown_after_commit", "entry_add")
    lost = faulted("unknown_after_rollback", "entry_add")
    if committed and lost:
        again = after(lost[0]["n"], lambda r: r.get("op") == "entry_add"
                      and movements(r) == movements(lost[0]))
        if again:
            windows[WINDOWS[1]] = sorted({committed[0]["n"], lost[0]["n"], again["n"]})

    # A worker taken down the instant one of its writes became durable, and the
    # first two things the process that replaced it did.
    killed = faulted("kill_client_after_commit", "member_put")
    if killed:
        victim = killed[0]
        lease = after(victim["n"], lambda r: r.get("op") == "kv_cas"
                      and key_of(r).endswith("lease")
                      and r.get("pid") != victim.get("pid"))
        mark = after(victim["n"], lambda r: r.get("op") == "kv_set"
                     and key_of(r).endswith("checkpoint"))
        if lease and mark:
            windows[WINDOWS[2]] = sorted({victim["n"], lease["n"], mark["n"]})

    # Rows the ledger has no record of - one carrying a movement number the
    # ledger never issued, one a second copy of a movement it did - and what
    # the migration did about both.
    removes = [r for r in oplog if r.get("op") == "entry_remove" and r.get("applied")]
    if removes:
        cleared = removes[0]
        singles = [r["n"] for r in oplog if r["n"] < cleared["n"]
                   and r.get("op") == "entry_add" and (r.get("count") or 0) == 1
                   and movements(r) & movements(cleared)]
        if singles:
            windows[WINDOWS[3]] = sorted(set(singles) | {cleared["n"]})

    # A lease that changed hands while a write of its previous holder was still
    # in flight: the takeover, the movements the new holder had already applied,
    # the authority moving, the passed-over worker's write landing on top of
    # them, and the two writes that put the destination back to one copy each.
    leases = [r for r in oplog if r.get("op") == "kv_cas" and r.get("applied")
              and key_of(r).endswith("lease")]
    takeover, seen = None, None
    for record in leases:
        holder = json.loads((record["detail"] or {}).get("value") or "{}").get("holder")
        if seen is not None and holder != seen and takeover is None:
            takeover = record
        seen = holder
    if takeover:
        stale = after(takeover["n"], lambda r: r.get("op") == "entry_add"
                      and r.get("pid") != takeover.get("pid") and r.get("applied"))
        flip = next((r for r in oplog if r.get("op") == "meta_put"
                     and (r.get("detail") or {}).get("meta", {}).get("authority")
                     == "destination"), None)
        if stale and flip:
            already = next((r for r in oplog if r["n"] < stale["n"]
                            and r.get("op") == "entry_add"
                            and movements(r) == movements(stale)), None)
            undo = after(stale["n"], lambda r: r.get("op") == "entry_remove"
                         and movements(r) == movements(stale))
            redo = after(undo["n"] if undo else stale["n"],
                         lambda r: r.get("op") == "entry_add"
                         and movements(r) == movements(stale))
            rows = {takeover["n"], flip["n"], stale["n"]}
            rows.update(r["n"] for r in (already, undo, redo) if r)
            windows[WINDOWS[4]] = sorted(rows)

    missing = [name for name in WINDOWS if name not in windows]
    if missing:
        raise SystemExit(f"the recording does not contain: {', '.join(missing)}")
    return windows


MANIFEST = """# ap-2 cutover, archive

The membership ledger in ap-2 was moved off its legacy SQLite store and onto a
destination store by the orchestrator this service is getting. These are the
artefacts that run left behind. They were kept because the remaining regions
have the same move to make.

`deployment.yaml` is ap-2's own `config/migration.yaml`. Its numbers are ap-2's
and no other region's.

## Files

`ledger-export.jsonl`
: ap-2's legacy ledger as exported at retirement, one line per movement.
  `member_id`, `seq`, `global_seq`, `delta_cents`, `reason`, `written_at`.

`member-book.json`
: ap-2's legacy `members` table at retirement. `member_id`, `tier`,
  `balance_cents`, `version`, `deleted`.

`destination-after-shadow-copy.json`, `destination-at-authority-change.json`,
`destination-final.json`
: what the destination store held at three points: when phase one finished,
  at the instant the authority moved, and at the end. `entries` are its ledger
  rows, `members` its member rows, `record` its migration record, `status` the
  service's own `GET /admin/migration/status` where one was taken.

`migration-record-history.jsonl`
: every version of the migration record the destination store accepted, in the
  order it accepted them. `n` is the position in the store's write log, `conn`
  the connection that wrote it, `was` the record before the write and `became`
  the record after it.

`coordination-keys.jsonl`
: every accepted write to the coordination keyspace, same ordering. `key`,
  `value`, and for a compare-and-swap whether it `swapped`.

`store-write-log-extracts.jsonl`
: five short stretches of the destination store's own write log, grouped by
  `window`. `committed` is whether the store applied the write; `acknowledged`
  is whether it told the caller so. `movements` are the `member_id#seq` a write
  carried. `rows` is how many rows it carried. Positions in the ledger are not
  kept; they were particular to that run.

`dual-read-probe.json`
: one member read through the public API while the destination was still
  behind, with the ledger's own numbers for that member at that instant and
  both stores' rows for them.

`open-ledger-probe.json`
: the public API read and written again later in the same run, with the
  service's own `status` at that instant. `member_read` and `ledger_read` are
  for the member in `member_id`; `write` is an adjustment for a different
  member and the reply it got. `legacy_rows` and `destination_rows` are the
  read member's rows in each store, the destination's taken at the instant the
  authority moved; `write_member_legacy_rows` are the written member's.

`handover-turns.json`
: the same migration in a second region-wide rehearsal, carried by two workers
  through a rolling deployment, and the lease record after each turn.
"""

DEPLOYMENT_YAML = """# Deployment settings for membershipd, ap-2, as they were for the cutover.
#
# Kept with the archive because the numbers below are what the recorded run was
# driven with. They are ap-2's; every region sets its own.

listen: 127.0.0.1:8080
store_socket: /run/ledger/store.sock
legacy_path: /app/data/legacy.db
clock_file: /run/ledger/clock

shadow_boundary: {shadow_boundary}
lease_ttl_seconds: {lease_ttl_seconds}
lease_holder: membershipd-a
apply_batch_max: {apply_batch_max}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="the recorded run's artefacts")
    parser.add_argument("--out", required=True, help="where the archive is shipped")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()

    obs = load(os.path.join(args.run, "observations.json"))
    verdict = load(os.path.join(args.run, "verdict.json"))
    if not verdict.get("passed_all"):
        raise SystemExit(
            "the recording was not certified by the scorer's model: "
            f"{verdict.get('failed')}"
        )

    cutover = obs["scenarios"]["cutover"]
    handover = obs["scenarios"]["handover"]
    if cutover["config"]["shadow_boundary"] != DEPLOYMENT["shadow_boundary"]:
        raise SystemExit("the recording's boundary is not the archived deployment's")
    if cutover["config"]["lease_ttl_seconds"] != DEPLOYMENT["lease_ttl_seconds"]:
        raise SystemExit("the recording's lease lifetime is not the archived deployment's")

    oplog = cutover["oplog"]
    conns = connections(oplog)
    windows = find_windows(oplog)

    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    os.makedirs(args.out)
    made = []

    with open(os.path.join(args.out, "MANIFEST.md"), "w", encoding="utf-8") as handle:
        handle.write(MANIFEST)
    made.append("MANIFEST.md")
    with open(os.path.join(args.out, "deployment.yaml"), "w", encoding="utf-8") as handle:
        handle.write(DEPLOYMENT_YAML.format(**DEPLOYMENT))
    made.append("deployment.yaml")

    ledger = [
        {key: row[key] for key in
         ("member_id", "seq", "global_seq", "delta_cents", "reason", "written_at")}
        for row in sorted(load_jsonl(os.path.join(args.run, "truth-cutover.jsonl")),
                          key=lambda row: row["global_seq"])
    ]
    write_jsonl(os.path.join(args.out, "ledger-export.jsonl"), ledger)
    made.append("ledger-export.jsonl")

    final = cutover["checks"]["final"]
    write_json(os.path.join(args.out, "member-book.json"),
               {"members": final["legacy_book"]["members"]})
    made.append("member-book.json")

    shadow = cutover["checks"]["after_shadow_copy"]
    write_json(os.path.join(args.out, "destination-after-shadow-copy.json"), {
        "status": shadow["status"],
        "entries": shadow["destination"]["entries"],
        "members": shadow["destination"]["members"],
        "record": (shadow["destination"].get("meta") or [None])[0],
    })
    made.append("destination-after-shadow-copy.json")

    flip = cutover["checks"]["at_cutover"]
    write_json(os.path.join(args.out, "destination-at-authority-change.json"), {
        "entries": flip["destination"]["entries"],
        "members": flip["destination"]["members"],
        "record": (flip["destination"].get("meta") or [None])[0],
    })
    made.append("destination-at-authority-change.json")

    write_json(os.path.join(args.out, "destination-final.json"), {
        "status": final["status"],
        "entries": final["destination"]["entries"],
        "members": final["destination"]["members"],
        "record": (final["destination"].get("meta") or [None])[0],
    })
    made.append("destination-final.json")

    write_jsonl(os.path.join(args.out, "migration-record-history.jsonl"),
                meta_history(oplog, conns))
    made.append("migration-record-history.jsonl")
    write_jsonl(os.path.join(args.out, "coordination-keys.jsonl"),
                coordination(oplog, conns))
    made.append("coordination-keys.jsonl")

    extracts = []
    for window in sorted(windows):
        for row in extract(oplog, set(windows[window]), conns):
            row["window"] = window
            extracts.append(row)
    write_jsonl(os.path.join(args.out, "store-write-log-extracts.jsonl"), extracts)
    made.append("store-write-log-extracts.jsonl")

    probe = cutover["checks"]["dual_read_probe"]
    member = probe["member_id"]
    write_json(os.path.join(args.out, "dual-read-probe.json"), {
        "status": probe["status"],
        "member_read": probe["member_read"],
        "ledger_read": probe["ledger_read"],
        "legacy_rows": [row for row in ledger if row["member_id"] == member],
        "destination_rows": [
            {"member_id": row["member_id"], "seq": row["seq"], "global_seq": row["global_seq"]}
            for row in shadow["destination"]["entries"] if row["member_id"] == member
        ],
    })
    made.append("dual-read-probe.json")

    open_ledger = cutover["checks"]["open_ledger_probe"]
    read_member = open_ledger["member_id"]
    write_member = open_ledger["write"]["member_id"]
    write_json(os.path.join(args.out, "open-ledger-probe.json"), {
        "status": open_ledger["status"],
        "member_read": open_ledger["member_read"],
        "ledger_read": open_ledger["ledger_read"],
        "write": open_ledger["write"],
        "legacy_rows": [row for row in ledger if row["member_id"] == read_member],
        "destination_rows": [
            {"member_id": row["member_id"], "seq": row["seq"], "global_seq": row["global_seq"]}
            for row in flip["destination"]["entries"] if row["member_id"] == read_member
        ],
        "write_member_legacy_rows": [
            row for row in ledger if row["member_id"] == write_member
        ],
    })
    made.append("open-ledger-probe.json")

    lease_by_n = {row["n"]: row for row in coordination(handover["oplog"],
                                                       connections(handover["oplog"]))
                  if (row.get("key") or "").endswith("lease")}
    write_json(os.path.join(args.out, "handover-turns.json"), {
        "turns": handover["turns"],
        "lease_record_writes": [lease_by_n[n] for n in sorted(lease_by_n)],
    })
    made.append("handover-turns.json")

    print(f"archive written to {args.out}")
    for name in made:
        size = os.path.getsize(os.path.join(args.out, name))
        print(f"  {name:44s} {size:>9,d} bytes")

    if args.audit:
        print("\n--- what the extracts carry")
        for window in sorted(windows):
            print(f"  {window}: write log rows {windows[window]}")
        print("\n--- the numbers a route depends on")
        print(f"  boundary in deployment.yaml            {DEPLOYMENT['shadow_boundary']}")
        print(f"  highest global_seq copied by phase one "
              f"{max(row['global_seq'] for row in shadow['destination']['entries'])}")
        print(f"  members in the book                    {len(final['legacy_book']['members'])}")
        print(f"  of which closed                        "
              f"{sum(1 for row in final['legacy_book']['members'] if row['deleted'])}")
        print(f"  members copied by phase one            "
              f"{len(shadow['destination']['members'])}")
        print(f"  of which closed                        "
              f"{sum(1 for row in shadow['destination']['members'] if row['deleted'])}")
        print(f"  members in the destination at the end  "
              f"{len(final['destination']['members'])}")
        print(f"  of which closed                        "
              f"{sum(1 for row in final['destination']['members'] if row['deleted'])}")
        print(f"  the book moved on                      {cutover.get('book_changed')}")
        print(f"  read after the authority moved         "
              f"{open_ledger['member_read']['http_status']}, balance "
              f"{(open_ledger['member_read']['body'] or {}).get('balance_cents')}")
        print(f"  write after the authority moved        "
              f"{open_ledger['write']['http_status']}")
        print(f"  movements in the ledger export         {len(ledger)}")
        print(f"  movements in the destination at the end "
              f"{len(final['destination']['entries'])}")
        print(f"  divergence in the final record         "
              f"{final['status']['divergence_count']}")
        print(f"  record versions kept                   {len(meta_history(oplog, conns))}")
        print(f"  coordination writes kept               {len(coordination(oplog, conns))}")
        print(f"  write log rows kept                    {len(extracts)} of {len(oplog)}")


if __name__ == "__main__":
    main()
