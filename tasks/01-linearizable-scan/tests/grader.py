#!/usr/bin/env python3
"""Behavioural grader for the linearizable ticket scanning task.

Everything here is observed through the service's own HTTP surface and the
database it writes to. Nothing reads the solver's source.

Reward is binary: 1.0 only when every rule passes. The split between
reward.json (numbers only) and reward-detail.json is written by write_split,
which every exit path goes through.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

API = os.environ.get("API_BASE", "http://127.0.0.1:3000")
DSN = os.environ.get("GEL_DSN_LOCAL", "gel://admin:dev@localhost:5656/main")
OUT_DIR = os.environ.get("REWARD_DIR", "/tmp/reward")
VERIFIER_DATA = os.environ.get("VERIFIER_DATA", "/opt/verifier")

EVENT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_EVENT_ID = "22222222-2222-4222-8222-222222222222"
SCAN_CODE = "DOOR42"
OTHER_SCAN_CODE = "DOOR99"
HOST = "usr-host-001"
SCANNERS = ["usr-host-001", "usr-door-1", "usr-door-2", "usr-door-3"]

sys.path.insert(0, VERIFIER_DATA)
from scan_model import Attempt, ScanModel, Ticket, ModelError  # noqa: E402


# Fixture shape, mirrored from seed.edgeql. name -> (pending, valid, owner).
# ri-0060 belongs to the other event and is deliberately absent: the model
# describes the event under test, and that ticket is graded directly.
def _fixture():
    plain = {
        "ri-0001": "usr-a01", "ri-0002": "usr-a02", "ri-0003": "usr-a03",
        "ri-0004": "usr-a03", "ri-0005": "usr-a03", "ri-0006": "usr-a04",
        "ri-0007": "usr-a04", "ri-0008": "usr-a04", "ri-0010": "usr-a06",
        "ri-0011": "usr-a07", "ri-0012": "usr-a08", "ri-0013": "usr-a09",
        "ri-0014": "usr-a10", "ri-0015": "usr-a11", "ri-0016": "usr-a11",
        "ri-0019": "usr-a13", "ri-0020": "usr-a14", "ri-0021": "usr-a15",
        "ri-0022": "usr-a15", "ri-0023": "usr-a16", "ri-0024": "usr-a17",
        "ri-0025": "usr-a18", "ri-0026": "usr-a19", "ri-0027": "usr-a20",
        "ri-0028": "usr-a21", "ri-0029": "usr-a21", "ri-0030": "usr-a21",
        "ri-0031": "usr-a22", "ri-0032": "usr-a22", "ri-0033": "usr-a22",
        "ri-0034": "usr-a23", "ri-0035": "usr-a24", "ri-0036": "usr-a24",
        "ri-0037": "usr-a24", "ri-0038": "usr-a24", "ri-0039": "usr-a25",
        "ri-0040": "usr-a25", "ri-0041": "usr-a25", "ri-0042": "usr-a26",
        "ri-0043": "usr-a26", "ri-0044": "usr-a26", "ri-0045": "usr-a27",
        "ri-0047": "usr-a27", "ri-0048": "usr-a28", "ri-0049": "usr-a29",
        "ri-0051": "usr-a30", "ri-0053": "usr-a31", "ri-0055": "usr-a32",
        "ri-0056": "usr-a32", "ri-0057": "usr-a33", "ri-0058": "usr-a34",
        "ri-0059": "usr-a35",
    }
    out = {name: (False, True, owner) for name, owner in plain.items()}
    for name, owner in (("ri-0009", "usr-a05"), ("ri-0046", "usr-a27"),
                        ("ri-0054", "usr-a31")):
        out[name] = (True, True, owner)          # pending
    for name, owner in (("ri-0017", "usr-a12"), ("ri-0018", "usr-a12"),
                        ("ri-0050", "usr-a29"), ("ri-0052", "usr-a30")):
        out[name] = (False, False, owner)        # refunded or abandoned
    return out


FIXTURE = _fixture()
SEEDED_SCAN = ("scn-0001", ("ri-0010",), HOST)

RULES = [
    "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12",
    "R13", "R14", "R15", "R16",
]


class HarnessFailure(Exception):
    """The environment could not be driven; this is not a wrong answer."""


class ScaffoldingGone(Exception):
    """The rendezvous the timing scenarios need is no longer in the request path.

    Not a harness failure on its own: the surrounding rules are still graded,
    and only a candidate that would otherwise have scored 1.0 is reported as
    unverifiable rather than as wrong.
    """


# --------------------------------------------------------------------- output

def write_split(reward, harness_failure, detail):
    """Write the numbers-only reward file and the human-readable detail file.

    Called from a finally block so a crash still produces a scored failure
    rather than silence.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    # The reward key is always present. A harness failure is not a wrong answer
    # and the flag is what says so downstream, but a file carrying the flag
    # alone is a second failure stacked on the first and it hides the first.
    numbers = {"reward": 0.0 if harness_failure else float(reward)}
    if harness_failure:
        numbers["harness_failure"] = 1
    # Belt and braces: refuse to emit anything that is not a plain number.
    clean = {}
    for k, v in numbers.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        clean[k] = v
    with open(os.path.join(OUT_DIR, "reward.json"), "w") as fh:
        json.dump(clean, fh)
        fh.write("\n")
    with open(os.path.join(OUT_DIR, "reward-detail.json"), "w") as fh:
        json.dump(detail, fh, indent=2, default=str)
        fh.write("\n")


# ------------------------------------------------------------------- plumbing

def gel(query):
    proc = subprocess.run(
        ["gel", "query", "--tls-security", "insecure", "--output-format", "json",
         "--dsn", DSN, query],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise HarnessFailure(f"gel query failed: {proc.stderr.strip()[:400]}")
    out = proc.stdout.strip()
    return json.loads(out) if out else []


def http(method, path, body=None, headers=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            if not raw.strip():
                return resp.status, {}
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                # Not every endpoint speaks JSON; the health probe does not.
                return resp.status, {"raw": raw[:400]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:400]}
    except Exception as e:  # connection refused, timeout, reset
        raise HarnessFailure(f"{method} {path}: {e}")


def payload(body):
    """Unwrap the {result, data} envelope the API uses."""
    if isinstance(body, dict) and "data" in body and isinstance(body["data"], dict):
        return body["data"]
    return body if isinstance(body, dict) else {}


def scan(user, scanner=HOST, ticket_ids=None, key=None, pass_code=None,
         event_id=EVENT_ID, timeout=90):
    """POST one scan. Returns (status, scanStatus, scanId, raw)."""
    headers = {}
    if scanner:
        headers["X-Load-Test-User-ID"] = scanner
    if key:
        headers["Idempotency-Key"] = key
    if pass_code:
        headers["PASS_CODE"] = pass_code
    body = {"eventId": event_id, "userId": user}
    if ticket_ids is not None:
        body["ticketIds"] = ticket_ids
    status, raw = http("POST", "/v2/events/hosts/scan", body, headers, timeout=timeout)
    d = payload(raw)
    return status, d.get("scanStatus"), d.get("scanId") or None, raw


def scan_may_die(*args, **kwargs):
    """A scan whose reply we expect to lose, because the process is killed.

    The request is supposed to be interrupted, so a dropped connection is the
    outcome under test rather than an environment problem.
    """
    try:
        return scan(*args, **kwargs)
    except HarnessFailure:
        return None


def admitted(result):
    """Did this response claim to have admitted the ticket(s)?"""
    if not result:
        return False
    status, scan_status, scan_id, _ = result
    return status < 400 and scan_status == "success" and bool(scan_id)


def brief(result):
    if not result:
        return None
    return {"http": result[0], "scanStatus": result[1], "scanId": result[2]}


# An event id that is well-formed and absent from the fixture. Driving the route
# with it runs the surviving lookup and stops before admission.
ABSENT_EVENT = "99999999-9999-4999-8999-999999999999"

# Signatures of the store being unreachable rather than the code being wrong.
# These name the Gel client's own failure modes: the solver does not write this
# layer, and the surviving lookup that emits them runs before any code they do
# write.
INFRA_MARKERS = (
    "clientconnectiontimeout",
    "clientconnectionfailed",
    "clientconnectionclosed",
    "i/o timeout",
    "connection refused",
    "connection reset",
)


def infra_fault(raw):
    """Does this response body say the store was unreachable?

    A wrong implementation and an unreachable database can both answer 500, and
    calling the second one a wrong answer is how a task acquires a difficulty it
    does not have. Only the Gel client's transport failures count, and only on
    the lookup that runs before the removed code.
    """
    if not isinstance(raw, (dict, str)):
        return None
    text = (raw if isinstance(raw, str) else json.dumps(raw)).lower()
    if "gel" not in text:
        return None
    for marker in INFRA_MARKERS:
        if marker in text:
            return marker
    return None


# A member of door staff who holds no ticket. Scanning them runs the whole
# request path up to the point where it discovers there is nothing to admit.
NOBODY = "usr-door-1"

# The widest rendezvous any scenario arms. The warm-up opens at least this many
# connections at once, so the race is not also the first time the service is
# asked to do several things at the same moment.
WARM_WIDTH = 12


def warm_up(detail, budget=180):
    """Drive the route until it answers promptly, alone and in parallel.

    Every lookup in front of the removed code carries its own few-second
    deadline. Those are generous for a warm service and not generous at all for
    a cold one: the first request through compiles its queries, and on a slow or
    loaded host that can take longer than the deadline allows. A request that
    dies there never reaches the rendezvous, and a rendezvous that does not fill
    is a concurrency scenario that did not happen.

    That failure is worse than it looks. If several racers are picked off before
    the checkpoint, the survivors do not overlap, and a submission with no
    interlock at all would admit exactly once and look correct. The grader
    refuses to score a rendezvous that did not fill for exactly that reason --
    so paying the warm-up cost here is what lets the concurrency rules be
    graded rather than skipped.

    Two phases. First one request at a time until the store answers at all;
    then WARM_WIDTH of them at once, because a pool that has served one caller
    is not a pool that has served twelve.
    """
    w = detail.setdefault("warm_up", {})
    deadline = time.time() + budget
    attempts, last = 0, None
    while time.time() < deadline:
        attempts += 1
        try:
            _, _, _, raw = scan("usr-a01", event_id=ABSENT_EVENT, timeout=30)
        except HarnessFailure as e:
            last = str(e)
            time.sleep(1)
            continue
        last = infra_fault(raw)
        if last is None:
            break
        time.sleep(1)
    else:
        w.update(attempts=attempts, settled=False, last=last)
        raise HarnessFailure(
            f"the store never answered the event lookup within {budget}s "
            f"({attempts} attempts, last: {last}); grading would measure the "
            f"environment rather than the submission")
    w.update(attempts=attempts, settled=True)

    rounds, faults = 0, None
    while time.time() < deadline:
        rounds += 1
        results, errors = parallel([
            (lambda i=i: scan(NOBODY, scanner=SCANNERS[i % len(SCANNERS)], timeout=30))
            for i in range(WARM_WIDTH)])
        faults = [infra_fault(x[3]) for x in results if x] + [e for e in errors if e]
        faults = [f for f in faults if f]
        if not faults:
            w.update(parallel_rounds=rounds, parallel_settled=True)
            return
        time.sleep(2)
    w.update(parallel_rounds=rounds, parallel_settled=False, last=faults)
    raise HarnessFailure(
        f"the store never served {WARM_WIDTH} callers at once within {budget}s "
        f"(last: {faults}); the concurrency scenarios could not have been "
        f"driven, so no verdict is possible")


# ------------------------------------------------------------ coordination

class Coord:
    """Drives the in-process rendezvous the workspace exposes for tests."""

    def __init__(self):
        self.notes = []

    def _post(self, path, body):
        try:
            status, raw = http("POST", "/internal/task/coord" + path, body, timeout=30)
        except HarnessFailure as e:
            raise HarnessFailure(f"coordination endpoint {path} unreachable: {e}")
        if status >= 400:
            raise HarnessFailure(f"coordination endpoint {path} answered {status}")
        return raw

    def arm(self, name, parties, hold=False, timeout_ms=30000):
        return self._post("/arm", {"name": name, "parties": parties,
                                   "hold": hold, "timeoutMs": timeout_ms})

    def release(self, name):
        return self._post("/release", {"name": name})

    def reset(self):
        return self._post("/reset", {})

    def status(self, name):
        try:
            _, raw = http("GET", f"/internal/task/coord/status?name={name}", timeout=30)
        except HarnessFailure as e:
            raise HarnessFailure(f"coordination status unreachable: {e}")
        return raw if isinstance(raw, dict) else {}

    def wait_arrived(self, name, n, budget=90):
        """Poll until n parties have reached the checkpoint. Never sleeps blind."""
        deadline = time.time() + budget
        while time.time() < deadline:
            if int(self.status(name).get("arrived") or 0) >= n:
                return True
            time.sleep(0.05)
        return False

    def hold_one(self, name, fn, budget=90):
        """Run fn in a thread and return once it is parked at the checkpoint.

        Returns (thread, holder, reached). The caller mutates whatever state it
        wants to change mid-flight, then releases.
        """
        self.arm(name, 1, hold=True, timeout_ms=120000)
        holder = {}

        def body():
            holder["r"] = fn()

        t = threading.Thread(target=body)
        t.start()
        reached = self.wait_arrived(name, 1, budget=budget)
        return t, holder, reached


def parallel(fns):
    """Run callables concurrently and return their results in order."""
    results = [None] * len(fns)
    errors = [None] * len(fns)

    def runner(i, fn):
        try:
            results[i] = fn()
        except Exception as e:  # noqa: BLE001 - recorded, not swallowed
            errors[i] = repr(e)

    threads = [threading.Thread(target=runner, args=(i, f)) for i, f in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


# ------------------------------------------------------------ store readers

def store_history():
    """scan history per receipt item, straight from the database."""
    rows = gel("select ReceiptItem { firestore_id, scans } order by .firestore_id")
    return {r["firestore_id"]: list(r.get("scans") or []) for r in rows}


def store_scan_ids():
    rows = gel("select Scan { scan_id }")
    return [r["scan_id"] for r in rows]


def store_scan_rows():
    rows = gel("select Scan { scan_id, purchased_ticket_ids,"
               " scanner := .scanner_user.firestore_id }")
    return {r["scan_id"]: {"items": sorted(r.get("purchased_ticket_ids") or []),
                           "scanner": r.get("scanner")}
            for r in rows}


def store_num_scanned():
    rows = gel(
        "with event := (select Event filter .firestore_id = '%s' and not .deleted limit 1),"
        " valid := (select ReceiptItem filter .event = event and not .pending"
        " and .refund_status != RefundStatus.refunded and not .abandoned)"
        " select { n := count((select valid filter len(.scans ?? <array<str>>[]) > 0)),"
        " total := count(valid) }" % EVENT_ID
    )
    return rows[0]["n"], rows[0]["total"]


def store_attendees_with_scans(eligible_only):
    """Distinct people who hold at least one admitted ticket.

    Two populations, because the two people-counting surfaces describe two
    different things. The timeline is a record of scans as they happened and
    counts whoever was let through; scan-stats is a rate against tickets that
    were actually sold, and its own surviving doc comment excludes pending,
    refunded and abandoned. On a store where admission obeyed the rules the two
    are the same set, and asking each one its own question is what keeps R8
    measuring the projections rather than re-reporting a broken R1 or R6.
    """
    valid = (" and not .pending and .refund_status != RefundStatus.refunded"
             " and not .abandoned") if eligible_only else ""
    rows = gel(
        "with event := (select Event filter .firestore_id = '%s' and not .deleted limit 1),"
        " scanned := (select ReceiptItem filter .event = event%s"
        " and len(.scans ?? <array<str>>[]) > 0)"
        " select count(distinct scanned.persona_event.persona[is User].firestore_id)"
        % (EVENT_ID, valid)
    )
    return rows[0] if rows else 0


def set_scan_code(code, event_id=EVENT_ID):
    gel("update Event filter .firestore_id = '%s' set { scan_code := '%s' }"
        % (event_id, code))


def set_privilege(persona_event, privilege):
    gel("update PersonaEvent filter .firestore_id = '%s' set"
        " { privilege := PersonaEventPrivilege.%s }" % (persona_event, privilege))


def drop_privilege_row(persona_event):
    gel("delete PersonaEvent filter .firestore_id = '%s'" % persona_event)


# ------------------------------------------------------------------ scenarios

def build_model():
    tickets = {}
    for name, (pending, valid, owner) in FIXTURE.items():
        tickets[name] = Ticket(pending=pending, valid=valid, owner=owner)
    model = ScanModel(tickets)
    sid, items, scanner = SEEDED_SCAN
    for item in items:
        model.tickets[item].history.append(sid)
    model.seed_scan(sid, items, scanner)
    return model


def untouched(hist, names):
    return all(hist.get(n, []) == [] for n in names)


def disjoint_winners_ok(results, batches, hist_before, hist_after):
    """The legality test for a set of simultaneous, partially overlapping scans.

    Permitted: any set of winners whose ticket sets do not intersect. Each
    winner's whole batch must carry its reference and nothing else may have
    moved. Whether any of them won at all is not constrained: an
    implementation that refuses everything under contention is slow, not
    wrong.
    """
    problems = []
    winners = [(i, r) for i, r in enumerate(results) if admitted(r)]
    claimed = set()
    for i, r in winners:
        items = batches[i]
        if claimed & set(items):
            problems.append(f"batch {i} admitted tickets another winner also admitted")
        claimed |= set(items)
        for name in items:
            if hist_after.get(name, []) != [r[2]]:
                problems.append(
                    f"batch {i} reported {r[2]} but {name} holds "
                    f"{hist_after.get(name, [])}")
    for name in {n for b in batches for n in b}:
        before, after = hist_before.get(name, []), hist_after.get(name, [])
        if name in claimed:
            continue
        if after != before:
            problems.append(f"{name} moved from {before} to {after} with no winner claiming it")
    return problems


def run(detail):
    """Drive every scenario. Returns a dict of rule -> bool."""
    # None until the scenarios behind a rule have actually run. The difference
    # between "this rule failed" and "we never got to this rule" is what lets a
    # missing rendezvous be reported as unverifiable instead of as wrong.
    rules = {r: None for r in RULES}
    detail["rules"] = rules
    ev = detail.setdefault("scenarios", {})
    coord = Coord()
    model = build_model()
    contradictions = []
    # scan id -> the staff member we expect the store to attribute it to, or
    # None when the door code authorised it and no person was named.
    attributed = {SEEDED_SCAN[0]: SEEDED_SCAN[2]}

    def record(attempt, result):
        """Feed one attempt to the model, surviving a contradiction.

        A ModelError means the service reported something the specification
        forbids outright. That is a definite failure, but the remaining
        scenarios are still worth running for the report, so it is collected
        rather than raised.
        """
        won = bool(result) and admitted(result)
        sid = result[2] if result else None
        if won and sid:
            attributed[sid] = attempt.scanner
        try:
            model.apply(attempt, won, sid)
        except ModelError as e:
            contradictions.append(str(e))

    warm_up(detail)
    coord.reset()

    # -- S0: baseline projection ------------------------------------------
    n0, total0 = store_num_scanned()
    ev["baseline"] = {"numScanned": n0, "totalTickets": total0}
    if (n0, total0) != (model.expected_num_scanned(), model.expected_total_tickets()):
        raise HarnessFailure(
            f"fixture is not in its expected starting state: got {(n0, total0)}, "
            f"expected {(model.expected_num_scanned(), model.expected_total_tickets())}")

    # -- S1: a single admission, which also confirms the seam --------------
    r = scan("usr-a01")
    ev["single_admit"] = brief(r)
    hist = store_history()
    seam_ok = bool(hist.get("ri-0001"))
    ev["seam_resolved"] = seam_ok
    record(Attempt("solo", ("ri-0001",), scanner=HOST), r)
    if not seam_ok:
        # Two very different things reach this line. If the store was
        # unreachable we cannot say anything about the submission, and a zero
        # here would read as a hard task rather than as a broken run. Anything
        # else is an implementation that does not work.
        marker = infra_fault(r[3])
        if marker is not None:
            raise HarnessFailure(
                f"the first admission failed on the store being unreachable "
                f"({marker}), not on the submission; no verdict is possible")
        ev["note"] = ("scan endpoint responded but no admission reached the store; "
                      "grading as incorrect, not as a harness failure")
        for r in RULES:
            rules[r] = False
        return rules

    single_ok = admitted(r) and hist.get("ri-0001") == [r[2]]

    # -- S2: many scanners racing for one fresh ticket ---------------------
    def race(item, user, n, label, explicit=False):
        """n scanners present one fresh ticket at the same instant.

        `explicit` names the ticket in the request rather than leaving the
        service to find the holder's only ticket, which is a different code
        path into the same decision.
        """
        coord.arm("pre-admit", n)
        results, errors = parallel([
            (lambda i=i: scan(user, scanner=SCANNERS[i % len(SCANNERS)],
                              ticket_ids=[item] if explicit else None))
            for i in range(n)])
        st = coord.status("pre-admit")
        coord.reset()
        hist = store_history()
        for i, x in enumerate(results):
            if x is None:
                continue
            record(Attempt(f"{label}{i}", (item,), group=label,
                           scanner=SCANNERS[i % len(SCANNERS)]), x)
        winner_ids = [x[2] for x in results if admitted(x)]
        ev[label] = {
            "participants": n,
            "rendezvous_arrived": st.get("arrived"),
            "rendezvous_timed_out": st.get("timedOut"),
            "reported_admits": len(winner_ids),
            "stored_history": hist.get(item, []),
            "responses": [brief(x) for x in results],
            "errors": [e for e in errors if e],
        }
        if st.get("arrived") != n:
            if not st.get("arrived"):
                raise ScaffoldingGone(
                    f"no participant reached the {label} rendezvous")
            coord.notes.append(
                f"only {st.get('arrived')} of {n} racers reached the rendezvous")
        return len(winner_ids) == 1 and hist.get(item, []) == winner_ids

    race6 = race("ri-0002", "usr-a02", 6, "race")
    race12 = race("ri-0057", "usr-a33", 12, "race_wide", explicit=True)
    rules["R2"] = race6 and race12

    # -- S3: batches -------------------------------------------------------
    #    (a) a fresh pair goes through together, under one reference
    r_pair = scan("usr-a03", ticket_ids=["ri-0003", "ri-0004"])
    record(Attempt("pair", ("ri-0003", "ri-0004"), scanner=HOST), r_pair)
    hist = store_history()
    pair = [hist.get("ri-0003", []), hist.get("ri-0004", [])]
    all_same = admitted(r_pair) and all(h == [r_pair[2]] for h in pair)

    #    (b) the same pair again plus a third, still-fresh ticket. Two members
    #        are already in, so the whole thing must be refused and the third
    #        must be left alone.
    r_trio = scan("usr-a03", ticket_ids=["ri-0003", "ri-0004", "ri-0005"])
    record(Attempt("trio", ("ri-0003", "ri-0004", "ri-0005"), scanner=HOST), r_trio)
    hist = store_history()
    third = hist.get("ri-0005", [])

    #    (c) a batch with a pending member, and a batch with a refunded one,
    #        and a batch with an abandoned one. Each has a fresh member that
    #        must survive the refusal untouched.
    stale_batches = {}
    for label, items, owner in (
            ("with_pending", ("ri-0053", "ri-0054"), "usr-a31"),
            ("with_refunded", ("ri-0049", "ri-0050"), "usr-a29"),
            ("with_abandoned", ("ri-0051", "ri-0052"), "usr-a30")):
        res = scan(owner, ticket_ids=list(items))
        record(Attempt(label, items, scanner=HOST), res)
        h = store_history()
        stale_batches[label] = {"response": brief(res),
                                "stored": [h.get(n, []) for n in items]}
        stale_batches[label]["ok"] = (not admitted(res)
                                      and untouched(h, items))

    ev["batch"] = {
        "fresh_pair": {**brief(r_pair), "stored": pair},
        "pair_plus_fresh_third": {**brief(r_trio), "stored_third": third,
                                  "stored_pair": [hist.get("ri-0003", []),
                                                  hist.get("ri-0004", [])]},
        "with_one_bad_member": stale_batches,
    }
    rules["R3"] = (not admitted(r_trio) and third == []
                   and [hist.get("ri-0003", []), hist.get("ri-0004", [])] == pair
                   and all(v["ok"] for v in stale_batches.values()))

    # One admission is recorded under exactly one reference, whether the scan
    # covered a single ticket or several.
    rules["R10"] = all_same and single_ok

    # -- S4: batches that overlap, in every shape the door can produce -----
    #    Each shape is armed so that its members are inside the decision at the
    #    same moment, and each is legal only if the winners do not intersect.
    overlap_shapes = [
        ("overlap_pair", "usr-a04",
         [("ri-0006", "ri-0007"), ("ri-0007", "ri-0008")]),
        ("overlap_chain", "usr-a24",
         [("ri-0035", "ri-0036"), ("ri-0036", "ri-0037"), ("ri-0037", "ri-0038")]),
        ("overlap_containment", "usr-a25",
         [("ri-0039", "ri-0040", "ri-0041"), ("ri-0040",)]),
        ("overlap_single_and_batches", "usr-a26",
         [("ri-0042",), ("ri-0042",), ("ri-0042", "ri-0043"), ("ri-0042", "ri-0044")]),
        # A batch that can never win because one member is pending, in flight
        # with a batch that shares its admissible member.
        ("overlap_with_pending", "usr-a27",
         [("ri-0045", "ri-0046"), ("ri-0045", "ri-0047")]),
    ]
    overlap_problems = []
    ev["overlap"] = {}
    for label, owner, batches in overlap_shapes:
        before = store_history()
        coord.arm("pre-admit", len(batches))
        results, errors = parallel([
            (lambda b=b: scan(owner, ticket_ids=list(b))) for b in batches])
        st = coord.status("pre-admit")
        coord.reset()
        after = store_history()
        for i, x in enumerate(results):
            if x is None:
                continue
            record(Attempt(f"{label}{i}", batches[i], group=label, scanner=HOST), x)
        problems = disjoint_winners_ok(results, batches, before, after)
        if label == "overlap_with_pending":
            if admitted(results[0]):
                problems.append("a batch holding a pending ticket was admitted")
            if after.get("ri-0046", []):
                problems.append("a pending ticket was admitted")
        if not st.get("arrived"):
            raise ScaffoldingGone(f"no participant reached the {label} rendezvous")
        if st.get("arrived") != len(batches):
            coord.notes.append(
                f"only {st.get('arrived')} of {len(batches)} batches reached "
                f"the {label} rendezvous")
        ev["overlap"][label] = {
            "batches": [list(b) for b in batches],
            "rendezvous_arrived": st.get("arrived"),
            "responses": [brief(x) for x in results],
            "stored": {n: after.get(n, []) for b in batches for n in b},
            "errors": [e for e in errors if e],
            "problems": problems,
        }
        overlap_problems += [f"{label}: {p}" for p in problems]
    rules["R4"] = not overlap_problems

    # -- S5: a pending ticket is never admitted ----------------------------
    before = store_history().get("ri-0009", [])
    r = scan("usr-a05")
    after = store_history().get("ri-0009", [])
    record(Attempt("pending", ("ri-0009",), scanner=HOST), r)
    ev["pending"] = {**brief(r), "stored_before": before, "stored_after": after}
    rules["R6"] = (after == [] == before) and not admitted(r) and not ev["overlap"][
        "overlap_with_pending"]["stored"].get("ri-0046")

    # -- S6: re-presenting a ticket writes nothing -------------------------
    #    (a) a ticket admitted an hour ago is a repeat, not a double-tap
    r_old = scan("usr-a06")
    hist_old = store_history().get("ri-0010", [])
    record(Attempt("repeat-old", ("ri-0010",), scanner=HOST), r_old)
    #    (b) two presentations back to back
    r1 = scan("usr-a10")
    record(Attempt("debounce1", ("ri-0014",), scanner=HOST), r1)
    r2 = scan("usr-a10")
    record(Attempt("debounce2", ("ri-0014",), scanner=HOST), r2)
    hist_db = store_history().get("ri-0014", [])
    #    (c) a batch, then one of its members alone, then the batch again
    r_b1 = scan("usr-a32", ticket_ids=["ri-0055", "ri-0056"])
    record(Attempt("batch-tap1", ("ri-0055", "ri-0056"), scanner=HOST), r_b1)
    r_b2 = scan("usr-a32", ticket_ids=["ri-0055"])
    record(Attempt("batch-tap2", ("ri-0055",), scanner=HOST), r_b2)
    r_b3 = scan("usr-a32", ticket_ids=["ri-0055", "ri-0056"])
    record(Attempt("batch-tap3", ("ri-0055", "ri-0056"), scanner=HOST), r_b3)
    hist_batch_tap = store_history()
    ev["repeat"] = {
        "hour_old": {**brief(r_old), "stored": hist_old},
        "back_to_back": {"first": brief(r1), "second": brief(r2), "stored": hist_db},
        "batch_then_member": {
            "batch": brief(r_b1), "member": brief(r_b2), "batch_again": brief(r_b3),
            "stored": [hist_batch_tap.get("ri-0055", []),
                       hist_batch_tap.get("ri-0056", [])],
        },
    }
    old_ok = (hist_old == ["scn-0001"] and not admitted(r_old)
              and (r_old[0] >= 400 or r_old[1] != "debounce"))
    db_ok = admitted(r1) and not admitted(r2) and hist_db == [r1[2]]
    batch_tap_ok = (admitted(r_b1) and not admitted(r_b2) and not admitted(r_b3)
                    and hist_batch_tap.get("ri-0055", []) == [r_b1[2]]
                    and hist_batch_tap.get("ri-0056", []) == [r_b1[2]])
    rules["R9"] = old_ok and db_ok and batch_tap_ok

    # -- S7: retrying with the same key ------------------------------------
    key = "idem-key-alpha"
    r1 = scan("usr-a07", key=key)
    record(Attempt("idem1", ("ri-0011",), idempotency_key=key, scanner=HOST), r1)
    n_before, _ = store_num_scanned()
    r2 = scan("usr-a07", key=key)
    record(Attempt("idem2", ("ri-0011",), idempotency_key=key, scanner=HOST), r2)
    r3 = scan("usr-a07", key=key)
    record(Attempt("idem3", ("ri-0011",), idempotency_key=key, scanner=HOST), r3)
    n_after, _ = store_num_scanned()
    hist_idem = store_history().get("ri-0011", [])
    ev["idempotency"] = {
        "first": brief(r1), "retry": brief(r2), "retry_again": brief(r3),
        "numScanned": [n_before, n_after], "stored": hist_idem,
    }
    rules["R5"] = (admitted(r1) and r2[2] == r1[2] and r2[0] < 400
                   and r3[2] == r1[2] and r3[0] < 400
                   and n_before == n_after and hist_idem == [r1[2]])

    # -- S8: the same key after the process is killed and restarted --------
    key2 = "idem-key-restart"
    r1 = scan("usr-a08", key=key2)
    record(Attempt("crash1", ("ri-0012",), idempotency_key=key2, scanner=HOST), r1)
    hist_before = store_history().get("ri-0012", [])
    n_before, _ = store_num_scanned()
    if not restart_api(detail, "after_first_keyed_scan"):
        raise HarnessFailure("service did not come back after restart")
    r2 = scan("usr-a08", key=key2)
    record(Attempt("crash2", ("ri-0012",), idempotency_key=key2, scanner=HOST), r2)
    hist_after = store_history().get("ri-0012", [])
    n_after, _ = store_num_scanned()
    ev["restart"] = {
        "before": {**brief(r1), "stored": hist_before, "numScanned": n_before},
        "after": {**brief(r2), "stored": hist_after, "numScanned": n_after},
    }
    rules["R11"] = (admitted(r1) and hist_before == [r1[2]]
                    and hist_after == hist_before and n_after == n_before
                    and r2[2] == r1[2] and r2[0] < 400)

    # -- S9: a key belongs to the call that took it ------------------------
    #    The same key, presented for something else, is a different request
    #    wearing somebody else's name. It replays nothing and admits nothing,
    #    and the call it does belong to stays replayable afterwards.
    binding = {}

    kb1 = "kb-single"
    b_first = scan("usr-a13", key=kb1)                       # admits ri-0019
    record(Attempt("kb1-first", ("ri-0019",), idempotency_key=kb1, scanner=HOST), b_first)
    b_other = scan("usr-a14", key=kb1)                       # ri-0020, same key
    record(Attempt("kb1-other", ("ri-0020",), idempotency_key=kb1, scanner=HOST), b_other)
    b_replay = scan("usr-a13", key=kb1)
    record(Attempt("kb1-replay", ("ri-0019",), idempotency_key=kb1, scanner=HOST), b_replay)
    h = store_history()
    binding["single"] = {
        "first": brief(b_first), "same_key_other_ticket": brief(b_other),
        "replay": brief(b_replay),
        "stored": {"ri-0019": h.get("ri-0019", []), "ri-0020": h.get("ri-0020", [])},
        "ok": (admitted(b_first) and not admitted(b_other)
               and h.get("ri-0019", []) == [b_first[2]]
               and h.get("ri-0020", []) == []
               and b_replay[0] < 400 and b_replay[2] == b_first[2]),
    }

    kb2 = "kb-batch"
    c_first = scan("usr-a15", ticket_ids=["ri-0021", "ri-0022"], key=kb2)
    record(Attempt("kb2-first", ("ri-0021", "ri-0022"), idempotency_key=kb2,
                   scanner=HOST), c_first)
    #    A subset of the original request is not the original request.
    c_subset = scan("usr-a15", ticket_ids=["ri-0021"], key=kb2)
    record(Attempt("kb2-subset", ("ri-0021",), idempotency_key=kb2, scanner=HOST), c_subset)
    #    The same tickets listed the other way round. Whether that is "the same
    #    call" is a reading rather than a fact -- nothing in the workspace says
    #    the list is a set rather than a sequence, and refusing it is the safer
    #    of the two readings, so both are accepted. What neither may do is admit
    #    anybody again or hand back a scan that is not the one this key bought.
    c_reorder = scan("usr-a15", ticket_ids=["ri-0022", "ri-0021"], key=kb2)
    record(Attempt("kb2-reorder", ("ri-0021", "ri-0022"), idempotency_key=kb2,
                   scanner=HOST), c_reorder)
    h = store_history()
    binding["batch"] = {
        "first": brief(c_first), "subset": brief(c_subset), "reorder": brief(c_reorder),
        "stored": [h.get("ri-0021", []), h.get("ri-0022", [])],
        "ok": (admitted(c_first)
               # The subset is a different call, so it is refused, and it must
               # not be answered with the original scan either.
               and not admitted(c_subset) and c_subset[2] != c_first[2]
               # Replayed with the original scan, or refused outright.
               and (c_reorder[2] == c_first[2] or not admitted(c_reorder))
               and h.get("ri-0021", []) == [c_first[2]]
               and h.get("ri-0022", []) == [c_first[2]]),
    }

    #    Two requests carrying one key at the same moment. Identical bodies are
    #    the same call twice and must collapse onto one admission; different
    #    bodies are two calls and only one of them may have the key.
    kb3 = "kb-concurrent-same"
    coord.arm("pre-admit", 2)
    same_results, same_errors = parallel([
        (lambda: scan("usr-a16", ticket_ids=["ri-0023"], key=kb3)),
        (lambda: scan("usr-a16", ticket_ids=["ri-0023"], key=kb3)),
    ])
    coord.reset()
    h = store_history()
    same_winners = [x for x in same_results if admitted(x)]
    for i, x in enumerate(same_results):
        if x is None:
            continue
        record(Attempt(f"kb3-{i}", ("ri-0023",), idempotency_key=kb3,
                       group="kb3", scanner=HOST), x)
    same_ok = (len(h.get("ri-0023", [])) == 1
               and all(x[2] == h["ri-0023"][0] for x in same_winners if x[2])
               and len({x[2] for x in same_winners}) <= 1)

    kb4 = "kb-concurrent-diff"
    coord.arm("pre-admit", 2)
    diff_results, diff_errors = parallel([
        (lambda: scan("usr-a17", ticket_ids=["ri-0024"], key=kb4)),
        (lambda: scan("usr-a18", ticket_ids=["ri-0025"], key=kb4)),
    ])
    coord.reset()
    h = store_history()
    for i, (x, item) in enumerate(zip(diff_results, ("ri-0024", "ri-0025"))):
        if x is None:
            continue
        record(Attempt(f"kb4-{i}", (item,), idempotency_key=kb4,
                       group="kb4", scanner=HOST), x)
    diff_admits = [i for i, x in enumerate(diff_results) if admitted(x)]
    diff_moved = [n for n in ("ri-0024", "ri-0025") if h.get(n, [])]
    diff_ok = len(diff_admits) <= 1 and len(diff_moved) <= 1
    if diff_admits:
        want = ("ri-0024", "ri-0025")[diff_admits[0]]
        diff_ok = diff_ok and diff_moved == [want] \
            and h.get(want, []) == [diff_results[diff_admits[0]][2]]
    else:
        diff_ok = diff_ok and not diff_moved

    binding["concurrent_same_body"] = {
        "responses": [brief(x) for x in same_results],
        "stored": h.get("ri-0023", []), "errors": [e for e in same_errors if e],
        "ok": same_ok,
    }
    binding["concurrent_different_body"] = {
        "responses": [brief(x) for x in diff_results],
        "stored": {n: h.get(n, []) for n in ("ri-0024", "ri-0025")},
        "errors": [e for e in diff_errors if e], "ok": diff_ok,
    }
    ev["key_binding"] = binding
    rules["R13"] = all(v["ok"] for v in binding.values())

    # -- S10: a key is spent only by the call that committed ---------------
    #    Three ways for a keyed call to be refused, and after each one the key
    #    must still be usable by the call that comes next.
    spending = {}

    ks1 = "ks-refused-pending"
    s_bad = scan("usr-a31", ticket_ids=["ri-0053", "ri-0054"], key=ks1)
    record(Attempt("ks1-refused", ("ri-0053", "ri-0054"), idempotency_key=ks1,
                   scanner=HOST), s_bad)
    s_good = scan("usr-a31", ticket_ids=["ri-0053"], key=ks1)
    record(Attempt("ks1-reuse", ("ri-0053",), idempotency_key=ks1, scanner=HOST), s_good)
    h = store_history()
    spending["after_a_refused_batch"] = {
        "refused": brief(s_bad), "reused": brief(s_good),
        "stored": {"ri-0053": h.get("ri-0053", []), "ri-0054": h.get("ri-0054", [])},
        "ok": (not admitted(s_bad) and admitted(s_good)
               and h.get("ri-0053", []) == [s_good[2]]
               and h.get("ri-0054", []) == []),
    }

    ks2 = "ks-refused-taken"
    taken = scan("usr-a28", ticket_ids=["ri-0048"])
    record(Attempt("ks2-first", ("ri-0048",), scanner=HOST), taken)
    s_lost = scan("usr-a28", ticket_ids=["ri-0048"], key=ks2)
    record(Attempt("ks2-lost", ("ri-0048",), idempotency_key=ks2, scanner=HOST), s_lost)
    s_next = scan("usr-a19", ticket_ids=["ri-0026"], key=ks2)
    record(Attempt("ks2-reuse", ("ri-0026",), idempotency_key=ks2, scanner=HOST), s_next)
    h = store_history()
    spending["after_losing_a_ticket"] = {
        "first": brief(taken), "refused": brief(s_lost), "reused": brief(s_next),
        "stored": {"ri-0048": h.get("ri-0048", []), "ri-0026": h.get("ri-0026", [])},
        "ok": (admitted(taken) and not admitted(s_lost) and admitted(s_next)
               and h.get("ri-0048", []) == [taken[2]]
               and h.get("ri-0026", []) == [s_next[2]]),
    }

    #    Refused for want of authorisation: the wrong door's code. The key is
    #    not spent by that either, so the same key with the right code works.
    ks3 = "ks-refused-code"
    s_wrong = scan("usr-a34", scanner=None, pass_code=OTHER_SCAN_CODE,
                   ticket_ids=["ri-0058"], key=ks3)
    record(Attempt("ks3-wrongcode", ("ri-0058",), idempotency_key=ks3,
                   authorised_at_write=False), s_wrong)
    h_mid = store_history()
    s_right = scan("usr-a34", scanner=None, pass_code=SCAN_CODE,
                   ticket_ids=["ri-0058"], key=ks3)
    record(Attempt("ks3-rightcode", ("ri-0058",), idempotency_key=ks3), s_right)
    h = store_history()
    spending["after_a_wrong_door_code"] = {
        "wrong_code": brief(s_wrong), "stored_after_wrong": h_mid.get("ri-0058", []),
        "right_code": brief(s_right), "stored": h.get("ri-0058", []),
        "ok": (not admitted(s_wrong) and h_mid.get("ri-0058", []) == []
               and admitted(s_right) and h.get("ri-0058", []) == [s_right[2]]),
    }
    ev["key_spending"] = spending
    rules["R14"] = all(v["ok"] for v in spending.values())

    # -- S11: an admission is real the moment it commits -------------------
    #    A request held between its write and its reply. The ticket is already
    #    gone as far as everyone else is concerned, and the reply that never
    #    arrived is recoverable from the key alone.
    visibility = {}

    kv1 = "kv-lost-reply"
    t, holder, reached = coord.hold_one(
        "post-admit",
        lambda: scan_may_die("usr-a20", ticket_ids=["ri-0027"], key=kv1))
    if not reached:
        coord.release("post-admit")
        t.join(timeout=120)
        coord.reset()
        raise ScaffoldingGone("no request could be held between its write and its reply")

    #    While it is parked, somebody else presents the same ticket.
    rival = scan("usr-a20", scanner="usr-door-2", ticket_ids=["ri-0027"])
    h_parked = store_history()
    committed = h_parked.get("ri-0027", [])

    #    Now lose the reply for real.
    if not restart_api(detail, "while_a_reply_was_in_flight"):
        raise HarnessFailure("service did not come back after the mid-reply restart")
    t.join(timeout=60)
    coord.reset()

    replay = scan("usr-a20", ticket_ids=["ri-0027"], key=kv1)
    h = store_history()
    #    The parked call committed, so the model is told about it even though
    #    its caller never heard. The scan id comes from the store.
    if len(committed) == 1:
        record(Attempt("kv1-committed", ("ri-0027",), idempotency_key=kv1,
                       scanner=HOST), (200, "success", committed[0], {}))
        record(Attempt("kv1-rival", ("ri-0027",), scanner="usr-door-2"), rival)
        record(Attempt("kv1-replay", ("ri-0027",), idempotency_key=kv1,
                       scanner=HOST), replay)
    visibility["lost_reply"] = {
        "rival_while_parked": brief(rival),
        "stored_while_parked": committed,
        "held": holder.get("r") and brief(holder["r"]),
        "replay_after_restart": brief(replay),
        "stored": h.get("ri-0027", []),
        "ok": (len(committed) == 1 and not admitted(rival)
               and h.get("ri-0027", []) == committed
               and replay[0] < 400 and replay[2] == committed[0]),
    }

    #    The same window around a batch, with an overlapping batch as the rival
    #    and the reply delivered rather than lost.
    kv2 = "kv-parked-batch"
    t, holder, reached = coord.hold_one(
        "post-admit",
        lambda: scan("usr-a21", ticket_ids=["ri-0028", "ri-0029"], key=kv2))
    if not reached:
        coord.release("post-admit")
        t.join(timeout=120)
        coord.reset()
        raise ScaffoldingGone("no batch could be held between its write and its reply")
    rival2 = scan("usr-a21", ticket_ids=["ri-0029", "ri-0030"])
    h_parked2 = store_history()
    coord.release("post-admit")
    t.join(timeout=120)
    coord.reset()
    held = holder.get("r")
    replay2 = scan("usr-a21", ticket_ids=["ri-0028", "ri-0029"], key=kv2)
    conflict2 = scan("usr-a21", ticket_ids=["ri-0028"], key=kv2)
    h = store_history()
    if held:
        record(Attempt("kv2-held", ("ri-0028", "ri-0029"), idempotency_key=kv2,
                       scanner=HOST), held)
        record(Attempt("kv2-rival", ("ri-0029", "ri-0030"), scanner=HOST), rival2)
        record(Attempt("kv2-replay", ("ri-0028", "ri-0029"), idempotency_key=kv2,
                       scanner=HOST), replay2)
        record(Attempt("kv2-conflict", ("ri-0028",), idempotency_key=kv2,
                       scanner=HOST), conflict2)
    visibility["parked_batch"] = {
        "rival_while_parked": brief(rival2),
        "stored_while_parked": {n: h_parked2.get(n, [])
                                for n in ("ri-0028", "ri-0029", "ri-0030")},
        "held": brief(held), "replay": brief(replay2), "conflict": brief(conflict2),
        "stored": {n: h.get(n, []) for n in ("ri-0028", "ri-0029", "ri-0030")},
        "ok": (admitted(held) and not admitted(rival2)
               and h_parked2.get("ri-0028", []) == [held[2]]
               and h_parked2.get("ri-0029", []) == [held[2]]
               and h.get("ri-0030", []) == []
               and replay2[0] < 400 and replay2[2] == held[2]),
        # conflict2 is recorded because it is worth reading beside the replay,
        # and it is deliberately not asserted here: whether a key offered for a
        # different call is refused is R13's question, and asserting it again
        # here made a key-binding defect fail R15 as well as R13. A rule that
        # cannot fail alone is a rule nobody has verified.
    }
    ev["commit_visibility"] = visibility
    rules["R15"] = all(v["ok"] for v in visibility.values())

    # -- S12: authorisation is decided where the write lands ---------------
    freshness = {}

    #    (a) the door code is rotated while an anonymous scan is in flight
    t, holder, reached = coord.hold_one(
        "pre-admit", lambda: scan("usr-a09", scanner=None, pass_code=SCAN_CODE))
    if reached:
        set_scan_code("ROTATED-999")
    coord.release("pre-admit")
    t.join(timeout=120)
    set_scan_code(SCAN_CODE)
    coord.reset()
    if not reached:
        raise ScaffoldingGone("could not hold a request before its write")
    r = holder.get("r")
    record(Attempt("auth-code", ("ri-0013",), authorised_at_write=False), r)
    freshness["code_rotated_mid_flight"] = {
        "response": brief(r), "stored": store_history().get("ri-0013", []),
        "ok": store_history().get("ri-0013", []) == [] and not admitted(r),
    }

    #    (b) a bouncer is demoted while a batch of theirs is in flight. Nothing
    #        may be admitted, and nothing may be half-admitted either.
    batch = ["ri-0031", "ri-0032", "ri-0033"]
    t, holder, reached = coord.hold_one(
        "pre-admit",
        lambda: scan("usr-a22", scanner="usr-door-2", ticket_ids=batch))
    if reached:
        set_privilege("pe-door-2", "attendee")
    coord.release("pre-admit")
    t.join(timeout=120)
    coord.reset()
    if not reached:
        set_privilege("pe-door-2", "bouncer")
        raise ScaffoldingGone("could not hold a batch before its write")
    r_demoted = holder.get("r")
    h_demoted = store_history()
    record(Attempt("auth-demoted", tuple(batch), scanner="usr-door-2",
                   authorised_at_write=False), r_demoted)
    #        Put the privilege back: the same batch must now go through whole,
    #        so a refusal that was really a permanent breakage is visible.
    set_privilege("pe-door-2", "bouncer")
    r_restored = scan("usr-a22", scanner="usr-door-2", ticket_ids=batch)
    record(Attempt("auth-restored", tuple(batch), scanner="usr-door-2"), r_restored)
    h_restored = store_history()
    freshness["bouncer_demoted_mid_batch"] = {
        "response": brief(r_demoted),
        "stored_after_demotion": [h_demoted.get(n, []) for n in batch],
        "after_restoring": brief(r_restored),
        "stored": [h_restored.get(n, []) for n in batch],
        "ok": (not admitted(r_demoted) and untouched(h_demoted, batch)
               and admitted(r_restored)
               and all(h_restored.get(n, []) == [r_restored[2]] for n in batch)),
    }

    #    (c) the same, by taking the scanner's place at the event away entirely
    #        rather than downgrading it, and with a single ticket. Another
    #        scanner who still has the right admits it afterwards.
    t, holder, reached = coord.hold_one(
        "pre-admit",
        lambda: scan("usr-a23", scanner="usr-door-3", ticket_ids=["ri-0034"]))
    if reached:
        drop_privilege_row("pe-door-3")
    coord.release("pre-admit")
    t.join(timeout=120)
    coord.reset()
    if not reached:
        raise ScaffoldingGone("could not hold a single scan before its write")
    r_dropped = holder.get("r")
    h_dropped = store_history()
    record(Attempt("auth-dropped", ("ri-0034",), scanner="usr-door-3",
                   authorised_at_write=False), r_dropped)
    r_other = scan("usr-a23", scanner="usr-door-1", ticket_ids=["ri-0034"])
    record(Attempt("auth-other-scanner", ("ri-0034",), scanner="usr-door-1"), r_other)
    h_other = store_history()
    freshness["scanner_removed_mid_flight"] = {
        "response": brief(r_dropped), "stored_after_removal": h_dropped.get("ri-0034", []),
        "other_scanner": brief(r_other), "stored": h_other.get("ri-0034", []),
        "ok": (not admitted(r_dropped) and h_dropped.get("ri-0034", []) == []
               and admitted(r_other) and h_other.get("ri-0034", []) == [r_other[2]]),
    }
    ev["freshness"] = freshness
    rules["R12"] = all(v["ok"] for v in freshness.values())

    # -- S13: tickets that must never come through this door ----------------
    never = {}
    #    A refunded ticket and an abandoned one, presented together.
    r_invalid = scan("usr-a12", ticket_ids=["ri-0017", "ri-0018"])
    record(Attempt("invalid", ("ri-0017", "ri-0018"), scanner=HOST), r_invalid)
    #    A two-ticket holder whose tickets are listed and never selected.
    r_preview = scan("usr-a11")
    record(Attempt("preview", ("ri-0015", "ri-0016"), scanner=HOST), r_preview)
    #    Somebody else's event's ticket, presented at this door.
    r_foreign = scan("usr-a36", ticket_ids=["ri-0060"])
    foreign_rows = gel("select ReceiptItem { scans } filter .firestore_id = 'ri-0060'")
    hist = store_history()
    never["refunded_and_abandoned"] = {
        **brief(r_invalid),
        "stored": [hist.get("ri-0017", []), hist.get("ri-0018", [])],
        "ok": not admitted(r_invalid) and untouched(hist, ("ri-0017", "ri-0018")),
    }
    never["listed_but_not_selected"] = {
        **brief(r_preview),
        "stored": [hist.get("ri-0015", []), hist.get("ri-0016", [])],
        "ok": not admitted(r_preview) and untouched(hist, ("ri-0015", "ri-0016")),
    }
    never["another_events_ticket"] = {
        **brief(r_foreign),
        "stored": (foreign_rows[0].get("scans") if foreign_rows else None),
        "ok": (not admitted(r_foreign) and bool(foreign_rows)
               and not (foreign_rows[0].get("scans") or [])),
    }
    #    And the one that must: an anonymous scan carrying this door's code.
    r_code = scan("usr-a35", scanner=None, pass_code=SCAN_CODE)
    record(Attempt("door-code", ("ri-0059",)), r_code)
    hist = store_history()
    never["this_doors_code_admits"] = {
        **brief(r_code), "stored": hist.get("ri-0059", []),
        "ok": admitted(r_code) and hist.get("ri-0059", []) == [r_code[2]],
    }
    ev["never_admit"] = never
    rules["R1"] = all(v["ok"] for v in never.values())

    # -- S14: what each stored scan says about itself ------------------------
    #    A scan names the staff member who made it and the tickets it admitted.
    #    Where the door code authorised the scan there is nobody to name, and
    #    the schema says so, so those are only checked for their tickets.
    hist = store_history()
    rows = store_scan_rows()
    by_scan = {}
    for name, ids in hist.items():
        for sid in ids:
            by_scan.setdefault(sid, set()).add(name)
    attribution_problems = []
    for sid, items in sorted(by_scan.items()):
        row = rows.get(sid)
        if row is None:
            attribution_problems.append(f"{sid} is referenced but not stored")
            continue
        if row["items"] != sorted(items):
            attribution_problems.append(
                f"{sid} says it admitted {row['items']} but holds {sorted(items)}")
        want = attributed.get(sid, "unknown")
        if want == "unknown":
            attribution_problems.append(f"{sid} was written by nothing the harness asked for")
        elif want is not None and row["scanner"] != want:
            attribution_problems.append(
                f"{sid} was made by {want} but records {row['scanner']}")
    ev["attribution"] = {"scans": rows, "expected_scanner": attributed,
                         "problems": attribution_problems}
    rules["R16"] = not attribution_problems

    # -- S15: projections and store integrity ------------------------------
    n_final, total_final = store_num_scanned()
    scan_rows = store_scan_ids()

    st_code, st_raw = http("GET", f"/v2/events/hosts/scanstatus?eventId={EVENT_ID}",
                           headers={"X-Load-Test-User-ID": HOST})
    st_body = payload(st_raw)
    an_code, an_raw = http("GET", f"/v2/events/hosts/scan-analytics?eventId={EVENT_ID}",
                           headers={"X-Load-Test-User-ID": HOST})
    an_body = payload(an_raw)
    timeline = an_body.get("timeline") or []
    cumulative = timeline[-1]["peopleScannedCumulative"] if timeline else 0
    ss_code, ss_raw = http("GET", f"/v2/events/hosts/scan-stats?eventId={EVENT_ID}",
                           headers={"X-Load-Test-User-ID": HOST})
    ss_body = payload(ss_raw)

    attendees_in_store = store_attendees_with_scans(eligible_only=False)
    eligible_attendees_in_store = store_attendees_with_scans(eligible_only=True)

    referenced = set()
    for ids in hist.values():
        referenced.update(ids)
    orphans = sorted(set(scan_rows) - referenced)
    dangling = sorted(referenced - set(scan_rows))
    duplicate_rows = len(scan_rows) != len(set(scan_rows))

    ev["projections"] = {
        "scanstatus": {"http": st_code, "numScanned": st_body.get("numScanned"),
                       "totalTickets": st_body.get("totalTickets")},
        "store": {"numScanned": n_final, "totalTickets": total_final},
        "analytics": {"http": an_code, "cumulative": cumulative,
                      "buckets": len(timeline)},
        "scanstats": {"http": ss_code,
                      "scannedPeople": ss_body.get("scannedPeople"),
                      "expectedAttendees": ss_body.get("expectedAttendees")},
        "attendees_in_store": attendees_in_store,
        "eligible_attendees_in_store": eligible_attendees_in_store,
        "model_unique_attendees": model.expected_unique_attendees(),
        "orphan_scan_rows": orphans,
        "dangling_scan_references": dangling,
        "duplicate_scan_rows": duplicate_rows,
    }

    # R7 is about the projection telling the truth about the store, and about
    # the ticket population not being quietly altered to make it do so.
    rules["R7"] = (st_code == 200
                   and st_body.get("numScanned") == n_final
                   and st_body.get("totalTickets") == total_final
                   == model.expected_total_tickets())
    # R8 is about references resolving and the two people-counting surfaces
    # agreeing with the store. They count people where scanstatus counts
    # tickets, so a batch admitted under one scan separates them: getting both
    # right at once constrains how an admission is recorded.
    #
    # Each surface is held to its own population, not to a single one imposed on
    # both. A submission that admits a refunded ticket puts the store in a state
    # the rules say cannot happen; the two surfaces then describe it differently
    # and both correctly, and holding them to one count fails R8 as well as R1.
    # That is one rule reporting another's defect, and a rule that cannot fail on
    # its own is a rule nothing has verified.
    #
    # expectedAttendees is recorded but not graded. The field name says people
    # and the surviving doc comment beside it says "valid tickets issued", and
    # the fixture has holders of several tickets, so the two readings give
    # different numbers with nothing in the workspace to settle which is meant.
    # Grading it would be grading a coin flip rather than the behaviour.
    rules["R8"] = (an_code == 200 and ss_code == 200
                   and not orphans and not dangling and not duplicate_rows
                   and cumulative == attendees_in_store
                   and ss_body.get("scannedPeople") == eligible_attendees_in_store)

    # The model comparison is a backstop rather than a rule of its own: every
    # way to diverge from it is already owned by the rule governing the path
    # that diverged. It is recorded so a run that scores 1.0 while disagreeing
    # with the model is visible rather than silent.
    model_hist = model.expected_history()
    ev["final_state"] = {
        "contradictions": contradictions,
        "model_violations": model.violations(),
        "mismatches_vs_model": {k: {"store": hist.get(k, []), "model": v}
                                for k, v in model_hist.items()
                                if hist.get(k, []) != v},
        "items_with_multiple_admissions": {k: v for k, v in hist.items()
                                           if len(v) > 1},
    }

    detail["coordination_notes"] = coord.notes
    return rules


def port_open(host="127.0.0.1", port=3000):
    import socket
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def restart_api(detail=None, why=""):
    """Kill the service outright and bring it back, polling for readiness.

    The kill matches on the executable name rather than a command-line
    fragment, because a -f pattern also matches the shell that is running the
    pkill and takes it down mid-way.
    """
    marks = {"why": why}
    t0 = time.time()
    subprocess.run(["pkill", "-9", "-x", "ExampleCo-backend"], check=False)

    deadline = time.time() + 60
    while time.time() < deadline and port_open():
        time.sleep(0.1)
    marks["died_after_s"] = round(time.time() - t0, 2)
    if port_open():
        if detail is not None:
            detail.setdefault("restart_timing", []).append(marks)
        return False

    # Launched twice if need be. On a badly loaded host the service can fail to
    # be seen coming back, which records a harness failure instead of the wrong
    # answer it was, where the same run repeated cleanly.
    # A relaunch costs a few seconds and the alternative is
    # losing a verdict to whatever else the box was doing. The relaunch is only
    # reached if the port is still free, so it cannot end up racing a survivor.
    marks["launches"] = 0
    for attempt in range(2):
        if attempt and port_open():
            break
        # No setsid here: start_new_session already detaches the child, and
        # wrapping it in one meant the thing being waited on was setsid, which
        # forks the service and exits immediately. Watching that exit and
        # concluding the service had died turned a live restart into a harness
        # failure inside a second.
        subprocess.Popen(
            ["/workspace/bin/ExampleCo-backend"],
            cwd="/workspace",
            stdout=open("/var/log/task/api.log", "ab"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        marks["launches"] += 1
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                code, _ = http("GET", "/", timeout=3)
                if code == 200:
                    marks["up_after_s"] = round(time.time() - t0, 2)
                    if detail is not None:
                        detail.setdefault("restart_timing", []).append(marks)
                    return True
            except HarnessFailure:
                pass
            time.sleep(0.25)
    marks["up_after_s"] = None
    if detail is not None:
        detail.setdefault("restart_timing", []).append(marks)
    return False


def main():
    detail = {"task": "01-linearizable-scan", "started": time.time()}
    reward = 0.0
    harness_failure = 0
    try:
        rules = run(detail)
        reward = 1.0 if all(rules.get(r) is True for r in RULES) else 0.0
        detail["failed_rules"] = [r for r in RULES if rules.get(r) is not True]
    except HarnessFailure as e:
        harness_failure = 1
        detail["harness_failure"] = str(e)
    except ScaffoldingGone as e:
        # The rendezvous the timing scenarios drive is not in the request path
        # any more, so those scenarios cannot be run at all. Anything already
        # decided still decides the verdict; if nothing had failed yet there is
        # no verdict to reach and saying so beats inventing one.
        rules = detail.get("rules") or {}
        already = [r for r in RULES if rules.get(r) is False]
        detail["scaffolding_removed"] = str(e)
        detail["failed_rules"] = already
        if already:
            reward = 0.0
        else:
            harness_failure = 1
            detail["harness_failure"] = (
                f"{e}; the concurrency and timing scenarios could not be driven")
    except ModelError as e:
        # The system claimed something the specification forbids outright.
        detail["model_error"] = str(e)
        reward = 0.0
    except Exception as e:  # noqa: BLE001
        harness_failure = 1
        detail["harness_failure"] = f"unexpected grader error: {e!r}"
        import traceback
        detail["traceback"] = traceback.format_exc()
    finally:
        detail["finished"] = time.time()
        write_split(reward, harness_failure, detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
