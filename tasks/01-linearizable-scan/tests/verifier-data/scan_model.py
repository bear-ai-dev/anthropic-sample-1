"""An independent model of what a door-scanning service is allowed to do.

This is written from the task statement, not from the reference implementation.
It shares no code with it: the reference decides admission inside one EdgeQL
statement against Gel, while this keeps plain Python dictionaries and replays
the request log as an explicit state machine.

Its job is to answer, for a given sequence of scan attempts and the winners the
system happened to pick among concurrent attempts, exactly what the store must
look like afterwards. The grader compares that prediction against the real
database and the real HTTP projections.

Vocabulary used here:

  admission   a receipt item going from "no scan history" to "some scan
              history". It may happen at most once per item, ever.
  writer      an attempt that performed an admission. Only writers may change
              stored state; everything else must leave the store untouched.
  spent       an idempotency key that some committed call is now holding. A
              refused call commits nothing, so it spends nothing.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


class ModelError(Exception):
    """The request log itself is inconsistent with the specification."""


@dataclass
class Attempt:
    """One scan POST as the harness issued it."""

    label: str
    items: Tuple[str, ...]
    idempotency_key: Optional[str] = None
    # Whether the caller was authorised at the moment the write would land.
    authorised_at_write: bool = True
    # Attempts sharing a group id were in flight simultaneously.
    group: Optional[str] = None
    # The staff member the request was made as, or None for a scan authorised
    # by the door code rather than by a person.
    scanner: Optional[str] = None


@dataclass
class Ticket:
    pending: bool = False
    valid: bool = True          # not refunded, not abandoned
    owner: str = ""
    history: List[str] = field(default_factory=list)


@dataclass
class StoredScan:
    items: Tuple[str, ...]
    scanner: Optional[str]


@dataclass
class Outcome:
    label: str
    admitted: bool
    scan_id: Optional[str]
    reason: str


class ScanModel:
    """Replays scan attempts and reports the only stored states permitted."""

    def __init__(self, tickets: Dict[str, Ticket]):
        self.tickets = {k: Ticket(v.pending, v.valid, v.owner, list(v.history))
                        for k, v in tickets.items()}
        # key -> (scan id handed back, the item set the key was taken for)
        self.keys: Dict[str, Tuple[str, frozenset]] = {}
        # scan id -> what that scan admitted, and who made it
        self.scans: Dict[str, StoredScan] = {}
        self.outcomes: List[Outcome] = []

    def seed_scan(self, scan_id: str, items: Tuple[str, ...], scanner: Optional[str]) -> None:
        """Record a scan the fixture arrives with."""
        self.scans[scan_id] = StoredScan(tuple(sorted(items)), scanner)

    # ---------------------------------------------------------------- replay

    def apply(self, attempt: Attempt, winner: bool, scan_id: Optional[str]) -> Outcome:
        """Advance the model by one attempt.

        `winner` says whether the system reported that this attempt performed
        the admission. For attempts that were alone in flight the model checks
        that claim rather than trusting it; for a group of simultaneous
        attempts it accepts the system's choice of winner but still checks that
        exactly one was allowed to win.
        """
        eligible = self._eligible(attempt)
        key = attempt.idempotency_key

        if key and key in self.keys:
            replay, bound = self.keys[key]
            if bound != frozenset(attempt.items):
                if winner:
                    raise ModelError(
                        f"{attempt.label}: admitted under key {key}, which "
                        f"belongs to a different set of tickets")
                out = Outcome(attempt.label, False, None, "key conflict")
            else:
                if winner and scan_id != replay:
                    raise ModelError(
                        f"{attempt.label}: reported a fresh admission under a "
                        f"key already answered with {replay}")
                out = Outcome(attempt.label, False, replay, "replayed")
            self.outcomes.append(out)
            return out

        if not winner:
            # A refused call commits nothing, so its key stays free. Recording
            # it here would let the model bless a service that burns keys on
            # the way out.
            out = Outcome(attempt.label, False, None,
                          "not admitted" if eligible else self._refusal(attempt))
            self.outcomes.append(out)
            return out

        if not eligible:
            raise ModelError(
                f"{attempt.label}: reported an admission that the rules forbid "
                f"({self._refusal(attempt)})")
        if scan_id is None:
            raise ModelError(f"{attempt.label}: admitted without a scan reference")
        if scan_id in self.scans:
            raise ModelError(f"{attempt.label}: reused scan reference {scan_id}")

        for name in attempt.items:
            self.tickets[name].history.append(scan_id)
        self.scans[scan_id] = StoredScan(tuple(sorted(attempt.items)), attempt.scanner)
        if key:
            self.keys[key] = (scan_id, frozenset(attempt.items))

        out = Outcome(attempt.label, True, scan_id, "admitted")
        self.outcomes.append(out)
        return out

    def _eligible(self, attempt: Attempt) -> bool:
        if not attempt.authorised_at_write:
            return False
        for name in attempt.items:
            t = self.tickets.get(name)
            if t is None or not t.valid or t.pending or t.history:
                return False
        return True

    def _refusal(self, attempt: Attempt) -> str:
        if not attempt.authorised_at_write:
            return "not authorised at admission time"
        for name in attempt.items:
            t = self.tickets.get(name)
            if t is None:
                return f"{name} unknown"
            if not t.valid:
                return f"{name} is refunded or abandoned"
            if t.pending:
                return f"{name} pending"
            if t.history:
                return f"{name} already admitted"
        return "eligible"

    # ------------------------------------------------------------ predictions

    def expected_history(self) -> Dict[str, List[str]]:
        """The scan history every receipt item must carry."""
        return {k: list(v.history) for k, v in self.tickets.items()}

    def expected_scan_ids(self) -> Set[str]:
        """Every scan reference that must exist as a stored scan, and no other."""
        return set(self.scans)

    def expected_scan_rows(self) -> Dict[str, StoredScan]:
        """What each stored scan must say about itself."""
        return dict(self.scans)

    def expected_num_scanned(self) -> int:
        """What the scan-status projection must report."""
        return sum(1 for t in self.tickets.values() if t.valid and not t.pending and t.history)

    def expected_total_tickets(self) -> int:
        return sum(1 for t in self.tickets.values() if t.valid and not t.pending)

    def expected_unique_attendees(self) -> int:
        """Distinct people admitted, which is what the timeline accumulates."""
        return len({t.owner for t in self.tickets.values() if t.history and t.owner})

    def free_key(self, key: str) -> bool:
        """Whether the key has been spent by a call that committed."""
        return key not in self.keys

    def violations(self) -> List[str]:
        """Anything true of the model state that the specification forbids."""
        problems = []
        for name, t in self.tickets.items():
            if len(t.history) > 1:
                problems.append(f"{name} admitted more than once: {t.history}")
            if t.pending and t.history:
                problems.append(f"{name} is pending yet carries {t.history}")
            if not t.valid and t.history:
                problems.append(f"{name} is not a valid ticket yet carries {t.history}")
        return problems

    def group_check(self, group: str, winners: List[str]) -> Optional[str]:
        """At most one member of a simultaneous group may have admitted."""
        if len(winners) > 1:
            return f"group {group}: {len(winners)} attempts admitted ({winners}); at most one is allowed"
        return None
