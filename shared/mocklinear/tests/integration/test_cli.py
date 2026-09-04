import json
import os
import subprocess
import sys
from pathlib import Path

from mocklinear.tests.integration.conftest import Daemon

SHARED = Path(__file__).resolve().parents[3]
WRAPPER = SHARED / "mocklinear" / "bin" / "mocklinear"


def _run(url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(SHARED),
        "MOCKLINEAR_URL": url,
    }
    return subprocess.run(
        [sys.executable, "-m", "mocklinear.client", *arguments],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
    )


def test_the_command_lists_the_tools_it_answers(daemon: Daemon) -> None:
    done = _run(daemon.url, "tools")
    assert done.returncode == 0
    assert done.stderr == ""
    assert done.stdout.count("inputSchema") == 0
    assert "list_issues: List issues in the workspace" in done.stdout
    assert done.stdout.count('  "type": "object"') == 20


def test_a_tool_call_prints_what_the_workspace_answered(daemon: Daemon) -> None:
    done = _run(daemon.url, "list_issues", "--assignee", "me", "--limit", "2")
    assert done.returncode == 0
    payload = json.loads(done.stdout)
    assert [issue["identifier"] for issue in payload["issues"]] == ["WEB-619", "WEB-611"]
    assert daemon.engine.journal.records()[0]["via"] == "cli"


def test_arguments_can_arrive_as_one_json_object(daemon: Daemon) -> None:
    done = _run(daemon.url, "list_issues", "--json", '{"team": "IOS", "limit": 1}')
    assert done.returncode == 0
    assert json.loads(done.stdout)["issues"][0]["identifier"] == "IOS-1471"


def test_a_value_that_starts_with_a_dash_travels_after_a_double_dash(daemon: Daemon) -> None:
    refused = _run(daemon.url, "list_issues", "--updatedAt", "-P2D")
    assert refused.returncode == 2
    assert "put it after --" in refused.stderr
    accepted = _run(daemon.url, "list_issues", "--updatedAt", "--", "-P2D")
    assert accepted.returncode == 0
    assert len(json.loads(accepted.stdout)["issues"]) == 3


def test_a_missing_entity_exits_one_with_the_vendor_text(daemon: Daemon) -> None:
    done = _run(daemon.url, "get_issue", "--id", "WEB-999")
    assert done.returncode == 1
    assert done.stdout == "Entity not found: Issue - Could not find referenced Issue.\n"


def test_an_unknown_tool_exits_two(daemon: Daemon) -> None:
    done = _run(daemon.url, "create_issue", "--title", "nope")
    assert done.returncode == 2
    assert done.stderr.strip() == "Unknown tool: create_issue"


def test_a_daemon_that_is_not_listening_is_reported_without_a_traceback() -> None:
    done = _run("http://127.0.0.1:4", "list_issues")
    assert done.returncode == 2
    assert done.stderr.strip() == "mocklinear daemon not reachable at http://127.0.0.1:4"
    assert "Traceback" not in done.stderr


def test_the_shell_wrapper_reaches_the_same_tools(daemon: Daemon) -> None:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "MOCKLINEAR_PYTHONPATH": str(SHARED),
        "MOCKLINEAR_URL": daemon.url,
    }
    done = subprocess.run(
        [str(WRAPPER), "get_team", "--id", "WEB"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["key"] == "WEB"


def test_stdin_that_never_speaks_gets_the_usage_and_exits_zero(daemon: Daemon) -> None:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(SHARED),
        "MOCKLINEAR_URL": daemon.url,
        "MOCKLINEAR_STDIO_IDLE_SEC": "0.2",
    }
    done = subprocess.run(
        [sys.executable, "-m", "mocklinear.client"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    assert done.returncode == 0
    assert "linear tools" in done.stdout


def test_the_same_tool_through_both_transports_differs_only_in_how_it_arrived(
    daemon: Daemon,
) -> None:
    _run(daemon.url, "get_team", "--id", "WEB")
    daemon.post(
        "/mcp/linear",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_team", "arguments": {"id": "WEB"}},
        },
        {"x-mocklinear-via": "mcp"},
    )
    records = daemon.engine.journal.records()
    assert [record["via"] for record in records] == ["cli", "mcp"]
    assert records[0]["args"] == records[1]["args"]
    assert records[0]["result_chars"] == records[1]["result_chars"]
