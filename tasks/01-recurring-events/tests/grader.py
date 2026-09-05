#!/usr/bin/env python3
"""Behavioural grader for the recurring-events task.

Everything here is decided by driving the HTTP surface and then reading the
store, and comparing what is there against an independent model of the
specification. The model shares no code with the reference implementation and
does not take the same route to an answer; see recurrence_model.py. Nothing is
compared against the reference's source, so a candidate that reaches the right
occurrence list by other means passes, which is the point.

Layout of a rule: each `rule_*` function returns a list of complaint strings.
Empty means the rule holds. Reward is 1.0 only when every rule holds and 0.0
otherwise -- these are not independent features to be scored separately, they
are one specification, and a series that is right about daylight saving and
wrong about who owns a local date is simply wrong. The detail file names every
rule that failed and why, so a partial result is still legible without being
worth anything.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import datetime as dt
import subprocess
from zoneinfo import ZoneInfo

VERIFIER_DATA = os.environ.get("VERIFIER_DATA", "/tests/verifier-data")
sys.path.insert(0, VERIFIER_DATA)
import recurrence_model as model  # noqa: E402

API = "http://127.0.0.1:3000"
GEL_DSN = os.environ.get("GEL_DSN", "gel://admin:dev@localhost:5656/main")
REWARD_DIR = os.environ.get("REWARD_DIR", "/logs/verifier")

ORG = "org-series-001"
MANAGER = "usr-series-mgr"

UTC = dt.timezone.utc


# --------------------------------------------------------------------- plumbing

def http(method, path, body=None, headers=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Load-Test-User-ID", MANAGER)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:  # connection refused, reset, timeout
        return 0, str(e)


def api_json(method, path, body=None, headers=None, timeout=90):
    status, raw = http(method, path, body, headers, timeout)
    try:
        return status, json.loads(raw)
    except Exception:
        return status, {"_raw": raw[:2000]}


def eq_str(value):
    """Quote a string as an EdgeQL literal.

    This CLI build has no --variable flag, so identifiers are formatted into the
    query text. Every one of them is either a fixture name or a uuid the grader
    just read back, but quoting them properly is cheap and a stray apostrophe
    would otherwise read as a broken rule rather than a broken query.
    """
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


class StoreUnreachable(RuntimeError):
    """The database could not be reached, which is not the candidate's fault.

    Every rule here reads the store, so once the server is gone every remaining
    rule raises. Recording those as failures scores the host's health as if it
    were the submission: a correct answer collects a 0.0 with a list of rules it
    never actually failed. This exception is routed past the per-rule handler to
    `harness_failure`, so the run is discarded rather than scored.
    """


# The wording gel uses when there is no server on the other end, as opposed to a
# query it read and refused. A refused query is the candidate's problem; these
# are the machine's.
_UNREACHABLE = (
    "connection refused",
    "clientconnectionfailederror",
    "clientconnectiontimeouterror",
    "connection reset by peer",
    "temporary failure in name resolution",
    "could not connect",
)


def gel(query, _tries=3):
    """Run one EdgeQL query and return parsed JSON.

    The store is the authority for every rule here. Grading the HTTP response
    body instead would let a candidate that returns a correct-looking payload
    without persisting it pass, and persistence is most of what the task is.

    A connection failure is retried a bounded number of times and then raised as
    `StoreUnreachable` rather than as a rule complaint. The retry is readiness
    polling, not a sleep before an assertion: it re-establishes a connection and
    re-reads the same committed state, so it cannot turn a wrong answer into a
    right one -- only a missing server into an honest harness failure.
    """
    cmd = ["gel", "query", "--tls-security", "insecure",
           "--output-format", "json", "--dsn", GEL_DSN, query]
    last = ""
    for attempt in range(_tries):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired as e:
            raise StoreUnreachable(f"gel query timed out after 120s: {e}") from e
        if out.returncode == 0:
            return json.loads(out.stdout or "[]")
        last = out.stderr.strip()[:800]
        low = last.lower()
        if not any(m in low for m in _UNREACHABLE):
            raise RuntimeError(f"gel query failed: {last}")
        if attempt + 1 < _tries:
            time.sleep(1.0 + attempt)
    raise StoreUnreachable(f"gel unreachable after {_tries} attempts: {last}")


SERIES_QUERY = """
select EventSeries {
  series_id,
  form_data,
  repeat_config: {
    repeat_interval, repeat_unit, selected_days, timezone,
    end_type, number_of_occurrences, end_date
  },
  occurrences: {
    occurrence_id,
    date,
    date_updated,
    form_data,
    published_event: { firestore_id }
  }
} filter .series_id = %SID%
"""

# Live sales, counted the same way the specification words it: a receipt item
# that is not pending, not refunded and not abandoned. Counted per event so that
# an occurrence's protection can be looked up from its published event.
RECEIPTS_QUERY = """
select Event { firestore_id, live := count((
  select .<event[is ReceiptItem]
  filter not .pending and not .abandoned and .refund_status != RefundStatus.refunded
)) }
"""


_RECEIPTS_CACHE = {}


def live_receipts():
    """Live sales per event.

    Read once. Nothing the grader does inserts, refunds or abandons a receipt
    item -- the fixture states them and the scenarios only ever move which
    occurrence points at which event -- so this map is constant for the whole
    run, and reading it again for every series read costs a subprocess per
    scenario for an answer that cannot have changed.
    """
    if not _RECEIPTS_CACHE:
        _RECEIPTS_CACHE.update(
            {e["firestore_id"]: e["live"] for e in gel(RECEIPTS_QUERY)})
    return _RECEIPTS_CACHE


def load_series(sid):
    """Read a series out of the store into the model's vocabulary."""
    rows = gel(SERIES_QUERY.replace("%SID%", eq_str(sid)))
    if not rows:
        return None
    row = rows[0]
    rc = row["repeat_config"]
    cfg = model.RepeatConfig(
        repeat_unit=rc["repeat_unit"],
        repeat_interval=rc["repeat_interval"],
        selected_days=tuple(rc.get("selected_days") or ()),
        timezone=rc.get("timezone") or "UTC",
        end_type=rc["end_type"],
        number_of_occurrences=rc.get("number_of_occurrences"),
        end_date=iso_to_epoch(rc.get("end_date")),
    )
    sales = live_receipts()
    occs = []
    for o in row["occurrences"]:
        pub = (o.get("published_event") or {}).get("firestore_id")
        occs.append(model.Occurrence(
            occurrence_id=o["occurrence_id"],
            epoch=iso_to_epoch(o["date"]),
            published_event_id=pub,
            form_data_digest=digest(o.get("form_data")),
            edited=o.get("date_updated") is not None,
            live_receipts=sales.get(pub, 0) if pub else 0,
        ))
    occs.sort(key=lambda o: o.epoch)
    form = row["form_data"]
    if isinstance(form, str):
        form = json.loads(form)
    return {"cfg": cfg, "occurrences": occs, "form": form,
            "offset": int((form or {}).get("startTimeOffset") or 0)}


def iso_to_epoch(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = value.replace("Z", "+00:00")
    # Gel renders microseconds; fromisoformat wants at most six digits.
    if "." in text:
        head, _, tail = text.partition(".")
        frac, sign, rest = tail.partition("+")
        if not sign:
            frac, sign, rest = tail.partition("-")
        text = head + "." + frac[:6] + sign + rest
    return int(dt.datetime.fromisoformat(text).timestamp())


def digest(form):
    if form is None:
        return None
    if isinstance(form, str):
        try:
            form = json.loads(form)
        except Exception:
            return form
    return json.dumps(form, sort_keys=True)


def fmt(epochs, tz):
    out = []
    for e in sorted(epochs):
        local = dt.datetime.fromtimestamp(e, tz=UTC).astimezone(tz)
        out.append(f"{local.strftime('%Y-%m-%d %H:%M %z')}(={e})")
    return out


def outcome_slots(outcome, tz):
    """The full slot list a regenerate outcome describes: kept rows plus inserts.

    A kept row is already an occurrence rather than a slot, so it is presented
    as one here; only the instant matters to the comparison.
    """
    kept = [model.Slot(o.local_date(tz),
                       dt.datetime.fromtimestamp(o.epoch, tz=UTC))
            for o in outcome.kept]
    return kept + list(outcome.inserted)


def compare_slots(label, stored, expected, tz):
    """Compare stored occurrence instants against the model's slot list."""
    got = sorted(o.epoch for o in stored)
    want = sorted(s.epoch for s in expected)
    if got == want:
        return []
    return [f"{label}: occurrence instants differ\n"
            f"    expected {fmt(want, tz)}\n"
            f"    stored   {fmt(got, tz)}"]


# ----------------------------------------------------------------- scenario kit

FORM_BASE = {
    "name": "Scenario Series",
    "description": "created by the grader",
    "visibility": {"showToPublic": True, "showToFriends": False},
    "location": {},
    "eventType": "party",
    "color": "blue",
    "effect": "none",
    "settings": {},
    "tickets": [],
}


def create_series(name, repeat, start_iso, offset_seconds, timeout=90):
    """POST a new series and return (series_id, error-or-None)."""
    form = dict(FORM_BASE, name=name, startTimeOffset=offset_seconds)
    body = {
        "organizationId": ORG,
        "name": name,
        "description": "grader scenario",
        "formData": form,
        "repeatConfig": repeat,
        "startDate": start_iso,
    }
    status, payload = api_json("POST", "/v2/event-series", body, timeout=timeout)
    if status != 200:
        return None, f"create {name}: HTTP {status} {json.dumps(payload)[:400]}"
    sid = (((payload or {}).get("data") or {}).get("series") or {}).get("id")
    if not sid:
        return None, f"create {name}: response carried no series id: {json.dumps(payload)[:400]}"
    return sid, None


def repeat_cfg(unit, timezone, interval=1, selected=None, count=None,
               end_date_iso=None):
    cfg = {
        "repeatInterval": interval,
        "repeatUnit": unit,
        "selectedDays": selected or [],
        "timezone": timezone,
    }
    if end_date_iso is not None:
        cfg["endType"] = "onDate"
        cfg["endDate"] = int(dt.datetime.fromisoformat(
            end_date_iso.replace("Z", "+00:00")).timestamp())
    else:
        cfg["endType"] = "afterOccurrences"
        cfg["numberOfOccurrences"] = count
    return cfg


def start_instant(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def created_case(label, unit, tz_name, start_iso, offset, *, interval=1,
                 selected=None, count=None, end_date_iso=None):
    """Create a series, then check its stored occurrences against the model.

    Returns (complaints, state) so a caller can go on to regenerate or extend
    the same series.
    """
    tz = ZoneInfo(tz_name)
    repeat = repeat_cfg(unit, tz_name, interval, selected, count, end_date_iso)
    sid, err = create_series(label, repeat, start_iso, offset)
    if err:
        return [err], None

    state = load_series(sid)
    if state is None:
        return [f"{label}: series {sid} is not in the store after create"], None

    cfg = state["cfg"]
    try:
        expected = model.generate(cfg, start_instant(start_iso), offset)
    except model.ModelError as e:
        return [f"{label}: model rejected the stored config: {e}"], state

    problems = compare_slots(label, state["occurrences"], expected, tz)
    problems += [f"{label}: {v}" for v in
                 model.violations(state["occurrences"], tz)]
    state["sid"] = sid
    state["start_iso"] = start_iso
    state["offset"] = offset
    state["expected"] = expected
    return problems, state


# ------------------------------------------------------------------- the rules
# Each returns a list of complaints. The names are the ones that show up in
# reward-detail.json.

def rule_R1_shapes():
    """Daily, weekly and monthly creates land where the model says."""
    problems = []
    for label, unit, tz, start, offset, kw in [
        ("R1-daily-utc", "day", "UTC", "2026-03-02T09:00:00Z", 43200,
         dict(count=6)),
        ("R1-daily-interval", "day", "Europe/Berlin", "2026-03-02T09:00:00Z",
         75600, dict(interval=3, count=5)),
        ("R1-weekly", "week", "America/Chicago", "2026-03-02T09:00:00Z", 72000,
         dict(selected=[1], count=4)),
        ("R1-monthly", "month", "America/New_York", "2026-03-15T09:00:00Z",
         68400, dict(count=4)),
    ]:
        got, _ = created_case(label, unit, tz, start, offset, **kw)
        problems += got
    return problems


def rule_R2_selected_days():
    """Weekly honours selectedDays and never starts before the start date.

    The start date is a Wednesday and Sunday is selected, so a candidate that
    anchors the week without clipping emits the preceding Sunday.
    """
    problems = []
    got, state = created_case("R2-two-days", "week", "America/Los_Angeles",
                              "2026-03-04T09:00:00Z", 68400,
                              selected=[0, 3], count=6)
    problems += got
    if state:
        tz = ZoneInfo("America/Los_Angeles")
        anchor = start_instant("2026-03-04T09:00:00Z").astimezone(tz).date()
        for o in state["occurrences"]:
            if o.local_date(tz) < anchor:
                problems.append(
                    f"R2-two-days: occurrence {o.occurrence_id} on "
                    f"{o.local_date(tz)} precedes the start date {anchor}")
        for o in state["occurrences"]:
            wd = model.weekday_sunday0(o.local_date(tz))
            if wd not in (0, 3):
                problems.append(
                    f"R2-two-days: occurrence on {o.local_date(tz)} is a "
                    f"{model.SUNDAY_FIRST[wd]}, not a selected day")
    return problems


def rule_R3_month_clamp():
    """Monthly from the 31st clamps into short months and does not stay clamped.

    Six occurrences from 31 January 2026 must read 31 Jan, 28 Feb, 31 Mar,
    30 Apr, 31 May, 30 Jun. A sticky clamp gives 28 Feb, 28 Mar; a rolling
    30-day step gives 2 Mar.
    """
    problems, state = created_case("R3-month-end", "month", "America/New_York",
                                   "2026-01-31T09:00:00Z", 68400, count=6)
    if state:
        tz = ZoneInfo("America/New_York")
        want = [dt.date(2026, 1, 31), dt.date(2026, 2, 28), dt.date(2026, 3, 31),
                dt.date(2026, 4, 30), dt.date(2026, 5, 31), dt.date(2026, 6, 30)]
        got = [o.local_date(tz) for o in state["occurrences"]]
        if got != want:
            problems.append(
                "R3-month-end: local dates differ\n"
                f"    expected {[d.isoformat() for d in want]}\n"
                f"    stored   {[d.isoformat() for d in got]}")

    # A leap February, to separate a hard-coded 28 from a real month length.
    more, leap = created_case("R3-leap", "month", "UTC",
                              "2028-01-31T09:00:00Z", 43200, count=3)
    problems += more
    if leap:
        got = [o.local_date(ZoneInfo("UTC")) for o in leap["occurrences"]]
        if dt.date(2028, 2, 29) not in got:
            problems.append(
                f"R3-leap: February 2028 has 29 days; stored dates were "
                f"{[d.isoformat() for d in got]}")
    return problems


def transition_case(label, zone, start_iso, offset, day, kind):
    """A short daily series stepping over a transition, checked at the crossing.

    The occurrence on `day` is the interesting one: its nominal wall clock is
    either missing from the local calendar or present twice. Whichever it is,
    the date must still hold exactly one occurrence, at the instant the spec
    names, and no occurrence anywhere in the series may sit at a local time
    that does not exist.
    """
    problems, state = created_case(label, "day", zone, start_iso, offset,
                                   count=5)
    if not state:
        return problems
    tz = ZoneInfo(zone)
    nominal = (dt.datetime.combine(day, dt.time(0)) +
               dt.timedelta(seconds=offset))
    if model.local_kind(nominal, tz) != kind:
        return problems + [
            f"{label}: GRADER BUG -- {nominal} in {zone} is "
            f"{model.local_kind(nominal, tz)}, not {kind}"]

    dates = [o.local_date(tz) for o in state["occurrences"]]
    if len(set(dates)) != len(dates):
        problems.append(f"{label}: repeated local dates "
                        f"{[d.isoformat() for d in dates]}")
    if dates.count(day) != 1:
        problems.append(
            f"{label}: {day.isoformat()} must hold exactly one occurrence; a "
            f"transition neither removes a date nor doubles it. Stored "
            f"{[d.isoformat() for d in dates]}")
    for o in state["occurrences"]:
        local = dt.datetime.fromtimestamp(o.epoch, tz=UTC).astimezone(tz)
        if model.local_kind(local.replace(tzinfo=None), tz) == "gap":
            problems.append(f"{label}: occurrence {o.occurrence_id} sits at "
                            f"{local}, a local time that does not exist")
        if o.local_date(tz) != day:
            continue
        want = int(model.resolve_instant(day, offset, tz).timestamp())
        if o.epoch != want:
            note = ("the first instant that exists" if kind == "gap"
                    else "the earlier of its two offsets")
            problems.append(
                f"{label}: {nominal.time()} on {day.isoformat()} is {kind} in "
                f"{zone}, so the occurrence takes {note}\n"
                f"    expected {fmt([want], tz)[0]}\n"
                f"    stored   {fmt([o.epoch], tz)[0]}")
    return problems


def rule_R4_spring_forward():
    """A local time that does not exist resolves forward, on the same date.

    Three zones, because the standard library's own answer for a nonexistent
    wall time lands on a different side of the gap in each and reports nothing
    unusual in any of them. Los Angeles comes back an hour early, Lisbon an
    hour late because its winter offset is zero, and Lord Howe Island's gap is
    thirty minutes wide rather than an hour, so a fix expressed in whole hours
    overshoots it.
    """
    problems = []
    for label, zone, start, offset, day in [
        ("R4-spring-la", "America/Los_Angeles", "2026-03-06T09:00:00Z", 9000,
         dt.date(2026, 3, 8)),
        ("R4-spring-lisbon", "Europe/Lisbon", "2026-03-27T09:00:00Z", 3900,
         dt.date(2026, 3, 29)),
        ("R4-spring-lhi", "Australia/Lord_Howe", "2026-10-02T09:00:00Z", 8100,
         dt.date(2026, 10, 4)),
    ]:
        problems += transition_case(label, zone, start, offset, day, "gap")
    return problems


def rule_R5_fall_back():
    """An ambiguous local time keeps its date, at the earlier of its instants.

    Three zones again, and for the same reason: constructing an ambiguous wall
    time in Go returns one of the two passes without saying which, and it is
    not consistently the earlier one. New York's 01:30 on 1 November comes back
    as the first pass and Berlin's 02:30 on 25 October as the second, so a
    single American test zone lets the mistake through. Lord Howe Island
    repeats only thirty minutes, so its ambiguous window is half an hour wide.
    """
    problems = []
    for label, zone, start, offset, day in [
        ("R5-fallback-ny", "America/New_York", "2026-10-30T09:00:00Z", 5400,
         dt.date(2026, 11, 1)),
        ("R5-fallback-berlin", "Europe/Berlin", "2026-10-23T09:00:00Z", 9000,
         dt.date(2026, 10, 25)),
        ("R5-fallback-lhi", "Australia/Lord_Howe", "2026-04-03T09:00:00Z",
         6300, dt.date(2026, 4, 5)),
    ]:
        problems += transition_case(label, zone, start, offset, day,
                                    "ambiguous")
    return problems


def rule_R6_count():
    """afterOccurrences yields exactly the count, across all three units."""
    problems = []
    for label, unit, tz, start, offset, kw in [
        ("R6-day-1", "day", "UTC", "2026-03-02T09:00:00Z", 43200, dict(count=1)),
        ("R6-week-7", "week", "Europe/Berlin", "2026-03-02T09:00:00Z", 75600,
         dict(selected=[1, 4], count=7)),
        ("R6-month-13", "month", "America/Denver", "2026-01-30T09:00:00Z",
         64800, dict(count=13)),
    ]:
        got, state = created_case(label, unit, tz, start, offset, **kw)
        problems += got
        if state:
            want = kw["count"]
            have = len(state["occurrences"])
            if have != want:
                problems.append(
                    f"{label}: numberOfOccurrences was {want}, store holds {have}")
    return problems


def rule_R7_end_date():
    """onDate includes the end date itself and nothing past it."""
    problems = []
    # 10 March at noon UTC is itself a slot of an every-other-day series from
    # 2 March, so the inclusive boundary is observable.
    got, state = created_case("R7-boundary", "day", "UTC",
                              "2026-03-02T09:00:00Z", 43200, interval=2,
                              end_date_iso="2026-03-10T00:00:00Z")
    problems += got
    if state:
        tz = ZoneInfo("UTC")
        dates = [o.local_date(tz) for o in state["occurrences"]]
        if dt.date(2026, 3, 10) not in dates:
            problems.append(
                "R7-boundary: an occurrence whose local date equals the end "
                f"date must be included; stored {[d.isoformat() for d in dates]}")
        beyond = [d for d in dates if d > dt.date(2026, 3, 10)]
        if beyond:
            problems.append(
                f"R7-boundary: occurrences past the end date: "
                f"{[d.isoformat() for d in beyond]}")

    # The end date read in the series' own zone, not in UTC. Midnight UTC on
    # 11 March is still 10 March in Los Angeles, so a series ending then must
    # not contain the 11th.
    got2, state2 = created_case("R7-zone", "day", "America/Los_Angeles",
                                "2026-03-08T09:00:00Z", 68400,
                                end_date_iso="2026-03-11T04:00:00Z")
    problems += got2
    if state2:
        tz = ZoneInfo("America/Los_Angeles")
        dates = [o.local_date(tz) for o in state2["occurrences"]]
        if dt.date(2026, 3, 11) in dates:
            problems.append(
                "R7-zone: the end date is a local date in the series' zone; "
                f"11 March is past it. Stored {[d.isoformat() for d in dates]}")
    return problems


def _regenerate(sid, start_iso=None, timeout=120):
    body = {"startDate": start_iso} if start_iso else {}
    return api_json("POST", f"/v2/event-series/{sid}/regenerate", body,
                    timeout=timeout)


def rule_R8_protect_published():
    """Regenerate keeps published occurrences whole, and rebuilds the rest.

    hs-guard-a has two published occurrences, one of which has sales. The
    regenerate is given a start date that moves the pattern off both of them, so
    keeping them is a decision and not an accident of the dates lining up.
    """
    problems = []
    tz = ZoneInfo("America/Chicago")
    before = load_series("hs-guard-a")
    if before is None:
        return ["R8-protect: fixture series hs-guard-a is missing"]

    published = {o.occurrence_id: o for o in before["occurrences"] if o.published}
    if len(published) != 2:
        return [f"R8-protect: fixture should hold two published occurrences, "
                f"found {sorted(published)}"]

    start_iso = "2026-04-06T09:00:00Z"
    status, payload = _regenerate("hs-guard-a", start_iso)
    if status != 200:
        return [f"R8-protect: regenerate returned HTTP {status} "
                f"{json.dumps(payload)[:400]}"]

    after = load_series("hs-guard-a")
    outcome = model.regenerate(before["cfg"], before["occurrences"],
                              start_instant(start_iso), before["offset"])

    got_ids = {o.occurrence_id for o in after["occurrences"]}
    for oid, occ in published.items():
        if oid not in got_ids:
            problems.append(
                f"R8-protect: published occurrence {oid} was destroyed by the "
                "regenerate")
            continue
        now = next(o for o in after["occurrences"] if o.occurrence_id == oid)
        if now.epoch != occ.epoch:
            problems.append(
                f"R8-protect: published occurrence {oid} moved from "
                f"{occ.epoch} to {now.epoch}")
        if now.published_event_id != occ.published_event_id:
            problems.append(
                f"R8-protect: published occurrence {oid} lost its event link "
                f"({occ.published_event_id} -> {now.published_event_id})")
        if now.form_data_digest != occ.form_data_digest:
            problems.append(
                f"R8-protect: published occurrence {oid} had its form data "
                "rewritten")

    problems += compare_slots("R8-protect", after["occurrences"],
                              outcome_slots(outcome, tz), tz)
    problems += [f"R8-protect: {v}" for v in
                 model.violations(after["occurrences"], tz)]

    # Unpublished, unedited rows are not sacred: they must have been replaced.
    stale = {o.occurrence_id for o in before["occurrences"]
             if not o.published and not o.edited}
    survived = stale & got_ids
    if survived:
        problems.append(
            f"R8-protect: unpublished, unedited occurrences {sorted(survived)} "
            "survived a regenerate that moved the pattern off their dates")
    return problems


def rule_R9_edited():
    """An individually edited occurrence survives, until the pattern moves.

    Two regenerates on hs-hand-a. The first keeps the pattern where it is, so
    the edited row is still on it and must be kept with its own date. The second
    moves the start date a week on, taking the pattern off that date, and the row
    must then go: nothing has to remember that anything changed, because being
    on the lattice is the whole test.
    """
    problems = []
    tz = ZoneInfo("America/Denver")
    state = load_series("hs-hand-a")
    if state is None:
        return ["R9-edit: fixture series hs-hand-a is missing"]
    if any(o.published for o in state["occurrences"]):
        return ["R9-edit: fixture series hs-hand-a should hold nothing published"]
    if len(state["occurrences"]) < 4:
        return [f"R9-edit: fixture series hs-hand-a should hold four "
                f"occurrences, store holds {len(state['occurrences'])}"]

    target = state["occurrences"][2]
    new_form = dict(FORM_BASE, name="Edited Occurrence By Hand",
                    startTimeOffset=state["offset"])
    status, payload = api_json(
        "PATCH", f"/v2/event-series/hs-hand-a/occurrences/{target.occurrence_id}",
        {"formData": new_form})
    if status != 200:
        return [f"R9-edit: PATCH of an occurrence returned HTTP {status} "
                f"{json.dumps(payload)[:400]}"]

    edited = load_series("hs-hand-a")
    row = next((o for o in edited["occurrences"]
                if o.occurrence_id == target.occurrence_id), None)
    if row is None:
        return [f"R9-edit: occurrence {target.occurrence_id} vanished on PATCH"]
    if not row.edited:
        problems.append(
            "R9-edit: an individual edit must be recorded on the occurrence "
            "(date_updated is unset), so a regenerate cannot tell it apart")

    # First regenerate: same pattern, so the edit stays.
    start_same = "2026-03-03T09:00:00Z"
    status, payload = _regenerate("hs-hand-a", start_same)
    if status != 200:
        return problems + [f"R9-edit: regenerate returned HTTP {status} "
                           f"{json.dumps(payload)[:400]}"]
    after = load_series("hs-hand-a")
    kept = next((o for o in after["occurrences"]
                 if o.occurrence_id == target.occurrence_id), None)
    if kept is None:
        problems.append(
            f"R9-edit: edited occurrence {target.occurrence_id} was destroyed "
            "by a regenerate that left its date on the pattern")
    else:
        if kept.epoch != row.epoch:
            problems.append(
                f"R9-edit: edited occurrence {target.occurrence_id} moved from "
                f"{row.epoch} to {kept.epoch}")
        if kept.form_data_digest != row.form_data_digest:
            problems.append(
                f"R9-edit: edited occurrence {target.occurrence_id} had its "
                "hand-edited form data overwritten")
    problems += [f"R9-edit: {v}" for v in model.violations(after["occurrences"], tz)]

    # Second regenerate: the pattern starts past the edited date, so that date is
    # no longer on it and the row must go.
    #
    # The start date has to move past the edit, not merely change. This series
    # selects Tuesdays explicitly, so shifting the start by a week -- or to a
    # different weekday -- still generates the same Tuesdays and the edit would
    # stay on the pattern for reasons that have nothing to do with the rule.
    start_moved = "2026-03-24T09:00:00Z"
    status, payload = _regenerate("hs-hand-a", start_moved)
    if status != 200:
        return problems + [f"R9-edit: second regenerate returned HTTP {status} "
                           f"{json.dumps(payload)[:400]}"]
    moved = load_series("hs-hand-a")
    expect = model.regenerate(after["cfg"], after["occurrences"],
                             start_instant(start_moved), after["offset"])
    if any(o.occurrence_id == target.occurrence_id for o in moved["occurrences"]):
        problems.append(
            f"R9-edit: edited occurrence {target.occurrence_id} survived a "
            "regenerate that took the pattern off its date; an edit protects a "
            "row only while it is still on the pattern")
    problems += compare_slots("R9-edit-moved", moved["occurrences"],
                              outcome_slots(expect, tz), tz)
    return problems


def rule_R10_extend():
    """Extend continues the series' own lattice from its earliest occurrence.

    hs-anchor-a is monthly on the 31st and its two rows are 31 January and
    28 February -- February clamped. Continuing from the *latest* row treats 28
    February as the anchor and gives 28 March; continuing from the series' own
    anchor gives 31 March. That is the whole distinction, and the fixture is
    built so the two answers differ.
    """
    problems = []
    tz = ZoneInfo("America/New_York")
    before = load_series("hs-anchor-a")
    if before is None:
        return ["R10-extend: fixture series hs-anchor-a is missing"]

    status, payload = api_json("POST", "/v2/event-series/hs-anchor-a/extend",
                              {"additionalOccurrences": 3})
    if status != 200:
        return [f"R10-extend: extend returned HTTP {status} "
                f"{json.dumps(payload)[:400]}"]

    after = load_series("hs-anchor-a")
    old_dates = [o.local_date(tz) for o in before["occurrences"]]
    anchor = min(old_dates)
    expected = model.extend(before["cfg"], anchor, old_dates, 3,
                            before["offset"])

    added = [o for o in after["occurrences"]
             if o.occurrence_id not in {x.occurrence_id for x in before["occurrences"]}]
    problems += compare_slots("R10-extend", added, expected, tz)

    survived = {o.occurrence_id for o in before["occurrences"]} & \
               {o.occurrence_id for o in after["occurrences"]}
    if len(survived) != len(before["occurrences"]):
        problems.append(
            "R10-extend: extending must not disturb the occurrences already "
            f"there; {len(before['occurrences']) - len(survived)} went missing")
    problems += [f"R10-extend: {v}" for v in model.violations(after["occurrences"], tz)]

    # Extending twice must not repeat a date, which is what happens when the
    # continuation is measured from the wrong end or the end rule is reapplied.
    status, payload = api_json("POST", "/v2/event-series/hs-anchor-a/extend",
                              {"additionalOccurrences": 2})
    if status != 200:
        problems.append(f"R10-extend: second extend returned HTTP {status} "
                        f"{json.dumps(payload)[:400]}")
    else:
        twice = load_series("hs-anchor-a")
        problems += [f"R10-extend-twice: {v}" for v in
                     model.violations(twice["occurrences"], tz)]
        if len(twice["occurrences"]) != len(before["occurrences"]) + 5:
            problems.append(
                f"R10-extend-twice: expected "
                f"{len(before['occurrences']) + 5} occurrences after adding "
                f"3 then 2, store holds {len(twice['occurrences'])}")
    return problems


def rule_R11_concurrent():
    """Regenerates arriving together leave the state one would.

    Every request in a round carries the same start date, so a serialisable
    implementation ends in the state a single regenerate reaches whichever order
    they take. The failure this catches is interleaving: one request's delete
    landing after another's insert, leaving a series that is short, or doubled,
    or holding slots from two different plans.

    Four racers over three rounds rather than one pair once, and that is the
    difference between a rule and a coin toss. A read-plan-write sequence with no
    transaction around it is only wrong when the window actually overlaps, and
    two requests are quite likely to miss each other -- a candidate that dropped
    the transaction entirely passed a single two-way race here. Widening the race
    and repeating it makes an unprotected implementation lose reliably while a
    serialisable one is unaffected, because it is not a race at all.

    Each round moves the start date, so every round really does drop the whole
    series and insert a new one. Repeating one start date would find the store
    already correct and quietly test nothing.
    """
    problems = []
    tz = ZoneInfo("Europe/Berlin")
    if load_series("hs-contend-a") is None:
        return ["R11-concurrent: fixture series hs-contend-a is missing"]

    racers = 4
    # The last round crosses Berlin's March transition, so the round that runs
    # under the most contention is also the one where the dates are hardest.
    rounds = ["2026-03-16T09:00:00Z",
              "2026-03-24T09:00:00Z",
              "2026-04-01T09:00:00Z"]

    for rnd, start_iso in enumerate(rounds, 1):
        before = load_series("hs-contend-a")
        results = {}
        barrier = threading.Barrier(racers)
        # Held at the checkpoint in the regenerate path until all four have
        # reached it, so the overlap is arranged rather than hoped for. A
        # candidate that removed the checkpoint simply falls back to the timing
        # race, which is the weaker version of the same test and not a
        # different one.
        coord("arm", "pre-regenerate", parties=racers, hold=False,
              timeout_ms=20000)

        def fire(tag):
            barrier.wait()
            results[tag] = _regenerate("hs-contend-a", start_iso,
                                       timeout=180)

        # Daemons: a racer whose request outlives the join below must not be
        # able to hold the interpreter open after the verdict is written.
        threads = [threading.Thread(target=fire, args=(i,), daemon=True)
                   for i in range(racers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(240)

        if len(results) != racers:
            return problems + [
                f"R11-concurrent: round {rnd}: only {len(results)} of "
                f"{racers} regenerates returned"]

        after = load_series("hs-contend-a")
        expect = model.regenerate(before["cfg"], before["occurrences"],
                                  start_instant(start_iso), before["offset"])
        round_problems = compare_slots(
            f"R11-concurrent round {rnd}", after["occurrences"],
            outcome_slots(expect, tz), tz)
        round_problems += [f"R11-concurrent round {rnd}: {v}" for v in
                           model.violations(after["occurrences"], tz)]

        codes = {tag: res[0] for tag, res in results.items()}
        if not any(c == 200 for c in codes.values()):
            round_problems.append(
                f"R11-concurrent: round {rnd}: no regenerate succeeded: {codes}")
        for tag, code in codes.items():
            if code == 0:
                round_problems.append(
                    f"R11-concurrent: round {rnd}: request {tag} killed the "
                    f"connection ({results[tag][1][:200]}); a contended "
                    "regenerate must fail cleanly, not take the service down")

        # Stop at the first bad round. Later rounds would be comparing against a
        # store the failure has already corrupted, and their complaints would
        # describe the wreckage rather than a second independent fault.
        if round_problems:
            return problems + round_problems

    return problems


def rule_R12_publish_then_regenerate():
    """Publishing an occurrence makes a later regenerate keep it.

    Fresh series, so nothing about the fixture's own published rows is doing the
    work. The regenerate afterwards moves the pattern, and the published row
    must still be there on its original date.
    """
    problems = []
    tz = ZoneInfo("America/Chicago")
    problems_created, state = created_case(
        "R12-publish", "week", "America/Chicago", "2026-05-04T09:00:00Z",
        72000, selected=[1], count=4)
    problems += problems_created
    if state is None:
        return problems
    sid = state["sid"]
    if len(state["occurrences"]) < 2:
        return problems + [
            "R12-publish: the new series holds "
            f"{len(state['occurrences'])} occurrences, so there is nothing to "
            "publish and the rest of the rule cannot be checked"]

    target = state["occurrences"][1]
    status, payload = api_json(
        "POST", f"/v2/event-series/{sid}/occurrences/{target.occurrence_id}/publish",
        {"eventId": "evt-published-003"})
    if status != 200:
        return problems + [
            f"R12-publish: publish returned HTTP {status} "
            f"{json.dumps(payload)[:400]}"]

    published = load_series(sid)
    row = next((o for o in published["occurrences"]
                if o.occurrence_id == target.occurrence_id), None)
    if row is None or not row.published:
        return problems + [
            "R12-publish: publishing did not set the occurrence's "
            "published_event link"]

    start_moved = "2026-05-11T09:00:00Z"
    status, payload = _regenerate(sid, start_moved)
    if status != 200:
        return problems + [f"R12-publish: regenerate returned HTTP {status} "
                           f"{json.dumps(payload)[:400]}"]

    after = load_series(sid)
    kept = next((o for o in after["occurrences"]
                 if o.occurrence_id == target.occurrence_id), None)
    if kept is None:
        problems.append(
            "R12-publish: the occurrence published a moment ago was destroyed "
            "by a regenerate")
    else:
        if kept.epoch != row.epoch:
            problems.append(
                f"R12-publish: the published occurrence moved from {row.epoch} "
                f"to {kept.epoch}; a published date is fixed")
        if kept.published_event_id != row.published_event_id:
            problems.append(
                "R12-publish: the published occurrence lost its event link")

    expect = model.regenerate(published["cfg"], published["occurrences"],
                             start_instant(start_moved), published["offset"])
    problems += compare_slots("R12-publish", after["occurrences"],
                              outcome_slots(expect, tz), tz)
    problems += [f"R12-publish: {v}" for v in
                 model.violations(after["occurrences"], tz)]
    return problems


def rule_R13_delete_sales():
    """Deleting is refused only when the published event has taken money.

    Both fixture occurrences are published. One carries an event with two live
    receipt items; the other carries an event whose receipt items are all
    pending, refunded or abandoned. A candidate that refuses on publication
    refuses both; one that counts every receipt item refuses both; one that
    forgets the filter entirely allows both.
    """
    problems = []
    state = load_series("hs-guard-a")
    if state is None:
        return ["R13-delete: fixture series hs-guard-a is missing"]

    sold = [o for o in state["occurrences"] if o.sales_protected]
    clean = [o for o in state["occurrences"]
             if o.published and not o.sales_protected]
    if not sold or not clean:
        return [f"R13-delete: fixture must hold one sold and one unsold "
                f"published occurrence; sold={[o.occurrence_id for o in sold]} "
                f"clean={[o.occurrence_id for o in clean]}"]

    victim = sold[0]
    status, payload = api_json(
        "DELETE", f"/v2/event-series/hs-guard-a/occurrences/{victim.occurrence_id}")
    if status != 409:
        problems.append(
            f"R13-delete: deleting occurrence {victim.occurrence_id}, whose "
            f"published event has {victim.live_receipts} live receipt items, "
            f"returned HTTP {status} rather than 409")
    still = load_series("hs-guard-a")
    if not any(o.occurrence_id == victim.occurrence_id
               for o in still["occurrences"]):
        problems.append(
            f"R13-delete: occurrence {victim.occurrence_id} was removed from "
            "the store despite having live sales")

    keeper = clean[0]
    status, payload = api_json(
        "DELETE", f"/v2/event-series/hs-guard-a/occurrences/{keeper.occurrence_id}")
    if status != 200:
        problems.append(
            f"R13-delete: deleting occurrence {keeper.occurrence_id}, whose "
            "published event sold nothing (its receipt items are pending, "
            f"refunded or abandoned), returned HTTP {status} rather than 200")
    else:
        gone = load_series("hs-guard-a")
        if any(o.occurrence_id == keeper.occurrence_id
               for o in gone["occurrences"]):
            problems.append(
                f"R13-delete: DELETE reported success but occurrence "
                f"{keeper.occurrence_id} is still in the store")
    return problems


# ------------------------------------------------------- scoped edits (R14-R17)

def scope_patch(sid, occurrence_id, offset, name="Scoped By The Grader",
                scope="thisAndFollowing", timeout=120):
    """PATCH one occurrence with a scope and a new time of day.

    The offset travels inside formData, which is the only place the API has for
    it, so a scoped edit necessarily carries a whole template with it. That is
    what makes the rule two rules at once: the form data lands on every
    occurrence the scope reaches, and the time of day inside it decides where
    each of those occurrences now sits.
    """
    form = dict(FORM_BASE, name=name, startTimeOffset=offset)
    return api_json("PATCH",
                    f"/v2/event-series/{sid}/occurrences/{occurrence_id}",
                    {"formData": form, "scope": scope}, timeout=timeout)


def check_scope(label, sid, target_id, new_offset, before, tz):
    """Run a scoped edit and check the whole series against the model.

    Everything the model separates is checked separately, because the three
    groups fail for different reasons: rows before the target are a boundary
    question, paid rows are a protection question, and the rows that do move
    are a date-resolution question.
    """
    template_before = digest(before["form"])
    status, payload = scope_patch(sid, target_id, new_offset)
    if status != 200:
        return [f"{label}: scoped PATCH returned HTTP {status} "
                f"{json.dumps(payload)[:400]}"]

    try:
        plan = model.scoped_edit(before["cfg"], before["occurrences"],
                                 target_id, new_offset)
    except model.ModelError as e:
        return [f"{label}: model could not plan the edit: {e}"]

    after = load_series(sid)
    problems = []
    by_id = {o.occurrence_id: o for o in after["occurrences"]}

    for occ in before["occurrences"]:
        now = by_id.get(occ.occurrence_id)
        if now is None:
            problems.append(
                f"{label}: occurrence {occ.occurrence_id} disappeared; an edit "
                "removes nothing")
            continue
        want = plan.expected_epoch(occ)
        if now.epoch != want:
            group = ("moved" if occ.occurrence_id in plan.moved else
                     "paid, so untouched" if occ.occurrence_id in plan.paid
                     else "before the target, so untouched")
            problems.append(
                f"{label}: occurrence {occ.occurrence_id} ({group}) should sit "
                f"at {fmt([want], tz)[0]} and sits at {fmt([now.epoch], tz)[0]}")
        moved = occ.occurrence_id in plan.moved
        if not moved and now.form_data_digest != occ.form_data_digest:
            problems.append(
                f"{label}: occurrence {occ.occurrence_id} is outside the scope "
                "of the edit but its form data was rewritten")
        if moved and now.form_data_digest == occ.form_data_digest:
            problems.append(
                f"{label}: occurrence {occ.occurrence_id} is inside the scope "
                "of the edit but its form data was left as it was")

    extra = set(by_id) - {o.occurrence_id for o in before["occurrences"]}
    if extra:
        problems.append(
            f"{label}: an edit created occurrences {sorted(extra)}")
    if digest(after["form"]) != template_before:
        problems.append(
            f"{label}: the series template was rewritten; a scoped edit reaches "
            "occurrences and never the series itself")
    problems += [f"{label}: {v}" for v in model.violations(after["occurrences"], tz)]
    return problems


def rule_R14_scope_paid():
    """A scoped edit moves what it reaches and steps over what has sold.

    hs-reach-a is five Chicago Thursdays. The target is the second, and the
    third has taken money. So one row is before the scope, three are inside it,
    and one is inside it and protected -- and the protection predicate is the
    same one the delete path refuses on. An implementation that reached for
    "update every occurrence whose date is not less than this one" moves the
    paid row too, which is the obvious answer and the wrong one.
    """
    tz = ZoneInfo("America/Chicago")
    before = load_series("hs-reach-a")
    if before is None:
        return ["R14-scope: fixture series hs-reach-a is missing"]
    paid = [o for o in before["occurrences"] if o.sales_protected]
    if len(paid) != 1:
        return [f"R14-scope: fixture must hold exactly one paid occurrence, "
                f"found {[o.occurrence_id for o in paid]}"]
    if len(before["occurrences"]) != 5:
        return [f"R14-scope: fixture should hold five occurrences, store holds "
                f"{len(before['occurrences'])}"]

    target = before["occurrences"][1]
    problems = check_scope("R14-scope", "hs-reach-a", target.occurrence_id,
                           61200, before, tz)

    # The paid row is the whole point, so it is also stated directly rather than
    # only falling out of the comparison above.
    after = load_series("hs-reach-a")
    was = paid[0]
    now = next((o for o in after["occurrences"]
                if o.occurrence_id == was.occurrence_id), None)
    if now is None:
        problems.append(
            f"R14-scope: paid occurrence {was.occurrence_id} was removed")
    elif now.epoch != was.epoch or now.form_data_digest != was.form_data_digest:
        problems.append(
            f"R14-scope: paid occurrence {was.occurrence_id} was modified by a "
            "scoped edit; an occurrence whose published event has taken money "
            "keeps both its instant and its form data")
    return problems


def rule_R15_scope_over_clamp():
    """A scope moves each occurrence by its own local date, clamps and all.

    Lisbon, monthly from 29 January, scoped from February onwards to 01:05 in
    the morning. Three rules meet on three consecutive rows and none of them
    can be satisfied in its own branch:

      * 28 February is where the 29th was clamped. The row that moves is the
        one on 28 February, so an implementation that recomputes the pattern
        from the anchor to decide where each row now goes puts it on the 29th
        or loses it, while one that reads each row's own local date does not.
      * 29 March has no 01:05 at all -- Lisbon goes from 01:00 to 02:00 that
        morning -- so this row must land on 02:00, the same resolution a create
        would give it, reached here from an edit instead.
      * 29 April is on the other side of the transition, so holding the wall
        clock fixed moves the instant by an hour relative to February.

    ser-lis-monthly in the fixture is the same series read-only, so all three
    are readable before anything is written.
    """
    tz = ZoneInfo("Europe/Lisbon")
    want = [dt.date(2026, 1, 29), dt.date(2026, 2, 28), dt.date(2026, 3, 29),
            dt.date(2026, 4, 29), dt.date(2026, 5, 29)]

    # First the same series as ser-lis-monthly, built rather than read, so that
    # the clamp and the gap are graded on the create path too and not only
    # through an edit. 01:05 on 29 March is the row that does not exist.
    problems, direct = created_case("R15-clamp-create", "month",
                                    "Europe/Lisbon", "2026-01-29T12:00:00Z",
                                    3900, count=5)
    if direct is not None:
        got = [o.local_date(tz) for o in direct["occurrences"]]
        if got != want:
            problems.append(
                "R15-clamp-create: local dates differ\n"
                f"    expected {[d.isoformat() for d in want]}\n"
                f"    stored   {[d.isoformat() for d in got]}")

    more, state = created_case("R15-clamp-scope", "month", "Europe/Lisbon",
                               "2026-01-29T12:00:00Z", 68400, count=5)
    problems += more
    if state is None:
        return problems
    dates = [o.local_date(tz) for o in state["occurrences"]]
    if dates != want:
        return problems + [
            "R15-clamp-scope: the series has to be built correctly before it "
            f"can be edited; expected {[d.isoformat() for d in want]}, stored "
            f"{[d.isoformat() for d in dates]}"]

    target = state["occurrences"][1]
    problems += check_scope("R15-clamp-scope", state["sid"],
                            target.occurrence_id, 3900, state, tz)

    after = load_series(state["sid"])
    still = [o.local_date(tz) for o in after["occurrences"]]
    if still != want:
        problems.append(
            "R15-clamp-scope: an edit changes the time of day and never which "
            f"local date an occurrence falls on; dates are now "
            f"{[d.isoformat() for d in still]}")
    for occ in after["occurrences"]:
        local = dt.datetime.fromtimestamp(occ.epoch, tz=UTC).astimezone(tz)
        if model.local_kind(local.replace(tzinfo=None), tz) == "gap":
            problems.append(
                f"R15-clamp-scope: occurrence {occ.occurrence_id} was moved to "
                f"{local}, a local time that does not exist")
    return problems


def rule_R16_scope_across_dst():
    """A scoped edit resolves each occurrence's own local time afresh.

    Los Angeles, daily at noon, over the March transition, then scoped to
    02:30. On 8 March there is no 02:30, so that occurrence takes the first
    local time there is -- 03:00 -- exactly as a create would. Shifting every
    stored instant by the same difference instead lands it on 01:30, an hour
    before the transition and a wall clock nobody asked for; letting the zone
    normalise a nonexistent time forward by its own gap lands it on 03:30.
    Both are visible here and neither is visible in a series that does not
    cross a transition, which is why this is a separate scenario rather than a
    different offset in the one above.
    """
    tz = ZoneInfo("America/Los_Angeles")
    problems, state = created_case("R16-scope-dst", "day",
                                   "America/Los_Angeles",
                                   "2026-03-06T20:00:00Z", 43200, count=5)
    if state is None:
        return problems

    target = next((o for o in state["occurrences"]
                   if o.local_date(tz) == dt.date(2026, 3, 7)), None)
    if target is None:
        return problems + [
            "R16-scope-dst: 7 March is not in the series, so the scenario "
            f"cannot run; stored {[str(o.local_date(tz)) for o in state['occurrences']]}"]

    problems += check_scope("R16-scope-dst", state["sid"],
                            target.occurrence_id, 9000, state, tz)

    after = load_series(state["sid"])
    for occ in after["occurrences"]:
        local = dt.datetime.fromtimestamp(occ.epoch, tz=UTC).astimezone(tz)
        if model.local_kind(local.replace(tzinfo=None), tz) == "gap":
            problems.append(
                f"R16-scope-dst: occurrence {occ.occurrence_id} was moved to "
                f"{local}, a local time that does not exist")
    dates = [o.local_date(tz) for o in after["occurrences"]]
    if len(set(dates)) != len(dates):
        problems.append(
            "R16-scope-dst: an edit changes the time of day, not the date; "
            f"local dates are now {[d.isoformat() for d in dates]}")
    return problems


def rule_R17_scope_then_regenerate():
    """A scoped edit survives a regenerate exactly as a single edit does.

    The rows a scope touched are individually edited rows, so whether each one
    survives the regenerate that follows is decided by the same test as
    anywhere else: still on the pattern, or published. This is the rule the two
    halves of the task share, and running it after a scope is how a candidate
    that recorded the scoped edit somewhere other than on the occurrences comes
    apart -- the regenerate then cannot tell those rows from ones it generated
    itself, and replaces them.
    """
    tz = ZoneInfo("America/Denver")
    problems, state = created_case("R17-scope-regen", "week",
                                   "America/Denver", "2026-07-06T18:00:00Z",
                                   64800, selected=[1], count=4)
    if state is None:
        return problems
    if len(state["occurrences"]) != 4:
        return problems + [
            f"R17-scope-regen: expected four occurrences, store holds "
            f"{len(state['occurrences'])}"]

    sid = state["sid"]
    target = state["occurrences"][1]
    problems += check_scope("R17-scope-regen", sid, target.occurrence_id,
                            36000, state, tz)

    edited = load_series(sid)
    start_same = "2026-07-06T18:00:00Z"
    status, payload = _regenerate(sid, start_same)
    if status != 200:
        return problems + [
            f"R17-scope-regen: regenerate returned HTTP {status} "
            f"{json.dumps(payload)[:400]}"]

    after = load_series(sid)
    expect = model.regenerate(edited["cfg"], edited["occurrences"],
                              start_instant(start_same), edited["offset"])
    problems += compare_slots("R17-scope-regen", after["occurrences"],
                              outcome_slots(expect, tz), tz)
    kept_ids = {o.occurrence_id for o in after["occurrences"]}
    scoped = [o for o in edited["occurrences"]
              if o.occurrence_id in
              {x.occurrence_id for x in state["occurrences"][1:]}]
    for occ in scoped:
        if occ.occurrence_id not in kept_ids:
            problems.append(
                f"R17-scope-regen: occurrence {occ.occurrence_id} was moved by "
                "a scoped edit and its local date is still on the pattern, so "
                "the regenerate had to keep it, and it is gone")
    problems += [f"R17-scope-regen: {v}" for v in
                 model.violations(after["occurrences"], tz)]
    return problems


# ------------------------------------------------------------ extend (R18-R19)

def _extend(sid, n, timeout=120):
    return api_json("POST", f"/v2/event-series/{sid}/extend",
                    {"additionalOccurrences": n}, timeout=timeout)


def check_extend(label, sid, n, tz):
    """Extend a series and check what it added against the model."""
    before = load_series(sid)
    if before is None:
        return [f"{label}: series {sid} is missing"]
    if not before["occurrences"]:
        return [f"{label}: series {sid} holds nothing to extend from"]

    status, payload = _extend(sid, n)
    if status != 200:
        return [f"{label}: extend returned HTTP {status} "
                f"{json.dumps(payload)[:400]}"]

    held = [o.local_date(tz) for o in before["occurrences"]]
    expected = model.extend(before["cfg"], min(held), held, n,
                            before["offset"])

    after = load_series(sid)
    old_ids = {o.occurrence_id for o in before["occurrences"]}
    added = [o for o in after["occurrences"] if o.occurrence_id not in old_ids]
    problems = compare_slots(f"{label}-added", added, expected, tz)
    missing = old_ids - {o.occurrence_id for o in after["occurrences"]}
    if missing:
        problems.append(
            f"{label}: extending removed occurrences {sorted(missing)}; it adds "
            "and does nothing else")
    for occ in before["occurrences"]:
        now = next((o for o in after["occurrences"]
                    if o.occurrence_id == occ.occurrence_id), None)
        if now is not None and now.epoch != occ.epoch:
            problems.append(
                f"{label}: extending moved existing occurrence "
                f"{occ.occurrence_id} from {fmt([occ.epoch], tz)[0]} to "
                f"{fmt([now.epoch], tz)[0]}")
    problems += [f"{label}: {v}" for v in model.violations(after["occurrences"], tz)]
    return problems


def rule_R18_extend_gap():
    """Extending fills a hole in the pattern before it appends past the end.

    hs-vacant-a is four New York Fridays with the second one absent. Walking
    the pattern from the series' earliest occurrence reaches 8 May before it
    reaches anything past 22 May, so two more occurrences are 8 and 29 May.
    Appending after the latest row gives 29 May and 5 June, which is the answer
    a series that happens to be contiguous cannot tell apart from the right
    one -- and every other fixture in this task is contiguous.
    """
    tz = ZoneInfo("America/New_York")
    before = load_series("hs-vacant-a")
    if before is None:
        return ["R18-extend-gap: fixture series hs-vacant-a is missing"]
    held = sorted(o.local_date(tz) for o in before["occurrences"])
    if held != [dt.date(2026, 5, 1), dt.date(2026, 5, 15), dt.date(2026, 5, 22)]:
        return [f"R18-extend-gap: fixture should hold 1, 15 and 22 May; store "
                f"holds {[d.isoformat() for d in held]}"]
    return check_extend("R18-extend-gap", "hs-vacant-a", 2, tz)


def rule_R19_extend_after_regenerate():
    """Extending a series a regenerate has already reshaped.

    A fortnightly series, its first occurrence published, then regenerated from
    a start date one week on. The published row is off the new pattern and is
    kept anyway, so it is both the series' earliest occurrence and a date the
    current pattern would never generate -- and the pattern the extension walks
    is the one measured from it, which for a fortnightly series is the opposite
    parity of weeks to the rows the regenerate just wrote. So the dates the
    extension adds land *between* the ones already there.

    Every shortcut gives a different answer: continuing from the latest
    occurrence, continuing from the start date the regenerate was given,
    continuing from the config, or appending without checking what is held.
    """
    tz = ZoneInfo("America/Los_Angeles")
    problems, state = created_case("R19-extend-regen", "week",
                                   "America/Los_Angeles",
                                   "2026-05-06T20:00:00Z", 68400,
                                   interval=2, selected=[3], count=4)
    if state is None:
        return problems
    sid = state["sid"]
    if len(state["occurrences"]) != 4:
        return problems + [
            f"R19-extend-regen: expected four occurrences, store holds "
            f"{len(state['occurrences'])}"]

    first = state["occurrences"][0]
    status, payload = api_json(
        "POST", f"/v2/event-series/{sid}/occurrences/{first.occurrence_id}/publish",
        {"eventId": "evt-published-003"})
    if status != 200:
        return problems + [f"R19-extend-regen: publish returned HTTP {status} "
                           f"{json.dumps(payload)[:400]}"]

    moved_start = "2026-05-13T20:00:00Z"
    published = load_series(sid)
    status, payload = _regenerate(sid, moved_start)
    if status != 200:
        return problems + [
            f"R19-extend-regen: regenerate returned HTTP {status} "
            f"{json.dumps(payload)[:400]}"]

    after = load_series(sid)
    expect = model.regenerate(published["cfg"], published["occurrences"],
                              start_instant(moved_start), published["offset"])
    problems += compare_slots("R19-extend-regen-regenerated",
                              after["occurrences"],
                              outcome_slots(expect, tz), tz)
    if not any(o.occurrence_id == first.occurrence_id
               for o in after["occurrences"]):
        return problems + [
            "R19-extend-regen: the published occurrence was destroyed, so the "
            "series has no off-pattern anchor left and the extension cannot be "
            "checked"]
    if problems:
        return problems

    return check_extend("R19-extend-regen", sid, 2, tz)


# ------------------------------------------------------------ concurrency (R20)

def coord(action, name, parties=1, hold=False, timeout_ms=15000, group=""):
    return api_json("POST", f"/internal/task/coord/{action}",
                    {"name": name, "group": group, "parties": parties,
                     "hold": hold, "timeoutMs": timeout_ms}, timeout=30)


def coord_status(name):
    status, payload = api_json(
        "GET", f"/internal/task/coord/status?name={name}", timeout=30)
    return payload if status == 200 else {}


def as_occurrences(outcome):
    """A regenerate outcome, expressed as the occurrence rows it leaves.

    Kept rows carry their real identity, their protection and their edit stamp
    with them; the inserted ones are fresh, unpublished and unedited, so they
    get placeholder ids. What a following scoped edit needs from them is which
    local date each is on and whether it has sold anything.
    """
    rows = list(outcome.kept)
    for i, slot in enumerate(outcome.inserted):
        rows.append(model.Occurrence(occurrence_id=f"_new{i}", epoch=slot.epoch))
    return rows


def race_round(label, sid, target_id, new_offset, start_iso, tz):
    """One scoped edit against one regenerate, on the same series, at once.

    Returns complaints. The two requests meet at a barrier inside the service
    rather than being fired off in the hope that they overlap: the edit's
    checkpoint and the regenerate's are armed onto one gate for two parties, so
    whichever arrives first parks until the other arrives and both then leave at
    the same instant, each with its work up to that point already done. That is
    the same mechanism R11 uses for two regenerates, and it is what makes the
    window overlap rather than the two requests happening to collide.

    Both orders are computed and either is accepted, because either is a real
    order. They differ, which is what makes the check worth running: the state
    records which of the two went second. A store holding neither is holding
    half of each plan.
    """
    before = load_series(sid)
    if before is None:
        return [f"{label}: series {sid} is missing"]
    if not any(o.occurrence_id == target_id for o in before["occurrences"]):
        return [f"{label}: occurrence {target_id} is not in the series"]

    coord("arm", "pre-regenerate", parties=2, hold=False, group="race")
    coord("arm", "pre-occurrence-edit", parties=2, hold=False, group="race")

    results = {}
    barrier = threading.Barrier(2)

    def do_regen():
        barrier.wait()
        results["regenerate"] = _regenerate(sid, start_iso, timeout=180)

    def do_edit():
        barrier.wait()
        results["edit"] = scope_patch(sid, target_id, new_offset, timeout=180)

    threads = [threading.Thread(target=do_regen, daemon=True),
               threading.Thread(target=do_edit, daemon=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(240)
    coord("reset", "pre-regenerate")

    if len(results) != 2:
        return [f"{label}: only {sorted(results)} returned"]
    for tag, (code, payload) in results.items():
        if code == 0:
            return [f"{label}: the {tag} killed the connection "
                    f"({str(payload)[:200]}); a contended request must fail "
                    "cleanly, not take the service down"]

    codes = {t: r[0] for t, r in results.items()}
    regen_ok = codes["regenerate"] == 200
    edit_ok = codes["edit"] == 200

    cfg, offset = before["cfg"], before["offset"]

    def after_regen(source):
        return as_occurrences(
            model.regenerate(cfg, source, start_instant(start_iso), offset))

    def after_edit(source):
        plan = model.scoped_edit(cfg, source, target_id, new_offset)
        out = []
        for o in source:
            moved = o.occurrence_id in plan.moved
            out.append(model.Occurrence(
                occurrence_id=o.occurrence_id,
                epoch=plan.expected_epoch(o),
                published_event_id=o.published_event_id,
                # An edit that reached a row leaves it individually edited,
                # which is what a following regenerate reads. R17 grades that
                # separately, so assuming it here is not assuming anything a
                # passing candidate has not already been required to do.
                edited=o.edited or moved,
                live_receipts=o.live_receipts))
        return out

    rows = before["occurrences"]
    try:
        if regen_ok and edit_ok:
            orders = {
                "regenerate then edit": after_edit(after_regen(rows)),
                "edit then regenerate": after_regen(after_edit(rows)),
            }
        elif regen_ok:
            orders = {"the regenerate alone, the edit having been refused":
                      after_regen(rows)}
        elif edit_ok:
            orders = {"the edit alone, the regenerate having been refused":
                      after_edit(rows)}
        else:
            return [f"{label}: neither request succeeded: {codes}"]
    except model.ModelError as e:
        return [f"{label}: model could not describe an order: {e}"]

    after = load_series(sid)
    got = sorted(o.epoch for o in after["occurrences"])
    for expected in orders.values():
        if got == sorted(o.epoch for o in expected):
            break
    else:
        lines = [f"{label}: the store holds a state no order produces "
                 f"(HTTP {codes})", f"    stored {fmt(got, tz)}"]
        for name, expected in orders.items():
            lines.append(f"    {name}: "
                         f"{fmt([o.epoch for o in expected], tz)}")
        return ["\n".join(lines)]

    problems = [f"{label}: {v}" for v in
                model.violations(after["occurrences"], tz)]
    for was in rows:
        if not was.sales_protected:
            continue
        now = next((o for o in after["occurrences"]
                    if o.occurrence_id == was.occurrence_id), None)
        if now is None:
            problems.append(
                f"{label}: paid occurrence {was.occurrence_id} was removed")
        elif now.epoch != was.epoch:
            problems.append(
                f"{label}: paid occurrence {was.occurrence_id} moved; neither "
                "a regenerate nor a scoped edit may touch it, in any order")
    return problems


def rule_R20_race_scope_and_regenerate():
    """A scoped edit and a regenerate arriving together serialise.

    Both rewrite the occurrence list of one series, so protecting only the
    regenerate leaves the pair unserialisable: it takes two participants to
    serialise. And two writers whose statements happen not to name a row in
    common have no conflict for the store to detect, so an implementation that
    wraps each request in a transaction and stops there can still interleave
    into a series holding half of each plan.

    Four rounds, each on its own series. The barrier makes the two windows
    overlap rather than leaving it to chance, and each round is arranged so
    that the overlap has something to fight over: the regenerate's start date
    moves the pattern, so it deletes and replaces rows the edit is in the
    middle of moving, and one occurrence of each series is published and one is
    published and paid, so what survives is decided rather than incidental.
    Four of them rather than one because the losing interleaving still has to
    be reached inside the overlap, and four independent attempts turn a likely
    catch into a reliable one.

    Both orders are accepted and they differ, so the check is exact rather than
    a range: whichever request went second decides the time of day the rows the
    regenerate appended are sitting at.
    """
    # Twenty rows per series rather than five. Both plans then spend
    # milliseconds writing instead of microseconds, so the overlap the barrier
    # guarantees is wide enough for an unprotected read to actually go stale
    # inside it. With five rows the window was real but usually missed.
    count = 20

    zones = [
        # (zone, series start, time of day, target index, paid index,
        #  regenerate start, new time of day)
        ("UTC", "2026-09-01T09:00:00Z", 43200, 1, 3,
         "2026-09-03T06:00:00Z", 3600),
        ("America/Chicago", "2026-09-01T18:00:00Z", 72000, 1, 3,
         "2026-09-03T18:00:00Z", 3600),
        ("Europe/Berlin", "2026-10-22T09:00:00Z", 75600, 1, 3,
         "2026-10-24T09:00:00Z", 5400),
        ("Australia/Lord_Howe", "2026-04-01T09:00:00Z", 68400, 1, 3,
         "2026-04-03T09:00:00Z", 6300),
    ]
    rounds = [zones[i % len(zones)] for i in range(8)]

    problems = []
    for n, (zone, start, offset, tgt_i, paid_i, regen_start,
            new_offset) in enumerate(rounds, 1):
        label = f"R20-race round {n} ({zone})"
        tz = ZoneInfo(zone)
        made, state = created_case(f"{label} setup", "day", zone, start,
                                   offset, count=count)
        if made:
            return problems + made
        if len(state["occurrences"]) != count:
            return problems + [
                f"{label}: expected {count} occurrences, store holds "
                f"{len(state['occurrences'])}"]

        sid = state["sid"]
        # The target has to survive the regenerate for the edit to have
        # anything to aim at whichever order wins, so it is published. The paid
        # row is what neither request may touch in either order.
        for idx, event in ((tgt_i, "evt-published-002"),
                           (paid_i, "evt-published-001")):
            occ = state["occurrences"][idx]
            status, payload = api_json(
                "POST",
                f"/v2/event-series/{sid}/occurrences/{occ.occurrence_id}/publish",
                {"eventId": event})
            if status != 200:
                return problems + [
                    f"{label}: publishing {occ.occurrence_id} returned HTTP "
                    f"{status} {json.dumps(payload)[:400]}"]

        armed = load_series(sid)
        paid = [o for o in armed["occurrences"] if o.sales_protected]
        if len(paid) != 1:
            return problems + [
                f"{label}: the round needs exactly one paid occurrence and has "
                f"{[o.occurrence_id for o in paid]}; evt-published-001 is the "
                "fixture's event with live sales"]

        target = state["occurrences"][tgt_i]
        got = race_round(label, sid, target.occurrence_id, new_offset,
                         regen_start, tz)
        # Stop at the first bad round: later ones would be describing the
        # wreckage rather than a second independent fault.
        if got:
            return problems + got
    return problems


# ------------------------------------------------- the cross product (R21-R24)
#
# Everything above grades one concern at a time, on a series shaped to make that
# concern visible. What follows grades the concerns together, because they
# combine: a month-end clamp that lands on a local time that does not exist, in
# a zone whose transition is not an hour wide, on a series that is being
# regenerated while an edit is in flight and one of its occurrences has taken
# money. Each of those is already required separately; a solver who has each
# rule in its own branch still has to make the branches agree.
#
# Nothing here is a new requirement. Every case is a repeat configuration the
# API already accepts, in a zone the tz database already has, and every answer
# comes from the same independent model the rules above compare against -- so
# none of it can be right by having guessed a convention, and none of it needs a
# name, a spelling or a status code that is not already written down.

# Zones chosen for the shapes of their transitions rather than for variety:
# whole-hour in both directions, a half hour (Lord Howe), three quarters of an
# hour (Chatham), a zone whose standard offset is zero so a nonexistent local
# time normalises the other way (Lisbon), a zone whose winter is the negative
# adjustment (Dublin), a southern zone whose spring transition happens at
# midnight so that a series kept at local midnight has no local time to sit at
# (Santiago), a half-hour zone that never moves (Kathmandu), and a zone whose
# offset is not a whole number of hours in either season (St John's).
CROSS_ZONES = [
    "UTC",
    "America/Los_Angeles",
    "America/New_York",
    "America/St_Johns",
    "America/Santiago",
    "Europe/Lisbon",
    "Europe/Berlin",
    "Europe/Dublin",
    "Asia/Kathmandu",
    "Australia/Lord_Howe",
    "Pacific/Chatham",
    "Pacific/Auckland",
]

# Repeat configurations. `end_days` means an onDate end that many days after
# the anchor, computed per case so that the end rule bites wherever the anchor
# lands rather than only in one of the zones.
CROSS_SHAPES = [
    ("day", dict(count=9)),
    ("day", dict(interval=2, count=7)),
    ("day", dict(interval=5, count=5)),
    ("day", dict(end_days=13)),
    ("week", dict(selected=[0, 3], count=8)),
    ("week", dict(selected=[1, 2, 4, 6], count=11)),
    ("week", dict(interval=2, selected=[5], count=5)),
    ("week", dict(selected=[2, 5], end_days=41)),
    ("month", dict(count=7)),
    ("month", dict(interval=2, count=5)),
]

# Anchors placed on the weeks the zones above change offset, so that most of
# the cross product crosses a transition rather than only the cases written to.
CROSS_ANCHORS = [
    "2026-03-05T12:00:00Z",
    "2026-10-22T12:00:00Z",
    "2026-01-31T12:00:00Z",
    "2026-04-01T12:00:00Z",
    "2026-09-24T12:00:00Z",
]

# Local times of day. Midnight and one minute to midnight are here because a
# transition at either end of the day is where holding the wall clock fixed and
# holding the calendar date fixed pull against each other.
CROSS_OFFSETS = [0, 3600, 5400, 8100, 9000, 43200, 68400, 86340]


def cross_cases():
    """The (zone, shape, anchor, time of day) cross product, deterministically.

    Every zone meets every shape. The anchor and the time of day are picked by
    position rather than by another loop, which keeps the set to something that
    can be graded in a minute while still giving each zone several anchors and
    each shape several times of day.
    """
    cases = []
    for zi, zone in enumerate(CROSS_ZONES):
        for si, (unit, shape) in enumerate(CROSS_SHAPES):
            anchor = CROSS_ANCHORS[(zi + si) % len(CROSS_ANCHORS)]
            offset = CROSS_OFFSETS[(zi * 3 + si) % len(CROSS_OFFSETS)]
            kw = dict(shape)
            end_days = kw.pop("end_days", None)
            if end_days is not None:
                kw["end_date_iso"] = (
                    start_instant(anchor) + dt.timedelta(days=end_days)
                ).astimezone(UTC).isoformat().replace("+00:00", "Z")
            label = f"R21-{zone.replace('/', '-')}-{unit}-{si}"
            cases.append((label, unit, zone, anchor, offset, kw))
    return cases


def rule_R21_cross_product():
    """Every zone against every repeat configuration.

    One rule, many situations. A series is created for each pair and its stored
    occurrences are compared against the model, so what is graded is the same
    thing R1 to R7 grade -- where the occurrences are -- across a set wide
    enough that an implementation which is right about the cases it thought of
    and wrong about one interaction is caught by the interaction.

    The set is fixed, not sampled: the same cases run every time, in the same
    order, with the same anchors and the same times of day.
    """
    problems = []
    for label, unit, zone, anchor, offset, kw in cross_cases():
        got, state = created_case(label, unit, zone, anchor, offset, **kw)
        problems += got
        if state is None:
            # A create that did not land leaves nothing to say about the rest
            # of the set, and repeating the same complaint a hundred times
            # makes the detail file unreadable.
            if len(problems) > 12:
                problems.append(
                    "R21: stopping after the first dozen failures; the "
                    "remaining cases would report the same thing")
                return problems
            continue
        if len(problems) > 12:
            problems.append(
                "R21: stopping after the first dozen failures; the remaining "
                "cases would report the same thing")
            return problems
    return problems


def publish_onto(sid, occurrence_id, event_id):
    """Publish one occurrence onto a fixture event, or say why not."""
    status, payload = api_json(
        "POST",
        f"/v2/event-series/{sid}/occurrences/{occurrence_id}/publish",
        {"eventId": event_id})
    if status != 200:
        return (f"publishing {occurrence_id} onto {event_id} returned HTTP "
                f"{status} {json.dumps(payload)[:400]}")
    return None


def hand_edit(sid, occurrence_id, offset, name):
    """PATCH one occurrence with no scope: an ordinary individual edit."""
    form = dict(FORM_BASE, name=name, startTimeOffset=offset)
    status, payload = api_json(
        "PATCH", f"/v2/event-series/{sid}/occurrences/{occurrence_id}",
        {"formData": form})
    if status != 200:
        return (f"editing {occurrence_id} returned HTTP {status} "
                f"{json.dumps(payload)[:400]}")
    return None


# (zone, unit, anchor, time of day, shape, index published and paid, index
#  published and unpaid, index edited by hand, the regenerate's start date)
#
# Each row puts a paid occurrence, a published one and a hand-edited one on the
# same series and then moves the pattern out from under all three. The shapes
# are the ones where a date is already hard on its own: a month end that clamps,
# a week that crosses a transition, a series whose time of day does not exist on
# one of its dates.
REGEN_CROSS = [
    ("Europe/Lisbon", "month", "2026-01-29T12:00:00Z", 3900, dict(count=6),
     1, 3, 4, "2026-02-27T12:00:00Z"),
    ("America/New_York", "month", "2026-01-31T12:00:00Z", 68400, dict(count=6),
     0, 2, 3, "2026-03-30T12:00:00Z"),
    ("America/Los_Angeles", "week", "2026-03-01T12:00:00Z", 9000,
     dict(selected=[0, 3], count=8), 2, 4, 5, "2026-03-04T12:00:00Z"),
    ("Australia/Lord_Howe", "week", "2026-03-29T12:00:00Z", 6300,
     dict(selected=[0, 2], count=8), 1, 3, 5, "2026-03-31T12:00:00Z"),
    ("Pacific/Chatham", "day", "2026-04-01T12:00:00Z", 8100, dict(count=8),
     1, 2, 5, "2026-04-03T12:00:00Z"),
    ("America/Santiago", "day", "2026-09-03T12:00:00Z", 0, dict(count=8),
     0, 3, 6, "2026-09-05T12:00:00Z"),
    ("Europe/Dublin", "day", "2026-10-23T12:00:00Z", 5400, dict(interval=2,
                                                                count=7),
     1, 2, 4, "2026-10-25T12:00:00Z"),
    ("UTC", "month", "2028-01-31T12:00:00Z", 43200, dict(interval=2, count=6),
     0, 1, 4, "2028-02-29T12:00:00Z"),
]


def rule_R22_regenerate_cross():
    """Regenerate, with everything that survives a regenerate on one series.

    Each round holds a paid occurrence, a published one that has sold nothing,
    a row edited by hand and a handful of rows that are none of those, and then
    the pattern is moved so that no row is where the new plan wants one. What
    the store ends up holding is decided by four rules at once -- publication
    keeps a row, an edit keeps a row only while its date is still on the
    pattern, the plan is the pattern in the series' own zone with its clamps,
    and a paid row may not be touched at all -- and the model is the only place
    all four are put together.
    """
    problems = []
    for zone, unit, anchor, offset, shape, paid_i, pub_i, edit_i, regen_start \
            in REGEN_CROSS:
        label = f"R22-regen-{zone.replace('/', '-')}-{unit}"
        tz = ZoneInfo(zone)
        made, state = created_case(f"{label} setup", unit, zone, anchor,
                                   offset, **shape)
        if made:
            problems += made
            continue
        rows = state["occurrences"]
        if len(rows) <= max(paid_i, pub_i, edit_i):
            problems.append(
                f"{label}: the round needs {max(paid_i, pub_i, edit_i) + 1} "
                f"occurrences and the series holds {len(rows)}")
            continue
        sid = state["sid"]

        err = publish_onto(sid, rows[paid_i].occurrence_id, "evt-published-001")
        err = err or publish_onto(sid, rows[pub_i].occurrence_id,
                                  "evt-published-002")
        err = err or hand_edit(sid, rows[edit_i].occurrence_id, offset,
                               "Edited Before The Regenerate")
        if err:
            problems.append(f"{label}: {err}")
            continue

        armed = load_series(sid)
        paid = [o for o in armed["occurrences"] if o.sales_protected]
        if len(paid) != 1:
            problems.append(
                f"{label}: the round needs exactly one paid occurrence and has "
                f"{[o.occurrence_id for o in paid]}")
            continue
        stamped = next((o for o in armed["occurrences"]
                        if o.occurrence_id == rows[edit_i].occurrence_id), None)
        if stamped is None or not stamped.edited:
            problems.append(
                f"{label}: an individual edit must be recorded on the "
                "occurrence, and this one is not, so the regenerate that "
                "follows cannot tell it from a row it generated itself")
            continue

        status, payload = _regenerate(sid, regen_start)
        if status != 200:
            problems.append(f"{label}: regenerate returned HTTP {status} "
                            f"{json.dumps(payload)[:400]}")
            continue

        after = load_series(sid)
        expect = model.regenerate(armed["cfg"], armed["occurrences"],
                                  start_instant(regen_start), armed["offset"])
        problems += compare_slots(label, after["occurrences"],
                                  outcome_slots(expect, tz), tz)
        problems += [f"{label}: {v}" for v in
                     model.violations(after["occurrences"], tz)]

        kept = {o.occurrence_id for o in after["occurrences"]}
        for occ in armed["occurrences"]:
            if occ.published and occ.occurrence_id not in kept:
                problems.append(
                    f"{label}: published occurrence {occ.occurrence_id} was "
                    "destroyed by a regenerate")
            if occ.sales_protected:
                now = next((o for o in after["occurrences"]
                            if o.occurrence_id == occ.occurrence_id), None)
                if now is None or now.epoch != occ.epoch:
                    problems.append(
                        f"{label}: the paid occurrence {occ.occurrence_id} was "
                        "moved or removed by a regenerate")
        if len(problems) > 12:
            return problems
    return problems


# (zone, unit, anchor, time of day, shape, paid index, scope target index,
#  the time of day the scope moves rows to, how many to extend by)
SCOPE_CROSS = [
    ("Europe/Lisbon", "month", "2026-01-29T12:00:00Z", 68400, dict(count=6),
     4, 1, 3900, 3),
    ("America/Los_Angeles", "day", "2026-03-05T12:00:00Z", 43200, dict(count=7),
     5, 1, 9000, 4),
    ("Australia/Lord_Howe", "day", "2026-04-02T12:00:00Z", 43200, dict(count=7),
     5, 1, 6300, 3),
    ("Pacific/Chatham", "week", "2026-09-20T12:00:00Z", 43200,
     dict(selected=[0, 3], count=8), 6, 2, 13500, 3),
    ("America/St_Johns", "month", "2026-01-31T12:00:00Z", 43200, dict(count=6),
     4, 1, 5400, 2),
    ("Europe/Dublin", "week", "2026-10-18T12:00:00Z", 43200,
     dict(selected=[0, 2, 5], count=9), 7, 2, 3600, 4),
]


def rule_R23_scope_then_extend_cross():
    """A scoped edit, a regenerate and an extend, one after another, on a
    series where every date is already awkward.

    The three write paths share one question -- which local date is a row on --
    and they answer it from three different places: an edit reads the date off
    the row, a regenerate reads it off the pattern, and an extend walks the
    pattern from the series' own anchor. A series whose dates are clamped, or
    whose time of day does not exist on one of them, is where those three
    answers come apart, and running them in sequence on the same series is what
    makes an implementation that keeps three ideas of a date disagree with
    itself.
    """
    problems = []
    for zone, unit, anchor, offset, shape, paid_i, target_i, new_offset, more \
            in SCOPE_CROSS:
        label = f"R23-chain-{zone.replace('/', '-')}-{unit}"
        tz = ZoneInfo(zone)
        made, state = created_case(f"{label} setup", unit, zone, anchor,
                                   offset, **shape)
        if made:
            problems += made
            continue
        rows = state["occurrences"]
        if len(rows) <= max(paid_i, target_i):
            problems.append(
                f"{label}: the round needs {max(paid_i, target_i) + 1} "
                f"occurrences and the series holds {len(rows)}")
            continue
        sid = state["sid"]

        err = publish_onto(sid, rows[paid_i].occurrence_id, "evt-published-001")
        if err:
            problems.append(f"{label}: {err}")
            continue

        armed = load_series(sid)
        if not any(o.sales_protected for o in armed["occurrences"]):
            problems.append(
                f"{label}: publishing onto the fixture's event with live sales "
                "left no paid occurrence, so the protection half of the round "
                "cannot run")
            continue

        # 1. the scoped edit, which must step over the paid row and resolve
        #    every other row's own local date afresh.
        problems += check_scope(f"{label}-scope", sid,
                                rows[target_i].occurrence_id, new_offset,
                                armed, tz)

        # 2. a regenerate that leaves the pattern where it is, so the rows the
        #    scope moved are still on it and must survive with their new times.
        edited = load_series(sid)
        status, payload = _regenerate(sid, anchor)
        if status != 200:
            problems.append(f"{label}: regenerate returned HTTP {status} "
                            f"{json.dumps(payload)[:400]}")
            continue
        regenerated = load_series(sid)
        expect = model.regenerate(edited["cfg"], edited["occurrences"],
                                  start_instant(anchor), edited["offset"])
        problems += compare_slots(f"{label}-regen", regenerated["occurrences"],
                                  outcome_slots(expect, tz), tz)

        # 3. and an extend, which walks the same lattice from the series' own
        #    earliest date and must not repeat one of the dates already held.
        problems += check_extend(f"{label}-extend", sid, more, tz)
        if len(problems) > 12:
            return problems
    return problems


# (zone, unit, anchor, time of day, shape, target index, paid index,
#  the regenerate's start date, the time of day the edit moves rows to)
RACE_CROSS = [
    ("Europe/Lisbon", "month", "2026-01-29T12:00:00Z", 68400, dict(count=14),
     1, 3, "2026-02-27T12:00:00Z", 3900),
    ("America/Los_Angeles", "week", "2026-03-01T12:00:00Z", 43200,
     dict(selected=[0, 1, 3, 5], count=20), 1, 3, "2026-03-04T12:00:00Z", 9000),
    ("Pacific/Chatham", "day", "2026-09-24T12:00:00Z", 43200, dict(count=20),
     1, 3, "2026-09-26T12:00:00Z", 13500),
    ("America/St_Johns", "month", "2026-01-31T12:00:00Z", 43200,
     dict(count=14), 1, 3, "2026-03-30T12:00:00Z", 5400),
]


def rule_R24_race_cross():
    """The same race as R20, on series whose dates are hard to get right.

    R20 races a scoped edit against a regenerate on daily series, where every
    date is a day after the last one and the only thing at stake is
    serialisation. Here the same race runs on a month-end series that clamps, a
    weekly series on four days across a transition, a zone that moves by
    three quarters of an hour and one that moves by half. Serialising is
    necessary and no longer sufficient: whichever request goes second has to be
    right about the dates as well, and the two accepted orders differ.
    """
    problems = []
    for n, (zone, unit, anchor, offset, shape, tgt_i, paid_i, regen_start,
            new_offset) in enumerate(RACE_CROSS, 1):
        label = f"R24-race round {n} ({zone} {unit})"
        tz = ZoneInfo(zone)
        made, state = created_case(f"{label} setup", unit, zone, anchor,
                                   offset, **shape)
        if made:
            return problems + made
        rows = state["occurrences"]
        if len(rows) <= max(tgt_i, paid_i):
            return problems + [
                f"{label}: the round needs {max(tgt_i, paid_i) + 1} "
                f"occurrences and the series holds {len(rows)}"]
        sid = state["sid"]

        err = publish_onto(sid, rows[tgt_i].occurrence_id, "evt-published-002")
        err = err or publish_onto(sid, rows[paid_i].occurrence_id,
                                  "evt-published-001")
        if err:
            return problems + [f"{label}: {err}"]

        armed = load_series(sid)
        paid = [o for o in armed["occurrences"] if o.sales_protected]
        if len(paid) != 1:
            return problems + [
                f"{label}: the round needs exactly one paid occurrence and has "
                f"{[o.occurrence_id for o in paid]}"]

        got = race_round(label, sid, rows[tgt_i].occurrence_id, new_offset,
                         regen_start, tz)
        if got:
            return problems + got
    return problems


# ------------------------------------------- independent dimensions (R25-R27)
#
# R1 to R24 are largely one kind of knowledge wearing many hats. Get the
# lattice right -- local calendar dates in the series' own zone, a fixed time of
# day, clamping, and the two daylight-saving resolutions -- and most of R21's
# hundred and twenty situations fall out together. Breadth like that multiplies
# work rather than difficulty: under a binary reward the pass rate is the
# product of the per-scenario rates only where a solver cannot unlock the
# scenarios together.
#
# What follows is deliberately not date arithmetic. A general rule about
# offsets says nothing about which row owns a local date once several rows have
# a claim on it, nothing about what a scoped edit owes an occurrence that has
# already been paid for, and nothing about what an extend in flight sees when a
# rebuild lands underneath it. Those are three separate things to know, and each
# is placed on dates that are hard on their own, so a candidate has to hold the
# lattice and the new rule at the same time rather than one at a time.


def publish_rows(sid, rows, pairs):
    """Publish rows[i] onto event e for each (i, e). Returns complaints."""
    problems = []
    for idx, event in pairs:
        if idx >= len(rows):
            problems.append(f"setup: the series holds {len(rows)} occurrences "
                            f"and the round needs index {idx}")
            continue
        err = publish_onto(sid, rows[idx].occurrence_id, event)
        if err:
            problems.append(f"setup: {err}")
    return problems


def edit_rows(sid, rows, indices, offset):
    """Hand-edit rows[i] for each i, keeping the time of day. Complaints."""
    problems = []
    for idx in indices:
        if idx >= len(rows):
            problems.append(f"setup: the series holds {len(rows)} occurrences "
                            f"and the round needs index {idx}")
            continue
        err = hand_edit(sid, rows[idx].occurrence_id, offset,
                        f"Hand Edit {idx}")
        if err:
            problems.append(f"setup: {err}")
    return problems


def check_identity(label, sid, start_iso, tz, form_check=True):
    """Rebuild, then ask which row is sitting on which local date.

    Everything else in this grader asks where the occurrences are. This asks
    who they are, which is a different question and is not answered by getting
    the dates right. A rebuild has to match the rows it is keeping against the
    plan it is about to write: a kept row owns its local date, so no slot is
    inserted alongside it, and it keeps its own instant rather than being reset
    to whatever the plan wanted for that date. Getting that wrong shows up as a
    date carrying two occurrences, or as a published row quietly reissued under
    a new identity with the event link copied across -- and in both cases the
    list of instants still reads exactly right.
    """
    before = load_series(sid)
    if before is None:
        return [f"{label}: series {sid} is missing"]

    status, payload = _regenerate(sid, start_iso)
    if status != 200:
        return [f"{label}: regenerate returned HTTP {status} "
                f"{json.dumps(payload)[:400]}"]

    after = load_series(sid)
    try:
        outcome = model.regenerate(before["cfg"], before["occurrences"],
                                   start_instant(start_iso), before["offset"])
    except model.ModelError as e:
        return [f"{label}: model could not describe the rebuild: {e}"]

    problems = compare_slots(label, after["occurrences"],
                             outcome_slots(outcome, tz), tz)
    problems += [f"{label}: {v}" for v in
                 model.violations(after["occurrences"], tz)]

    now_by_id = {o.occurrence_id: o for o in after["occurrences"]}
    was_ids = {o.occurrence_id for o in before["occurrences"]}

    for occ in outcome.kept:
        why = "published" if occ.published else "edited, on a date still wanted"
        row = now_by_id.get(occ.occurrence_id)
        if row is None:
            problems.append(
                f"{label}: occurrence {occ.occurrence_id} ({why}) had to "
                "survive the rebuild and is gone. A row on the same date under "
                "a new identity is a different occurrence: the ticket that "
                "named the old one no longer resolves")
            continue
        if row.epoch != occ.epoch:
            problems.append(
                f"{label}: surviving occurrence {occ.occurrence_id} ({why}) "
                f"was moved from {fmt([occ.epoch], tz)[0]} to "
                f"{fmt([row.epoch], tz)[0]}; a kept row keeps its own instant "
                "rather than taking the one the plan wanted for its date")
        if row.published_event_id != occ.published_event_id:
            problems.append(
                f"{label}: surviving occurrence {occ.occurrence_id} lost its "
                f"event link ({occ.published_event_id} became "
                f"{row.published_event_id})")
        if form_check and row.form_data_digest != occ.form_data_digest:
            problems.append(
                f"{label}: surviving occurrence {occ.occurrence_id} had its "
                "form data rewritten by the rebuild")

    for occ in outcome.dropped:
        if occ.occurrence_id in now_by_id:
            problems.append(
                f"{label}: occurrence {occ.occurrence_id} survived the "
                "rebuild; it is neither published nor a hand edit whose date "
                "the pattern still wants, so it is one of the rows a rebuild "
                "replaces")

    fresh = [o for o in after["occurrences"] if o.occurrence_id not in was_ids]
    if len(fresh) != len(outcome.inserted):
        problems.append(
            f"{label}: the rebuild wrote {len(fresh)} new occurrences and the "
            f"plan leaves room for {len(outcome.inserted)}; the difference is "
            "local dates claimed twice or claimed by nobody")
    for row in fresh:
        if row.published_event_id is not None:
            problems.append(
                f"{label}: newly generated occurrence {row.occurrence_id} "
                "arrived already linked to an event")
    return problems


# Each row builds one series, arranges a particular set of claims on its dates,
# and then moves the pattern out from under them.
#
#   (zone, unit, anchor, time of day, shape, [(index, event) to publish],
#    [indices to hand-edit], index to scope from or None, the scope's new time
#    of day, the rebuild's start date)
#
# evt-published-001, -004 and -005 carry live sales; -002 and -003 carry none.
IDENTITY_CROSS = [
    # A published row on February's clamped date, which the rebuild also wants:
    # the row owns the date and no slot is inserted beside it. It is also
    # hand-edited, so it carries a template of its own rather than the series'
    # -- a night that was published and then given its own door time. A rebuild
    # driven from the series template overwrites that and leaves every date
    # right.
    ("Europe/Lisbon", "month", "2026-01-29T12:00:00Z", 3900, dict(count=6),
     [(1, "evt-published-002")], [1, 3], None, 0, "2026-01-29T12:00:00Z"),
    # A hand edit on 01:45, which on 5 April in Lord Howe happens twice. The
    # row is still on the pattern, so it stays -- at the instant it already
    # holds, not at whichever of the two the plan would have chosen.
    ("Australia/Lord_Howe", "week", "2026-03-22T12:00:00Z", 6300,
     dict(selected=[0], count=6), [(0, "evt-published-003")], [2], None, 0,
     "2026-03-22T12:00:00Z"),
    # Published rows the pattern has walked away from: kept regardless, off the
    # lattice, with the plan's own dates written around them.
    ("America/St_Johns", "month", "2026-01-31T12:00:00Z", 43200,
     dict(count=6), [(0, "evt-published-002"), (2, "evt-published-001")], [],
     None, 0, "2026-03-30T12:00:00Z"),
    # Hand edits the pattern has walked away from: dropped, because an edit
    # keeps a row only while the pattern still wants its date.
    ("America/Santiago", "day", "2026-09-03T12:00:00Z", 0, dict(count=8),
     [(1, "evt-published-003")], [4, 5], None, 0, "2026-09-06T12:00:00Z"),
    # A scoped edit first, so a run of rows is edited and sitting at a time of
    # day the template no longer names, and then a rebuild that leaves the
    # pattern where it is. Every moved row is still on its own local date, so
    # every one survives -- carrying the edit's time of day, which is exactly
    # what a rebuild driven from the template overwrites.
    ("Pacific/Chatham", "week", "2026-09-20T12:00:00Z", 43200,
     dict(selected=[0, 3], count=8), [(1, "evt-published-001")], [], 2, 8100,
     "2026-09-20T12:00:00Z"),
    # A paid row the pattern has walked away from. Publication alone would keep
    # it; the money means nothing may touch it under any rule.
    ("Europe/Dublin", "day", "2026-10-22T12:00:00Z", 5400,
     dict(interval=2, count=7), [(1, "evt-published-001")], [3], None, 0,
     "2026-10-27T12:00:00Z"),
    # Survivors on adjacent dates across a transition, one published and one
    # edited, with the plan wanting both.
    ("Pacific/Auckland", "week", "2026-04-01T12:00:00Z", 9000,
     dict(selected=[0, 1, 3, 6], count=12),
     [(2, "evt-published-002")], [3], None, 0, "2026-04-01T12:00:00Z"),
    # A zone that never moves, on a month end, with a paid row that has also
    # been edited by hand and two more hand edits, all on dates the rebuild
    # wants. Nothing here is about offsets at all, which is the reason it is in
    # the list.
    ("Asia/Kathmandu", "month", "2028-01-31T12:00:00Z", 68400,
     dict(interval=1, count=6), [(1, "evt-published-004")], [1, 2, 3], None, 0,
     "2028-01-31T12:00:00Z"),
]


def rule_R25_survivor_identity():
    """Which occurrence owns which local date once a rebuild has run.

    Eight series, each carrying a different mixture of claims -- published,
    published and paid, hand-edited, moved by an earlier scoped edit,
    untouched -- on dates that are awkward for their own reasons. The rebuild
    then either wants the date a survivor sits on or has walked away from it,
    and both cases appear for every kind of survivor.
    """
    problems = []
    for (zone, unit, anchor, offset, shape, publish, edits, scope_from,
         scope_offset, regen_start) in IDENTITY_CROSS:
        label = f"R25-identity-{zone.replace('/', '-')}-{unit}"
        tz = ZoneInfo(zone)
        made, state = created_case(f"{label} setup", unit, zone, anchor,
                                   offset, **shape)
        if made:
            problems += made
            if len(problems) > 12:
                return problems
            continue
        sid, rows = state["sid"], state["occurrences"]

        setup = publish_rows(sid, rows, publish)
        setup += edit_rows(sid, rows, edits, offset)
        if not setup and scope_from is not None:
            status, payload = scope_patch(sid, rows[scope_from].occurrence_id,
                                          scope_offset)
            if status != 200:
                setup.append(f"scoped edit returned HTTP {status} "
                             f"{json.dumps(payload)[:400]}")
        if setup:
            problems += [f"{label}: {s}" for s in setup]
            if len(problems) > 12:
                return problems
            continue

        problems += check_identity(label, sid, regen_start, tz)
        if len(problems) > 12:
            return problems
    return problems


# The five events the fixture provides and what each is worth. Only the live
# count matters; how an item stopped being live does not.
#
#   evt-published-001  two items, live by every clause
#   evt-published-004  one item, live
#   evt-published-005  three items: one pending, one refunded, and one whose
#                      holder has *asked* for a refund and not been given one.
#                      That last is still money -- nobody has been paid back and
#                      the ticket still admits its holder -- and it is the only
#                      place in the fixture where "not refunded" and "no refund
#                      status at all" give different answers. Every surviving
#                      sibling query in the tree writes the first of those.
#   evt-published-002  three items: one pending, one refunded, one abandoned
#   evt-published-003  no items at all
MONEY_EVENTS = [
    ("evt-published-001", True),
    ("evt-published-004", True),
    ("evt-published-005", True),
    ("evt-published-002", False),
    ("evt-published-003", False),
]


def money_series(label, zone, unit, anchor, offset, shape):
    """A series with one occurrence published onto each of the five events."""
    made, state = created_case(f"{label} setup", unit, zone, anchor, offset,
                               **shape)
    if made:
        return made, None
    rows = state["occurrences"]
    if len(rows) < len(MONEY_EVENTS):
        return [f"{label}: the round needs {len(MONEY_EVENTS)} occurrences "
                f"and the series holds {len(rows)}"], None
    setup = publish_rows(state["sid"], rows,
                         [(i, e) for i, (e, _) in enumerate(MONEY_EVENTS)])
    if setup:
        return [f"{label}: {s}" for s in setup], None

    armed = load_series(state["sid"])
    live = {o.occurrence_id for o in armed["occurrences"] if o.sales_protected}
    want = {rows[i].occurrence_id
            for i, (_, paid) in enumerate(MONEY_EVENTS) if paid}
    if live != want:
        return [f"{label}: the store disagrees with the fixture about which "
                f"occurrences carry money: expected {sorted(want)}, the "
                f"receipt items say {sorted(live)}"], None
    armed["sid"] = state["sid"]
    armed["rows"] = rows
    return [], armed


def rule_R26_money_across_operations():
    """One question about money, asked by all four paths that write a series.

    Whether an occurrence is carrying money is a single predicate, and four
    different requests need the answer: a delete refuses, a scoped edit steps
    over, a rebuild keeps, an extend counts the date as already held. An
    implementation that grew the predicate where it first needed it and nowhere
    else passes one of these and fails the others, and it fails silently --
    every date is still exactly where it should be.

    Each path runs against a series whose dates are hard on their own: a month
    end that clamps, a morning that happens twice, an offset at neither a whole
    nor a half hour, and a transition that swallows the time of day. Five
    occurrences of each are published, onto events that between them cover
    every way a receipt item can fail to be money -- pending, refunded,
    abandoned, and no items at all.
    """
    problems = []

    # --- a delete refuses exactly where money would be stranded ------------
    label = "R26-delete"
    tz = ZoneInfo("Europe/Lisbon")
    made, state = money_series(label, "Europe/Lisbon", "month",
                               "2026-01-29T12:00:00Z", 3900, dict(count=6))
    if made:
        problems += made
    else:
        sid = state["sid"]
        for i, (event, paid) in enumerate(MONEY_EVENTS):
            oid = state["rows"][i].occurrence_id
            status, payload = api_json(
                "DELETE", f"/v2/event-series/{sid}/occurrences/{oid}")
            want = 409 if paid else 200
            if status != want:
                held = "it has taken money" if paid else "it has taken none"
                problems.append(
                    f"{label}: deleting the occurrence published onto {event} "
                    f"returned HTTP {status}, expected {want} ({held}) "
                    f"{json.dumps(payload)[:200]}")
            after = load_series(sid)
            present = any(o.occurrence_id == oid for o in after["occurrences"])
            if paid and not present:
                problems.append(
                    f"{label}: the occurrence published onto {event} was "
                    "removed although it has taken money")
            if not paid and present:
                problems.append(
                    f"{label}: the occurrence published onto {event} survived "
                    "a delete, and nothing has been paid for it")
        problems += [f"{label}: {v}" for v in
                     model.violations(load_series(sid)["occurrences"], tz)]

    # --- a scoped edit steps over the same rows ----------------------------
    label = "R26-scope"
    tz = ZoneInfo("Australia/Lord_Howe")
    made, state = money_series(label, "Australia/Lord_Howe", "week",
                               "2026-03-22T12:00:00Z", 6300,
                               dict(selected=[0], count=6))
    if made:
        problems += made
    else:
        problems += check_scope(label, state["sid"],
                                state["rows"][0].occurrence_id, 9000,
                                state, tz)

    # --- a rebuild keeps every published row, paid or not ------------------
    label = "R26-regenerate"
    tz = ZoneInfo("America/St_Johns")
    made, state = money_series(label, "America/St_Johns", "month",
                               "2026-01-31T12:00:00Z", 43200, dict(count=6))
    if made:
        problems += made
    else:
        # Not the form-data half: that a survivor keeps its own template
        # across a rebuild is R25's question, and asking it here as well would
        # leave neither rule able to fail on its own.
        problems += check_identity(label, state["sid"],
                                   "2026-03-30T12:00:00Z", tz, form_check=False)

    # --- an extend counts their dates as already held ----------------------
    #
    # A hole is opened first, by removing a published row that has taken
    # nothing, and an attempt is made to open a second one where money is
    # sitting. The extend that follows has to reach past a date it still holds
    # only because a delete was refused, and fill the one it does not.
    label = "R26-extend"
    tz = ZoneInfo("Pacific/Chatham")
    made, state = money_series(label, "Pacific/Chatham", "week",
                               "2026-09-20T12:00:00Z", 9900,
                               dict(selected=[0, 3], count=6))
    if made:
        problems += made
    else:
        sid = state["sid"]
        for i in (0, 3):
            event, paid = MONEY_EVENTS[i]
            oid = state["rows"][i].occurrence_id
            status, _ = api_json(
                "DELETE", f"/v2/event-series/{sid}/occurrences/{oid}")
            want = 409 if paid else 200
            if status != want:
                problems.append(
                    f"{label}: clearing a date before the extend, the "
                    f"occurrence published onto {event} answered HTTP "
                    f"{status} and had to answer {want}")
        problems += check_extend(label, sid, 3, tz)
    return problems


# ------------------------------------------------------------ interleavings
#
# R11 and R20 race two regenerates, and a regenerate against a scoped edit. The
# other write paths contend too, and they contend differently. An extend
# decides which dates the series is missing and then writes them, so a rebuild
# landing between the decision and the write turns a right answer into one that
# was true of a series which no longer exists. A publish and a delete both
# change what a rebuild is allowed to keep, in opposite directions.

def _apply_regen(cfg, offset, rows, start_iso):
    return as_occurrences(
        model.regenerate(cfg, rows, start_instant(start_iso), offset))


def _apply_scope(cfg, rows, target_id, new_offset):
    plan = model.scoped_edit(cfg, rows, target_id, new_offset)
    return [model.Occurrence(
        occurrence_id=o.occurrence_id,
        epoch=plan.expected_epoch(o),
        published_event_id=o.published_event_id,
        form_data_digest=o.form_data_digest,
        edited=o.edited or o.occurrence_id in plan.moved,
        live_receipts=o.live_receipts) for o in rows]


def _apply_extend(cfg, offset, rows, additional, tz):
    held = [o.local_date(tz) for o in rows]
    if not held:
        raise model.ModelError("a series with no occurrences cannot extend")
    slots = model.extend(cfg, min(held), held, additional, offset)
    return list(rows) + [
        model.Occurrence(occurrence_id=f"_ext{i}", epoch=s.epoch)
        for i, s in enumerate(slots)]


def _apply_publish(rows, target_id, event_id, live):
    out = []
    for o in rows:
        if o.occurrence_id == target_id:
            out.append(model.Occurrence(
                occurrence_id=o.occurrence_id, epoch=o.epoch,
                published_event_id=event_id,
                form_data_digest=o.form_data_digest, edited=o.edited,
                live_receipts=live))
        else:
            out.append(o)
    return out


def _apply_delete(rows, target_id):
    victim = next((o for o in rows if o.occurrence_id == target_id), None)
    if victim is None or victim.sales_protected:
        return list(rows)
    return [o for o in rows if o.occurrence_id != target_id]


def two_way_race(label, sid, tz, first, second):
    """Fire two writers into one series at once and demand a serial result.

    `first` and `second` are each (checkpoint, request callable, model
    callable). The two checkpoints are armed onto one gate for two parties, so
    each request has finished everything up to its own checkpoint before either
    is let past: the windows overlap by construction rather than by luck, which
    is the mechanism R11 and R20 already use.

    Both orders are computed and either is accepted, because either is a real
    order, and in every pair below the two differ -- so the store records which
    request went second, and a store holding neither is holding half of each.
    Where one request is refused, the state its survivor would have reached
    alone is the only accepted answer: refusing is a legitimate way to
    serialise, and answering with a state no order produces is not.
    """
    before = load_series(sid)
    if before is None:
        return [f"{label}: series {sid} is missing"]

    (a_gate, a_call, a_model), (b_gate, b_call, b_model) = first, second
    group = f"race-{label}"
    coord("arm", a_gate, parties=2, hold=False, group=group)
    if b_gate != a_gate:
        coord("arm", b_gate, parties=2, hold=False, group=group)

    results = {}
    barrier = threading.Barrier(2)

    def run(tag, call):
        barrier.wait()
        results[tag] = call()

    threads = [threading.Thread(target=run, args=("a", a_call), daemon=True),
               threading.Thread(target=run, args=("b", b_call), daemon=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(240)
    coord("reset", a_gate)
    if b_gate != a_gate:
        coord("reset", b_gate)

    if len(results) != 2:
        return [f"{label}: only {sorted(results)} returned"]
    for tag, (code, payload) in results.items():
        if code == 0:
            return [f"{label}: request {tag} killed the connection "
                    f"({str(payload)[:200]}); a contended request must fail "
                    "cleanly rather than take the service down"]

    codes = {tag: r[0] for tag, r in results.items()}
    rows = before["occurrences"]
    try:
        if codes["a"] == 200 and codes["b"] == 200:
            orders = {"a then b": b_model(a_model(rows)),
                      "b then a": a_model(b_model(rows))}
        elif codes["a"] == 200:
            orders = {"a alone, b having been refused": a_model(rows)}
        elif codes["b"] == 200:
            orders = {"b alone, a having been refused": b_model(rows)}
        else:
            return [f"{label}: neither request succeeded: {codes}"]
    except model.ModelError as e:
        return [f"{label}: model could not describe an order: {e}"]

    after = load_series(sid)
    got = sorted(o.epoch for o in after["occurrences"])
    for expected in orders.values():
        if got == sorted(o.epoch for o in expected):
            break
    else:
        lines = [f"{label}: the store holds a state no order produces "
                 f"(HTTP {codes})", f"    stored {fmt(got, tz)}"]
        for name, expected in orders.items():
            lines.append(f"    {name}: {fmt([o.epoch for o in expected], tz)}")
        return ["\n".join(lines)]

    problems = [f"{label}: {v}" for v in
                model.violations(after["occurrences"], tz)]
    for was in rows:
        if not was.sales_protected:
            continue
        now = next((o for o in after["occurrences"]
                    if o.occurrence_id == was.occurrence_id), None)
        if now is None:
            problems.append(
                f"{label}: paid occurrence {was.occurrence_id} was removed by "
                "a pair of requests neither of which may remove it")
        elif now.epoch != was.epoch:
            problems.append(
                f"{label}: paid occurrence {was.occurrence_id} was moved, in "
                "an order in which nothing is allowed to move it")
    return problems


# (pair, zone, unit, anchor, time of day, shape, [published indices], the paid
#  index, the index the second writer names, the rebuild's start, the scope's
#  new time of day)
#
# Every row is arranged so the two orders leave different occurrence lists, or
# so one of the two requests must be refused. A pair whose orders agree grades
# nothing: any implementation that serialises at all passes it.
INTERLEAVINGS = [
    # An extend decides what the series is missing, a rebuild moves the whole
    # pattern, on Lisbon month ends at a time of day 29 March does not have.
    ("extend-vs-rebuild", "Europe/Lisbon", "month", "2026-01-29T12:00:00Z",
     3900, dict(count=14), [2], 4, 1, "2026-02-27T12:00:00Z", 68400),
    # Extend against a scoped edit: whether the three new rows are inside the
    # scope depends entirely on which landed first.
    ("extend-vs-scope", "America/St_Johns", "month", "2026-01-31T12:00:00Z",
     43200, dict(count=14), [2], 4, 1, "2026-03-30T12:00:00Z", 5400),
    # A publish decides a row survives; the rebuild it is racing decides the
    # same row does not. The paid row sits on Lord Howe's repeated 01:45.
    ("publish-vs-rebuild", "Australia/Lord_Howe", "week",
     "2026-03-22T12:00:00Z", 6300, dict(selected=[0, 3], count=16), [2], 4, 1,
     "2026-04-05T12:00:00Z", 9000),
    # A delete and a rebuild, on a published row both of them reach: deleting
    # first leaves the rebuild to fill the date, deleting second leaves a hole.
    ("delete-vs-rebuild", "Pacific/Chatham", "day", "2026-09-24T12:00:00Z",
     9900, dict(count=20), [2, 7], 4, 7, "2026-09-26T12:00:00Z", 13500),
    # Two scoped edits with overlapping reach, on Santiago days whose midnight
    # does not exist on 6 September.
    ("scope-vs-scope", "America/Santiago", "day", "2026-09-03T12:00:00Z", 0,
     dict(count=20), [2], 4, 1, "2026-09-05T12:00:00Z", 46800),
]


def rule_R27_interleavings():
    """Each pair of writers that can reach one series at once.

    Five pairs, each on a series whose dates are already awkward and which
    carries a published occurrence and a paid one, so what survives is settled
    by the rules rather than by which write happened to land last. Serialising
    is necessary and not sufficient: whichever request goes second still has to
    be right about the dates, and about what the first one left behind.
    """
    problems = []
    for (name, zone, unit, anchor, offset, shape, published, paid_i, tgt_i,
         regen_start, new_offset) in INTERLEAVINGS:
        label = f"R27-{name}"
        tz = ZoneInfo(zone)
        made, state = created_case(f"{label} setup", unit, zone, anchor,
                                   offset, **shape)
        if made:
            return problems + made
        sid, rows = state["sid"], state["occurrences"]
        needed = max([paid_i, tgt_i] + published) + 1
        if len(rows) < needed:
            return problems + [
                f"{label}: the round needs {needed} occurrences and the "
                f"series holds {len(rows)}"]

        setup = publish_rows(sid, rows,
                             [(i, "evt-published-002") for i in published] +
                             [(paid_i, "evt-published-001")])
        if setup:
            return problems + [f"{label}: {s}" for s in setup]

        armed = load_series(sid)
        paid = [o for o in armed["occurrences"] if o.sales_protected]
        if len(paid) != 1:
            return problems + [
                f"{label}: the round needs exactly one paid occurrence and "
                f"the store reports {len(paid)}"]

        cfg, off = armed["cfg"], armed["offset"]
        target = rows[tgt_i].occurrence_id
        second = rows[paid_i - 1].occurrence_id

        regen = ("pre-regenerate",
                 lambda: _regenerate(sid, regen_start, timeout=180),
                 lambda rs: _apply_regen(cfg, off, rs, regen_start))
        scope = ("pre-occurrence-edit",
                 lambda: scope_patch(sid, target, new_offset, timeout=180),
                 lambda rs: _apply_scope(cfg, rs, target, new_offset))
        extend = ("pre-extend", lambda: _extend(sid, 3, timeout=180),
                  lambda rs: _apply_extend(cfg, off, rs, 3, tz))
        publish = ("pre-occurrence-publish",
                   lambda: api_json(
                       "POST", f"/v2/event-series/{sid}/occurrences/"
                               f"{target}/publish",
                       {"eventId": "evt-published-003"}, timeout=180),
                   lambda rs: _apply_publish(rs, target, "evt-published-003",
                                             0))
        delete = ("pre-occurrence-delete",
                  lambda: api_json(
                      "DELETE",
                      f"/v2/event-series/{sid}/occurrences/{target}",
                      timeout=180),
                  lambda rs: _apply_delete(rs, target))
        scope_b = ("pre-occurrence-edit",
                   lambda: scope_patch(sid, second, new_offset + 1800,
                                       timeout=180),
                   lambda rs: _apply_scope(cfg, rs, second, new_offset + 1800))

        pair = {
            "extend-vs-rebuild": (extend, regen),
            "extend-vs-scope": (extend, scope),
            "publish-vs-rebuild": (publish, regen),
            "delete-vs-rebuild": (delete, regen),
            "scope-vs-scope": (scope, scope_b),
        }[name]
        got = two_way_race(label, sid, tz, *pair)
        if got:
            return problems + got
    return problems


def gate_fixture_intact():
    """The read-only exemplars still say what they said.

    ser-la-weekly, ser-utc-daily, ser-lhi-weekly and ser-lis-monthly are the
    fixture's statement of the rules in data: nothing the task asks for writes
    to them. Between them they say what a zone offset does to an instant, what
    an inclusive end date means, that a transition need not be an hour wide, and
    what happens when a month-end clamp lands on a local time that does not
    exist. If a candidate's create or regenerate path has reached them, the
    evidence a solver is meant to read has been destroyed and the rest of the
    run is suspect.

    This is a gate rather than a scored rule, and the difference matters. An
    untouched workspace passes it trivially -- it does nothing, so it damages
    nothing -- and a rule that the do-nothing answer passes is a rule that hands
    out free reward. So it can only take the reward away.
    """
    problems = []
    for sid, tz_name, count in [("ser-la-weekly", "America/Los_Angeles", 8),
                                ("ser-utc-daily", "UTC", 5),
                                ("ser-lhi-weekly", "Australia/Lord_Howe", 5),
                                ("ser-lis-monthly", "Europe/Lisbon", 5)]:
        state = load_series(sid)
        if state is None:
            problems.append(f"fixture: {sid} is missing from the store")
            continue
        tz = ZoneInfo(tz_name)
        if len(state["occurrences"]) != count:
            problems.append(
                f"fixture: {sid} should hold {count} occurrences, store "
                f"holds {len(state['occurrences'])}")
        if not state["occurrences"]:
            continue
        expected = model.generate(
            state["cfg"],
            dt.datetime.fromtimestamp(
                min(o.epoch for o in state["occurrences"]), tz=UTC),
            state["offset"])
        problems += compare_slots(f"fixture-{sid}", state["occurrences"],
                                  expected, tz)
        problems += [f"fixture-{sid}: {v}" for v in
                     model.violations(state["occurrences"], tz)]

    # ser-syd-scoped and ser-ber-gap are the other two read-only exemplars, and
    # they are checked against literal instants rather than against the model.
    # That is the point of them: neither is a plain generation. One has had a
    # scoped edit run over its tail, so its last four rows sit at a time of day
    # its own template does not carry; the other has a filled vacancy, so two of
    # its rows were written after rows that fall later than they do. Handing
    # either to model.generate would ask the wrong question.
    for sid, tz_name, want in [
            ("ser-syd-scoped", "Australia/Sydney",
             ["2026-05-07 19:00", "2026-05-14 19:00", "2026-05-21 17:00",
              "2026-05-28 17:00", "2026-06-04 17:00", "2026-06-11 17:00"]),
            ("ser-ber-gap", "Europe/Berlin",
             ["2026-06-02 19:00", "2026-06-09 19:00", "2026-06-16 19:00",
              "2026-06-23 19:00", "2026-06-30 19:00", "2026-07-07 19:00"])]:
        state = load_series(sid)
        if state is None:
            problems.append(f"fixture: {sid} is missing from the store")
            continue
        tz = ZoneInfo(tz_name)
        got = sorted(
            dt.datetime.fromtimestamp(o.epoch, tz=UTC).astimezone(tz)
              .strftime("%Y-%m-%d %H:%M")
            for o in state["occurrences"])
        if got != want:
            problems.append(
                f"fixture: {sid} should hold {want} in local time, store "
                f"holds {got}")
    return problems


RULES = [
    ("R1-generate-shapes", rule_R1_shapes),
    ("R2-selected-days", rule_R2_selected_days),
    ("R3-month-clamp", rule_R3_month_clamp),
    ("R4-spring-forward", rule_R4_spring_forward),
    ("R5-fall-back", rule_R5_fall_back),
    ("R6-occurrence-count", rule_R6_count),
    ("R7-end-date", rule_R7_end_date),
    ("R8-protect-published", rule_R8_protect_published),
    ("R9-edited-survives", rule_R9_edited),
    ("R10-extend", rule_R10_extend),
    ("R11-concurrent-regenerate", rule_R11_concurrent),
    ("R12-publish-then-regenerate", rule_R12_publish_then_regenerate),
    ("R13-delete-with-sales", rule_R13_delete_sales),
    ("R14-scope-steps-over-paid", rule_R14_scope_paid),
    ("R15-scope-over-month-end", rule_R15_scope_over_clamp),
    ("R16-scope-across-transition", rule_R16_scope_across_dst),
    ("R17-scope-then-regenerate", rule_R17_scope_then_regenerate),
    ("R18-extend-fills-gap", rule_R18_extend_gap),
    ("R19-extend-after-regenerate", rule_R19_extend_after_regenerate),
    ("R20-race-scope-vs-regenerate", rule_R20_race_scope_and_regenerate),
    ("R21-zone-by-configuration", rule_R21_cross_product),
    ("R22-regenerate-cross", rule_R22_regenerate_cross),
    ("R23-scope-regenerate-extend", rule_R23_scope_then_extend_cross),
    ("R24-race-on-hard-dates", rule_R24_race_cross),
    ("R25-survivor-identity", rule_R25_survivor_identity),
    ("R26-money-across-operations", rule_R26_money_across_operations),
    ("R27-interleavings", rule_R27_interleavings),
]


# A grader that does not finish is a fake zero: the trial dies on a timeout and
# carries no verdict at all, which is indistinguishable from a candidate that
# failed and much worse to look at. Three things guard against it.
#
#  1. Every write of reward.json goes through a temporary file and a rename, so
#     a process killed part way through a write leaves the previous, complete
#     file rather than half a JSON document. A truncated reward.json is a parse
#     error upstream, not a zero.
#  2. A deadline thread. If the whole run overruns, it writes a harness failure
#     and takes the process down itself, rather than leaving the harness to
#     notice much later.
#  3. The exit is os._exit, because the concurrency rules leave worker threads
#     behind whenever a request outlives its join, and a non-daemon thread
#     blocked in a socket read keeps the interpreter alive after main has
#     returned -- reward.json written, verdict reached, process never exits.
GRADER_DEADLINE_SECONDS = int(os.environ.get("GRADER_DEADLINE_SECONDS", "2100"))


def write_reward(payload, detail_payload):
    """Write both reward files atomically. Numbers only in reward.json."""
    for name, body, indent in (("reward.json", payload, None),
                               ("reward-detail.json", detail_payload, 2)):
        path = os.path.join(REWARD_DIR, name)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(body, fh, indent=indent)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)


def arm_deadline():
    def blow(started):
        while time.time() - started < GRADER_DEADLINE_SECONDS:
            time.sleep(1.0)
        print(f"[grader] deadline of {GRADER_DEADLINE_SECONDS}s passed with no "
              "verdict; reporting a harness failure", flush=True)
        try:
            write_reward(
                {"reward": 0.0, "harness_failure": 1},
                {"reward": 0.0, "harness_failure":
                 f"the grader ran past {GRADER_DEADLINE_SECONDS}s without "
                 "reaching a verdict"})
        finally:
            os._exit(0)

    t = threading.Thread(target=blow, args=(time.time(),), daemon=True)
    t.start()


def main():
    os.makedirs(REWARD_DIR, exist_ok=True)
    arm_deadline()
    passed, failed, detail = [], [], {}

    for name, fn in RULES:
        started = time.time()
        try:
            complaints = fn()
        except StoreUnreachable:
            # Not a rule that failed -- a rule that was never asked. Let it out
            # to the handler at the bottom, which records harness_failure so the
            # run is thrown away instead of being read as a verdict.
            raise
        except Exception as e:  # a rule that cannot run is a rule that failed
            complaints = [f"{name} raised {type(e).__name__}: {e}"]
        took = round(time.time() - started, 1)
        if complaints:
            failed.append(name)
            detail[name] = {"seconds": took, "complaints": complaints}
            print(f"[grader] FAIL {name} ({took}s)")
            for c in complaints[:6]:
                print(f"           {c}")
        else:
            passed.append(name)
            detail[name] = {"seconds": took, "complaints": []}
            print(f"[grader] pass {name} ({took}s)")

    reward = 1.0 if not failed else 0.0

    # The fixture gate runs last and can only take reward away. A candidate that
    # trampled the read-only exemplars has destroyed the evidence the other
    # rules were read against, so whatever they said is not worth reporting.
    try:
        gate = gate_fixture_intact()
    except StoreUnreachable:
        raise
    except Exception as e:
        gate = [f"fixture gate raised {type(e).__name__}: {e}"]
    if gate:
        print("[grader] FIXTURE GATE FAILED; reward forced to zero")
        for c in gate[:6]:
            print(f"           {c}")
        reward = 0.0
        detail["fixture-gate"] = {"seconds": 0, "complaints": gate}

    # reward.json carries numbers and nothing else: it is the only file Harbor
    # reads a score out of, and a string in it is a parse failure rather than a
    # zero. Everything a human would want is next door.
    write_reward({"reward": reward,
                  "harness_failure": 0,
                  "rules_total": len(RULES),
                  "rules_passed": len(passed),
                  "fixture_gate_failed": 1 if gate else 0},
                 {"reward": reward,
                  "passed_rules": passed,
                  "failed_rules": failed,
                  "fixture_gate": gate,
                  "rules": detail})

    print(f"[grader] {len(passed)}/{len(RULES)} rules passed; reward={reward}")
    if failed:
        print(f"[grader] failed: {', '.join(failed)}")


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:            # noqa: BLE001 -- last line of defence
        # Reaching here means the grader itself broke rather than the candidate:
        # the per-rule handler above already turns a failing rule into a failing
        # rule. Say so in the file rather than dying with a traceback and
        # leaving the trial to be scored on a missing file.
        import traceback
        traceback.print_exc()
        write_reward(
            {"reward": 0.0, "harness_failure": 1},
            {"reward": 0.0,
             "harness_failure": f"{type(e).__name__}: {e}",
             "traceback": traceback.format_exc()})
    finally:
        # Threads from the concurrency rules may still be blocked on a socket.
        # The verdict is written; nothing is served by waiting for them.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
