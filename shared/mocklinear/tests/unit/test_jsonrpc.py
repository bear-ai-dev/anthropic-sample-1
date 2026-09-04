from typing import Any

from mocklinear import __version__
from mocklinear.engine import Engine
from mocklinear.journal import Journal
from mocklinear.jsonrpc import handle
from mocklinear.scenario import validate_scenario
from mocklinear.tests.probe import registries
from mocklinear.tests.require import require


def _engine(scenario: dict[str, Any]) -> Engine:
    return Engine(validate_scenario(scenario), 7, Journal(None), registries())


def _call(scenario: dict[str, Any], message: dict[str, Any]) -> Any:
    return handle(message, "probe", _engine(scenario), "http")


def test_initialize_echoes_a_protocol_version_the_client_asked_for(
    scenario: dict[str, Any],
) -> None:
    response = _call(
        scenario,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
    )
    assert response == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
            "serverInfo": {"name": "probe", "version": __version__},
        },
    }


def test_initialize_falls_back_to_the_newest_version_it_speaks(scenario: dict[str, Any]) -> None:
    response = _call(
        scenario,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"},
        },
    )
    assert response["result"]["protocolVersion"] == "2025-06-18"
    bare = _call(scenario, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert bare["result"]["protocolVersion"] == "2025-06-18"


def test_a_notification_is_answered_with_nothing(scenario: dict[str, Any]) -> None:
    assert _call(scenario, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping_prompts_and_resources_answer_empty(scenario: dict[str, Any]) -> None:
    assert _call(scenario, {"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
    assert _call(scenario, {"jsonrpc": "2.0", "id": 3, "method": "prompts/list"})["result"] == {
        "prompts": []
    }
    assert _call(scenario, {"jsonrpc": "2.0", "id": 4, "method": "resources/list"})["result"] == {
        "resources": []
    }


def test_the_tool_list_carries_every_descriptor(scenario: dict[str, Any]) -> None:
    result = _call(scenario, {"jsonrpc": "2.0", "id": 5, "method": "tools/list"})["result"]
    assert [tool["name"] for tool in result["tools"]] == ["bad", "boom", "echo", "paged"]


def test_a_successful_call_omits_the_error_flag(scenario: dict[str, Any]) -> None:
    result = _call(
        scenario,
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"id": "WEB-611"}},
        },
    )["result"]
    assert "isError" not in result
    assert result["content"][0]["type"] == "text"


def test_a_failing_call_sets_the_error_flag_in_the_result(scenario: dict[str, Any]) -> None:
    result = _call(
        scenario,
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "boom"}},
    )["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"].startswith("Entity not found")


def test_an_unknown_tool_or_service_is_an_invalid_parameter(scenario: dict[str, Any]) -> None:
    response = _call(
        scenario,
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "nope"}},
    )
    assert response["error"] == {"code": -32602, "message": "Unknown tool: nope"}
    unknown_service = require(
        handle(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/list"},
            "linear",
            _engine(scenario),
            "http",
        )
    )
    assert unknown_service["error"] == {"code": -32602, "message": "Unknown service: linear"}


def test_an_unknown_method_is_reported_as_not_found(scenario: dict[str, Any]) -> None:
    response = _call(scenario, {"jsonrpc": "2.0", "id": 10, "method": "tools/write"})
    assert response["error"] == {"code": -32601, "message": "Method not found: tools/write"}


def test_a_message_without_a_method_is_an_invalid_request(scenario: dict[str, Any]) -> None:
    assert _call(scenario, {"jsonrpc": "2.0", "id": 11})["error"]["code"] == -32600
    assert _call(scenario, {"jsonrpc": "2.0", "id": 12, "method": 7})["error"]["code"] == -32600


def test_parameters_that_are_not_an_object_are_invalid(scenario: dict[str, Any]) -> None:
    response = _call(scenario, {"jsonrpc": "2.0", "id": 13, "method": "tools/list", "params": []})
    assert response["error"] == {"code": -32602, "message": "Invalid params"}
    no_name = _call(scenario, {"jsonrpc": "2.0", "id": 14, "method": "tools/call", "params": {}})
    assert no_name["error"] == {"code": -32602, "message": "Invalid params: missing tool name"}
    bad_args = _call(
        scenario,
        {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": 3},
        },
    )
    assert bad_args["error"] == {"code": -32602, "message": "Invalid params: arguments"}


def test_initialize_advertises_every_capability_the_daemon_serves(
    scenario: dict[str, Any],
) -> None:
    response = _call(scenario, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response["result"]["capabilities"] == {"tools": {}, "prompts": {}, "resources": {}}
