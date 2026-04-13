"""Tests for orthograph.extensions.cypher.parser."""

from typing import Optional

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.core.types import Cardinality


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


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_type__ = Person
    __target_type__ = City
    __source_cardinality__ = Cardinality.ONE


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
        name="Film",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn, LivesIn],
    )


# --- CypherQueryInfo extraction tests ---


def test_parse_extracts_node_labels():
    from orthograph.extensions.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (n:Person)-[r:ACTED_IN]->(m:Movie) RETURN n")
    assert "Person" in info.node_labels
    assert "Movie" in info.node_labels


def test_parse_extracts_relationship_types():
    from orthograph.extensions.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (n:Person)-[r:ACTED_IN]->(m:Movie) RETURN n")
    assert "ACTED_IN" in info.relationship_types


def test_parse_extracts_property_accesses():
    from orthograph.extensions.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (n:Person) WHERE n.age > 21 RETURN n.name")
    assert "age" in info.property_accesses.get("n", set())
    assert "name" in info.property_accesses.get("n", set())


def test_parse_multi_pattern():
    from orthograph.extensions.cypher.parser import parse_cypher

    info = parse_cypher(
        "MATCH (a:Person)-[:ACTED_IN]->(b:Movie), "
        "(a)-[:LIVES_IN]->(c:City) RETURN a, b, c"
    )
    assert info.node_labels == {"Person", "Movie", "City"}
    assert info.relationship_types == {"ACTED_IN", "LIVES_IN"}


def test_parse_merge_query():
    from orthograph.extensions.cypher.parser import parse_cypher

    info = parse_cypher('MERGE (p:Person {name: "Alice"}) RETURN p')
    assert "Person" in info.node_labels
    assert info.query_intent in ("write", "read_write")


def test_parse_read_query_intent():
    from orthograph.extensions.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (n:Person) RETURN n")
    assert info.query_intent == "read"


def test_parse_variable_bindings():
    from orthograph.extensions.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (n:Person)-[r:ACTED_IN]->(m:Movie) RETURN n")
    assert info.variable_bindings.get("n") == "Person"
    assert info.variable_bindings.get("m") == "Movie"
    assert info.variable_bindings.get("r") == "ACTED_IN"


def test_parse_patterns():
    from orthograph.extensions.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (a:Person)-[r:ACTED_IN]->(b:Movie) RETURN a")
    assert len(info.patterns) >= 1
    pat = info.patterns[0]
    assert pat.source_label == "Person"
    assert pat.relationship_type == "ACTED_IN"
    assert pat.target_label == "Movie"


def test_parse_empty_query_raises():
    from orthograph.extensions.cypher.parser import parse_cypher

    with pytest.raises(ValueError):
        parse_cypher("")


# --- validate_cypher tests ---


def test_validate_valid_query(model: GraphDataModel):
    from orthograph.extensions.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (n:Person)-[r:ACTED_IN]->(m:Movie) RETURN n",
        model,
    )
    assert result.is_valid


def test_validate_unknown_node_label(model: GraphDataModel):
    from orthograph.extensions.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (n:Animal) RETURN n",
        model,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_UNKNOWN_NODE_LABEL" for e in result.errors)


def test_validate_unknown_rel_type(model: GraphDataModel):
    from orthograph.extensions.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH ()-[r:FRIEND_OF]->() RETURN r",
        model,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_UNKNOWN_REL_TYPE" for e in result.errors)


def test_validate_unknown_property(model: GraphDataModel):
    from orthograph.extensions.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (n:Person) WHERE n.salary > 100 RETURN n",
        model,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_UNKNOWN_PROPERTY" for e in result.errors)


def test_validate_valid_property(model: GraphDataModel):
    from orthograph.extensions.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (n:Person) WHERE n.age > 21 RETURN n.name",
        model,
    )
    assert result.is_valid


def test_validate_invalid_endpoint(model: GraphDataModel):
    from orthograph.extensions.cypher.parser import validate_cypher

    # ACTED_IN connects Person->Movie, not Person->City
    result = validate_cypher(
        "MATCH (n:Person)-[:ACTED_IN]->(c:City) RETURN n",
        model,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_INVALID_ENDPOINT" for e in result.errors)


def test_validate_multi_pattern_valid(model: GraphDataModel):
    from orthograph.extensions.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Person)-[:ACTED_IN]->(b:Movie), "
        "(a)-[:LIVES_IN]->(c:City) RETURN a, b, c",
        model,
    )
    assert result.is_valid


# --- Strategy pattern tests ---


def test_parser_strategy_protocol():
    from orthograph.extensions.cypher.parser import (
        GraphglotParser,
    )

    parser = GraphglotParser()
    # Verify it satisfies the protocol by calling it
    info = parser.parse("MATCH (n:Person) RETURN n")
    assert "Person" in info.node_labels


def test_validate_cypher_accepts_custom_strategy(
    model: GraphDataModel,
):
    from orthograph.extensions.cypher.parser import (
        GraphglotParser,
        validate_cypher,
    )

    result = validate_cypher(
        "MATCH (n:Person) RETURN n",
        model,
        parser=GraphglotParser(),
    )
    assert result.is_valid
