from __future__ import annotations

import re
from datetime import datetime
from typing import Any, NoReturn

from ..clock import parse_ts
from ..ids import uuid_for
from ..scenario import ScenarioError
from .models import Attachment, Comment, Issue, Project, Team, User

_SLUG = re.compile(r"[^a-z0-9]+")


def _fail(identifier: str, kind: str, value: Any) -> NoReturn:
    raise ScenarioError(f"issue {identifier} names an unknown {kind}: {value}")


def _slug(title: str) -> str:
    return _SLUG.sub("-", title.lower()).strip("-")[:40].rstrip("-")


def _optional_ts(raw: dict[str, Any], key: str) -> datetime | None:
    value = raw.get(key)
    return None if value is None else parse_ts(str(value))


def _attachments(raw: list[dict[str, Any]], identifier: str, seed: int) -> tuple[Attachment, ...]:
    return tuple(
        Attachment(
            id=uuid_for(seed, "linear", "attachment", str(item["key"])),
            key=str(item["key"]),
            title=str(item.get("title", item["key"])),
            subtitle=str(item.get("subtitle", "")),
            url=str(item.get("url", "")),
            issue_identifier=identifier,
        )
        for item in raw
    )


def _comments(
    raw: list[dict[str, Any]], identifier: str, seed: int, clock: datetime
) -> tuple[Comment, ...]:
    return tuple(
        Comment(
            id=uuid_for(seed, "linear", "comment", str(item["key"])),
            key=str(item["key"]),
            body=str(item.get("body", "")),
            user_key=str(item.get("user", "")),
            created_at=parse_ts(item["createdAt"]) if "createdAt" in item else clock,
            parent_key=item.get("parent"),
            issue_identifier=identifier,
        )
        for item in raw
    )


def _team_of(raw: dict[str, Any], teams: tuple[Team, ...], identifier: str) -> Team:
    key = str(raw.get("team", ""))
    team = next((item for item in teams if item.key == key), None)
    if team is None:
        _fail(identifier, "team", key)
    return team


def _state_key(raw: dict[str, Any], team: Team, identifier: str) -> str:
    wanted = str(raw.get("state", "")).casefold()
    match = next(
        (item for item in team.states if wanted in (item.key.casefold(), item.name.casefold())),
        None,
    )
    if match is None:
        _fail(identifier, "state", raw.get("state"))
    return match.key


def _cycle_key(raw: dict[str, Any], team: Team, identifier: str) -> str | None:
    if raw.get("cycle") is None:
        return None
    number = int(raw["cycle"])
    match = next((item for item in team.cycles if item.number == number), None)
    if match is None:
        _fail(identifier, "cycle", number)
    return match.key


def _milestone_key(
    raw: dict[str, Any], projects: tuple[Project, ...], identifier: str
) -> str | None:
    key = raw.get("milestone")
    if key is None:
        return None
    known = {item.key for project in projects for item in project.milestones}
    if key not in known:
        _fail(identifier, "milestone", key)
    return str(key)


def _user_key(
    raw: dict[str, Any], field: str, users: tuple[User, ...], identifier: str
) -> str | None:
    key = raw.get(field)
    if key is None:
        return None
    if not any(user.key == key for user in users):
        _fail(identifier, field, key)
    return str(key)


def _branch_name(raw: dict[str, Any], owner: str | None, identifier: str) -> str:
    authored = raw.get("branchName")
    if authored is not None:
        return str(authored)
    return f"{owner}/{identifier.lower()}-{_slug(str(raw.get('title', '')))}"


def load_issues(
    raw: list[dict[str, Any]],
    teams: tuple[Team, ...],
    users: tuple[User, ...],
    projects: tuple[Project, ...],
    seed: int,
    clock: datetime,
) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    for item in raw:
        identifier = str(item["identifier"])
        team = _team_of(item, teams, identifier)
        assignee_key = _user_key(item, "assignee", users, identifier)
        creator_key = _user_key(item, "creator", users, identifier)
        owner_key = assignee_key or creator_key
        owner = next((user.display_name for user in users if user.key == owner_key), "")
        issues.append(
            Issue(
                id=uuid_for(seed, "linear", "issue", identifier),
                identifier=identifier,
                title=str(item.get("title", "")),
                description=str(item.get("description", "")),
                team_key=team.key,
                state_key=_state_key(item, team, identifier),
                assignee_key=assignee_key,
                creator_key=creator_key or "",
                priority=int(item.get("priority", 0)),
                estimate=None if item.get("estimate") is None else int(item["estimate"]),
                label_keys=tuple(str(label) for label in item.get("labels", [])),
                project_key=item.get("project"),
                milestone_key=_milestone_key(item, projects, identifier),
                cycle_key=_cycle_key(item, team, identifier),
                parent_identifier=item.get("parent"),
                created_at=parse_ts(item["createdAt"]) if "createdAt" in item else clock,
                updated_at=parse_ts(item["updatedAt"]) if "updatedAt" in item else clock,
                started_at=_optional_ts(item, "startedAt"),
                completed_at=_optional_ts(item, "completedAt"),
                canceled_at=_optional_ts(item, "canceledAt"),
                due_date=item.get("dueDate"),
                branch_name=_branch_name(item, owner, identifier),
                attachments=_attachments(item.get("attachments", []), identifier, seed),
                comments=_comments(item.get("comments", []), identifier, seed, clock),
            )
        )
    return tuple(issues)
