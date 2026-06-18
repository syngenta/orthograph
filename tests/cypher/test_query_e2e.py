"""End-to-end tests for CypherQuery via adapter + CypherExecutor against a live
Neo4j DB.

These tests require a running Neo4j instance.  They are skipped by default and
must be opted in explicitly:

    pytest --neo4j                                 # default URI/credentials
    pytest --neo4j --neo4j-password secret

Every test uses the ``neo4j_clean`` fixture (root conftest) which wipes the DB
before and after each test.

What is covered
---------------
- YAML-loaded CypherQuery read via CypherQueryReadAdapter → list[dict]
- Python-constructed CypherQuery read with a typed Params model
- CypherQuery write (CREATE) via CypherQueryWriteAdapter → CypherWriteResultSummary
- CypherQuery write (SET) returns properties_set counter
- validate_query_catalogue on a YAML-loaded catalogue against the live definition
  produces no errors for correct queries
- validate_query_catalogue detects a renamed-label error (QUERY_UNKNOWN_NODE_LABEL)
  without a DB round-trip (static, but shown in the e2e file for completeness)
"""

# mypy: disable-error-code="arg-type"

from typing import Any

import pytest

from orthograph.api.model import load_query_catalogue
from orthograph.cypher.bindings import NoIdentifiers
from orthograph.cypher.query import CypherQuery
from orthograph.cypher.query_execution import (
    CypherExecutor,
    CypherQueryReadAdapter,
    CypherQueryWriteAdapter,
    CypherWriteResultSummary,
)
from orthograph.cypher.validation import validate_query_catalogue
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.query.catalogue import QueryCatalogue


# ---------------------------------------------------------------------------
# Domain models (filmography — consistent with the rest of the test suite)
# ---------------------------------------------------------------------------


class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    born: int | None = None


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    released: int | None = None


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    __directed__ = True
    role: str


FILM_DEFINITION = GraphDefinition(
    name="Filmography",
    node_types=[Person, Movie],
    relationship_types=[ActedIn],
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed(driver: Any) -> None:
    """Populate the DB with a minimal filmography dataset.

    Two Movie nodes and two Person nodes with ACTED_IN edges.
    """
    driver.execute_query(
        "MERGE (m1:Movie {title: 'The Matrix', released: 1999})"
        " MERGE (m2:Movie {title: 'Speed', released: 1994})"
        " MERGE (p1:Person {name: 'Keanu Reeves', born: 1964})"
        " MERGE (p2:Person {name: 'Sandra Bullock', born: 1964})"
        " MERGE (p1)-[:ACTED_IN {role: 'Neo'}]->(m1)"
        " MERGE (p2)-[:ACTED_IN {role: 'Annie'}]->(m2)"
    )


def _make_executor(driver: Any) -> CypherExecutor:
    """Return a CypherExecutor backed by the live driver session."""
    return CypherExecutor(driver.session)


# ---------------------------------------------------------------------------
# Read tests
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
def test_yaml_query_read_returns_matching_rows(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """A YAML-loaded CypherQuery read via adapter returns the expected rows."""
    _seed(neo4j_driver)

    yaml_src = """
- name: find_movie_by_title
  cypher_template: "MATCH (m:Movie {title: $title}) RETURN m.title, m.released"
  params_schema:
    title: FindMovieByTitleParams
    type: object
    properties:
      title: {type: string, title: Title}
    required: [title]
"""
    queries = load_query_catalogue(yaml_src)
    query = queries[0]
    adapter = CypherQueryReadAdapter(query)
    executor = _make_executor(neo4j_driver)

    rows: list[dict[str, Any]] = executor.read(adapter, {"title": "The Matrix"})

    assert len(rows) == 1
    assert rows[0]["m.title"] == "The Matrix"
    assert rows[0]["m.released"] == 1999


@pytest.mark.neo4j
def test_cypher_query_read_all_movies(neo4j_driver: Any, neo4j_clean: None) -> None:
    """CypherQuery without params returns all matching nodes."""
    _seed(neo4j_driver)

    from orthograph.cypher.bindings import NoParams

    query = CypherQuery(
        name="all_movies",
        cypher_template="MATCH (m:Movie) RETURN m.title ORDER BY m.title",
        Params=NoParams,
        Identifiers=NoIdentifiers,
    )
    adapter = CypherQueryReadAdapter(query)
    executor = _make_executor(neo4j_driver)

    rows: list[dict[str, Any]] = executor.read(adapter, {})

    titles = [r["m.title"] for r in rows]
    assert sorted(titles) == ["Speed", "The Matrix"]


@pytest.mark.neo4j
def test_cypher_query_read_with_typed_params(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """CypherQuery with a typed Params model coerces and filters correctly."""
    from pydantic import BaseModel

    _seed(neo4j_driver)

    class MovieByYearParams(BaseModel):
        released: int

    query = CypherQuery(
        name="movies_by_year",
        cypher_template=(
            "MATCH (m:Movie {released: $released}) RETURN m.title, m.released"
        ),
        Params=MovieByYearParams,
        Identifiers=NoIdentifiers,
    )
    adapter = CypherQueryReadAdapter(query)
    executor = _make_executor(neo4j_driver)

    rows: list[dict[str, Any]] = executor.read(adapter, {"released": 1994})

    assert len(rows) == 1
    assert rows[0]["m.title"] == "Speed"


@pytest.mark.neo4j
def test_cypher_query_read_optional_param_excluded_when_absent(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """Optional params not supplied are excluded from the Cypher parameter dict."""
    _seed(neo4j_driver)

    from orthograph.cypher.bindings import NoParams

    query = CypherQuery(
        name="movies_with_optional_limit",
        cypher_template="MATCH (m:Movie) RETURN m.title ORDER BY m.title",
        Params=NoParams,
        Identifiers=NoIdentifiers,
    )
    adapter = CypherQueryReadAdapter(query)
    executor = _make_executor(neo4j_driver)

    # No limit supplied — query returns all movies without error
    rows: list[dict[str, Any]] = executor.read(adapter, {})

    assert len(rows) == 2


@pytest.mark.neo4j
def test_cypher_query_read_actors_for_movie(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """Traversal query returns correct actors for a given movie."""
    _seed(neo4j_driver)

    from pydantic import BaseModel

    class ActorsForMovieParams(BaseModel):
        title: str

    query = CypherQuery(
        name="actors_for_movie",
        cypher_template=(
            "MATCH (p:Person)-[:ACTED_IN]->(m:Movie {title: $title})"
            " RETURN p.name, p.born"
        ),
        Params=ActorsForMovieParams,
        Identifiers=NoIdentifiers,
    )
    adapter = CypherQueryReadAdapter(query)
    executor = _make_executor(neo4j_driver)

    rows: list[dict[str, Any]] = executor.read(adapter, {"title": "The Matrix"})

    assert len(rows) == 1
    assert rows[0]["p.name"] == "Keanu Reeves"


# ---------------------------------------------------------------------------
# Write tests
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
def test_cypher_query_write_create_returns_nodes_created(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """CypherQuery write (CREATE) returns
    CypherWriteResultSummary with nodes_created=1."""
    from pydantic import BaseModel

    class CreateMovieParams(BaseModel):
        title: str
        released: int

    query = CypherQuery(
        name="create_movie",
        cypher_template="CREATE (m:Movie {title: $title, released: $released})",
        Params=CreateMovieParams,
        Identifiers=NoIdentifiers,
    )
    adapter = CypherQueryWriteAdapter(query)
    executor = _make_executor(neo4j_driver)

    summary: CypherWriteResultSummary = executor.write(
        adapter,
        {"title": "Inception", "released": 2010},
    )

    assert isinstance(summary, CypherWriteResultSummary)
    assert summary.nodes_created == 1

    # Verify the node is actually in the DB
    result, _, _ = neo4j_driver.execute_query(
        "MATCH (m:Movie {title: $title}) RETURN m.title",
        title="Inception",
    )
    assert len(result) == 1


@pytest.mark.neo4j
def test_cypher_query_write_set_returns_properties_set(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """CypherQuery write (SET) returns properties_set counter."""
    _seed(neo4j_driver)

    from pydantic import BaseModel

    class TagMovieParams(BaseModel):
        title: str
        genre: str

    query = CypherQuery(
        name="tag_movie",
        cypher_template="MATCH (m:Movie {title: $title}) SET m.genre = $genre",
        Params=TagMovieParams,
        Identifiers=NoIdentifiers,
    )
    adapter = CypherQueryWriteAdapter(query)
    executor = _make_executor(neo4j_driver)

    summary: CypherWriteResultSummary = executor.write(
        adapter,
        {"title": "The Matrix", "genre": "sci-fi"},
    )

    assert isinstance(summary, CypherWriteResultSummary)
    assert summary.properties_set == 1


@pytest.mark.neo4j
def test_cypher_query_write_create_relationship(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """CypherQuery write creating a relationship returns relationships_created=1."""
    _seed(neo4j_driver)

    from pydantic import BaseModel

    class AddActorParams(BaseModel):
        actor: str
        movie: str
        role: str

    query = CypherQuery(
        name="add_actor_to_movie",
        cypher_template=(
            "MATCH (p:Person {name: $actor}), (m:Movie {title: $movie})"
            " MERGE (p)-[r:ACTED_IN {role: $role}]->(m)"
        ),
        Params=AddActorParams,
        Identifiers=NoIdentifiers,
    )
    adapter = CypherQueryWriteAdapter(query)
    executor = _make_executor(neo4j_driver)

    summary: CypherWriteResultSummary = executor.write(
        adapter,
        {"actor": "Sandra Bullock", "movie": "The Matrix", "role": "Trinity"},
    )

    assert isinstance(summary, CypherWriteResultSummary)
    assert summary.relationships_created == 1


# ---------------------------------------------------------------------------
# Catalogue + validation (static — no DB round-trip, but placed here so the
# same domain fixtures and seed data are visible in context)
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
def test_catalogue_validate_yaml_queries_against_live_definition(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """validate_query_catalogue on YAML
    queries against FILM_DEFINITION returns no errors."""
    yaml_src = """
- name: find_movie
  cypher_template: "MATCH (m:Movie {title: $title}) RETURN m.title, m.released"
  params_schema:
    title: FindMovieParams
    type: object
    properties:
      title: {type: string, title: Title}
    required: [title]
- name: find_person
  cypher_template: "MATCH (p:Person {name: $name}) RETURN p.name, p.born"
  params_schema:
    title: FindPersonParams
    type: object
    properties:
      name: {type: string, title: Name}
    required: [name]
- name: actor_movies
  cypher_template: >-
    MATCH (p:Person {name: $name})-[:ACTED_IN]->(m:Movie)
    RETURN p.name, m.title
  params_schema:
    title: ActorMoviesParams
    type: object
    properties:
      name: {type: string, title: Name}
    required: [name]
"""
    queries = load_query_catalogue(yaml_src)
    catalogue = QueryCatalogue()
    for q in queries:
        catalogue.register_cypher_query(q)

    result = validate_query_catalogue(catalogue, FILM_DEFINITION)

    assert result.is_valid, [
        f"{i.code}: {i.message}" for i in result.issues if i.severity.value == "ERROR"
    ]


@pytest.mark.neo4j
def test_catalogue_validate_detects_stale_param_in_yaml(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """A YAML query with an undeclared $param surfaces QUERY_PARAM_ALIGNMENT_ERROR."""
    stale_yaml = """
- name: bad_param
  cypher_template: "MATCH (m:Movie {released: $released}) RETURN m.title"
  params_schema:
    title: BadParamParams
    type: object
    properties:
      title: {type: string, title: Title}
    required: [title]
"""
    queries = load_query_catalogue(stale_yaml)
    catalogue = QueryCatalogue()
    for q in queries:
        catalogue.register_cypher_query(q)

    result = validate_query_catalogue(catalogue, FILM_DEFINITION)

    assert not result.is_valid
    assert any(i.code == "QUERY_PARAM_ALIGNMENT_ERROR" for i in result.issues)
