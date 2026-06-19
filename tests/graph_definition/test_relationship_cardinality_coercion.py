"""Tests for UML-notation coercion on RelationshipModel class variables.

Covers:
- RelationshipModel subclass with __source_cardinality__ = "1..*" → CardinalitySpec
- ConditionalCardinality construction accepts notation strings for rules and default
- Default (no override) is CardinalitySpec(min=0, max=None)
"""

from typing import cast

from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    PropMatch,
    RelationshipModel,
)


class _Source:
    __label__ = "Source"


class _Target:
    __label__ = "Target"


# --- Class-body string coercion in __init_subclass__ ------------------------


def test_source_cardinality_string_coerced():
    """Scope: __source_cardinality__ = '1..*' is coerced to CardinalitySpec."""

    class HasMany(RelationshipModel):
        __label__ = "HAS_MANY"
        __source_label__ = "Source"
        __target_label__ = "Target"
        __source_cardinality__ = "1..*"

    assert cast(CardinalitySpec, HasMany.__source_cardinality__) == CardinalitySpec(
        min=1, max=None
    )


def test_target_cardinality_string_coerced():
    """Scope: __target_cardinality__ = '0..1' is coerced to CardinalitySpec."""

    class HasOne(RelationshipModel):
        __label__ = "HAS_ONE"
        __source_label__ = "Source"
        __target_label__ = "Target"
        __target_cardinality__ = "0..1"

    assert cast(CardinalitySpec, HasOne.__target_cardinality__) == CardinalitySpec(
        min=0, max=1
    )


def test_cardinality_spec_instance_unchanged():
    """Scope: a CardinalitySpec instance is left as-is (not re-wrapped)."""
    spec = CardinalitySpec(min=2, max=5)

    class Ranged(RelationshipModel):
        __label__ = "RANGED"
        __source_label__ = "Source"
        __target_label__ = "Target"
        __source_cardinality__ = spec

    assert Ranged.__source_cardinality__ == spec


def test_conditional_cardinality_instance_unchanged():
    """Scope: a ConditionalCardinality class var is left as-is."""
    cc = ConditionalCardinality(rules=(), default=CardinalitySpec(min=0, max=None))

    class Conditional(RelationshipModel):
        __label__ = "CONDITIONAL"
        __source_label__ = "Source"
        __target_label__ = "Target"
        __source_cardinality__ = cc

    assert Conditional.__source_cardinality__ is cc


# --- Default cardinality (no override) --------------------------------------


def test_default_source_cardinality_is_zero_or_more():
    """Scope: default __source_cardinality__ is CardinalitySpec(min=0, max=None)."""

    class Plain(RelationshipModel):
        __label__ = "PLAIN"
        __source_label__ = "Source"
        __target_label__ = "Target"

    assert Plain.__source_cardinality__ == CardinalitySpec(min=0, max=None)


def test_default_target_cardinality_is_zero_or_more():
    """Scope: default __target_cardinality__ is CardinalitySpec(min=0, max=None)."""

    class Plain2(RelationshipModel):
        __label__ = "PLAIN2"
        __source_label__ = "Source"
        __target_label__ = "Target"

    assert Plain2.__target_cardinality__ == CardinalitySpec(min=0, max=None)


# --- ConditionalCardinality construction accepts notation strings ----------


def test_rules_accept_notation_strings():
    """Scope: ConditionalRule specs given as notation strings build equal to the
    spec-valued form."""
    cc_str = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "a"}),
                target=PropMatch({"kind": "b"}),
                spec="1..2",
            ),
        ),
        default="0..*",
    )
    cc_spec = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "a"}),
                target=PropMatch({"kind": "b"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
        ),
        default=CardinalitySpec(min=0, max=None),
    )
    assert cc_str == cc_spec


def test_default_accepts_notation_string():
    """Scope: ConditionalCardinality default accepts a bare notation string."""
    cc = ConditionalCardinality(
        rules=(),
        default="0..*",
    )
    assert cc.default == CardinalitySpec(min=0, max=None)
