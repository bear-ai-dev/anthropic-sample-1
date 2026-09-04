from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from ..paging import id_cursor_page
from ..tool_result import ToolResult, json_result


class HasId(Protocol):
    @property
    def id(self) -> str: ...


T = TypeVar("T", bound=HasId)

PAGE_PROPERTIES: dict[str, Any] = {
    "limit": {
        "type": "integer",
        "description": "How many items to return (default 50).",
        "default": 50,
    },
    "after": {"type": "string", "description": "Return items after this cursor."},
    "before": {"type": "string", "description": "Return items before this cursor."},
}


def list_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": {**properties, **PAGE_PROPERTIES}}


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def paged(
    plural: str,
    items: list[T],
    arguments: dict[str, Any],
    render: Callable[[T], dict[str, Any]],
    id_of: Callable[[T], str] = lambda item: str(item.id),
) -> ToolResult:
    window, info = id_cursor_page(
        items,
        int(arguments["limit"]),
        arguments.get("after"),
        arguments.get("before"),
        id_of,
    )
    return json_result({plural: [render(item) for item in window], "pageInfo": info}, page=info)
