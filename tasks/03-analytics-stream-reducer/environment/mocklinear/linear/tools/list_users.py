from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import list_schema, paged
from ..render import user_json

SCHEMA = list_schema(
    {"query": {"type": "string", "description": "Text to look for in the name or email."}}
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    wanted = str(arguments["query"]).casefold() if arguments.get("query") else None
    users = [
        user
        for user in state.users
        if wanted is None or wanted in f"{user.name} {user.display_name} {user.email}".casefold()
    ]
    return paged("users", sorted(users, key=lambda user: user.display_name), arguments, user_json)


SPEC = ToolSpec(
    name="list_users",
    description="List the members of the workspace.",
    input_schema=SCHEMA,
    handler=handler,
)
