"""An independent model of what a recurring event series is allowed to contain.

Written from the task statement, not from the Go reference. It shares no code
with it and does not take the same route to an answer:

  * the reference walks instants, carrying a *time.Time cursor and asking Go's
    zone database to interpret each one; this enumerates *local calendar dates*
    as plain integers and only materialises an instant at the very end;
  * the reference clamps month ends by asking Go for the first of the following
    month and stepping back a day; this uses an explicit month-length table and
    keeps the anchor day-of-month as a separate field, so a clamp can never
    become sticky;
  * the reference detects a spring-forward gap by round-tripping a constructed
    time and noticing the wall clock moved; this compares the two candidate UTC
    offsets either side of the nominal time and searches the gap directly;
  * the reference decides retention with EdgeQL against Gel; this folds a
    plain list of exported rows.

Two different routes to the same prediction is the whole point. If they
disagree, one of them is wrong and that has to be settled before shipping.

Vocabulary:

  slot          a local calendar date the repeat configuration puts in the
                series, together with the instant it resolves to.
  anchor        the local date the lattice is measured from. For a monthly
                series the anchor also carries a day-of-month, which is what
                survives a clamp.
  kept          an existing occurrence row that a regenerate must not destroy.
  claimed       a local date already occupied by a kept row, so no generated
                slot may be inserted on it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

# A configuration that never terminates would otherwise hang the grader. No
# fixture in this task comes close to it.
SLOT_CEILING = 600

SUNDAY_FIRST = ("sunday", "monday", "tuesday", "wednesday", "thursday",
                "friday", "saturday")


class ModelError(Exception):
    """The inputs are not something the specification can describe."""


# ------------------------------------------------------------------ calendar
# Deliberately arithmetic on (year, month, day) triples rather than on date
# objects with month deltas, so the clamp is visible and the anchor day is a
# separate value that a clamp cannot overwrite.

def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def month_length(year: int, month: int) -> int:
    table = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if month == 2 and _leap(year):
        return 29
    return table[month - 1]


def add_months(year: int, month: int, delta: int) -> Tuple[int, int]:
    """Advance a (year, month) pair, keeping month in 1..12."""
    zero = (year * 12) + (month - 1) + delta
    return zero // 12, (zero % 12) + 1


def weekday_sunday0(d: dt.date) -> int:
    """Day of week with Sunday as 0, which is what selectedDays uses.

    Python's weekday() is Monday-based; isoweekday() is Monday..Sunday as
    1..7. Neither is the convention the repeat config documents, so it is
    converted here once and nowhere else.
    """
    return (d.isoweekday()) % 7


def sunday_on_or_before(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=weekday_sunday0(d))


# ------------------------------------------------------------------- config

@dataclass(frozen=True)
class RepeatConfig:
    repeat_unit: str                    # 'day' | 'week' | 'month'
    repeat_interval: int = 1
    selected_days: Tuple[int, ...] = ()
    timezone: str = "UTC"
    end_type: str = "afterOccurrences"  # 'afterOccurrences' | 'onDate'
    number_of_occurrences: Optional[int] = None
    end_date: Optional[int] = None      # unix seconds

    def zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone or "UTC")
        except Exception as exc:  # unknown zone name
            raise ModelError(f"unknown timezone {self.timezone!r}: {exc}")


# -------------------------------------------------------- instant resolution

def _offset_at(naive: dt.datetime, tz: ZoneInfo, fold: int) -> dt.timedelta:
    return naive.replace(tzinfo=tz, fold=fold).utcoffset()


def local_kind(naive: dt.datetime, tz: ZoneInfo) -> str:
    """Classify a nominal local time as normal, a spring gap, or ambiguous.

    A wall time is real when interpreting it with the offset in force at that
    wall time lands back on the same wall time. Comparing the fold=0 and
    fold=1 readings is enough to tell the three cases apart without consulting
    a transition list.
    """
    off0 = _offset_at(naive, tz, 0)
    off1 = _offset_at(naive, tz, 1)
    if off0 == off1:
        return "normal"
    # fold picks between two offsets. If the earlier-offset reading round trips
    # to a different wall clock, the wall time never happened.
    as_utc = naive.replace(tzinfo=tz, fold=0).astimezone(dt.timezone.utc)
    if as_utc.astimezone(tz).replace(tzinfo=None) != naive:
        return "gap"
    return "ambiguous"


def resolve_instant(day: dt.date, seconds_from_midnight: int,
                    tz: ZoneInfo) -> dt.datetime:
    """The instant an occurrence on `day` happens at.

    Normal wall times resolve directly. An ambiguous wall time (the hour a
    fall-back repeats) takes the earlier of its two instants. A wall time that
    does not exist at all (the hour a spring-forward removes) takes the
    earliest instant that does exist at or after it, which is the far edge of
    the gap and is still on `day`.
    """
    nominal = (dt.datetime.combine(day, dt.time(0)) +
               dt.timedelta(seconds=seconds_from_midnight))
    kind = local_kind(nominal, tz)

    if kind == "normal":
        return nominal.replace(tzinfo=tz).astimezone(dt.timezone.utc)
    if kind == "ambiguous":
        # fold=0 is the first pass through this wall time, i.e. the earlier
        # instant. Assert it rather than trusting the flag's direction.
        a = nominal.replace(tzinfo=tz, fold=0).astimezone(dt.timezone.utc)
        b = nominal.replace(tzinfo=tz, fold=1).astimezone(dt.timezone.utc)
        return min(a, b)

    # A gap. Walk forward a minute at a time from the nominal wall time to the
    # first wall time that exists; the transition is on a minute boundary in
    # every zone in the tz database, so this terminates quickly. Searching
    # forward is a different mechanism from the reference's round-trip test,
    # which is the point.
    probe = nominal
    for _ in range(24 * 60):
        probe += dt.timedelta(minutes=1)
        if local_kind(probe, tz) != "gap":
            return probe.replace(tzinfo=tz, fold=0).astimezone(dt.timezone.utc)
    raise ModelError(f"no valid local time found after {nominal} in {tz}")


# --------------------------------------------------------- date enumeration

def _end_local_date(cfg: RepeatConfig, tz: ZoneInfo) -> Optional[dt.date]:
    if cfg.end_type != "onDate" or cfg.end_date is None:
        return None
    inst = dt.datetime.fromtimestamp(cfg.end_date, tz=dt.timezone.utc)
    return inst.astimezone(tz).date()


def _wanted_count(cfg: RepeatConfig) -> Optional[int]:
    if cfg.end_type != "afterOccurrences":
        return None
    if cfg.number_of_occurrences is None:
        raise ModelError("afterOccurrences with no numberOfOccurrences")
    return int(cfg.number_of_occurrences)


def _daily_dates(anchor: dt.date, interval: int) -> Iterable[dt.date]:
    d = anchor
    while True:
        yield d
        d = d + dt.timedelta(days=interval)


def _weekly_dates(anchor: dt.date, interval: int,
                  selected: Sequence[int]) -> Iterable[dt.date]:
    """Selected weekdays inside each stride-th week, Sunday-anchored.

    The week the anchor falls in is week 0 even when the anchor is not a
    Sunday, and days in week 0 that fall before the anchor are not part of the
    series -- the series cannot start before its own start date.
    """
    days = sorted({int(x) % 7 for x in selected}) or [weekday_sunday0(anchor)]
    week_start = sunday_on_or_before(anchor)
    while True:
        for sd in days:
            d = week_start + dt.timedelta(days=sd)
            if d >= anchor:
                yield d
        week_start = week_start + dt.timedelta(weeks=interval)


def _monthly_dates(anchor: dt.date, interval: int) -> Iterable[dt.date]:
    """The anchor's day-of-month every stride-th month, clamped, never sticky.

    anchor_day is kept out of the loop on purpose. Reading the day back off the
    previously emitted date is what turns a single clamp into a permanent one:
    Jan 31 would become Feb 28 and then March 28 instead of March 31.
    """
    anchor_day = anchor.day
    step = 0
    while True:
        year, month = add_months(anchor.year, anchor.month, step * interval)
        day = min(anchor_day, month_length(year, month))
        yield dt.date(year, month, day)
        step += 1


def local_dates(cfg: RepeatConfig, anchor: dt.date, *,
                limit: Optional[int] = None,
                until: Optional[dt.date] = None,
                skip: Optional[Iterable[dt.date]] = None) -> List[dt.date]:
    """The lattice of local dates a config puts in a series.

    `limit` and `until` are the two end rules; `skip` is used by extend, which
    walks the same lattice but wants only the dates the series does not already
    hold. It is a set rather than a boundary because a series need not be
    contiguous: a date left vacant in the middle is still a free date on the
    lattice, and it comes before anything past the last occurrence.
    """
    skipped = {d for d in (skip or ())}
    if cfg.repeat_interval < 1:
        raise ModelError(f"repeatInterval {cfg.repeat_interval} is not >= 1")

    if cfg.repeat_unit == "day":
        stream = _daily_dates(anchor, cfg.repeat_interval)
    elif cfg.repeat_unit == "week":
        stream = _weekly_dates(anchor, cfg.repeat_interval, cfg.selected_days)
    elif cfg.repeat_unit == "month":
        stream = _monthly_dates(anchor, cfg.repeat_interval)
    else:
        raise ModelError(f"unknown repeatUnit {cfg.repeat_unit!r}")

    out: List[dt.date] = []
    seen = 0
    for d in stream:
        seen += 1
        if seen > SLOT_CEILING:
            raise ModelError("repeat configuration does not terminate")
        if until is not None and d > until:
            break
        if d in skipped:
            continue
        skipped.add(d)
        out.append(d)
        if limit is not None and len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------- slots

@dataclass(frozen=True)
class Slot:
    local_date: dt.date
    instant: dt.datetime          # tz-aware, UTC

    @property
    def epoch(self) -> int:
        return int(self.instant.timestamp())


def generate(cfg: RepeatConfig, start_instant: dt.datetime,
             seconds_from_midnight: int) -> List[Slot]:
    """The full slot list a create or a regenerate must produce."""
    tz = cfg.zone()
    anchor = start_instant.astimezone(tz).date()
    dates = local_dates(cfg, anchor,
                        limit=_wanted_count(cfg),
                        until=_end_local_date(cfg, tz))
    return [Slot(d, resolve_instant(d, seconds_from_midnight, tz))
            for d in dates]


def extend(cfg: RepeatConfig, anchor_date: dt.date,
           held: Iterable[dt.date], additional: int,
           seconds_from_midnight: int) -> List[Slot]:
    """The slots an extend must add.

    The lattice is the series' own, so it is measured from the earliest
    occurrence rather than from today or from the last one -- for a monthly
    series clamped into February those give different answers. The config's end
    rule does not apply: extending is the act of going past it.

    What is added is the first `additional` dates of that lattice the series
    does not already hold, which is a set difference rather than an append. The
    two agree only while the series is contiguous.
    """
    tz = cfg.zone()
    dates = local_dates(cfg, anchor_date, limit=additional, skip=held)
    return [Slot(d, resolve_instant(d, seconds_from_midnight, tz))
            for d in dates]


# ---------------------------------------------------------------- occurrences

@dataclass
class Occurrence:
    """One stored row, as exported from the database."""

    occurrence_id: str
    epoch: int                       # instant, unix seconds
    published_event_id: Optional[str] = None
    form_data_digest: Optional[str] = None
    edited: bool = False             # date_updated is set
    live_receipts: int = 0           # on the published event

    def local_date(self, tz: ZoneInfo) -> dt.date:
        return dt.datetime.fromtimestamp(
            self.epoch, tz=dt.timezone.utc).astimezone(tz).date()

    @property
    def published(self) -> bool:
        return bool(self.published_event_id)

    @property
    def sales_protected(self) -> bool:
        return self.published and self.live_receipts > 0


@dataclass
class RegenerateOutcome:
    kept: List[Occurrence] = field(default_factory=list)
    dropped: List[Occurrence] = field(default_factory=list)
    inserted: List[Slot] = field(default_factory=list)
    claimed: Dict[dt.date, str] = field(default_factory=dict)

    def local_dates(self, tz: ZoneInfo) -> List[dt.date]:
        return sorted([o.local_date(tz) for o in self.kept] +
                      [s.local_date for s in self.inserted])

    def epochs(self) -> List[int]:
        return sorted([o.epoch for o in self.kept] +
                      [s.epoch for s in self.inserted])

    def kept_ids(self) -> List[str]:
        return sorted(o.occurrence_id for o in self.kept)


def regenerate(cfg: RepeatConfig, existing: Sequence[Occurrence],
               start_instant: dt.datetime,
               seconds_from_midnight: int) -> RegenerateOutcome:
    """What the store must hold after one regenerate.

    Retention has two tiers and they are not the same rule:

      * a published occurrence is kept unconditionally. It may sit on a date
        the current configuration would never generate -- that is exactly what
        happens when the configuration changed after publishing -- and it is
        still kept.
      * an individually edited but unpublished occurrence is kept only while
        its own local date is still on the lattice. This is what makes an edit
        survive an ordinary regenerate and not survive a configuration change,
        without anything having to remember that the configuration changed.

    Everything else is replaced. A kept row owns its local date, so the
    generated slot for that date is not inserted and the run ends with exactly
    one occurrence per local calendar date.
    """
    tz = cfg.zone()
    slots = generate(cfg, start_instant, seconds_from_midnight)
    on_lattice = {s.local_date for s in slots}

    out = RegenerateOutcome()
    for occ in existing:
        d = occ.local_date(tz)
        if occ.published:
            out.kept.append(occ)
        elif occ.edited and d in on_lattice:
            out.kept.append(occ)
        else:
            out.dropped.append(occ)

    for occ in out.kept:
        d = occ.local_date(tz)
        if d in out.claimed:
            raise ModelError(
                f"two kept occurrences share local date {d}: "
                f"{out.claimed[d]} and {occ.occurrence_id}")
        out.claimed[d] = occ.occurrence_id

    for s in slots:
        if s.local_date not in out.claimed:
            out.inserted.append(s)

    return out


@dataclass
class ScopedOutcome:
    """What a thisAndFollowing edit must leave behind.

    Three disjoint groups, keyed by occurrence id:

      moved     the rows the scope reaches, each with the instant its own local
                date and the edit's new time of day resolve to;
      paid      rows on or after the target that the scope steps over, because
                somebody outside the system is holding a ticket that names when
                that event starts;
      earlier   rows before the target's local date, which a scope never
                reaches at all.
    """

    moved: Dict[str, int] = field(default_factory=dict)
    paid: List[str] = field(default_factory=list)
    earlier: List[str] = field(default_factory=list)

    def expected_epoch(self, occ: Occurrence) -> int:
        """The instant `occ` must be sitting at once the edit has run."""
        if occ.occurrence_id in self.moved:
            return self.moved[occ.occurrence_id]
        return occ.epoch


def scoped_edit(cfg: RepeatConfig, existing: Sequence[Occurrence],
                target_id: str, seconds_from_midnight: int) -> ScopedOutcome:
    """What a thisAndFollowing edit must do.

    Membership is decided on *local calendar dates* in the series' zone, not on
    stored instants. The two disagree precisely when the edit changes the time
    of day, which is the case that matters: an occurrence a few hours later on
    the previous local date can hold a larger instant than the target does, so a
    comparison against the stored column pulls in a row the scope does not
    reach.

    A paid occurrence is stepped over and keeps everything: its instant and its
    form data both. That is the same predicate the delete path refuses on, so an
    implementation that grew it in only one of the two places disagrees here.

    Nothing changes which local date it falls on. A scope moves the time of day
    an occurrence happens at, so the one-per-local-date invariant survives by
    construction.
    """
    tz = cfg.zone()
    target = next((o for o in existing if o.occurrence_id == target_id), None)
    if target is None:
        raise ModelError(f"occurrence {target_id} is not in the series")
    boundary = target.local_date(tz)

    out = ScopedOutcome()
    for occ in existing:
        d = occ.local_date(tz)
        if d < boundary:
            out.earlier.append(occ.occurrence_id)
        elif occ.sales_protected:
            out.paid.append(occ.occurrence_id)
        else:
            inst = resolve_instant(d, seconds_from_midnight, tz)
            out.moved[occ.occurrence_id] = int(inst.timestamp())
    return out


def deletable(occ: Occurrence) -> bool:
    """Whether DELETE on this occurrence may succeed.

    Sales are the thing being protected, not publication: an occurrence that
    was published and sold nothing is still the host's to remove.
    """
    return not occ.sales_protected


# ------------------------------------------------------------------ checks

def violations(occurrences: Sequence[Occurrence], tz: ZoneInfo) -> List[str]:
    """Anything true of a stored set that the specification forbids."""
    problems: List[str] = []
    by_date: Dict[dt.date, List[str]] = {}
    by_id: Dict[str, int] = {}
    for o in occurrences:
        by_date.setdefault(o.local_date(tz), []).append(o.occurrence_id)
        by_id[o.occurrence_id] = by_id.get(o.occurrence_id, 0) + 1
    for d, ids in sorted(by_date.items()):
        if len(ids) > 1:
            problems.append(f"{len(ids)} occurrences share local date {d}: {sorted(ids)}")
    for oid, n in sorted(by_id.items()):
        if n > 1:
            problems.append(f"occurrence_id {oid} appears {n} times")
    return problems


def describe(slots: Sequence[Slot], tz: ZoneInfo) -> List[str]:
    """Readable slot list for the detail report."""
    out = []
    for s in slots:
        local = s.instant.astimezone(tz)
        out.append(f"{s.local_date.isoformat()} {local.strftime('%H:%M %z')} "
                   f"({SUNDAY_FIRST[weekday_sunday0(s.local_date)]}) "
                   f"epoch={s.epoch}")
    return out
