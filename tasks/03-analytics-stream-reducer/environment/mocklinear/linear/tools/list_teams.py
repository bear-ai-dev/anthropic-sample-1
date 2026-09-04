from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import list_schema, paged
from ..render import team_json

SCHEMA = list_schema(
    {"query": {"type": "string", "description": "Text to look for in the key or name."}}
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    wanted = str(arguments["query"]).casefold() if arguments.get("query") else None
    teams = [
        team
        for team in state.teams
        if wanted is None or wanted in f"{team.key} {team.name}".casefold()
    ]
    return paged(
        "teams",
        sorted(teams, key=lambda team: team.key),
        arguments,
        lambda team: team_json(state, team),
    )


SPEC = ToolSpec(
    name="list_teams",
    description="List the teams in the workspace.",
    input_schema=SCHEMA,
    handler=handler,
)
