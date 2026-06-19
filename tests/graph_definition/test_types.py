"""Tests for orthograph.graph_definition -- CardinalitySpec, Cardinality, TypeInfo."""

from typing import Optional

import pytest
from pydantic import ValidationError

from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.graph_definition.models import (
    CardinalitySpec,
)
from orthograph.graph_definition.property_spec import resolve_type_info


# --- CardinalitySpec tests ---


def test_cardinality_spec_create_with_min_and_max():
    spec = CardinalitySpec(min=1, max=5)
    assert spec.min == 1
    assert spec.max == 5


def test_cardinality_spec_create_with_unbounded_max():
    spec = CardinalitySpec(min=0, max=None)
    assert spec.min == 0
    assert spec.max is None


def test_cardinality_spec_min_cannot_be_negative():
    with pytest.raises(ValidationError):
        CardinalitySpec(min=-1, max=5)


def test_cardinality_spec_max_cannot_be_less_than_min():
    with pytest.raises(ValidationError):
        CardinalitySpec(min=3, max=2)


def test_cardinality_spec_max_zero_only_if_min_zero():
    spec = CardinalitySpec(min=0, max=0)
    assert spec.min == 0
    assert spec.max == 0


def test_cardinality_spec_equality():
    a = CardinalitySpec(min=1, max=5)
    b = CardinalitySpec(min=1, max=5)
    c = CardinalitySpec(min=0, max=5)
    assert a == b
    assert a != c


def test_cardinality_spec_repr():
    spec = CardinalitySpec(min=1, max=None)
    r = repr(spec)
    assert "1" in r


def test_cardinality_spec_frozen():
    spec = CardinalitySpec(min=1, max=5)
    with pytest.raises(ValidationError):
        spec.min = 2  # type: ignore[misc,unused-ignore]


def test_cardinality_spec_contains_count_within_bounds():
    spec = CardinalitySpec(min=1, max=5)
    assert spec.contains(1)
    assert spec.contains(3)
    assert spec.contains(5)


def test_cardinality_spec_contains_count_outside_bounds():
    spec = CardinalitySpec(min=1, max=5)
    assert not spec.contains(0)
    assert not spec.contains(6)


def test_cardinality_spec_contains_unbounded():
    spec = CardinalitySpec(min=1, max=None)
    assert spec.contains(1)
    assert spec.contains(999999)
    assert not spec.contains(0)


# --- Cardinality tests ---


def test_cardinality_zero_or_one():
    spec = CardinalitySpec.parse("0..1")
    assert spec.min == 0
    assert spec.max == 1


def test_cardinality_one():
    spec = CardinalitySpec.parse("1..1")
    assert spec.min == 1
    assert spec.max == 1


def test_cardinality_zero_or_more():
    spec = CardinalitySpec.parse("0..*")
    assert spec.min == 0
    assert spec.max is None


def test_cardinality_zero_or_more_accepts_zero():
    """ZERO_OR_MORE (0..*) must accept count=0 -- participation is optional."""
    spec = CardinalitySpec.parse("0..*")
    assert spec.contains(0)
    assert spec.contains(1)
    assert spec.contains(999)


def test_cardinality_one_or_more():
    spec = CardinalitySpec.parse("1..*")
    assert spec.min == 1
    assert spec.max is None


def test_cardinality_one_or_more_rejects_zero():
    """ONE_OR_MORE (1..*) must reject count=0 -- participation is mandatory."""
    spec = CardinalitySpec.parse("1..*")
    assert not spec.contains(0)
    assert spec.contains(1)
    assert spec.contains(999)


def test_cardinality_zero_or_more_vs_one_or_more():
    """The semantic difference: both accept high counts, but only ZERO_OR_MORE
    accepts zero.  This is the core distinction between optional and mandatory
    participation."""
    zero_plus = CardinalitySpec.parse("0..*")
    one_plus = CardinalitySpec.parse("1..*")

    # Both accept count > 0
    assert zero_plus.contains(5)
    assert one_plus.contains(5)

    # Only ZERO_OR_MORE accepts count = 0
    assert zero_plus.contains(0)
    assert not one_plus.contains(0)


def test_cardinality_custom():
    custom = CardinalitySpec(min=2, max=5)
    assert custom.min == 2
    assert custom.max == 5
    assert custom.contains(3)
    assert not custom.contains(1)


# --- EntityType tests ---


def test_entity_type_node_value():
    assert EntityType.NODE.value == "node"


def test_entity_type_relationship_value():
    assert EntityType.RELATIONSHIP.value == "relationship"


# --- Severity tests ---


def test_severity_levels():
    assert Severity.ERROR.value == "error"
    assert Severity.WARNING.value == "warning"
    assert Severity.INFO.value == "info"


def test_severity_ordering():
    # ERROR is more severe than WARNING
    assert Severity.ERROR.value < Severity.WARNING.value  # alphabetical


# --- PropertyRequired / resolve_type_info tests ---


def test_resolve_type_info_required_str():
    info = resolve_type_info(str)
    assert info.python_type is str
    assert info.is_required is True
    assert info.default is None


def test_resolve_type_info_optional_str():
    info = resolve_type_info(Optional[str])
    assert info.python_type is str
    assert info.is_required is False


def test_resolve_type_info_int():
    info = resolve_type_info(int)
    assert info.python_type is int
    assert info.is_required is True


def test_resolve_type_info_list_of_str():
    info = resolve_type_info(list[str])
    assert info.python_type is list
    assert info.is_required is True


def test_resolve_type_info_optional_int():
    info = resolve_type_info(Optional[int])
    assert info.python_type is int
    assert info.is_required is False


def test_resolve_type_info_union_none():
    info = resolve_type_info(str | None)
    assert info.python_type is str
    assert info.is_required is False
