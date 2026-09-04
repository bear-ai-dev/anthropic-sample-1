from typing import Any

import pytest

from mocklinear.schema_args import coerce_arguments
from mocklinear.tool_errors import InvalidArguments


def test_a_missing_required_parameter_is_reported_by_name() -> None:
    with pytest.raises(InvalidArguments, match="missing required parameter: id"):
        coerce_arguments({}, {"required": ["id"], "properties": {"id": {"type": "string"}}})


def test_string_numbers_are_coerced_and_unknown_keys_kept() -> None:
    out = coerce_arguments(
        {"limit": "25", "extra": 1}, {"properties": {"limit": {"type": "integer"}}}
    )
    assert out == {"limit": 25, "extra": 1}


def test_numbers_and_booleans_accept_their_string_forms() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "ratio": {"type": "number"},
            "archived": {"type": "boolean"},
            "active": {"type": "boolean"},
            "name": {"type": "string"},
        }
    }
    out = coerce_arguments(
        {"ratio": "1.5", "archived": "TRUE", "active": False, "name": "main"}, schema
    )
    assert out == {"ratio": 1.5, "archived": True, "active": False, "name": "main"}
    assert coerce_arguments({"archived": "0"}, schema) == {"archived": False}
    assert coerce_arguments({"ratio": 2}, schema) == {"ratio": 2.0}


def test_a_value_that_is_not_of_its_declared_type_is_rejected_by_name() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "limit": {"type": "integer"},
            "ratio": {"type": "number"},
            "archived": {"type": "boolean"},
        }
    }
    with pytest.raises(InvalidArguments, match="parameter limit must be an integer"):
        coerce_arguments({"limit": "many"}, schema)
    with pytest.raises(InvalidArguments, match="parameter ratio must be a number"):
        coerce_arguments({"ratio": "some"}, schema)
    with pytest.raises(InvalidArguments, match="parameter archived must be a boolean"):
        coerce_arguments({"archived": "maybe"}, schema)


def test_a_value_outside_the_enum_lists_the_allowed_values() -> None:
    schema: dict[str, Any] = {
        "properties": {"orderBy": {"type": "string", "enum": ["createdAt", "updatedAt"]}}
    }
    assert coerce_arguments({"orderBy": "createdAt"}, schema) == {"orderBy": "createdAt"}
    with pytest.raises(InvalidArguments, match="parameter orderBy must be one of"):
        coerce_arguments({"orderBy": "priority"}, schema)


def test_null_values_are_dropped_and_leave_a_required_parameter_missing() -> None:
    schema: dict[str, Any] = {
        "required": ["id"],
        "properties": {"id": {"type": "string"}, "team": {"type": "string"}},
    }
    with pytest.raises(InvalidArguments, match="missing required parameter: id"):
        coerce_arguments({"id": None}, schema)
    assert coerce_arguments({"id": "ENG-1", "team": None}, schema) == {"id": "ENG-1"}


def test_a_schema_without_properties_passes_arguments_through() -> None:
    assert coerce_arguments({"query": "scanner"}, {}) == {"query": "scanner"}
