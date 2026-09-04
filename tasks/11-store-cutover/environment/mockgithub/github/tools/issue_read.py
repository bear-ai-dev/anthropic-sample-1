from __future__ import annotations

from typing import Any

from ...tool_errors import NotFound
from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import compact, rest_list
from ..lookup import PAGE_SCHEMA, REPO_SCHEMA, issue_of, repo_of
from ..render_issues import comment, full_label, rest_issue

METHODS = ["get", "get_comments", "get_sub_issues", "get_parent", "get_labels"]
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "method": {"type": "string", "enum": METHODS, "description": "The read operation"},
        **REPO_SCHEMA,
        "issue_number": {"type": "integer", "description": "The number of the issue"},
        **PAGE_SCHEMA,
    },
    "required": ["method", "owner", "repo", "issue_number"],
}


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    repo = repo_of(world, arguments)
    state = world.github
    issue = issue_of(repo, int(arguments["issue_number"]))
    method = arguments["method"]
    if method == "get":
        return compact(rest_issue(repo, issue, state))
    if method == "get_labels":
        found = [label for label in (repo.label(name) for name in issue.label_names) if label]
        return compact([full_label(repo, label) for label in found])
    if method == "get_parent":
        parent = None if issue.parent_number is None else repo.issue(issue.parent_number)
        if parent is None:
            raise NotFound("parent", f"{repo.full_name}/issues/{issue.number}/parent")
        return compact(rest_issue(repo, parent, state))
    if method == "get_sub_issues":
        children = [child for child in map(repo.issue, issue.sub_issue_numbers) if child]
        rendered, page = rest_list(children, arguments, lambda c: rest_issue(repo, c, state))
        return compact(rendered, page=page)
    rendered, page = rest_list(
        list(issue.comments),
        arguments,
        lambda item: comment(repo, "issues", issue.number, item, state),
    )
    return compact(rendered, page=page)


SPEC = ToolSpec(
    "issue_read",
    "Get information about a specific issue: details, comments, sub-issues, parent or labels.",
    SCHEMA,
    handle,
)
