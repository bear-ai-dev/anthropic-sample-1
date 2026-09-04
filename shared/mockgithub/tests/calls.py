import json
from typing import Any

from mockgithub.engine import Engine
from mockgithub.tool_result import ToolResult


def call(engine: Engine, tool: str, args: dict[str, Any] | None = None) -> ToolResult:
    return engine.call("github", tool, args or {}, "cli")


def call_json(engine: Engine, tool: str, args: dict[str, Any] | None = None) -> Any:
    result = call(engine, tool, args)
    assert not result.is_error, result.content[0]["text"]
    return json.loads(result.content[0]["text"])


def call_text(engine: Engine, tool: str, args: dict[str, Any] | None = None) -> str:
    result = call(engine, tool, args)
    text: str = result.content[0]["text"]
    return text


def call_error(engine: Engine, tool: str, args: dict[str, Any] | None = None) -> str:
    result = call(engine, tool, args)
    assert result.is_error
    text: str = result.content[0]["text"]
    return text
