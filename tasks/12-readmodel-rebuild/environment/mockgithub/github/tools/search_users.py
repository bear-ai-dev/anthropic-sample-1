from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import search_result
from ..models_issues import User
from ..render_users import search_user
from ..search_query import parse

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "User search query"},
        "sort": {"type": "string", "description": "Sort field"},
        "order": {"type": "string", "enum": ["asc", "desc"], "description": "Sort order"},
        "page": {"type": "integer", "description": "Page number (min 1)", "default": 1},
        "perPage": {"type": "integer", "description": "Results per page", "default": 30},
    },
    "required": ["query"],
}


def _matches(user: User, terms: tuple[tuple[str, bool], ...]) -> bool:
    haystack = f"{user.login}\n{user.name}\n{user.email}".casefold()
    return all((term in haystack) != negated for term, negated in terms)


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    terms = parse(str(arguments["query"])).terms
    users = [search_user(user) for user in world.github.users if _matches(user, terms)]
    return search_result(users, arguments)


SPEC = ToolSpec(
    "search_users",
    "Find GitHub users by username, real name, or other profile information.",
    SCHEMA,
    handle,
)
