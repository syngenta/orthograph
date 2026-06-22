"""Tests for orthograph.graph_profile.models -- GraphProfile and sub-models."""

import math
from datetime import datetime

from orthograph.graph_profile.models import (
    BoundedDistribution,
    CardinalityStats,
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PartitionKey,
    PropertyProfile,
    RelationshipTypeProfile,
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
        source_labels={"Person"},
        target_labels={"Movie"},
    )
    assert r.rel_type == "ACTED_IN"
    assert r.count == 200
    assert r.source_labels == {"Person"}
    assert r.cardinality_stats is None


def test_relationship_type_profile_with_cardinality():
    stats = CardinalityStats(count=50, min=1.0, max=10.0, mean=3.5)
    r = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=200,
        source_labels={"Person"},
        target_labels={"Movie"},
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
    profile = GraphProfile(
        source="networkx",
        node_type_profiles={
            "Person": NodeTypeProfile(label="Person", count=10),
            "Movie": NodeTypeProfile(label="Movie", count=5),
        },
        rel_type_profiles={
            "ACTED_IN": RelationshipTypeProfile(
                rel_type="ACTED_IN",
                count=20,
                source_labels={"Person"},
                target_labels={"Movie"},
            ),
        },
    )
    assert profile.node_labels == {"Person", "Movie"}
    assert profile.relationship_types == {"ACTED_IN"}


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
            "ACTED_IN": RelationshipTypeProfile(
                rel_type="ACTED_IN",
                count=200,
                source_labels={"Person"},
                target_labels={"Movie"},
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
    rel = restored.rel_type_profiles["ACTED_IN"]
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


# --- PartitionKey ---


def test_partition_key_str_both_values():
    """__str__ encodes both non-None values deterministically."""
    k = PartitionKey(source_value="subsampling", target_value="Sample")
    s = str(k)
    assert "subsampling" in s
    assert "Sample" in s


def test_partition_key_str_null_source():
    """None source_value is represented as the literal 'null' in __str__."""
    k = PartitionKey(source_value=None, target_value="Sample")
    s = str(k)
    assert "null" in s
    assert "Sample" in s


def test_partition_key_str_null_target():
    """None target_value is represented as the literal 'null' in __str__."""
    k = PartitionKey(source_value="Operation", target_value=None)
    s = str(k)
    assert "Operation" in s
    assert "null" in s


def test_partition_key_str_both_null():
    """Both None values produce a stable, recognisable string."""
    k = PartitionKey(source_value=None, target_value=None)
    s = str(k)
    assert s  # non-empty
    assert "null" in s


def test_partition_key_str_deterministic():
    """Same inputs always produce the same __str__ output."""
    k1 = PartitionKey(source_value="A", target_value="B")
    k2 = PartitionKey(source_value="A", target_value="B")
    assert str(k1) == str(k2)


def test_partition_key_str_different_values_differ():
    """Different (src, tgt) pairs produce different strings."""
    k1 = PartitionKey(source_value="A", target_value="B")
    k2 = PartitionKey(source_value="B", target_value="A")
    assert str(k1) != str(k2)


def test_partition_key_frozen():
    """PartitionKey is immutable."""
    import pytest
    from pydantic import ValidationError

    k = PartitionKey(source_value="x", target_value="y")
    with pytest.raises(ValidationError):
        k.source_value = "z"  # type: ignore[misc]


def test_partition_key_round_trips_as_dict_key():
    """str(PartitionKey) can be used as a dict key and recovered."""
    k = PartitionKey(source_value="subsampling", target_value="Sample")
    key_str = str(k)
    d = {key_str: CardinalityStats(count=10, min=1.0, max=3.0)}
    assert key_str in d


# --- per-side partitioned cardinality on RelationshipTypeProfile ---


def test_relationship_type_profile_partitioned_cardinality_defaults_none():
    """Both per-side breakdowns default to None (non-conditional unchanged)."""
    r = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=200,
        source_labels={"Person"},
        target_labels={"Movie"},
    )
    assert r.source_partitioned_cardinality is None
    assert r.target_partitioned_cardinality is None


def test_relationship_type_profile_with_partitioned_cardinality():
    """A profile with two partitions carries the expected BoundedDistribution values."""
    k1 = PartitionKey(source_value="subsampling", target_value="Sample")
    k2 = PartitionKey(source_value="nothing", target_value="Sample")
    partitions = {
        str(k1): BoundedDistribution(count=10, min=2.0, max=2.0, mean=2.0),
        str(k2): BoundedDistribution(count=5, min=0.0, max=0.0, mean=0.0),
    }
    r = RelationshipTypeProfile(
        rel_type="PRODUCES",
        count=15,
        source_labels={"Operation"},
        target_labels={"Sample"},
        source_partitioned_cardinality=partitions,
    )
    assert r.source_partitioned_cardinality is not None
    assert len(r.source_partitioned_cardinality) == 2
    assert r.source_partitioned_cardinality[str(k1)].min == 2.0
    assert r.source_partitioned_cardinality[str(k2)].max == 0.0


def test_relationship_type_profile_both_sides_independent_no_collision():
    """Both per-side breakdowns coexist without colliding on the same key.

    The same ``str(PartitionKey)`` may appear on both sides with different degree
    distributions (source-counted vs target-counted); the two named fields keep
    them separate.
    """
    k = PartitionKey(source_value="subsampling", target_value="subsampling")
    r = RelationshipTypeProfile(
        rel_type="HAS_OUTPUT",
        count=4,
        source_labels={"Operation"},
        target_labels={"Sample"},
        source_partitioned_cardinality={
            str(k): BoundedDistribution(count=1, min=2.0, max=2.0)
        },
        target_partitioned_cardinality={
            str(k): BoundedDistribution(count=2, min=1.0, max=1.0)
        },
    )
    assert r.source_partitioned_cardinality is not None
    assert r.target_partitioned_cardinality is not None
    # Same key, distinct distributions — no collision.
    assert r.source_partitioned_cardinality[str(k)].max == 2.0
    assert r.target_partitioned_cardinality[str(k)].max == 1.0
    restored = RelationshipTypeProfile.model_validate(r.model_dump())
    assert restored == r


def test_relationship_type_profile_partitioned_cardinality_round_trip():
    """A per-side breakdown round-trips through model_dump/model_validate.

    The field is typed on ``BoundedDistribution`` (not the ``CardinalityStats``
    marker subclass), so storing ``BoundedDistribution`` makes the round-trip
    lossless and equality-preserving.  See
    ``test_relationship_type_profile_cardinality_stats_partition_loses_subtype``
    for why a ``CardinalityStats`` value must not be stored here.
    """
    k1 = PartitionKey(source_value="subsampling", target_value="Sample")
    k2 = PartitionKey(source_value=None, target_value="Sample")
    partitions: dict[str, BoundedDistribution] = {
        str(k1): BoundedDistribution(count=10, min=2.0, max=2.0),
        str(k2): BoundedDistribution(count=3, min=0.0, max=1.0),
    }
    r = RelationshipTypeProfile(
        rel_type="PRODUCES",
        count=13,
        source_labels={"Operation"},
        target_labels={"Sample"},
        cardinality_stats=CardinalityStats(count=13, min=0.0, max=2.0),
        source_partitioned_cardinality=partitions,
    )
    d = r.model_dump()
    restored = RelationshipTypeProfile.model_validate(d)
    assert restored == r
    assert restored.source_partitioned_cardinality is not None
    assert len(restored.source_partitioned_cardinality) == 2


def test_relationship_type_profile_cardinality_stats_partition_loses_subtype():
    """Storing a CardinalityStats partition is not round-trip-stable.

    ``CardinalityStats`` is a marker subclass that adds no fields; the field is
    typed on ``BoundedDistribution``, so Pydantic restores the base type on
    reload.  This test pins the documented contract (store ``BoundedDistribution``,
    not ``CardinalityStats``) so a future regression that silently relies on
    subtype identity is caught.
    """
    k = PartitionKey(source_value="A", target_value="B")
    r = RelationshipTypeProfile(
        rel_type="REL",
        count=5,
        source_partitioned_cardinality={
            str(k): CardinalityStats(count=5, min=1.0, max=3.0)
        },
    )
    restored = RelationshipTypeProfile.model_validate(r.model_dump())
    assert restored.source_partitioned_cardinality is not None
    # Data is preserved (CardinalityStats adds no fields)...
    assert restored.source_partitioned_cardinality[str(k)].min == 1.0
    assert restored.source_partitioned_cardinality[str(k)].max == 3.0
    # ...but the subtype is not, hence the field/inspectors use BoundedDistribution.
    assert type(restored.source_partitioned_cardinality[str(k)]) is BoundedDistribution


def test_partitioned_cardinality_accepts_bounded_distribution():
    """Field type is BoundedDistribution — plain BoundedDistribution is accepted."""
    k = PartitionKey(source_value="A", target_value="B")
    partitions: dict[str, BoundedDistribution] = {
        str(k): BoundedDistribution(count=5, min=1.0, max=3.0),
    }
    r = RelationshipTypeProfile(
        rel_type="REL",
        count=5,
        source_partitioned_cardinality=partitions,
    )
    assert r.source_partitioned_cardinality is not None
    assert isinstance(r.source_partitioned_cardinality[str(k)], BoundedDistribution)


def test_relationship_type_profile_existing_aggregate_unaffected():
    """cardinality_stats (aggregate) is unaffected when a per-side breakdown is
    also set."""
    agg = CardinalityStats(count=15, min=0.0, max=2.0, mean=1.0)
    k = PartitionKey(source_value="A", target_value="B")
    r = RelationshipTypeProfile(
        rel_type="REL",
        count=15,
        cardinality_stats=agg,
        source_partitioned_cardinality={
            str(k): BoundedDistribution(count=10, min=1.0, max=2.0)
        },
    )
    assert r.cardinality_stats == agg
    assert r.source_partitioned_cardinality is not None
