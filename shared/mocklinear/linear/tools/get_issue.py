from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, json_result
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import object_schema
from ..lookup import found
from ..render_issue import issue_json

SCHEMA = object_schema(
    {"id": {"type": "string", "description": "Issue id or identifier such as WEB-611."}},
    ["id"],
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    key = str(arguments["id"])
    issue = found(state.issue(key), "Issue", key)
    return json_result(issue_json(state, issue, detail=True))


SPEC = ToolSpec(
    name="get_issue",
    description="Get one issue by id or identifier, with its attachments and branch name.",
    input_schema=SCHEMA,
    handler=handler,
)
