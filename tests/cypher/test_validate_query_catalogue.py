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
  * Declarative read queries with an ``Output`` model are additionally checked for
    RETURN→Output column alignment (``QUERY_RETURN_OUTPUT_MISMATCH``, INFO).
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
    """Declarative, model-consistent read — whole-node return against NodeModel."""

    Params = ReleasedYearParams
    Output = Movie
    name = "movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(**raw["m"])


class CreateMovie(CypherWriteQuery[ReleasedYearParams, int]):
    """Declarative, model-consistent write."""

    Params = ReleasedYearParams
    name = "create_movie"
    cypher_template = "CREATE (m:Movie {released: $released})"

    def interpret_result(self, raw: Any) -> int:
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


# ---------------------------------------------------------------------------
# T5: RETURN → Output column alignment check
# ---------------------------------------------------------------------------


class MovieTitleOutput(BaseModel):
    """Output model with two fields: title and released."""

    title: str
    released: int


class MoviesByYearPartialReturn(CypherReadQuery[ReleasedYearParams, MovieTitleOutput]):
    """Read that projects only m.title AS title — missing 'released' in RETURN."""

    Params = ReleasedYearParams
    Output = MovieTitleOutput
    name = "movies_by_year_partial"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title AS title"

    def materialize(self, raw: dict[str, Any]) -> MovieTitleOutput:
        return MovieTitleOutput(title=raw["title"], released=0)


class MoviesByYearFullReturn(CypherReadQuery[ReleasedYearParams, MovieTitleOutput]):
    """Read that projects both columns — no mismatch."""

    Params = ReleasedYearParams
    Output = MovieTitleOutput
    name = "movies_by_year_full"
    cypher_template = (
        "MATCH (m:Movie {released: $released}) "
        "RETURN m.title AS title, m.released AS released"
    )

    def materialize(self, raw: dict[str, Any]) -> MovieTitleOutput:
        return MovieTitleOutput(title=raw["title"], released=raw["released"])


class MoviesByYearReturnStar(CypherReadQuery[ReleasedYearParams, MovieTitleOutput]):
    """Read that uses RETURN * — alignment check must be skipped."""

    Params = ReleasedYearParams
    Output = MovieTitleOutput
    name = "movies_by_year_return_star"
    cypher_template = (
        "MATCH (m:Movie {released: $released}) "
        "RETURN m.title AS title, m.released AS released"
    )

    def materialize(self, raw: dict[str, Any]) -> MovieTitleOutput:
        return MovieTitleOutput(title=raw["title"], released=raw["released"])


def test_scalar_projection_missing_required_field_emits_error(
    graph_definition: GraphDefinition,
) -> None:
    """Scalar projection missing required Output field is an ERROR."""
    catalogue = QueryCatalogue()
    catalogue.register_read(MoviesByYearPartialReturn())

    result = validate_query_catalogue(catalogue, graph_definition)

    mismatch_issues = [
        i for i in result.issues if i.code == "QUERY_RETURN_OUTPUT_MISMATCH"
    ]
    assert len(mismatch_issues) == 1
    issue = mismatch_issues[0]
    assert issue.severity == Severity.ERROR
    assert issue.entity_type == EntityType.QUERY
    assert issue.entity_id == "movies_by_year_partial"
    assert "released" in issue.message
    # ERROR issues make the result invalid.
    assert not result.is_valid


def test_return_output_aligned_emits_no_mismatch_issue(
    graph_definition: GraphDefinition,
) -> None:
    """A query projecting all Output fields emits no QUERY_RETURN_OUTPUT_MISMATCH."""
    catalogue = QueryCatalogue()
    catalogue.register_read(MoviesByYearFullReturn())

    result = validate_query_catalogue(catalogue, graph_definition)

    mismatch_issues = [
        i for i in result.issues if i.code == "QUERY_RETURN_OUTPUT_MISMATCH"
    ]
    assert mismatch_issues == []


def test_whole_node_return_against_nodemodel_emits_no_issue(
    graph_definition: GraphDefinition,
) -> None:
    """RETURN m with Output = Movie (NodeModel) produces no mismatch and is valid."""

    class FindMovies(CypherReadQuery[ReleasedYearParams, Movie]):
        Params = ReleasedYearParams
        Output = Movie
        name = "find_movies_whole_node"
        cypher_template = "MATCH (m:Movie {released: $released}) RETURN m"

        def materialize(self, raw: dict[str, Any]) -> Movie:
            return Movie(**raw["m"])

    catalogue = QueryCatalogue()
    catalogue.register_read(FindMovies())

    result = validate_query_catalogue(catalogue, graph_definition)

    mismatch_issues = [
        i
        for i in result.issues
        if i.code
        in {"QUERY_RETURN_OUTPUT_MISMATCH", "QUERY_RETURN_OUTPUT_LABEL_MISMATCH"}
    ]
    assert mismatch_issues == [], (
        f"Whole-node vs matching NodeModel clean; got: {mismatch_issues}"
    )
    assert result.is_valid


def test_whole_node_return_wrong_label_emits_error(
    graph_definition: GraphDefinition,
) -> None:
    """RETURN m where m is a Movie but Output is a Person NodeModel → ERROR."""
    from orthograph.graph_definition.models import NodeModel as NM

    class PersonModel(NM):
        __label__ = "Person"
        __uid_field__ = "name"
        name: str

    class FindMoviesWrongOutput(CypherReadQuery[ReleasedYearParams, PersonModel]):
        Params = ReleasedYearParams
        Output = PersonModel
        name = "find_movies_wrong_output"
        cypher_template = "MATCH (m:Movie {released: $released}) RETURN m"

        def materialize(self, raw: dict[str, Any]) -> PersonModel:
            return PersonModel(name="x")

    # Need a graph_definition that knows Movie
    from orthograph.graph_definition.graph_definition import GraphDefinition as GD

    gd = GD(name="Film", node_types=[Movie, PersonModel], relationship_types=[])
    catalogue = QueryCatalogue()
    catalogue.register_read(FindMoviesWrongOutput())

    result = validate_query_catalogue(catalogue, gd)

    label_mismatch = [
        i for i in result.issues if i.code == "QUERY_RETURN_OUTPUT_LABEL_MISMATCH"
    ]
    assert len(label_mismatch) >= 1
    assert label_mismatch[0].severity == Severity.ERROR
    assert not result.is_valid


def test_projection_of_whole_nodes_emits_no_mismatch(
    graph_definition: GraphDefinition,
) -> None:
    """RETURN p, m with projection Output (person, movie) → no mismatch."""
    from orthograph.graph_definition.models import NodeModel as NM

    class PersonModel(NM):
        __label__ = "Person"
        __uid_field__ = "name"
        name: str

    class ActorMoviePair(BaseModel):
        person: PersonModel
        movie: Movie

    class FindActorMoviePairs(CypherReadQuery[ReleasedYearParams, ActorMoviePair]):
        Params = ReleasedYearParams
        Output = ActorMoviePair
        name = "find_actor_movie_pairs"
        cypher_template = (
            "MATCH (p:Person)-[:ACTED_IN]->(m:Movie {released: $released}) RETURN p, m"
        )

        def materialize(self, raw: dict[str, Any]) -> ActorMoviePair:
            return ActorMoviePair(
                person=PersonModel(**raw["p"]), movie=Movie(**raw["m"])
            )

    from orthograph.graph_definition.graph_definition import GraphDefinition as GD
    from orthograph.graph_definition.models import RelationshipModel

    class ActedIn(RelationshipModel):
        __label__ = "ACTED_IN"
        __source_label__ = "Person"
        __target_label__ = "Movie"
        role: str = ""

    gd = GD(name="Film", node_types=[Movie, PersonModel], relationship_types=[ActedIn])
    catalogue = QueryCatalogue()
    catalogue.register_read(FindActorMoviePairs())

    result = validate_query_catalogue(catalogue, gd)

    mismatch_issues = [
        i
        for i in result.issues
        if i.code
        in {"QUERY_RETURN_OUTPUT_MISMATCH", "QUERY_RETURN_OUTPUT_LABEL_MISMATCH"}
    ]
    assert mismatch_issues == [], (
        f"Projection Output with whole-node RETURN clean; got: {mismatch_issues}"
    )


def test_return_star_skips_alignment_check(
    graph_definition: GraphDefinition,
) -> None:
    """A query with RETURN * must not emit QUERY_RETURN_OUTPUT_MISMATCH."""
    # We test the underlying extract_return_columns function directly for RETURN *.
    from orthograph.cypher.parser import extract_return_columns

    result = extract_return_columns("MATCH (m:Movie) RETURN *")
    assert result is None, "RETURN * should cause extract_return_columns to return None"


def test_aggregation_skips_alignment_check(
    graph_definition: GraphDefinition,
) -> None:
    """A query with aggregation must not emit QUERY_RETURN_OUTPUT_MISMATCH."""
    from orthograph.cypher.parser import extract_return_columns

    result = extract_return_columns("MATCH (m:Movie) RETURN count(m)")
    assert result is None, (
        "Aggregation should cause extract_return_columns to return None"
    )


def test_write_query_without_return_emits_no_alignment_issue(
    graph_definition: GraphDefinition,
) -> None:
    """A WriteQuery with Output but no RETURN clause emits no alignment issue."""

    class CreateMovieWithOutput(CypherWriteQuery[ReleasedYearParams, int]):
        Params = ReleasedYearParams
        Output = MovieTitleOutput
        name = "create_movie_with_output"
        cypher_template = "CREATE (m:Movie {released: $released})"

        def interpret_result(self, raw: Any) -> int:
            return 1

    catalogue = QueryCatalogue()
    catalogue.register_write(CreateMovieWithOutput())

    result = validate_query_catalogue(catalogue, graph_definition)

    mismatch_issues = [
        i for i in result.issues if i.code == "QUERY_RETURN_OUTPUT_MISMATCH"
    ]
    assert mismatch_issues == []


def test_write_query_with_output_and_return_emits_no_alignment_issue(
    graph_definition: GraphDefinition,
) -> None:
    """A WriteQuery declaring Output AND a RETURN clause must not emit alignment issues.

    Before the fix, the T5 gate checked for the presence of an ``Output`` ClassVar
    without distinguishing read from write queries.  A write query with both
    ``Output`` and a ``RETURN`` clause would emit a false-positive
    ``QUERY_RETURN_OUTPUT_MISMATCH`` (INFO) for every Output field missing from the
    RETURN projection.  Writes expose only mutation counters — not projected rows —
    so the RETURN→Output alignment check must be skipped entirely for WriteQuery
    instances regardless of what the template projects.
    """

    class CreateMovieWithReturn(CypherWriteQuery[ReleasedYearParams, int]):
        Params = ReleasedYearParams
        # Output declares two fields; the RETURN only projects one — would have
        # triggered a false-positive mismatch on 'released' before the fix.
        Output = MovieTitleOutput
        name = "create_movie_with_return"
        cypher_template = (
            "CREATE (m:Movie {released: $released}) RETURN m.title AS title"
        )

        def interpret_result(self, raw: Any) -> int:
            return 1

    catalogue = QueryCatalogue()
    catalogue.register_write(CreateMovieWithReturn())

    result = validate_query_catalogue(catalogue, graph_definition)

    mismatch_issues = [
        i for i in result.issues if i.code == "QUERY_RETURN_OUTPUT_MISMATCH"
    ]
    assert mismatch_issues == [], (
        "WriteQuery instances must never emit QUERY_RETURN_OUTPUT_MISMATCH "
        "even when Output is declared and the template has a partial RETURN clause"
    )


def test_query_with_identifier_injection_emits_info_issue(
    graph_definition: GraphDefinition,
) -> None:
    """A query using <<...>> placeholders emits
    a QUERY_USES_IDENTIFIER_INJECTION INFO issue."""
    from pydantic import BaseModel

    from orthograph.cypher.bindings import NoParams

    class LabelIdentifiers(BaseModel):
        label: str

    class QueryWithIdentifierInjection(CypherReadQuery[NoParams, Movie]):
        Params = NoParams
        Output = Movie
        Identifiers = LabelIdentifiers
        name = "query_with_identifier_injection"
        cypher_template = (
            "MATCH (n:`<<label>>`) RETURN n.title AS title, n.released AS released"
        )

        def materialize(self, raw: dict[str, Any]) -> Movie:
            return Movie(title=raw["title"], released=raw["released"])

    catalogue = QueryCatalogue()
    catalogue.register_read(
        QueryWithIdentifierInjection(identifiers={"label": "Movie"})
    )

    result = validate_query_catalogue(catalogue, graph_definition)

    injection_issues = [
        i for i in result.issues if i.code == "QUERY_USES_IDENTIFIER_INJECTION"
    ]
    assert len(injection_issues) == 1
    issue = injection_issues[0]
    assert issue.severity == Severity.INFO
    assert issue.entity_type == EntityType.QUERY
    assert issue.entity_id == "query_with_identifier_injection"
    assert "identifier injection" in issue.message.lower()
    assert "<<" in issue.message
    # INFO issues do not make the result invalid.
    assert result.is_valid


def test_query_with_multiple_identifier_placeholders_emits_single_issue(
    graph_definition: GraphDefinition,
) -> None:
    """A query with multiple <<...>> placeholders emits
    exactly one QUERY_USES_IDENTIFIER_INJECTION issue."""
    from pydantic import BaseModel

    from orthograph.cypher.bindings import NoParams

    class MultipleIdentifiers(BaseModel):
        label: str
        rel_type: str

    class QueryWithMultipleIdentifiers(CypherReadQuery[NoParams, Movie]):
        Params = NoParams
        Output = Movie
        Identifiers = MultipleIdentifiers
        name = "query_with_multiple_identifiers"
        cypher_template = (
            "MATCH (n:`<<label>>`) "
            "-[r:`<<rel_type>>`]->() "
            "RETURN n.title AS title, n.released AS released"
        )

        def materialize(self, raw: dict[str, Any]) -> Movie:
            return Movie(title=raw["title"], released=raw["released"])

    catalogue = QueryCatalogue()
    catalogue.register_read(
        QueryWithMultipleIdentifiers(
            identifiers={"label": "Movie", "rel_type": "LIKES"}
        )
    )

    result = validate_query_catalogue(catalogue, graph_definition)

    injection_issues = [
        i for i in result.issues if i.code == "QUERY_USES_IDENTIFIER_INJECTION"
    ]
    assert len(injection_issues) == 1, (
        "Multiple <<...>> placeholders should emit exactly one info issue "
        "(not one per placeholder)"
    )
    assert result.is_valid


def test_query_without_identifier_injection_emits_no_issue(
    graph_definition: GraphDefinition,
) -> None:
    """A query without <<...>> placeholders
    emits no QUERY_USES_IDENTIFIER_INJECTION issue."""
    catalogue = QueryCatalogue()
    catalogue.register_read(MoviesByYear())

    result = validate_query_catalogue(catalogue, graph_definition)

    injection_issues = [
        i for i in result.issues if i.code == "QUERY_USES_IDENTIFIER_INJECTION"
    ]
    assert injection_issues == []


def test_inspect_cardinality_query_emits_identifier_injection_issue(
    graph_definition: GraphDefinition,
) -> None:
    """InspectCardinalityQuery (uses <<label>> and <<rel_type>>)
    emits QUERY_USES_IDENTIFIER_INJECTION."""
    from orthograph.graph_profile.queries.shared import InspectCardinalityQuery

    catalogue = QueryCatalogue()
    catalogue.register_read(
        InspectCardinalityQuery(identifiers={"label": "Movie", "rel_type": "LIKES"})
    )

    result = validate_query_catalogue(catalogue, graph_definition)

    injection_issues = [
        i for i in result.issues if i.code == "QUERY_USES_IDENTIFIER_INJECTION"
    ]
    assert len(injection_issues) >= 1, (
        "InspectCardinalityQuery uses <<label>> and <<rel_type>>, "
        "so it should emit at least one QUERY_USES_IDENTIFIER_INJECTION INFO issue"
    )
    # Check that the issue message mentions the query name
    assert any("inspect.cardinality" in i.message for i in injection_issues)
