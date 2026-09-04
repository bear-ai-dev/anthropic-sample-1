import io
import json
import os
from typing import Any, TextIO

import pytest

from mockgithub.client import stdio
from mockgithub.client.http_client import DaemonUnreachable
from mockgithub.client.usage import USAGE


class Recorder:
    def __init__(self, answers: list[Any]) -> None:
        self.answers = list(answers)
        self.sent: list[dict[str, Any]] = []
        self.via: list[str] = []

    def __call__(self, message: dict[str, Any], via: str) -> Any:
        self.sent.append(message)
        self.via.append(via)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _run(
    monkeypatch: pytest.MonkeyPatch, stdin: TextIO, answers: list[Any]
) -> tuple[int, str, str, Recorder]:
    recorder = Recorder(answers)
    monkeypatch.setattr(stdio, "post_message", recorder)
    out, err = io.StringIO(), io.StringIO()
    code = stdio.run(stdin, out, err)
    return code, out.getvalue(), err.getvalue(), recorder


def test_a_terminal_gets_the_usage_text_instead_of_a_hanging_shim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, out, err, recorder = _run(monkeypatch, Terminal(), [])
    assert code == 0
    assert out == USAGE
    assert err == ""
    assert recorder.sent == []


def test_end_of_input_before_any_request_prints_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, _, _ = _run(monkeypatch, io.StringIO(""), [])
    assert code == 0
    assert out == USAGE


def test_silence_before_the_first_request_prints_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(stdio.IDLE_ENV, "0.05")
    read_end, write_end = os.pipe()
    stdin = os.fdopen(read_end, "r", encoding="utf-8")
    try:
        code, out, _, _ = _run(monkeypatch, stdin, [])
    finally:
        os.close(write_end)
        stdin.close()
    assert code == 0
    assert out == USAGE


def test_each_request_line_is_forwarded_and_answered_on_one_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_me"}}
    lines = "\n".join(json.dumps(item) for item in (initialize, notification, call)) + "\n\n"
    answers = [
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}},
        None,
        {"jsonrpc": "2.0", "id": 2, "result": {"content": []}},
    ]
    code, out, err, recorder = _run(monkeypatch, io.StringIO(lines), answers)
    assert code == 0
    assert err == ""
    assert recorder.sent == [initialize, notification, call]
    assert recorder.via == ["mcp", "mcp", "mcp"]
    assert out.splitlines() == [
        '{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}}',
        '{"jsonrpc": "2.0", "id": 2, "result": {"content": []}}',
    ]


def test_a_line_that_is_not_json_is_a_parse_error_and_the_shim_keeps_going(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ping = {"jsonrpc": "2.0", "id": 3, "method": "ping"}
    lines = "{not json\n[1, 2]\n" + json.dumps(ping) + "\n"
    answers = [{"jsonrpc": "2.0", "id": 3, "result": {}}]
    code, out, _, recorder = _run(monkeypatch, io.StringIO(lines), answers)
    assert code == 0
    assert recorder.sent == [ping]
    first, second, third = (json.loads(line) for line in out.splitlines())
    assert first == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "Parse error"},
    }
    assert second["error"] == {"code": -32600, "message": "Invalid Request"}
    assert third == {"jsonrpc": "2.0", "id": 3, "result": {}}


def test_a_daemon_outage_is_reported_as_a_json_rpc_error_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ping = {"jsonrpc": "2.0", "id": 4, "method": "ping"}
    lines = json.dumps(ping) + "\n" + json.dumps(ping) + "\n"
    failure = DaemonUnreachable("mockgithub daemon not reachable at http://127.0.0.1:4570")
    answers = [failure, {"jsonrpc": "2.0", "id": 4, "result": {}}]
    code, out, _, recorder = _run(monkeypatch, io.StringIO(lines), answers)
    assert code == 0
    assert len(recorder.sent) == 2
    first, second = (json.loads(line) for line in out.splitlines())
    assert first == {
        "jsonrpc": "2.0",
        "id": 4,
        "error": {
            "code": -32000,
            "message": "mockgithub daemon not reachable at http://127.0.0.1:4570",
        },
    }
    assert second == {"jsonrpc": "2.0", "id": 4, "result": {}}
