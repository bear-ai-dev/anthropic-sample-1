import base64
from typing import Any

from mockgithub.engine import Engine
from mockgithub.ids import hex_for, number_for
from mockgithub.tests.calls import call_error, call_json
from mockgithub.tests.conftest import SEED

LEDGER = {"owner": "ExampleCo", "repo": "membership-ledger"}
NOT_FOUND = "failed to get pull request: GET https://api.github.com/repos/ExampleCo/membership-ledger/"


def _sha(key: str) -> str:
    return hex_for(SEED, "github", "commit", f"ExampleCo/membership-ledger:{key}", 40)


def _pull(engine: Engine, number: int, method: str = "get", **extra: Any) -> Any:
    return call_json(
        engine, "pull_request_read", dict(LEDGER, method=method, pullNumber=number, **extra)
    )


def test_pull_request_read_review_comments_are_graphql_threads(engine: Engine) -> None:
    threads = _pull(engine, 46, "get_review_comments")
    assert list(threads) == ["reviewThreads", "pageInfo", "totalCount"]
    assert threads["totalCount"] == 4
    assert threads["pageInfo"] == {
        "hasNextPage": False,
        "endCursor": base64.b64encode(b"cursor:4").decode(),
    }
    first = threads["reviewThreads"][0]
    comment_id = number_for(SEED, "github", "review_comment", "ExampleCo/membership-ledger#46:0")
    assert first == {
        "id": comment_id,
        "isResolved": False,
        "comments": {
            "nodes": [
                {
                    "id": comment_id,
                    "body": first["comments"]["nodes"][0]["body"],
                    "path": first["comments"]["nodes"][0]["path"],
                    "line": first["comments"]["nodes"][0]["line"],
                    "author": {"login": first["comments"]["nodes"][0]["author"]["login"]},
                }
            ]
        },
    }
    page = _pull(engine, 46, "get_review_comments", perPage=3)
    assert len(page["reviewThreads"]) == 3
    assert page["pageInfo"]["hasNextPage"]
    rest = _pull(engine, 46, "get_review_comments", perPage=3, after=page["pageInfo"]["endCursor"])
    assert len(rest["reviewThreads"]) == 1
    assert not rest["pageInfo"]["hasNextPage"]


def test_pull_request_read_reviews_comments_and_check_runs(engine: Engine) -> None:
    reviews = _pull(engine, 40, "get_reviews")
    assert [review["state"] for review in reviews] == [
        review["state"] for review in reviews if review["state"] in ("APPROVED", "COMMENTED")
    ]
    assert list(reviews[0]) == ["id", "user", "state", "body", "submitted_at"]
    assert reviews[0]["id"] == number_for(SEED, "github", "review", "ExampleCo/membership-ledger#40:0")
    assert reviews[0]["user"] == {"login": reviews[0]["user"]["login"]}
    comments = _pull(engine, 39, "get_comments")
    assert [comment["user"]["login"] for comment in comments] == ["mbeaulieu"]
    assert comments[0]["html_url"].startswith(
        "https://github.com/ExampleCo/membership-ledger/pull/39#issuecomment-"
    )
    runs = _pull(engine, 47, "get_check_runs")
    assert runs["total_count"] == 4
    assert [run["conclusion"] for run in runs["check_runs"]] == [
        "success",
        "success",
        "success",
        "failure",
    ]
    assert runs["check_runs"][0]["name"] == "ci / build"
    assert runs["check_runs"][0]["status"] == "completed"
    assert runs["check_runs"][0]["head_sha"] == _sha("c11")


def test_pull_request_read_refuses_bad_arguments_and_missing_pulls(engine: Engine) -> None:
    assert call_error(engine, "pull_request_read", dict(LEDGER, method="get", pullNumber=999)) == (
        NOT_FOUND + "pulls/999: 404 Not Found []"
    )
    assert call_error(engine, "pull_request_read", dict(LEDGER, method="get")) == (
        "missing required parameter: pullNumber"
    )
    message = call_error(engine, "pull_request_read", dict(LEDGER, method="get_x", pullNumber=39))
    assert message.startswith("parameter method must be one of get, get_diff, get_status, ")
    assert call_error(
        engine,
        "pull_request_read",
        dict(LEDGER, method="get_review_comments", pullNumber=46, after="zz"),
    ) == ("Invalid cursor")
