"""Tests for orthograph.graph_definition.relationship_model."""

from typing import Optional

import pytest

from orthograph.graph_definition.exceptions import MissingClassVarError
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    PropMatch,
    RelationshipModel,
    representative_spec,
)
from tests.graph_definition.conftest import City, Movie, Person  # noqa: F401


# --- RelationshipModel definition tests ---


def test_relationship_model_simple():
    class ActedIn(RelationshipModel):
        __label__ = "ACTED_IN"
        __source_label__ = "Person"
        __target_label__ = "Movie"

        role: str

    assert ActedIn.__label__ == "ACTED_IN"
    assert ActedIn.__source_label__ == "Person"
    assert ActedIn.__target_label__ == "Movie"
    assert ActedIn.__directed__ is True
    assert ActedIn.__optional__ is True
    # Default cardinality is ZERO_OR_MORE on both sides (permissive default)
    assert ActedIn.__source_cardinality__ == CardinalitySpec(min=0, max=None)
    assert ActedIn.__target_cardinality__ == CardinalitySpec(min=0, max=None)


def test_relationship_model_with_cardinality():
    class LivesIn(RelationshipModel):
        __label__ = "LIVES_IN"
        __source_label__ = "Person"
        __target_label__ = "City"
        __source_cardinality__ = CardinalitySpec(min=1, max=1)
        __target_cardinality__ = CardinalitySpec(min=0, max=None)

    assert LivesIn.__source_cardinality__ == CardinalitySpec(min=1, max=1)
    assert LivesIn.__target_cardinality__ == CardinalitySpec(min=0, max=None)


def test_relationship_model_undirected():
    class FriendOf(RelationshipModel):
        __label__ = "FRIEND_OF"
        __source_label__ = "Person"
        __target_label__ = "Person"
        __directed__ = False

    assert FriendOf.__directed__ is False


def test_relationship_model_with_optional_properties():
    class Knows(RelationshipModel):
        __label__ = "KNOWS"
        __source_label__ = "Person"
        __target_label__ = "Person"

        since: Optional[int] = None
        trust_level: float = 0.5

    k = Knows(since=2020)
    assert k.since == 2020
    assert k.trust_level == 0.5

    k2 = Knows()
    assert k2.since is None


def test_relationship_model_optional():
    class MaybeRel(RelationshipModel):
        __label__ = "MAYBE"
        __source_label__ = "Person"
        __target_label__ = "Movie"
        __optional__ = True

    assert MaybeRel.__optional__ is True


def test_relationship_model_requires_label():
    with pytest.raises(MissingClassVarError, match="__label__"):

        class BadRel(RelationshipModel):
            __source_label__ = "Person"
            __target_label__ = "Movie"


def test_relationship_model_requires_source_type():
    with pytest.raises(MissingClassVarError, match="__source_label__"):

        class BadRel(RelationshipModel):
            __label__ = "BAD"
            __target_label__ = "Movie"


def test_relationship_model_requires_target_type():
    with pytest.raises(MissingClassVarError, match="__target_label__"):

        class BadRel(RelationshipModel):
            __label__ = "BAD"
            __source_label__ = "Person"


def test_relationship_model_self_referencing():
    class Manages(RelationshipModel):
        __label__ = "MANAGES"
        __source_label__ = "Person"
        __target_label__ = "Person"
        __source_cardinality__ = CardinalitySpec(min=0, max=None)
        __target_cardinality__ = CardinalitySpec(min=0, max=1)

    assert Manages.__source_label__ == "Person"
    assert Manages.__target_label__ == "Person"


def test_relationship_model_custom_cardinality():
    class LimitedRel(RelationshipModel):
        __label__ = "LIMITED"
        __source_label__ = "Person"
        __target_label__ = "Movie"
        __source_cardinality__ = CardinalitySpec(min=2, max=5)

    assert LimitedRel.__source_cardinality__.min == 2
    assert LimitedRel.__source_cardinality__.max == 5


# --- RelationshipModel introspection tests ---


def test_relationship_model_get_property_specs():
    class ActedIn(RelationshipModel):
        __label__ = "ACTED_IN"
        __source_label__ = "Person"
        __target_label__ = "Movie"

        role: str
        year: Optional[int] = None

    specs = ActedIn.get_property_specs()
    assert "role" in specs
    assert specs["role"].is_required is True
    assert "year" in specs
    assert specs["year"].is_required is False


def test_relationship_model_get_required_property_names():
    class Rel(RelationshipModel):
        __label__ = "REL"
        __source_label__ = "Person"
        __target_label__ = "Movie"

        weight: float
        note: Optional[str] = None

    required = Rel.get_required_property_names()
    assert required == {"weight"}


def test_relationship_model_get_all_property_names():
    class Rel(RelationshipModel):
        __label__ = "REL"
        __source_label__ = "Person"
        __target_label__ = "Movie"

        weight: float
        note: Optional[str] = None

    names = Rel.get_all_property_names()
    assert names == {"weight", "note"}


# --- RelationshipModel serialization tests ---


def test_relationship_model_to_dict():
    class ActedIn(RelationshipModel):
        __label__ = "ACTED_IN"
        __source_label__ = "Person"
        __target_label__ = "Movie"

        role: str

    r = ActedIn(role="Forrest")
    d = r.model_dump()
    assert d == {"role": "Forrest"}


def test_relationship_model_from_dict():
    class ActedIn(RelationshipModel):
        __label__ = "ACTED_IN"
        __source_label__ = "Person"
        __target_label__ = "Movie"

        role: str

    r = ActedIn.model_validate({"role": "Hermione"})
    assert r.role == "Hermione"


# --- E40.3: conditional cardinality on ClassVar ---


def test_relationship_model_conditional_source_cardinality():
    """Scope: RelationshipModel with ConditionalCardinality source side constructs
    and ClassVar reads back equal."""
    conditional = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch({"kind": "none"}),
                spec=CardinalitySpec(min=0, max=0),
            ),
        ),
        default=CardinalitySpec(min=0, max=None),
    )

    class Directed(RelationshipModel):
        __label__ = "DIRECTED"
        __source_label__ = "Director"
        __target_label__ = "Movie"
        __source_cardinality__ = conditional

    assert Directed.__source_cardinality__ == conditional


def test_relationship_model_conditional_target_cardinality():
    """Scope: ConditionalCardinality is accepted on the target side too (symmetry)."""
    conditional = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch(),
                target=PropMatch({"kind": "unreleased"}),
                spec=CardinalitySpec(min=0, max=0),
            ),
        ),
        default=CardinalitySpec(min=0, max=None),
    )

    class Produced(RelationshipModel):
        __label__ = "PRODUCED"
        __source_label__ = "Director"
        __target_label__ = "Movie"
        __target_cardinality__ = conditional

    assert Produced.__target_cardinality__ == conditional


def test_relationship_model_constant_cardinality_regression():
    """Scope: constant-cardinality RelationshipModel subclass constructs correctly."""

    class LivesIn(RelationshipModel):
        __label__ = "LIVES_IN"
        __source_label__ = "Person"
        __target_label__ = "City"
        __source_cardinality__ = CardinalitySpec(min=1, max=1)
        __target_cardinality__ = CardinalitySpec(min=0, max=None)

    assert LivesIn.__source_cardinality__ == CardinalitySpec(min=1, max=1)
    assert LivesIn.__target_cardinality__ == CardinalitySpec(min=0, max=None)


# --- E40.3: representative_spec helper ---


def test_representative_spec_returns_plain_spec_unchanged():
    """Scope: a CardinalitySpec passes through representative_spec unchanged."""
    spec = CardinalitySpec(min=1, max=3)
    assert representative_spec(spec) is spec


def test_representative_spec_collapses_conditional_to_default():
    """Scope: a ConditionalCardinality collapses to its default bound, never
    raising AttributeError on min/max/contains access."""
    conditional = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "split"}),
                target=PropMatch({"kind": "nothing"}),
                spec=CardinalitySpec(min=0, max=0),
            ),
        ),
        default=CardinalitySpec(min=1, max=None),
    )

    result = representative_spec(conditional)

    assert result == CardinalitySpec(min=1, max=None)
    # The collapsed value supports the CardinalitySpec API the call sites need.
    assert result.min == 1
    assert result.max is None
    assert result.contains(5) is True
