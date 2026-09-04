from __future__ import annotations

from typing import Any, TextIO

from .cli import main as call_tool
from .http_client import SERVICE
from .stdio import run as serve_stdio


def dispatch(argv: list[str], stdin: Any, stdout: TextIO, stderr: TextIO) -> int:
    arguments = argv[1:] if argv[:1] == [SERVICE] else argv
    if not arguments:
        return serve_stdio(stdin, stdout, stderr)
    return call_tool(arguments, stdout, stderr)
