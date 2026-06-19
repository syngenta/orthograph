"""Shared filmography domain model for tutorial notebooks."""

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    NodeModel,
    RelationshipModel,
)


class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    born: int | None = None


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    released: int | None = None
    year: int | None = None  # Alias for released, used in notebooks


class City(NodeModel):
    __label__ = "City"
    __uid_field__ = "name"
    name: str


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    __directed__ = True
    role: str


class Directed(RelationshipModel):
    __label__ = "DIRECTED"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    __directed__ = True


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "City"
    __directed__ = True


# Reference GraphDefinition
FILMOGRAPHY_MODEL = GraphDefinition(
    name="Filmography",
    node_types=[Person, Movie, City],
    relationship_types=[ActedIn, Directed, LivesIn],
)
