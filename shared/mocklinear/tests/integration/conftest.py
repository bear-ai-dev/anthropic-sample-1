import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from mocklinear.engine import Engine
from mocklinear.journal import Journal
from mocklinear.registry import ServiceRegistry, build_registries
from mocklinear.scenario import validate_scenario
from mocklinear.serve import build_server
from mocklinear.tests.probe import registries

ADMIN_TOKEN = "integration-token"


@dataclass
class Daemon:
    url: str
    engine: Engine
    server: ThreadingHTTPServer
    journal_path: Path

    def post(self, path: str, payload: Any, headers: dict[str, str] | None = None) -> Any:
        body = json.dumps(payload).encode()
        request = Request(
            f"{self.url}{path}",
            data=body,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        return self._read(request)

    def get(self, path: str, headers: dict[str, str] | None = None) -> Any:
        return self._read(Request(f"{self.url}{path}", headers=headers or {}))

    def status(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, Any]:
        try:
            return 200, self.get(path, headers)
        except HTTPError as error:
            return error.code, json.loads(error.read() or b"null")

    def _read(self, request: Request) -> Any:
        with urlopen(request) as response:
            raw = response.read()
            return json.loads(raw) if raw else None


def _serve(
    scenario: dict[str, Any],
    tmp_path: Path,
    services: dict[str, ServiceRegistry],
    token: str | None = ADMIN_TOKEN,
) -> Iterator[Daemon]:
    journal_path = tmp_path / "calls.jsonl"
    engine = Engine(validate_scenario(scenario), 7, Journal(str(journal_path)), services)
    server = build_server(engine, "127.0.0.1", 0, token)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    port = server.server_address[1]
    try:
        yield Daemon(f"http://127.0.0.1:{port}", engine, server, journal_path)
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def daemon(scenario: dict[str, Any], tmp_path: Path) -> Iterator[Daemon]:
    yield from _serve(scenario, tmp_path, build_registries())


@pytest.fixture
def probe_daemon(scenario: dict[str, Any], tmp_path: Path) -> Iterator[Daemon]:
    yield from _serve(scenario, tmp_path, registries())


@pytest.fixture
def tokenless_daemon(scenario: dict[str, Any], tmp_path: Path) -> Iterator[Daemon]:
    yield from _serve(scenario, tmp_path, build_registries(), None)
