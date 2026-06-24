"""Tests for orthograph.cypher.parser."""

import pytest

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    NodeModel,
    RelationshipModel,
)
from tests.fixtures.conftest import ActedIn, City, LivesIn, Movie, Person


# --- Custom fixtures (specific to this test file) ---


class Company(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


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


# Same label, different endpoints (E50.7 multi-shape fixtures)
class KnowsPerson(RelationshipModel):
    __label__ = "KNOWS"
    __source_label__ = "Person"
    __target_label__ = "Person"


class KnowsCompany(RelationshipModel):
    __label__ = "KNOWS"
    __source_label__ = "Company"
    __target_label__ = "Company"


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
def multi_shape_model() -> GraphDefinition:
    """Model with two same-label/different-endpoint KNOWS relationship types."""
    return GraphDefinition(
        name="MultiShape",
        node_types=[Person, Company],
        relationship_types=[KnowsPerson, KnowsCompany],
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


# --- Parser exception → ValidationResult contract ---


def test_validate_cypher_unparseable_returns_result_not_exception(
    graph_definition: GraphDefinition,
):
    """A syntactically unparseable query must return a ValidationResult, not raise."""
    from orthograph.cypher.parser import validate_cypher
    from orthograph.diagnostics.result import ValidationResult

    result = validate_cypher("THIS IS NOT CYPHER %%%", graph_definition)
    assert isinstance(result, ValidationResult)


def test_validate_cypher_unparseable_is_not_valid(
    graph_definition: GraphDefinition,
):
    """An unparseable query must produce is_valid == False."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher("THIS IS NOT CYPHER %%%", graph_definition)
    assert not result.is_valid


def test_validate_cypher_unparseable_has_parse_error_code(
    graph_definition: GraphDefinition,
):
    """An unparseable query must surface a QUERY_PARSE_ERROR issue."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher("THIS IS NOT CYPHER %%%", graph_definition)
    assert any(e.code == "QUERY_PARSE_ERROR" for e in result.errors)


def test_validate_cypher_parse_error_entity_id_contains_query(
    graph_definition: GraphDefinition,
):
    """The QUERY_PARSE_ERROR issue entity_id should be the query string."""
    from orthograph.cypher.parser import validate_cypher

    query = "TOTALLY BROKEN ###"
    result = validate_cypher(query, graph_definition)
    parse_errors = [e for e in result.errors if e.code == "QUERY_PARSE_ERROR"]
    assert len(parse_errors) == 1
    assert parse_errors[0].entity_id == query


# --- extract_return_columns classification tests (T1) ---


def test_extract_return_columns_whole_node():
    """RETURN m → single WHOLE_NODE column with label 'Movie'."""
    from orthograph.cypher.parser import ReturnKind, extract_return_columns

    result = extract_return_columns("MATCH (m:Movie) RETURN m")
    assert result is not None
    assert len(result) == 1
    col = result[0]
    assert col.name == "m"
    assert col.kind == ReturnKind.WHOLE_NODE
    assert col.label == "Movie"


def test_extract_return_columns_multiple_nodes_and_rel():
    """RETURN p, r, m → three columns: p/Person, r/ACTED_IN, m/Movie."""
    from orthograph.cypher.parser import ReturnKind, extract_return_columns

    result = extract_return_columns(
        "MATCH (p:Person)-[r:ACTED_IN]->(m:Movie) RETURN p, r, m"
    )
    assert result is not None
    assert len(result) == 3

    by_name = {c.name: c for c in result}
    assert by_name["p"].kind == ReturnKind.WHOLE_NODE
    assert by_name["p"].label == "Person"
    assert by_name["r"].kind == ReturnKind.WHOLE_REL
    assert by_name["r"].label == "ACTED_IN"
    assert by_name["m"].kind == ReturnKind.WHOLE_NODE
    assert by_name["m"].label == "Movie"


def test_extract_return_columns_scalar_with_aliases():
    """RETURN m.title AS title, m.released AS released → two SCALAR columns."""
    from orthograph.cypher.parser import ReturnKind, extract_return_columns

    result = extract_return_columns(
        "MATCH (m:Movie) RETURN m.title AS title, m.released AS released"
    )
    assert result is not None
    assert len(result) == 2
    by_name = {c.name: c for c in result}
    assert by_name["title"].kind == ReturnKind.SCALAR
    assert by_name["title"].label is None
    assert by_name["released"].kind == ReturnKind.SCALAR
    assert by_name["released"].label is None


def test_extract_return_columns_scalar_no_alias():
    """RETURN m.title (no alias) → SCALAR column named 'title'."""
    from orthograph.cypher.parser import ReturnKind, extract_return_columns

    result = extract_return_columns("MATCH (m:Movie) RETURN m.title")
    assert result is not None
    assert len(result) == 1
    col = result[0]
    assert col.name == "title"
    assert col.kind == ReturnKind.SCALAR
    assert col.label is None


def test_extract_return_columns_aliased_whole_node():
    """RETURN m AS movie → WHOLE_NODE named 'movie', label 'Movie'."""
    from orthograph.cypher.parser import ReturnKind, extract_return_columns

    result = extract_return_columns("MATCH (m:Movie) RETURN m AS movie")
    assert result is not None
    assert len(result) == 1
    col = result[0]
    assert col.name == "movie"
    assert col.kind == ReturnKind.WHOLE_NODE
    assert col.label == "Movie"


def test_extract_return_columns_star_returns_none():
    """RETURN * → None (alignment check should be skipped)."""
    from orthograph.cypher.parser import extract_return_columns

    result = extract_return_columns("MATCH (m:Movie) RETURN *")
    assert result is None


def test_extract_return_columns_aggregation_returns_none():
    """RETURN count(m) AS c → None (aggregation skips the check)."""
    from orthograph.cypher.parser import extract_return_columns

    result = extract_return_columns("MATCH (m:Movie) RETURN count(m) AS c")
    assert result is None


def test_extract_return_columns_mixed_node_and_scalar():
    """RETURN p, m.title AS t → one WHOLE_NODE + one SCALAR."""
    from orthograph.cypher.parser import ReturnKind, extract_return_columns

    result = extract_return_columns(
        "MATCH (p:Person)-[r:ACTED_IN]->(m:Movie) RETURN p, m.title AS t"
    )
    assert result is not None
    assert len(result) == 2
    by_name = {c.name: c for c in result}
    assert by_name["p"].kind == ReturnKind.WHOLE_NODE
    assert by_name["p"].label == "Person"
    assert by_name["t"].kind == ReturnKind.SCALAR
    assert by_name["t"].label is None


# --- E50.7: endpoint-aware relationship resolution (multi-shape) ---


def test_validate_multi_shape_correct_person_pattern(
    multi_shape_model: GraphDefinition,
):
    """Person-KNOWS->Person pattern resolves the Person shape and is valid."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a, b",
        multi_shape_model,
    )
    assert result.is_valid


def test_validate_multi_shape_correct_company_pattern(
    multi_shape_model: GraphDefinition,
):
    """Company-KNOWS->Company pattern resolves the Company shape and is valid."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Company)-[:KNOWS]->(b:Company) RETURN a, b",
        multi_shape_model,
    )
    assert result.is_valid


def test_validate_multi_shape_mismatched_endpoints_rejected(
    multi_shape_model: GraphDefinition,
):
    """Person-KNOWS->Company matches no declared triple → QUERY_INVALID_ENDPOINT."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Person)-[:KNOWS]->(b:Company) RETURN a, b",
        multi_shape_model,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_INVALID_ENDPOINT" for e in result.errors)


def test_validate_multi_shape_unknown_label_still_caught(
    multi_shape_model: GraphDefinition,
):
    """Unknown rel type not in multi-shape model still raises QUERY_UNKNOWN_REL_TYPE."""
    from orthograph.cypher.parser import validate_cypher

    result = validate_cypher(
        "MATCH (a:Person)-[:FRIEND_OF]->(b:Person) RETURN a",
        multi_shape_model,
    )
    assert not result.is_valid
    assert any(e.code == "QUERY_UNKNOWN_REL_TYPE" for e in result.errors)
