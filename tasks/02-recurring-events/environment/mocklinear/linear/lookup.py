from __future__ import annotations

from typing import TypeVar

from ..tool_errors import NotFound

T = TypeVar("T")


def found(entity: T | None, kind: str, key: str) -> T:
    if entity is None:
        raise NotFound(kind, key)
    return entity
