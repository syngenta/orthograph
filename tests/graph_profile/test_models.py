"""Tests for orthograph.graph_profile.models -- GraphProfile and sub-models."""

import math
from datetime import datetime

from orthograph.graph_profile.models import (
    BoundedDistribution,
    CardinalityStats,
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PartitionedCardinalityRow,
    PartitionKey,
    PropertyProfile,
    RelationshipTypeProfile,
    RelTypeKey,
)


# --- PropertyProfile ---


def test_property_profile_completeness():
    p = PropertyProfile(name="age", present_count=80, total_count=100)
    assert p.completeness == 0.8
    assert p.missing_count == 20


def test_property_profile_fully_complete():
    p = PropertyProfile(name="name", present_count=100, total_count=100)
    assert p.completeness == 1.0
    assert p.missing_count == 0


def test_property_profile_empty():
    p = PropertyProfile(name="x", present_count=0, total_count=0)
    assert p.completeness == 0.0


# --- PropertyProfile presence-source split ---


def test_property_profile_is_required_removed():
    """``is_required`` is removed; the 100%-present concept reads off completeness."""
    p = PropertyProfile(name="name", present_count=100, total_count=100)
    assert not hasattr(p, "is_required")
    assert p.completeness == 1.0


def test_property_profile_constraint_required_default_none():
    """``constraint_required`` defaults to None (constraint info unavailable)."""
    p = PropertyProfile(name="x", present_count=5, total_count=10)
    assert p.constraint_required is None


def test_property_profile_constraint_required_true():
    """A DB presence/existence constraint covers this property."""
    p = PropertyProfile(
        name="name", present_count=10, total_count=10, constraint_required=True
    )
    assert p.constraint_required is True


def test_property_profile_constraint_required_false():
    """Inspected, no covering presence/existence constraint found."""
    p = PropertyProfile(
        name="nickname", present_count=3, total_count=10, constraint_required=False
    )
    assert p.constraint_required is False


def test_property_profile_constraint_required_serialises():
    """``constraint_required`` round-trips through model_dump / model_validate."""
    p = PropertyProfile(
        name="name", present_count=10, total_count=10, constraint_required=True
    )
    d = p.model_dump()
    assert d["constraint_required"] is True
    restored = PropertyProfile.model_validate(d)
    assert restored.constraint_required is True


def test_property_profile_observed_types():
    p = PropertyProfile(
        name="val",
        present_count=10,
        total_count=10,
        observed_types=["String", "Long"],
    )
    assert p.observed_types == ["String", "Long"]


def test_property_profile_observed_type_counts_default():
    """observed_type_counts defaults to empty dict when not supplied."""
    p = PropertyProfile(name="x", present_count=5, total_count=10)
    assert p.observed_type_counts == {}


def test_property_profile_observed_type_counts_populated():
    """observed_type_counts carries type-conformance statistics."""
    p = PropertyProfile(
        name="score",
        present_count=100,
        total_count=100,
        observed_types=["Long", "Float"],
        observed_type_counts={"Long": 95, "Float": 5},
    )
    assert p.observed_type_counts == {"Long": 95, "Float": 5}


def test_property_profile_observed_type_counts_serialises():
    """observed_type_counts round-trips through model_dump / model_validate."""
    p = PropertyProfile(
        name="age",
        present_count=10,
        total_count=10,
        observed_type_counts={"Long": 10},
    )
    d = p.model_dump()
    assert d["observed_type_counts"] == {"Long": 10}
    restored = PropertyProfile.model_validate(d)
    assert restored.observed_type_counts == {"Long": 10}


def test_property_profile_distinct_count_default():
    """distinct_count defaults to None (Case-A field, not always populated)."""
    p = PropertyProfile(name="x", present_count=5, total_count=10)
    assert p.distinct_count is None


def test_property_profile_distinct_count_populated():
    """distinct_count carries observed-only enrichment."""
    p = PropertyProfile(
        name="city",
        present_count=100,
        total_count=100,
        distinct_count=42,
    )
    assert p.distinct_count == 42


def test_property_profile_distinct_count_serialises():
    """distinct_count round-trips through model_dump / model_validate."""
    p = PropertyProfile(
        name="status",
        present_count=10,
        total_count=10,
        distinct_count=3,
    )
    d = p.model_dump()
    assert d["distinct_count"] == 3
    restored = PropertyProfile.model_validate(d)
    assert restored.distinct_count == 3


# ---------------------------------------------------------------------------
# How to add a Case-A observed-only field
# ---------------------------------------------------------------------------
# Recipe: add a field to PropertyProfile with default=None/{}. That is all.
#
# The field:
#   - is carried and serialised by Pydantic automatically
#   - does NOT touch validation.py, rules.py, or the comparison engine
#   - has no declared twin and never participates in comparison
#   - future backends can populate it; callers that don't supply it get None/{}
#
# distinct_count (D1) is the reference example.  Follow the same pattern for
# any new observed-only statistic (percentiles, histograms, means, etc.).
# ---------------------------------------------------------------------------


def test_property_profile_frozen():
    import pytest
    from pydantic import ValidationError

    p = PropertyProfile(name="x", present_count=1, total_count=1)
    with pytest.raises(ValidationError):
        p.name = "y"  # type: ignore[misc]


# --- BoundedDistribution ---


def test_bounded_distribution_complete_round_trip():
    """A complete distribution round-trips; moments read back equal."""
    d = BoundedDistribution(
        count=100,
        min=0.0,
        max=10.0,
        mean=4.2,
        variance=2.25,
        skewness=0.1,
        kurtosis=2.9,
        histogram={"a": 60, "b": 40},
    )
    assert d.count == 100
    assert d.min == 0.0
    assert d.max == 10.0
    assert d.mean == 4.2
    assert d.variance == 2.25
    assert d.skewness == 0.1
    assert d.kurtosis == 2.9
    assert d.histogram == {"a": 60, "b": 40}
    assert d.sample_complete is True
    assert d.limit is None
    assert d.other_count == 0

    restored = BoundedDistribution.model_validate(d.model_dump())
    assert restored == d


def test_bounded_distribution_truncated_round_trip():
    """A truncated distribution round-trips and reports truncation."""
    d = BoundedDistribution(
        count=1000,
        histogram={"x": 5, "y": 4, "z": 3},
        sample_complete=False,
        limit=3,
        other_count=988,
    )
    assert d.sample_complete is False
    assert d.limit == 3
    assert d.other_count == 988

    restored = BoundedDistribution.model_validate(d.model_dump())
    assert restored == d
    assert restored.sample_complete is False
    assert restored.other_count == 988


def test_bounded_distribution_std_derived_from_variance():
    """std derives from variance; None when variance is None."""
    d = BoundedDistribution(count=10, variance=9.0)
    assert d.std == math.sqrt(9.0)

    d_none = BoundedDistribution(count=10)
    assert d_none.variance is None
    assert d_none.std is None


def test_bounded_distribution_moments_none_tolerant():
    """Backends that supply only min/max leave the rest None."""
    d = BoundedDistribution(count=5, min=1.0, max=4.0)
    assert d.mean is None
    assert d.variance is None
    assert d.skewness is None
    assert d.kurtosis is None
    assert d.histogram is None


def test_bounded_distribution_frozen():
    import pytest
    from pydantic import ValidationError

    d = BoundedDistribution(count=1)
    with pytest.raises(ValidationError):
        d.count = 2  # type: ignore[misc]


# --- CardinalityStats (re-expressed on BoundedDistribution) ---


def test_cardinality_stats():
    c = CardinalityStats(count=100, min=0.0, max=5.0, mean=2.3, variance=1.5)
    assert c.count == 100
    assert c.min == 0.0
    assert c.max == 5.0
    assert c.mean == 2.3
    assert c.variance == 1.5


def test_cardinality_stats_is_bounded_distribution():
    """CardinalityStats is a specialisation of BoundedDistribution."""
    c = CardinalityStats(count=10, min=1.0, max=3.0, mean=2.0)
    assert isinstance(c, BoundedDistribution)


def test_cardinality_stats_round_trip():
    c = CardinalityStats(count=50, min=1.0, max=10.0, mean=3.5, variance=4.0)
    restored = CardinalityStats.model_validate(c.model_dump())
    assert restored == c


# --- ConstraintInfo ---


def test_constraint_info():
    c = ConstraintInfo(
        name="unique_person_name",
        constraint_type="UNIQUENESS",
        entity_type="NODE",
        labels=["Person"],
        properties=["name"],
    )
    assert c.name == "unique_person_name"
    assert c.property_type is None


# --- NodeTypeProfile ---


def test_node_type_profile():
    props = {
        "name": PropertyProfile(name="name", present_count=100, total_count=100),
        "age": PropertyProfile(name="age", present_count=80, total_count=100),
    }
    n = NodeTypeProfile(label="Person", count=100, property_profiles=props)
    assert n.label == "Person"
    assert n.count == 100
    assert len(n.property_profiles) == 2
    assert n.property_profiles["age"].completeness == 0.8


# --- RelationshipTypeProfile ---


def test_relationship_type_profile():
    r = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=200,
        source_label="Person",
        target_label="Movie",
    )
    assert r.rel_type == "ACTED_IN"
    assert r.count == 200
    assert r.source_label == "Person"
    assert r.target_label == "Movie"
    assert r.cardinality_stats is None


def test_relationship_type_profile_scalar_endpoints_describe_one_shape():
    """A profile carries scalar endpoints — exactly one (src, label, tgt) shape."""
    r = RelationshipTypeProfile(
        rel_type="KNOWS",
        count=10,
        source_label="Person",
        target_label="Company",
    )
    assert not hasattr(r, "source_labels")
    assert not hasattr(r, "target_labels")
    assert isinstance(r.source_label, str)
    assert isinstance(r.target_label, str)


def test_relationship_type_profile_with_cardinality():
    stats = CardinalityStats(count=50, min=1.0, max=10.0, mean=3.5)
    r = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=200,
        source_label="Person",
        target_label="Movie",
        cardinality_stats=stats,
    )
    assert r.cardinality_stats is not None
    assert r.cardinality_stats.mean == 3.5


# --- GraphProfile ---


def test_graph_profile_basic():
    profile = GraphProfile(source="test")
    assert profile.source == "test"
    assert profile.node_labels == set()
    assert profile.relationship_types == set()


def test_graph_profile_with_data():
    key = str(RelTypeKey(source_label="Person", label="ACTED_IN", target_label="Movie"))
    profile = GraphProfile(
        source="networkx",
        node_type_profiles={
            "Person": NodeTypeProfile(label="Person", count=10),
            "Movie": NodeTypeProfile(label="Movie", count=5),
        },
        rel_type_profiles={
            key: RelationshipTypeProfile(
                rel_type="ACTED_IN",
                count=20,
                source_label="Person",
                target_label="Movie",
            ),
        },
    )
    assert profile.node_labels == {"Person", "Movie"}
    assert profile.relationship_types == {"Person:ACTED_IN:Movie"}


def test_graph_profile_distinguishes_same_label_different_endpoints():
    """Two same-label/different-endpoint profiles round-trip with distinct keys."""
    k1 = str(RelTypeKey(source_label="Person", label="KNOWS", target_label="Person"))
    k2 = str(RelTypeKey(source_label="Company", label="KNOWS", target_label="Company"))
    profile = GraphProfile(
        source="networkx",
        rel_type_profiles={
            k1: RelationshipTypeProfile(
                rel_type="KNOWS",
                count=7,
                source_label="Person",
                target_label="Person",
                cardinality_stats=CardinalityStats(count=7, min=1.0, max=3.0),
            ),
            k2: RelationshipTypeProfile(
                rel_type="KNOWS",
                count=2,
                source_label="Company",
                target_label="Company",
                cardinality_stats=CardinalityStats(count=2, min=4.0, max=9.0),
            ),
        },
    )
    # relationship_types returns the two distinct key strings.
    assert profile.relationship_types == {
        "Person:KNOWS:Person",
        "Company:KNOWS:Company",
    }
    # Statistics are NOT blended across the two shapes.
    assert profile.rel_type_profiles[k1].count == 7
    assert profile.rel_type_profiles[k2].count == 2
    stats1 = profile.rel_type_profiles[k1].cardinality_stats
    stats2 = profile.rel_type_profiles[k2].cardinality_stats
    assert stats1 is not None
    assert stats1.max == 3.0
    assert stats2 is not None
    assert stats2.max == 9.0

    restored = GraphProfile.model_validate(profile.model_dump())
    assert restored == profile
    assert restored.relationship_types == {
        "Person:KNOWS:Person",
        "Company:KNOWS:Company",
    }


# --- PropertyProfile value_distribution ---


def test_property_profile_value_distribution_default_none():
    """value_distribution defaults to None when not supplied."""
    p = PropertyProfile(name="x", present_count=5, total_count=10)
    assert p.value_distribution is None


def test_property_profile_value_distribution_low_cardinality():
    """A low-cardinality property carries a complete BoundedDistribution."""
    dist = BoundedDistribution(
        count=10,
        histogram={"red": 6, "blue": 4},
        sample_complete=True,
    )
    p = PropertyProfile(
        name="colour",
        present_count=10,
        total_count=10,
        value_distribution=dist,
    )
    assert p.value_distribution is not None
    assert p.value_distribution.histogram == {"red": 6, "blue": 4}
    assert p.value_distribution.sample_complete is True
    assert p.value_distribution.other_count == 0


def test_property_profile_value_distribution_truncated():
    """A high-cardinality property carries a truncated BoundedDistribution."""
    dist = BoundedDistribution(
        count=1000,
        histogram={"uid1": 1, "uid2": 1, "uid3": 1},
        sample_complete=False,
        limit=3,
        other_count=997,
    )
    p = PropertyProfile(
        name="id",
        present_count=1000,
        total_count=1000,
        value_distribution=dist,
    )
    assert p.value_distribution is not None
    assert p.value_distribution.sample_complete is False
    assert p.value_distribution.limit == 3
    assert p.value_distribution.other_count == 997


def test_property_profile_value_distribution_serialises():
    """value_distribution round-trips through model_dump / model_validate."""
    dist = BoundedDistribution(
        count=5,
        histogram={"a": 3, "b": 2},
        sample_complete=True,
    )
    p = PropertyProfile(
        name="status",
        present_count=5,
        total_count=5,
        value_distribution=dist,
    )
    d = p.model_dump()
    assert d["value_distribution"]["histogram"] == {"a": 3, "b": 2}
    restored = PropertyProfile.model_validate(d)
    assert restored.value_distribution == dist


def test_graph_profile_serialisation():
    profile = GraphProfile(
        source="test",
        timestamp=datetime(2026, 1, 1),
        node_type_profiles={
            "A": NodeTypeProfile(
                label="A",
                count=5,
                property_profiles={
                    "x": PropertyProfile(
                        name="x",
                        present_count=5,
                        total_count=5,
                        observed_types=["String"],
                    )
                },
            )
        },
    )
    d = profile.model_dump()
    assert d["source"] == "test"
    assert d["node_type_profiles"]["A"]["count"] == 5
    loaded = GraphProfile.model_validate(d)
    assert loaded.node_labels == {"A"}


# --- Full reshaped GraphProfile round-trip ---


def test_full_reshaped_graph_profile_round_trip():
    """Full GraphProfile with all fields round-trips through model_dump/validate."""
    from orthograph.graph_profile.models import ConstraintInfo

    dist_complete = BoundedDistribution(
        count=10,
        min=0.0,
        max=5.0,
        mean=2.5,
        variance=1.0,
        histogram={"active": 7, "inactive": 3},
        sample_complete=True,
    )
    dist_truncated = BoundedDistribution(
        count=1000,
        histogram={"uid1": 1, "uid2": 1, "uid3": 1},
        sample_complete=False,
        limit=3,
        other_count=997,
    )
    cardinality = CardinalityStats(count=50, min=1.0, max=8.0, mean=3.2, variance=2.1)

    profile = GraphProfile(
        source="neo4j",
        timestamp=datetime(2026, 6, 22, 12, 0),
        node_type_profiles={
            "Person": NodeTypeProfile(
                label="Person",
                count=100,
                property_profiles={
                    "name": PropertyProfile(
                        name="name",
                        present_count=100,
                        total_count=100,
                        constraint_required=True,
                        observed_types=["String"],
                        value_distribution=dist_complete,
                    ),
                    "uid": PropertyProfile(
                        name="uid",
                        present_count=100,
                        total_count=100,
                        constraint_required=False,
                        observed_types=["String"],
                        value_distribution=dist_truncated,
                    ),
                    "age": PropertyProfile(
                        name="age",
                        present_count=80,
                        total_count=100,
                        constraint_required=None,
                        observed_types=["Long"],
                        value_distribution=None,
                    ),
                },
            )
        },
        rel_type_profiles={
            "Person:ACTED_IN:Movie": RelationshipTypeProfile(
                rel_type="ACTED_IN",
                count=200,
                source_label="Person",
                target_label="Movie",
                cardinality_stats=cardinality,
            )
        },
        constraints=[
            ConstraintInfo(
                name="person_name_exists",
                constraint_type="NODE_PROPERTY_EXISTENCE",
                entity_type="NODE",
                labels=["Person"],
                properties=["name"],
            )
        ],
    )

    d = profile.model_dump()
    restored = GraphProfile.model_validate(d)

    # Top-level fields
    assert restored.source == "neo4j"
    assert restored.timestamp == datetime(2026, 6, 22, 12, 0)

    # Node profile and property profiles
    person = restored.node_type_profiles["Person"]
    assert person.count == 100

    name_pp = person.property_profiles["name"]
    assert name_pp.constraint_required is True
    assert name_pp.completeness == 1.0
    assert name_pp.value_distribution is not None
    assert name_pp.value_distribution.histogram == {"active": 7, "inactive": 3}
    assert name_pp.value_distribution.sample_complete is True

    uid_pp = person.property_profiles["uid"]
    assert uid_pp.constraint_required is False
    assert uid_pp.value_distribution is not None
    assert uid_pp.value_distribution.sample_complete is False
    assert uid_pp.value_distribution.limit == 3
    assert uid_pp.value_distribution.other_count == 997

    age_pp = person.property_profiles["age"]
    assert age_pp.constraint_required is None
    assert age_pp.value_distribution is None

    # Cardinality stats (re-expressed on BoundedDistribution)
    rel = restored.rel_type_profiles["Person:ACTED_IN:Movie"]
    assert rel.cardinality_stats is not None
    assert rel.cardinality_stats.count == 50
    assert rel.cardinality_stats.min == 1.0
    assert rel.cardinality_stats.variance == 2.1
    assert isinstance(rel.cardinality_stats, CardinalityStats)

    # Constraints
    assert len(restored.constraints) == 1
    c = restored.constraints[0]
    assert c.constraint_type == "NODE_PROPERTY_EXISTENCE"
    assert c.labels == ["Person"]


def test_full_profile_round_trip_equality():
    """model_validate(model_dump(p)) == p for a fully-populated profile."""
    dist = BoundedDistribution(
        count=5, histogram={"a": 3, "b": 2}, sample_complete=True
    )
    profile = GraphProfile(
        source="networkx",
        timestamp=datetime(2026, 6, 22),
        node_type_profiles={
            "X": NodeTypeProfile(
                label="X",
                count=5,
                property_profiles={
                    "p": PropertyProfile(
                        name="p",
                        present_count=5,
                        total_count=5,
                        constraint_required=False,
                        observed_types=["String"],
                        value_distribution=dist,
                    )
                },
            )
        },
    )
    restored = GraphProfile.model_validate(profile.model_dump())
    assert restored == profile


# ---------------------------------------------------------------------------
# PartitionKey and partitioned_cardinality
# ---------------------------------------------------------------------------


# --- PartitionKey (map-shaped, name-aware) ---


def test_partition_key_constructs_with_maps():
    """PartitionKey carries {name: value} maps per endpoint."""
    k = PartitionKey(source={}, target={"type": "combine"})
    assert k.source == {}
    assert k.target == {"type": "combine"}


def test_partition_key_equal_by_value():
    """Two keys with equal maps are equal."""
    k1 = PartitionKey(source={}, target={"type": "combine"})
    k2 = PartitionKey(source={}, target={"type": "combine"})
    assert k1 == k2


def test_partition_key_distinct_names_not_equal():
    """Same value under different property names are distinct keys.

    This is the name-blindness defect that this change fixes:
    ``{"type": "combine"}`` and ``{"stage": "combine"}`` no longer collide.
    """
    k1 = PartitionKey(source={}, target={"type": "combine"})
    k2 = PartitionKey(source={}, target={"stage": "combine"})
    assert k1 != k2


def test_partition_key_empty_vs_null_value_distinct():
    """{} (no discriminator) is distinct from {"k": None} (present-but-null)."""
    no_disc = PartitionKey(source={}, target={})
    null_val = PartitionKey(source={}, target={"type": None})
    assert no_disc != null_val


def test_partition_key_frozen():
    """PartitionKey is immutable."""
    import pytest
    from pydantic import ValidationError

    k = PartitionKey(source={}, target={"type": "combine"})
    with pytest.raises(ValidationError):
        k.target = {"type": "other"}  # type: ignore[misc]


def test_partition_key_hashable_consistent_with_equality():
    """PartitionKey is usable as a dict key / set member, hash == for equal keys.

    Despite carrying ``dict`` fields, the key hashes its sorted map items so it
    can index the partition merges in the producer and comparison paths.
    """
    a = PartitionKey(source={}, target={"type": "combine"})
    b = PartitionKey(source={}, target={"type": "combine"})
    c = PartitionKey(source={}, target={"stage": "combine"})
    assert a == b and hash(a) == hash(b)
    assert a != c and hash(a) != hash(c)
    assert {a: 1, c: 2}[b] == 1  # b matches a as a dict key
    assert len({a, b, c}) == 2  # a and b dedupe; c distinct


def test_partition_key_str_is_deterministic_display_form():
    """__str__ is a deterministic, sorted-key display form."""
    k1 = PartitionKey(source={}, target={"type": "combine", "stage": "x"})
    k2 = PartitionKey(source={}, target={"stage": "x", "type": "combine"})
    # Sorted-key form is insensitive to insertion order.
    assert str(k1) == str(k2)
    s = str(k1)
    assert "type" in s
    assert "combine" in s
    assert "stage" in s


def test_partition_key_str_shows_names_and_values():
    """The display form shows discriminator names alongside values."""
    k = PartitionKey(source={}, target={"type": "combine"})
    s = str(k)
    assert "type" in s
    assert "combine" in s


def test_partition_key_round_trips():
    """PartitionKey round-trips through model_dump/model_validate."""
    k = PartitionKey(source={"role": "in"}, target={"type": None})
    assert PartitionKey.model_validate(k.model_dump()) == k


# --- PartitionedCardinalityRow ({key, stats}) ---


def test_partitioned_cardinality_row_constructs():
    """A row pairs a PartitionKey with a BoundedDistribution."""
    row = PartitionedCardinalityRow(
        key=PartitionKey(source={}, target={"type": "combine"}),
        stats=BoundedDistribution(count=9, min=2.0, max=3.0),
    )
    assert row.key.target == {"type": "combine"}
    assert row.stats.max == 3.0


def test_partitioned_cardinality_row_round_trips():
    """A row round-trips through model_dump/model_validate."""
    row = PartitionedCardinalityRow(
        key=PartitionKey(source={}, target={"type": "combine"}),
        stats=BoundedDistribution(count=9, min=2.0, max=3.0),
    )
    assert PartitionedCardinalityRow.model_validate(row.model_dump()) == row


def test_partitioned_cardinality_row_value_with_pipe_and_equals_round_trips():
    """Regression of the old string-key bug: values containing ``|`` and ``=``.

    The old ``"src=<v>|tgt=<v>"`` dict key was ambiguous on these characters; the
    structured row round-trips them losslessly.
    """
    row = PartitionedCardinalityRow(
        key=PartitionKey(source={}, target={"label": "a|b=c"}),
        stats=BoundedDistribution(count=1, min=1.0, max=1.0),
    )
    restored = PartitionedCardinalityRow.model_validate(row.model_dump())
    assert restored == row
    assert restored.key.target == {"label": "a|b=c"}


def test_partitioned_cardinality_row_cardinality_stats_loses_subtype():
    """A CardinalityStats passed as stats is restored as BoundedDistribution.

    The field is typed on the base ``BoundedDistribution`` so round-trip equality holds.
    """
    row = PartitionedCardinalityRow(
        key=PartitionKey(source={}, target={"type": "combine"}),
        stats=CardinalityStats(count=5, min=1.0, max=3.0),
    )
    restored = PartitionedCardinalityRow.model_validate(row.model_dump())
    assert restored.stats.min == 1.0
    assert restored.stats.max == 3.0
    assert type(restored.stats) is BoundedDistribution


# --- per-side partitioned cardinality on RelationshipTypeProfile ---


def test_relationship_type_profile_partitioned_cardinality_defaults_none():
    """Both per-side breakdowns default to None (non-conditional unchanged)."""
    r = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=200,
        source_label="Person",
        target_label="Movie",
    )
    assert r.source_partitioned_cardinality is None
    assert r.target_partitioned_cardinality is None


def test_relationship_type_profile_with_partitioned_cardinality():
    """A profile carries a list of rows with the expected values, order preserved."""
    rows = [
        PartitionedCardinalityRow(
            key=PartitionKey(source={"step": "subsampling"}, target={}),
            stats=BoundedDistribution(count=10, min=2.0, max=2.0, mean=2.0),
        ),
        PartitionedCardinalityRow(
            key=PartitionKey(source={"step": "nothing"}, target={}),
            stats=BoundedDistribution(count=5, min=0.0, max=0.0, mean=0.0),
        ),
    ]
    r = RelationshipTypeProfile(
        rel_type="PRODUCES",
        count=15,
        source_label="Operation",
        target_label="Sample",
        source_partitioned_cardinality=rows,
    )
    assert r.source_partitioned_cardinality is not None
    assert len(r.source_partitioned_cardinality) == 2
    assert r.source_partitioned_cardinality[0].stats.min == 2.0
    assert r.source_partitioned_cardinality[1].stats.max == 0.0


def test_relationship_type_profile_both_sides_independent():
    """Both per-side breakdowns coexist as independent lists of rows.

    A partition discriminating the same property/value may appear on both sides
    with different degree distributions (source-counted vs target-counted); the
    two named list fields keep them separate.
    """
    key = PartitionKey(source={"step": "subsampling"}, target={"step": "subsampling"})
    r = RelationshipTypeProfile(
        rel_type="HAS_OUTPUT",
        count=4,
        source_label="Operation",
        target_label="Sample",
        source_partitioned_cardinality=[
            PartitionedCardinalityRow(
                key=key, stats=BoundedDistribution(count=1, min=2.0, max=2.0)
            )
        ],
        target_partitioned_cardinality=[
            PartitionedCardinalityRow(
                key=key, stats=BoundedDistribution(count=2, min=1.0, max=1.0)
            )
        ],
    )
    assert r.source_partitioned_cardinality is not None
    assert r.target_partitioned_cardinality is not None
    assert r.source_partitioned_cardinality[0].stats.max == 2.0
    assert r.target_partitioned_cardinality[0].stats.max == 1.0
    restored = RelationshipTypeProfile.model_validate(r.model_dump())
    assert restored == r


def test_relationship_type_profile_partitioned_cardinality_round_trip():
    """A full profile with a list of rows on each side round-trips, order preserved."""
    source_rows = [
        PartitionedCardinalityRow(
            key=PartitionKey(source={"step": "subsampling"}, target={}),
            stats=BoundedDistribution(count=10, min=2.0, max=2.0),
        ),
        PartitionedCardinalityRow(
            key=PartitionKey(source={"step": None}, target={}),
            stats=BoundedDistribution(count=3, min=0.0, max=1.0),
        ),
    ]
    target_rows = [
        PartitionedCardinalityRow(
            key=PartitionKey(source={}, target={"type": "combine"}),
            stats=BoundedDistribution(count=9, min=2.0, max=3.0),
        ),
    ]
    r = RelationshipTypeProfile(
        rel_type="PRODUCES",
        count=13,
        source_label="Operation",
        target_label="Sample",
        cardinality_stats=CardinalityStats(count=13, min=0.0, max=2.0),
        source_partitioned_cardinality=source_rows,
        target_partitioned_cardinality=target_rows,
    )
    restored = RelationshipTypeProfile.model_validate(r.model_dump())
    assert restored == r
    assert restored.source_partitioned_cardinality is not None
    assert [row.key for row in restored.source_partitioned_cardinality] == [
        row.key for row in source_rows
    ]


def test_relationship_type_profile_existing_aggregate_unaffected():
    """cardinality_stats (aggregate) is unaffected when a per-side breakdown is
    also set."""
    agg = CardinalityStats(count=15, min=0.0, max=2.0, mean=1.0)
    r = RelationshipTypeProfile(
        rel_type="REL",
        count=15,
        source_label="A",
        target_label="B",
        cardinality_stats=agg,
        source_partitioned_cardinality=[
            PartitionedCardinalityRow(
                key=PartitionKey(source={"k": "v"}, target={}),
                stats=BoundedDistribution(count=10, min=1.0, max=2.0),
            )
        ],
    )
    assert r.cardinality_stats == agg
    assert r.source_partitioned_cardinality is not None


# ---------------------------------------------------------------------------
# RelTypeKey -- relationship-identity encoding/decoding
# ---------------------------------------------------------------------------


def test_rel_type_key_str_form():
    """__str__ is the 'source:LABEL:target' form."""
    k = RelTypeKey(source_label="Person", label="KNOWS", target_label="Person")
    assert str(k) == "Person:KNOWS:Person"


def test_rel_type_key_str_deterministic():
    """Same inputs always produce the same __str__ output."""
    k1 = RelTypeKey(source_label="Person", label="KNOWS", target_label="Company")
    k2 = RelTypeKey(source_label="Person", label="KNOWS", target_label="Company")
    assert str(k1) == str(k2)


def test_rel_type_key_str_distinguishes_endpoints():
    """Same label, different endpoints produce different strings (the whole point)."""
    k1 = RelTypeKey(source_label="Person", label="KNOWS", target_label="Person")
    k2 = RelTypeKey(source_label="Company", label="KNOWS", target_label="Company")
    assert str(k1) != str(k2)


def test_rel_type_key_parse_round_trips():
    """parse(str(k)) == k for representative triples."""
    for k in (
        RelTypeKey(source_label="Person", label="KNOWS", target_label="Person"),
        RelTypeKey(source_label="Company", label="KNOWS", target_label="Company"),
        RelTypeKey(source_label="Person", label="ACTED_IN", target_label="Movie"),
        RelTypeKey(source_label="_A", label="R0", target_label="B_1"),
    ):
        assert RelTypeKey.parse(str(k)) == k


def test_rel_type_key_parse_returns_fields():
    """parse recovers each part exactly."""
    k = RelTypeKey.parse("Person:ACTED_IN:Movie")
    assert k.source_label == "Person"
    assert k.label == "ACTED_IN"
    assert k.target_label == "Movie"


def test_rel_type_key_frozen():
    """RelTypeKey is immutable."""
    import pytest
    from pydantic import ValidationError

    k = RelTypeKey(source_label="Person", label="KNOWS", target_label="Person")
    with pytest.raises(ValidationError):
        k.label = "LIKES"  # type: ignore[misc]


def test_rel_type_key_round_trips_as_dict_key():
    """str(RelTypeKey) is a usable, recoverable dict key."""
    k = RelTypeKey(source_label="Person", label="KNOWS", target_label="Company")
    d = {str(k): "value"}
    assert str(k) in d
    assert RelTypeKey.parse(next(iter(d))) == k


def test_rel_type_key_parse_rejects_too_few_parts():
    """A string with fewer than two delimiters is malformed."""
    import pytest

    with pytest.raises(ValueError):
        RelTypeKey.parse("Person:KNOWS")


def test_rel_type_key_parse_rejects_too_many_parts():
    """A string with more than two delimiters is malformed (would mis-split)."""
    import pytest

    with pytest.raises(ValueError):
        RelTypeKey.parse("Person:KNOWS:Person:extra")


def test_rel_type_key_parse_rejects_empty_part():
    """An empty part silently mis-identifies a type — reject it."""
    import pytest

    for bad in ("Person:KNOWS:", ":KNOWS:Person", "Person::Person"):
        with pytest.raises(ValueError):
            RelTypeKey.parse(bad)
