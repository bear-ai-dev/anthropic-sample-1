from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any, TypeVar

from .tool_errors import InvalidArguments

T = TypeVar("T")
MAX_PAGE_SIZE = 100
_CURSOR_PREFIX = "cursor:"


def rest_page(items: list[T], page: int, per_page: int) -> list[T]:
    size = min(max(per_page, 1), MAX_PAGE_SIZE)
    start = (max(page, 1) - 1) * size
    return items[start : start + size]


def _offset_of(cursor: str) -> int:
    try:
        text = base64.b64decode(cursor, validate=True).decode()
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidArguments("Invalid cursor") from error
    if not text.startswith(_CURSOR_PREFIX) or not text[len(_CURSOR_PREFIX) :].isdigit():
        raise InvalidArguments("Invalid cursor")
    return int(text[len(_CURSOR_PREFIX) :])


def graphql_page(items: list[T], first: int, after: str | None) -> tuple[list[T], str | None, bool]:
    size = min(max(first, 1), MAX_PAGE_SIZE)
    start = _offset_of(after) if after is not None else 0
    window = items[start : start + size]
    if not window:
        return [], None, False
    end = start + len(window)
    end_cursor = base64.b64encode(f"{_CURSOR_PREFIX}{end}".encode()).decode()
    return window, end_cursor, end < len(items)


def _index_of(ids: list[str], cursor: str) -> int:
    try:
        return ids.index(cursor)
    except ValueError as error:
        raise InvalidArguments("Invalid cursor") from error


def id_cursor_page(
    items: list[T],
    limit: int,
    after: str | None,
    before: str | None,
    id_of: Callable[[T], str],
) -> tuple[list[T], dict[str, Any]]:
    ids = [id_of(item) for item in items]
    lower = _index_of(ids, after) + 1 if after is not None else 0
    upper = _index_of(ids, before) if before is not None else len(items)
    if after is None and before is not None:
        lower = max(upper - limit, 0)
    else:
        upper = min(lower + limit, upper)
    window = items[lower:upper]
    info: dict[str, Any] = {
        "hasNextPage": upper < len(items),
        "hasPreviousPage": lower > 0,
        "startCursor": ids[lower] if window else None,
        "endCursor": ids[upper - 1] if window else None,
    }
    return window, info
