from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, json_result
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import object_schema
from ..lookup import found
from ..render_project import project_json

SCHEMA = object_schema({"id": {"type": "string", "description": "Project id or name."}}, ["id"])


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    key = str(arguments["id"])
    project = found(state.project(key), "Project", key)
    return json_result(project_json(state, project))


SPEC = ToolSpec(
    name="get_project",
    description="Get one project by id or name.",
    input_schema=SCHEMA,
    handler=handler,
)
