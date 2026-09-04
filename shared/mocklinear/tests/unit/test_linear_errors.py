from mocklinear.linear.errors import ERRORS


def test_a_rate_limit_reads_like_the_linear_server() -> None:
    result = ERRORS.rate_limited("list_issues")
    assert result.is_error
    assert result.content[0]["text"] == (
        "Linear API rate limit exceeded. Please retry after a short delay."
    )


def test_a_server_error_names_the_internal_error_code() -> None:
    result = ERRORS.server_error("get_issue")
    assert result.is_error
    assert result.content[0]["text"] == "Linear API error (INTERNAL_ERROR): Something went wrong"


def test_a_missing_entity_reads_the_same_whatever_was_asked_for() -> None:
    issue = ERRORS.not_found("get_issue", "Issue", "WEB-999")
    assert issue.is_error
    assert issue.content[0]["text"] == "Entity not found: Issue - Could not find referenced Issue."
    other = ERRORS.not_found("get_issue", "Issue", "6f0c-not-a-real-id")
    assert other.content[0]["text"] == issue.content[0]["text"]
    assert ERRORS.not_found("get_user", "User", "nobody").content[0]["text"] == (
        "Entity not found: User - Could not find referenced User."
    )


def test_bad_arguments_are_quoted_back_to_the_caller() -> None:
    result = ERRORS.invalid_arguments("list_issues", "Invalid cursor")
    assert result.is_error
    assert result.content[0]["text"] == "Invalid arguments: Invalid cursor"
