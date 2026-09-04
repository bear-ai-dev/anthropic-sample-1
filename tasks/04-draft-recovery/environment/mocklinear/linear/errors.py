from __future__ import annotations

from ..tool_result import ToolResult, text_result


class LinearErrors:
    def rate_limited(self, tool: str) -> ToolResult:
        return text_result(
            "Linear API rate limit exceeded. Please retry after a short delay.", is_error=True
        )

    def server_error(self, tool: str) -> ToolResult:
        return text_result("Linear API error (INTERNAL_ERROR): Something went wrong", is_error=True)

    def invalid_arguments(self, tool: str, message: str) -> ToolResult:
        return text_result(f"Invalid arguments: {message}", is_error=True)

    def not_found(self, tool: str, kind: str, key: str) -> ToolResult:
        return text_result(
            f"Entity not found: {kind} - Could not find referenced {kind}.", is_error=True
        )


ERRORS = LinearErrors()
