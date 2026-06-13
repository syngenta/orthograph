"""Tests for validate_query_catalogue — static model validation of a
query_catalogue's queries.

``validate_query_catalogue`` introspects each registered query against a
``GraphDefinition`` WITHOUT a database:

  * Declarative Cypher queries (a ``cypher_template`` ClassVar) are validated via
    the existing ``validate_cypher`` — unknown labels / rel types / properties
    surface as ERRORs.
  * Imperative Cypher queries (no template) cannot be statically inspected; they
    are reported as ``QUERY_UNVERIFIABLE`` (INFO) with the reason, never silently
    skipped.
  * Non-Cypher queries cannot be validated by this Cypher-specific function; they
    too are reported as ``QUERY_UNVERIFIABLE`` (INFO) with the reason.
"""

import warnings
from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.cypher.base_models import CypherReadQuery, CypherWriteQuery
from orthograph.cypher.bindings import CypherQuery
from orthograph.cypher.validation import validate_query_catalogue
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel
from orthograph.query.base_models import Backend, ReadQuery
from orthograph.query.catalogue import QueryCatalogue


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    released: int


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(name="Film", node_types=[Movie], relationship_types=[])


class ReleasedYearParams(BaseModel):
    released: int


class TitleParams(BaseModel):
    title: str


class MoviesByYear(CypherReadQuery[ReleasedYearParams, Movie]):
    """Declarative, model-consistent read."""

    Params = ReleasedYearParams
    Output = Movie
    name = "movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title, m.released"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(title=raw["m.title"], released=raw["m.released"])


class CreateMovie(CypherWriteQuery[ReleasedYearParams, int]):
    """Declarative, model-consistent write."""

    Params = ReleasedYearParams
    name = "create_movie"
    cypher_template = "CREATE (m:Movie {released: $released})"

    def materialize(self, raw: Any) -> int:
        return 1


class MoviesByTitleBadLabel(CypherReadQuery[TitleParams, Movie]):
    """Declarative read referencing a label that is NOT in the model."""

    Params = TitleParams
    Output = Movie
    name = "movies_by_title_bad_label"
    cypher_template = "MATCH (f:Film {title: $title}) RETURN f.title"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(title=raw["f.title"], released=0)


def test_import_validate_query_catalogue() -> None:
    """validate_query_catalogue imports from the cypher extension."""
    from orthograph.cypher.validation import (
        validate_query_catalogue,  # noqa: F401
    )


def test_consistent_catalogue_has_no_errors(graph_definition: GraphDefinition) -> None:
    """A query_catalogue of model-consistent declarative queries validates clean."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(MoviesByYear())
    query_catalogue.register_write(CreateMovie())

    result = validate_query_catalogue(query_catalogue, graph_definition)

    assert result.is_valid
    assert result.errors == []


def test_model_violating_query_surfaces_error(
    graph_definition: GraphDefinition,
) -> None:
    """A declarative query referencing an unknown label produces an ERROR."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(MoviesByTitleBadLabel())

    result = validate_query_catalogue(query_catalogue, graph_definition)

    assert not result.is_valid
    assert any("Film" in issue.message for issue in result.errors)


def test_imperative_query_reported_unverifiable_with_reason(
    graph_definition: GraphDefinition,
) -> None:
    """An imperative query is reported as unverifiable with the reason why."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)

        class ImperativeRead(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "imperative_read"

            def build(self, params: ReleasedYearParams) -> CypherQuery:
                return ("MATCH (m:Movie) RETURN m", {})

            def materialize(self, raw: dict[str, Any]) -> Movie:
                return Movie(title="x", released=0)

    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(ImperativeRead())

    result = validate_query_catalogue(query_catalogue, graph_definition)

    unverifiable = [i for i in result.issues if i.code == "QUERY_UNVERIFIABLE"]
    assert len(unverifiable) == 1
    issue = unverifiable[0]
    assert issue.severity == Severity.INFO
    assert issue.entity_type == EntityType.QUERY
    assert issue.entity_id == "imperative_read"
    assert "imperative" in issue.message.lower()
    assert "cypher_template" in issue.message
    # Reporting an unverifiable query does not make the query_catalogue invalid.
    assert result.is_valid


def test_non_cypher_query_reported_unverifiable_with_reason(
    graph_definition: GraphDefinition,
) -> None:
    """A non-Cypher query cannot be checked here and is reported with the reason."""

    class SqlRead(ReadQuery[TitleParams, Movie]):
        Params = TitleParams
        Output = Movie
        name = "sql_read"
        backend = Backend.SQLALCHEMY

        def build(self, params: TitleParams) -> str:
            return "SELECT title FROM movie"

        def materialize(self, raw: dict[str, Any]) -> Movie:
            return Movie(title=raw["title"], released=0)

    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SqlRead())

    result = validate_query_catalogue(query_catalogue, graph_definition)

    unverifiable = [i for i in result.issues if i.code == "QUERY_UNVERIFIABLE"]
    assert len(unverifiable) == 1
    issue = unverifiable[0]
    assert issue.severity == Severity.INFO
    assert issue.entity_type == EntityType.QUERY
    assert issue.entity_id == "sql_read"
    assert "sqlalchemy" in issue.message.lower()


def test_mixed_catalogue_reports_each_query(graph_definition: GraphDefinition) -> None:
    """Errors and unverifiable reports are merged across all registered queries."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)

        class ImperativeRead(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "imperative_read_2"

            def build(self, params: ReleasedYearParams) -> CypherQuery:
                return ("MATCH (m:Movie) RETURN m", {})

            def materialize(self, raw: dict[str, Any]) -> Movie:
                return Movie(title="x", released=0)

    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(MoviesByYear())  # clean
    query_catalogue.register_read(MoviesByTitleBadLabel())  # ERROR
    query_catalogue.register_read(ImperativeRead())  # UNVERIFIABLE

    result = validate_query_catalogue(query_catalogue, graph_definition)

    assert not result.is_valid  # the bad-label query
    assert any(i.code == "QUERY_UNVERIFIABLE" for i in result.issues)
    assert any("Film" in i.message for i in result.errors)
