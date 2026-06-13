"""Shared test fixtures for comparison tests."""

from typing import Optional

import pytest

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    Cardinality,
    NodeModel,
    RelationshipModel,
)


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


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    role: str


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "City"
    __source_cardinality__ = Cardinality.ONE
    __target_cardinality__ = Cardinality.ZERO_OR_MORE


class Directed(RelationshipModel):
    __label__ = "DIRECTED"
    __source_label__ = "Person"
    __target_label__ = "Movie"


@pytest.fixture()
def filmography_model() -> GraphDefinition:
    return GraphDefinition(
        name="Filmography",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn, LivesIn, Directed],
    )
