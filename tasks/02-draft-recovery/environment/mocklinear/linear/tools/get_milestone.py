from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, json_result
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import object_schema
from ..lookup import found
from ..render_project import milestone_json

SCHEMA = object_schema({"id": {"type": "string", "description": "Milestone id or name."}}, ["id"])


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    key = str(arguments["id"])
    milestone = found(state.milestone(key), "ProjectMilestone", key)
    return json_result(milestone_json(state, milestone))


SPEC = ToolSpec(
    name="get_milestone",
    description="Get one project milestone by id or name.",
    input_schema=SCHEMA,
    handler=handler,
)
