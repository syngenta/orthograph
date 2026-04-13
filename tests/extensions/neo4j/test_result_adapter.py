"""Tests for orthograph.extensions.neo4j.result_adapter."""

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.extensions.neo4j import (
    node_to_dict,
    records_to_graph_data,
    rel_to_dict,
    validate_result,
)


# --- Fixtures ---


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


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_type__ = Person
    __target_type__ = Movie
    role: str


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )


def _mock_node(
    labels: frozenset[str],
    properties: dict[str, Any],
    element_id: str = "eid:1",
) -> MagicMock:
    """Create a mock neo4j Node."""
    node = MagicMock()
    node.labels = labels
    node.element_id = element_id
    node.__iter__ = MagicMock(return_value=iter(properties.keys()))
    node.__getitem__ = MagicMock(side_effect=properties.__getitem__)
    node.get = MagicMock(side_effect=properties.get)
    node.items = MagicMock(return_value=properties.items())
    node.keys = MagicMock(return_value=properties.keys())

    # Make dict(node) work
    node.__iter__ = MagicMock(return_value=iter(properties.keys()))
    node.__len__ = MagicMock(return_value=len(properties))

    # For isinstance checks in the code, we tag it
    node._is_neo4j_node = True
    return node


def _mock_rel(
    rel_type: str,
    properties: dict[str, Any],
    start_node: MagicMock | None = None,
    end_node: MagicMock | None = None,
    element_id: str = "eid:r1",
) -> MagicMock:
    """Create a mock neo4j Relationship."""
    rel = MagicMock()
    rel.type = rel_type
    rel.element_id = element_id
    rel.start_node = start_node
    rel.end_node = end_node
    # Explicitly mark as NOT a node
    rel.labels = None
    rel.__iter__ = MagicMock(return_value=iter(properties.keys()))
    rel.__getitem__ = MagicMock(side_effect=properties.__getitem__)
    rel.get = MagicMock(side_effect=properties.get)
    rel.items = MagicMock(return_value=properties.items())
    rel.keys = MagicMock(return_value=properties.keys())
    rel.__len__ = MagicMock(return_value=len(properties))
    return rel


def _mock_record(values: dict[str, Any]) -> MagicMock:
    """Create a mock neo4j Record."""
    record = MagicMock()
    record.__getitem__ = MagicMock(side_effect=values.__getitem__)
    record.keys = MagicMock(return_value=list(values.keys()))
    record.values = MagicMock(return_value=list(values.values()))
    record.items = MagicMock(return_value=list(values.items()))
    return record


# --- node_to_dict tests ---


def test_node_to_dict_single_label(model: GraphDataModel):
    node = _mock_node(
        frozenset({"Person"}),
        {"name": "Alice", "age": 30},
    )
    d = node_to_dict(node, model)
    assert d["__label__"] == "Person"
    assert d["name"] == "Alice"
    assert d["age"] == 30


def test_node_to_dict_multi_label_picks_matching(
    model: GraphDataModel,
):
    node = _mock_node(
        frozenset({"Person", "Employee"}),
        {"name": "Alice", "age": 30},
    )
    d = node_to_dict(node, model)
    assert d["__label__"] == "Person"


def test_node_to_dict_no_matching_label(model: GraphDataModel):
    node = _mock_node(
        frozenset({"Animal"}),
        {"species": "Cat"},
    )
    d = node_to_dict(node, model)
    assert d["__label__"] == "Animal"


# --- rel_to_dict tests ---


def test_rel_to_dict(model: GraphDataModel):
    start = _mock_node(
        frozenset({"Person"}),
        {"name": "Alice", "age": 30},
        element_id="eid:1",
    )
    end = _mock_node(
        frozenset({"Movie"}),
        {"title": "Inception", "year": 2010},
        element_id="eid:2",
    )
    rel = _mock_rel("ACTED_IN", {"role": "Cobb"}, start, end)
    d = rel_to_dict(rel, model)
    assert d["__label__"] == "ACTED_IN"
    assert d["role"] == "Cobb"
    assert d["__source_uid__"] == "Alice"
    assert d["__target_uid__"] == "Inception"


def test_rel_to_dict_falls_back_to_element_id(
    model: GraphDataModel,
):
    start = _mock_node(
        frozenset({"Unknown"}),
        {"x": 1},
        element_id="eid:99",
    )
    end = _mock_node(
        frozenset({"Unknown"}),
        {"y": 2},
        element_id="eid:100",
    )
    rel = _mock_rel("ACTED_IN", {"role": "X"}, start, end)
    d = rel_to_dict(rel, model)
    assert d["__source_uid__"] == "eid:99"
    assert d["__target_uid__"] == "eid:100"


# --- records_to_graph_data tests ---


def test_records_to_graph_data(model: GraphDataModel):
    person = _mock_node(
        frozenset({"Person"}),
        {"name": "Alice", "age": 30},
        element_id="eid:1",
    )
    movie = _mock_node(
        frozenset({"Movie"}),
        {"title": "Inception", "year": 2010},
        element_id="eid:2",
    )
    rel = _mock_rel("ACTED_IN", {"role": "Cobb"}, person, movie)
    record = _mock_record({"p": person, "m": movie, "r": rel})

    nodes, rels = records_to_graph_data([record], model)
    assert len(nodes) == 2
    assert len(rels) == 1


def test_records_to_graph_data_skips_scalars(
    model: GraphDataModel,
):
    person = _mock_node(
        frozenset({"Person"}),
        {"name": "Alice", "age": 30},
    )
    record = _mock_record({"p": person, "count": 42})

    nodes, rels = records_to_graph_data([record], model)
    assert len(nodes) == 1
    assert len(rels) == 0


# --- validate_result tests ---


def test_validate_result_valid(model: GraphDataModel):
    person = _mock_node(
        frozenset({"Person"}),
        {"name": "Alice", "age": 30},
        element_id="eid:1",
    )
    movie = _mock_node(
        frozenset({"Movie"}),
        {"title": "Inception", "year": 2010},
        element_id="eid:2",
    )
    rel = _mock_rel("ACTED_IN", {"role": "Cobb"}, person, movie)
    record = _mock_record({"p": person, "m": movie, "r": rel})

    result = validate_result([record], model)
    assert result.is_valid, [str(e) for e in result.errors]


def test_validate_result_invalid_node(model: GraphDataModel):
    bad = _mock_node(
        frozenset({"Person"}),
        {"name": "Alice"},  # missing age
    )
    record = _mock_record({"p": bad})

    result = validate_result([record], model)
    assert not result.is_valid


def test_validate_result_with_result_model():
    """Validate against a specific result model (subset of DB model)."""

    class PersonResult(NodeModel):
        __label__ = "Person"
        __uid_field__ = "name"
        name: str

    result_model = GraphDataModel(
        name="QueryResult",
        node_types=[PersonResult],
        relationship_types=[],
    )

    person = _mock_node(
        frozenset({"Person"}),
        {"name": "Alice"},
    )
    record = _mock_record({"p": person})

    result = validate_result([record], result_model)
    assert result.is_valid
