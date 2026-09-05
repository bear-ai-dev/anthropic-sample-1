from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..clock import resolve_relative
from .models import Issue
from .state import LinearState

Predicate = Callable[[Issue], bool]


def _folded(value: Any) -> str:
    return str(value).strip().casefold()


def _never(issue: Issue) -> bool:
    return False


def _assignee(state: LinearState, value: Any) -> Predicate:
    user = state.user(str(value))
    if user is None:
        return _never
    return lambda issue: issue.assignee_key == user.key


def _team(state: LinearState, value: Any) -> Predicate:
    team = state.team(str(value))
    if team is None:
        return _never
    return lambda issue: issue.team_key == team.key


def _status(state: LinearState, value: Any) -> Predicate:
    wanted = _folded(value)
    keys = {
        status.key
        for status in state.workflow_states()
        if wanted in (status.name.casefold(), status.type.casefold())
    }
    return lambda issue: issue.state_key in keys


def _label(state: LinearState, value: Any) -> Predicate:
    label = state.label(str(value))
    if label is None:
        return _never
    return lambda issue: label.key in issue.label_keys


def _project(state: LinearState, value: Any) -> Predicate:
    project = state.project(str(value))
    if project is None:
        return _never
    return lambda issue: issue.project_key == project.key


def _cycle(state: LinearState, value: Any) -> Predicate:
    wanted = _folded(value)
    keys = {
        cycle.key
        for cycle in state.cycles()
        if wanted in (cycle.name.casefold(), str(cycle.number), cycle.id)
    }
    return lambda issue: issue.cycle_key in keys


def _parent(state: LinearState, value: Any) -> Predicate:
    parent = state.issue(str(value))
    if parent is None:
        return _never
    return lambda issue: issue.parent_identifier == parent.identifier


def _created_after(value: Any, now: datetime) -> Predicate:
    moment = resolve_relative(str(value), now)
    return lambda issue: issue.created_at >= moment


def _updated_after(value: Any, now: datetime) -> Predicate:
    moment = resolve_relative(str(value), now)
    return lambda issue: issue.updated_at >= moment


def _query(value: Any) -> Predicate:
    wanted = _folded(value)
    return lambda issue: (
        wanted in (f"{issue.identifier} {issue.title} {issue.description}".casefold())
    )


def _predicates(state: LinearState, arguments: dict[str, Any], now: datetime) -> list[Predicate]:
    builders: dict[str, Callable[[Any], Predicate]] = {
        "assignee": lambda value: _assignee(state, value),
        "team": lambda value: _team(state, value),
        "state": lambda value: _status(state, value),
        "label": lambda value: _label(state, value),
        "project": lambda value: _project(state, value),
        "cycle": lambda value: _cycle(state, value),
        "parent": lambda value: _parent(state, value),
        "createdAt": lambda value: _created_after(value, now),
        "updatedAt": lambda value: _updated_after(value, now),
        "query": _query,
    }
    return [builder(arguments[name]) for name, builder in builders.items() if arguments.get(name)]


def matching_issues(state: LinearState, arguments: dict[str, Any], now: datetime) -> list[Issue]:
    checks = _predicates(state, arguments, now)
    found = [issue for issue in state.issues if all(check(issue) for check in checks)]
    field = "created_at" if arguments.get("orderBy") == "createdAt" else "updated_at"
    return sorted(found, key=lambda issue: getattr(issue, field), reverse=True)
