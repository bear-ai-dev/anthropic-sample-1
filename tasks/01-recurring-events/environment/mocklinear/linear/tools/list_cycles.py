from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..cycles import select_cycles
from ..envelope import list_schema, paged
from ..render_project import cycle_json

SCHEMA = list_schema(
    {
        "team": {"type": "string", "description": "Team id, key or name."},
        "type": {
            "type": "string",
            "description": "Which cycles to return (default all).",
            "enum": ["current", "previous", "next", "all"],
        },
    }
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    team = state.team(str(arguments["team"])) if arguments.get("team") else None
    cycles = select_cycles(state, team, str(arguments.get("type", "all")), world.clock)
    return paged("cycles", cycles, arguments, lambda cycle: cycle_json(state, cycle))


SPEC = ToolSpec(
    name="list_cycles",
    description="List a team's cycles: the current one, the previous one, the next one, or all.",
    input_schema=SCHEMA,
    handler=handler,
)
