from __future__ import annotations

from datetime import datetime

from .models import Cycle, Team
from .state import LinearState


def _current(cycles: list[Cycle], now: datetime) -> Cycle | None:
    return next((cycle for cycle in cycles if cycle.starts_at <= now < cycle.ends_at), None)


def _for_team(cycles: list[Cycle], kind: str, now: datetime) -> list[Cycle]:
    ordered = sorted(cycles, key=lambda cycle: cycle.starts_at)
    current = _current(ordered, now)
    if kind == "current":
        return [current] if current is not None else []
    if kind == "previous":
        earlier = [cycle for cycle in ordered if cycle.ends_at <= now]
        return earlier[-1:] if earlier else []
    later = [cycle for cycle in ordered if cycle.starts_at > now]
    return later[:1] if later else []


def select_cycles(state: LinearState, team: Team | None, kind: str, now: datetime) -> list[Cycle]:
    teams = [team] if team is not None else list(state.teams)
    if kind == "all":
        return [cycle for item in teams for cycle in item.cycles]
    return [cycle for item in teams for cycle in _for_team(list(item.cycles), kind, now)]
