"""Tests for the vendor-free constraint cross-reference."""

from orthograph.graph_profile.constraints import is_presence_constraint_for
from orthograph.graph_profile.models import ConstraintInfo


def _existence(label: str, prop: str, entity_type: str = "NODE") -> ConstraintInfo:
    return ConstraintInfo(
        name=None,
        constraint_type="NODE_PROPERTY_EXISTENCE",
        entity_type=entity_type,
        labels=[label],
        properties=[prop],
    )


def test_node_existence_constraint_matches_property():
    constraints = [_existence("Person", "name")]
    assert is_presence_constraint_for(constraints, "NODE", "Person", "name") is True


def test_uniqueness_alone_is_not_a_presence_constraint():
    constraints = [
        ConstraintInfo(
            name=None,
            constraint_type="UNIQUENESS",
            entity_type="NODE",
            labels=["Person"],
            properties=["name"],
        )
    ]
    assert is_presence_constraint_for(constraints, "NODE", "Person", "name") is False


def test_node_key_constraint_implies_presence():
    constraints = [
        ConstraintInfo(
            name=None,
            constraint_type="NODE_KEY",
            entity_type="NODE",
            labels=["Person"],
            properties=["name"],
        )
    ]
    assert is_presence_constraint_for(constraints, "NODE", "Person", "name") is True


def test_memgraph_exists_constraint_implies_presence():
    constraints = [
        ConstraintInfo(
            name=None,
            constraint_type="EXISTS",
            entity_type="NODE",
            labels=["Person"],
            properties=["name"],
        )
    ]
    assert is_presence_constraint_for(constraints, "NODE", "Person", "name") is True


def test_no_matching_property_is_false():
    constraints = [_existence("Person", "name")]
    assert is_presence_constraint_for(constraints, "NODE", "Person", "age") is False


def test_no_matching_label_is_false():
    constraints = [_existence("Person", "name")]
    assert is_presence_constraint_for(constraints, "NODE", "Movie", "name") is False


def test_wrong_entity_type_is_false():
    """A node existence constraint does not cover a relationship property."""
    constraints = [_existence("Person", "name")]
    assert (
        is_presence_constraint_for(constraints, "RELATIONSHIP", "Person", "name")
        is False
    )


def test_relationship_existence_constraint_matches():
    constraints = [
        ConstraintInfo(
            name=None,
            constraint_type="RELATIONSHIP_PROPERTY_EXISTENCE",
            entity_type="RELATIONSHIP",
            labels=["ACTED_IN"],
            properties=["role"],
        )
    ]
    assert (
        is_presence_constraint_for(constraints, "RELATIONSHIP", "ACTED_IN", "role")
        is True
    )


def test_empty_constraints_is_false():
    assert is_presence_constraint_for([], "NODE", "Person", "name") is False
