import io
import json
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from mockgmail.client import http_client
from mockgmail.client.http_client import (
    DEFAULT_URL,
    DaemonUnreachable,
    ServiceUnavailable,
    base_url,
    post_message,
)


class Answer(io.BytesIO):
    def __init__(self, payload: bytes, status: int = 200) -> None:
        super().__init__(payload)
        self.status = status

    def __enter__(self) -> "Answer":
        return self

    def __exit__(self, *unused: Any) -> None:
        self.close()


def test_the_daemon_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOCKGMAIL_URL", raising=False)
    assert base_url() == DEFAULT_URL
    monkeypatch.setenv("MOCKGMAIL_URL", "http://127.0.0.1:9999")
    assert base_url() == "http://127.0.0.1:9999"
    monkeypatch.setenv("MOCKGMAIL_URL", "http://127.0.0.1:9999/")
    assert base_url() == "http://127.0.0.1:9999"


def test_a_message_is_posted_to_the_gmail_endpoint_with_its_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_open(request: Any, timeout: float) -> Answer:
        seen["url"] = request.full_url
        seen["via"] = request.headers["X-mockgmail-via"]
        seen["body"] = json.loads(request.data)
        return Answer(b'{"jsonrpc":"2.0","id":1,"result":{}}')

    monkeypatch.setattr(http_client, "urlopen", fake_open)
    monkeypatch.setenv("MOCKGMAIL_URL", "http://127.0.0.1:4570")
    assert post_message({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "cli") == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {},
    }
    assert seen["url"] == "http://127.0.0.1:4570/mcp/gmail"
    assert seen["via"] == "cli"
    assert seen["body"]["method"] == "ping"


def test_an_accepted_notification_answers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_client, "urlopen", lambda request, timeout: Answer(b"", 202))
    assert post_message({"jsonrpc": "2.0", "method": "notifications/x"}, "mcp") is None


def test_a_daemon_that_refuses_the_connection_is_named_in_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(request: Any, timeout: float) -> Answer:
        raise URLError("connection refused")

    monkeypatch.setattr(http_client, "urlopen", refuse)
    monkeypatch.setenv("MOCKGMAIL_URL", "http://127.0.0.1:4570")
    with pytest.raises(DaemonUnreachable, match="not reachable at http://127.0.0.1:4570"):
        post_message({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "cli")


def test_a_daemon_that_does_not_serve_gmail_is_a_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(request: Any, timeout: float) -> Answer:
        raise HTTPError(
            request.full_url,
            404,
            "Not Found",
            Message(),
            io.BytesIO(b'{"error":"unknown service: gmail"}'),
        )

    monkeypatch.setattr(http_client, "urlopen", missing)
    with pytest.raises(ServiceUnavailable, match="unknown service: gmail"):
        post_message({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "cli")


def test_any_other_http_failure_reads_as_an_unreachable_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(request: Any, timeout: float) -> Answer:
        raise HTTPError(request.full_url, 500, "Server Error", Message(), io.BytesIO(b"{}"))

    monkeypatch.setattr(http_client, "urlopen", broken)
    with pytest.raises(DaemonUnreachable, match="answered 500"):
        post_message({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "cli")
