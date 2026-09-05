from __future__ import annotations

from datetime import datetime
from typing import Any

from ..clock import iso_ms
from .models import Issue, Label, Team, User, WorkflowState
from .state import LinearState


def _ts(value: datetime | None) -> str | None:
    return None if value is None else iso_ms(value)


def _url(state: LinearState, kind: str, key: str) -> str:
    return f"https://linear.app/{state.organization.url_key}/{kind}/{key}"


def user_by_key(state: LinearState, key: str | None) -> User | None:
    return next((user for user in state.users if user.key == key), None)


def user_json(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "name": user.name,
        "displayName": user.display_name,
        "email": user.email,
        "active": user.active,
    }


def user_ref(state: LinearState, key: str | None) -> dict[str, Any] | None:
    user = user_by_key(state, key)
    if user is None:
        return None
    return {
        "id": user.id,
        "name": user.name,
        "displayName": user.display_name,
        "email": user.email,
    }


def team_ref(team: Team | None) -> dict[str, Any] | None:
    return None if team is None else {"id": team.id, "key": team.key, "name": team.name}


def team_json(state: LinearState, team: Team) -> dict[str, Any]:
    members = [user_ref(state, key) for key in team.member_keys]
    return {
        "id": team.id,
        "key": team.key,
        "name": team.name,
        "description": team.description,
        "members": [member for member in members if member is not None],
    }


def label_by_key(state: LinearState, key: str | None) -> Label | None:
    return next((label for label in state.labels if label.key == key), None)


def label_json(state: LinearState, label: Label) -> dict[str, Any]:
    owner = state.team(label.team_key) if label.team_key else None
    return {
        "id": label.id,
        "name": label.name,
        "color": label.color,
        "team": team_ref(owner),
    }


def labels_json(state: LinearState, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    labels = (label_by_key(state, key) for key in keys)
    return [label_json(state, label) for label in labels if label is not None]


def status_by_key(state: LinearState, key: str) -> WorkflowState | None:
    return next((status for status in state.workflow_states() if status.key == key), None)


def status_ref(status: WorkflowState | None) -> dict[str, Any] | None:
    if status is None:
        return None
    return {"id": status.id, "name": status.name, "type": status.type, "color": status.color}


def status_json(state: LinearState, status: WorkflowState) -> dict[str, Any]:
    return {
        "id": status.id,
        "name": status.name,
        "type": status.type,
        "color": status.color,
        "position": status.position,
        "team": team_ref(state.team(status.team_key)),
    }


def issue_by_identifier(state: LinearState, identifier: str | None) -> Issue | None:
    return next((issue for issue in state.issues if issue.identifier == identifier), None)


def issue_id(state: LinearState, identifier: str | None) -> str | None:
    issue = issue_by_identifier(state, identifier)
    return None if issue is None else issue.id


def issue_ref(state: LinearState, identifier: str | None) -> dict[str, Any] | None:
    issue = issue_by_identifier(state, identifier)
    return None if issue is None else {"id": issue.id, "identifier": issue.identifier}
