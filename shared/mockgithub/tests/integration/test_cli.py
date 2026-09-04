import json
import os
import subprocess
import sys
from pathlib import Path

from mockgithub.tests.integration.conftest import Daemon

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
WRAPPER = PACKAGE_ROOT / "mockgithub" / "bin" / "mockgithub"


def _run(daemon: Daemon, *argv: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "MOCKGITHUB_URL": daemon.url, "PYTHONPATH": str(PACKAGE_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "mockgithub.client", *argv],
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_the_tool_listing_and_a_call_with_flags(daemon: Daemon) -> None:
    listing = _run(daemon, "tools")
    assert listing.returncode == 0
    assert "issue_read: " in listing.stdout
    assert '"issue_number"' in listing.stdout
    called = _run(daemon, "issue_read", "--owner", "ExampleCo", "--repo", "membership-ledger")
    assert called.returncode == 1
    assert called.stdout == "missing required parameter: method\n"
    called = _run(
        daemon,
        "issue_read",
        "--owner",
        "ExampleCo",
        "--repo",
        "membership-ledger",
        "--method",
        "get",
        "--issue_number",
        "38",
    )
    assert called.returncode == 0
    assert json.loads(called.stdout)["number"] == 38
    assert daemon.engine.journal.records()[-1]["via"] == "cli"
    assert daemon.engine.journal.records()[-1]["args"]["issue_number"] == 38


def test_json_arguments_dash_values_and_a_resource_block(daemon: Daemon) -> None:
    searched = _run(daemon, "search_issues", "--json", '{"query": "is:open", "perPage": 1}')
    assert searched.returncode == 0
    assert json.loads(searched.stdout)["total_count"] == 3
    refused = _run(daemon, "search_issues", "--query", "-label:docs")
    assert refused.returncode == 2
    assert "put it after --" in refused.stderr
    passed = _run(daemon, "search_issues", "--query", "--", "-label:docs is:open")
    assert passed.returncode == 0
    assert json.loads(passed.stdout)["total_count"] == 1
    contents = _run(
        daemon,
        "get_file_contents",
        "--owner",
        "ExampleCo",
        "--repo",
        "membership-ledger",
        "--path",
        "README.md",
    )
    assert contents.returncode == 0
    first, second = contents.stdout.split("\n", 1)
    assert first.startswith("successfully downloaded text file (SHA: ")
    assert second.startswith("# membership-ledger\n")


def test_the_shell_wrapper_and_usage_on_end_of_input(daemon: Daemon) -> None:
    env = {
        **os.environ,
        "MOCKGITHUB_URL": daemon.url,
        "MOCKGITHUB_PYTHONPATH": str(PACKAGE_ROOT),
    }
    wrapped = subprocess.run(
        ["sh", str(WRAPPER), "github", "get_me"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert wrapped.returncode == 0
    assert json.loads(wrapped.stdout)["login"] == "rhea-menon"
    bare = _run(daemon, stdin="")
    assert bare.returncode == 0
    assert "github tools" in bare.stdout


def test_the_same_call_over_stdio_and_cli_differs_only_in_its_transport(daemon: Daemon) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "list_branches",
            "arguments": {"owner": "ExampleCo", "repo": "membership-ledger"},
        },
    }
    shim = _run(daemon, stdin=json.dumps(request) + "\n")
    assert shim.returncode == 0
    assert json.loads(shim.stdout)["result"]["content"][0]["text"].startswith('[{"name":"main"')
    cli = _run(daemon, "list_branches", "--owner", "ExampleCo", "--repo", "membership-ledger")
    assert cli.returncode == 0
    first, second = daemon.engine.journal.records()[-2:]
    assert (first["via"], second["via"]) == ("mcp", "cli")
    stripped = [
        {k: v for k, v in record.items() if k not in ("via", "at", "duration_ms", "seq")}
        for record in (first, second)
    ]
    assert stripped[0] == stripped[1]
