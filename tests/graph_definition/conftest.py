"""Shared node/relationship classes and pytest fixtures for graph_definition tests."""

from typing import Optional

import pytest

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    NodeModel,
    RelationshipModel,
)


# ---------------------------------------------------------------------------
# Node models
# ---------------------------------------------------------------------------


class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    age: int
    email: Optional[str] = None


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    year: int


class City(NodeModel):
    __label__ = "City"
    __uid_field__ = "name"
    name: str


# ---------------------------------------------------------------------------
# Relationship models
# (ActedIn uses explicit cardinalities; Directed / LivesIn are
#  the same on all three test files so defined once here.)
# ---------------------------------------------------------------------------


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    __source_cardinality__ = "0..*"
    __target_cardinality__ = "0..*"

    role: str


class Directed(RelationshipModel):
    __label__ = "DIRECTED"
    __source_label__ = "Person"
    __target_label__ = "Movie"


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "City"
    __source_cardinality__ = "1..1"
    __target_cardinality__ = "0..*"


# ---------------------------------------------------------------------------
# Undirected-relationship models (used by both graph_definition and
# validation tests for the undirected test sections)
# ---------------------------------------------------------------------------


class Company(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


class FriendOf(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_label__ = "Person"
    __target_label__ = "Person"
    __directed__ = False
    __source_cardinality__ = "0..*"


class Collaborates(RelationshipModel):
    __label__ = "COLLABORATES"
    __source_label__ = "Person"
    __target_label__ = "Company"
    __directed__ = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def filmography_model() -> GraphDefinition:
    """Minimal filmography: Person + Movie, ActedIn + Directed (no City/LivesIn)."""
    return GraphDefinition(
        name="Filmography",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )


@pytest.fixture()
def full_model() -> GraphDefinition:
    """Full filmography: Person + Movie + City, ActedIn + Directed + LivesIn."""
    return GraphDefinition(
        name="Full",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn, Directed, LivesIn],
    )


@pytest.fixture()
def social_model() -> GraphDefinition:
    """Social graph: Person + FriendOf (undirected, self-referencing)."""
    return GraphDefinition(
        name="Social",
        node_types=[Person],
        relationship_types=[FriendOf],
    )


@pytest.fixture()
def cross_undirected_model() -> GraphDefinition:
    """Cross-type undirected graph: Person + Company, Collaborates."""
    return GraphDefinition(
        name="CrossUndirected",
        node_types=[Person, Company],
        relationship_types=[Collaborates],
    )
