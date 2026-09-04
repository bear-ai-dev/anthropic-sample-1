from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, text_result
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import object_schema

SCHEMA = object_schema(
    {"query": {"type": "string", "description": "What to look for in the Linear docs."}},
    ["query"],
)

ANSWER = (
    "No documentation matched that query. Linear's documentation lives at https://linear.app/docs."
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    return text_result(ANSWER)


SPEC = ToolSpec(
    name="search_documentation",
    description="Search Linear's product documentation.",
    input_schema=SCHEMA,
    handler=handler,
)
