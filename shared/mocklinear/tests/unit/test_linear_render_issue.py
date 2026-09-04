from mocklinear.linear import render_issue
from mocklinear.linear.state import LinearState
from mocklinear.tests.require import require


def test_an_issue_carries_every_field_a_linear_client_reads(state: LinearState) -> None:
    issue = require(state.issue("WEB-611"))
    payload = render_issue.issue_json(state, issue)
    assert payload["id"] == issue.id
    assert payload["identifier"] == "WEB-611"
    assert payload["title"] == "Ticket scanner rejects re-entry passes"
    assert payload["description"].startswith("Hosts report")
    assert payload["priority"] == 1
    assert payload["priorityLabel"] == "Urgent"
    assert payload["estimate"] == 3
    assert payload["url"] == "https://linear.app/ExampleCo/issue/WEB-611"
    assert payload["state"] == {
        "id": require(state.workflow_state("In Progress", state.team("WEB"))).id,
        "name": "In Progress",
        "type": "started",
        "color": "#f2c94c",
    }
    assert payload["team"] == {"id": require(state.team("WEB")).id, "key": "WEB", "name": "Web"}
    assert payload["assignee"] == {
        "id": require(state.user("dana")).id,
        "name": "Dana Whitfield",
        "displayName": "dana",
        "email": "dana@ExampleCo.example",
    }
    assert payload["creator"]["displayName"] == "milo"
    assert [label["name"] for label in payload["labels"]] == ["Bug", "Escalation", "Regression"]
    assert payload["project"] == {
        "id": require(state.project("Door operations")).id,
        "name": "Door operations",
    }
    assert payload["cycle"] == {
        "id": require(state.team("WEB")).cycles[2].id,
        "number": 43,
        "name": "Cycle 43",
    }
    assert payload["parent"] is None
    assert payload["createdAt"] == "2026-02-18T09:12:00.000Z"
    assert payload["updatedAt"] == "2026-03-03T16:40:00.000Z"
    assert payload["startedAt"] == "2026-02-20T11:00:00.000Z"
    assert payload["completedAt"] is None
    assert payload["canceledAt"] is None
    assert payload["dueDate"] == "2026-03-10"
    assert payload["branchName"] == "dana/web-611-reentry-scan"
    assert payload["commentCount"] == 3
    assert "attachments" not in payload


def test_the_detailed_issue_adds_its_attachments(state: LinearState) -> None:
    issue = require(state.issue("WEB-611"))
    payload = render_issue.issue_json(state, issue, detail=True)
    assert payload["attachments"] == [
        {
            "id": issue.attachments[0].id,
            "title": "door-scan.mov",
            "subtitle": "Uploaded by the host at Warehouse 9",
            "url": "https://files.ExampleCo.example/door-scan.mov",
        }
    ]
    assert (
        render_issue.issue_json(state, require(state.issue("WEB-613")), detail=True)["attachments"]
        == []
    )


def test_an_issue_without_people_or_places_renders_nulls(state: LinearState) -> None:
    payload = render_issue.issue_json(state, require(state.issue("WEB-617")))
    assert payload["assignee"] is None
    assert payload["project"] is None
    assert payload["cycle"] is None
    assert payload["estimate"] is None
    assert payload["dueDate"] is None
    assert payload["priorityLabel"] == "Low"
    assert payload["canceledAt"] == "2026-02-06T11:00:00.000Z"


def test_a_sub_issue_names_its_parent(state: LinearState) -> None:
    payload = render_issue.issue_json(state, require(state.issue("WEB-615")))
    assert payload["parent"] == {
        "id": require(state.issue("WEB-614")).id,
        "identifier": "WEB-614",
    }


def test_priority_labels_cover_the_whole_scale(state: LinearState) -> None:
    assert [render_issue.priority_label(value) for value in range(5)] == [
        "No priority",
        "Urgent",
        "High",
        "Medium",
        "Low",
    ]


def test_a_comment_names_its_author_and_its_thread(state: LinearState) -> None:
    comments = require(state.issue("WEB-611")).comments
    assert render_issue.comment_json(state, comments[0]) == {
        "id": comments[0].id,
        "body": "Second scan says ALREADY_ADMITTED even though the guest was checked out.",
        "user": {
            "id": require(state.user("milo")).id,
            "name": "Milo Ferrante",
            "displayName": "milo",
            "email": "milo@ExampleCo.example",
        },
        "createdAt": "2026-02-18T10:02:00.000Z",
        "parentId": None,
        "issueId": require(state.issue("WEB-611")).id,
    }
    assert render_issue.comment_json(state, comments[2])["parentId"] == comments[1].id


def test_an_attachment_points_back_at_its_issue(state: LinearState) -> None:
    attachment = require(state.issue("IOS-1471")).attachments[0]
    assert render_issue.attachment_json(state, attachment) == {
        "id": attachment.id,
        "title": "permission-loop.txt",
        "subtitle": "Console log from the door iPad",
        "url": "https://files.ExampleCo.example/permission-loop.txt",
        "issue": {"id": require(state.issue("IOS-1471")).id, "identifier": "IOS-1471"},
    }


def test_an_issue_names_the_project_milestone_it_belongs_to(state: LinearState) -> None:
    payload = render_issue.issue_json(state, require(state.issue("WEB-611")))
    assert payload["projectMilestone"] == {
        "id": require(state.milestone("Scanner reliability")).id,
        "name": "Scanner reliability",
        "targetDate": "2026-03-20",
    }
    assert (
        render_issue.issue_json(state, require(state.issue("WEB-617")))["projectMilestone"] is None
    )
