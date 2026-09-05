from __future__ import annotations


class ToolError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(ToolError):
    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"{kind} not found: {key}")
        self.kind = kind
        self.key = key


class InvalidArguments(ToolError):
    pass


class Throttled(ToolError):
    pass


class TransientServerError(ToolError):
    pass
