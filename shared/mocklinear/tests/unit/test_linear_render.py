from mocklinear.linear import render, render_project
from mocklinear.linear.state import LinearState
from mocklinear.tests.require import require


def test_a_project_carries_its_lead_teams_labels_and_dates(state: LinearState) -> None:
    project = require(state.project("Door operations"))
    payload = render_project.project_json(state, project)
    assert payload["id"] == project.id
    assert payload["name"] == "Door operations"
    assert payload["state"] == "started"
    assert payload["lead"]["displayName"] == "dana"
    assert payload["teams"] == [{"id": require(state.team("WEB")).id, "key": "WEB", "name": "Web"}]
    assert payload["startDate"] == "2026-02-02"
    assert payload["targetDate"] == "2026-03-27"
    assert payload["createdAt"] == "2026-01-28T09:00:00.000Z"
    assert payload["updatedAt"] == "2026-03-03T17:10:00.000Z"
    assert [label["name"] for label in payload["labels"]] == ["Bug", "Escalation"]
    assert payload["url"] == "https://linear.app/ExampleCo/project/door-ops"
    assert (
        render_project.project_json(state, require(state.project("Mobile scanning")))["lead"][
            "displayName"
        ]
        == "sasha"
    )


def test_a_milestone_names_its_project(state: LinearState) -> None:
    milestone = require(state.milestone("Scanner reliability"))
    assert render_project.milestone_json(state, milestone) == {
        "id": milestone.id,
        "name": "Scanner reliability",
        "targetDate": "2026-03-20",
        "project": {
            "id": require(state.project("Door operations")).id,
            "name": "Door operations",
        },
    }


def test_a_team_a_status_a_label_and_a_cycle_render_their_own_shapes(state: LinearState) -> None:
    team = require(state.team("WEB"))
    rendered = render.team_json(state, team)
    assert {key: value for key, value in rendered.items() if key != "members"} == {
        "id": team.id,
        "key": "WEB",
        "name": "Web",
        "description": "Web checkout and door tooling",
    }
    status = team.states[2]
    assert render.status_json(state, status) == {
        "id": status.id,
        "name": "In Progress",
        "type": "started",
        "color": "#f2c94c",
        "position": 2,
        "team": {"id": team.id, "key": "WEB", "name": "Web"},
    }
    label = require(state.label("bug"))
    assert render.label_json(state, label) == {
        "id": label.id,
        "name": "Bug",
        "color": "#eb5757",
        "team": None,
    }
    cycle = team.cycles[2]
    assert render_project.cycle_json(state, cycle) == {
        "id": cycle.id,
        "number": 43,
        "name": "Cycle 43",
        "startsAt": "2026-03-02T00:00:00.000Z",
        "endsAt": "2026-03-16T00:00:00.000Z",
        "team": {"id": team.id, "key": "WEB", "name": "Web"},
    }


def test_a_user_renders_its_activity_flag_in_the_long_form(state: LinearState) -> None:
    user = require(state.user("irene"))
    assert render.user_json(user) == {
        "id": user.id,
        "name": "Irene Kwon",
        "displayName": "irene",
        "email": "irene@ExampleCo.example",
        "active": False,
    }


def test_a_document_carries_its_body_and_its_project(state: LinearState) -> None:
    document = require(state.document("door-runbook"))
    payload = render_project.document_json(state, document)
    assert payload["id"] == document.id
    assert payload["title"] == "Door night runbook"
    assert payload["slugId"] == "door-runbook"
    assert payload["content"].startswith("# Door night runbook")
    assert payload["project"] == {
        "id": require(state.project("Door operations")).id,
        "name": "Door operations",
    }
    assert payload["creator"]["displayName"] == "dana"
    assert payload["createdAt"] == "2026-02-03T12:00:00.000Z"
    assert payload["updatedAt"] == "2026-02-25T09:20:00.000Z"
    assert payload["url"] == "https://linear.app/ExampleCo/document/door-runbook"


def test_a_reference_to_something_absent_renders_as_null(state: LinearState) -> None:
    assert render.status_ref(None) is None
    assert render.team_ref(None) is None
    assert render_project.cycle_ref(state, None) is None
    assert render_project.project_ref(state, None) is None
    assert render.user_ref(state, None) is None
    assert render.issue_ref(state, None) is None
    assert render.issue_id(state, None) is None


def test_a_team_names_its_members(state: LinearState) -> None:
    team = require(state.team("WEB"))
    assert render.team_json(state, team)["members"] == [
        {
            "id": require(state.user("dana")).id,
            "name": "Dana Whitfield",
            "displayName": "dana",
            "email": "dana@ExampleCo.example",
        },
        {
            "id": require(state.user("milo")).id,
            "name": "Milo Ferrante",
            "displayName": "milo",
            "email": "milo@ExampleCo.example",
        },
        {
            "id": require(state.user("sasha")).id,
            "name": "Sasha Bright",
            "displayName": "sasha",
            "email": "sasha@ExampleCo.example",
        },
    ]


def test_a_label_says_which_team_owns_it(state: LinearState) -> None:
    workspace = require(state.label("Bug"))
    assert render.label_json(state, workspace)["team"] is None
    team_owned = require(state.label("Regression"))
    assert render.label_json(state, team_owned)["team"] == {
        "id": require(state.team("WEB")).id,
        "key": "WEB",
        "name": "Web",
    }
