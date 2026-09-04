from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, text_result
from ...tool_spec import ToolSpec
from ...world import World
from ..diff import commit_diff
from ..envelope import compact
from ..lookup import PAGE_SCHEMA, REPO_SCHEMA, commit_of, repo_of
from ..render_repo import commit as render_commit
from ..render_repo import commit_with_files

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **REPO_SCHEMA,
        "sha": {"type": "string", "description": "Commit SHA, branch name, or tag name"},
        "detail": {
            "type": "string",
            "enum": ["summary", "diff", "raw"],
            "description": "How much of the commit to return",
            "default": "summary",
        },
        **PAGE_SCHEMA,
    },
    "required": ["owner", "repo", "sha"],
}


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    repo = repo_of(world, arguments)
    commit = commit_of(repo, str(arguments["sha"]))
    detail = str(arguments.get("detail", "summary"))
    if detail == "raw":
        return text_result(commit_diff(repo, commit))
    if detail == "diff":
        return compact(commit_with_files(repo, commit, world.github))
    return compact(render_commit(repo, commit, world.github))


SPEC = ToolSpec("get_commit", "Get details for a commit from a GitHub repository.", SCHEMA, handle)
