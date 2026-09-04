from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SHARED = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SHARED))

from mocklinear.engine import Engine  # noqa: E402
from mocklinear.journal import Journal  # noqa: E402
from mocklinear.scenario import load_scenario  # noqa: E402
from mocklinear.serve import build_server  # noqa: E402

SCENARIO = Path(__file__).parent / "fixtures" / "linear.json"
TOKEN = "smoke-token"
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: Any = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        FAILURES.append(f"{label}: {detail}")
        print(f"  FAIL {label} {detail}")


def post(url: str, message: dict[str, Any]) -> Any:
    request = Request(
        url, data=json.dumps(message).encode(), headers={"Content-Type": "application/json"}
    )
    with urlopen(request, timeout=30) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def get(url: str, headers: dict[str, str] | None = None) -> Any:
    with urlopen(Request(url, headers=headers or {}), timeout=30) as response:
        return json.loads(response.read())


def run_cli(url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
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


def drive_http(base: str) -> None:
    print("\nMCP over HTTP")
    endpoint = f"{base}/mcp/linear"
    handshake = post(endpoint, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    check(
        "initialize names the server",
        handshake["result"]["serverInfo"]["name"] == "linear",
        handshake,
    )
    listed = post(endpoint, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [tool["name"] for tool in listed["result"]["tools"]]
    check("tools/list carries twenty tools", len(names) == 20, names)
    called = post(
        endpoint,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_issue", "arguments": {"id": "WEB-611"}},
        },
    )
    issue = json.loads(called["result"]["content"][0]["text"])
    check("get_issue answers the issue", issue["identifier"] == "WEB-611", issue.get("identifier"))
    check("the issue carries its branch", issue["branchName"].startswith("dana/"), issue)
    missing = post(
        endpoint,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_issue", "arguments": {"id": "WEB-999"}},
        },
    )
    check(
        "an unknown issue is a vendor-shaped error",
        missing["result"]["isError"]
        and missing["result"]["content"][0]["text"]
        == "Entity not found: Issue - Could not find referenced Issue.",
        missing["result"],
    )


def drive_cli(base: str) -> None:
    print("\nCLI")
    listing = run_cli(base, "tools")
    check("tools lists the surface", "list_issues:" in listing.stdout, listing.stderr)
    called = run_cli(base, "list_issues", "--assignee", "me", "--limit", "2")
    payload = json.loads(called.stdout or "{}")
    check(
        "list_issues answers the viewer's issues",
        called.returncode == 0 and len(payload.get("issues", [])) == 2,
        called.stderr,
    )
    failed = run_cli(base, "get_issue", "--id", "WEB-999")
    check("a missing issue exits one", failed.returncode == 1, failed.returncode)
    refused = run_cli(base, "list_issues", "--updatedAt", "-P1W")
    check("a dash-leading value is refused", refused.returncode == 2, refused.returncode)


def drive_admin(base: str) -> None:
    print("\nAdmin plane")
    check("healthz is open", get(f"{base}/healthz") == {"ok": True, "services": ["linear"]})
    snapshot = get(f"{base}/_admin/snapshot", {"x-mocklinear-admin-token": TOKEN})
    identifier = snapshot["linear"]["issues"]["WEB-611"]
    check(
        "the snapshot maps a human key to an opaque id",
        len(identifier) == 36 and identifier.count("-") == 4,
        identifier,
    )
    calls = get(f"{base}/_admin/calls", {"x-mocklinear-admin-token": TOKEN})
    vias = sorted({call["via"] for call in calls["calls"]})
    check("the journal saw both transports", vias == ["cli", "http"], vias)
    try:
        get(f"{base}/_admin/snapshot")
        check("the admin plane refuses an unauthenticated read", False, "no error raised")
    except HTTPError as error:
        check("the admin plane refuses an unauthenticated read", error.code == 403, error.code)


def main() -> int:
    engine = Engine(load_scenario(str(SCENARIO)), 7, Journal(None))
    server = build_server(engine, "127.0.0.1", 0, TOKEN)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"mocklinear on {base}")
    try:
        drive_http(base)
        drive_cli(base)
        drive_admin(base)
    finally:
        server.shutdown()
        server.server_close()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("all smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
