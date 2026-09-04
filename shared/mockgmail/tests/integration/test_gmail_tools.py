import json
from typing import Any

from mockgmail.tests.integration.conftest import Daemon


def _call(daemon: Daemon, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    answer = daemon.post(
        "/mcp/gmail",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    )
    result: dict[str, Any] = answer["result"]
    return result


def test_every_gmail_tool_answers_over_http(daemon: Daemon) -> None:
    listed = daemon.post("/mcp/gmail", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [tool["name"] for tool in listed["result"]["tools"]] == [
        "download_attachment",
        "list_email_labels",
        "read_email",
        "search_emails",
    ]
    found = _call(daemon, "search_emails", {"query": "filename:invoice-5120.pdf"})
    message_id = found["content"][0]["text"].split("\n")[0].removeprefix("ID: ")
    read = _call(daemon, "read_email", {"messageId": message_id})["content"][0]["text"]
    assert read.startswith("Thread ID: ")
    attachment_id = read.rsplit("ID: ", 1)[1].rstrip(")")
    labels = _call(daemon, "list_email_labels", {})["content"][0]["text"]
    assert labels.startswith("Found 11 labels (8 system, 3 user):")
    downloaded = _call(
        daemon, "download_attachment", {"messageId": message_id, "attachmentId": attachment_id}
    )
    payload = json.loads(downloaded["content"][0]["text"])["mockgmail_attachment"]
    assert payload["filename"] == "invoice-5120.pdf"
    assert [entry["tool"] for entry in daemon.engine.journal.records()] == [
        "search_emails",
        "read_email",
        "list_email_labels",
        "download_attachment",
    ]


def test_a_gmail_error_travels_as_plain_text_without_the_error_flag(daemon: Daemon) -> None:
    result = _call(daemon, "read_email", {"messageId": "nope"})
    assert result == {
        "content": [{"type": "text", "text": "Error: Requested entity was not found."}]
    }
