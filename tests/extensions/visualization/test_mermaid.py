"""Tests for orthograph.extensions.visualization.mermaid."""

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.extensions.visualization import to_mermaid


class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    age: int


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    year: int


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_type__ = Person
    __target_type__ = Movie
    role: str


class Directed(RelationshipModel):
    __label__ = "DIRECTED"
    __source_type__ = Person
    __target_type__ = Movie
    __directed__ = True


class FriendOf(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_type__ = Person
    __target_type__ = Person
    __directed__ = False


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )


@pytest.fixture()
def undirected_model() -> GraphDataModel:
    return GraphDataModel(
        name="Social",
        node_types=[Person],
        relationship_types=[FriendOf],
    )


def test_mermaid_basic(model: GraphDataModel):
    mermaid = to_mermaid(model)
    assert "graph TD" in mermaid
    assert "Person" in mermaid
    assert "Movie" in mermaid
    assert "ACTED_IN" in mermaid
    assert "DIRECTED" in mermaid


def test_mermaid_directed_arrow(model: GraphDataModel):
    mermaid = to_mermaid(model)
    assert "-->" in mermaid


def test_mermaid_undirected_arrow(
    undirected_model: GraphDataModel,
):
    mermaid = to_mermaid(undirected_model)
    assert "---" in mermaid


def test_mermaid_node_properties(model: GraphDataModel):
    mermaid = to_mermaid(model)
    assert "name" in mermaid
    assert "age" in mermaid


# --- Undirected relationship Mermaid tests ---


class Company(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


class Collaborates(RelationshipModel):
    __label__ = "COLLABORATES"
    __source_type__ = Person
    __target_type__ = Company
    __directed__ = False


def test_mermaid_undirected_cross_type():
    """Undirected cross-type relationship uses '---' arrow."""
    m = GraphDataModel(
        name="Cross",
        node_types=[Person, Company],
        relationship_types=[Collaborates],
    )
    mermaid = to_mermaid(m)
    assert "---" in mermaid
    assert "-->" not in mermaid
    assert "Person" in mermaid
    assert "Company" in mermaid
    assert "COLLABORATES" in mermaid


def test_mermaid_mixed_directed_and_undirected():
    """Model with both directed and undirected uses correct arrows."""
    m = GraphDataModel(
        name="Mixed",
        node_types=[Person, Movie, Company],
        relationship_types=[ActedIn, FriendOf, Collaborates],
    )
    mermaid = to_mermaid(m)
    # Should contain both arrow types
    assert "---" in mermaid
    assert "-->" in mermaid
