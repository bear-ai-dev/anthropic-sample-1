from mockgmail.gmail.errors import ERRORS


def test_a_rate_limit_is_plain_text_without_the_error_flag() -> None:
    result = ERRORS.rate_limited("search_emails")
    assert not result.is_error
    assert result.content == ({"type": "text", "text": "Error: Rate Limit Exceeded"},)


def test_a_server_error_reads_as_a_backend_error() -> None:
    result = ERRORS.server_error("read_email")
    assert not result.is_error
    assert result.content[0]["text"] == "Error: Backend Error"


def test_a_missing_entity_reads_the_same_whatever_was_asked_for() -> None:
    message = ERRORS.not_found("read_email", "Message", "0000000000000000")
    attachment = ERRORS.not_found("download_attachment", "Attachment", "nope")
    assert not message.is_error
    assert message.content[0]["text"] == "Error: Requested entity was not found."
    assert attachment.content[0]["text"] == message.content[0]["text"]


def test_bad_arguments_are_quoted_back_after_the_error_prefix() -> None:
    result = ERRORS.invalid_arguments("search_emails", "missing required parameter: query")
    assert not result.is_error
    assert result.content[0]["text"] == "Error: missing required parameter: query"
