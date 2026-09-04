from __future__ import annotations

from typing import Any

from ..tool_errors import NotFound
from ..world import World
from .history import resolve_ref
from .models_issues import Issue
from .models_pulls import Pull
from .models_repo import Commit, Repo

REPO_SCHEMA: dict[str, Any] = {
    "owner": {"type": "string", "description": "Repository owner"},
    "repo": {"type": "string", "description": "Repository name"},
}
PAGE_SCHEMA: dict[str, Any] = {
    "page": {"type": "integer", "description": "Page number (min 1)", "default": 1},
    "perPage": {
        "type": "integer",
        "description": "Results per page (min 1, max 100)",
        "default": 30,
    },
}


def repo_of(world: World, args: dict[str, Any]) -> Repo:
    owner, name = str(args["owner"]), str(args["repo"])
    repo = world.github.repo(owner, name)
    if repo is None:
        raise NotFound("repository", f"{owner}/{name}")
    return repo


def issue_of(repo: Repo, number: int) -> Issue:
    issue = repo.issue(number)
    if issue is None:
        raise NotFound("issue", f"{repo.full_name}/issues/{number}")
    return issue


def pull_of(repo: Repo, number: int) -> Pull:
    pull = repo.pull(number)
    if pull is None:
        raise NotFound("pull", f"{repo.full_name}/pulls/{number}")
    return pull


def commit_of(repo: Repo, sha: str) -> Commit:
    commit = resolve_ref(repo, sha)
    if commit is None:
        raise NotFound("commit", f"{repo.full_name}/commits/{sha}")
    return commit
