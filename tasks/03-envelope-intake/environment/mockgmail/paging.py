from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from .tool_errors import InvalidArguments

T = TypeVar("T")


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
