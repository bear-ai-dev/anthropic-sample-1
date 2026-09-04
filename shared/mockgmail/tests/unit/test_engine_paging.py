import json
from typing import Any

from mockgmail.engine import Engine
from mockgmail.gmail.errors import ERRORS
from mockgmail.journal import Journal
from mockgmail.registry import ServiceRegistry
from mockgmail.scenario import validate_scenario
from mockgmail.tool_result import ToolResult, json_result
from mockgmail.tool_spec import ToolSpec
from mockgmail.world import World

PAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "default": 50},
        "maxResults": {"type": "integer", "default": 25},
        "perPage": {"type": "integer", "default": 30},
        "id": {"type": "string"},
    },
}


def _sizes(world: World, arguments: dict[str, Any]) -> ToolResult:
    return json_result(arguments)


def _engine(scenario: dict[str, Any]) -> Engine:
    spec = ToolSpec("wide", "Report every page size it was given", PAGE_SCHEMA, _sizes)
    return Engine(
        validate_scenario(scenario),
        7,
        Journal(None),
        {"probe": ServiceRegistry("probe", [spec], ERRORS)},
    )


def _call(engine: Engine, arguments: dict[str, Any]) -> Any:
    return json.loads(engine.call("probe", "wide", arguments, "cli").content[0]["text"])


def test_every_page_argument_a_tool_declares_arrives_with_its_schema_default(
    scenario: dict[str, Any],
) -> None:
    assert _call(_engine(scenario), {}) == {"limit": 50, "maxResults": 25, "perPage": 30}


def test_a_page_cap_shrinks_every_page_argument_the_tool_declares(
    scenario: dict[str, Any],
) -> None:
    scenario["faults"] = {"rules": [{"service": "probe", "tool": "wide", "max_page_size": 2}]}
    engine = _engine(scenario)
    assert _call(engine, {}) == {"limit": 2, "maxResults": 2, "perPage": 2}
    assert _call(engine, {"limit": 40, "maxResults": 1, "perPage": "9"}) == {
        "limit": 2,
        "maxResults": 1,
        "perPage": 2,
    }


def test_a_tool_that_declares_no_page_argument_is_left_alone(scenario: dict[str, Any]) -> None:
    scenario["faults"] = {"rules": [{"service": "probe", "tool": "*", "max_page_size": 2}]}
    schema: dict[str, Any] = {"type": "object", "properties": {"id": {"type": "string"}}}
    spec = ToolSpec("plain", "Echo the arguments back", schema, _sizes)
    engine = Engine(
        validate_scenario(scenario),
        7,
        Journal(None),
        {"probe": ServiceRegistry("probe", [spec], ERRORS)},
    )
    text = engine.call("probe", "plain", {"id": "x"}, "cli").content[0]["text"]
    assert json.loads(text) == {"id": "x"}
