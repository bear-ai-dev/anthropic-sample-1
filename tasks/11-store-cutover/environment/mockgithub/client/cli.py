from __future__ import annotations

import json
from typing import Any, TextIO

from ..scenario import SERVICE
from .http_client import DaemonUnreachable, ServiceUnavailable, post_message
from .usage import USAGE

VIA = "cli"
USAGE_ERROR = 2
TOOL_ERROR = 1


class UsageError(ValueError):
    pass


def _typed(value: str) -> Any:
    if value in ("true", "false"):
        return value == "true"
    if value.lstrip("-").isdigit():
        return int(value)
    return value


def _json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise UsageError("--json is not a JSON object") from error
    if not isinstance(parsed, dict):
        raise UsageError("--json is not a JSON object")
    return parsed


def parse_arguments(argv: list[str]) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    index = 0
    while index < len(argv):
        flag = argv[index]
        if not flag.startswith("--") or flag == "--":
            raise UsageError(f"expected --name value, got {flag}")
        if index + 1 >= len(argv):
            raise UsageError(f"missing value for {flag}")
        value = argv[index + 1]
        index += 2
        if value == "--":
            if index >= len(argv):
                raise UsageError(f"missing value for {flag}")
            value = argv[index]
            index += 1
        elif value.startswith("-"):
            raise UsageError(f"value for {flag} looks like a flag; put it after --")
        if flag == "--json":
            extra = _json_object(value)
        else:
            arguments[flag[2:]] = _typed(value)
    return dict(arguments, **extra)


def _print_tools(tools: list[dict[str, Any]], stdout: TextIO) -> None:
    for tool in tools:
        stdout.write(f"{tool['name']}: {tool['description']}\n")
        stdout.write(json.dumps(tool.get("inputSchema", {}), indent=2) + "\n\n")


def _print_content(content: list[dict[str, Any]], stdout: TextIO) -> None:
    for block in content:
        if block.get("type") == "text":
            stdout.write(str(block.get("text", "")) + "\n")
        elif block.get("type") == "resource":
            stdout.write(str(block.get("resource", {}).get("text", "")) + "\n")


def _exchange(message: dict[str, Any], stderr: TextIO) -> dict[str, Any] | None:
    try:
        answer = post_message(message, VIA)
    except ServiceUnavailable:
        stderr.write(f"{SERVICE} is not available here\n")
        return None
    except DaemonUnreachable as failure:
        stderr.write(f"{failure}\n")
        return None
    if answer is None:
        stderr.write("the daemon answered nothing\n")
        return None
    if "error" in answer:
        stderr.write(f"{answer['error'].get('message', 'error')}\n")
        return None
    result: dict[str, Any] = answer.get("result", {})
    return result


def main(argv: list[str], stdout: TextIO, stderr: TextIO) -> int:
    words = argv[1:] if argv[:1] == [SERVICE] else list(argv)
    if not words:
        stderr.write(USAGE)
        return USAGE_ERROR
    if words[0] == "tools":
        listed = _exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, stderr)
        if listed is None:
            return USAGE_ERROR
        _print_tools(listed.get("tools", []), stdout)
        return 0
    try:
        arguments = parse_arguments(words[1:])
    except UsageError as error:
        stderr.write(f"{error}\n{USAGE}")
        return USAGE_ERROR
    params = {"name": words[0], "arguments": arguments}
    result = _exchange(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, stderr
    )
    if result is None:
        return USAGE_ERROR
    _print_content(result.get("content", []), stdout)
    return TOOL_ERROR if result.get("isError") else 0
