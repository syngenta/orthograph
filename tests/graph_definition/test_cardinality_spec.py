"""Tests for CardinalitySpec, PropMatch, and ConditionalCardinality.

Covers E40.1 (ZERO, EXACTLY, resolve_for_pair) and E40.2 (PropMatch,
ConditionalCardinality, most-specific-wins, ambiguity guard).
"""

from typing import Any, cast

import pytest

from orthograph.graph_definition.exceptions import (
    AmbiguousCardinalityError,
    ModelDefinitionError,
)
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    PropMatch,
    _highest_specificity,
)


def test_cardinality_zero_contains_zero():
    """Scope: CardinalitySpec(min=0, max=0).contains(0) returns True."""
    assert CardinalitySpec(min=0, max=0).contains(0) is True


def test_cardinality_zero_contains_one_is_false():
    """Scope: CardinalitySpec(min=0, max=0).contains(1) returns False."""
    assert CardinalitySpec(min=0, max=0).contains(1) is False


def test_cardinality_zero_has_correct_bounds():
    """Scope: CardinalitySpec(min=0, max=0) has min=0, max=0."""
    assert CardinalitySpec(min=0, max=0).min == 0
    assert CardinalitySpec(min=0, max=0).max == 0


def test_exactly_three_creates_correct_spec():
    """Scope: CardinalitySpec(min=3, max=3) equals CardinalitySpec(min=3, max=3)."""
    assert CardinalitySpec(min=3, max=3) == CardinalitySpec(min=3, max=3)


def test_exactly_three_contains_three():
    """Scope: CardinalitySpec(min=3, max=3).contains(3) returns True."""
    assert CardinalitySpec(min=3, max=3).contains(3) is True


def test_exactly_three_contains_two_is_false():
    """Scope: CardinalitySpec(min=3, max=3).contains(2) returns False."""
    assert CardinalitySpec(min=3, max=3).contains(2) is False


def test_exactly_zero_creates_zero_spec():
    """Scope: CardinalitySpec(min=0, max=0) equals CardinalitySpec(min=0, max=0)."""
    assert CardinalitySpec(min=0, max=0) == CardinalitySpec(min=0, max=0)


def test_exactly_zero_contains_zero():
    """Scope: CardinalitySpec(min=0, max=0).contains(0) returns True."""
    assert CardinalitySpec(min=0, max=0).contains(0) is True


def test_cardinalityspec_resolve_for_pair_returns_self():
    """Scope: CardinalitySpec.resolve_for_pair returns self."""
    spec = CardinalitySpec(min=1, max=2)
    resolved = spec.resolve_for_pair({}, {})
    assert resolved is spec


def test_resolve_for_pair_ignores_self_props():
    """Scope: CardinalitySpec.resolve_for_pair ignores self_props."""
    spec = CardinalitySpec(min=1, max=2)
    resolved = spec.resolve_for_pair({"kind": "short"}, {})
    assert resolved is spec


def test_resolve_for_pair_ignores_other_props():
    """Scope: CardinalitySpec.resolve_for_pair ignores other_props."""
    spec = CardinalitySpec(min=1, max=2)
    resolved = spec.resolve_for_pair({}, {"kind": "none"})
    assert resolved is spec


def test_resolve_for_pair_ignores_both_props():
    """Scope: CardinalitySpec.resolve_for_pair ignores both endpoint properties."""
    spec = CardinalitySpec(min=1, max=2)
    resolved = spec.resolve_for_pair({"kind": "short"}, {"kind": "none"})
    assert resolved is spec


def test_cardinality_one_resolve_for_pair():
    """Scope: CardinalitySpec(min=1, max=1).resolve_for_pair returns itself."""
    assert CardinalitySpec(min=1, max=1).resolve_for_pair({}, {}) == CardinalitySpec(
        min=1, max=1
    )


def test_cardinality_zero_or_one_resolve_for_pair():
    """Scope: CardinalitySpec(min=0, max=1).resolve_for_pair returns itself."""
    assert CardinalitySpec(min=0, max=1).resolve_for_pair({}, {}) == CardinalitySpec(
        min=0, max=1
    )


def test_cardinality_zero_or_more_resolve_for_pair():
    """Scope: CardinalitySpec(min=0, max=None).resolve_for_pair returns itself."""
    assert CardinalitySpec(min=0, max=None).resolve_for_pair({}, {}) == CardinalitySpec(
        min=0, max=None
    )


def test_cardinality_one_or_more_resolve_for_pair():
    """Scope: CardinalitySpec(min=1, max=None).resolve_for_pair returns itself."""
    assert CardinalitySpec(min=1, max=None).resolve_for_pair({}, {}) == CardinalitySpec(
        min=1, max=None
    )


def test_cardinality_zero_resolve_for_pair():
    """Scope: CardinalitySpec(min=0, max=0).resolve_for_pair returns itself."""
    assert CardinalitySpec(min=0, max=0).resolve_for_pair({}, {}) == CardinalitySpec(
        min=0, max=0
    )


# ---------------------------------------------------------------------------
# PropMatch
# ---------------------------------------------------------------------------


def test_propmatch_matches_exact_value():
    """Scope: PropMatch({'kind': 'short'}).matches({'kind': 'short'}) is True."""
    assert PropMatch({"kind": "short"}).matches({"kind": "short"}) is True


def test_propmatch_no_match_wrong_value():
    """Scope: PropMatch({'kind': 'short'}).matches({'kind': 'x'}) is False."""
    assert PropMatch({"kind": "short"}).matches({"kind": "x"}) is False


def test_propmatch_empty_matches_any():
    """Scope: empty PropMatch().matches({...}) is always True."""
    assert PropMatch().matches({}) is True
    assert PropMatch().matches({"kind": "anything"}) is True


def test_propmatch_is_wildcard_true_when_empty():
    """Scope: PropMatch().is_wildcard is True."""
    assert PropMatch().is_wildcard is True


def test_propmatch_is_wildcard_false_when_conditions_set():
    """Scope: PropMatch({'kind': 'short'}).is_wildcard is False."""
    assert PropMatch({"kind": "short"}).is_wildcard is False


def test_propmatch_specificity_counts_conditions():
    """Scope: PropMatch({'a': 1, 'b': 2}).specificity == 2."""
    assert PropMatch({"a": 1, "b": 2}).specificity == 2


def test_propmatch_specificity_empty_is_zero():
    """Scope: PropMatch().specificity == 0."""
    assert PropMatch().specificity == 0


def test_propmatch_matches_missing_key_is_false():
    """Scope: PropMatch({'kind': 'short'}).matches({}) is False (key absent)."""
    assert PropMatch({"kind": "short"}).matches({}) is False


def test_propmatch_none_condition_does_not_match_absent_key():
    """Scope: a None condition matches a present None value, not an absent key."""
    p = PropMatch({"kind": None})
    assert p.matches({}) is False
    assert p.matches({"kind": None}) is True


def test_propmatch_conditions_is_mapping_not_writable():
    """Scope: conditions is a genuinely read-only mapping after construction.

    Pydantic ``frozen=True`` alone would not freeze the underlying dict, so
    PropMatch wraps it in a read-only proxy.  This guarantees equality and
    specificity cannot drift after construction.
    """
    p = PropMatch({"kind": "short"})
    assert p.conditions == {"kind": "short"}
    assert p.specificity == 1
    with pytest.raises(TypeError):
        cast(Any, p.conditions)["injected"] = "x"
    assert p == PropMatch({"kind": "short"})


# ---------------------------------------------------------------------------
# ConditionalCardinality — basic resolution
# ---------------------------------------------------------------------------

_ONE_TO_TWO = CardinalitySpec(min=1, max=2)
_DEFAULT = CardinalitySpec(min=0, max=None)

# ADR-029 deciding table (movie domain: Director kind → Film kind)
# - (documentary, documentary) → 1..2  (co-directed documentaries)
# - (short, none) → ZERO               (short directors skip unclassified films)
# - (feature, none) → ZERO             (feature directors skip unclassified films)
_DIRECTED = ConditionalCardinality(
    rules=(
        ConditionalRule(
            source=PropMatch({"kind": "documentary"}),
            target=PropMatch({"kind": "documentary"}),
            spec=_ONE_TO_TWO,
        ),
        ConditionalRule(
            source=PropMatch({"kind": "short"}),
            target=PropMatch({"kind": "none"}),
            spec=CardinalitySpec(min=0, max=0),
        ),
        ConditionalRule(
            source=PropMatch({"kind": "feature"}),
            target=PropMatch({"kind": "none"}),
            spec=CardinalitySpec(min=0, max=0),
        ),
    ),
    default=_DEFAULT,
)


def test_resolves_documentary_documentary():
    """Scope: rule table (documentary, documentary) -> 1..2."""
    spec = _DIRECTED.resolve_for_pair({"kind": "documentary"}, {"kind": "documentary"})
    assert spec == _ONE_TO_TWO


def test_resolves_short_none():
    """Scope: rule table (short, none) -> ZERO."""
    spec = _DIRECTED.resolve_for_pair({"kind": "short"}, {"kind": "none"})
    assert spec == CardinalitySpec(min=0, max=0)


def test_resolves_feature_none():
    """Scope: rule table (feature, none) -> ZERO."""
    spec = _DIRECTED.resolve_for_pair({"kind": "feature"}, {"kind": "none"})
    assert spec == CardinalitySpec(min=0, max=0)


def test_unmatched_pair_returns_default():
    """Scope: rule table (x, y) with no matching rule returns default."""
    spec = _DIRECTED.resolve_for_pair({"kind": "x"}, {"kind": "y"})
    assert spec == _DEFAULT


# ---------------------------------------------------------------------------
# ConditionalCardinality — most-specific-wins
# ---------------------------------------------------------------------------

_NARROW = ConditionalCardinality(
    rules=(
        ConditionalRule(
            source=PropMatch({"kind": "short"}),
            target=PropMatch(),
            spec=CardinalitySpec(min=0, max=0),
        ),
        ConditionalRule(
            source=PropMatch({"kind": "short"}),
            target=PropMatch({"kind": "none"}),
            spec=CardinalitySpec(min=1, max=1),
        ),
    ),
    default=_DEFAULT,
)


def test_most_specific_wins_narrow_rule_selected():
    """Scope: ('short','none') rule beats ('short','*') for (short, none) pair."""
    spec = _NARROW.resolve_for_pair({"kind": "short"}, {"kind": "none"})
    assert spec == CardinalitySpec(min=1, max=1)


def test_most_specific_wins_broad_rule_for_other_target():
    """Scope: ('short','*') rule selected for (short, other) when no narrower match."""
    spec = _NARROW.resolve_for_pair({"kind": "short"}, {"kind": "other"})
    assert spec == CardinalitySpec(min=0, max=0)


# ---------------------------------------------------------------------------
# ConditionalCardinality — order independence
# ---------------------------------------------------------------------------


def test_order_independence_rules_reversed():
    """Scope: reversing rule declaration order does not change resolution."""
    rules_fwd = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch(),
                spec=CardinalitySpec(min=0, max=0),
            ),
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch({"kind": "none"}),
                spec=CardinalitySpec(min=1, max=1),
            ),
        ),
        default=_DEFAULT,
    )
    rules_rev = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch({"kind": "none"}),
                spec=CardinalitySpec(min=1, max=1),
            ),
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch(),
                spec=CardinalitySpec(min=0, max=0),
            ),
        ),
        default=_DEFAULT,
    )
    for props_self, props_other in [
        ({"kind": "short"}, {"kind": "none"}),
        ({"kind": "short"}, {"kind": "other"}),
        ({"kind": "x"}, {"kind": "y"}),
    ]:
        assert rules_fwd.resolve_for_pair(
            props_self, props_other
        ) == rules_rev.resolve_for_pair(props_self, props_other)


# ---------------------------------------------------------------------------
# ConditionalCardinality — ambiguity guard
# ---------------------------------------------------------------------------


def test_ambiguity_guard_raises_on_equal_specificity():
    """Scope: equal-specificity overlap raises AmbiguousCardinalityError.

    Rules ('short','*') and ('*','none') both have specificity 1 and both
    match the pair (short, none).
    """
    ambiguous = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch(),
                spec=CardinalitySpec(min=0, max=0),
            ),
            ConditionalRule(
                source=PropMatch(),
                target=PropMatch({"kind": "none"}),
                spec=CardinalitySpec(min=1, max=1),
            ),
        ),
        default=_DEFAULT,
    )
    with pytest.raises(AmbiguousCardinalityError):
        ambiguous.resolve_for_pair({"kind": "short"}, {"kind": "none"})


def test_ambiguous_cardinality_error_is_model_definition_error():
    """Scope: AmbiguousCardinalityError is catchable as ModelDefinitionError."""
    ambiguous = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch(),
                spec=CardinalitySpec(min=0, max=0),
            ),
            ConditionalRule(
                source=PropMatch(),
                target=PropMatch({"kind": "none"}),
                spec=CardinalitySpec(min=1, max=1),
            ),
        ),
        default=_DEFAULT,
    )
    with pytest.raises(ModelDefinitionError):
        ambiguous.resolve_for_pair({"kind": "short"}, {"kind": "none"})


def test_highest_specificity_requires_non_empty_matches():
    """Scope: _highest_specificity asserts on empty input (private precondition)."""
    with pytest.raises(AssertionError):
        _highest_specificity([])


# ---------------------------------------------------------------------------
# PropMatch — positional construction contract
# ---------------------------------------------------------------------------


def test_propmatch_positional_equals_keyword():
    """Scope: PropMatch({...}) and PropMatch(conditions={...}) are equal."""
    assert PropMatch({"kind": "short"}) == PropMatch(conditions={"kind": "short"})


def test_propmatch_positional_multi_key():
    """Scope: PropMatch({...}) with multiple keys — specificity and matches."""
    p = PropMatch({"kind": "short", "genre": "drama"})
    assert p.specificity == 2
    assert p.matches({"kind": "short", "genre": "drama"}) is True
    assert p.matches({"kind": "short", "genre": "other"}) is False
    assert p.matches({"kind": "short"}) is False


def test_propmatch_empty_positional_is_wildcard():
    """Scope: PropMatch() with no argument is a wildcard."""
    assert PropMatch().is_wildcard is True
    assert PropMatch().specificity == 0
    assert PropMatch().matches({"kind": "anything"}) is True


def test_propmatch_in_conditional_rule_positional_form():
    """Scope: the agreed authoring form (positional PropMatch) resolves correctly.

    Exercises the exact snippet from the design agreement — multi-key source
    predicate and single-key target — to confirm the full stack works end to end.
    """
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "short", "genre": "drama"}),
                target=PropMatch({"kind": "none"}),
                spec=CardinalitySpec(min=0, max=0),
            ),
        ),
        default=CardinalitySpec(min=0, max=None),
    )
    assert card.resolve_for_pair(
        {"kind": "short", "genre": "drama"}, {"kind": "none"}
    ) == CardinalitySpec(min=0, max=0)
    assert card.resolve_for_pair(
        {"kind": "short", "genre": "other"}, {"kind": "none"}
    ) == CardinalitySpec(min=0, max=None)
    assert card.resolve_for_pair(
        {"kind": "short", "genre": "drama"}, {"kind": "other"}
    ) == CardinalitySpec(min=0, max=None)
