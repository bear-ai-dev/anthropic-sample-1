#!/usr/bin/env python3
"""An independent model of the migration specification.

This is not a check of the reference solution. It is a second, separate reading
of `instruction.md` and `docs/migration-runbook.md`, written before the
reference existed and sharing no code with it. It never imports, reads or
executes anything from the workspace. It is handed three things and decides from
them alone:

  * the canonical append log, one line per committed ledger movement;
  * what the driver observed while it drove the service through its endpoints;
  * the storage service's own record of every write it performed.

Where the reference is an incremental orchestrator that carries cursors and
leases forward as it goes, this is a batch fold: it recomputes what the ledger
must contain from the log every time it needs to know, and compares multisets.
Two routes to the same answer, so a mistake on one side does not agree with a
mistake on the other. The one place it does look at order rather than at end
state is the store's write record, replayed forward, which is the only way to
ask whether a claim was made before the thing it claims was true.

Vocabulary, from the runbook:

  movement  one ledger entry, identified by (member_id, seq). The same
            (member_id, seq) seen twice is one movement, not two.
  fold      balance_cents is the sum of a member's movements' deltas and
            version is how many there are, each movement counted once
            however many rows carry it.
  prefix    the movements with global_seq at or below some boundary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter


# ------------------------------------------------------------------ the fold


def load_log(path):
    """The canonical log, as a list of movements in commit order."""
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda row: row["global_seq"])
    return rows


def movements_upto(log, boundary):
    """The movements the ledger held when its log reached `boundary`."""
    return [row for row in log if row["global_seq"] <= boundary]


def fold(movements):
    """Fold movements into per-member totals, counting each movement once."""
    seen = set()
    totals = {}
    for row in movements:
        identity = (row["member_id"], row["seq"])
        if identity in seen:
            continue
        seen.add(identity)
        entry = totals.setdefault(row["member_id"], {"balance_cents": 0, "version": 0})
        entry["balance_cents"] += row["delta_cents"]
        entry["version"] += 1
    return totals


def identities(movements):
    """Movement identities as a multiset, so duplication is visible."""
    return Counter((row["member_id"], row["seq"]) for row in movements)


def observed_identities(destination):
    return Counter((row["member_id"], row["seq"]) for row in destination.get("entries", []))


def compare_identities(expected, observed):
    """Describe how an observed multiset differs from the expected set."""
    problems = []
    duplicated = sorted(key for key, count in observed.items() if count > 1)
    if duplicated:
        problems.append(
            f"{len(duplicated)} movement(s) applied more than once, "
            f"first {duplicated[0]} seen {observed[duplicated[0]]} times"
        )
    missing = sorted(set(expected) - set(observed))
    if missing:
        problems.append(f"{len(missing)} movement(s) missing, first {missing[0]}")
    extra = sorted(set(observed) - set(expected))
    if extra:
        problems.append(f"{len(extra)} movement(s) present that the log never had, first {extra[0]}")
    return problems


def compare_fold(expected, destination, *, book=None):
    """Check the destination's member rows against the fold."""
    problems = []
    rows = {row["member_id"]: row for row in destination.get("members", [])}
    for member_id, totals in sorted(expected.items()):
        row = rows.get(member_id)
        if row is None:
            problems.append(f"member {member_id} has movements but no row in the destination")
            continue
        if row["balance_cents"] != totals["balance_cents"]:
            problems.append(
                f"member {member_id} balance {row['balance_cents']} "
                f"but the log folds to {totals['balance_cents']}"
            )
        if row["version"] != totals["version"]:
            problems.append(
                f"member {member_id} version {row['version']} "
                f"but the log has {totals['version']} movement(s)"
            )
        if len(problems) > 8:
            break
    if book is not None:
        for member_id, source in sorted(book.items()):
            row = rows.get(member_id)
            if row is None:
                problems.append(f"member {member_id} is in the member book but not the destination")
                continue
            if row["tier"] != source["tier"]:
                problems.append(f"member {member_id} tier {row['tier']!r} not {source['tier']!r}")
            if bool(row["deleted"]) != bool(source["deleted"]):
                problems.append(f"member {member_id} deleted flag does not match the book")
            if len(problems) > 8:
                break
        missing = set(book) - set(rows)
        if missing:
            problems.append(
                f"{len(missing)} member(s) never copied, including {sorted(missing)[:3]}"
            )
        # A member with no movements still has to be there, with zeroes.
        for member_id in sorted(set(book) - set(expected)):
            row = rows.get(member_id)
            if row and (row["balance_cents"] != 0 or row["version"] != 0):
                problems.append(
                    f"member {member_id} has no movements yet but holds "
                    f"{row['balance_cents']}/{row['version']}"
                )
                break
    return problems


def book_from(snapshot):
    return {
        row["member_id"]: {"tier": row["tier"], "deleted": bool(row["deleted"])}
        for row in snapshot.get("members", [])
    }


def internal_fold(destination):
    """What the destination's own member rows ought to say, given the movements
    the destination itself holds. This asks nothing of the log: it is the
    ledger invariant inside one store."""
    totals = {}
    counted = set()
    for row in destination.get("entries", []):
        identity = (row["member_id"], row["seq"])
        if identity in counted:
            continue
        counted.add(identity)
        entry = totals.setdefault(row["member_id"], {"balance_cents": 0, "version": 0})
        entry["balance_cents"] += row["delta_cents"]
        entry["version"] += 1
    return totals


def fold_disagreements(destination, limit=6):
    """Members whose row does not match the movements underneath it in the same
    store. Two writes make a movement and its fold, and this is what is left
    behind when only one of them happened."""
    inside = internal_fold(destination)
    problems = []
    for row in destination.get("members", []):
        totals = inside.get(row["member_id"], {"balance_cents": 0, "version": 0})
        if row["balance_cents"] != totals["balance_cents"] or row["version"] != totals["version"]:
            problems.append(
                f"member {row['member_id']} says "
                f"{row['balance_cents']}/{row['version']} while the movements the "
                f"destination holds for them fold to "
                f"{totals['balance_cents']}/{totals['version']}"
            )
        if len(problems) >= limit:
            break
    return problems


# ------------------------------------------------ the store's write record


def parse_key(text):
    member_id, _, seq = str(text).rpartition("#")
    if not seq.isdigit():
        return None
    return (member_id, int(seq))


def applied_meta_writes(oplog, lo=0, hi=None):
    """Every migration-record write the store actually performed."""
    out = []
    for record in oplog:
        if record.get("op") != "meta_put" or not record.get("applied"):
            continue
        position = record.get("n", 0)
        if position <= lo or (hi is not None and position > hi):
            continue
        detail = record.get("detail") or {}
        meta = detail.get("meta")
        if not meta:
            continue
        out.append(
            {
                "n": position,
                "pid": record.get("pid"),
                "phase": meta.get("phase"),
                "authority": meta.get("authority"),
                "fence": meta.get("fence"),
                "cursor": meta.get("cursor"),
            }
        )
    return out


def faulted_entry_writes(oplog, op="entry_add"):
    """The writes a fault was applied to, and what they carried."""
    out = []
    for record in oplog:
        if record.get("op") != op or not record.get("rule"):
            continue
        out.append(
            {
                "rule": record["rule"],
                "action": record.get("action"),
                "applied": bool(record.get("applied")),
                "keys": record.get("keys") or [],
                "members": record.get("members") or [],
                "global_seqs": record.get("global_seqs") or [],
            }
        )
    return out


def carried(write, log):
    """The movements a write carried, as identities the log recognises."""
    known = {(row["member_id"], row["seq"]) for row in log}
    out = []
    for key in write["keys"]:
        identity = parse_key(key)
        if identity is not None and identity in known:
            out.append(identity)
    return out


# ------------------------------------------------------------------- rules


def rule_shadow_copy(log, obs):
    """R1 The shadow copy is the member book plus the ledger prefix, once each."""
    check = obs["checks"].get("after_shadow_copy")
    if not check:
        return ["the migration never reached the end of the shadow copy"]
    boundary = obs["config"]["shadow_boundary"]
    expected = movements_upto(log, boundary)
    problems = compare_identities(identities(expected), observed_identities(check["destination"]))
    problems += compare_fold(fold(expected), check["destination"], book=book_from(check["legacy"]))
    if check["status"]["authority"] != "legacy":
        problems.append("the authority moved before the ledger had been copied")
    beyond = [
        row["global_seq"]
        for row in check["destination"].get("entries", [])
        if row["global_seq"] > boundary
    ]
    if beyond:
        problems.append(
            f"{len(beyond)} row(s) copied past the phase-one boundary {boundary}, "
            f"up to global_seq {max(beyond)}"
        )
    return problems


def served_read_problems(log, probe, when):
    """Whether what the public endpoints served for one member matches the
    ledger as it stood at that instant.

    The same question is asked at two points in the migration and the answer
    has to be the same both times, so it is asked by one piece of code. What
    differs is which store could answer it without help, and that is the
    submission's problem rather than this model's: nothing here knows or cares
    where an answer came from.
    """
    member_id = probe["member_id"]
    upto = probe["truth_upto"]
    expected = fold([row for row in movements_upto(log, upto) if row["member_id"] == member_id])
    totals = expected.get(member_id, {"balance_cents": 0, "version": 0})
    problems = []

    read = probe["member_read"]
    if read["http_status"] != 200:
        problems.append(f"reading {member_id} {when} answered {read['http_status']}")
    else:
        body = read["body"]
        if body.get("balance_cents") != totals["balance_cents"]:
            problems.append(
                f"a read {when} served {body.get('balance_cents')} for {member_id} "
                f"when the ledger stood at {totals['balance_cents']}"
            )
        if body.get("version") != totals["version"]:
            problems.append(
                f"a read {when} served version {body.get('version')} for {member_id} "
                f"when the ledger stood at {totals['version']}"
            )

    ledger = probe["ledger_read"]
    if ledger["http_status"] != 200:
        problems.append(f"reading the ledger of {member_id} {when} answered {ledger['http_status']}")
    else:
        rows = ledger["body"].get("entries") or []
        served = Counter(row["seq"] for row in rows)
        wanted = Counter(
            row["seq"] for row in movements_upto(log, upto) if row["member_id"] == member_id
        )
        repeated = sorted(seq for seq, count in served.items() if count > 1)
        if repeated:
            problems.append(
                f"the merged ledger of {member_id} {when} lists seq {repeated[0]} "
                f"{served[repeated[0]]} times"
            )
        if set(wanted) - set(served):
            problems.append(
                f"the merged ledger of {member_id} {when} is missing seq "
                f"{sorted(set(wanted) - set(served))[:3]}"
            )
        if set(served) - set(wanted):
            problems.append(
                f"the merged ledger of {member_id} {when} lists seq "
                f"{sorted(set(served) - set(wanted))[:3]} which the log never had"
            )
    return problems


def rule_dual_read(log, obs):
    """R2 A read during dual-read is fresh, and a merged ledger lists once."""
    probe = obs["checks"].get("dual_read_probe")
    if not probe:
        return ["the migration never reached dual-read"]
    if probe["adjust"]["http_status"] != 200:
        return [f"an adjustment during dual-read was rejected with {probe['adjust']['http_status']}"]
    return served_read_problems(log, probe, "during dual-read")


def rule_open_ledger_read(log, obs):
    """R13 A read is not behind the ledger after the authority has moved.

    The stretch this asks about is the one the cutover window creates and
    cannot avoid: movements reach legacy while the write naming the
    destination as the authority is still open, and more reach it before the
    drain that follows the flip has run. For that stretch the record points at
    a store that cannot yet answer for the ledger, and a caller asking what
    they are owed must still be told what the ledger holds.

    This is not R2 again at a later hour. R2's probe is taken while the record
    still names legacy, so a submission that simply reads whichever store the
    record points at passes it and fails here; and a submission can serve
    every read out of legacy until retirement, pass both, and still get the
    replay or the end state wrong.
    """
    probe = obs["checks"].get("open_ledger_probe")
    if not probe:
        return ["the ledger was never read after the authority moved"]
    if (probe.get("status") or {}).get("authority") != "destination":
        return ["the authority had not moved when the ledger was read"]
    return served_read_problems(log, probe, "after the authority moved")


def rule_open_ledger_write(log, obs):
    """R15 The ledger goes on taking movements until legacy is retired.

    The move happens with production still writing and there is no maintenance
    window, and legacy is out of the picture only once it has been retired.
    Between the authority moving and legacy being retired the ledger is
    therefore still open, and an adjustment arriving there is an ordinary
    movement rather than something to be turned away.

    Where the submission puts it is not this rule's business -- the record
    names the destination, `phases.go` says the authority is the store a
    movement is recorded in, and either store is a defensible place for it to
    land. That the movement is not lost afterwards is R10's, which reads it
    out of the canonical log like any other.
    """
    probe = obs["checks"].get("open_ledger_probe")
    if not probe:
        return ["the ledger was never written to after the authority moved"]
    if (probe.get("status") or {}).get("authority") != "destination":
        return ["the authority had not moved when the ledger was written to"]
    write = probe["write"]
    status = write["http_status"]
    if status not in (200, 201):
        return [
            f"an adjustment for {write['member_id']} made after the authority moved and "
            f"before legacy was retired was answered with {status}, so the move closed "
            "the ledger to production"
        ]
    body = write.get("body")
    if not isinstance(body, dict) or not body.get("entry"):
        return [
            "an adjustment after the authority moved was accepted without reporting the "
            "movement it made, so no caller can tell what was recorded"
        ]
    return []


def rule_restart(log, obs):
    """R3 A kill between a durable write and the next start-up costs nothing.

    A ledger movement and the member balance it belongs to are two writes, and
    the driver takes a process down on both sides of that pair: once the
    instant the movements became durable, and once the instant a member row
    did. Whichever order a submission makes them in, one of those two kills
    lands between an effect and the record of it, leaving the store holding one
    without the other and nothing anywhere saying so.

    So this is asked of the destination alone, and of every member in it rather
    than only the ones the killed write named: a submission that repairs the
    fold for the batch it is applying and no further leaves the rest behind.
    """
    check = obs["checks"].get("after_catch_up")
    if not check:
        return ["the migration never finished catching up"]
    killed = [
        write for write in faulted_entry_writes(obs["oplog"])
        if write["action"] == "kill_client_after_commit"
    ]
    folds_killed = [
        write for write in faulted_entry_writes(obs["oplog"], op="member_put")
        if write["action"] == "kill_client_after_commit"
    ]
    if not killed:
        return ["no writer was taken down mid-flight, so this was not exercised"]
    if not obs.get("restarts"):
        return ["the writer was never restarted, so recovery was not exercised"]

    destination = check["destination"]
    served = observed_identities(destination)

    problems = []
    for write in killed:
        for identity in carried(write, log):
            count = served.get(identity, 0)
            if count != 1:
                problems.append(
                    f"movement {identity}, which was durable when the writer was taken "
                    f"down, is in the destination {count} time(s) after the restart"
                )
            if len(problems) > 6:
                break

    disagreements = fold_disagreements(destination)
    if disagreements:
        named = ""
        if folds_killed:
            named = (
                " (a writer was taken down the instant a member row became durable, "
                "and the fold was never put back)"
            )
        problems += [problem + named for problem in disagreements[:4]]
    return problems


def rule_unknown_outcome(log, obs):
    """R4 A write whose outcome was never reported is applied exactly once.

    Judged at the end of the phase that made the write. A phase that reported
    itself finished while a movement it was responsible for is missing has
    guessed, and guessed wrong; so has one that wrote it twice.
    """
    faulted = faulted_entry_writes(obs["oplog"])
    ambiguous = [
        write for write in faulted
        if write["action"] in ("unknown_after_commit", "unknown_after_rollback")
    ]
    if not ambiguous:
        return ["no write had its outcome withheld, so the rule was not exercised"]
    check = obs["checks"].get("after_catch_up")
    if not check:
        return ["the migration never finished catching up"]

    served = observed_identities(check["destination"])
    problems = []
    for write in ambiguous:
        landed = "committed" if write["applied"] else "did not commit"
        for identity in carried(write, log):
            count = served.get(identity, 0)
            if count == 1:
                continue
            problems.append(
                f"movement {identity}, in a write that {landed} and was never "
                f"acknowledged, is in the destination {count} time(s)"
            )
        if len(problems) > 6:
            break
    return problems


def rule_stale_worker(log, obs):
    """R5 A worker that lost its lease does not move the migration on.

    The worker was frozen inside a ledger write and let go long after another
    worker had taken the migration off it. What it must not do afterwards is
    carry the migration: publish the record, move the phase, move the
    authority, or put the fence back. `store.Client.MetaPut` takes the record
    the write was derived from and reports whether the swap happened, which is
    the tool for exactly that, and the archived record history is an unbroken
    chain across a change of holder.

    Graded on the record, which is the migration's own account of where it is.
    What this rule used to also require -- that no data-path write by that
    worker take effect after it was let go -- is gone. See
    `rule_stale_worker_data_path_removed` below for the measurements that
    removed it.
    """
    stale = obs.get("stale")
    if not stale:
        return ["no worker was left holding a lease that had moved on"]
    problems = []
    if not stale.get("attempted"):
        problems.append("the stale worker never got as far as attempting an advance")
    if not stale.get("parked"):
        problems.append("the stale worker was never frozen inside a write")

    before, after = stale["status_before"], stale["status_after"]
    for field in ("phase", "authority"):
        if before[field] != after[field]:
            problems.append(
                f"the stale worker moved {field} from {before[field]!r} to {after[field]!r}"
            )
    if after["fence"] < before["fence"]:
        problems.append(
            f"the fence fell from {before['fence']} to {after['fence']} "
            "while a stale worker was running"
        )

    # From the moment another worker started acting under a newer lease, the old
    # one has no authority left. Anything it managed to publish after that
    # instant is a write that should have been refused.
    guard = stale["fence"]
    since = stale.get("takeover_mark") or stale["oplog_mark"]
    for write in applied_meta_writes(obs["oplog"], lo=since):
        if write["pid"] != stale["pid"]:
            continue
        problems.append(
            f"the stale worker published the migration record "
            f"({write['phase']}/{write['authority']}, fence {write['fence']}) "
            f"after the lease had moved on at fence {guard}"
        )
        break
    return problems


# Why R5 no longer grades the data path, and R6 no longer grades at all.
#
# R5's data-path facet required that no write by the passed-over worker take
# effect after it was let go, past the one it was holding. Three measurements
# retired it, and the third is the one that settles it:
#
#  1. It was the only rule eight trials failed, and they failed it the
#     same way -- record fenced, data path open. A rule that fails every
#     competent submission identically is an unrouted rule, not a hard one.
#  2. The one piece of evidence a solver has about what a passed-over worker's
#     data write costs is the archive's `a-lease-that-moved-mid-write`, and it
#     shows such a write being ACCEPTED and the holder repairing it afterwards
#     with entry_remove then entry_add. The archive demonstrates the opposite
#     of the rule: in this system a superseded worker's write lands and the
#     remedy is repair. That is a route pointing the wrong way, which is worse
#     than no route.
#  3. `alt-record-fenced-data-open` -- fence the record, leave the data path
#     open -- failed R5 and NOTHING else. R10 passes: the destination ends up
#     holding the folded ledger, every member folds, nothing is lost or
#     doubled. So the omission has no consequence anywhere in the graded run.
#     The facet scored an internal act -- which process id issued a store
#     op -- and not an outcome, against a system whose outcome was correct.
#     That candidate is now named `alt-` and expected at 1.0, because under
#     the rule above it is a correct submission rather than a wrong one.
#
# The record facet above survives all three tests. It is routed by
# `MetaPut(want, expect)` and by the archive's unbroken record chain, both of
# which demonstrate the requirement rather than a violation of it, and it has
# a consequence: `wrong-no-lease` moves the phase from CUTOVER to
# LEGACY_RETIRED under a lease it lost, and R7 does not see that.
#
# R6 asked whether the stores agreed at the instant the authority moved. It
# never graded anything: `alt-flip-without-recheck` makes exactly the mistake
# R6 was built to catch -- reconciles, then flips without confirming the
# repair still held -- and scores 1.0, because nothing arrives in the gap it
# observes. All it separated was repair completeness, and a submission holding
# an unrepaired divergence at the flip is still holding it at the end, which
# R10 fails: all four such candidates fail R10 too. Carrying it as an
# uncounted diagnostic kept a rule on the page that grades nothing, so it is
# gone rather than parked.
#
# The observation it read, `checks["at_cutover"]`, is still taken and still
# written to the observations file: it is the state the cutover committed to,
# which is the most useful thing in that file when an R10 zero is audited, and
# it is what `destination-at-authority-change.json` in the archive is cut
# from. Closing R6 as a rule needs divergence injected between a submission's
# final survey and its authority flip, deterministically, which is a new stall
# slot in the driver and a re-cut archive. Nobody should reinstate it without
# that and without a candidate that fails it alone.
rule_stale_worker_data_path_removed = True


def rule_single_cutover(log, obs):
    """R7 One fenced authority change, and the fence never falls."""
    writes = applied_meta_writes(obs["oplog"])
    if not writes:
        return ["the migration record was never written"]
    problems = []

    authority = [write["authority"] for write in writes]
    transitions = [
        (before, after)
        for before, after in zip(authority, authority[1:])
        if before != after
    ]
    forward = [t for t in transitions if t == ("legacy", "destination")]
    if len(forward) != 1:
        problems.append(
            f"the authority moved from legacy to the destination {len(forward)} time(s), "
            "and it must happen exactly once"
        )
    for before, after in transitions:
        if (before, after) != ("legacy", "destination"):
            problems.append(f"the authority moved {before!r} to {after!r}, which is not allowed")

    highest = None
    for write in writes:
        if highest is not None and write["fence"] < highest:
            problems.append(
                f"the fence fell from {highest} to {write['fence']} in the migration record"
            )
            break
        highest = write["fence"] if highest is None else max(highest, write["fence"])

    cutover = next((write for write in writes if write["authority"] == "destination"), None)
    first = writes[0]
    if cutover and cutover["fence"] <= 0:
        problems.append("the authority moved without a fence")
    if cutover and cutover["fence"] < first["fence"]:
        problems.append("the authority moved under a fence older than the record already had")
    return problems


# Every origin the driver stamps on a movement, and what R8 is entitled to
# conclude from it. R8 is the one rule whose verdict depends on WHEN a movement
# reached legacy relative to the migration's own progress, so an origin it does
# not recognise is not a wrong answer -- it is a question the model cannot
# answer. See `unrecognised_origins`.
#
#   seed        in the ledger before the migration started
#   api         written through the public endpoint while the migration ran
#   divergence  injected into legacy before the reconcile gate was judged
#   window      landed while the authority was moving: after the gate was
#               judged, with the record naming the destination still open
#   late        landed after the authority had moved and before replay began
#
# A movement injected *during* the replay would need its own origin and its own
# treatment: the submission may legitimately not carry it, because it can have
# finished scanning the log before that movement existed, and requiring it
# "exactly once" here fails a correct migration rather than making the task
# harder, so an unknown origin stops the run instead.
KNOWN_ORIGINS = frozenset(("seed", "api", "divergence", "window", "late"))

REPLAYED_ORIGINS = ("window", "late")


def unrecognised_origins(log):
    """Origins in the canonical log that no rule knows how to score."""
    return sorted({row.get("origin") for row in log} - KNOWN_ORIGINS - {None})


def rule_late_replay(log, obs):
    """R8 Writes that landed after the authority moved are applied once.

    Some of them landed while it was moving: after the gate was judged, with
    the write that names the destination still open. A cutover that treats the
    flip as instantaneous never looks for those again.

    This rule is scored only over the origins in REPLAYED_ORIGINS, which are
    the ones that had certainly reached legacy before the submission could have
    stopped looking. Widening it without widening that reasoning is how it
    starts failing correct submissions.
    """
    late = [row for row in log if row.get("origin") == "late"]
    window = [row for row in log if row.get("origin") == "window"]
    assert set(REPLAYED_ORIGINS) <= KNOWN_ORIGINS
    if not late and not window:
        return ["no writes landed after the authority moved, so replay was not tested"]
    before = obs["checks"].get("before_late_replay")
    after = obs["checks"].get("after_late_replay")
    if not after:
        return ["the migration never replayed the late writes"]

    problems = []
    if before and late:
        early = observed_identities(before["destination"])
        premature = [key for key in identities(late) if early.get(key, 0) > 0]
        if premature:
            problems.append(
                f"{len(premature)} late movement(s) were in the destination before they "
                f"had been written to legacy, first {sorted(premature)[0]}"
            )
    served = observed_identities(after["destination"])
    for row in sorted(identities(late + window)):
        count = served.get(row, 0)
        if count != 1:
            kind = "in-flight" if row in identities(window) else "late"
            problems.append(f"{kind} movement {row} is in the destination {count} time(s)")
        if len(problems) > 6:
            break
    return problems


def rule_retirement(log, obs):
    """R9 Legacy is out of the read path, and legacy's write path is shut.

    Both halves of that are the prompt's: once legacy is retired nothing reads
    it and its write path is closed. Neither half is a statement about the
    destination, and this rule used to make one -- it required the ledger to
    refuse an adjustment outright after retirement, and counted a movement
    reaching the destination as a violation.

    Nothing a solver can read says that. `phases.go` says the authority names
    the store a ledger movement is "recorded in", so after the cutover the
    destination is the live write path, and the graded run accepts writes
    landing there before retirement (R8 is scored over exactly those). A
    submission that goes on serving adjustments out of the destination once
    legacy is gone is reading the workspace, not ignoring it, and it was being
    failed for the reading. Independent solvers do not converge on
    dest-write-close, so it was oracle-internal and it is gone.

    What is left is checkable against the prompt alone: a read after retirement
    must not come from legacy, and a movement must not reach legacy.
    """
    check = obs["checks"].get("after_retire")
    if not check:
        return ["the migration never retired legacy"]
    problems = []

    read = check["member_read"]
    poison = check["poison"]
    expected = fold([row for row in log if row["member_id"] == poison["member_id"]])
    totals = expected.get(poison["member_id"], {"balance_cents": 0, "version": 0})
    if read["http_status"] != 200:
        problems.append(f"reading a member after retirement answered {read['http_status']}")
    else:
        body = read["body"]
        if body.get("balance_cents") == poison["balance_cents"]:
            problems.append(
                "a read after retirement served the value that was written straight into "
                "the legacy file, so legacy is still in the read path"
            )
        elif body.get("balance_cents") != totals["balance_cents"]:
            problems.append(
                f"a read after retirement served {body.get('balance_cents')} for "
                f"{poison['member_id']} when the ledger folds to {totals['balance_cents']}"
            )
        for field in ("member_id", "tier", "balance_cents", "version", "deleted"):
            if field not in body:
                problems.append(f"the member response lost its {field!r} field")

    # Whether the adjustment was refused or served out of the destination is
    # the submission's business. Where the movement landed is not: legacy's
    # write path is shut, so nothing may reach it.
    if check["legacy_entry_count_after"] != check["legacy_entry_count_before"]:
        problems.append(
            "an adjustment after retirement reached the legacy ledger, "
            f"which went from {check['legacy_entry_count_before']} movement(s) to "
            f"{check['legacy_entry_count_after']}, so legacy's write path is still open"
        )
    return problems


def rule_member_book(log, obs):
    """R14 The destination ends up with the ledger's member book, as it is.

    Members join, close their accounts and change tier while a migration runs,
    and none of that is a ledger movement: it appears nowhere in the append
    log and moves no balance. A migration that treats the book as something
    copied once at the start therefore carries a book that stopped being true
    somewhere in the middle, and nothing about the ledger says so.

    Kept apart from R10 deliberately. R10 asks what the destination holds
    about the *ledger* and every data-path mistake lands in it; this asks what
    it holds about the *membership*, and a submission can get either right
    with the other wrong.
    """
    check = obs["checks"].get("final")
    if not check:
        return ["the migration never completed"]
    book = book_from(check["legacy_book"])
    rows = {row["member_id"]: row for row in check["destination"].get("members", [])}
    totals = fold(log)
    problems = []

    for member_id, source in sorted(book.items()):
        row = rows.get(member_id)
        if row is None:
            problems.append(f"member {member_id} is in the member book but not the destination")
        else:
            if row["tier"] != source["tier"]:
                problems.append(
                    f"member {member_id} is {row['tier']!r} in the destination and "
                    f"{source['tier']!r} in the member book"
                )
            if bool(row["deleted"]) != bool(source["deleted"]):
                problems.append(
                    f"member {member_id} is "
                    f"{'closed' if source['deleted'] else 'open'} in the member book and "
                    f"{'closed' if row['deleted'] else 'open'} in the destination"
                )
            if member_id not in totals and (row["balance_cents"] != 0 or row["version"] != 0):
                problems.append(
                    f"member {member_id} has no movements yet but holds "
                    f"{row['balance_cents']}/{row['version']} in the destination"
                )
        if len(problems) > 6:
            break

    strangers = sorted(set(rows) - set(book))
    if strangers:
        problems.append(
            f"{len(strangers)} member(s) in the destination that the book never had, "
            f"first {strangers[0]}"
        )
    return problems


def rule_final_state(log, obs):
    """R10 The destination holds the whole ledger, folded, and says so.

    Scored over the ledger alone. What the destination says about the
    membership -- who is in it, their tier, whether they are closed -- is
    R14's, so that a book left behind and a ledger left behind are two
    failures and not one.
    """
    check = obs["checks"].get("final")
    if not check:
        return ["the migration never completed"]
    problems = compare_identities(identities(log), observed_identities(check["destination"]))
    problems += compare_fold(fold(log), check["destination"])

    status = check["status"]
    if status["phase"] != "COMPLETE":
        problems.append(f"the migration finished in phase {status['phase']!r}, not COMPLETE")
    if status["authority"] != "destination":
        problems.append(f"the authority ended up as {status['authority']!r}")
    if status["divergence_count"] != 0:
        problems.append(f"the migration reports {status['divergence_count']} divergence(s) left")
    return problems


def rule_progress_order(log, obs):
    """R11 No progress is recorded that the destination cannot back.

    Replayed from the store's own record of its writes: at the instant a
    migration record naming a cursor was written, every movement at or below
    that cursor had to be in the store already. A cursor written first and
    earned afterwards is a claim about work that has not happened, and a
    restart that believes it skips that work for good. Nothing here depends on
    where a submission keeps its own checkpoint or what it looks like: the
    record's cursor is part of the status contract and it is enough.

    Only a cursor that goes past the highest one recorded so far is a claim of
    progress, and only those are judged. Re-publishing a position that was
    already earned is not a claim about new work: a worker that takes the lease
    over carries the record's cursor forward, and it has no way of knowing that
    some other worker is at that moment part-way through repairing a duplicate
    -- which the store can only do by removing the movement altogether and
    putting it back. Judging carried-forward cursors would fail that worker for
    another worker's in-flight write, which it can neither see nor prevent.
    """
    oplog = obs.get("oplog") or []
    if not oplog:
        return ["the store recorded no writes at all"]
    ordered = sorted((row["global_seq"], (row["member_id"], row["seq"])) for row in log)
    held = Counter()
    problems = []
    claims = 0
    highest = -1
    for record in oplog:
        op = record.get("op")
        if not record.get("applied"):
            continue
        if op == "entry_add":
            for text in record.get("keys") or []:
                identity = parse_key(text)
                if identity:
                    held[identity] += 1
        elif op == "entry_remove":
            for text in record.get("keys") or []:
                identity = parse_key(text)
                if identity and identity in held:
                    del held[identity]
        elif op == "meta_put":
            meta = (record.get("detail") or {}).get("meta") or {}
            cursor = meta.get("cursor")
            if cursor is None or cursor <= highest:
                continue
            highest = cursor
            claims += 1
            absent = [
                identity for position, identity in ordered
                if position <= cursor and identity not in held
            ]
            if absent:
                problems.append(
                    f"the record was written naming a cursor of {cursor} in phase "
                    f"{meta.get('phase')!r} while {len(absent)} movement(s) at or below it "
                    f"were not in the destination, first {sorted(absent)[0]}"
                )
                break
    if not claims:
        return ["the migration record never named a position, so nothing was checked"]
    return problems


# `stale_publish` is the driver's other passed-over-worker seam: a worker held
# part-way through recording a phase, let go after the other one has taken the
# migration over. Nothing grades it, and a rule was written for it here and
# then removed, because it does not separate. The measurements, so nobody
# spends the afternoon again:
#
#   wrong-r5-unfenced-write   R7 + the new rule, never the new rule alone
#   wrong-r12-lease-forfeit   R12 + the new rule, never the new rule alone
#
# The reason is structural rather than a weak predicate. `store.Meta` is
# written whole -- `client.go:58-59`, "every field of it is written
# together" -- so any held publish that actually swaps rewrites `fence` to the
# value the worker held before it was parked. That is a fence going backwards,
# and R7 already fails a record whose fence falls. There is no held publish
# that lands, does damage, and leaves the fence alone, so there is no candidate
# the new rule could catch by itself.
#
# The one reading it would have caught and R7 would not is a worker that takes
# the lease AGAIN after losing it -- raising the fence -- and then publishes
# the phase it computed under the old one. That is a live trap, because R12
# requires a worker to take a free lease and carry on, so solvers are pushed
# toward re-acquiring. But the driver does not let the victim retry after the
# release here, so no observation distinguishes it. Grading it needs a retry in
# `stale_publish` and a candidate built for it; until both exist this seam
# stays an observation.


def rule_handover(log, obs):
    """R12 Whichever worker holds the lease carries the migration on.

    Two workers take turns and the deployment clock moves past the lease
    lifetime before every turn, so the lease is genuinely free and the worker
    whose turn it is genuinely takes it: this is a rolling deployment, not a
    fight. A worker that treats a lease it has lost as a lease it can never
    hold again drops out after its first turn and the other one carries
    everything, which is what this looks for.
    """
    turns = obs.get("turns")
    if not turns:
        return ["the migration was never driven across two workers"]
    moved = Counter()
    for turn in turns:
        if turn.get("died"):
            continue
        if turn.get("to") and turn.get("to") != turn.get("from"):
            moved[turn["worker"]] += 1
    problems = []
    if len(moved) < 2:
        problems.append(
            "only one of the two workers ever moved the migration on: "
            f"{dict(moved) or 'neither did'}"
        )
    for name in sorted({turn["worker"] for turn in turns}):
        if moved[name] < 2:
            problems.append(
                f"{name} moved the migration on {moved[name]} time(s) out of "
                f"{sum(1 for t in turns if t['worker'] == name)} turn(s); a worker that "
                "takes a free lease advances on its turn"
            )
    return problems


ALL = "cutover handover"
RULES = [
    ("R1", "shadow copy covers the book and the ledger prefix, once each",
     rule_shadow_copy, "cutover"),
    ("R2", "dual-read serves fresh data and merges the ledger without duplicates",
     rule_dual_read, "cutover"),
    ("R3", "a kill between a durable write and its fold costs nothing",
     rule_restart, "cutover"),
    ("R4", "a write whose outcome was withheld is applied exactly once",
     rule_unknown_outcome, "cutover"),
    ("R5", "a worker that lost its lease does not move the migration on",
     rule_stale_worker, "cutover"),
    ("R7", "one fenced authority change, and the fence never falls",
     rule_single_cutover, ALL),
    ("R8", "writes landing during and after the cutover are replayed exactly once",
     rule_late_replay, ALL),
    ("R9", "legacy leaves the read path and legacy's write path is shut",
     rule_retirement, ALL),
    ("R10", "the destination ends up holding the folded ledger",
     rule_final_state, ALL),
    ("R11", "no recorded position ever ran ahead of the store",
     rule_progress_order, ALL),
    ("R12", "whichever worker holds the lease carries the migration on",
     rule_handover, "handover"),
    ("R13", "a read after the authority moved is not behind the ledger",
     rule_open_ledger_read, "cutover"),
    ("R14", "the destination ends up with the ledger's member book, as it is",
     rule_member_book, ALL),
    ("R15", "the ledger goes on taking movements until legacy is retired",
     rule_open_ledger_write, "cutover"),
]

# Checks that would still be run and reported without deciding the reward.
#
# Deliberately empty. R6 lived here and no longer exists: an uncounted rule is
# a rule on the page that grades nothing, and the honest options were to make
# it grade something or to stop evaluating it. The reasoning and the
# measurements are beside `rule_stale_worker` above. The mechanism stays
# because a rule may need parking again, and parking is only ever a step on the
# way to one of those two answers.
DIAGNOSTIC = frozenset()


def evaluate(log, obs, scenario):
    results = {}
    for rule_id, description, check, scope in RULES:
        if scenario not in scope.split():
            continue
        try:
            problems = check(log, obs) or []
        except Exception as error:  # a model that crashes must not pass anything
            problems = [f"the model could not evaluate this rule: {error!r}"]
        results[rule_id] = {
            "description": description,
            "passed": not problems,
            "problems": problems[:10],
            "counted": rule_id not in DIAGNOSTIC,
        }
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth-dir", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.observations, encoding="utf-8") as handle:
        whole = json.load(handle)

    scenarios = whole.get("scenarios") or {}
    if not scenarios:
        verdict = {"scenarios": {}, "failed": ["no scenario ran"], "passed_all": False}
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(verdict, handle, indent=2, sort_keys=True)
        print("no scenario ran")
        return 1

    expected = {name for name, _, _, scope in
                [(r[0], r[1], r[2], r[3]) for r in RULES] for name in scope.split()}
    out = {"scenarios": {}}
    failed = []
    for name in sorted(scenarios):
        obs = scenarios[name]
        truth = os.path.join(args.truth_dir, f"truth-{name}.jsonl")
        if not os.path.exists(truth):
            out["scenarios"][name] = {"rules": {}, "failed": ["the canonical log is missing"]}
            failed.append(f"{name}/log")
            continue
        log = load_log(truth)
        strange = unrecognised_origins(log)
        if strange:
            out["harness_failure"] = (
                f"{name}: the canonical log carries movement origin(s) "
                f"{', '.join(strange)}, which no rule knows how to score. "
                "A verdict reached over them would be arbitrary."
            )
            out["scenarios"][name] = {"rules": {}, "failed": ["unscorable log"]}
            failed.append(f"{name}/origin")
            continue
        results = evaluate(log, obs, name)
        out["scenarios"][name] = {
            "movements_in_log": len(log),
            "rules": results,
            "failed": sorted(
                rule for rule, result in results.items()
                if not result["passed"] and result["counted"]
            ),
            "diagnostics_that_did_not_hold": sorted(
                rule for rule, result in results.items()
                if not result["passed"] and not result["counted"]
            ),
        }
        failed += [f"{name}/{rule}" for rule in out["scenarios"][name]["failed"]]

    # A scenario that never ran is not a pass.
    missing = sorted(expected - set(scenarios))
    if missing:
        failed += [f"{name}/absent" for name in missing]
    out["failed"] = sorted(failed)
    out["passed_all"] = not failed

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2, sort_keys=True)

    for name in sorted(out["scenarios"]):
        print(f"--- {name}")
        for rule, result in sorted(out["scenarios"][name].get("rules", {}).items()):
            state = "pass" if result["passed"] else "FAIL"
            if not result.get("counted", True):
                state += " (diagnostic, not counted)"
            print(f"{rule} {state}: {result['description']}")
            for problem in result["problems"]:
                print(f"    {problem}")
        for problem in out["scenarios"][name].get("failed", []):
            if problem not in out["scenarios"][name].get("rules", {}):
                print(f"    {problem}")
    for name in missing:
        print(f"--- {name}: never ran")
    if out.get("harness_failure"):
        print(f"HARNESS FAILURE: {out['harness_failure']}")
        return 2
    return 0 if out["passed_all"] else 1


if __name__ == "__main__":
    sys.exit(main())
