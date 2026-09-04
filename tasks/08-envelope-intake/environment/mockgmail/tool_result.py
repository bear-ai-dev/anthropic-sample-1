from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    content: tuple[dict[str, Any], ...]
    is_error: bool = False
    page: dict[str, Any] | None = None


def text_result(
    text: str, *, is_error: bool = False, page: dict[str, Any] | None = None
) -> ToolResult:
    return ToolResult(content=({"type": "text", "text": text},), is_error=is_error, page=page)


def json_result(payload: Any, *, page: dict[str, Any] | None = None) -> ToolResult:
    return text_result(json.dumps(payload, indent=2), page=page)


def result_chars(result: ToolResult) -> int:
    return sum(len(block.get("text", "")) for block in result.content)
