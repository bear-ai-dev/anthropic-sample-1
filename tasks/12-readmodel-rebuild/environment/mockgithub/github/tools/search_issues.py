from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import search_result
from .search_common import SEARCH_SCHEMA, search


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    return search_result(search(world, arguments, "issue"), arguments)


SPEC = ToolSpec(
    "search_issues",
    "Search for issues in GitHub repositories using issues search syntax.",
    SEARCH_SCHEMA,
    handle,
)
