from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeVar

from ..paging import graphql_page, rest_page
from ..tool_result import ToolResult, text_result

T = TypeVar("T")
DEFAULT_PER_PAGE = 30


def compact(payload: Any, *, page: dict[str, Any] | None = None) -> ToolResult:
    return text_result(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), page=page)


def rest_list(
    items: list[T], args: dict[str, Any], render: Callable[[T], Any]
) -> tuple[list[Any], dict[str, Any]]:
    page = int(args.get("page", 1))
    per_page = int(args.get("perPage", DEFAULT_PER_PAGE))
    window = rest_page(items, page, per_page)
    has_next = rest_page(items, page + 1, per_page) != []
    return [render(item) for item in window], {
        "page": page,
        "perPage": per_page,
        "hasNextPage": has_next,
    }


def graphql_list(
    items: list[T], args: dict[str, Any], render: Callable[[T], Any]
) -> tuple[list[Any], dict[str, Any], dict[str, Any]]:
    per_page = int(args.get("perPage", DEFAULT_PER_PAGE))
    window, end_cursor, has_next = graphql_page(items, per_page, args.get("after"))
    info = {"hasNextPage": has_next, "endCursor": end_cursor}
    return [render(item) for item in window], info, dict(perPage=per_page, **info)


def search_result(items: list[Any], args: dict[str, Any]) -> ToolResult:
    rendered, page = rest_list(items, args, lambda item: item)
    payload = {"total_count": len(items), "incomplete_results": False, "items": rendered}
    return compact(payload, page=page)
