from __future__ import annotations

from typing import Any

from ...clock import parse_ts
from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import compact, graphql_list
from ..lookup import REPO_SCHEMA, repo_of
from ..models_issues import Issue
from ..render_issues import graphql_issue

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **REPO_SCHEMA,
        "state": {"type": "string", "enum": ["OPEN", "CLOSED"], "description": "Filter by state"},
        "labels": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Filter by labels (all must match)",
        },
        "orderBy": {
            "type": "string",
            "enum": ["CREATED_AT", "UPDATED_AT"],
            "description": "Order issues by field",
            "default": "CREATED_AT",
        },
        "direction": {
            "type": "string",
            "enum": ["ASC", "DESC"],
            "description": "Order direction",
            "default": "DESC",
        },
        "since": {"type": "string", "description": "Only issues updated at or after this time"},
        "perPage": {"type": "integer", "description": "Results per page", "default": 30},
        "after": {"type": "string", "description": "Cursor for pagination"},
    },
    "required": ["owner", "repo"],
}


def _selected(issues: tuple[Issue, ...], arguments: dict[str, Any]) -> list[Issue]:
    wanted_state = arguments.get("state")
    labels = [str(label) for label in arguments.get("labels", [])]
    since = None if "since" not in arguments else parse_ts(str(arguments["since"]))
    selected = [
        issue
        for issue in issues
        if (wanted_state is None or issue.state.upper() == wanted_state)
        and all(label in issue.label_names for label in labels)
        and (since is None or issue.updated_at >= since)
    ]
    by_updated = arguments.get("orderBy", "CREATED_AT") == "UPDATED_AT"
    selected.sort(
        key=lambda issue: (issue.updated_at if by_updated else issue.created_at, issue.number),
        reverse=arguments.get("direction", "DESC") == "DESC",
    )
    return selected


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    repo = repo_of(world, arguments)
    selected = _selected(repo.issues, arguments)
    rendered, info, page = graphql_list(selected, arguments, graphql_issue)
    payload = {"issues": rendered, "pageInfo": info, "totalCount": len(selected)}
    return compact(payload, page=page)


SPEC = ToolSpec("list_issues", "List issues in a GitHub repository.", SCHEMA, handle)
