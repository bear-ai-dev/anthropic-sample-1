import json
from typing import Any

from mocklinear.tests.integration.conftest import Daemon


def _call(daemon: Daemon, tool: str, arguments: dict[str, Any]) -> Any:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    return daemon.post("/mcp/linear", message)["result"]


def test_a_client_reads_the_workspace_over_the_wire(daemon: Daemon) -> None:
    listed = daemon.post("/mcp/linear", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert len(listed["result"]["tools"]) == 20
    result = _call(daemon, "list_issues", {"assignee": "me", "limit": 2})
    assert "isError" not in result
    payload = json.loads(result["content"][0]["text"])
    assert [issue["identifier"] for issue in payload["issues"]] == ["WEB-619", "WEB-611"]
    assert payload["pageInfo"]["hasNextPage"]


def test_a_missing_issue_comes_back_as_an_error_result(daemon: Daemon) -> None:
    result = _call(daemon, "get_issue", {"id": "WEB-999"})
    assert result["isError"] is True
    assert result["content"][0]["text"] == (
        "Entity not found: Issue - Could not find referenced Issue."
    )


def test_the_journal_records_the_tool_the_arguments_and_the_page(daemon: Daemon) -> None:
    _call(daemon, "get_issue", {"id": "WEB-611"})
    _call(daemon, "list_issues", {"limit": 2})
    records = daemon.engine.journal.records()
    assert [record["tool"] for record in records] == ["get_issue", "list_issues"]
    assert records[0]["args"] == {"id": "WEB-611"}
    assert records[0]["page"] is None
    assert records[1]["page"]["hasNextPage"] is True
