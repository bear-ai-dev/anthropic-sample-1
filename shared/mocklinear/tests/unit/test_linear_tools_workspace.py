from typing import Any

import pytest

from mocklinear.engine import Engine
from mocklinear.journal import Journal
from mocklinear.scenario import validate_scenario
from mocklinear.tests.unit.test_linear_tools_issues import call, error_text


@pytest.fixture
def engine(scenario: dict[str, Any]) -> Engine:
    return Engine(validate_scenario(scenario), 7, Journal(None))


def test_the_workflow_states_of_a_team_come_back_in_board_order(engine: Engine) -> None:
    payload = call(engine, "list_issue_statuses", team="WEB")
    assert [status["name"] for status in payload["statuses"]] == [
        "Backlog",
        "Todo",
        "In Progress",
        "In Review",
        "Done",
        "Canceled",
    ]
    assert payload["statuses"][2]["team"]["key"] == "WEB"
    assert len(call(engine, "list_issue_statuses")["statuses"]) == 10


def test_one_workflow_state_is_reachable_by_name_within_a_team(engine: Engine) -> None:
    payload = call(engine, "get_issue_status", id="In Progress", team="IOS")
    assert payload["team"]["key"] == "IOS"
    assert payload["type"] == "started"
    assert call(engine, "get_issue_status", id=payload["id"])["name"] == "In Progress"
    assert error_text(engine, "get_issue_status", id="Shipped") == (
        "Entity not found: WorkflowState - Could not find referenced WorkflowState."
    )


def test_issue_labels_are_workspace_wide_plus_the_teams_own(engine: Engine) -> None:
    assert [label["name"] for label in call(engine, "list_issue_labels")["labels"]] == [
        "Bug",
        "Chore",
        "Escalation",
        "Feature",
        "Regression",
    ]
    assert [label["name"] for label in call(engine, "list_issue_labels", team="IOS")["labels"]] == [
        "Bug",
        "Chore",
        "Escalation",
        "Feature",
    ]


def test_projects_are_listed_by_name_and_filtered_by_team_and_state(engine: Engine) -> None:
    assert [project["name"] for project in call(engine, "list_projects")["projects"]] == [
        "Billing cleanup",
        "Door operations",
        "Mobile scanning",
    ]
    assert [
        project["name"] for project in call(engine, "list_projects", team="IOS")["projects"]
    ] == ["Mobile scanning"]
    assert [
        project["name"] for project in call(engine, "list_projects", state="completed")["projects"]
    ] == ["Billing cleanup"]


def test_one_project_is_reachable_by_key_or_name(engine: Engine) -> None:
    payload = call(engine, "get_project", id="Door operations")
    assert payload["lead"]["displayName"] == "dana"
    assert call(engine, "get_project", id=payload["id"])["id"] == payload["id"]
    assert error_text(engine, "get_project", id="no-such-project") == (
        "Entity not found: Project - Could not find referenced Project."
    )


def test_project_labels_are_the_ones_projects_actually_carry(engine: Engine) -> None:
    assert [label["name"] for label in call(engine, "list_project_labels")["labels"]] == [
        "Bug",
        "Chore",
        "Escalation",
        "Feature",
    ]


def test_milestones_belong_to_their_project(engine: Engine) -> None:
    assert [item["name"] for item in call(engine, "list_milestones")["milestones"]] == [
        "Scanner reliability",
        "Reporting cleanup",
        "iOS 19 readiness",
    ]
    assert [
        item["name"]
        for item in call(engine, "list_milestones", project="Mobile scanning")["milestones"]
    ] == ["iOS 19 readiness"]
    assert call(engine, "get_milestone", id="Scanner reliability")["project"]["name"] == (
        "Door operations"
    )
    assert error_text(engine, "get_milestone", id="m-nope") == (
        "Entity not found: ProjectMilestone - Could not find referenced ProjectMilestone."
    )


def test_cycles_are_selected_against_the_scenario_clock(engine: Engine) -> None:
    assert [cycle["number"] for cycle in call(engine, "list_cycles")["cycles"]] == [
        41,
        42,
        43,
        44,
        12,
    ]
    assert [cycle["number"] for cycle in call(engine, "list_cycles", type="current")["cycles"]] == [
        43
    ]
    assert [
        cycle["number"] for cycle in call(engine, "list_cycles", type="previous")["cycles"]
    ] == [42, 12]
    assert [cycle["number"] for cycle in call(engine, "list_cycles", type="next")["cycles"]] == [44]
    assert [
        cycle["number"] for cycle in call(engine, "list_cycles", team="IOS", type="all")["cycles"]
    ] == [12]


def test_documents_are_listed_newest_first_and_filtered(engine: Engine) -> None:
    payload = call(engine, "list_documents")
    assert [document["title"] for document in payload["documents"]] == [
        "Wallet pass notes",
        "Door night runbook",
        "Re-entry incident review",
    ]
    assert [
        document["title"]
        for document in call(engine, "list_documents", project="Door operations")["documents"]
    ] == ["Door night runbook", "Re-entry incident review"]
    assert [
        document["title"]
        for document in call(engine, "list_documents", query="incident")["documents"]
    ] == ["Re-entry incident review"]
    assert [
        document["title"]
        for document in call(engine, "list_documents", issue="WEB-611")["documents"]
    ] == ["Re-entry incident review"]


def test_one_document_is_reachable_by_slug_or_title(engine: Engine) -> None:
    payload = call(engine, "get_document", id="door-runbook")
    assert payload["title"] == "Door night runbook"
    assert payload["content"].startswith("# Door night runbook")
    assert call(engine, "get_document", id="Door night runbook")["id"] == payload["id"]
    assert error_text(engine, "get_document", id="missing-doc") == (
        "Entity not found: Document - Could not find referenced Document."
    )


def test_teams_are_listed_and_searchable(engine: Engine) -> None:
    assert [team["key"] for team in call(engine, "list_teams")["teams"]] == ["IOS", "WEB"]
    assert [team["key"] for team in call(engine, "list_teams", query="web")["teams"]] == ["WEB"]
    assert call(engine, "get_team", id="WEB")["description"] == "Web checkout and door tooling"
    assert call(engine, "get_team", id="iOS")["key"] == "IOS"
    assert error_text(engine, "get_team", id="QA") == (
        "Entity not found: Team - Could not find referenced Team."
    )


def test_users_are_listed_and_the_viewer_answers_to_me(engine: Engine) -> None:
    assert [user["displayName"] for user in call(engine, "list_users")["users"]] == [
        "dana",
        "irene",
        "milo",
        "sasha",
    ]
    assert [
        user["displayName"] for user in call(engine, "list_users", query="ferrante")["users"]
    ] == ["milo"]
    assert call(engine, "get_user", id="me")["email"] == "dana@ExampleCo.example"
    assert call(engine, "get_user", id="milo@ExampleCo.example")["name"] == "Milo Ferrante"
    assert call(engine, "get_user", id="irene")["active"] is False
    assert error_text(engine, "get_user", id="nobody") == (
        "Entity not found: User - Could not find referenced User."
    )


def test_the_documentation_search_reads_like_an_empty_result(engine: Engine) -> None:
    result = engine.call("linear", "search_documentation", {"query": "cycles"}, "cli")
    assert not result.is_error
    text = result.content[0]["text"]
    assert text == (
        "No documentation matched that query. "
        "Linear's documentation lives at https://linear.app/docs."
    )
    assert "workspace" not in text


def test_a_team_carries_the_people_on_it(engine: Engine) -> None:
    payload = call(engine, "get_team", id="IOS")
    assert [member["displayName"] for member in payload["members"]] == ["sasha", "irene"]
    assert payload["members"][0]["email"] == "sasha@ExampleCo.example"
