from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import list_schema, paged
from ..filters import matching_issues
from ..render_issue import issue_json

SCHEMA = list_schema(
    {
        "assignee": {
            "type": "string",
            "description": "Assignee id, name, email, or 'me' for the signed-in user.",
        },
        "team": {"type": "string", "description": "Team id, key or name."},
        "state": {"type": "string", "description": "Workflow state name or type."},
        "label": {"type": "string", "description": "Issue label id or name."},
        "project": {"type": "string", "description": "Project id or name."},
        "cycle": {"type": "string", "description": "Cycle id, number or name."},
        "parent": {"type": "string", "description": "Parent issue id or identifier."},
        "createdAt": {
            "type": "string",
            "description": "Only issues created on or after this moment: an ISO 8601 timestamp, "
            "or a relative ISO 8601 duration such as -P1W or -P1M.",
        },
        "updatedAt": {
            "type": "string",
            "description": "Only issues updated on or after this moment: an ISO 8601 timestamp, "
            "or a relative ISO 8601 duration such as -P1W or -P1M.",
        },
        "query": {"type": "string", "description": "Text to look for in identifier, title, body."},
        "orderBy": {
            "type": "string",
            "description": "Sort field, newest first.",
            "enum": ["createdAt", "updatedAt"],
        },
    }
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    issues = matching_issues(state, arguments, world.clock)
    return paged("issues", issues, arguments, lambda issue: issue_json(state, issue))


SPEC = ToolSpec(
    name="list_issues",
    description="List issues in the workspace, filtered by assignee, team, state, label, "
    "project, cycle, parent, timestamps or free text.",
    input_schema=SCHEMA,
    handler=handler,
)
