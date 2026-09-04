import io
import json
import threading
import time
from typing import Any

import pytest

from mockgmail.client import stdio
from mockgmail.client.http_client import DaemonUnreachable

USAGE_MARKER = "gmail tools"


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


class NeverSpeaks:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def isatty(self) -> bool:
        return False

    def __iter__(self) -> Any:
        time.sleep(self.seconds)
        return iter(())


def _answers(answer: Any) -> Any:
    def send(message: dict[str, Any], via: str) -> Any:
        if isinstance(answer, Exception):
            raise answer
        return dict(answer, id=message.get("id"))

    return send


def test_a_terminal_gets_the_usage_instead_of_a_protocol_stream() -> None:
    out = io.StringIO()
    assert stdio.run(Tty(), out, io.StringIO()) == 0
    assert USAGE_MARKER in out.getvalue()


def test_a_request_is_forwarded_and_its_answer_written_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stdio, "post_message", _answers({"jsonrpc": "2.0", "result": {"ok": True}}))
    stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n')
    out = io.StringIO()
    assert stdio.run(stdin, out, io.StringIO()) == 0
    assert json.loads(out.getvalue().strip()) == {"jsonrpc": "2.0", "result": {"ok": True}, "id": 1}


def test_a_notification_leaves_the_stream_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stdio, "post_message", lambda message, via: None)
    stdin = io.StringIO('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    out = io.StringIO()
    assert stdio.run(stdin, out, io.StringIO()) == 0
    assert out.getvalue() == ""


def test_end_of_input_before_the_first_request_prints_the_usage() -> None:
    out = io.StringIO()
    assert stdio.run(io.StringIO(""), out, io.StringIO()) == 0
    assert USAGE_MARKER in out.getvalue()


def test_silence_for_longer_than_the_idle_window_prints_the_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCKGMAIL_STDIO_IDLE_SEC", "0.05")
    out = io.StringIO()
    started = time.time()
    assert stdio.run(NeverSpeaks(2.0), out, io.StringIO()) == 0
    assert time.time() - started < 1.5
    assert USAGE_MARKER in out.getvalue()


def test_a_line_that_is_not_json_is_answered_with_a_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stdio, "post_message", _answers({"jsonrpc": "2.0"}))
    out = io.StringIO()
    assert stdio.run(io.StringIO("{oops\n"), out, io.StringIO()) == 0
    assert json.loads(out.getvalue().strip())["error"]["code"] == -32700


def test_a_daemon_that_is_not_running_is_reported_in_the_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stdio, "post_message", _answers(DaemonUnreachable("no daemon at :4570")))
    out = io.StringIO()
    stdin = io.StringIO('{"jsonrpc":"2.0","id":4,"method":"ping"}\n')
    assert stdio.run(stdin, out, io.StringIO()) == 0
    answer = json.loads(out.getvalue().strip())
    assert answer["id"] == 4
    assert answer["error"] == {"code": -32000, "message": "no daemon at :4570"}


def test_the_reader_stops_at_end_of_input_after_serving(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stdio, "post_message", _answers({"jsonrpc": "2.0", "result": {}}))
    out = io.StringIO()
    stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
    assert stdio.run(stdin, out, io.StringIO()) == 0
    assert USAGE_MARKER not in out.getvalue()
    assert threading.active_count() >= 1


def test_a_json_line_that_is_not_an_object_is_an_invalid_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stdio, "post_message", _answers({"jsonrpc": "2.0"}))
    out = io.StringIO()
    assert stdio.run(io.StringIO("[1, 2]\n"), out, io.StringIO()) == 0
    answer = json.loads(out.getvalue().strip())
    assert answer["error"] == {"code": -32600, "message": "Invalid Request"}
