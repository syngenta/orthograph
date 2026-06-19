"""Tests for CardinalitySpec UML-notation (de)serialization (E42.1).

Covers ``parse`` / ``notation`` round-trip, the ``mode="before"`` coercion
seam, the ``*``-using ``__repr__``, and ``CardinalityParseError`` on every
illegal grammar case from ADR-031.
"""

import pytest

from orthograph.graph_definition.exceptions import CardinalityParseError
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    PropMatch,
)


# The five canonical specs plus two arbitrary bounded specs from the task.
ROUND_TRIP_SPECS = [
    CardinalitySpec(min=0, max=0),
    CardinalitySpec(min=0, max=1),
    CardinalitySpec(min=1, max=1),
    CardinalitySpec(min=0, max=None),
    CardinalitySpec(min=1, max=None),
    CardinalitySpec(min=2, max=5),
    CardinalitySpec(min=3, max=3),
]

LEGAL_NOTATIONS = {
    "0..0": (0, 0),
    "0..1": (0, 1),
    "1..1": (1, 1),
    "0..*": (0, None),
    "1..*": (1, None),
    "2..5": (2, 5),
    "3..3": (3, 3),
}

# Syntactic failures from the ADR-031 grammar block.
SYNTACTIC_ILLEGAL = ["1", "*", "..5", "1..", "*..5", "1...5", "a..b"]


# --- parse: legal strings ---------------------------------------------------


@pytest.mark.parametrize(("text", "expected"), LEGAL_NOTATIONS.items())
def test_parse_legal_notation(text, expected):
    """Scope: every legal notation parses to the expected (min, max)."""
    spec = CardinalitySpec.parse(text)
    assert (spec.min, spec.max) == expected


# --- round-trip invariant ---------------------------------------------------


@pytest.mark.parametrize("spec", ROUND_TRIP_SPECS)
def test_round_trip_parse_of_notation(spec):
    """Scope: parse(spec.notation) == spec for every canonical spec."""
    assert CardinalitySpec.parse(spec.notation) == spec


def test_notation_uses_star_for_unbounded():
    """Scope: notation emits ``*`` (not ``N``) for an unbounded max."""
    assert CardinalitySpec(min=1, max=None).notation == "1..*"


def test_notation_emits_bounded_max():
    """Scope: notation emits the numeric max when bounded."""
    assert CardinalitySpec(min=2, max=5).notation == "2..5"


# --- parse: illegal strings -------------------------------------------------


@pytest.mark.parametrize("text", SYNTACTIC_ILLEGAL)
def test_parse_syntactic_failure_raises(text):
    """Scope: syntactically illegal notation raises CardinalityParseError."""
    with pytest.raises(CardinalityParseError):
        CardinalitySpec.parse(text)


def test_parse_inverted_bounds_raises_value_error():
    """Scope: ``5..2`` is syntactically valid; the bound check rejects it."""
    with pytest.raises(ValueError):
        CardinalitySpec.parse("5..2")


def test_parse_negative_min_raises_value_error():
    """Scope: ``-1..0`` is syntactically valid; the bound check rejects it."""
    with pytest.raises(ValueError):
        CardinalitySpec.parse("-1..0")


# --- mode="before" coercion seam --------------------------------------------


def test_model_validate_coerces_notation_string():
    """Scope: model_validate('1..*') yields CardinalitySpec(min=1, max=None)."""
    assert CardinalitySpec.model_validate("1..*") == CardinalitySpec(min=1, max=None)


def test_model_validate_passes_dict_through():
    """Scope: dict input is unchanged by the before-validator."""
    assert CardinalitySpec.model_validate({"min": 2, "max": 5}) == CardinalitySpec(
        min=2, max=5
    )


def test_model_validate_passes_instance_through():
    """Scope: an existing instance is passed through untouched."""
    spec = CardinalitySpec(min=1, max=1)
    assert CardinalitySpec.model_validate(spec) == spec


# --- __repr__ ---------------------------------------------------------------


def test_repr_unbounded_uses_star():
    """Scope: repr renders an unbounded max with ``*``."""
    assert repr(CardinalitySpec(min=1, max=None)) == "CardinalitySpec(1..*)"


def test_repr_bounded():
    """Scope: repr renders a bounded spec as min..max."""
    assert repr(CardinalitySpec(min=2, max=5)) == "CardinalitySpec(2..5)"


# --- embedded use in conditional types (no regression) ----------------------


def test_conditional_rule_coerces_notation_spec():
    """Scope: ConditionalRule.spec accepts a notation string via the seam."""
    rule = ConditionalRule(source=PropMatch(), target=PropMatch(), spec="1..*")
    assert rule.spec == CardinalitySpec(min=1, max=None)


def test_conditional_cardinality_coerces_notation_default():
    """Scope: ConditionalCardinality.default accepts a notation string."""
    cc = ConditionalCardinality(rules=(), default="0..*")
    assert cc.default == CardinalitySpec(min=0, max=None)


def test_conditional_types_still_construct_with_spec_instances():
    """Scope: instance-valued construction (the existing form) is unchanged."""
    rule = ConditionalRule(
        source=PropMatch(), target=PropMatch(), spec=CardinalitySpec(min=1, max=1)
    )
    cc = ConditionalCardinality(rules=(rule,), default=CardinalitySpec(min=0, max=None))
    assert cc.default == CardinalitySpec(min=0, max=None)
    assert cc.rules[0].spec == CardinalitySpec(min=1, max=1)
