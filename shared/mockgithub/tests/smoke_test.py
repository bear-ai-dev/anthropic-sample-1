import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from mockgithub.engine import Engine  # noqa: E402
from mockgithub.journal import Journal  # noqa: E402
from mockgithub.scenario import load_scenario  # noqa: E402
from mockgithub.serve import build_server  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "github.json"
LEDGER = {"owner": "ExampleCo", "repo": "membership-ledger"}
CALLS: list[tuple[str, dict[str, Any]]] = [
    ("get_me", {}),
    ("issue_read", dict(LEDGER, method="get", issue_number=38)),
    ("issue_read", dict(LEDGER, method="get_comments", issue_number=45)),
    ("list_issues", dict(LEDGER, state="OPEN")),
    ("search_issues", {"query": "is:open label:docs"}),
    ("get_label", dict(LEDGER, name="docs")),
    ("pull_request_read", dict(LEDGER, method="get", pullNumber=39)),
    ("pull_request_read", dict(LEDGER, method="get_files", pullNumber=39)),
    ("list_pull_requests", dict(LEDGER, state="closed")),
    ("search_pull_requests", {"query": "author:jiwon-park"}),
    ("get_file_contents", dict(LEDGER, path="README.md")),
    ("get_file_contents", dict(LEDGER, path="docs/")),
    ("list_commits", dict(LEDGER, perPage=3)),
    ("get_commit", dict(LEDGER, sha="v0.8.0", detail="diff")),
    ("search_code", {"query": "filename:smoke.sh"}),
    ("list_branches", LEDGER),
    ("list_tags", LEDGER),
    ("list_releases", LEDGER),
    ("search_users", {"query": "ExampleCo.example"}),
]


def _http(url: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    request = Request(
        f"{url}/mcp/github",
        data=json.dumps(message).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        answer: dict[str, Any] = json.loads(response.read())["result"]
        return answer


def _cli(url: str, tool: str, arguments: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "MOCKGITHUB_URL": url, "PYTHONPATH": str(PACKAGE_ROOT)}
    argv = [sys.executable, "-m", "mockgithub.client", tool, "--json", json.dumps(arguments)]
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=30, check=False)


def main() -> int:
    engine = Engine(load_scenario(str(FIXTURE)), 7, Journal(None))
    server = build_server(engine, "127.0.0.1", 0, None)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    failures: list[str] = []
    try:
        for tool, arguments in CALLS:
            result = _http(url, tool, arguments)
            text = result["content"][0]["text"]
            if result.get("isError"):
                failures.append(f"http {tool}: {text}")
            completed = _cli(url, tool, arguments)
            if completed.returncode != 0:
                failures.append(f"cli {tool}: exit {completed.returncode} {completed.stderr}")
            elif not completed.stdout.startswith(text):
                failures.append(f"cli {tool}: stdout differs from the http text")
            print(f"ok {tool} {json.dumps(arguments)} -> {len(text)} chars")
        tools = sorted(tool["name"] for tool in engine.tools("github"))
        exercised = sorted({tool for tool, _ in CALLS})
        if tools != exercised:
            failures.append(f"tools not exercised: {sorted(set(tools) - set(exercised))}")
    finally:
        server.shutdown()
        server.server_close()
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"{len(CALLS)} calls over http and cli, {len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
