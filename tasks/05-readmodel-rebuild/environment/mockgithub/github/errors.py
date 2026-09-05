from __future__ import annotations

from ..tool_result import ToolResult, text_result

OPERATIONS = {
    "get_me": "get user",
    "issue_read": "get issue",
    "list_issues": "list issues",
    "search_issues": "search issues",
    "get_label": "get label",
    "pull_request_read": "get pull request",
    "list_pull_requests": "list pull requests",
    "search_pull_requests": "search pull requests",
    "get_file_contents": "get file contents",
    "list_commits": "list commits",
    "get_commit": "get commit",
    "search_code": "search code",
    "list_branches": "list branches",
    "list_tags": "list tags",
    "list_releases": "list releases",
    "search_users": "search users",
}
API = "https://api.github.com/repos/"


def operation(tool: str) -> str:
    return OPERATIONS.get(tool, tool.replace("_", " "))


class GithubErrors:
    def rate_limited(self, tool: str) -> ToolResult:
        return text_result(
            f"failed to {operation(tool)}: GitHub API rate limit exceeded. Retry after 1m0s.",
            is_error=True,
        )

    def server_error(self, tool: str) -> ToolResult:
        return text_result(f"failed to {operation(tool)}: 502 Bad Gateway []", is_error=True)

    def invalid_arguments(self, tool: str, message: str) -> ToolResult:
        return text_result(message, is_error=True)

    def not_found(self, tool: str, kind: str, key: str) -> ToolResult:
        return text_result(
            f"failed to {operation(tool)}: GET {API}{key}: 404 Not Found []", is_error=True
        )


ERRORS = GithubErrors()
