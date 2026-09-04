from __future__ import annotations

from datetime import datetime
from typing import Any

from ...world import World
from ..models_issues import Issue
from ..models_pulls import Pull
from ..models_repo import Repo
from ..render_issues import search_document as issue_document
from ..render_issues import search_issue
from ..render_pulls import search_document as pull_document
from ..render_pulls import search_pull
from ..search_query import matches, parse

SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query using GitHub search syntax"},
        "owner": {"type": "string", "description": "Optional repository owner"},
        "repo": {"type": "string", "description": "Optional repository name"},
        "sort": {
            "type": "string",
            "enum": ["comments", "created", "updated"],
            "description": "Sort field by number of matches of categories",
        },
        "order": {"type": "string", "enum": ["asc", "desc"], "description": "Sort order"},
        "page": {"type": "integer", "description": "Page number (min 1)", "default": 1},
        "perPage": {"type": "integer", "description": "Results per page", "default": 30},
    },
    "required": ["query"],
}


def _repos(world: World, arguments: dict[str, Any]) -> list[Repo]:
    owner, name = arguments.get("owner"), arguments.get("repo")
    if owner is None or name is None:
        return list(world.github.repos)
    repo = world.github.repo(str(owner), str(name))
    return [] if repo is None else [repo]


def _key(item: Issue | Pull, sort: str) -> tuple[datetime | int, int]:
    if sort == "comments":
        return len(item.comments), item.number
    if sort == "updated":
        return item.updated_at, item.number
    return item.created_at, item.number


def search(world: World, arguments: dict[str, Any], kind: str) -> list[Any]:
    query = parse(f"is:{kind} {arguments['query']}")
    state = world.github
    hits: list[tuple[Issue | Pull, dict[str, Any]]] = []
    for repo in _repos(world, arguments):
        for issue in repo.issues:
            if matches(query, issue_document(repo, issue)):
                hits.append((issue, search_issue(repo, issue, state)))
        for pull in repo.pulls:
            if matches(query, pull_document(repo, pull)):
                hits.append((pull, search_pull(repo, pull, state)))
    sort = str(arguments.get("sort", "created"))
    hits.sort(key=lambda hit: _key(hit[0], sort), reverse=arguments.get("order", "desc") == "desc")
    return [rendered for _, rendered in hits]
