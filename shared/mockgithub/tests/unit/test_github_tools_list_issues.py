import base64
from typing import Any

from mockgithub.engine import Engine
from mockgithub.ids import number_for
from mockgithub.tests.calls import call_error, call_json
from mockgithub.tests.conftest import SEED

LEDGER = {"owner": "ExampleCo", "repo": "membership-ledger"}
NOT_FOUND = "failed to get issue: GET https://api.github.com/repos/ExampleCo/membership-ledger/"


def _issue(engine: Engine, number: int, method: str = "get", **extra: Any) -> Any:
    return call_json(
        engine, "issue_read", dict(LEDGER, method=method, issue_number=number, **extra)
    )


def test_list_issues_is_the_graphql_shape_newest_first(engine: Engine) -> None:
    listing = call_json(engine, "list_issues", LEDGER)
    assert list(listing) == ["issues", "pageInfo", "totalCount"]
    assert [issue["number"] for issue in listing["issues"]] == [50, 49, 48, 45, 43, 41, 38]
    assert listing["totalCount"] == 7
    assert listing["pageInfo"] == {
        "hasNextPage": False,
        "endCursor": base64.b64encode(b"cursor:7").decode(),
    }
    first = listing["issues"][0]
    assert first == {
        "number": 50,
        "title": "a make target for the smoke run",
        "body": first["body"],
        "state": "OPEN",
        "author": {"login": "rhea-menon"},
        "labels": {"nodes": [{"name": "ops"}]},
        "createdAt": "2025-11-24T16:02:00Z",
        "updatedAt": first["updatedAt"],
        "closedAt": None,
        "comments": {"totalCount": 1},
    }


def test_list_issues_filters_by_state_labels_and_since(engine: Engine) -> None:
    closed = call_json(engine, "list_issues", dict(LEDGER, state="CLOSED"))
    assert [issue["number"] for issue in closed["issues"]] == [45, 43, 41, 38]
    assert all(issue["state"] == "CLOSED" for issue in closed["issues"])
    docs = call_json(engine, "list_issues", dict(LEDGER, labels=["docs", "ap-2"]))
    assert [issue["number"] for issue in docs["issues"]] == [49, 48]
    recent = call_json(engine, "list_issues", dict(LEDGER, since="2025-11-01T00:00:00Z"))
    assert [issue["number"] for issue in recent["issues"]] == [50, 49, 48]
    assert call_error(engine, "list_issues", dict(LEDGER, since="soon")) == (
        "not a timestamp: soon"
    )
    assert call_error(engine, "list_issues", dict(LEDGER, state="open")) == (
        "parameter state must be one of OPEN, CLOSED"
    )


def test_list_issues_orders_and_pages_with_graphql_cursors(engine: Engine) -> None:
    oldest = call_json(engine, "list_issues", dict(LEDGER, direction="ASC", perPage=3))
    assert [issue["number"] for issue in oldest["issues"]] == [38, 41, 43]
    assert oldest["pageInfo"]["hasNextPage"]
    following = call_json(
        engine,
        "list_issues",
        dict(LEDGER, direction="ASC", perPage=3, after=oldest["pageInfo"]["endCursor"]),
    )
    assert [issue["number"] for issue in following["issues"]] == [45, 48, 49]
    updated = call_json(engine, "list_issues", dict(LEDGER, orderBy="UPDATED_AT"))
    assert updated["issues"][0]["number"] == 50
    assert call_error(engine, "list_issues", dict(LEDGER, after="zzz")) == "Invalid cursor"
    entry = engine.journal.records()[-1]
    assert entry["page"] is None
    assert engine.journal.records()[0]["page"] == {
        "perPage": 3,
        "hasNextPage": True,
        "endCursor": oldest["pageInfo"]["endCursor"],
    }


def test_list_issues_on_an_unknown_repository_is_a_not_found(engine: Engine) -> None:
    assert call_error(engine, "list_issues", {"owner": "acme", "repo": "nope"}) == (
        "failed to list issues: GET https://api.github.com/repos/acme/nope: 404 Not Found []"
    )


def test_get_label_returns_the_label_or_a_not_found(engine: Engine) -> None:
    label = call_json(engine, "get_label", dict(LEDGER, name="area/api"))
    assert label == {
        "id": number_for(SEED, "github", "label", "ExampleCo/membership-ledger:area/api"),
        "name": "area/api",
        "color": "0e8a16",
        "description": "The public /v1 endpoints",
        "url": "https://api.github.com/repos/ExampleCo/membership-ledger/labels/area/api",
    }
    assert call_error(engine, "get_label", dict(LEDGER, name="nope")) == (
        "failed to get label: GET https://api.github.com/repos/ExampleCo/membership-ledger/labels/nope"
        ": 404 Not Found []"
    )
