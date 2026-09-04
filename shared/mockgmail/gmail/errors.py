from __future__ import annotations

from ..tool_result import ToolResult, text_result


class GmailErrors:
    def rate_limited(self, tool: str) -> ToolResult:
        return text_result("Error: Rate Limit Exceeded")

    def server_error(self, tool: str) -> ToolResult:
        return text_result("Error: Backend Error")

    def invalid_arguments(self, tool: str, message: str) -> ToolResult:
        return text_result(f"Error: {message}")

    def not_found(self, tool: str, kind: str, key: str) -> ToolResult:
        return text_result("Error: Requested entity was not found.")


ERRORS = GmailErrors()
