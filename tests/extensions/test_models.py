"""Tests for orthograph.extensions.models -- GraphProfile and sub-models."""

from datetime import datetime

from orthograph.extensions.models import (
    CardinalityStats,
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)


# --- PropertyProfile ---


def test_property_profile_completeness():
    p = PropertyProfile(name="age", present_count=80, total_count=100)
    assert p.completeness == 0.8
    assert p.missing_count == 20
    assert p.is_mandatory is False


def test_property_profile_fully_complete():
    p = PropertyProfile(name="name", present_count=100, total_count=100)
    assert p.completeness == 1.0
    assert p.missing_count == 0
    assert p.is_mandatory is True


def test_property_profile_empty():
    p = PropertyProfile(name="x", present_count=0, total_count=0)
    assert p.completeness == 0.0
    assert p.is_mandatory is False


def test_property_profile_observed_types():
    p = PropertyProfile(
        name="val",
        present_count=10,
        total_count=10,
        observed_types=["String", "Long"],
    )
    assert p.observed_types == ["String", "Long"]


def test_property_profile_frozen():
    import pytest
    from pydantic import ValidationError

    p = PropertyProfile(name="x", present_count=1, total_count=1)
    with pytest.raises(ValidationError):
        p.name = "y"  # type: ignore[misc]


# --- CardinalityStats ---


def test_cardinality_stats():
    c = CardinalityStats(min_degree=0, max_degree=5, avg_degree=2.3, sample_size=100)
    assert c.min_degree == 0
    assert c.max_degree == 5
    assert c.avg_degree == 2.3
    assert c.sample_size == 100


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
    stats = CardinalityStats(
        min_degree=1, max_degree=10, avg_degree=3.5, sample_size=50
    )
    r = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=200,
        source_labels={"Person"},
        target_labels={"Movie"},
        cardinality_stats=stats,
    )
    assert r.cardinality_stats is not None
    assert r.cardinality_stats.avg_degree == 3.5


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
