"""Tests for orthograph.extensions.neo4j.result_adapter."""

from typing import Optional

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

from .conftest import mock_node, mock_record, mock_rel


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


# --- node_to_dict tests ---


def test_node_to_dict_single_label(model: GraphDataModel) -> None:
    node = mock_node(
        frozenset({"Person"}),
        {"name": "Alice", "age": 30},
    )
    d = node_to_dict(node, model)
    assert d["__label__"] == "Person"
    assert d["name"] == "Alice"
    assert d["age"] == 30


def test_node_to_dict_multi_label_picks_matching(model: GraphDataModel) -> None:
    node = mock_node(
        frozenset({"Person", "Employee"}),
        {"name": "Alice", "age": 30},
    )
    d = node_to_dict(node, model)
    assert d["__label__"] == "Person"


def test_node_to_dict_no_matching_label(model: GraphDataModel) -> None:
    node = mock_node(
        frozenset({"Animal"}),
        {"species": "Cat"},
    )
    d = node_to_dict(node, model)
    assert d["__label__"] == "Animal"


# --- rel_to_dict tests ---


def test_rel_to_dict(model: GraphDataModel) -> None:
    start = mock_node(
        frozenset({"Person"}),
        {"name": "Alice", "age": 30},
        element_id="eid:1",
    )
    end = mock_node(
        frozenset({"Movie"}),
        {"title": "Inception", "year": 2010},
        element_id="eid:2",
    )
    rel = mock_rel("ACTED_IN", {"role": "Cobb"}, start, end)
    d = rel_to_dict(rel, model)
    assert d["__label__"] == "ACTED_IN"
    assert d["role"] == "Cobb"
    assert d["__source_uid__"] == "Alice"
    assert d["__target_uid__"] == "Inception"


def test_rel_to_dict_falls_back_to_element_id(model: GraphDataModel) -> None:
    start = mock_node(
        frozenset({"Unknown"}),
        {"x": 1},
        element_id="eid:99",
    )
    end = mock_node(
        frozenset({"Unknown"}),
        {"y": 2},
        element_id="eid:100",
    )
    rel = mock_rel("ACTED_IN", {"role": "X"}, start, end)
    d = rel_to_dict(rel, model)
    assert d["__source_uid__"] == "eid:99"
    assert d["__target_uid__"] == "eid:100"


# --- records_to_graph_data tests ---


def test_records_to_graph_data(model: GraphDataModel) -> None:
    person = mock_node(
        frozenset({"Person"}),
        {"name": "Alice", "age": 30},
        element_id="eid:1",
    )
    movie = mock_node(
        frozenset({"Movie"}),
        {"title": "Inception", "year": 2010},
        element_id="eid:2",
    )
    rel = mock_rel("ACTED_IN", {"role": "Cobb"}, person, movie)
    record = mock_record({"p": person, "m": movie, "r": rel})

    nodes, rels = records_to_graph_data([record], model)
    assert len(nodes) == 2
    assert len(rels) == 1


def test_records_to_graph_data_skips_scalars(model: GraphDataModel) -> None:
    person = mock_node(
        frozenset({"Person"}),
        {"name": "Alice", "age": 30},
    )
    record = mock_record({"p": person, "count": 42})

    nodes, rels = records_to_graph_data([record], model)
    assert len(nodes) == 1
    assert len(rels) == 0


# --- validate_result tests ---


def test_validate_result_valid(model: GraphDataModel) -> None:
    person = mock_node(
        frozenset({"Person"}),
        {"name": "Alice", "age": 30},
        element_id="eid:1",
    )
    movie = mock_node(
        frozenset({"Movie"}),
        {"title": "Inception", "year": 2010},
        element_id="eid:2",
    )
    rel = mock_rel("ACTED_IN", {"role": "Cobb"}, person, movie)
    record = mock_record({"p": person, "m": movie, "r": rel})

    result = validate_result([record], model)
    assert result.is_valid, [str(e) for e in result.errors]


def test_validate_result_invalid_node(model: GraphDataModel) -> None:
    bad = mock_node(
        frozenset({"Person"}),
        {"name": "Alice"},  # missing age
    )
    record = mock_record({"p": bad})

    result = validate_result([record], model)
    assert not result.is_valid


def test_validate_result_with_result_model() -> None:
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

    person = mock_node(
        frozenset({"Person"}),
        {"name": "Alice"},
    )
    record = mock_record({"p": person})

    result = validate_result([record], result_model)
    assert result.is_valid
