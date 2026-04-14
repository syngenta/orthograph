"""Tests for schema_to_networkx conversion."""

import networkx as nx
import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.extensions.networkx import schema_to_networkx


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


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )


def test_schema_to_networkx_convert(model: GraphDataModel):
    g = schema_to_networkx(model)
    assert isinstance(g, nx.MultiDiGraph)
    assert "Person" in g.nodes
    assert "Movie" in g.nodes


def test_schema_to_networkx_edges_are_relationship_types(model: GraphDataModel):
    g = schema_to_networkx(model)
    edge_labels = {data["label"] for _, _, data in g.edges(data=True)}
    assert "ACTED_IN" in edge_labels
    assert "DIRECTED" in edge_labels


def test_schema_to_networkx_node_attributes(model: GraphDataModel):
    g = schema_to_networkx(model)
    assert g.nodes["Person"]["uid_field"] == "name"
    assert "name" in g.nodes["Person"]["properties"]


# --- Undirected relationship NetworkX tests ---


class FriendOf(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_type__ = Person
    __target_type__ = Person
    __directed__ = False


class Company(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


class Collaborates(RelationshipModel):
    __label__ = "COLLABORATES"
    __source_type__ = Person
    __target_type__ = Company
    __directed__ = False


@pytest.fixture()
def undirected_model() -> GraphDataModel:
    return GraphDataModel(
        name="Undirected",
        node_types=[Person, Company],
        relationship_types=[FriendOf, Collaborates],
    )


def test_schema_to_networkx_undirected_edge_metadata(
    undirected_model: GraphDataModel,
):
    """Undirected relationships store directed=False in edge metadata."""
    g = schema_to_networkx(undirected_model)
    edge_data = [data for _, _, data in g.edges(data=True)]
    friend_of_edges = [d for d in edge_data if d["label"] == "FRIEND_OF"]
    assert len(friend_of_edges) == 1
    assert friend_of_edges[0]["directed"] is False


def test_schema_to_networkx_directed_edge_metadata(model: GraphDataModel):
    """Directed relationships store directed=True in edge metadata."""
    g = schema_to_networkx(model)
    edge_data = [data for _, _, data in g.edges(data=True)]
    acted_in_edges = [d for d in edge_data if d["label"] == "ACTED_IN"]
    assert len(acted_in_edges) == 1
    assert acted_in_edges[0]["directed"] is True


def test_schema_to_networkx_undirected_cross_type(
    undirected_model: GraphDataModel,
):
    """Undirected cross-type relationship connects correct nodes."""
    g = schema_to_networkx(undirected_model)
    collab_edges = [
        (u, v, d) for u, v, d in g.edges(data=True) if d["label"] == "COLLABORATES"
    ]
    assert len(collab_edges) == 1
    u, v, d = collab_edges[0]
    assert {u, v} == {"Person", "Company"}
    assert d["directed"] is False
