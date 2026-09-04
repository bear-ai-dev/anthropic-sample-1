from types import SimpleNamespace
from typing import Any, cast

from mocklinear.linear.state import LinearState
from mocklinear.tool_result import ToolResult, text_result
from mocklinear.tool_spec import ToolSpec
from mocklinear.world import World

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"id": {"type": "string"}},
    "required": ["id"],
}


def _handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    return text_result(f"{world}:{arguments['id']}")


def _spec() -> ToolSpec:
    return ToolSpec(
        name="get_issue", description="Get an issue", input_schema=SCHEMA, handler=_handler
    )


def test_a_spec_publishes_the_mcp_descriptor_of_its_tool() -> None:
    assert _spec().descriptor() == {
        "name": "get_issue",
        "description": "Get an issue",
        "inputSchema": SCHEMA,
    }


def test_a_spec_calls_through_to_its_handler(state: LinearState) -> None:
    world = cast(World, SimpleNamespace(linear=state))
    assert _spec().handler(world, {"id": "ENG-1"}) == text_result(f"{world}:ENG-1")
