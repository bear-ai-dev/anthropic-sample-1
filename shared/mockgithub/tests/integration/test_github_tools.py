import json
from typing import Any

import pytest

from mockgithub.tests.integration.conftest import Daemon

LEDGER = {"owner": "ExampleCo", "repo": "membership-ledger"}
EVERY_TOOL: list[tuple[str, dict[str, Any]]] = [
    ("get_me", {}),
    ("issue_read", dict(LEDGER, method="get", issue_number=38)),
    ("list_issues", dict(LEDGER, state="OPEN")),
    ("search_issues", {"query": "is:open label:docs"}),
    ("get_label", dict(LEDGER, name="docs")),
    ("pull_request_read", dict(LEDGER, method="get", pullNumber=39)),
    ("list_pull_requests", dict(LEDGER, state="closed")),
    ("search_pull_requests", {"query": "author:jiwon-park"}),
    ("get_file_contents", dict(LEDGER, path="README.md")),
    ("list_commits", dict(LEDGER, perPage=3)),
    ("get_commit", dict(LEDGER, sha="v0.8.0", detail="diff")),
    ("search_code", {"query": "filename:smoke.sh"}),
    ("list_branches", LEDGER),
    ("list_tags", LEDGER),
    ("list_releases", LEDGER),
    ("search_users", {"query": "ExampleCo.example"}),
]


def _call(daemon: Daemon, tool: str, arguments: dict[str, Any]) -> Any:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    return daemon.post("/mcp/github", message)["result"]


def test_the_health_check_names_only_github(daemon: Daemon) -> None:
    assert daemon.get("/healthz") == {"ok": True, "services": ["github"]}


def test_the_tool_list_is_the_sixteen_read_only_tools(daemon: Daemon) -> None:
    listed = daemon.post("/mcp/github", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert sorted(tool["name"] for tool in listed["result"]["tools"]) == sorted(
        name for name, _ in EVERY_TOOL
    )


@pytest.mark.parametrize(("tool", "arguments"), EVERY_TOOL, ids=[name for name, _ in EVERY_TOOL])
def test_every_tool_answers_over_http_without_an_error(
    daemon: Daemon, tool: str, arguments: dict[str, Any]
) -> None:
    result = _call(daemon, tool, arguments)
    assert "isError" not in result
    assert result["content"][0]["type"] == "text"
    text = result["content"][0]["text"]
    if tool == "get_file_contents":
        assert text.startswith("successfully downloaded text file (SHA: ")
        assert result["content"][1]["resource"]["uri"].startswith("repo://ExampleCo/")
    else:
        assert "\n" not in text
        json.loads(text)
    assert daemon.engine.journal.records()[-1]["tool"] == tool
    assert daemon.engine.journal.records()[-1]["outcome"] == "ok"


def test_the_snapshot_maps_commit_keys_to_shas_and_lists_numbers(daemon: Daemon) -> None:
    snapshot = daemon.get("/_admin/snapshot", {"x-mockgithub-admin-token": "integration-token"})
    ledger = snapshot["github"]["ExampleCo/membership-ledger"]
    assert ledger["issues"] == [38, 41, 43, 45, 48, 49, 50]
    assert ledger["pulls"] == [39, 40, 42, 44, 46, 47, 51]
    assert len(ledger["commits"]["c1"]) == 40
    assert snapshot["github"]["users"]["rhea-menon"] == daemon.engine.world.github.viewer.id


def test_a_not_found_and_a_bad_argument_reach_the_client_as_tool_errors(daemon: Daemon) -> None:
    missing = _call(daemon, "issue_read", dict(LEDGER, method="get", issue_number=999))
    assert missing["isError"] is True
    assert missing["content"][0]["text"] == (
        "failed to get issue: GET https://api.github.com/repos/ExampleCo/membership-ledger/"
        "issues/999: 404 Not Found []"
    )
    invalid = _call(daemon, "list_issues", {"repo": "membership-ledger"})
    assert invalid["isError"] is True
    assert invalid["content"][0]["text"] == "missing required parameter: owner"
