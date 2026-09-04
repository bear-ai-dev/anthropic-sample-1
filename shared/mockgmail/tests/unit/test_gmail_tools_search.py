from typing import Any

from mockgmail.engine import Engine
from mockgmail.gmail.format import search_result
from mockgmail.gmail.models import Message
from mockgmail.gmail.state import GmailState
from mockgmail.journal import Journal
from mockgmail.scenario import validate_scenario
from mockgmail.tests.require import require


def _engine(scenario: dict[str, Any]) -> Engine:
    return Engine(validate_scenario(scenario), 7, Journal(None))


def _text(engine: Engine, tool: str, arguments: dict[str, Any]) -> str:
    result = engine.call("gmail", tool, arguments, "cli")
    assert not result.is_error
    assert len(result.content) == 1
    return str(result.content[0]["text"])


def _message(state: GmailState, key: str) -> Message:
    return require(next((item for item in state.messages if item.key == key), None))


def test_the_registry_lists_the_four_read_tools(scenario: dict[str, Any]) -> None:
    tools = _engine(scenario).tools("gmail")
    assert [tool["name"] for tool in tools] == [
        "download_attachment",
        "list_email_labels",
        "read_email",
        "search_emails",
    ]
    by_name = {tool["name"]: tool for tool in tools}
    assert by_name["search_emails"]["inputSchema"]["required"] == ["query"]
    assert by_name["search_emails"]["inputSchema"]["properties"]["maxResults"]["default"] == 10
    assert by_name["read_email"]["inputSchema"]["required"] == ["messageId"]
    assert by_name["download_attachment"]["inputSchema"]["required"] == [
        "messageId",
        "attachmentId",
    ]
    assert set(by_name["download_attachment"]["inputSchema"]["properties"]) == {
        "messageId",
        "attachmentId",
        "savePath",
        "filename",
    }
    assert by_name["list_email_labels"]["inputSchema"]["properties"] == {}
    assert all(tool["description"] for tool in tools)


def test_search_emails_lists_matches_newest_first_up_to_max_results(
    scenario: dict[str, Any],
) -> None:
    engine = _engine(scenario)
    state = engine.world.gmail
    text = _text(engine, "search_emails", {"query": "from:okonjo"})
    assert text == search_result([_message(state, "okonjo-3"), _message(state, "okonjo-1")])
    capped = _text(engine, "search_emails", {"query": "label:billing", "maxResults": 2})
    assert capped.count("ID: ") == 2
    assert capped.startswith(f"ID: {_message(state, 'bergstrom-2').id}\n")
    assert (
        _text(engine, "search_emails", {"query": "in:anywhere", "maxResults": "3"}).count("ID: ")
        == 3
    )


def test_search_emails_defaults_to_ten_results(scenario: dict[str, Any]) -> None:
    assert _text(_engine(scenario), "search_emails", {"query": ""}).count("ID: ") == 10


def test_search_emails_without_matches_says_so(scenario: dict[str, Any]) -> None:
    assert _text(_engine(scenario), "search_emails", {"query": "from:nobody"}) == (
        "No emails found matching the query"
    )


def test_search_emails_requires_a_query(scenario: dict[str, Any]) -> None:
    assert _text(_engine(scenario), "search_emails", {}) == (
        "Error: missing required parameter: query"
    )


def test_a_page_cap_fault_shrinks_the_search_result(scenario: dict[str, Any]) -> None:
    scenario["faults"] = {
        "rules": [{"service": "gmail", "tool": "search_emails", "max_page_size": 3}]
    }
    engine = _engine(scenario)
    assert _text(engine, "search_emails", {"query": "", "maxResults": 20}).count("ID: ") == 3
    assert _text(engine, "search_emails", {"query": "", "maxResults": 1}).count("ID: ") == 1


def test_the_search_journal_records_the_page(scenario: dict[str, Any]) -> None:
    journal = Journal(None)
    engine = Engine(validate_scenario(scenario), 7, journal)
    engine.call("gmail", "search_emails", {"query": "label:billing", "maxResults": 5}, "mcp")
    assert journal.records()[0]["page"] == {"maxResults": 5, "matched": 12, "returned": 5}
