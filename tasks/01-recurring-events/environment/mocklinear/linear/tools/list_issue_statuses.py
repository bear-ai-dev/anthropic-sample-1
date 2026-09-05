from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import list_schema, paged
from ..render import status_json

SCHEMA = list_schema({"team": {"type": "string", "description": "Team id, key or name."}})


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    team = state.team(str(arguments["team"])) if arguments.get("team") else None
    statuses = [
        status for status in state.workflow_states() if team is None or status.team_key == team.key
    ]
    return paged("statuses", statuses, arguments, lambda status: status_json(state, status))


SPEC = ToolSpec(
    name="list_issue_statuses",
    description="List the workflow states of a team, in board order.",
    input_schema=SCHEMA,
    handler=handler,
)
