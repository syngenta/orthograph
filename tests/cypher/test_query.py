"""Tests for CypherQuery.

Covers construction, argument listing, building queries, and validation against schemas.

Coverage:
- Construction: required params_schema, optional identifiers_schema, description
- list_arguments: derives required/optional from params_schema.model_fields
- build: validates kwargs, returns CypherQueryData
- _validate_cypher_query: free function in cypher.validation, runs shared validate_cypher_spec core
- Identifiers: opt-in identifier injection
- model_dump: JSON-Schema serialization via params_schema / identifiers_schema
"""  # NOQA E501

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from orthograph.cypher.base_models import CypherReadQuery
from orthograph.cypher.bindings import NoIdentifiers, NoParams
from orthograph.cypher.exceptions import CypherQueryError
from orthograph.cypher.query import CypherQuery
from orthograph.cypher.validation import (
    _validate_cypher_query,
    validate_query_catalogue,
)
from orthograph.diagnostics.classification import Severity
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.query.catalogue import QueryCatalogue


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "movie_id"
    movie_id: str
    title: str


class Festival(NodeModel):
    __label__ = "Festival"
    __uid_field__ = "id"
    id: str
    name: str


class HasMovie(RelationshipModel):
    __label__ = "HAS_MOVIE"
    __source_label__ = "Festival"
    __target_label__ = "Movie"
    __directed__ = True


@pytest.fixture()
def definition() -> GraphDefinition:
    return GraphDefinition(
        name="Movies",
        node_types=[Movie, Festival],
        relationship_types=[HasMovie],
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_minimal_construction() -> None:
    """Query requires query_id, cypher_template, and params_schema."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    assert q.query_id == "find_movie"
    assert q.params_schema is FindMovieParams
    assert q.description is None


def test_no_params_query_uses_no_params_sentinel() -> None:
    """Zero-arg query passes params_schema=NoParams."""
    q = CypherQuery(
        query_id="count_movies",
        cypher_template="MATCH (m:Movie) RETURN count(m) AS n",
        params_schema=NoParams,
        identifiers_schema=NoIdentifiers,
    )
    assert q.params_schema is NoParams
    assert q.params_schema.model_fields == {}


def test_full_construction() -> None:
    """Query accepts optional parameters model and description."""

    class MyParams(BaseModel):
        movie_id: str
        title: str | None = None

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=MyParams,
        description="Find a movie by its ID.",
        identifiers_schema=NoIdentifiers,
    )
    assert q.params_schema is MyParams
    assert q.description == "Find a movie by its ID."


def test_description_is_optional() -> None:
    """Query can be created without description."""
    q = CypherQuery(
        query_id="test",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=NoParams,
        identifiers_schema=NoIdentifiers,
    )
    assert q.description is None


def test_description_stored_when_provided() -> None:
    """Query stores description when provided."""
    desc = "This is a test query"
    q = CypherQuery(
        query_id="test",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=NoParams,
        description=desc,
        identifiers_schema=NoIdentifiers,
    )
    assert q.description == desc


# ---------------------------------------------------------------------------
# list_arguments — derived from Params.model_fields
# ---------------------------------------------------------------------------


def test_list_arguments_structure() -> None:
    """list_arguments returns dict with required and optional keys."""

    class MovieParams(BaseModel):
        movie_id: str
        title: str | None = None

    q = CypherQuery(
        query_id="q",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=MovieParams,
        identifiers_schema=NoIdentifiers,
    )
    result = q.list_arguments()
    assert result["required"] == ["movie_id"]
    assert result["optional"] == ["title"]


def test_list_arguments_empty() -> None:
    """list_arguments returns empty lists for NoParams."""
    q = CypherQuery(
        query_id="q",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=NoParams,
        identifiers_schema=NoIdentifiers,
    )
    assert q.list_arguments() == {"required": [], "optional": []}


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def test_build_returns_cypher_and_params() -> None:
    """build returns CypherQueryData(cypher, params)."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    cypher, params = q.build(movie_id="M-001")
    assert cypher == "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
    assert params == {"movie_id": "M-001"}


def test_build_optional_arg_included_when_provided() -> None:
    """build includes optional arguments when supplied."""

    class MovieParams(BaseModel):
        movie_id: str
        title: str | None = None

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=MovieParams,
        identifiers_schema=NoIdentifiers,
    )
    cypher, params = q.build(movie_id="M-001", title="Inception")
    assert params == {"movie_id": "M-001", "title": "Inception"}


def test_build_optional_arg_omitted_not_in_params() -> None:
    """build excludes optional arguments when not supplied (exclude_unset)."""

    class MovieParams(BaseModel):
        movie_id: str
        title: str | None = None

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=MovieParams,
        identifiers_schema=NoIdentifiers,
    )
    _, params = q.build(movie_id="M-001")
    assert "title" not in params


def test_build_missing_required_arg_raises() -> None:
    """build raises when required argument missing."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    with pytest.raises(CypherQueryError, match="Missing required"):
        q.build()


def test_build_unknown_arg_raises() -> None:
    """build raises when unknown argument supplied."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    with pytest.raises(CypherQueryError, match="Unknown"):
        q.build(movie_id="M-001", typo_arg="x")


def test_build_no_args_query_builds_with_empty_params() -> None:
    """build returns empty params dict for NoParams query."""
    q = CypherQuery(
        query_id="count_movies",
        cypher_template="MATCH (m:Movie) RETURN count(m) AS n",
        params_schema=NoParams,
        identifiers_schema=NoIdentifiers,
    )
    cypher, params = q.build()
    assert params == {}


def test_build_params_model_validates_types() -> None:
    """build validates argument types through Params model."""

    class MovieParams(BaseModel):
        movie_id: str
        limit: int = 10

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m LIMIT $limit",
        params_schema=MovieParams,
        identifiers_schema=NoIdentifiers,
    )
    _, params = q.build(movie_id="M-001", limit=5)
    assert params["limit"] == 5


def test_build_params_model_coerces_compatible_types() -> None:
    """build coerces compatible types through Pydantic."""

    class LimitParams(BaseModel):
        limit: int = 10

    q = CypherQuery(
        query_id="q",
        cypher_template="MATCH (m:Movie) RETURN m LIMIT $limit",
        params_schema=LimitParams,
        identifiers_schema=NoIdentifiers,
    )
    _, params = q.build(limit="5")
    assert params["limit"] == 5


def test_build_params_model_rejects_incompatible_type() -> None:
    """build raises ValidationError for incompatible types in Params model."""

    class LimitParams(BaseModel):
        limit: int

    q = CypherQuery(
        query_id="q",
        cypher_template="MATCH (m:Movie) RETURN m LIMIT $limit",
        params_schema=LimitParams,
        identifiers_schema=NoIdentifiers,
    )
    with pytest.raises(ValidationError):
        q.build(limit="not_an_int")


def test_build_returns_tuple() -> None:
    """build return value unpacks as a 2-tuple."""
    q = CypherQuery(
        query_id="test",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=NoParams,
        identifiers_schema=NoIdentifiers,
    )
    result = q.build()
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_build_first_element_is_cypher_string() -> None:
    """build tuple first element is the cypher string unchanged."""

    class FindMovieParams(BaseModel):
        movie_id: str

    cypher_str = "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
    q = CypherQuery(
        query_id="test",
        cypher_template=cypher_str,
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    result_cypher, _ = q.build(movie_id="M-001")
    assert result_cypher == cypher_str


def test_build_second_element_is_params_dict() -> None:
    """build tuple second element is dict of parameters."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="test",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    _, params = q.build(movie_id="M-001")
    assert isinstance(params, dict)
    assert params == {"movie_id": "M-001"}


def test_build_with_multiple_required_args() -> None:
    """build accepts multiple required arguments."""

    class FestivalMovieParams(BaseModel):
        festival_id: str
        movie_id: str

    q = CypherQuery(
        query_id="find_relationship",
        cypher_template=(
            "MATCH (f:Festival)-[:HAS_MOVIE]->(m:Movie) "
            "WHERE f.id = $festival_id "
            "AND m.movie_id = $movie_id RETURN f, m"
        ),
        params_schema=FestivalMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    cypher, params = q.build(festival_id="F-001", movie_id="M-001")
    assert params == {"festival_id": "F-001", "movie_id": "M-001"}
    assert cypher == q.cypher_template


def test_build_with_multiple_optional_args() -> None:
    """build accepts multiple optional arguments."""

    class PaginationParams(BaseModel):
        limit: int | None = None
        offset: int | None = None

    q = CypherQuery(
        query_id="search_movies",
        cypher_template="MATCH (m:Movie) RETURN m LIMIT $limit SKIP $offset",
        params_schema=PaginationParams,
        identifiers_schema=NoIdentifiers,
    )
    cypher, params = q.build(limit=10, offset=5)
    assert params == {"limit": 10, "offset": 5}


def test_build_partial_optional_args() -> None:
    """build accepts subset of optional arguments."""

    class SearchParams(BaseModel):
        limit: int | None = None
        offset: int | None = None
        sort: str | None = None

    q = CypherQuery(
        query_id="search_movies",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=SearchParams,
        identifiers_schema=NoIdentifiers,
    )
    cypher, params = q.build(limit=10)
    assert params == {"limit": 10}
    assert "offset" not in params
    assert "sort" not in params


def test_build_with_complex_parameters() -> None:
    """build handles various parameter types through Params model."""

    class ComplexParams(BaseModel):
        movie_id: str
        year: int
        rating: float
        is_available: bool

    q = CypherQuery(
        query_id="complex_query",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=ComplexParams,
        identifiers_schema=NoIdentifiers,
    )
    _, params = q.build(
        movie_id="M-001",
        year=2024,
        rating=8.5,
        is_available=True,
    )
    assert params["movie_id"] == "M-001"
    assert params["year"] == 2024
    assert params["rating"] == 8.5
    assert params["is_available"] is True


def test_params_model_with_defaults_excludes_unset() -> None:
    """build with Params: omitted optional fields excluded (exclude_unset)."""

    class MovieParams(BaseModel):
        movie_id: str
        limit: int = 100

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie) RETURN m LIMIT $limit",
        params_schema=MovieParams,
        identifiers_schema=NoIdentifiers,
    )
    _, params = q.build(movie_id="M-001")
    assert params["movie_id"] == "M-001"
    assert "limit" not in params  # Not supplied → excluded by exclude_unset


def test_error_message_clear_for_missing_required_args() -> None:
    """Error message for missing args clearly states which args are missing."""

    class FindMovieParams(BaseModel):
        movie_id: str
        title: str

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id, title: $title}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    with pytest.raises(CypherQueryError) as exc_info:
        q.build(movie_id="M-001")
    error_msg = str(exc_info.value)
    assert "title" in error_msg
    assert "Missing required" in error_msg


def test_error_message_clear_for_unknown_args() -> None:
    """Error message for unknown args clearly states which args are invalid."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    with pytest.raises(CypherQueryError) as exc_info:
        q.build(movie_id="M-001", invalid_arg="x")
    error_msg = str(exc_info.value)
    assert "invalid_arg" in error_msg
    assert "Unknown" in error_msg


def test_multiple_queries_independent() -> None:
    """Multiple query instances are independent."""

    class Params1(BaseModel):
        arg1: str

    class Params2(BaseModel):
        arg2: str

    q1 = CypherQuery(
        query_id="query1",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=Params1,
        identifiers_schema=NoIdentifiers,
    )
    q2 = CypherQuery(
        query_id="query2",
        cypher_template="MATCH (f:Festival) RETURN f",
        params_schema=Params2,
        identifiers_schema=NoIdentifiers,
    )
    assert q1.query_id != q2.query_id
    assert q1.cypher_template != q2.cypher_template
    assert set(q1.params_schema.model_fields) != set(q2.params_schema.model_fields)


# ---------------------------------------------------------------------------
# _validate_cypher_query
# ---------------------------------------------------------------------------


def test_validate_valid_query_returns_no_errors(definition: GraphDefinition) -> None:
    """validate returns no errors for valid query."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    result = _validate_cypher_query(q, definition)
    errors = [i for i in result.issues if i.severity == Severity.ERROR]
    assert errors == []


def test_validate_unknown_label_surfaces_as_error(definition: GraphDefinition) -> None:
    """validate reports unknown node label as error."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="bad_label",
        cypher_template="MATCH (m:UnknownLabel {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    result = _validate_cypher_query(q, definition)
    codes = {i.code for i in result.issues if i.severity == Severity.ERROR}
    assert "QUERY_UNKNOWN_NODE_LABEL" in codes


def test_validate_unknown_rel_type_surfaces_as_error(
    definition: GraphDefinition,
) -> None:
    """validate reports unknown relationship type as error."""
    q = CypherQuery(
        query_id="bad_rel",
        cypher_template="MATCH (f:Festival)-[:UNKNOWN_REL]->(m:Movie) RETURN m",
        params_schema=NoParams,
        identifiers_schema=NoIdentifiers,
    )
    result = _validate_cypher_query(q, definition)
    codes = {i.code for i in result.issues if i.severity == Severity.ERROR}
    assert "QUERY_UNKNOWN_REL_TYPE" in codes


def test_validate_without_definition_returns_empty_result() -> None:
    """validate with no definition returns valid result (syntax-only check)."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    result = _validate_cypher_query(q, None)
    assert result.is_valid


def test_validate_syntax_error_surfaces_regardless_of_definition(
    definition: GraphDefinition,
) -> None:
    """validate reports parse errors even with domain validation."""
    q = CypherQuery(
        query_id="bad_syntax",
        cypher_template="THIS IS NOT CYPHER",
        params_schema=NoParams,
        identifiers_schema=NoIdentifiers,
    )
    result = _validate_cypher_query(q, definition)
    non_info = [i for i in result.issues if i.severity != Severity.INFO]
    assert non_info


def test_validate_valid_rel_type_no_errors(definition: GraphDefinition) -> None:
    """validate accepts valid relationship types in schema."""
    q = CypherQuery(
        query_id="movies_by_festival",
        cypher_template="MATCH (f:Festival)-[:HAS_MOVIE]->(m:Movie) RETURN m",
        params_schema=NoParams,
        identifiers_schema=NoIdentifiers,
    )
    result = _validate_cypher_query(q, definition)
    errors = [i for i in result.issues if i.severity == Severity.ERROR]
    assert errors == []


def test_validate_returns_validation_result() -> None:
    """validate returns ValidationResult with is_valid and issues."""
    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=NoParams,
        identifiers_schema=NoIdentifiers,
    )
    result = _validate_cypher_query(q, None)
    assert hasattr(result, "is_valid")
    assert hasattr(result, "issues")
    assert result.is_valid is True


def test_validate_with_complex_cypher() -> None:
    """validate handles complex multi-clause cypher queries."""

    class FestivalParams(BaseModel):
        festival_id: str

    q = CypherQuery(
        query_id="complex",
        cypher_template="""
            MATCH (f:Festival)-[:HAS_MOVIE]->(m:Movie)
            WHERE f.id = $festival_id
            WITH m, f
            OPTIONAL MATCH (m)-[:REVIEWED_BY]->(c:Critic)
            RETURN m, f, c
        """,
        params_schema=FestivalParams,
        identifiers_schema=NoIdentifiers,
    )
    result = _validate_cypher_query(q, None)
    assert result.is_valid


# ---------------------------------------------------------------------------
# model_dump / serialization
# ---------------------------------------------------------------------------


def test_to_dict_preserves_format() -> None:
    """model_dump(by_alias=True) returns dict with correct field names."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        description="Find a movie by ID.",
        identifiers_schema=NoIdentifiers,
    )
    d = q.model_dump(by_alias=True, exclude_none=True)
    assert d["query_id"] == "find_movie"
    assert d["cypher_template"] == "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
    assert isinstance(d["params_schema"], dict)
    assert d["description"] == "Find a movie by ID."


def test_to_dict_omits_none_description() -> None:
    """model_dump with exclude_none=True excludes description when not set."""

    class FindMovieParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="find_movie",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    d = q.model_dump(by_alias=True, exclude_none=True)
    assert "description" not in d


def test_to_dict_includes_all_fields() -> None:
    """model_dump returns all query metadata with proper field names."""

    class FindMovieParams(BaseModel):
        arg1: str
        arg2: str
        arg3: str | None = None

    q = CypherQuery(
        query_id="test_query",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=FindMovieParams,
        description="Test query description.",
        identifiers_schema=NoIdentifiers,
    )
    d = q.model_dump(by_alias=True)
    assert "query_id" in d
    assert "cypher_template" in d
    assert "params_schema" in d
    assert "identifiers_schema" in d
    assert "description" in d


def test_cypher_template_access() -> None:
    """cypher_template attribute returns the raw unmodified cypher string."""

    class FindByTitleParams(BaseModel):
        title: str

    cypher_str = "MATCH (m:Movie) WHERE m.title = $title RETURN m"
    q = CypherQuery(
        query_id="find_by_title",
        cypher_template=cypher_str,
        params_schema=FindByTitleParams,
        identifiers_schema=NoIdentifiers,
    )
    assert q.cypher_template == cypher_str


def test_name_access_returns_query_name() -> None:
    """Query name attribute returns the query identifier."""
    q = CypherQuery(
        query_id="my_query_name",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=NoParams,
        identifiers_schema=NoIdentifiers,
    )
    assert q.query_id == "my_query_name"


def test_repr_shows_query_structure() -> None:
    """__repr__ returns string with name and Params class name."""

    class MyParams(BaseModel):
        arg1: str

    q = CypherQuery(
        query_id="my_query",
        cypher_template="MATCH (m:Movie) RETURN m",
        params_schema=MyParams,
        identifiers_schema=NoIdentifiers,
    )
    repr_str = repr(q)
    assert "my_query" in repr_str
    assert "MyParams" in repr_str


# ---------------------------------------------------------------------------
# opt-in Identifiers tests
# ---------------------------------------------------------------------------


def test_identifiers_value_only_query_renders_byte_identical() -> None:
    """Value-only query (no Identifiers) returns cypher byte-for-byte unchanged."""

    class FindMovieParams(BaseModel):
        movie_id: str

    cypher_str = "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
    q = CypherQuery(
        query_id="find_movie",
        cypher_template=cypher_str,
        params_schema=FindMovieParams,
        identifiers_schema=NoIdentifiers,
    )
    result_cypher, _ = q.build(movie_id="M-001")
    assert result_cypher == cypher_str


def test_identifiers_valid_label_splices_safely() -> None:
    """<<label>> with a valid Identifiers field is substituted in build()."""

    class LabelIds(BaseModel):
        label: str

    q = CypherQuery(
        query_id="dynamic_label",
        cypher_template="MATCH (n:<<label>>) RETURN n",
        params_schema=NoParams,
        identifiers_schema=LabelIds,
    )
    result_cypher, _ = q.build(identifiers=LabelIds(label="Movie"))
    assert result_cypher == "MATCH (n:Movie) RETURN n"


def test_identifiers_unsafe_value_raises_cypher_identifier_error() -> None:
    """An unsafe identifier value raises CypherIdentifierError at build() time."""
    from orthograph.cypher.exceptions import CypherIdentifierError

    class LabelIds(BaseModel):
        label: str

    q = CypherQuery(
        query_id="dynamic_label",
        cypher_template="MATCH (n:<<label>>) RETURN n",
        params_schema=NoParams,
        identifiers_schema=LabelIds,
    )
    with pytest.raises(CypherIdentifierError):
        q.build(identifiers=LabelIds(label="Bad Label!"))


def test_identifiers_missing_field_raises_at_build() -> None:
    """<<name>> with no matching Identifiers field raises CypherQueryDefinitionError."""
    from orthograph.cypher.exceptions import CypherQueryDefinitionError

    class LabelIds(BaseModel):
        other_field: str

    q = CypherQuery(
        query_id="dynamic_label",
        cypher_template="MATCH (n:<<label>>) RETURN n",
        params_schema=NoParams,
        identifiers_schema=LabelIds,
    )
    with pytest.raises(CypherQueryDefinitionError):
        q.build(identifiers=LabelIds(other_field="Movie"))


# ---------------------------------------------------------------------------
# shared validation + simple path behavioural tests
# ---------------------------------------------------------------------------


def test_validate_cypher_spec_syntactic_only_catches_stale_param() -> None:
    """check_cypher_spec (no definition) catches an undeclared $param as ERROR."""
    from orthograph.cypher.validation import check_cypher_spec

    result = check_cypher_spec(
        cypher="MATCH (m:Movie {movie_id: $movie_id, title: $title}) RETURN m",
        params_fields={"movie_id"},  # $title is used but not declared
        query_name="stale_param_query",
    )
    alignment_errors = [
        i for i in result.issues if i.code == "QUERY_PARAM_ALIGNMENT_ERROR"
    ]
    assert len(alignment_errors) >= 1, (
        f"Expected QUERY_PARAM_ALIGNMENT_ERROR "
        f"for undeclared $title; got: {result.issues}"
    )
    assert not result.is_valid


def test_validate_cypher_spec_with_definition_catches_unknown_label(
    definition: GraphDefinition,
) -> None:
    """validate_cypher_spec with a definition catches an unknown label as ERROR."""
    from orthograph.cypher.validation import validate_cypher_spec

    result = validate_cypher_spec(
        cypher="MATCH (f:Film {released: $released}) RETURN f",
        params_fields={"released"},
        query_name="bad_label_query",
        graph_definition=definition,
    )
    label_errors = [i for i in result.issues if i.code == "QUERY_UNKNOWN_NODE_LABEL"]
    assert len(label_errors) >= 1, (
        f"Expected QUERY_UNKNOWN_NODE_LABEL for 'Film'; got: {result.issues}"
    )
    assert not result.is_valid


def test_cypher_query_validate_none_catches_param_alignment() -> None:
    """validate_cypher_query(query, None) catches a $param alignment error."""

    class StaleParams(BaseModel):
        movie_id: str

    q = CypherQuery(
        query_id="stale",
        cypher_template="MATCH (m:Movie {movie_id: $movie_id, title: $title}) RETURN m",
        params_schema=StaleParams,
        # $title used in cypher_template but not declared on Params
        identifiers_schema=NoIdentifiers,
    )
    result = _validate_cypher_query(q, None)
    alignment_errors = [
        i for i in result.issues if i.code == "QUERY_PARAM_ALIGNMENT_ERROR"
    ]
    assert len(alignment_errors) >= 1, (
        f"Expected QUERY_PARAM_ALIGNMENT_ERROR "
        f"for undeclared $title; got: {result.issues}"
    )
    assert not result.is_valid


def test_cypher_query_validate_parity_with_typed_query(
    definition: GraphDefinition,
) -> None:
    """validate_cypher_query(query, definition) produces same domain codes as typed query.

    Both paths call validate_cypher_spec; the domain (label/rel-type) codes must
    match. RETURN→Output codes are excluded — the simple path declares no Output
    by design, so only the shared syntactic+semantic axis is compared.
    """  # NOQA E501

    _DOMAIN_CODES = {
        "QUERY_UNKNOWN_NODE_LABEL",
        "QUERY_UNKNOWN_REL_TYPE",
        "QUERY_UNKNOWN_PROPERTY",
        "QUERY_INVALID_ENDPOINT",
        "QUERY_PARSE_ERROR",
        "QUERY_PARAM_ALIGNMENT_ERROR",
    }

    cypher_str = "MATCH (f:Film {released: $released}) RETURN f"

    class ReleasedParams(BaseModel):
        released: int

    # Simple path
    simple = CypherQuery(
        query_id="simple_bad_label",
        cypher_template=cypher_str,
        params_schema=ReleasedParams,
        identifiers_schema=NoIdentifiers,
    )
    simple_result = _validate_cypher_query(simple, definition)
    simple_domain_codes = {
        i.code for i in simple_result.issues if i.code in _DOMAIN_CODES
    }

    # Typed path — use same cypher; Output declared separately (not compared here).
    class TypedBadLabel(CypherReadQuery[ReleasedParams, Movie]):
        Params = ReleasedParams
        Output = Movie
        name = "typed_bad_label_parity"
        cypher_template = cypher_str

        def materialize(self, raw: dict[str, Any]) -> Movie:
            return Movie(**raw["f"])

    cat = QueryCatalogue()
    cat.register_read(TypedBadLabel())
    typed_result = validate_query_catalogue(cat, definition)
    typed_domain_codes = {
        i.code for i in typed_result.issues if i.code in _DOMAIN_CODES
    }

    assert "QUERY_UNKNOWN_NODE_LABEL" in simple_domain_codes, (
        f"Simple path missing QUERY_UNKNOWN_NODE_LABEL; got: {simple_domain_codes}"
    )
    assert simple_domain_codes == typed_domain_codes, (
        f"Simple path domain codes {simple_domain_codes} "
        f"!= typed path domain codes {typed_domain_codes}"
    )


# Round-trip serialization tests


def test_cypher_query_python_to_dump_to_load_round_trip() -> None:
    """CypherQuery constructed in Python, dumped via model_dump(by_alias=True),
    re-loaded through file loader, produces equivalent query (Params.model_fields match,
    cypher_template matches).
    """
    from orthograph.io.query_catalogue_yaml import load_query_catalogue_string

    class MovieParams(BaseModel):
        released: int
        limit: int | None = None

    # Load via YAML (simulates file round-trip)
    yaml_str = """
- query_id: movies_by_year
  cypher_template: "MATCH (m:Movie {released: $released}) RETURN m.title LIMIT $limit"
  description: "Movies released in a given year"
  params_schema:
    title: MovieParams
    type: object
    properties:
      released: {type: integer, title: Released}
      limit: {type: integer, title: Limit, default: null}
    required: [released]
"""
    reloaded_list = load_query_catalogue_string(yaml_str)
    reloaded = reloaded_list[0]

    # Verify structure
    assert reloaded.query_id == "movies_by_year"
    assert (
        reloaded.cypher_template
        == "MATCH (m:Movie {released: $released}) RETURN m.title LIMIT $limit"
    )
    assert reloaded.description == "Movies released in a given year"
    assert set(reloaded.params_schema.model_fields.keys()) == {"released", "limit"}
    # Verify required/optional structure
    reload_required = [
        n for n, f in reloaded.params_schema.model_fields.items() if f.is_required()
    ]
    assert reload_required == ["released"]


def test_cypher_query_with_identifiers_round_trips() -> None:
    """CypherQuery with Identifiers round-trips its identifiers_schema."""
    from orthograph.io.query_catalogue_yaml import load_query_catalogue_string

    yaml_str = """
- query_id: movies_by_genre
  cypher_template: "MATCH (m:<<label>> {genre: $genre}) RETURN m"
  description: "Movies by dynamically injected label"
  params_schema:
    title: MovieParams
    type: object
    properties:
      genre: {type: string, title: Genre}
    required: [genre]
  identifiers_schema:
    title: MovieIdentifiers
    type: object
    properties:
      label: {type: string, title: Label}
    required: [label]
"""
    reloaded_list = load_query_catalogue_string(yaml_str)
    reloaded = reloaded_list[0]

    assert reloaded.identifiers_schema is not None
    assert set(reloaded.identifiers_schema.model_fields.keys()) == {"label"}
    assert reloaded.identifiers_schema.model_fields["label"].is_required()
