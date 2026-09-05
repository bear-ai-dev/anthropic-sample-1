from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import list_schema, paged
from ..render import label_json

SCHEMA = list_schema({"team": {"type": "string", "description": "Team id, key or name."}})


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    team = state.team(str(arguments["team"])) if arguments.get("team") else None
    labels = [label for label in state.labels if team is None or label.team_key in (None, team.key)]
    return paged(
        "labels",
        sorted(labels, key=lambda label: label.name),
        arguments,
        lambda label: label_json(state, label),
    )


SPEC = ToolSpec(
    name="list_issue_labels",
    description="List issue labels: the workspace labels plus the labels a team defines.",
    input_schema=SCHEMA,
    handler=handler,
)
