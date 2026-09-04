from __future__ import annotations

from typing import Any

from ..clock import iso_seconds
from .models_pulls import CheckRun, Pull, Review, ReviewComment, Status
from .models_repo import Repo
from .render_issues import API, labels, stamp
from .render_users import ref_for
from .state import GithubState


def head_sha(repo: Repo, pull: Pull) -> str:
    commit = repo.commit_by_key(pull.head_key)
    return "" if commit is None else commit.sha


def rest_pull(repo: Repo, pull: Pull, state: GithubState) -> dict[str, Any]:
    return {
        "number": pull.number,
        "title": pull.title,
        "body": pull.body,
        "state": pull.state,
        "draft": pull.draft,
        "merged": pull.merged,
        "merged_at": stamp(pull.merged_at),
        "head": {"ref": pull.head_ref, "sha": head_sha(repo, pull)},
        "base": {"ref": pull.base_ref},
        "user": ref_for(state, pull.user_login),
        "labels": labels(repo, pull.label_names),
        "html_url": f"{repo.html_url}/pull/{pull.number}",
        "created_at": iso_seconds(pull.created_at),
        "updated_at": iso_seconds(pull.updated_at),
        "mergeable_state": "clean" if pull.state == "open" else "unknown",
    }


def search_pull(repo: Repo, pull: Pull, state: GithubState) -> dict[str, Any]:
    html_url = f"{repo.html_url}/pull/{pull.number}"
    return {
        "number": pull.number,
        "title": pull.title,
        "body": pull.body,
        "state": pull.state,
        "state_reason": None,
        "user": ref_for(state, pull.user_login),
        "labels": labels(repo, pull.label_names),
        "assignees": [],
        "milestone": None,
        "comments": len(pull.comments),
        "created_at": iso_seconds(pull.created_at),
        "updated_at": iso_seconds(pull.updated_at),
        "closed_at": stamp(pull.closed_at),
        "html_url": html_url,
        "pull_request": {
            "url": f"{API}{repo.full_name}/pulls/{pull.number}",
            "html_url": html_url,
            "diff_url": f"{html_url}.diff",
            "patch_url": f"{html_url}.patch",
            "merged_at": stamp(pull.merged_at),
        },
        "repository_url": f"{API}{repo.full_name}",
    }


def search_document(repo: Repo, pull: Pull) -> dict[str, Any]:
    return {
        "type": "pr",
        "state": pull.state,
        "merged": pull.merged,
        "draft": pull.draft,
        "labels": list(pull.label_names),
        "author": pull.user_login,
        "assignees": [],
        "repo": repo.full_name,
        "title": pull.title,
        "body": pull.body,
    }


def review(item: Review) -> dict[str, Any]:
    return {
        "id": item.id,
        "user": {"login": item.user_login},
        "state": item.state,
        "body": item.body,
        "submitted_at": iso_seconds(item.submitted_at),
    }


def review_thread(item: ReviewComment) -> dict[str, Any]:
    node = {
        "id": item.id,
        "body": item.body,
        "path": item.path,
        "line": item.line,
        "author": {"login": item.user_login},
    }
    return {"id": item.id, "isResolved": False, "comments": {"nodes": [node]}}


def check_run(item: CheckRun, sha: str) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "status": item.status,
        "conclusion": item.conclusion,
        "head_sha": sha,
    }


def status(item: Status) -> dict[str, Any]:
    return {
        "context": item.context,
        "state": item.state,
        "description": item.description,
        "target_url": item.target_url,
    }


def combined_status(repo: Repo, pull: Pull) -> dict[str, Any]:
    states = {item.state for item in pull.statuses}
    if not states:
        overall = "pending"
    elif states & {"failure", "error"}:
        overall = "failure"
    elif states == {"success"}:
        overall = "success"
    else:
        overall = "pending"
    return {
        "state": overall,
        "statuses": [status(item) for item in pull.statuses],
        "sha": head_sha(repo, pull),
        "total_count": len(pull.statuses),
    }
