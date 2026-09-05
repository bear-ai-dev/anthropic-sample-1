from __future__ import annotations

from datetime import datetime
from typing import Any

from ..clock import parse_ts
from ..ids import uuid_for
from .load_issues import load_issues
from .models import (
    Cycle,
    Document,
    Label,
    Milestone,
    Organization,
    Project,
    Team,
    User,
    WorkflowState,
)
from .state import LinearState


def _organization(raw: dict[str, Any], seed: int) -> Organization:
    url_key = str(raw.get("urlKey", "workspace"))
    return Organization(
        id=uuid_for(seed, "linear", "organization", url_key),
        name=str(raw.get("name", "Workspace")),
        url_key=url_key,
    )


def _users(raw: list[dict[str, Any]], seed: int) -> tuple[User, ...]:
    return tuple(
        User(
            id=uuid_for(seed, "linear", "user", str(item["key"])),
            key=str(item["key"]),
            name=str(item.get("name", item["key"])),
            display_name=str(item.get("displayName", item["key"])),
            email=str(item.get("email", "")),
            active=bool(item.get("active", True)),
        )
        for item in raw
    )


def _states(raw: list[dict[str, Any]], team_key: str, seed: int) -> tuple[WorkflowState, ...]:
    return tuple(
        WorkflowState(
            id=uuid_for(seed, "linear", "state", str(item["key"])),
            key=str(item["key"]),
            name=str(item["name"]),
            type=str(item["type"]),
            position=int(item.get("position", index)),
            color=str(item.get("color", "#95a2b3")),
            team_key=team_key,
        )
        for index, item in enumerate(raw)
    )


def _cycles(raw: list[dict[str, Any]], team_key: str, seed: int) -> tuple[Cycle, ...]:
    return tuple(
        Cycle(
            id=uuid_for(seed, "linear", "cycle", f"{team_key}:{item['number']}"),
            key=f"{team_key}:{item['number']}",
            number=int(item["number"]),
            name=str(item.get("name", f"Cycle {item['number']}")),
            starts_at=parse_ts(str(item["startsAt"])),
            ends_at=parse_ts(str(item["endsAt"])),
            team_key=team_key,
        )
        for item in raw
    )


def _teams(raw: list[dict[str, Any]], seed: int) -> tuple[Team, ...]:
    return tuple(
        Team(
            id=uuid_for(seed, "linear", "team", str(item["key"])),
            key=str(item["key"]),
            name=str(item.get("name", item["key"])),
            description=str(item.get("description", "")),
            member_keys=tuple(str(member) for member in item.get("members", [])),
            states=_states(item.get("states", []), str(item["key"]), seed),
            cycles=_cycles(item.get("cycles", []), str(item["key"]), seed),
        )
        for item in raw
    )


def _label(item: dict[str, Any], team_key: str | None, seed: int) -> Label:
    return Label(
        id=uuid_for(seed, "linear", "label", str(item["key"])),
        key=str(item["key"]),
        name=str(item.get("name", item["key"])),
        color=str(item.get("color", "#95a2b3")),
        team_key=team_key,
    )


def _labels(section: dict[str, Any], seed: int) -> tuple[Label, ...]:
    labels = [_label(item, None, seed) for item in section.get("labels", [])]
    for team in section.get("teams", []):
        labels.extend(_label(item, str(team["key"]), seed) for item in team.get("labels", []))
    return tuple(labels)


def _milestones(raw: list[dict[str, Any]], project_key: str, seed: int) -> tuple[Milestone, ...]:
    return tuple(
        Milestone(
            id=uuid_for(seed, "linear", "milestone", str(item["key"])),
            key=str(item["key"]),
            name=str(item.get("name", item["key"])),
            target_date=item.get("targetDate"),
            project_key=project_key,
        )
        for item in raw
    )


def _projects(raw: list[dict[str, Any]], seed: int, clock: datetime) -> tuple[Project, ...]:
    return tuple(
        Project(
            id=uuid_for(seed, "linear", "project", str(item["key"])),
            key=str(item["key"]),
            name=str(item.get("name", item["key"])),
            description=str(item.get("description", "")),
            state=str(item.get("state", "planned")),
            lead_key=item.get("lead"),
            team_keys=tuple(str(team) for team in item.get("teams", [])),
            start_date=item.get("startDate"),
            target_date=item.get("targetDate"),
            created_at=parse_ts(item["createdAt"]) if "createdAt" in item else clock,
            updated_at=parse_ts(item["updatedAt"]) if "updatedAt" in item else clock,
            label_keys=tuple(str(label) for label in item.get("labels", [])),
            milestones=_milestones(item.get("milestones", []), str(item["key"]), seed),
        )
        for item in raw
    )


def _documents(raw: list[dict[str, Any]], seed: int, clock: datetime) -> tuple[Document, ...]:
    return tuple(
        Document(
            id=uuid_for(seed, "linear", "document", str(item["key"])),
            key=str(item["key"]),
            title=str(item.get("title", item["key"])),
            content=str(item.get("content", "")),
            project_key=item.get("project"),
            issue_identifier=item.get("issue"),
            creator_key=str(item.get("creator", "")),
            created_at=parse_ts(item["createdAt"]) if "createdAt" in item else clock,
            updated_at=parse_ts(item["updatedAt"]) if "updatedAt" in item else clock,
        )
        for item in raw
    )


def load(section: dict[str, Any], seed: int, clock: datetime) -> LinearState:
    users = _users(section.get("users", []), seed)
    viewer_key = str(section.get("viewer", ""))
    viewer = next(
        (user for user in users if user.key == viewer_key),
        User(
            id=uuid_for(seed, "linear", "user", ""),
            key="",
            name="",
            display_name="",
            email="",
            active=True,
        ),
    )
    teams = _teams(section.get("teams", []), seed)
    projects = _projects(section.get("projects", []), seed, clock)
    return LinearState(
        organization=_organization(section.get("organization", {}), seed),
        viewer=viewer,
        users=users,
        teams=teams,
        labels=_labels(section, seed),
        projects=projects,
        documents=_documents(section.get("documents", []), seed, clock),
        issues=load_issues(section.get("issues", []), teams, users, projects, seed, clock),
    )
