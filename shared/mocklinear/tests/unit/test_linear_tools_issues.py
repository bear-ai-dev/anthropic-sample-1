import json
from typing import Any

import pytest

from mocklinear.engine import Engine
from mocklinear.journal import Journal
from mocklinear.scenario import validate_scenario


@pytest.fixture
def engine(scenario: dict[str, Any]) -> Engine:
    return Engine(validate_scenario(scenario), 7, Journal(None))


def call(engine: Engine, tool: str, **arguments: Any) -> Any:
    result = engine.call("linear", tool, arguments, "cli")
    assert not result.is_error, result.content[0]["text"]
    return json.loads(result.content[0]["text"])


def error_text(engine: Engine, tool: str, **arguments: Any) -> str:
    result = engine.call("linear", tool, arguments, "cli")
    assert result.is_error
    return str(result.content[0]["text"])


def test_the_workspace_publishes_the_twenty_read_tools(engine: Engine) -> None:
    assert sorted(tool["name"] for tool in engine.tools("linear")) == [
        "get_attachment",
        "get_document",
        "get_issue",
        "get_issue_status",
        "get_milestone",
        "get_project",
        "get_team",
        "get_user",
        "list_comments",
        "list_cycles",
        "list_documents",
        "list_issue_labels",
        "list_issue_statuses",
        "list_issues",
        "list_milestones",
        "list_project_labels",
        "list_projects",
        "list_teams",
        "list_users",
        "search_documentation",
    ]


def test_listing_issues_returns_an_envelope_with_page_information(engine: Engine) -> None:
    payload = call(engine, "list_issues")
    assert [issue["identifier"] for issue in payload["issues"]][:2] == ["WEB-619", "WEB-611"]
    assert payload["pageInfo"] == {
        "hasNextPage": False,
        "hasPreviousPage": False,
        "startCursor": payload["issues"][0]["id"],
        "endCursor": payload["issues"][-1]["id"],
    }


def test_listing_issues_pages_forwards_and_backwards_by_cursor(engine: Engine) -> None:
    first = call(engine, "list_issues", limit=5)
    assert len(first["issues"]) == 5
    assert first["pageInfo"]["hasNextPage"]
    second = call(engine, "list_issues", limit=5, after=first["pageInfo"]["endCursor"])
    assert [issue["identifier"] for issue in second["issues"]][0] == "WEB-615"
    assert second["pageInfo"]["hasPreviousPage"]
    back = call(engine, "list_issues", limit=5, before=second["pageInfo"]["startCursor"])
    assert [issue["identifier"] for issue in back["issues"]] == [
        issue["identifier"] for issue in first["issues"]
    ]


def test_an_unknown_cursor_is_reported_as_bad_arguments(engine: Engine) -> None:
    assert error_text(engine, "list_issues", after="not-a-cursor") == (
        "Invalid arguments: Invalid cursor"
    )


def test_listing_issues_honours_every_documented_filter(engine: Engine) -> None:
    assert [issue["identifier"] for issue in call(engine, "list_issues", assignee="me")["issues"]][
        0
    ] == "WEB-619"
    assert [issue["identifier"] for issue in call(engine, "list_issues", team="IOS")["issues"]] == [
        "IOS-1471",
        "IOS-1472",
        "IOS-1473",
    ]
    assert [
        issue["identifier"]
        for issue in call(engine, "list_issues", state="started", label="escalation")["issues"]
    ] == ["WEB-611", "IOS-1471"]
    assert [
        issue["identifier"] for issue in call(engine, "list_issues", query="wallet")["issues"]
    ] == ["IOS-1472"]
    assert [
        issue["identifier"] for issue in call(engine, "list_issues", parent="WEB-614")["issues"]
    ] == ["WEB-615"]
    assert [
        issue["identifier"]
        for issue in call(engine, "list_issues", project="Billing cleanup", cycle="41")["issues"]
    ] == ["WEB-613"]
    assert [
        issue["identifier"] for issue in call(engine, "list_issues", updatedAt="-P2D")["issues"]
    ] == ["WEB-619", "WEB-611", "WEB-614"]
    assert [
        issue["identifier"]
        for issue in call(engine, "list_issues", orderBy="createdAt", createdAt="2026-03-01")[
            "issues"
        ]
    ] == ["WEB-619"]


def test_an_order_the_server_does_not_know_is_refused(engine: Engine) -> None:
    assert error_text(engine, "list_issues", orderBy="priority") == (
        "Invalid arguments: parameter orderBy must be one of createdAt, updatedAt"
    )


def test_a_page_cap_forces_the_client_to_paginate(scenario: dict[str, Any]) -> None:
    scenario["faults"] = {
        "rules": [{"service": "linear", "tool": "list_issues", "max_page_size": 3}]
    }
    engine = Engine(validate_scenario(scenario), 7, Journal(None))
    page = call(engine, "list_issues", limit=50)
    assert len(page["issues"]) == 3
    assert page["pageInfo"]["hasNextPage"]


def test_getting_one_issue_returns_the_entity_with_its_attachments(engine: Engine) -> None:
    payload = call(engine, "get_issue", id="WEB-611")
    assert payload["identifier"] == "WEB-611"
    assert payload["branchName"] == "dana/web-611-reentry-scan"
    assert payload["commentCount"] == 3
    assert [item["title"] for item in payload["attachments"]] == ["door-scan.mov"]
    assert call(engine, "get_issue", id=payload["id"])["identifier"] == "WEB-611"


def test_an_issue_nobody_filed_reads_the_same_however_it_was_asked_for(engine: Engine) -> None:
    missing = "Entity not found: Issue - Could not find referenced Issue."
    assert error_text(engine, "get_issue", id="WEB-999") == missing
    assert error_text(engine, "get_issue", id="6f0c4f2a-0000-0000-0000-000000000000") == missing


def test_a_required_argument_is_named_when_it_is_missing(engine: Engine) -> None:
    assert error_text(engine, "get_issue") == "Invalid arguments: missing required parameter: id"


def test_listing_comments_keeps_the_thread(engine: Engine) -> None:
    payload = call(engine, "list_comments", issueId="WEB-611")
    bodies = [comment["body"] for comment in payload["comments"]]
    assert bodies[0].startswith("Second scan says")
    assert payload["comments"][2]["parentId"] == payload["comments"][1]["id"]
    assert payload["pageInfo"]["hasNextPage"] is False
    assert call(engine, "list_comments", issueId="WEB-611", limit=2)["pageInfo"]["hasNextPage"]
    assert call(engine, "list_comments", issueId="WEB-614")["comments"] == []


def test_comments_on_an_issue_that_is_not_there_are_a_missing_issue(engine: Engine) -> None:
    assert error_text(engine, "list_comments", issueId="WEB-999") == (
        "Entity not found: Issue - Could not find referenced Issue."
    )


def test_an_attachment_is_reachable_by_its_own_identifier(engine: Engine) -> None:
    attachment = call(engine, "get_issue", id="WEB-611")["attachments"][0]
    payload = call(engine, "get_attachment", id=attachment["id"])
    assert payload["title"] == "door-scan.mov"
    assert payload["issue"]["identifier"] == "WEB-611"
    assert error_text(engine, "get_attachment", id="nope") == (
        "Entity not found: Attachment - Could not find referenced Attachment."
    )


def test_an_issue_names_its_project_milestone(engine: Engine) -> None:
    payload = call(engine, "get_issue", id="WEB-611")
    assert payload["projectMilestone"]["name"] == "Scanner reliability"
    assert call(engine, "get_issue", id="WEB-617")["projectMilestone"] is None


def test_the_timestamp_filters_document_the_durations_they_accept(engine: Engine) -> None:
    schema = next(tool for tool in engine.tools("linear") if tool["name"] == "list_issues")
    wanted = "ISO 8601 timestamp, or a relative ISO 8601 duration such as -P1W or -P1M"
    for field in ("createdAt", "updatedAt"):
        assert wanted in schema["inputSchema"]["properties"][field]["description"]
