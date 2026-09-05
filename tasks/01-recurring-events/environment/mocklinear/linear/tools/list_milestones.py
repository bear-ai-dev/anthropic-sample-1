from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import list_schema, paged
from ..render_project import milestone_json

SCHEMA = list_schema({"project": {"type": "string", "description": "Project id or name."}})


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    project = state.project(str(arguments["project"])) if arguments.get("project") else None
    milestones = [
        milestone
        for milestone in state.milestones()
        if project is None or milestone.project_key == project.key
    ]
    return paged("milestones", milestones, arguments, lambda item: milestone_json(state, item))


SPEC = ToolSpec(
    name="list_milestones",
    description="List project milestones, optionally within one project.",
    input_schema=SCHEMA,
    handler=handler,
)
