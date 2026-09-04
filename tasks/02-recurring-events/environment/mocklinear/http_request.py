from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .tool_errors import InvalidArguments


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        if not self.body:
            return {}
        try:
            return json.loads(self.body.decode("utf-8", "replace"))
        except json.JSONDecodeError as error:
            raise InvalidArguments("body is not valid JSON") from error

    def header(self, name: str, default: str = "") -> str:
        target = name.lower()
        for key, value in self.headers.items():
            if key.lower() == target:
                return value
        return default


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


def json_response(payload: Any, status: int = 200) -> Response:
    body = json.dumps(payload, separators=(",", ":")).encode()
    return Response(status=status, body=body, headers={"Content-Type": "application/json"})
