from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .tool_errors import InvalidArguments

_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no"}


def _as_integer(name: str, value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise InvalidArguments(f"parameter {name} must be an integer") from error


def _as_number(name: str, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise InvalidArguments(f"parameter {name} must be a number") from error


def _as_boolean(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise InvalidArguments(f"parameter {name} must be a boolean")


_COERCERS: dict[str, Callable[[str, Any], Any]] = {
    "integer": _as_integer,
    "number": _as_number,
    "boolean": _as_boolean,
}


def _coerce_value(name: str, value: Any, spec: dict[str, Any]) -> Any:
    coercer = _COERCERS.get(spec.get("type", ""))
    coerced = value if coercer is None else coercer(name, value)
    choices = spec.get("enum")
    if choices is not None and coerced not in choices:
        allowed = ", ".join(str(choice) for choice in choices)
        raise InvalidArguments(f"parameter {name} must be one of {allowed}")
    return coerced


def coerce_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = schema.get("properties", {})
    coerced: dict[str, Any] = {}
    for name, value in arguments.items():
        if value is None:
            continue
        spec = properties.get(name)
        coerced[name] = value if spec is None else _coerce_value(name, value, spec)
    for name in schema.get("required", []):
        if name not in coerced:
            raise InvalidArguments(f"missing required parameter: {name}")
    return coerced
