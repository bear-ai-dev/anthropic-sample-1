from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import list_schema, paged
from ..render_project import project_json

SCHEMA = list_schema(
    {
        "team": {"type": "string", "description": "Team id, key or name."},
        "state": {
            "type": "string",
            "description": "Project state: planned, started, paused, completed or canceled.",
        },
    }
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    team = state.team(str(arguments["team"])) if arguments.get("team") else None
    wanted = str(arguments["state"]).casefold() if arguments.get("state") else None
    projects = [
        project
        for project in state.projects
        if (team is None or team.key in project.team_keys)
        and (wanted is None or project.state.casefold() == wanted)
    ]
    return paged(
        "projects",
        sorted(projects, key=lambda project: project.name),
        arguments,
        lambda project: project_json(state, project),
    )


SPEC = ToolSpec(
    name="list_projects",
    description="List projects, filtered by team or project state.",
    input_schema=SCHEMA,
    handler=handler,
)
