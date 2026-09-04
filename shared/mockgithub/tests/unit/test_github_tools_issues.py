from typing import Any

from mockgithub.engine import Engine
from mockgithub.ids import number_for
from mockgithub.tests.calls import call, call_error, call_json
from mockgithub.tests.conftest import SEED

LEDGER = {"owner": "ExampleCo", "repo": "membership-ledger"}
NOT_FOUND = "failed to get issue: GET https://api.github.com/repos/ExampleCo/membership-ledger/"


def _issue(engine: Engine, number: int, method: str = "get", **extra: Any) -> Any:
    return call_json(
        engine, "issue_read", dict(LEDGER, method=method, issue_number=number, **extra)
    )


def test_get_me_is_the_viewer_as_a_minimal_user(engine: Engine) -> None:
    me = call_json(engine, "get_me")
    user_id = number_for(SEED, "github", "user", "rhea-menon")
    assert me == {
        "login": "rhea-menon",
        "id": user_id,
        "profile_url": "https://github.com/rhea-menon",
        "avatar_url": f"https://avatars.githubusercontent.com/u/{user_id}?v=4",
        "details": {
            "name": "Rhea Menon",
            "email": "rhea.menon@ExampleCo.example",
            "company": "",
            "location": "",
            "bio": "",
            "public_repos": 0,
            "followers": 0,
            "following": 0,
            "created_at": "2026-03-04T10:00:00Z",
        },
    }
    text = call(engine, "get_me").content[0]["text"]
    assert text.startswith('{"login":"rhea-menon","id":')
    assert "\n" not in text


def test_issue_read_get_is_the_rest_issue(engine: Engine) -> None:
    issue = _issue(engine, 38)
    assert list(issue) == [
        "number",
        "title",
        "body",
        "state",
        "state_reason",
        "user",
        "labels",
        "assignees",
        "milestone",
        "comments",
        "created_at",
        "updated_at",
        "closed_at",
        "html_url",
    ]
    assert issue["number"] == 38
    assert issue["state"] == "closed"
    assert issue["state_reason"] == "completed"
    assert issue["user"]["login"] == "rhea-menon"
    assert set(issue["user"]) == {"login", "id", "html_url", "avatar_url"}
    assert issue["labels"] == [
        {"name": "ci", "color": "fbca04", "description": "Build pipeline"},
        {
            "name": "flaky",
            "color": "d4c5f9",
            "description": "Fails intermittently and not because of the change",
        },
    ]
    assert [user["login"] for user in issue["assignees"]] == ["mbeaulieu"]
    assert issue["milestone"] is None
    assert issue["comments"] == 3
    assert issue["created_at"] == "2025-06-20T09:30:00Z"
    assert issue["updated_at"] == "2025-09-03T09:02:00Z"
    assert issue["closed_at"] == "2025-09-03T09:02:00Z"
    assert issue["html_url"] == "https://github.com/ExampleCo/membership-ledger/issues/38"
    open_issue = _issue(engine, 48)
    assert open_issue["state"] == "open"
    assert open_issue["state_reason"] is None
    assert open_issue["closed_at"] is None
    assert open_issue["milestone"] == {
        "number": 3,
        "title": "next region",
        "state": "open",
        "due_on": "2026-05-29T00:00:00Z",
    }


def test_issue_read_comments_are_paged_rest_comments(engine: Engine) -> None:
    comments = _issue(engine, 45, "get_comments")
    assert [comment["user"]["login"] for comment in comments] == [
        "sofia-braga",
        "dkowalczyk",
        "harun-yildiz",
        "rhea-menon",
    ]
    first = comments[0]
    assert first["id"] == number_for(SEED, "github", "comment", "ExampleCo/membership-ledger:i45c1")
    assert first["body"].startswith("Finance re-ran")
    assert first["created_at"] == "2025-09-09T14:50:00Z"
    assert first["html_url"].startswith(
        "https://github.com/ExampleCo/membership-ledger/issues/45#issuecomment-"
    )
    second_page = _issue(engine, 45, "get_comments", page=2, perPage=3)
    assert [comment["id"] for comment in second_page] == [comments[3]["id"]]


def test_issue_read_walks_sub_issues_and_parents(engine: Engine) -> None:
    children = _issue(engine, 48, "get_sub_issues")
    assert [child["number"] for child in children] == [49]
    assert children[0]["html_url"].endswith("/issues/49")
    assert _issue(engine, 49, "get_parent")["number"] == 48
    assert _issue(engine, 49, "get_sub_issues") == []
    assert call_error(engine, "issue_read", dict(LEDGER, method="get_parent", issue_number=48)) == (
        NOT_FOUND + "issues/48/parent: 404 Not Found []"
    )


def test_issue_read_labels_are_the_full_label_objects(engine: Engine) -> None:
    labels = _issue(engine, 45, "get_labels")
    assert [label["name"] for label in labels] == ["ops", "ap-2"]
    assert labels[0]["id"] == number_for(SEED, "github", "label", "ExampleCo/membership-ledger:ops")
    assert labels[0]["color"] == "b60205"


def test_issue_read_refuses_bad_arguments_and_missing_issues(engine: Engine) -> None:
    assert call_error(engine, "issue_read", {"method": "get"}) == (
        "missing required parameter: owner"
    )
    assert call_error(engine, "issue_read", dict(LEDGER, issue_number=38)) == (
        "missing required parameter: method"
    )
    assert call_error(engine, "issue_read", dict(LEDGER, method="nope", issue_number=38)) == (
        "parameter method must be one of get, get_comments, get_sub_issues, get_parent, get_labels"
    )
    assert call_error(engine, "issue_read", dict(LEDGER, method="get", issue_number=999)) == (
        NOT_FOUND + "issues/999: 404 Not Found []"
    )
    assert call_error(
        engine,
        "issue_read",
        {"owner": "ExampleCo", "repo": "nope", "method": "get", "issue_number": 1},
    ) == ("failed to get issue: GET https://api.github.com/repos/ExampleCo/nope: 404 Not Found []")
    assert (
        call_error(engine, "issue_read", dict(LEDGER, method="get", issue_number="x"))
        == "parameter issue_number must be an integer"
    )
