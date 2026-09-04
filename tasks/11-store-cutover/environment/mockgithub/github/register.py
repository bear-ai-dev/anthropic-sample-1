from __future__ import annotations

from ..tool_spec import ToolSpec
from .tools import (
    get_commit,
    get_file_contents,
    get_label,
    get_me,
    issue_read,
    list_branches,
    list_commits,
    list_issues,
    list_pull_requests,
    list_releases,
    list_tags,
    pull_request_read,
    search_code,
    search_issues,
    search_pull_requests,
    search_users,
)


def specs() -> list[ToolSpec]:
    return [
        get_me.SPEC,
        issue_read.SPEC,
        list_issues.SPEC,
        search_issues.SPEC,
        get_label.SPEC,
        pull_request_read.SPEC,
        list_pull_requests.SPEC,
        search_pull_requests.SPEC,
        get_file_contents.SPEC,
        list_commits.SPEC,
        get_commit.SPEC,
        search_code.SPEC,
        list_branches.SPEC,
        list_tags.SPEC,
        list_releases.SPEC,
        search_users.SPEC,
    ]
