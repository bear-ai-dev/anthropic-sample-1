from typing import Any

from mockgithub.engine import Engine
from mockgithub.ids import hex_for
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


def test_list_pull_requests_defaults_to_open_and_filters_by_state(engine: Engine) -> None:
    assert call_json(engine, "list_pull_requests", LEDGER) == []
    closed = call_json(engine, "list_pull_requests", dict(LEDGER, state="closed"))
    assert [pull["number"] for pull in closed] == [51, 47, 46, 44, 42, 40, 39]
    assert closed[0]["head"]["sha"] == _sha("c15")
    everything = call_json(engine, "list_pull_requests", dict(LEDGER, state="all"))
    assert len(everything) == 7


def test_list_pull_requests_filters_by_head_and_base_and_sorts(engine: Engine) -> None:
    by_head = call_json(
        engine, "list_pull_requests", dict(LEDGER, state="all", head="ExampleCo:ap2-probes")
    )
    assert [pull["number"] for pull in by_head] == [47]
    bare_head = call_json(
        engine, "list_pull_requests", dict(LEDGER, state="all", head="ap2-probes")
    )
    assert [pull["number"] for pull in bare_head] == [47]
    assert call_json(engine, "list_pull_requests", dict(LEDGER, state="all", base="develop")) == []
    ascending = call_json(
        engine,
        "list_pull_requests",
        dict(LEDGER, state="all", sort="created", direction="asc", perPage=2, page=2),
    )
    assert [pull["number"] for pull in ascending] == [42, 44]
    by_update = call_json(engine, "list_pull_requests", dict(LEDGER, state="all", sort="updated"))
    assert by_update[0]["number"] == 51
    popular = call_json(engine, "list_pull_requests", dict(LEDGER, state="all", sort="popularity"))
    assert popular[0]["number"] == 46
    assert engine.journal.records()[-1]["page"] == {"page": 1, "perPage": 30, "hasNextPage": False}
    assert call_error(engine, "list_pull_requests", dict(LEDGER, state="merged")) == (
        "parameter state must be one of open, closed, all"
    )
    assert call_error(engine, "list_pull_requests", {"owner": "acme", "repo": "nope"}) == (
        "failed to list pull requests: GET https://api.github.com/repos/acme/nope: 404 Not Found []"
    )
