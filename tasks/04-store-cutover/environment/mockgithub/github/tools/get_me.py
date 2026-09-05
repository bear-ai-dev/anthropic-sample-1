from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import compact
from ..render_users import minimal_user

SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.github
    return compact(minimal_user(state, state.viewer))


SPEC = ToolSpec("get_me", "Get details of the authenticated GitHub user.", SCHEMA, handle)
