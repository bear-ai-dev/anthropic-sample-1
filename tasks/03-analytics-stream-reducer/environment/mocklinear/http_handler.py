from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qsl, urlparse

from . import jsonrpc
from .admin import ADMIN_PREFIX, handle_admin
from .engine import Engine
from .http_request import Request, Response, json_response
from .tool_errors import InvalidArguments

MCP_PREFIX = "/mcp/"
VIA_HEADER = "x-mocklinear-via"
VERBOSE_ENV = "MOCKLINEAR_VERBOSE"


def _parse_error() -> Response:
    return json_response(jsonrpc.error(None, -32700, "Parse error"))


def _mcp(req: Request, engine: Engine) -> Response:
    service = req.path[len(MCP_PREFIX) :]
    if service not in engine.services():
        return json_response({"error": f"unknown service: {service}"}, 404)
    try:
        message = req.json()
    except InvalidArguments:
        return _parse_error()
    if not isinstance(message, dict):
        return json_response(jsonrpc.error(None, -32600, "Invalid Request"))
    answer = jsonrpc.handle(message, service, engine, req.header(VIA_HEADER, "http"))
    if answer is None:
        return Response(status=202)
    return json_response(answer)


def route(req: Request, engine: Engine, admin_token: str | None) -> Response:
    if req.path.startswith(ADMIN_PREFIX):
        return handle_admin(req, engine, admin_token)
    if req.method in ("GET", "HEAD") and req.path == "/healthz":
        return json_response({"ok": True, "services": engine.services()})
    if req.method == "POST" and req.path.startswith(MCP_PREFIX):
        return _mcp(req, engine)
    return json_response({"error": "not found"}, 404)


def make_handler(engine: Engine, admin_token: str | None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "mocklinear/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            if os.environ.get(VERBOSE_ENV):
                super().log_message(fmt, *args)

        def _read(self) -> Request:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            parsed = urlparse(self.path)
            return Request(
                method=self.command,
                path=parsed.path,
                query=dict(parse_qsl(parsed.query, keep_blank_values=True)),
                headers={key.lower(): value for key, value in self.headers.items()},
                body=body,
            )

        def _dispatch(self) -> None:
            try:
                response = route(self._read(), engine, admin_token)
            except Exception as failure:
                payload = {"error": type(failure).__name__, "message": str(failure)}
                response = json_response(payload, 500)
            self.send_response(response.status)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)

        do_GET = _dispatch
        do_HEAD = _dispatch
        do_POST = _dispatch

    return Handler
