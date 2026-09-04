from __future__ import annotations

from datetime import datetime
from typing import Any

from ..clock import iso_seconds
from .models_issues import Comment, Issue, Label, Milestone
from .models_repo import Repo
from .render_users import ref_for
from .state import GithubState

API = "https://api.github.com/repos/"


def stamp(moment: datetime | None) -> str | None:
    return None if moment is None else iso_seconds(moment)


def label(item: Label) -> dict[str, Any]:
    return {"name": item.name, "color": item.color, "description": item.description}


def full_label(repo: Repo, item: Label) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "color": item.color,
        "description": item.description,
        "url": f"{API}{repo.full_name}/labels/{item.name}",
    }


def labels(repo: Repo, names: tuple[str, ...]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for name in names:
        found = repo.label(name)
        rendered.append(label(found) if found is not None else {"name": name})
    return rendered


def milestone(item: Milestone | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "number": item.number,
        "title": item.title,
        "state": item.state,
        "due_on": stamp(item.due_on),
    }


def rest_issue(repo: Repo, issue: Issue, state: GithubState) -> dict[str, Any]:
    closed = issue.state == "closed"
    return {
        "number": issue.number,
        "title": issue.title,
        "body": issue.body,
        "state": issue.state,
        "state_reason": "completed" if closed else None,
        "user": ref_for(state, issue.user_login),
        "labels": labels(repo, issue.label_names),
        "assignees": [ref_for(state, login) for login in issue.assignee_logins],
        "milestone": milestone(
            None if issue.milestone_number is None else repo.milestone(issue.milestone_number)
        ),
        "comments": len(issue.comments),
        "created_at": iso_seconds(issue.created_at),
        "updated_at": iso_seconds(issue.updated_at),
        "closed_at": stamp(issue.closed_at),
        "html_url": f"{repo.html_url}/issues/{issue.number}",
    }


def graphql_issue(issue: Issue) -> dict[str, Any]:
    return {
        "number": issue.number,
        "title": issue.title,
        "body": issue.body,
        "state": issue.state.upper(),
        "author": {"login": issue.user_login},
        "labels": {"nodes": [{"name": name} for name in issue.label_names]},
        "createdAt": iso_seconds(issue.created_at),
        "updatedAt": iso_seconds(issue.updated_at),
        "closedAt": stamp(issue.closed_at),
        "comments": {"totalCount": len(issue.comments)},
    }


def comment(
    repo: Repo, kind: str, number: int, item: Comment, state: GithubState
) -> dict[str, Any]:
    return {
        "id": item.id,
        "user": ref_for(state, item.user_login),
        "body": item.body,
        "created_at": iso_seconds(item.created_at),
        "updated_at": iso_seconds(item.created_at),
        "html_url": f"{repo.html_url}/{kind}/{number}#issuecomment-{item.id}",
    }


def search_issue(repo: Repo, issue: Issue, state: GithubState) -> dict[str, Any]:
    return dict(rest_issue(repo, issue, state), repository_url=f"{API}{repo.full_name}")


def search_document(repo: Repo, issue: Issue) -> dict[str, Any]:
    return {
        "type": "issue",
        "state": issue.state,
        "merged": False,
        "draft": False,
        "labels": list(issue.label_names),
        "author": issue.user_login,
        "assignees": list(issue.assignee_logins),
        "repo": repo.full_name,
        "title": issue.title,
        "body": issue.body,
    }
