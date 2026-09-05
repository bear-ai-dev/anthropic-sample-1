from __future__ import annotations

from typing import Any

from ...tool_errors import NotFound
from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import compact
from ..lookup import REPO_SCHEMA, repo_of
from ..render_issues import full_label

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {**REPO_SCHEMA, "name": {"type": "string", "description": "Label name"}},
    "required": ["owner", "repo", "name"],
}


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    repo = repo_of(world, arguments)
    name = str(arguments["name"])
    label = repo.label(name)
    if label is None:
        raise NotFound("label", f"{repo.full_name}/labels/{name}")
    return compact(full_label(repo, label))


SPEC = ToolSpec("get_label", "Get a specific label from a repository.", SCHEMA, handle)
