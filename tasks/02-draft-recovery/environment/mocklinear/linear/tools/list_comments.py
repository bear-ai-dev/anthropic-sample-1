from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import list_schema, paged
from ..lookup import found
from ..render_issue import comment_json

SCHEMA = list_schema(
    {"issueId": {"type": "string", "description": "Issue id or identifier."}},
)
SCHEMA["required"] = ["issueId"]


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    key = str(arguments["issueId"])
    issue = found(state.issue(key), "Issue", key)
    comments = sorted(issue.comments, key=lambda comment: comment.created_at)
    return paged("comments", comments, arguments, lambda comment: comment_json(state, comment))


SPEC = ToolSpec(
    name="list_comments",
    description="List the comments on one issue, oldest first, threaded through parentId.",
    input_schema=SCHEMA,
    handler=handler,
)
