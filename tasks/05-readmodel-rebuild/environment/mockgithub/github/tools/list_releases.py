from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import compact, rest_list
from ..lookup import PAGE_SCHEMA, REPO_SCHEMA, repo_of
from ..render_repo import release

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {**REPO_SCHEMA, **PAGE_SCHEMA},
    "required": ["owner", "repo"],
}


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    repo = repo_of(world, arguments)
    rendered, page = rest_list(list(repo.releases), arguments, lambda item: release(repo, item))
    return compact(rendered, page=page)


SPEC = ToolSpec("list_releases", "List releases in a GitHub repository.", SCHEMA, handle)
