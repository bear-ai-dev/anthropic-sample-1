from mocklinear.ids import uuid_for
from mocklinear.linear.state import LinearState
from mocklinear.tests.require import require

SEED = 7


def test_the_viewer_is_the_user_named_in_the_scenario(state: LinearState) -> None:
    assert state.viewer.key == "u-dana"
    assert state.viewer.email == "dana@ExampleCo.example"
    assert state.user("me") is state.viewer


def test_a_user_is_found_by_key_id_email_name_or_display_name(state: LinearState) -> None:
    milo = require(state.user("milo"))
    assert milo is not None
    assert state.user(milo.id) is milo
    assert state.user("MILO@ExampleCo.example") is milo
    assert state.user("Milo Ferrante") is milo
    assert state.user("nobody") is None


def test_a_team_is_found_by_key_name_or_id(state: LinearState) -> None:
    web = require(state.team("WEB"))
    assert state.team("web") is web
    assert state.team("Web") is web
    assert state.team(web.id) is web
    assert state.team("QA") is None


def test_states_belong_to_their_team_and_carry_their_position(state: LinearState) -> None:
    web = require(state.team("WEB"))
    assert [item.name for item in web.states][:3] == ["Backlog", "Todo", "In Progress"]
    assert web.states[2].type == "started"
    assert web.states[2].position == 2
    assert state.workflow_state("In Progress", web) is web.states[2]
    assert state.workflow_state(web.states[2].id, None) is web.states[2]
    assert state.workflow_state("Shipped", web) is None


def test_the_identifier_map_names_every_addressable_entity(state: LinearState) -> None:
    id_map = state.id_map()
    assert set(id_map) == {
        "issues",
        "users",
        "teams",
        "projects",
        "milestones",
        "documents",
        "attachments",
    }
    assert id_map["issues"]["WEB-611"] == uuid_for(SEED, "linear", "issue", "WEB-611")
    assert id_map["users"]["u-dana"] == uuid_for(SEED, "linear", "user", "u-dana")
    assert id_map["attachments"]["att-door-scan"] == uuid_for(
        SEED, "linear", "attachment", "att-door-scan"
    )


def test_the_workspace_lists_every_state_and_cycle_across_its_teams(state: LinearState) -> None:
    assert len(state.workflow_states()) == 10
    assert [cycle.key for cycle in state.cycles()][-1] == "IOS:12"


def test_a_document_is_found_by_key_title_or_id(state: LinearState) -> None:
    document = require(state.document("door-runbook"))
    assert state.document("Door night runbook") is document
    assert state.document(document.id) is document
    assert state.document("no-such-doc") is None


def test_a_fixture_key_is_not_something_a_linear_client_could_know(state: LinearState) -> None:
    assert state.user("u-dana") is None
    assert state.workflow_state("web-progress", None) is None
    assert state.label("web-regression") is None
    assert state.project("door-ops") is None
    assert state.milestone("m-scan") is None
    assert state.attachment("att-door-scan") is None


def test_every_real_linear_handle_still_finds_its_entity(state: LinearState) -> None:
    assert require(state.user("dana")).key == "u-dana"
    assert require(state.user("dana@ExampleCo.example")).key == "u-dana"
    assert require(state.workflow_state("In Progress", state.team("WEB"))).key == "web-progress"
    assert require(state.label("Regression")).key == "web-regression"
    assert require(state.project("Door operations")).key == "door-ops"
    assert require(state.milestone("Scanner reliability")).key == "m-scan"
    assert require(state.team("WEB")).name == "Web"
    assert require(state.document("door-runbook")).title == "Door night runbook"
