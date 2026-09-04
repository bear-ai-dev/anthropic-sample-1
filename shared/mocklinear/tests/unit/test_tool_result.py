from mocklinear.tool_result import (
    ToolResult,
    json_result,
    resource_result,
    result_chars,
    text_result,
)


def test_a_text_result_carries_one_text_block_and_no_page_by_default() -> None:
    result = text_result("hello")
    assert result == ToolResult(content=({"type": "text", "text": "hello"},))
    assert not result.is_error
    assert result.page is None


def test_an_error_result_keeps_its_page_information() -> None:
    result = text_result("nope", is_error=True, page={"hasNextPage": False})
    assert result.is_error
    assert result.page == {"hasNextPage": False}


def test_a_json_result_is_indented_the_way_the_linear_server_stringifies_it() -> None:
    payload = {"id": "ENG-1", "labels": ["bug"]}
    assert json_result(payload).content[0]["text"] == (
        '{\n  "id": "ENG-1",\n  "labels": [\n    "bug"\n  ]\n}'
    )
    assert json_result(payload, page={"hasNextPage": True}).page == {"hasNextPage": True}


def test_result_chars_counts_the_text_an_agent_would_read() -> None:
    assert result_chars(text_result("hello")) == 5
    assert result_chars(ToolResult(content=({"type": "text"},))) == 0


def test_a_resource_result_pairs_a_text_block_with_an_embedded_resource() -> None:
    result = resource_result(
        "downloaded README.md", "linear://x/README.md", "text/markdown", "# hi"
    )
    assert result.content == (
        {"type": "text", "text": "downloaded README.md"},
        {
            "type": "resource",
            "resource": {
                "uri": "linear://x/README.md",
                "mimeType": "text/markdown",
                "text": "# hi",
            },
        },
    )
    assert not result.is_error
    assert result_chars(result) == len("downloaded README.md")
