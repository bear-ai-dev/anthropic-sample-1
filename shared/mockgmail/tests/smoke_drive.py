from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

SHARED = Path(__file__).resolve().parents[2]
MISSING = "Error: Requested entity was not found."
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


def call(endpoint: str, tool: str, arguments: dict[str, Any]) -> str:
    answer = post(
        endpoint,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    )
    text: str = answer["result"]["content"][0]["text"]
    return text


def run_cli(url: str, cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(SHARED),
        "MOCKGMAIL_URL": url,
    }
    return subprocess.run(
        [sys.executable, "-m", "mockgmail.client", *arguments],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
        cwd=cwd,
    )


def first_id(listing: str) -> str:
    return listing.split("\n", 1)[0].removeprefix("ID: ")


def drive_http(base: str, workdir: Path) -> tuple[str, str]:
    print("\nMCP over HTTP")
    endpoint = f"{base}/mcp/gmail"
    handshake = post(endpoint, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    check("initialize names the server", handshake["result"]["serverInfo"]["name"] == "gmail")
    listed = post(endpoint, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = sorted(tool["name"] for tool in listed["result"]["tools"])
    check(
        "tools/list carries the four read tools",
        names == ["download_attachment", "list_email_labels", "read_email", "search_emails"],
        names,
    )
    found = call(endpoint, "search_emails", {"query": "filename:invoice-5120.pdf"})
    check("search_emails finds the mail carrying the invoice", found.startswith("ID: "), found)
    message_id = first_id(found)
    email = call(endpoint, "read_email", {"messageId": message_id})
    check("read_email renders the thread header", email.startswith("Thread ID: "), email[:40])
    check("read_email lists the attachment", "Attachments (1):" in email, email[-120:])
    attachment_id = email.rsplit("ID: ", 1)[1].rstrip(")")
    labels = call(endpoint, "list_email_labels", {})
    check("list_email_labels counts the labels", labels.startswith("Found 11 labels"), labels[:40])
    payload = json.loads(
        call(
            endpoint,
            "download_attachment",
            {"messageId": message_id, "attachmentId": attachment_id},
        )
    )
    check(
        "download_attachment hands the client a marked payload",
        payload["mockgmail_attachment"]["filename"] == "invoice-5120.pdf",
        payload,
    )
    check(
        "an unknown message is the vendor text",
        call(endpoint, "read_email", {"messageId": "x"}) == MISSING,
    )
    check(
        "no matches say so",
        call(endpoint, "search_emails", {"query": "from:nobody"}).startswith("No emails"),
    )
    return message_id, attachment_id


def drive_cli(base: str, workdir: Path, message_id: str, attachment_id: str) -> None:
    print("\nCLI")
    listing = run_cli(base, workdir, "tools")
    check("tools lists the surface", "search_emails:" in listing.stdout, listing.stderr)
    found = run_cli(base, workdir, "search_emails", "--query", "is:unread", "--maxResults", "3")
    check(
        "search_emails answers the unread mail",
        found.returncode == 0 and found.stdout.count("ID: ") == 3,
        found.stderr or found.stdout,
    )
    email = run_cli(base, workdir, "read_email", "--messageId", message_id)
    check("read_email prints the mail", email.stdout.startswith("Thread ID: "), email.stderr)
    labels = run_cli(base, workdir, "list_email_labels")
    check("list_email_labels prints the labels", "User Labels:" in labels.stdout, labels.stderr)
    saved = run_cli(
        base,
        workdir,
        "download_attachment",
        "--messageId",
        message_id,
        "--attachmentId",
        attachment_id,
    )
    target = workdir / "invoice-5120.pdf"
    check(
        "download_attachment writes the file where the command runs",
        saved.stdout.startswith("Attachment downloaded successfully")
        and target.stat().st_size == 88214,
        saved.stdout or saved.stderr,
    )
    failed = run_cli(base, workdir, "read_email", "--messageId", "nope")
    check(
        "a missing mail is the vendor text on stdout with exit 1",
        failed.returncode == 1 and failed.stdout.strip() == MISSING,
        (failed.returncode, failed.stdout),
    )
    refused = run_cli(base, workdir, "search_emails", "--query", "-in:sent")
    check("a dash-leading value is refused", refused.returncode == 2, refused.returncode)
