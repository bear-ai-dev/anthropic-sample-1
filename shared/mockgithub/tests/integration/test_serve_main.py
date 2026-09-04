import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from mockgithub import serve
from mockgithub.engine import Engine

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "github.json"


def test_the_command_line_starts_a_daemon_that_reads_its_token_and_journal_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    started: list[tuple[ThreadingHTTPServer, Engine]] = []
    build = serve.build_server

    def spy(engine: Engine, host: str, port: int, token: str | None) -> ThreadingHTTPServer:
        server = build(engine, host, port, token)
        started.append((server, engine))
        return server

    monkeypatch.setattr(serve, "build_server", spy)
    monkeypatch.setenv("MOCKGITHUB_ADMIN_TOKEN", "cli-token")
    monkeypatch.setenv("MOCKGITHUB_JOURNAL", str(tmp_path / "calls.jsonl"))
    exits: list[int] = []
    argv = ["--scenario", str(FIXTURE), "--host", "127.0.0.1", "--port", "0", "--seed", "41"]
    thread = threading.Thread(target=lambda: exits.append(serve.main(argv)), daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not started and time.time() < deadline:
        time.sleep(0.01)
    server, engine = started[0]
    port = server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/healthz") as response:
            assert json.load(response) == {"ok": True, "services": ["github"]}
        admin = Request(
            f"http://127.0.0.1:{port}/_admin/health",
            headers={"x-mockgithub-admin-token": "cli-token"},
        )
        with urlopen(admin) as response:
            assert json.load(response) == {"ok": True}
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
    assert exits == [0]
    assert engine.world.seed == 41
    assert engine.journal.sink_path == str(tmp_path / "calls.jsonl")
    assert f"mockgithub listening on http://127.0.0.1:{port}" in capsys.readouterr().out
