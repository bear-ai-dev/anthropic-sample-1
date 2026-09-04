from __future__ import annotations

from typing import Any

from . import __version__
from .engine import Engine, UnknownService, UnknownTool

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def error(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _result(id_: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": payload}


def _initialize(params: dict[str, Any], service: str) -> dict[str, Any]:
    wanted = params.get("protocolVersion")
    version = wanted if wanted in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
        "serverInfo": {"name": service, "version": __version__},
    }


def _tools_call(
    params: dict[str, Any], id_: Any, service: str, engine: Engine, via: str
) -> dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str):
        return error(id_, -32602, "Invalid params: missing tool name")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return error(id_, -32602, "Invalid params: arguments")
    outcome = engine.call(service, name, arguments, via)
    payload: dict[str, Any] = {"content": [dict(block) for block in outcome.content]}
    if outcome.is_error:
        payload["isError"] = True
    return _result(id_, payload)


def _dispatch(
    method: str, params: dict[str, Any], id_: Any, service: str, engine: Engine, via: str
) -> dict[str, Any]:
    if method == "initialize":
        return _result(id_, _initialize(params, service))
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": engine.tools(service)})
    if method == "tools/call":
        return _tools_call(params, id_, service, engine, via)
    if method == "prompts/list":
        return _result(id_, {"prompts": []})
    if method == "resources/list":
        return _result(id_, {"resources": []})
    return error(id_, -32601, f"Method not found: {method}")


def handle(
    message: dict[str, Any], service: str, engine: Engine, via: str
) -> dict[str, Any] | None:
    id_ = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        return error(id_, -32600, "Invalid Request")
    if method.startswith("notifications/"):
        return None
    params = message.get("params", {})
    if not isinstance(params, dict):
        return error(id_, -32602, "Invalid params")
    try:
        return _dispatch(method, params, id_, service, engine, via)
    except UnknownTool as unknown:
        return error(id_, -32602, f"Unknown tool: {unknown.args[0]}")
    except UnknownService as unknown:
        return error(id_, -32602, f"Unknown service: {unknown.args[0]}")
