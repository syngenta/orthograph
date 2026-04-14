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
