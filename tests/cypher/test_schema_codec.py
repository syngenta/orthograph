"""Tests for src/orthograph/cypher/schema_codec.py."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from orthograph.cypher.bindings import NoParams
from orthograph.cypher.exceptions import CypherQueryDefinitionError
from orthograph.cypher.schema_codec import model_from_json_schema, model_to_json_schema


# ---------------------------------------------------------------------------
# Round-trip helpers
# ---------------------------------------------------------------------------


def test_round_trip_required_and_optional_int() -> None:
    """Round-trip: one required int, one optional int with default 10."""

    class SomeParams(BaseModel):
        released: int
        limit: int = 10

    schema = model_to_json_schema(SomeParams)
    rebuilt = model_from_json_schema(schema)

    assert set(rebuilt.model_fields) == {"released", "limit"}
    assert rebuilt.model_fields["released"].is_required()
    assert not rebuilt.model_fields["limit"].is_required()
    assert rebuilt.model_fields["limit"].default == 10


def test_round_trip_no_params() -> None:
    """Round-trip NoParams → zero-field model."""
    schema = model_to_json_schema(NoParams)
    rebuilt = model_from_json_schema(schema)
    assert rebuilt.model_fields == {}


def test_round_trip_scalar_types() -> None:
    """Each scalar type survives the round-trip."""

    class AllScalars(BaseModel):
        a: int
        b: str
        c: float
        d: bool

    schema = model_to_json_schema(AllScalars)
    rebuilt = model_from_json_schema(schema)
    assert set(rebuilt.model_fields) == {"a", "b", "c", "d"}


def test_required_optional_split_in_validate() -> None:
    """Required field must be supplied; optional field can be omitted."""

    class Params(BaseModel):
        a: int
        b: int = 5

    schema = model_to_json_schema(Params)
    rebuilt = model_from_json_schema(schema)

    # Can construct with only required field.
    instance = rebuilt.model_validate({"a": 42})
    assert instance.a == 42  # type: ignore[attr-defined]
    # Optional field uses the default from the schema (5).
    assert instance.b == 5  # type: ignore[attr-defined]

    # Required field missing → ValidationError.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        rebuilt.model_validate({})


def test_model_name_from_argument() -> None:
    """model_name argument takes priority over schema title."""

    class Foo(BaseModel):
        x: int

    schema = model_to_json_schema(Foo)
    rebuilt = model_from_json_schema(schema, model_name="CustomName")
    assert rebuilt.__name__ == "CustomName"


def test_model_name_from_schema_title() -> None:
    """Falls back to schema title when model_name not given."""

    class MyParams(BaseModel):
        x: int

    schema = model_to_json_schema(MyParams)
    rebuilt = model_from_json_schema(schema)
    assert rebuilt.__name__ == "MyParams"


def test_model_name_default() -> None:
    """Falls back to 'ReconstructedParams' when no title and no model_name."""
    schema = {"type": "object", "properties": {}}
    rebuilt = model_from_json_schema(schema)
    assert rebuilt.__name__ == "ReconstructedParams"


# ---------------------------------------------------------------------------
# Unsupported construct errors
# ---------------------------------------------------------------------------


def test_error_nested_object() -> None:
    schema = {
        "type": "object",
        "properties": {"nested": {"type": "object", "properties": {}}},
    }
    with pytest.raises(CypherQueryDefinitionError, match="nested"):
        model_from_json_schema(schema)


def test_error_array() -> None:
    schema = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
    }
    with pytest.raises(CypherQueryDefinitionError, match="tags"):
        model_from_json_schema(schema)


def test_error_enum() -> None:
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["active", "inactive"]}},
    }
    with pytest.raises(CypherQueryDefinitionError, match="status"):
        model_from_json_schema(schema)


def test_error_ref() -> None:
    schema = {
        "type": "object",
        "properties": {"item": {"$ref": "#/$defs/Item"}},
    }
    with pytest.raises(CypherQueryDefinitionError, match="item"):
        model_from_json_schema(schema)


def test_error_unknown_scalar_type() -> None:
    schema = {
        "type": "object",
        "properties": {"ts": {"type": "datetime"}},
    }
    with pytest.raises(CypherQueryDefinitionError, match="ts"):
        model_from_json_schema(schema)


def test_error_not_object_type() -> None:
    schema = {"type": "string"}
    with pytest.raises(CypherQueryDefinitionError):
        model_from_json_schema(schema)


def test_error_missing_properties() -> None:
    schema = {"type": "object"}
    with pytest.raises(CypherQueryDefinitionError):
        model_from_json_schema(schema)
