from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, json_result
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import object_schema
from ..lookup import found
from ..render import user_json

SCHEMA = object_schema(
    {"id": {"type": "string", "description": "User id, name, email, or 'me'."}}, ["id"]
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    key = str(arguments["id"])
    return json_result(user_json(found(state.user(key), "User", key)))


SPEC = ToolSpec(
    name="get_user",
    description="Get one user by id, name, email, or 'me' for the signed-in user.",
    input_schema=SCHEMA,
    handler=handler,
)
