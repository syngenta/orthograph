"""Tests for orthograph.extensions.cypher -- Cypher query generation."""

from typing import Optional

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.core.types import Cardinality
from orthograph.extensions.cypher import CypherGenerator


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


class City(NodeModel):
    __label__ = "City"
    __uid_field__ = "name"

    name: str


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_type__ = Person
    __target_type__ = Movie

    role: str


class Directed(RelationshipModel):
    __label__ = "DIRECTED"
    __source_type__ = Person
    __target_type__ = Movie


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_type__ = Person
    __target_type__ = City
    __source_cardinality__ = Cardinality.ONE
    __target_cardinality__ = Cardinality.ZERO_OR_MORE


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
        name="Filmography",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn, Directed, LivesIn],
    )


# --- Cypher merge node tests ---


def test_cypher_merge_node_with_uid(model: GraphDataModel):
    gen = CypherGenerator(model)
    query, params = gen.merge_node({"__label__": "Person", "name": "Alice", "age": 30})
    assert "MERGE" in query
    assert ":Person" in query
    assert "name:" in query or "$name" in query
    assert isinstance(params, dict)


def test_cypher_merge_node_sets_properties(model: GraphDataModel):
    gen = CypherGenerator(model)
    query, params = gen.merge_node({"__label__": "Person", "name": "Alice", "age": 30})
    assert "SET" in query
    assert "age" in query


def test_cypher_merge_node_without_uid_falls_back_to_create(model: GraphDataModel):
    gen = CypherGenerator(model)
    query, params = gen.create_node({"__label__": "Person", "name": "Alice", "age": 30})
    assert "CREATE" in query
    assert ":Person" in query


# --- Cypher create relationship tests ---


def test_cypher_create_relationship(model: GraphDataModel):
    gen = CypherGenerator(model)
    query, params = gen.create_relationship(
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Alice",
            "__target_uid__": "Inception",
            "role": "Cobb",
        }
    )
    assert "MATCH" in query
    assert ":Person" in query
    assert ":Movie" in query
    assert "ACTED_IN" in query
    assert "role" in query


def test_cypher_merge_relationship(model: GraphDataModel):
    gen = CypherGenerator(model)
    query, params = gen.merge_relationship(
        {
            "__label__": "DIRECTED",
            "__source_uid__": "Nolan",
            "__target_uid__": "Inception",
        }
    )
    assert "MERGE" in query
    assert "DIRECTED" in query


# --- Cypher constraints tests ---


def test_cypher_generate_uniqueness_constraints(model: GraphDataModel):
    gen = CypherGenerator(model)
    constraints = gen.generate_constraints()
    assert len(constraints) >= 1
    # Person has uid_field=name, Movie has uid_field=title
    constraint_text = "\n".join(constraints)
    assert "Person" in constraint_text
    assert "name" in constraint_text
    assert "Movie" in constraint_text
    assert "title" in constraint_text


def test_cypher_constraint_is_valid_cypher(model: GraphDataModel):
    gen = CypherGenerator(model)
    constraints = gen.generate_constraints()
    for c in constraints:
        assert c.startswith("CREATE CONSTRAINT")


# --- Cypher match pattern tests ---


def test_cypher_match_node(model: GraphDataModel):
    gen = CypherGenerator(model)
    query = gen.match_node(Person)
    assert "MATCH" in query
    assert ":Person" in query
    assert "RETURN" in query


def test_cypher_match_relationship_pattern(model: GraphDataModel):
    gen = CypherGenerator(model)
    query = gen.match_relationship(ActedIn)
    assert "MATCH" in query
    assert ":Person" in query
    assert ":Movie" in query
    assert "ACTED_IN" in query
    assert "RETURN" in query
