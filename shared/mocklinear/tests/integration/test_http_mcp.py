import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mocklinear.registry import build_registries
from mocklinear.tests.integration.conftest import Daemon


def _rpc(daemon: Daemon, method: str, params: Any = None, id_: Any = 1) -> Any:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        message["params"] = params
    return daemon.post("/mcp/probe", message)


def test_the_health_check_is_open_and_names_the_service(daemon: Daemon) -> None:
    assert daemon.get("/healthz") == {"ok": True, "services": ["linear"]}


def test_a_service_the_daemon_does_not_serve_is_a_not_found(daemon: Daemon) -> None:
    try:
        daemon.post("/mcp/github", {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        raise AssertionError("expected a 404")
    except HTTPError as error:
        assert error.code == 404
        assert json.loads(error.read()) == {"error": "unknown service: github"}


def test_a_client_can_initialise_list_and_call_over_http(probe_daemon: Daemon) -> None:
    handshake = _rpc(probe_daemon, "initialize", {"protocolVersion": "2025-06-18"})
    assert handshake["result"]["serverInfo"]["name"] == "probe"
    listed = _rpc(probe_daemon, "tools/list")
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["bad", "boom", "echo", "paged"]
    called = _rpc(probe_daemon, "tools/call", {"name": "echo", "arguments": {"id": "WEB-611"}})
    assert json.loads(called["result"]["content"][0]["text"])["id"] == "WEB-611"


def test_a_notification_is_answered_with_an_empty_accepted(probe_daemon: Daemon) -> None:
    request = Request(
        f"{probe_daemon.url}/mcp/probe",
        data=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request) as response:
        assert response.status == 202
        assert response.read() == b""


def test_a_body_that_is_not_json_is_a_parse_error(probe_daemon: Daemon) -> None:
    request = Request(
        f"{probe_daemon.url}/mcp/probe",
        data=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request) as response:
        assert json.loads(response.read())["error"]["code"] == -32700


def test_a_message_that_is_not_an_object_is_an_invalid_request(probe_daemon: Daemon) -> None:
    assert probe_daemon.post("/mcp/probe", [1, 2])["error"]["code"] == -32600


def test_the_transport_records_how_the_call_arrived(probe_daemon: Daemon) -> None:
    _rpc(probe_daemon, "tools/call", {"name": "echo", "arguments": {}})
    probe_daemon.post(
        "/mcp/probe",
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "echo"}},
        {"x-mocklinear-via": "mcp"},
    )
    assert [entry["via"] for entry in probe_daemon.engine.journal.records()] == ["http", "mcp"]


def test_every_call_is_appended_to_the_journal_sink(probe_daemon: Daemon) -> None:
    _rpc(probe_daemon, "tools/call", {"name": "echo", "arguments": {"id": "WEB-611"}})
    lines = probe_daemon.journal_path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["tool"] == "echo"
    assert json.loads(lines[0])["outcome"] == "ok"


def test_an_unknown_path_is_a_not_found(daemon: Daemon) -> None:
    assert daemon.status("/nope") == (404, {"error": "not found"})


def test_a_head_request_answers_without_a_body(daemon: Daemon) -> None:
    request = Request(f"{daemon.url}/healthz", method="HEAD")
    with urlopen(request) as response:
        assert response.status == 200
        assert response.read() == b""


def test_a_handler_failure_is_a_five_hundred_and_the_daemon_keeps_serving(
    daemon: Daemon,
) -> None:
    daemon.engine.registries = None  # type: ignore[assignment]
    code, payload = daemon.status("/healthz")
    assert code == 500
    assert payload == {"error": "TypeError", "message": "'NoneType' object is not iterable"}
    daemon.engine.registries = build_registries()
    assert daemon.get("/healthz")["ok"] is True
