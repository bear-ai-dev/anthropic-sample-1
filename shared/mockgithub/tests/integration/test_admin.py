import json
from typing import Any
from urllib.error import HTTPError

from mockgithub.tests.integration.conftest import ADMIN_TOKEN, Daemon

HEADERS = {"x-mockgithub-admin-token": ADMIN_TOKEN}


def _post_status(daemon: Daemon, path: str, payload: Any) -> tuple[int, Any]:
    try:
        return 200, daemon.post(path, payload, HEADERS)
    except HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def test_the_admin_plane_refuses_every_wrong_token_identically(daemon: Daemon) -> None:
    missing = daemon.status("/_admin/health")
    wrong = daemon.status("/_admin/health", {"x-mockgithub-admin-token": "guess"})
    assert missing == (403, {"error": "forbidden"})
    assert missing == wrong


def test_a_daemon_with_no_token_configured_refuses_even_the_right_header(
    tokenless_daemon: Daemon,
) -> None:
    assert tokenless_daemon.status("/_admin/health", HEADERS) == (403, {"error": "forbidden"})


def test_health_answers_the_holder_of_the_token(daemon: Daemon) -> None:
    assert daemon.get("/_admin/health", HEADERS) == {"ok": True}


def test_the_snapshot_maps_human_keys_to_identifiers(daemon: Daemon) -> None:
    snapshot = daemon.get("/_admin/snapshot", HEADERS)
    assert snapshot["seed"] == 7
    assert snapshot["clock"] == "2026-03-04T10:00:00Z"
    assert snapshot["services"] == ["github"]
    viewer = daemon.engine.world.github.viewer
    assert snapshot["github"]["users"][viewer.login] == viewer.id


def test_the_call_log_carries_the_journal_and_the_fault_counters(probe_daemon: Daemon) -> None:
    probe_daemon.post(
        "/mcp/probe",
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "echo"}},
    )
    payload = probe_daemon.get("/_admin/calls", HEADERS)
    assert [call["tool"] for call in payload["calls"]] == ["echo"]
    assert payload["fault_counters"] == {"probe:echo": 1}


def test_reseeding_swaps_the_world_and_clears_the_journal(daemon: Daemon) -> None:
    before = daemon.get("/_admin/snapshot", HEADERS)["github"]["users"]["rhea-menon"]
    scenario = {"version": 1, "clock": "2026-05-01T00:00:00Z"}
    assert daemon.post("/_admin/reseed", {"scenario": scenario, "seed": 41}, HEADERS) == {
        "ok": True
    }
    after = daemon.get("/_admin/snapshot", HEADERS)
    assert after["seed"] == 41
    assert after["clock"] == "2026-05-01T00:00:00Z"
    assert after["github"]["users"] == {}
    assert before
    assert daemon.get("/_admin/calls", HEADERS)["calls"] == []


def test_reseeding_with_a_broken_scenario_is_refused(daemon: Daemon) -> None:
    code, payload = _post_status(
        daemon, "/_admin/reseed", {"scenario": {"version": 9, "clock": "2026-05-01T00:00:00Z"}}
    )
    assert code == 400
    assert payload == {"error": "unsupported scenario version: 9"}


def test_faults_can_be_switched_off_by_the_verifier(daemon: Daemon) -> None:
    assert daemon.engine.injector.enabled
    assert daemon.post("/_admin/faults", {"enabled": False}, HEADERS) == {"ok": True}
    assert not daemon.engine.injector.enabled
    assert daemon.post("/_admin/faults", {}, HEADERS) == {"ok": True}
    assert daemon.engine.injector.enabled


def test_an_unknown_admin_route_is_a_not_found(daemon: Daemon) -> None:
    assert daemon.status("/_admin/nope", HEADERS) == (404, {"error": "unknown admin route"})
    assert _post_status(daemon, "/_admin/health", {}) == (404, {"error": "unknown admin route"})
