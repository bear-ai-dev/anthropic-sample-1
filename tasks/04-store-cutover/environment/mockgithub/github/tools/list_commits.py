from __future__ import annotations

from typing import Any

from ...clock import parse_ts
from ...tool_errors import NotFound
from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import compact, rest_list
from ..history import ancestry, resolve_ref
from ..lookup import PAGE_SCHEMA, REPO_SCHEMA, repo_of
from ..models_repo import Commit
from ..render_repo import commit as render_commit

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **REPO_SCHEMA,
        "sha": {
            "type": "string",
            "description": "Commit SHA, branch or tag name to list commits of",
        },
        "path": {"type": "string", "description": "Only commits containing this file path"},
        "author": {"type": "string", "description": "Author username or email address"},
        "since": {"type": "string", "description": "Only commits after this date (ISO 8601)"},
        "until": {"type": "string", "description": "Only commits before this date (ISO 8601)"},
        **PAGE_SCHEMA,
    },
    "required": ["owner", "repo"],
}


def _keep(commit: Commit, arguments: dict[str, Any]) -> bool:
    path, author = arguments.get("path"), arguments.get("author")
    since = None if "since" not in arguments else parse_ts(str(arguments["since"]))
    until = None if "until" not in arguments else parse_ts(str(arguments["until"]))
    return (
        (path is None or any(change.path == str(path) for change in commit.files))
        and (author is None or commit.author_login == str(author))
        and (since is None or commit.date >= since)
        and (until is None or commit.date <= until)
    )


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    repo = repo_of(world, arguments)
    ref = str(arguments.get("sha", repo.default_branch))
    head = resolve_ref(repo, ref)
    if head is None:
        raise NotFound("ref", f"{repo.full_name}/commits?sha={ref}")
    selected = [commit for commit in ancestry(repo, head) if _keep(commit, arguments)]
    state = world.github
    rendered, page = rest_list(selected, arguments, lambda c: render_commit(repo, c, state))
    return compact(rendered, page=page)


SPEC = ToolSpec(
    "list_commits", "Get list of commits of a branch in a GitHub repository.", SCHEMA, handle
)
