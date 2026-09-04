from __future__ import annotations

import json
import os
import queue
import threading
from typing import Any, TextIO

from .http_client import DaemonUnreachable, ServiceUnavailable, post_message
from .usage import USAGE

IDLE_SECONDS_ENV = "MOCKGITHUB_STDIO_IDLE_SEC"
DEFAULT_IDLE_SECONDS = 10.0
VIA = "mcp"


def _error(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _answer(line: str) -> dict[str, Any] | None:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return _error(None, -32700, "Parse error")
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid Request")
    try:
        return post_message(message, VIA)
    except (DaemonUnreachable, ServiceUnavailable) as failure:
        return _error(message.get("id"), -32000, str(failure))


def _reader(stdin: TextIO, lines: queue.Queue[str | None]) -> None:
    for line in stdin:
        lines.put(line)
    lines.put(None)


def _first_line(stdin: TextIO, lines: queue.Queue[str | None]) -> str | None:
    threading.Thread(target=_reader, args=(stdin, lines), daemon=True).start()
    idle = float(os.environ.get(IDLE_SECONDS_ENV) or DEFAULT_IDLE_SECONDS)
    try:
        return lines.get(timeout=idle)
    except queue.Empty:
        return None


def run(stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    if stdin.isatty():
        stdout.write(USAGE)
        stdout.flush()
        return 0
    lines: queue.Queue[str | None] = queue.Queue()
    line = _first_line(stdin, lines)
    if line is None:
        stdout.write(USAGE)
        stdout.flush()
        return 0
    while line is not None:
        if line.strip():
            answer = _answer(line)
            if answer is not None:
                stdout.write(json.dumps(answer) + "\n")
                stdout.flush()
        line = lines.get()
    return 0
