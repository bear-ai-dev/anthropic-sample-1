from typing import Any

from mockgithub.engine import Engine
from mockgithub.ids import hex_for
from mockgithub.tests.calls import call, call_json
from mockgithub.tests.conftest import SEED
from mockgithub.tests.require import require

LEDGER = {"owner": "ExampleCo", "repo": "membership-ledger"}
NOT_FOUND = "failed to get pull request: GET https://api.github.com/repos/ExampleCo/membership-ledger/"


def _sha(key: str) -> str:
    return hex_for(SEED, "github", "commit", f"ExampleCo/membership-ledger:{key}", 40)


def _pull(engine: Engine, number: int, method: str = "get", **extra: Any) -> Any:
    return call_json(
        engine, "pull_request_read", dict(LEDGER, method=method, pullNumber=number, **extra)
    )


def test_an_open_pull_is_mergeable(engine: Engine) -> None:
    scenario = engine.world.github
    repo = require(scenario.repo("ExampleCo", "membership-ledger"))
    assert all(pull.merged for pull in repo.pulls)
    engine.reseed(
        {
            "version": 1,
            "clock": "2026-03-04T10:00:00Z",
            "faults": {},
            "github": {
                "users": [{"login": "ann"}],
                "repos": [
                    {
                        "owner": "acme",
                        "name": "widgets",
                        "commits": [{"key": "a", "message": "root", "author": "ann"}],
                        "pulls": [
                            {
                                "number": 1,
                                "title": "wip",
                                "head": {"ref": "topic", "sha": "a"},
                                "user": "ann",
                                "draft": True,
                                "statuses": [
                                    {"context": "ci/lint", "state": "success"},
                                    {"context": "ci/test", "state": "pending"},
                                ],
                            }
                        ],
                    }
                ],
            },
        },
        None,
    )
    args = {"owner": "acme", "repo": "widgets", "method": "get", "pullNumber": 1}
    pull = call_json(engine, "pull_request_read", args)
    assert pull["state"] == "open"
    assert pull["draft"] is True
    assert pull["mergeable_state"] == "clean"
    assert pull["merged_at"] is None
    status = call_json(engine, "pull_request_read", dict(args, method="get_status"))
    assert status["state"] == "pending"
    assert status["total_count"] == 2
    assert status["statuses"][1] == {
        "context": "ci/test",
        "state": "pending",
        "description": "",
        "target_url": None,
    }
    diff = call(engine, "pull_request_read", dict(args, method="get_diff"))
    assert diff.content[0]["text"] == ""
    files = call_json(engine, "pull_request_read", dict(args, method="get_files"))
    assert files == []
    runs = call_json(engine, "pull_request_read", dict(args, method="get_check_runs"))
    assert runs == {"total_count": 0, "check_runs": []}
    commits = call_json(engine, "pull_request_read", dict(args, method="get_commits"))
    assert [commit["sha"] for commit in commits] == [
        hex_for(SEED, "github", "commit", "acme/widgets:a", 40)
    ]


def _with_statuses(engine: Engine, statuses: list[dict[str, str]]) -> str:
    engine.reseed(
        {
            "version": 1,
            "clock": "2026-03-04T10:00:00Z",
            "github": {
                "users": [{"login": "ann"}],
                "repos": [
                    {
                        "owner": "acme",
                        "name": "widgets",
                        "commits": [{"key": "a", "message": "root", "author": "ann"}],
                        "branches": [{"name": "main", "head": "a"}],
                        "pulls": [
                            {
                                "number": 1,
                                "title": "wip",
                                "head": {"ref": "topic", "sha": "a"},
                                "user": "ann",
                                "statuses": statuses,
                            }
                        ],
                    }
                ],
            },
        },
        None,
    )
    args = {"owner": "acme", "repo": "widgets", "method": "get_status", "pullNumber": 1}
    state: str = call_json(engine, "pull_request_read", args)["state"]
    return state


def test_the_combined_status_is_the_worst_of_its_statuses(engine: Engine) -> None:
    assert _with_statuses(engine, [{"context": "a", "state": "success"}]) == "success"
    assert (
        _with_statuses(
            engine, [{"context": "a", "state": "success"}, {"context": "b", "state": "error"}]
        )
        == "failure"
    )
    assert _with_statuses(engine, [{"context": "a", "state": "failure"}]) == "failure"
    assert _with_statuses(engine, [{"context": "a", "state": "pending"}]) == "pending"
    args = {"owner": "acme", "repo": "widgets", "method": "get_commits", "pullNumber": 1}
    assert call_json(engine, "pull_request_read", args)[0]["parents"] == []
