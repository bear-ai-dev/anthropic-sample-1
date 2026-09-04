from __future__ import annotations

import json
import os
import threading
from queue import Empty, Queue
from typing import Any, TextIO

from .http_client import DaemonUnreachable, ServiceUnavailable, post_message
from .usage import USAGE

IDLE_ENV = "MOCKLINEAR_STDIO_IDLE_SEC"
DEFAULT_IDLE_SECONDS = 10.0


def _error(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _read_lines(stdin: TextIO, lines: Queue[str | None]) -> None:
    for line in stdin:
        lines.put(line)
    lines.put(None)


def _answer(line: str) -> dict[str, Any] | None:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return _error(None, -32700, "Parse error")
    try:
        reply: dict[str, Any] | None = post_message(message, "mcp")
    except (DaemonUnreachable, ServiceUnavailable) as failure:
        return _error(message.get("id"), -32000, str(failure))
    return reply


def run(stdin: Any, stdout: TextIO, stderr: TextIO) -> int:
    if stdin.isatty():
        stdout.write(USAGE)
        return 0
    lines: Queue[str | None] = Queue()
    threading.Thread(target=_read_lines, args=(stdin, lines), daemon=True).start()
    idle = float(os.environ.get(IDLE_ENV, DEFAULT_IDLE_SECONDS))
    served = False
    while True:
        try:
            line = lines.get() if served else lines.get(timeout=idle)
        except Empty:
            stdout.write(USAGE)
            return 0
        if line is None:
            if not served:
                stdout.write(USAGE)
            return 0
        if not line.strip():
            continue
        served = True
        reply = _answer(line)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
