from mockgithub.tool_errors import (
    InvalidArguments,
    NotFound,
    Throttled,
    ToolError,
    TransientServerError,
)


def test_a_not_found_error_names_the_kind_and_key_that_were_looked_up() -> None:
    error = NotFound("Issue", "ENG-9")
    assert error.kind == "Issue"
    assert error.key == "ENG-9"
    assert error.message == "Issue not found: ENG-9"
    assert str(error) == "Issue not found: ENG-9"


def test_every_tool_error_is_a_tool_error_carrying_its_message() -> None:
    errors: list[ToolError] = [
        InvalidArguments("Invalid cursor"),
        Throttled("rate limit exceeded for github:list_issues"),
        TransientServerError("internal error for github:get_issue"),
        NotFound("Comment", "c1"),
    ]
    assert [error.message for error in errors] == [str(error) for error in errors]
    assert all(isinstance(error, ToolError) for error in errors)
