from typing import Any

from mockgmail.gmail.errors import ERRORS
from mockgmail.registry import ServiceRegistry
from mockgmail.tool_errors import InvalidArguments, NotFound
from mockgmail.tool_result import ToolResult, json_result, text_result
from mockgmail.tool_spec import ToolSpec
from mockgmail.world import World

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"limit": {"type": "integer"}, "id": {"type": "string"}},
}


def _echo(world: World, arguments: dict[str, Any]) -> ToolResult:
    return json_result(dict(arguments, viewer=world.gmail.email_address), page={"limit": 1})


def _boom(world: World, arguments: dict[str, Any]) -> ToolResult:
    raise NotFound("Message", "0000000000000000")


def _bad(world: World, arguments: dict[str, Any]) -> ToolResult:
    raise InvalidArguments("Invalid cursor")


def _flag(world: World, arguments: dict[str, Any]) -> ToolResult:
    return text_result("refused", is_error=True)


def _paged(world: World, arguments: dict[str, Any]) -> ToolResult:
    return json_result({"maxResults": arguments["maxResults"]})


PAGED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"maxResults": {"type": "number", "default": 10}},
}


SPECS = [
    ToolSpec("echo", "Echo the arguments back", SCHEMA, _echo),
    ToolSpec("boom", "Always miss", SCHEMA, _boom),
    ToolSpec("bad", "Always refuse", SCHEMA, _bad),
    ToolSpec("flag", "Always raise the error flag", SCHEMA, _flag),
    ToolSpec("paged", "Report the page size it was given", PAGED_SCHEMA, _paged),
]


def registries() -> dict[str, ServiceRegistry]:
    return {"probe": ServiceRegistry("probe", SPECS, ERRORS)}
