import io
from typing import Any

import pytest

from mockgmail.client import cli
from mockgmail.client.http_client import DaemonUnreachable, ServiceUnavailable


class Recorder:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.sent: list[dict[str, Any]] = []
        self.via: list[str] = []

    def __call__(self, message: dict[str, Any], via: str) -> Any:
        self.sent.append(message)
        self.via.append(via)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _result(text: str, is_error: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        payload["isError"] = True
    return {"jsonrpc": "2.0", "id": 1, "result": payload}


def _run(
    monkeypatch: pytest.MonkeyPatch, answer: Any, argv: list[str]
) -> tuple[int, str, str, Recorder]:
    recorder = Recorder(answer)
    monkeypatch.setattr(cli, "post_message", recorder)
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, out, err)
    return code, out.getvalue(), err.getvalue(), recorder


def test_an_error_result_is_printed_and_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = _result("Error: Requested entity was not found.", is_error=True)
    code, out, err, _ = _run(monkeypatch, answer, ["read_email", "--messageId", "0000000000000000"])
    assert code == 1
    assert out == "Error: Requested entity was not found.\n"
    assert err == ""


def test_a_protocol_error_is_reported_on_standard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Unknown tool: nope"}}
    code, out, err, _ = _run(monkeypatch, answer, ["nope"])
    assert code == 2
    assert out == ""
    assert err == "Unknown tool: nope\n"


def test_the_tool_list_prints_a_name_a_description_and_a_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {
                    "name": "read_email",
                    "description": "Retrieves the content of a specific email",
                    "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
                }
            ]
        },
    }
    code, out, err, recorder = _run(monkeypatch, listing, ["tools"])
    assert code == 0
    assert err == ""
    assert out.startswith("read_email: Retrieves the content of a specific email\n")
    assert '  "type": "object"' in out
    assert recorder.sent[0]["method"] == "tools/list"


def test_a_daemon_that_is_not_running_is_reported_plainly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = DaemonUnreachable("mockgmail daemon not reachable at http://127.0.0.1:4570")
    code, out, err, _ = _run(monkeypatch, failure, ["search_emails"])
    assert code == 2
    assert out == ""
    assert err == "mockgmail daemon not reachable at http://127.0.0.1:4570\n"


def test_a_daemon_without_the_gmail_service_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err, _ = _run(monkeypatch, ServiceUnavailable("unknown service: gmail"), ["tools"])
    assert code == 2
    assert err == "gmail is not available here\n"


def test_an_empty_answer_is_reported_rather_than_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, _, err, _ = _run(monkeypatch, None, ["search_emails"])
    assert code == 2
    assert err == "the daemon answered nothing\n"


def test_every_content_block_is_printed_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
                {"type": "image", "data": "ignored"},
            ]
        },
    }
    code, out, _, _ = _run(monkeypatch, answer, ["search_emails"])
    assert code == 0
    assert out == "first\nsecond\n"


def test_an_embedded_resource_block_is_printed_after_its_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {"type": "text", "text": "downloaded quote.pdf"},
                {"type": "resource", "resource": {"uri": "x://quote.pdf", "text": "# hi"}},
                {"type": "resource"},
            ]
        },
    }
    code, out, _, _ = _run(monkeypatch, answer, ["read_email"])
    assert code == 0
    assert out == "downloaded quote.pdf\n# hi\n\n"
