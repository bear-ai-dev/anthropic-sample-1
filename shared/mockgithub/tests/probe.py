from typing import Any

from mockgithub.github.errors import ERRORS
from mockgithub.registry import ServiceRegistry
from mockgithub.tool_errors import InvalidArguments, NotFound
from mockgithub.tool_result import ToolResult, json_result
from mockgithub.tool_spec import ToolSpec
from mockgithub.world import World

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"limit": {"type": "integer"}, "id": {"type": "string"}},
}


def _echo(world: World, arguments: dict[str, Any]) -> ToolResult:
    return json_result(dict(arguments, viewer=world.github.viewer.login), page={"limit": 1})


def _paged(world: World, arguments: dict[str, Any]) -> ToolResult:
    return json_result({"perPage": arguments["perPage"]})


def _boom(world: World, arguments: dict[str, Any]) -> ToolResult:
    raise NotFound("issue", "ExampleCo/membership-ledger/issues/999")


def _bad(world: World, arguments: dict[str, Any]) -> ToolResult:
    raise InvalidArguments("Invalid cursor")


PAGED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"perPage": {"type": "integer", "default": 30}},
}

SPECS = [
    ToolSpec("echo", "Echo the arguments back", SCHEMA, _echo),
    ToolSpec("paged", "Report the page size it was given", PAGED_SCHEMA, _paged),
    ToolSpec("boom", "Always miss", SCHEMA, _boom),
    ToolSpec("bad", "Always refuse", SCHEMA, _bad),
]


def registries() -> dict[str, ServiceRegistry]:
    return {"probe": ServiceRegistry("probe", SPECS, ERRORS)}
