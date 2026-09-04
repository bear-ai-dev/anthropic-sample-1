import base64

import pytest

from mockgmail.paging import graphql_page, id_cursor_page, rest_page
from mockgmail.tool_errors import InvalidArguments


def test_an_unknown_cursor_is_an_invalid_argument() -> None:
    with pytest.raises(InvalidArguments, match="Invalid cursor"):
        id_cursor_page(["a", "b"], 1, "zzz", None, lambda x: x)
    with pytest.raises(InvalidArguments, match="Invalid cursor"):
        id_cursor_page(["a", "b"], 1, None, "zzz", lambda x: x)


def test_a_page_reports_its_own_first_and_last_id_as_cursors() -> None:
    page, info = id_cursor_page(["a", "b", "c"], 2, None, None, lambda x: x)
    assert page == ["a", "b"]
    assert info == {
        "hasNextPage": True,
        "hasPreviousPage": False,
        "startCursor": "a",
        "endCursor": "b",
    }


def test_a_page_after_a_cursor_continues_and_reports_a_previous_page() -> None:
    page, info = id_cursor_page(["a", "b", "c"], 2, "a", None, lambda x: x)
    assert page == ["b", "c"]
    assert info == {
        "hasNextPage": False,
        "hasPreviousPage": True,
        "startCursor": "b",
        "endCursor": "c",
    }


def test_a_page_before_a_cursor_walks_backwards() -> None:
    page, info = id_cursor_page(["a", "b", "c", "d"], 2, None, "d", lambda x: x)
    assert page == ["b", "c"]
    assert info["hasPreviousPage"]
    assert info["hasNextPage"]
    bounded, bounded_info = id_cursor_page(["a", "b", "c"], 2, "a", "c", lambda x: x)
    assert bounded == ["b"]
    assert bounded_info["hasNextPage"]


def test_a_page_with_no_items_has_no_cursors() -> None:
    empty: list[str] = []
    page, info = id_cursor_page(empty, 2, None, None, lambda x: x)
    assert page == []
    assert info == {
        "hasNextPage": False,
        "hasPreviousPage": False,
        "startCursor": None,
        "endCursor": None,
    }


def test_a_rest_page_is_one_based_and_clamps_the_page_size() -> None:
    items = list(range(1, 8))
    assert rest_page(items, 1, 3) == [1, 2, 3]
    assert rest_page(items, 3, 3) == [7]
    assert rest_page(items, 4, 3) == []
    assert rest_page(items, 0, 3) == [1, 2, 3]
    assert rest_page(items, 1, 0) == [1]
    assert rest_page(list(range(150)), 1, 500) == list(range(100))


def test_a_graphql_page_hands_out_opaque_offset_cursors() -> None:
    items = ["a", "b", "c", "d", "e"]
    window, end_cursor, has_next = graphql_page(items, 2, None)
    assert window == ["a", "b"]
    assert has_next
    assert end_cursor == base64.b64encode(b"cursor:2").decode()
    window, end_cursor, has_next = graphql_page(items, 2, end_cursor)
    assert window == ["c", "d"]
    assert has_next
    window, end_cursor, has_next = graphql_page(items, 2, end_cursor)
    assert window == ["e"]
    assert not has_next
    assert end_cursor == base64.b64encode(b"cursor:5").decode()


def test_an_empty_graphql_page_has_no_cursor() -> None:
    empty: list[str] = []
    assert graphql_page(empty, 2, None) == ([], None, False)


def test_a_graphql_cursor_that_was_not_minted_here_is_refused() -> None:
    with pytest.raises(InvalidArguments, match="Invalid cursor"):
        graphql_page(["a"], 1, "zzz")
    with pytest.raises(InvalidArguments, match="Invalid cursor"):
        graphql_page(["a"], 1, base64.b64encode(b"offset:1").decode())
    with pytest.raises(InvalidArguments, match="Invalid cursor"):
        graphql_page(["a"], 1, base64.b64encode(b"cursor:x").decode())
