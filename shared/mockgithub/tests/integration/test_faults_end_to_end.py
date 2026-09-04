import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mockgithub.engine import Engine
from mockgithub.journal import Journal
from mockgithub.registry import build_registries
from mockgithub.scenario import validate_scenario
from mockgithub.tests.integration.conftest import ADMIN_TOKEN, Daemon, _serve

LEDGER = {"owner": "ExampleCo", "repo": "membership-ledger"}
HEADERS = {"x-mockgithub-admin-token": ADMIN_TOKEN}


def _call(daemon: Daemon, tool: str, arguments: dict[str, Any]) -> Any:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    return daemon.post("/mcp/github", message)["result"]


@pytest.fixture
def faulty_daemon(scenario: dict[str, Any], tmp_path: Path) -> Iterator[Daemon]:
    scenario["faults"] = {
        "enabled": True,
        "rules": [
            {"service": "github", "tool": "issue_read", "throttle_every": 1},
            {"service": "github", "tool": "get_me", "server_error_every": 1},
            {"service": "github", "tool": "list_issues", "max_page_size": 2},
            {"service": "github", "tool": "list_commits", "max_page_size": 4},
        ],
    }
    yield from _serve(scenario, tmp_path, build_registries())


def test_a_throttle_rule_reads_like_the_github_rate_limit(faulty_daemon: Daemon) -> None:
    result = _call(faulty_daemon, "issue_read", dict(LEDGER, method="get", issue_number=38))
    assert result["isError"] is True
    assert result["content"][0]["text"] == (
        "failed to get issue: GitHub API rate limit exceeded. Retry after 1m0s."
    )
    assert faulty_daemon.engine.journal.records()[-1]["outcome"] == "throttled"


def test_a_server_error_rule_reads_like_a_bad_gateway(faulty_daemon: Daemon) -> None:
    result = _call(faulty_daemon, "get_me", {})
    assert result["isError"] is True
    assert result["content"][0]["text"] == "failed to get user: 502 Bad Gateway []"


def test_a_page_cap_forces_pagination_and_the_cursors_still_walk_to_the_end(
    faulty_daemon: Daemon,
) -> None:
    seen: list[int] = []
    after: str | None = None
    for _ in range(10):
        arguments: dict[str, Any] = dict(LEDGER, perPage=50)
        if after is not None:
            arguments["after"] = after
        page = json.loads(_call(faulty_daemon, "list_issues", arguments)["content"][0]["text"])
        assert len(page["issues"]) <= 2
        seen.extend(issue["number"] for issue in page["issues"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    assert seen == [50, 49, 48, 45, 43, 41, 38]
    commits = json.loads(
        _call(faulty_daemon, "list_commits", dict(LEDGER, perPage=100))["content"][0]["text"]
    )
    assert len(commits) == 4
    assert faulty_daemon.engine.journal.records()[-1]["page"]["perPage"] == 4


def test_the_verifier_can_switch_the_faults_off(faulty_daemon: Daemon) -> None:
    assert faulty_daemon.post("/_admin/faults", {"enabled": False}, HEADERS) == {"ok": True}
    result = _call(faulty_daemon, "issue_read", dict(LEDGER, method="get", issue_number=38))
    assert "isError" not in result
    assert json.loads(result["content"][0]["text"])["number"] == 38
    calls = faulty_daemon.get("/_admin/calls", HEADERS)
    assert calls["fault_counters"] == {"github:issue_read": 1}


def test_two_engines_with_the_same_seed_and_scenario_journal_identically(
    scenario: dict[str, Any],
) -> None:
    scenario["faults"] = {
        "rules": [{"service": "github", "tool": "*", "throttle_every": 3, "throttle_burst": 1}]
    }
    sequence: list[tuple[str, dict[str, Any]]] = [
        ("get_me", {}),
        ("list_issues", dict(LEDGER)),
        ("list_issues", dict(LEDGER)),
        ("issue_read", dict(LEDGER, method="get", issue_number=38)),
        ("list_issues", dict(LEDGER)),
        ("search_users", {"query": "rhea"}),
    ]
    journals: list[list[dict[str, Any]]] = []
    for _ in range(2):
        journal = Journal(None)
        engine = Engine(validate_scenario(scenario), 7, journal)
        for tool, arguments in sequence:
            engine.call("github", tool, arguments, "http")
        journals.append(
            [
                {key: value for key, value in record.items() if key not in ("at", "duration_ms")}
                for record in journal.records()
            ]
        )
    assert journals[0] == journals[1]
    assert "throttled" in {record["outcome"] for record in journals[0]}
