from __future__ import annotations

from typing import Any

from .engine import Engine
from .http_request import Request, Response, json_response
from .scenario import ScenarioError, validate_scenario

ADMIN_PREFIX = "/_admin/"
ADMIN_HEADER = "x-mockgithub-admin-token"
ADMIN_TOKEN_ENV = "MOCKGITHUB_ADMIN_TOKEN"


def _reseed(req: Request, engine: Engine) -> Response:
    payload: dict[str, Any] = req.json()
    try:
        scenario = validate_scenario(payload.get("scenario", {}))
    except ScenarioError as error:
        return json_response({"error": str(error)}, 400)
    engine.reseed(scenario, payload.get("seed"))
    return json_response({"ok": True})


def _faults(req: Request, engine: Engine) -> Response:
    payload: dict[str, Any] = req.json()
    engine.injector.enabled = bool(payload.get("enabled", True))
    return json_response({"ok": True})


def handle_admin(req: Request, engine: Engine, expected_token: str | None) -> Response:
    if not expected_token or req.header(ADMIN_HEADER) != expected_token:
        return json_response({"error": "forbidden"}, 403)
    route = req.path[len(ADMIN_PREFIX) :]
    if req.method == "GET" and route == "health":
        return json_response({"ok": True})
    if req.method == "GET" and route == "snapshot":
        return json_response(engine.world.snapshot())
    if req.method == "GET" and route == "calls":
        return json_response(
            {"calls": engine.journal.records(), "fault_counters": engine.injector.stats()}
        )
    if req.method == "POST" and route == "reseed":
        return _reseed(req, engine)
    if req.method == "POST" and route == "faults":
        return _faults(req, engine)
    return json_response({"error": "unknown admin route"}, 404)
