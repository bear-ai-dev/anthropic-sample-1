from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import search_result
from ..history import resolve_ref, tree_at
from ..render_repo import code_item
from ..search_query import matches, parse

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query using GitHub code search syntax"},
        "sort": {"type": "string", "description": "Sort field ('indexed' only)"},
        "order": {"type": "string", "enum": ["asc", "desc"], "description": "Sort order"},
        "page": {"type": "integer", "description": "Page number (min 1)", "default": 1},
        "perPage": {"type": "integer", "description": "Results per page", "default": 30},
    },
    "required": ["query"],
}


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    query = parse(str(arguments["query"]))
    items: list[dict[str, Any]] = []
    for repo in world.github.repos:
        head = resolve_ref(repo, repo.default_branch)
        if head is None:
            continue
        for change in tree_at(repo, head):
            document = {
                "repo": repo.full_name,
                "path": change.path,
                "filename": change.path.rsplit("/", 1)[-1],
                "content": change.content or "",
            }
            if matches(query, document):
                items.append(code_item(repo, head, change))
    return search_result(items, arguments)


SPEC = ToolSpec("search_code", "Search for code across GitHub repositories.", SCHEMA, handle)
