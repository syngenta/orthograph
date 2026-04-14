"""Tests for NetworkxInspector."""

import networkx as nx
import pytest

from orthograph.extensions.networkx import NetworkxInspector


def _make_graph() -> nx.MultiDiGraph:
    """Helper to create a fresh empty MultiDiGraph."""
    return nx.MultiDiGraph()


def test_inspect_empty_graph():
    g = _make_graph()
    profile = NetworkxInspector(g).inspect()

    assert profile.source == "networkx"
    assert profile.node_type_profiles == {}
    assert profile.rel_type_profiles == {}


def test_inspect_nodes_only():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice", age=30)
    g.add_node("b", __label__="Movie", title="Inception", year=2010)

    profile = NetworkxInspector(g).inspect()

    assert "Person" in profile.node_type_profiles
    assert "Movie" in profile.node_type_profiles
    assert profile.rel_type_profiles == {}


def test_inspect_node_count():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice")
    g.add_node("b", __label__="Person", name="Bob")
    g.add_node("c", __label__="Person", name="Charlie")
    g.add_node("m1", __label__="Movie", title="X")

    profile = NetworkxInspector(g).inspect()

    assert profile.node_type_profiles["Person"].count == 3
    assert profile.node_type_profiles["Movie"].count == 1


def test_inspect_property_completeness():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice", age=30, email="a@b.com")
    g.add_node("b", __label__="Person", name="Bob", age=25)
    g.add_node("c", __label__="Person", name="Charlie")

    profile = NetworkxInspector(g).inspect()
    props = profile.node_type_profiles["Person"].property_profiles

    assert props["name"].present_count == 3
    assert props["name"].total_count == 3
    assert props["name"].completeness == 1.0

    assert props["age"].present_count == 2
    assert props["age"].total_count == 3

    assert props["email"].present_count == 1
    assert props["email"].total_count == 3
    assert props["email"].completeness == pytest.approx(1 / 3)


def test_inspect_property_types():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice", age=30)
    g.add_node("b", __label__="Person", name="Bob", age=25)

    profile = NetworkxInspector(g).inspect()
    props = profile.node_type_profiles["Person"].property_profiles

    assert "str" in props["name"].observed_types
    assert "int" in props["age"].observed_types


def test_inspect_relationships():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice")
    g.add_node("m1", __label__="Movie", title="X")
    g.add_node("m2", __label__="Movie", title="Y")
    g.add_edge("a", "m1", __label__="ACTED_IN", role="Lead")
    g.add_edge("a", "m2", __label__="ACTED_IN", role="Extra")
    g.add_edge("a", "m1", __label__="DIRECTED")

    profile = NetworkxInspector(g).inspect()

    assert "ACTED_IN" in profile.rel_type_profiles
    assert "DIRECTED" in profile.rel_type_profiles
    assert profile.rel_type_profiles["ACTED_IN"].count == 2
    assert profile.rel_type_profiles["DIRECTED"].count == 1


def test_inspect_rel_source_target_labels():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice")
    g.add_node("m1", __label__="Movie", title="X")
    g.add_edge("a", "m1", __label__="ACTED_IN", role="Lead")

    profile = NetworkxInspector(g).inspect()
    rel = profile.rel_type_profiles["ACTED_IN"]

    assert rel.source_labels == {"Person"}
    assert rel.target_labels == {"Movie"}


def test_inspect_cardinality_stats():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice")
    g.add_node("b", __label__="Person", name="Bob")
    g.add_node("m1", __label__="Movie", title="X")
    g.add_node("m2", __label__="Movie", title="Y")
    g.add_node("m3", __label__="Movie", title="Z")
    # Alice -> 3 movies, Bob -> 1 movie
    g.add_edge("a", "m1", __label__="ACTED_IN")
    g.add_edge("a", "m2", __label__="ACTED_IN")
    g.add_edge("a", "m3", __label__="ACTED_IN")
    g.add_edge("b", "m1", __label__="ACTED_IN")

    profile = NetworkxInspector(g).inspect()
    stats = profile.rel_type_profiles["ACTED_IN"].cardinality_stats

    assert stats is not None
    assert stats.min_degree == 1
    assert stats.max_degree == 3
    assert stats.avg_degree == pytest.approx(2.0)
    assert stats.sample_size == 2


def test_inspect_full_graph():
    g = _make_graph()
    # Nodes
    g.add_node("a", __label__="Person", name="Alice", age=30)
    g.add_node("b", __label__="Person", name="Bob", age=25)
    g.add_node("m1", __label__="Movie", title="Inception", year=2010)
    g.add_node("m2", __label__="Movie", title="Matrix", year=1999)
    g.add_node("c1", __label__="City", name="London")
    # Edges
    g.add_edge("a", "m1", __label__="ACTED_IN", role="Cobb")
    g.add_edge("a", "m2", __label__="ACTED_IN", role="Trinity")
    g.add_edge("b", "m1", __label__="ACTED_IN", role="Arthur")
    g.add_edge("a", "m1", __label__="DIRECTED")
    g.add_edge("a", "c1", __label__="LIVES_IN")

    profile = NetworkxInspector(g).inspect()

    # Node profiles
    assert set(profile.node_labels) == {"Person", "Movie", "City"}
    assert profile.node_type_profiles["Person"].count == 2
    assert profile.node_type_profiles["Movie"].count == 2
    assert profile.node_type_profiles["City"].count == 1

    # Relationship profiles
    assert set(profile.relationship_types) == {"ACTED_IN", "DIRECTED", "LIVES_IN"}
    assert profile.rel_type_profiles["ACTED_IN"].count == 3
    assert profile.rel_type_profiles["DIRECTED"].count == 1
    assert profile.rel_type_profiles["LIVES_IN"].count == 1

    # Property profile on relationships
    acted_in_props = profile.rel_type_profiles["ACTED_IN"].property_profiles
    assert "role" in acted_in_props
    assert acted_in_props["role"].present_count == 3

    # Cardinality
    acted_in_stats = profile.rel_type_profiles["ACTED_IN"].cardinality_stats
    assert acted_in_stats is not None
    assert acted_in_stats.min_degree == 1  # Bob has 1
    assert acted_in_stats.max_degree == 2  # Alice has 2
