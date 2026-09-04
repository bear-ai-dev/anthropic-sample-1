import json
from typing import Any

import pytest

from mockgmail.engine import Engine, UnknownService, UnknownTool
from mockgmail.journal import Journal
from mockgmail.scenario import validate_scenario
from mockgmail.tests.probe import registries


def _engine(scenario: dict[str, Any], journal: Journal | None = None) -> Engine:
    return Engine(validate_scenario(scenario), 7, journal or Journal(None), registries())


def test_a_call_runs_the_handler_against_the_world(scenario: dict[str, Any]) -> None:
    engine = _engine(scenario)
    result = engine.call("probe", "echo", {"limit": "3"}, "cli")
    assert json.loads(result.content[0]["text"]) == {"limit": 3, "viewer": "inbox@desk.internal"}
    assert not result.is_error


def test_every_call_is_journalled_with_its_outcome(scenario: dict[str, Any]) -> None:
    journal = Journal(None)
    engine = _engine(scenario, journal)
    engine.call("probe", "echo", {"limit": 3}, "cli")
    engine.call("probe", "boom", {}, "mcp")
    engine.call("probe", "bad", {}, "http")
    records = journal.records()
    assert [record["outcome"] for record in records] == ["ok", "error", "error"]
    assert [record["error_kind"] for record in records] == [
        None,
        "not_found",
        "invalid_arguments",
    ]
    assert [record["via"] for record in records] == ["cli", "mcp", "http"]
    assert records[0]["tool"] == "echo"
    assert records[0]["service"] == "probe"
    assert records[0]["args"] == {"limit": 3}
    assert records[0]["page"] == {"limit": 1}
    assert records[0]["result_chars"] > 0
    assert records[0]["duration_ms"] >= 0


def test_a_missing_entity_is_rendered_by_the_service_error_vocabulary(
    scenario: dict[str, Any],
) -> None:
    result = _engine(scenario).call("probe", "boom", {}, "cli")
    assert not result.is_error
    assert result.content[0]["text"] == "Error: Requested entity was not found."


def test_bad_arguments_are_rendered_by_the_service_error_vocabulary(
    scenario: dict[str, Any],
) -> None:
    engine = _engine(scenario)
    assert engine.call("probe", "bad", {}, "cli").content[0]["text"] == ("Error: Invalid cursor")
    assert engine.call("probe", "echo", {"limit": "many"}, "cli").content[0]["text"] == (
        "Error: parameter limit must be an integer"
    )


def test_a_throttle_rule_answers_with_the_rate_limit_text(scenario: dict[str, Any]) -> None:
    scenario["faults"] = {"rules": [{"service": "probe", "tool": "echo", "throttle_every": 1}]}
    journal = Journal(None)
    result = _engine(scenario, journal).call("probe", "echo", {}, "cli")
    assert not result.is_error
    assert result.content[0]["text"] == "Error: Rate Limit Exceeded"
    assert journal.records()[0]["outcome"] == "throttled"


def test_a_server_error_rule_answers_with_the_internal_error_text(
    scenario: dict[str, Any],
) -> None:
    scenario["faults"] = {"rules": [{"service": "probe", "server_error_every": 1}]}
    journal = Journal(None)
    result = _engine(scenario, journal).call("probe", "echo", {}, "cli")
    assert result.content[0]["text"] == "Error: Backend Error"
    assert journal.records()[0]["outcome"] == "server_error"


def test_a_latency_rule_is_slept_before_the_answer(scenario: dict[str, Any]) -> None:
    scenario["faults"] = {"rules": [{"service": "probe", "latency_seconds": 0.05}]}
    journal = Journal(None)
    _engine(scenario, journal).call("probe", "echo", {}, "cli")
    assert journal.records()[0]["duration_ms"] >= 50


def test_an_unknown_service_or_tool_is_raised_to_the_protocol_layer(
    scenario: dict[str, Any],
) -> None:
    engine = _engine(scenario)
    with pytest.raises(UnknownService, match="gmail"):
        engine.call("gmail", "echo", {}, "cli")
    with pytest.raises(UnknownTool, match="nope"):
        engine.call("probe", "nope", {}, "cli")
    with pytest.raises(UnknownService, match="gmail"):
        engine.tools("gmail")


def test_the_tool_list_is_the_registry_descriptors(scenario: dict[str, Any]) -> None:
    engine = _engine(scenario)
    assert engine.services() == ["probe"]
    assert [tool["name"] for tool in engine.tools("probe")] == [
        "bad",
        "boom",
        "echo",
        "flag",
        "paged",
    ]
    assert engine.tools("probe")[0]["inputSchema"]["type"] == "object"


def test_reseeding_replaces_the_world_the_faults_and_the_journal(
    scenario: dict[str, Any],
) -> None:
    journal = Journal(None)
    engine = _engine(scenario, journal)
    engine.call("probe", "echo", {}, "cli")
    before = engine.world.gmail.messages[0].id
    engine.reseed(validate_scenario(scenario), 41)
    assert engine.world.seed == 41
    assert engine.world.gmail.messages[0].id != before
    assert journal.records() == []
    assert engine.injector.stats() == {}


def test_reseeding_without_a_seed_keeps_the_current_one(scenario: dict[str, Any]) -> None:
    engine = _engine(scenario)
    engine.reseed(validate_scenario(scenario), None)
    assert engine.world.seed == 7


def test_the_default_engine_serves_the_gmail_registry(scenario: dict[str, Any]) -> None:
    engine = Engine(validate_scenario(scenario), 7, Journal(None))
    assert engine.services() == ["gmail"]


def test_a_page_cap_shrinks_the_page_size_the_handler_sees(scenario: dict[str, Any]) -> None:
    scenario["faults"] = {"rules": [{"service": "probe", "tool": "paged", "max_page_size": 2}]}
    engine = _engine(scenario)
    assert json.loads(engine.call("probe", "paged", {}, "cli").content[0]["text"]) == {
        "maxResults": 2
    }
    assert json.loads(
        engine.call("probe", "paged", {"maxResults": 1}, "cli").content[0]["text"]
    ) == {"maxResults": 1}
    assert json.loads(
        engine.call("probe", "paged", {"maxResults": "5"}, "cli").content[0]["text"]
    ) == {"maxResults": 2}


def test_a_tool_that_declares_a_page_size_always_receives_one(scenario: dict[str, Any]) -> None:
    engine = _engine(scenario)
    assert json.loads(engine.call("probe", "paged", {}, "cli").content[0]["text"]) == {
        "maxResults": 10
    }
    assert json.loads(engine.call("probe", "echo", {}, "cli").content[0]["text"]) == {
        "limit": 50,
        "viewer": "inbox@desk.internal",
    }
