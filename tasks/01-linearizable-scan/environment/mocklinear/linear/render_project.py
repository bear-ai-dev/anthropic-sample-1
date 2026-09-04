from __future__ import annotations

from typing import Any

from .models import Cycle, Document, Milestone, Project
from .render import _ts, _url, issue_ref, labels_json, team_ref, user_ref
from .state import LinearState


def project_by_key(state: LinearState, key: str | None) -> Project | None:
    return next((project for project in state.projects if project.key == key), None)


def project_ref(state: LinearState, key: str | None) -> dict[str, Any] | None:
    project = project_by_key(state, key)
    return None if project is None else {"id": project.id, "name": project.name}


def project_json(state: LinearState, project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "state": project.state,
        "lead": user_ref(state, project.lead_key),
        "teams": [team_ref(state.team(key)) for key in project.team_keys],
        "startDate": project.start_date,
        "targetDate": project.target_date,
        "createdAt": _ts(project.created_at),
        "updatedAt": _ts(project.updated_at),
        "labels": labels_json(state, project.label_keys),
        "url": _url(state, "project", project.key),
    }


def milestone_ref(state: LinearState, key: str | None) -> dict[str, Any] | None:
    milestone = next((item for item in state.milestones() if item.key == key), None)
    if milestone is None:
        return None
    return {"id": milestone.id, "name": milestone.name, "targetDate": milestone.target_date}


def milestone_json(state: LinearState, milestone: Milestone) -> dict[str, Any]:
    return {
        "id": milestone.id,
        "name": milestone.name,
        "targetDate": milestone.target_date,
        "project": project_ref(state, milestone.project_key),
    }


def cycle_ref(state: LinearState, key: str | None) -> dict[str, Any] | None:
    cycle = next((item for item in state.cycles() if item.key == key), None)
    if cycle is None:
        return None
    return {"id": cycle.id, "number": cycle.number, "name": cycle.name}


def cycle_json(state: LinearState, cycle: Cycle) -> dict[str, Any]:
    return {
        "id": cycle.id,
        "number": cycle.number,
        "name": cycle.name,
        "startsAt": _ts(cycle.starts_at),
        "endsAt": _ts(cycle.ends_at),
        "team": team_ref(state.team(cycle.team_key)),
    }


def document_json(state: LinearState, document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "title": document.title,
        "slugId": document.key,
        "content": document.content,
        "project": project_ref(state, document.project_key),
        "issue": issue_ref(state, document.issue_identifier),
        "creator": user_ref(state, document.creator_key),
        "createdAt": _ts(document.created_at),
        "updatedAt": _ts(document.updated_at),
        "url": _url(state, "document", document.key),
    }
