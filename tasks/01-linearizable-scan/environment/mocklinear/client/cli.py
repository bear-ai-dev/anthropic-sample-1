from __future__ import annotations

import json
from typing import Any, TextIO

from .http_client import SERVICE, DaemonUnreachable, ServiceUnavailable, post_message


class UsageError(ValueError):
    pass


def _typed(value: str) -> Any:
    if value in ("true", "false"):
        return value == "true"
    try:
        return int(value)
    except ValueError:
        return value


def _value(argv: list[str], index: int, name: str) -> tuple[Any, int]:
    if index >= len(argv):
        raise UsageError(f"missing value for --{name}")
    if argv[index] == "--":
        if index + 1 >= len(argv):
            raise UsageError(f"missing value for --{name}")
        return _typed(argv[index + 1]), index + 2
    if argv[index].startswith("-"):
        raise UsageError(f"value for --{name} looks like a flag; put it after --")
    return _typed(argv[index]), index + 1


def parse_arguments(argv: list[str]) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    merged: dict[str, Any] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if not token.startswith("--") or token == "--":
            raise UsageError(f"expected --name value, got {token}")
        name = token[2:]
        value, index = _value(argv, index + 1, name)
        if name == "json":
            merged = _json_object(value)
        else:
            arguments[name] = value
    return {**arguments, **merged}


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as error:
        raise UsageError("--json is not a JSON object") from error
    if not isinstance(parsed, dict):
        raise UsageError("--json is not a JSON object")
    return parsed


def _print_tools(payload: dict[str, Any], stdout: TextIO) -> None:
    for tool in payload.get("tools", []):
        stdout.write(f"{tool['name']}: {tool['description']}\n")
        schema = json.dumps(tool["inputSchema"], indent=2)
        stdout.write("\n".join(f"  {line}" for line in schema.splitlines()) + "\n\n")


def _message(argv: list[str]) -> dict[str, Any]:
    if argv[0] == "tools":
        return {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": argv[0], "arguments": parse_arguments(argv[1:])},
    }


def main(argv: list[str], stdout: TextIO, stderr: TextIO) -> int:
    try:
        message = _message(argv)
        answer = post_message(message, "cli")
    except UsageError as error:
        stderr.write(f"{error}\n")
        return 2
    except ServiceUnavailable:
        stderr.write(f"{SERVICE} is not available here\n")
        return 2
    except DaemonUnreachable as error:
        stderr.write(f"{error}\n")
        return 2
    if not isinstance(answer, dict):
        stderr.write("the daemon answered nothing\n")
        return 2
    if "error" in answer:
        stderr.write(f"{answer['error']['message']}\n")
        return 2
    result = answer["result"]
    if argv[0] == "tools":
        _print_tools(result, stdout)
        return 0
    for block in result.get("content", []):
        if block.get("type") == "text":
            stdout.write(f"{block['text']}\n")
    return 1 if result.get("isError") else 0
