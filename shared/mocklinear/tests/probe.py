from typing import Any

from mocklinear.linear.errors import ERRORS
from mocklinear.registry import ServiceRegistry
from mocklinear.tool_errors import InvalidArguments, NotFound
from mocklinear.tool_result import ToolResult, json_result
from mocklinear.tool_spec import ToolSpec
from mocklinear.world import World

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"limit": {"type": "integer"}, "id": {"type": "string"}},
}


def _echo(world: World, arguments: dict[str, Any]) -> ToolResult:
    return json_result(dict(arguments, viewer=world.linear.viewer.key), page={"limit": 1})


def _paged(world: World, arguments: dict[str, Any]) -> ToolResult:
    return json_result({"limit": arguments["limit"]})


def _boom(world: World, arguments: dict[str, Any]) -> ToolResult:
    raise NotFound("Issue", "WEB-999")


def _bad(world: World, arguments: dict[str, Any]) -> ToolResult:
    raise InvalidArguments("Invalid cursor")


PAGED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"limit": {"type": "integer", "default": 50}},
}

SPECS = [
    ToolSpec("echo", "Echo the arguments back", SCHEMA, _echo),
    ToolSpec("paged", "Report the limit it was given", PAGED_SCHEMA, _paged),
    ToolSpec("boom", "Always miss", SCHEMA, _boom),
    ToolSpec("bad", "Always refuse", SCHEMA, _bad),
]


def registries() -> dict[str, ServiceRegistry]:
    return {"probe": ServiceRegistry("probe", SPECS, ERRORS)}
