"""Tests for CypherReadQuery and CypherWriteQuery (no driver — R1/R3).

These exercise the concrete Cypher backend bases purely. Two authoring styles
are covered:

  * Declarative — a ``cypher_template`` ClassVar; the base validates it at
    definition time and supplies a default ``build()`` returning
    ``(cypher_template, params)``.
  * Imperative — ``build()`` implemented directly for conditional queries.

``materialize()`` maps a hand-built record dict to the declared Output
NodeModel; no session is ever opened. The examples use the classic Neo4j
movies domain (Movie / Person).
"""

import warnings
from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.core.node_model import NodeModel
from orthograph.extensions.cypher import (
    CypherQueryDefinitionError,
    CypherReadQuery,
    CypherWriteQuery,
)
from orthograph.extensions.cypher.base_models import (
    CypherQuery,
    extract_cypher_params,
)


class ReleasedYearParams(BaseModel):
    released: int


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    released: int


# --- Declarative style: cypher_template ClassVar + default build() ---


class MoviesByYearCypher(CypherReadQuery[ReleasedYearParams, Movie]):
    """Declarative read — placeholder ``$released`` matches the Params field."""

    Params = ReleasedYearParams
    Output = Movie
    name = "movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title, m.released"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(title=raw["m.title"], released=raw["m.released"])


# --- Imperative style: build() overridden, no cypher_template ClassVar ---

# Suppress the expected UserWarning for imperative-style definitions at module level.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)

    class MoviesByYearImperative(CypherReadQuery[ReleasedYearParams, Movie]):
        """Imperative read — same logical query, build() constructs it by hand."""

        Params = ReleasedYearParams
        Output = Movie
        name = "movies_by_year_imperative"

        def build(self, params: ReleasedYearParams) -> CypherQuery:
            return (
                "MATCH (m:Movie {released: $year}) "
                "RETURN m.title AS t, m.released AS y",
                {"year": params.released},
            )

        def materialize(self, raw: dict[str, Any]) -> Movie:
            return Movie(title=raw["t"], released=raw["y"])


class CreateMovieCypher(CypherWriteQuery[ReleasedYearParams, int]):
    """Declarative write."""

    Params = ReleasedYearParams
    name = "create_movie"
    cypher_template = "CREATE (m:Movie {released: $released})"

    def interpret_result(self, raw: object) -> int:
        return 1


def test_import_cypher_query_base_models() -> None:
    """CypherReadQuery and CypherWriteQuery import from the cypher package."""
    from orthograph.extensions.cypher import (  # noqa: F401
        CypherReadQuery,
        CypherWriteQuery,
    )


def test_cypher_backend_tag_is_cypher() -> None:
    """The concrete bases fix backend to CYPHER without subclasses setting it."""
    from orthograph.catalogue.typed import Backend

    assert MoviesByYearCypher.backend is Backend.CYPHER
    assert CreateMovieCypher.backend is Backend.CYPHER


# --- Declarative default build() ---


def test_declarative_read_default_build_returns_cypher_and_dumped_params() -> None:
    """Declarative read's default build() returns (cypher_template, model_dump())."""
    query = MoviesByYearCypher()
    cypher, params = query.build(ReleasedYearParams(released=1999))
    assert cypher == MoviesByYearCypher.cypher_template
    assert params == {"released": 1999}


def test_declarative_write_default_build_returns_cypher_and_dumped_params() -> None:
    """Declarative write's default build() returns (cypher_template, model_dump())."""
    query = CreateMovieCypher()
    cypher, params = query.build(ReleasedYearParams(released=2003))
    assert cypher == CreateMovieCypher.cypher_template
    assert params == {"released": 2003}


# --- Imperative build() still works (no cypher_template ClassVar) ---


def test_imperative_read_build_returns_str_dict_tuple_no_driver() -> None:
    """An imperative build() returns a (str, dict) tuple with no driver/session."""
    query = MoviesByYearImperative()
    cypher, params = query.build(ReleasedYearParams(released=1999))
    assert isinstance(cypher, str)
    assert isinstance(params, dict)
    assert params == {"year": 1999}


# --- materialize() ---


def test_read_materialize_returns_output_nodemodel() -> None:
    """materialize() maps a hand-built record dict to the declared Output NodeModel."""
    query = MoviesByYearCypher()
    result = query.materialize({"m.title": "The Matrix", "m.released": 1999})
    assert isinstance(result, Movie)
    assert result.title == "The Matrix"
    assert result.released == 1999


def test_two_reads_same_output_have_identical_schema() -> None:
    """Two CypherReadQuerys with the same Output share an identical JSON schema.

    Port-swappability proof at the schema level: regardless of authoring style
    or raw record shape, they declare the same domain Output.
    """
    assert (
        MoviesByYearCypher.Output.model_json_schema()
        == MoviesByYearImperative.Output.model_json_schema()
    )


# --- write interpret_result ---


def test_write_interpret_result() -> None:
    """interpret_result() maps the raw driver result to the declared type."""
    query = CreateMovieCypher()
    assert query.interpret_result(object()) == 1


# --- extract_cypher_params helper ---


def test_extract_cypher_params_finds_placeholders() -> None:
    """extract_cypher_params returns the set of $name placeholders in a query."""
    cypher = (
        "MATCH (m:Movie {released: $released})<-[:ACTED_IN]-(p:Person) "
        "WHERE p.name = $name RETURN m"
    )
    assert extract_cypher_params(cypher) == {"released", "name"}


def test_extract_cypher_params_empty_when_no_params() -> None:
    """extract_cypher_params returns an empty set when no placeholders are present."""
    assert extract_cypher_params("MATCH (m:Movie) RETURN m") == set()


# --- definition-time validation of declarative cypher_template ---


def test_declarative_cypher_param_not_in_params_raises() -> None:
    """A $param with no matching Params field raises TypeError at definition time."""
    with pytest.raises(CypherQueryDefinitionError, match=r"\$missing.*not declared"):

        class BadRead(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "bad_read_param"
            cypher_template = "MATCH (m:Movie {released: $missing}) RETURN m"

            def materialize(self, raw: dict[str, Any]) -> Movie:
                return Movie(title=raw["t"], released=raw["y"])


def test_declarative_cypher_unparseable_raises() -> None:
    """Cypher that does not parse under the dialect raises TypeError at definition."""
    with pytest.raises(CypherQueryDefinitionError, match="does not parse"):

        class BadRead(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "bad_read_syntax"
            cypher_template = "THIS IS NOT CYPHER {{{ ("

            def materialize(self, raw: dict[str, Any]) -> Movie:
                return Movie(title=raw["t"], released=raw["y"])


def test_declarative_cypher_empty_string_raises() -> None:
    """An empty cypher_template raises TypeError at definition time."""
    with pytest.raises(
        CypherQueryDefinitionError, match="cypher_template must be a non-empty string"
    ):

        class BadRead(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "bad_read_empty"
            cypher_template = "   "

            def materialize(self, raw: dict[str, Any]) -> Movie:
                return Movie(title=raw["t"], released=raw["y"])


def test_declarative_write_param_not_in_params_raises() -> None:
    """A declarative write with an unknown $param raises TypeError at definition."""
    with pytest.raises(CypherQueryDefinitionError, match=r"\$missing.*not declared"):

        class BadWrite(CypherWriteQuery[ReleasedYearParams, int]):
            Params = ReleasedYearParams
            name = "bad_write_param"
            cypher_template = "CREATE (m:Movie {released: $missing})"

            def interpret_result(self, raw: object) -> int:
                return 1


def test_declarative_cypher_unused_params_field_raises() -> None:
    """A Params field with no matching $placeholder raises at definition time.

    Params map 1:1 to placeholders; a declared-but-unused field is silently
    ignored at runtime (usually a rename/typo) and must fail fast.
    """

    class TwoFieldParams(BaseModel):
        released: int
        genre: str

    with pytest.raises(
        CypherQueryDefinitionError, match=r"\$genre.*no matching placeholder"
    ):

        class BadRead(CypherReadQuery[TwoFieldParams, Movie]):
            Params = TwoFieldParams
            Output = Movie
            name = "bad_read_unused_param"
            # $genre is declared on Params but never referenced.
            cypher_template = "MATCH (m:Movie {released: $released}) RETURN m"

            def materialize(self, raw: dict[str, Any]) -> Movie:
                return Movie(title=raw["t"], released=raw["y"])


def test_declarative_write_unused_params_field_raises() -> None:
    """A declarative write with a declared-but-unused Params field raises."""

    class TwoFieldParams(BaseModel):
        released: int
        genre: str

    with pytest.raises(
        CypherQueryDefinitionError, match=r"\$genre.*no matching placeholder"
    ):

        class BadWrite(CypherWriteQuery[TwoFieldParams, int]):
            Params = TwoFieldParams
            name = "bad_write_unused_param"
            cypher_template = "CREATE (m:Movie {released: $released})"

            def interpret_result(self, raw: object) -> int:
                return 1


def test_declarative_optional_filter_pattern_does_not_flag_params() -> None:
    """The ``$param IS NULL OR`` optional-filter pattern uses each param as a
    placeholder, so it satisfies the 1:1 check and must not raise.
    """

    class OptionalFilterParams(BaseModel):
        released: int | None = None
        genre: str | None = None

    # Definition must succeed; both fields appear as $placeholders.
    class FilteredRead(CypherReadQuery[OptionalFilterParams, Movie]):
        Params = OptionalFilterParams
        Output = Movie
        name = "filtered_read"
        cypher_template = (
            "MATCH (m:Movie) "
            "WHERE ($released IS NULL OR m.released = $released) "
            "AND ($genre IS NULL OR m.genre = $genre) "
            "RETURN m.title, m.released"
        )

        def materialize(self, raw: dict[str, Any]) -> Movie:
            return Movie(title=raw["m.title"], released=raw["m.released"])

    assert FilteredRead.Params is OptionalFilterParams


def test_imperative_query_skips_cypher_validation() -> None:
    """A subclass with no cypher_template ClassVar is not subject to definition-time
    Cypher validation.

    The imperative example above already proves construction; here we assert the
    class has no ``cypher_template`` attribute and still builds.
    """
    assert not hasattr(MoviesByYearImperative, "cypher_template")
    query = MoviesByYearImperative()
    assert query.build(ReleasedYearParams(released=1999)) is not None


def test_imperative_without_cypher_template_and_without_build_override_raises() -> None:
    """Default build() with no cypher_template raises NotImplementedError."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)

        class NoCypherRead(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "no_cypher_read"

            def materialize(self, raw: dict[str, Any]) -> Movie:
                return Movie(title=raw["t"], released=raw["y"])

    with pytest.raises(NotImplementedError, match="sets no 'cypher_template'"):
        NoCypherRead().build(ReleasedYearParams(released=1999))


# --- UserWarning for imperative style ---


def test_imperative_definition_emits_user_warning() -> None:
    """Defining a query without cypher_template emits a UserWarning."""
    with pytest.warns(UserWarning, match="imperative style"):

        class WarnedRead(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "warned_read"

            def build(self, params: ReleasedYearParams) -> CypherQuery:
                return (
                    "MATCH (m:Movie) RETURN m.title, m.released",
                    {},
                )

            def materialize(self, raw: dict[str, Any]) -> Movie:
                return Movie(title=raw["m.title"], released=raw["m.released"])


def test_imperative_warning_points_to_caller_not_framework() -> None:
    """The imperative-style warning's stacklevel points to the user's class
    definition site, not orthograph's framework internals.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        class WarnedReadStack(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "warned_read_stack"

            def build(self, params: ReleasedYearParams) -> CypherQuery:
                return ("MATCH (m:Movie) RETURN m.title, m.released", {})

            def materialize(self, raw: dict[str, Any]) -> Movie:
                return Movie(title=raw["m.title"], released=raw["m.released"])

    assert len(caught) == 1
    # The warning must originate from THIS test file (the caller), not from
    # base_models.py (the framework) nor abc internals.
    assert caught[0].filename == __file__
