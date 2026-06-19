"""Tests for schema_to_networkx conversion."""

import networkx as nx
import pytest

from orthograph.backends.networkx.conversion import schema_to_networkx
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
    RelationshipModel,
)
from tests.fixtures.conftest import ActedIn, Directed, Movie, Person


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )


def test_schema_to_networkx_convert(graph_definition: GraphDefinition):
    g = schema_to_networkx(graph_definition)
    assert isinstance(g, nx.MultiDiGraph)
    assert "Person" in g.nodes
    assert "Movie" in g.nodes


def test_schema_to_networkx_edges_are_relationship_types(
    graph_definition: GraphDefinition,
):
    g = schema_to_networkx(graph_definition)
    edge_labels = {data["label"] for _, _, data in g.edges(data=True)}
    assert "ACTED_IN" in edge_labels
    assert "DIRECTED" in edge_labels


def test_schema_to_networkx_node_attributes(graph_definition: GraphDefinition):
    g = schema_to_networkx(graph_definition)
    assert g.nodes["Person"]["uid_field"] == "name"
    assert "name" in g.nodes["Person"]["properties"]


# --- Undirected relationship NetworkX tests ---


class FriendOf(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_label__ = "Person"
    __target_label__ = "Person"
    __directed__ = False


class Company(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


class Collaborates(RelationshipModel):
    __label__ = "COLLABORATES"
    __source_label__ = "Person"
    __target_label__ = "Company"
    __directed__ = False


@pytest.fixture()
def undirected_model() -> GraphDefinition:
    return GraphDefinition(
        name="Undirected",
        node_types=[Person, Company],
        relationship_types=[FriendOf, Collaborates],
    )


def test_schema_to_networkx_undirected_edge_metadata(
    undirected_model: GraphDefinition,
):
    """Undirected relationships store directed=False in edge metadata."""
    g = schema_to_networkx(undirected_model)
    edge_data = [data for _, _, data in g.edges(data=True)]
    friend_of_edges = [d for d in edge_data if d["label"] == "FRIEND_OF"]
    assert len(friend_of_edges) == 1
    assert friend_of_edges[0]["directed"] is False


def test_schema_to_networkx_directed_edge_metadata(graph_definition: GraphDefinition):
    """Directed relationships store directed=True in edge metadata."""
    g = schema_to_networkx(graph_definition)
    edge_data = [data for _, _, data in g.edges(data=True)]
    acted_in_edges = [d for d in edge_data if d["label"] == "ACTED_IN"]
    assert len(acted_in_edges) == 1
    assert acted_in_edges[0]["directed"] is True


def test_schema_to_networkx_undirected_cross_type(
    undirected_model: GraphDefinition,
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


# ============================================================
# Conditional cardinality tests
# ============================================================


class Operation(NodeModel):
    """Test node type for conditional cardinality."""

    __label__ = "Operation"
    __uid_field__ = "id"
    id: str
    kind: str


class Sample(NodeModel):
    """Test node type for conditional cardinality."""

    __label__ = "Sample"
    __uid_field__ = "id"
    id: str
    kind: str


class HasOutput(RelationshipModel):
    """Test relationship with conditional cardinality."""

    __label__ = "HAS_OUTPUT"
    __source_label__ = "Operation"
    __target_label__ = "Sample"
    __source_cardinality__ = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch({"kind": "subsampling"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
            ConditionalRule(
                source=PropMatch({"kind": "split"}),
                target=PropMatch({"kind": "nothing"}),
                spec="0..0",
            ),
        ),
        default="0..*",
    )


def test_schema_to_networkx_conditional_cardinality_stringifies():
    """Scope: Stringify conditional cardinality in schema_to_networkx."""
    m = GraphDefinition(
        name="ConditionalTest",
        node_types=[Operation, Sample],
        relationship_types=[HasOutput],
    )
    g = schema_to_networkx(m)
    # The edge should have a cardinality that stringifies successfully
    edge_data = [data for _, _, data in g.edges(data=True)]
    assert len(edge_data) > 0
    # Find the HAS_OUTPUT edge
    has_output_edges = [d for d in edge_data if d["label"] == "HAS_OUTPUT"]
    assert len(has_output_edges) > 0
    # The source_cardinality should be a string (not raise)
    card_str = has_output_edges[0]["source_cardinality"]
    assert isinstance(card_str, str)
    # Should contain some indication of being conditional (brace or "default")
    assert "{" in card_str or "default" in card_str
