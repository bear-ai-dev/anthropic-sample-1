import json
from typing import Any

import pytest

from mocklinear.engine import Engine
from mocklinear.journal import Journal
from mocklinear.scenario import validate_scenario
from mocklinear.tests.integration.conftest import ADMIN_TOKEN, Daemon

HEADERS = {"x-mocklinear-admin-token": ADMIN_TOKEN}


def _call(daemon: Daemon, tool: str, arguments: dict[str, Any]) -> Any:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    return daemon.post("/mcp/linear", message)["result"]


@pytest.fixture
def throttled(scenario: dict[str, Any]) -> dict[str, Any]:
    scenario["faults"] = {
        "rules": [{"service": "linear", "tool": "list_issues", "throttle_every": 1}]
    }
    return scenario


def test_a_throttled_tool_answers_with_the_linear_rate_limit_text(
    throttled: dict[str, Any], daemon: Daemon
) -> None:
    daemon.post("/_admin/reseed", {"scenario": throttled, "seed": 7}, HEADERS)
    result = _call(daemon, "list_issues", {})
    assert result["isError"] is True
    assert result["content"][0]["text"] == (
        "Linear API rate limit exceeded. Please retry after a short delay."
    )
    assert daemon.get("/_admin/calls", HEADERS)["fault_counters"] == {"linear:list_issues": 1}


def test_the_verifier_can_switch_the_faults_off(throttled: dict[str, Any], daemon: Daemon) -> None:
    daemon.post("/_admin/reseed", {"scenario": throttled, "seed": 7}, HEADERS)
    daemon.post("/_admin/faults", {"enabled": False}, HEADERS)
    result = _call(daemon, "list_issues", {})
    assert "isError" not in result


def test_a_capped_page_still_walks_to_the_end_of_the_list(
    scenario: dict[str, Any], daemon: Daemon
) -> None:
    scenario["faults"] = {
        "rules": [{"service": "linear", "tool": "list_issues", "max_page_size": 5}]
    }
    daemon.post("/_admin/reseed", {"scenario": scenario, "seed": 7}, HEADERS)
    seen: list[str] = []
    cursor: str | None = None
    while True:
        arguments: dict[str, Any] = {"limit": 50}
        if cursor is not None:
            arguments["after"] = cursor
        payload = json.loads(_call(daemon, "list_issues", arguments)["content"][0]["text"])
        assert len(payload["issues"]) <= 5
        seen.extend(issue["identifier"] for issue in payload["issues"])
        if not payload["pageInfo"]["hasNextPage"]:
            break
        cursor = payload["pageInfo"]["endCursor"]
    assert len(seen) == 12
    assert len(set(seen)) == 12


def test_two_engines_with_the_same_seed_answer_identically(scenario: dict[str, Any]) -> None:
    def drive(seed: int) -> list[str]:
        engine = Engine(validate_scenario(scenario), seed, Journal(None))
        calls = [
            ("list_issues", {"assignee": "me"}),
            ("get_issue", {"id": "WEB-611"}),
            ("list_teams", {}),
            ("get_user", {"id": "me"}),
        ]
        return [engine.call("linear", tool, args, "cli").content[0]["text"] for tool, args in calls]

    assert drive(7) == drive(7)
    assert drive(7) != drive(41)
