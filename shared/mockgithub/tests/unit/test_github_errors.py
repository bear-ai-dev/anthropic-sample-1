from mockgithub.github.errors import ERRORS


def test_a_rate_limit_reads_like_the_github_server_and_names_the_operation() -> None:
    result = ERRORS.rate_limited("issue_read")
    assert result.is_error
    assert result.content[0]["text"] == (
        "failed to get issue: GitHub API rate limit exceeded. Retry after 1m0s."
    )
    assert (
        ERRORS.rate_limited("list_pull_requests")
        .content[0]["text"]
        .startswith("failed to list pull requests: ")
    )


def test_a_server_error_is_a_bad_gateway() -> None:
    result = ERRORS.server_error("get_me")
    assert result.is_error
    assert result.content[0]["text"] == "failed to get user: 502 Bad Gateway []"


def test_a_missing_entity_is_a_rest_not_found_on_the_path_that_was_asked_for() -> None:
    result = ERRORS.not_found("issue_read", "issue", "ExampleCo/ledger/issues/999")
    assert result.is_error
    assert result.content[0]["text"] == (
        "failed to get issue: GET https://api.github.com/repos/ExampleCo/ledger/issues/999: "
        "404 Not Found []"
    )
    same = ERRORS.not_found("issue_read", "issue", "ExampleCo/ledger/issues/999")
    assert same.content[0]["text"] == result.content[0]["text"]


def test_bad_arguments_are_handed_back_verbatim() -> None:
    result = ERRORS.invalid_arguments("list_issues", "missing required parameter: owner")
    assert result.is_error
    assert result.content[0]["text"] == "missing required parameter: owner"


def test_every_tool_has_its_own_operation_name_and_unknown_tools_spell_theirs() -> None:
    expected = {
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
    for tool, op in expected.items():
        assert ERRORS.server_error(tool).content[0]["text"] == f"failed to {op}: 502 Bad Gateway []"
    assert ERRORS.server_error("boom").content[0]["text"] == "failed to boom: 502 Bad Gateway []"
