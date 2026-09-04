import io
import json
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from mockgithub.client import http_client
from mockgithub.client.http_client import (
    DEFAULT_URL,
    DaemonUnreachable,
    ServiceUnavailable,
    base_url,
    post_message,
)


class Response(io.BytesIO):
    def __init__(self, payload: bytes, status: int = 200) -> None:
        super().__init__(payload)
        self.status = status

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_the_daemon_address_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(http_client.URL_ENV, raising=False)
    assert base_url() == DEFAULT_URL == "http://127.0.0.1:4570"
    monkeypatch.setenv(http_client.URL_ENV, "http://127.0.0.1:9999/")
    assert base_url() == "http://127.0.0.1:9999"


def test_a_message_is_posted_to_the_github_endpoint_with_its_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []

    def fake_urlopen(request: Any, timeout: float) -> Response:
        seen.append((request, timeout))
        return Response(b'{"jsonrpc": "2.0", "id": 1, "result": {}}')

    monkeypatch.setattr(http_client, "urlopen", fake_urlopen)
    monkeypatch.setenv(http_client.URL_ENV, "http://127.0.0.1:4570")
    answer = post_message({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "cli")
    assert answer == {"jsonrpc": "2.0", "id": 1, "result": {}}
    request, timeout = seen[0]
    assert request.full_url == "http://127.0.0.1:4570/mcp/github"
    assert request.get_header("X-mockgithub-via") == "cli"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert timeout == 30.0


def test_an_accepted_notification_answers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_client, "urlopen", lambda request, timeout: Response(b"", 202))
    assert post_message({"jsonrpc": "2.0", "method": "notifications/initialized"}, "mcp") is None


def test_a_daemon_that_is_down_is_a_plain_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: Any, timeout: float) -> Response:
        raise URLError("connection refused")

    monkeypatch.setattr(http_client, "urlopen", refuse)
    monkeypatch.setenv(http_client.URL_ENV, "http://127.0.0.1:4570")
    with pytest.raises(DaemonUnreachable, match="not reachable at http://127.0.0.1:4570"):
        post_message({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "cli")


def test_a_daemon_without_the_service_raises_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(request: Any, timeout: float) -> Response:
        body = io.BytesIO(b'{"error": "unknown service: github"}')
        raise HTTPError(request.full_url, 404, "Not Found", {}, body)  # type: ignore[arg-type]

    monkeypatch.setattr(http_client, "urlopen", missing)
    with pytest.raises(ServiceUnavailable, match="unknown service: github"):
        post_message({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "cli")


def test_any_other_http_failure_carries_its_status_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def crash(request: Any, timeout: float) -> Response:
        body = io.BytesIO(b'{"error": "TypeError"}')
        raise HTTPError(request.full_url, 500, "Server Error", {}, body)  # type: ignore[arg-type]

    monkeypatch.setattr(http_client, "urlopen", crash)
    with pytest.raises(DaemonUnreachable, match="mcp/github answered 500: TypeError"):
        post_message({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "cli")
