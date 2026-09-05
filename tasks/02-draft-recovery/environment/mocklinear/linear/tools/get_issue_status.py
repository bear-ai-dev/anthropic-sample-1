from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, json_result
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import object_schema
from ..lookup import found
from ..render import status_json

SCHEMA = object_schema(
    {
        "id": {"type": "string", "description": "Workflow state id or name."},
        "team": {"type": "string", "description": "Team id, key or name."},
    },
    ["id"],
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    key = str(arguments["id"])
    team = state.team(str(arguments["team"])) if arguments.get("team") else None
    status = found(state.workflow_state(key, team), "WorkflowState", key)
    return json_result(status_json(state, status))


SPEC = ToolSpec(
    name="get_issue_status",
    description="Get one workflow state by id or name, optionally within a team.",
    input_schema=SCHEMA,
    handler=handler,
)
