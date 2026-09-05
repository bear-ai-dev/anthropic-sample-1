from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, json_result
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import object_schema
from ..lookup import found
from ..render import team_json

SCHEMA = object_schema({"id": {"type": "string", "description": "Team id, key or name."}}, ["id"])


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    key = str(arguments["id"])
    return json_result(team_json(state, found(state.team(key), "Team", key)))


SPEC = ToolSpec(
    name="get_team",
    description="Get one team by id, key or name.",
    input_schema=SCHEMA,
    handler=handler,
)
