from datetime import datetime
from typing import Any

from mocklinear.linear.filters import matching_issues
from mocklinear.linear.state import LinearState


def _found(workspace: LinearState, now: datetime, **arguments: Any) -> list[str]:
    return [issue.identifier for issue in matching_issues(workspace, arguments, now)]


def test_no_filter_returns_every_issue_newest_update_first(
    state: LinearState, now: datetime
) -> None:
    found = _found(state, now)
    assert len(found) == 12
    assert found[:3] == ["WEB-619", "WEB-611", "WEB-614"]
    assert found[-1] == "WEB-613"


def test_ordering_by_creation_is_offered_as_well(state: LinearState, now: datetime) -> None:
    assert _found(state, now, orderBy="createdAt")[0] == "WEB-619"
    assert _found(state, now, orderBy="createdAt")[-1] == "WEB-613"


def test_the_viewer_is_reachable_as_me(state: LinearState, now: datetime) -> None:
    mine = _found(state, now, assignee="me")
    assert mine == ["WEB-619", "WEB-611", "WEB-615", "WEB-612"]
    assert _found(state, now, assignee="dana") == mine
    assert _found(state, now, assignee="dana@ExampleCo.example") == mine
    assert _found(state, now, assignee="Dana Whitfield") == mine


def test_an_assignee_nobody_answers_to_matches_nothing(state: LinearState, now: datetime) -> None:
    assert _found(state, now, assignee="ghost@ExampleCo.example") == []


def test_a_team_filter_takes_a_key_a_name_or_an_id(state: LinearState, now: datetime) -> None:
    ios = _found(state, now, team="IOS")
    assert ios == ["IOS-1471", "IOS-1472", "IOS-1473"]
    assert _found(state, now, team="iOS") == ios


def test_a_state_filter_takes_a_status_name_or_a_status_type(
    state: LinearState, now: datetime
) -> None:
    assert _found(state, now, state="In Progress") == ["WEB-611", "WEB-614", "IOS-1471"]
    assert _found(state, now, state="started") == ["WEB-611", "WEB-614", "WEB-616", "IOS-1471"]
    assert _found(state, now, state="completed") == ["IOS-1473", "WEB-613"]
    assert _found(state, now, state="Shipped") == []


def test_a_label_filter_takes_a_label_key_or_name(state: LinearState, now: datetime) -> None:
    assert _found(state, now, label="escalation") == ["WEB-611", "IOS-1471"]
    assert _found(state, now, label="Escalation") == ["WEB-611", "IOS-1471"]
    assert _found(state, now, label="Regression") == ["WEB-611", "WEB-616"]


def test_a_project_a_cycle_and_a_parent_narrow_the_list(state: LinearState, now: datetime) -> None:
    assert _found(state, now, project="Billing cleanup") == ["WEB-613"]
    assert _found(state, now, project="Mobile scanning") == ["IOS-1471", "IOS-1472", "IOS-1473"]
    assert _found(state, now, cycle="43") == [
        "WEB-611",
        "WEB-614",
        "WEB-616",
        "WEB-615",
        "WEB-612",
    ]
    assert _found(state, now, cycle="Sprint 12") == ["IOS-1471", "IOS-1472"]
    assert _found(state, now, parent="WEB-614") == ["WEB-615"]
    assert _found(state, now, parent="WEB-611") == []


def test_a_timestamp_filter_accepts_an_instant_or_a_duration(
    state: LinearState, now: datetime
) -> None:
    assert _found(state, now, updatedAt="-P2D") == ["WEB-619", "WEB-611", "WEB-614"]
    assert _found(state, now, updatedAt="2026-03-02T00:00:00Z") == [
        "WEB-619",
        "WEB-611",
        "WEB-614",
        "WEB-616",
    ]
    assert _found(state, now, createdAt="2026-03-01") == ["WEB-619"]
    assert _found(state, now, createdAt="-P2D", updatedAt="-P2D") == ["WEB-619"]


def test_a_query_is_a_case_insensitive_substring_of_title_body_or_identifier(
    state: LinearState, now: datetime
) -> None:
    assert _found(state, now, query="scanner") == ["WEB-619", "WEB-611", "WEB-614"]
    assert _found(state, now, query="WEB-613") == ["WEB-613"]
    assert _found(state, now, query="wallet") == ["IOS-1472"]
    assert _found(state, now, query="nothing here") == []


def test_filters_combine(state: LinearState, now: datetime) -> None:
    assert _found(state, now, assignee="me", state="started", team="WEB") == ["WEB-611"]


def test_a_filter_never_answers_to_a_fixture_key(state: LinearState, now: datetime) -> None:
    assert _found(state, now, assignee="u-dana") == []
    assert _found(state, now, state="web-progress") == []
    assert _found(state, now, label="web-regression") == []
    assert _found(state, now, project="door-ops") == []
    assert _found(state, now, cycle="WEB:43") == []
    assert _found(state, now, team="QA") == []
    assert _found(state, now, parent="WEB-999") == []
