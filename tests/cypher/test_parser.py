"""Tests for orthograph.cypher.parser."""

from typing import Optional

import pytest

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    Cardinality,
    NodeModel,
    RelationshipModel,
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


class City(NodeModel):
    __label__ = "City"
    __uid_field__ = "name"
    name: str


class Company(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    role: str


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "City"
    __source_cardinality__ = Cardinality.ONE


class FriendOf(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_label__ = "Person"
    __target_label__ = "Person"
    __directed__ = False


class Collaborates(RelationshipModel):
    __label__ = "COLLABORATES"
    __source_label__ = "Person"
    __target_label__ = "Company"
    __directed__ = False


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(
        name="Film",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn, LivesIn],
    )


@pytest.fixture()
def social_model() -> GraphDefinition:
    return GraphDefinition(
        name="Social",
        node_types=[Person],
        relationship_types=[FriendOf],
    )


@pytest.fixture()
def cross_undirected_model() -> GraphDefinition:
    return GraphDefinition(
        name="CrossUndirected",
        node_types=[Person, Company],
        relationship_types=[Collaborates],
    )


# --- CypherQueryInfo extraction tests ---


def test_parse_extracts_node_labels():
    from orthograph.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (n:Person)-[r:ACTED_IN]->(m:Movie) RETURN n")
    assert "Person" in info.node_labels
    assert "Movie" in info.node_labels


def test_parse_extracts_relationship_types():
    from orthograph.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (n:Person)-[r:ACTED_IN]->(m:Movie) RETURN n")
    assert "ACTED_IN" in info.relationship_types


def test_parse_extracts_property_accesses():
    from orthograph.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (n:Person) WHERE n.age > 21 RETURN n.name")
    assert "age" in info.property_accesses.get("n", set())
    assert "name" in info.property_accesses.get("n", set())


def test_parse_multi_pattern():
    from orthograph.cypher.parser import parse_cypher

    info = parse_cypher(
        "MATCH (a:Person)-[:ACTED_IN]->(b:Movie), "
        "(a)-[:LIVES_IN]->(c:City) RETURN a, b, c"
    )
    assert info.node_labels == {"Person", "Movie", "City"}
    assert info.relationship_types == {"ACTED_IN", "LIVES_IN"}


def test_parse_merge_query():
    from orthograph.cypher.parser import parse_cypher

    info = parse_cypher('MERGE (p:Person {name: "Alice"}) RETURN p')
    assert "Person" in info.node_labels
    assert info.query_intent in ("write", "read_write")


def test_parse_read_query_intent():
    from orthograph.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (n:Person) RETURN n")
    assert info.query_intent == "read"


def test_parse_variable_bindings():
    from orthograph.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (n:Person)-[r:ACTED_IN]->(m:Movie) RETURN n")
    assert info.variable_bindings.get("n") == "Person"
    assert info.variable_bindings.get("m") == "Movie"
    assert info.variable_bindings.get("r") == "ACTED_IN"


def test_parse_patterns():
    from orthograph.cypher.parser import parse_cypher

    info = parse_cypher("MATCH (a:Person)-[r:ACTED_IN]->(b:Movie) RETURN a")
    assert len(info.patterns) >= 1
    pat = info.patterns[0]
    assert pat.source_label == "Person"
    assert pat.relationship_type == "ACTED_IN"
    assert pat.target_label == "Movie"


def test_parse_empty_query_raises():
    from orthograph.cypher.parser import parse_cypher

    with pytest.raises(ValueError):
        parse_cypher("")


# --- validate_cypher tests ---


def test_validate_valid_query(graph_definition: GraphDefinition):
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (n:Person)-[r:ACTED_IN]->(m:Movie) RETURN n",
        graph_definition,
    )
    assert result.is_valid


def test_validate_unknown_node_label(graph_definition: GraphDefinition):
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (n:Animal) RETURN n",
        graph_definition,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_UNKNOWN_NODE_LABEL" for e in result.errors)


def test_validate_unknown_rel_type(graph_definition: GraphDefinition):
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH ()-[r:FRIEND_OF]->() RETURN r",
        graph_definition,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_UNKNOWN_REL_TYPE" for e in result.errors)


def test_validate_unknown_property(graph_definition: GraphDefinition):
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (n:Person) WHERE n.salary > 100 RETURN n",
        graph_definition,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_UNKNOWN_PROPERTY" for e in result.errors)


def test_validate_valid_property(graph_definition: GraphDefinition):
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (n:Person) WHERE n.age > 21 RETURN n.name",
        graph_definition,
    )
    assert result.is_valid


def test_validate_invalid_endpoint(graph_definition: GraphDefinition):
    from orthograph.cypher.parser import validate_cypher

    # ACTED_IN connects Person->Movie, not Person->City
    result = validate_cypher(
        "MATCH (n:Person)-[:ACTED_IN]->(c:City) RETURN n",
        graph_definition,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_INVALID_ENDPOINT" for e in result.errors)


def test_validate_multi_pattern_valid(graph_definition: GraphDefinition):
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Person)-[:ACTED_IN]->(b:Movie), "
        "(a)-[:LIVES_IN]->(c:City) RETURN a, b, c",
        graph_definition,
    )
    assert result.is_valid


# --- Strategy pattern tests ---


def test_parser_strategy_protocol():
    from orthograph.cypher.parser import (
        GraphglotParser,
    )

    parser = GraphglotParser()
    # Verify it satisfies the protocol by calling it
    info = parser.parse("MATCH (n:Person) RETURN n")
    assert "Person" in info.node_labels


def test_validate_cypher_accepts_custom_strategy(
    graph_definition: GraphDefinition,
):
    from orthograph.cypher.parser import (
        GraphglotParser,
        validate_cypher,
    )

    result = validate_cypher(
        "MATCH (n:Person) RETURN n",
        graph_definition,
        parser=GraphglotParser(),
    )
    assert result.is_valid


# --- Undirected relationship endpoint validation tests ---


def test_validate_undirected_same_type_forward_valid(social_model: GraphDefinition):
    """Undirected same-type: forward direction is valid."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Person)-[:FRIEND_OF]->(b:Person) RETURN a, b",
        social_model,
    )
    assert result.is_valid


def test_validate_undirected_same_type_reverse_valid(social_model: GraphDefinition):
    """Undirected same-type: reverse direction is also valid (trivially, same types)."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Person)-[:FRIEND_OF]->(b:Person) RETURN a, b",
        social_model,
    )
    assert result.is_valid


def test_validate_undirected_cross_type_forward_valid(
    cross_undirected_model: GraphDefinition,
):
    """Undirected cross-type: Person->Company (forward) is valid."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Person)-[:COLLABORATES]->(b:Company) RETURN a, b",
        cross_undirected_model,
    )
    assert result.is_valid


def test_validate_undirected_cross_type_reverse_valid(
    cross_undirected_model: GraphDefinition,
):
    """Undirected cross-type: Company->Person (reversed) should also be valid."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Company)-[:COLLABORATES]->(b:Person) RETURN a, b",
        cross_undirected_model,
    )
    assert result.is_valid


def test_validate_undirected_cross_type_wrong_types_rejected(
    cross_undirected_model: GraphDefinition,
):
    """Undirected cross-type: completely wrong types still rejected."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Person)-[:COLLABORATES]->(b:Person) RETURN a, b",
        cross_undirected_model,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_INVALID_ENDPOINT" for e in result.errors)


def test_validate_directed_cross_type_reverse_rejected(
    graph_definition: GraphDefinition,
):
    """Directed: reverse direction is still rejected."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Movie)-[:ACTED_IN]->(b:Person) RETURN a, b",
        graph_definition,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_INVALID_ENDPOINT" for e in result.errors)
