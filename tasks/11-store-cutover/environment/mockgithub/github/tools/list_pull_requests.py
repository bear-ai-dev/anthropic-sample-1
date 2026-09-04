from __future__ import annotations

from datetime import datetime
from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import compact, rest_list
from ..lookup import PAGE_SCHEMA, REPO_SCHEMA, repo_of
from ..models_pulls import Pull
from ..render_pulls import rest_pull

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **REPO_SCHEMA,
        "state": {
            "type": "string",
            "enum": ["open", "closed", "all"],
            "description": "Filter by state",
            "default": "open",
        },
        "head": {"type": "string", "description": "Filter by head user/org and branch"},
        "base": {"type": "string", "description": "Filter by base branch"},
        "sort": {
            "type": "string",
            "enum": ["created", "updated", "popularity", "long-running"],
            "description": "Sort by",
            "default": "created",
        },
        "direction": {
            "type": "string",
            "enum": ["asc", "desc"],
            "description": "Sort direction",
            "default": "desc",
        },
        **PAGE_SCHEMA,
    },
    "required": ["owner", "repo"],
}


def _sort_key(pull: Pull, sort: str) -> tuple[datetime | int, int]:
    if sort == "updated":
        return pull.updated_at, pull.number
    if sort == "popularity":
        return len(pull.comments) + len(pull.reviews), pull.number
    return pull.created_at, pull.number


def _selected(pulls: tuple[Pull, ...], arguments: dict[str, Any]) -> list[Pull]:
    state = str(arguments.get("state", "open"))
    head = arguments.get("head")
    head_ref = None if head is None else str(head).split(":")[-1]
    base = arguments.get("base")
    selected = [
        pull
        for pull in pulls
        if state in ("all", pull.state)
        and (head_ref is None or pull.head_ref == head_ref)
        and (base is None or pull.base_ref == str(base))
    ]
    sort = str(arguments.get("sort", "created"))
    descending = str(arguments.get("direction", "desc")) == "desc"
    selected.sort(key=lambda pull: _sort_key(pull, sort), reverse=descending)
    return selected


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    repo = repo_of(world, arguments)
    state = world.github
    rendered, page = rest_list(
        _selected(repo.pulls, arguments), arguments, lambda pull: rest_pull(repo, pull, state)
    )
    return compact(rendered, page=page)


SPEC = ToolSpec("list_pull_requests", "List pull requests in a GitHub repository.", SCHEMA, handle)
