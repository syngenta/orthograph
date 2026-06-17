"""Tests for CypherQuerySpec.

Covers construction, argument listing, building queries, and validation against schemas.

Coverage mapping to noctis test_neo4j_queries.py:
- TestAbstractQuery:
  ✓ Class variables (query_name, etc.) - test_minimal_construction, test_full_construction
  ✓ Model config validation - implicitly validated in all tests
  ✓ validate_query_kwargs - test_build_missing_required_arg_raises, test_build_unknown_arg_raises
  ✓ list_arguments - test_list_arguments_structure, test_list_arguments_empty
  ✓ Instantiation success/failure - test_*_raises tests
  ✓ No required args - test_empty_args_defaults
  ✓ Optional-only args - test_build_partial_optional_args
  ✓ Parameterized queries - test_build_params_model_*
  ✓ Error messages - test_error_message_clear_*

- TestCustomQuery (YAML loading):
  ✓ Query creation - test_minimal_construction, test_full_construction
  ✓ to_dict method - test_to_dict_*
  ✓ Query string access - test_cypher_access_returns_raw_string
  ✓ Query name access - test_name_access_returns_query_name
  ✓ Validation - test_validate_*

Missing in orthograph (by design):
  ✗ Query registry/registration system (not part of CypherQuerySpec)
  ✗ Callable invocation pattern (use build() instead)
  ✗ get_query() method (use .cypher property instead)
  ✗ from_yaml per query (use load_query_catalogue_* for full YAML instead)
"""  # NOQA E501

import pytest
from pydantic import BaseModel

from orthograph.cypher.exceptions import CypherQuerySpecError
from orthograph.cypher.query_spec import CypherQuerySpec
from orthograph.diagnostics.classification import Severity
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel


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


def test_minimal_construction() -> None:
    """Query accepts name, cypher, and required arguments."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    assert q.name == "find_movie"
    assert "movie_id" in q.query_args_required
    assert q.query_args_optional == []
    assert q.Params is None
    assert q.description is None


def test_full_construction() -> None:
    """Query accepts optional parameters model and description."""

    class MyParams(BaseModel):
        movie_id: str
        title: str | None = None

    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
        query_args_optional=["title"],
        Params=MyParams,
        description="Find a movie by its ID.",
    )
    assert q.Params is MyParams
    assert q.description == "Find a movie by its ID."


def test_empty_args_defaults() -> None:
    """Query with no arguments has empty required and optional lists."""
    q = CypherQuerySpec(
        name="count_movies",
        cypher="MATCH (m:Movie) RETURN count(m) AS n",
    )
    assert q.query_args_required == []
    assert q.query_args_optional == []


def test_duplicate_arg_name_raises() -> None:
    """Query raises when argument appears in both required and optional."""
    with pytest.raises(CypherQuerySpecError, match="appear in both"):
        CypherQuerySpec(
            name="bad",
            cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
            query_args_required=["movie_id"],
            query_args_optional=["movie_id"],
        )


def test_params_model_missing_required_field_raises() -> None:
    """Query raises when Params model missing required argument fields."""

    class IncompleteParams(BaseModel):
        title: str

    with pytest.raises(CypherQuerySpecError, match="not declared in Params"):
        CypherQuerySpec(
            name="bad",
            cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
            query_args_required=["movie_id"],
            Params=IncompleteParams,
        )


def test_params_model_missing_optional_field_raises() -> None:
    """Query raises when Params model missing optional argument fields."""

    class IncompleteParams(BaseModel):
        movie_id: str

    with pytest.raises(CypherQuerySpecError, match="not declared in Params"):
        CypherQuerySpec(
            name="bad",
            cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
            query_args_required=["movie_id"],
            query_args_optional=["title"],
            Params=IncompleteParams,
        )


def test_list_arguments_structure() -> None:
    """list_arguments returns dict with required and optional keys."""
    q = CypherQuerySpec(
        name="q",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
        query_args_optional=["title"],
    )
    result = q.list_arguments()
    assert result == {"required": ["movie_id"], "optional": ["title"]}


def test_list_arguments_empty() -> None:
    """list_arguments returns empty lists when no arguments."""
    q = CypherQuerySpec(name="q", cypher="MATCH (m:Movie) RETURN m")
    assert q.list_arguments() == {"required": [], "optional": []}


def test_build_returns_cypher_and_params() -> None:
    """build returns tuple of cypher string and parameter dict."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    cypher, params = q.build(movie_id="M-001")
    assert cypher == "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
    assert params == {"movie_id": "M-001"}


def test_build_optional_arg_included_when_provided() -> None:
    """build includes optional arguments when supplied."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
        query_args_optional=["title"],
    )
    cypher, params = q.build(movie_id="M-001", title="Inception")
    assert params == {"movie_id": "M-001", "title": "Inception"}


def test_build_optional_arg_omitted_not_in_params() -> None:
    """build excludes optional arguments when not supplied."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
        query_args_optional=["title"],
    )
    _, params = q.build(movie_id="M-001")
    assert "title" not in params


def test_build_missing_required_arg_raises() -> None:
    """build raises when required argument missing."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    with pytest.raises(CypherQuerySpecError, match="Missing required"):
        q.build()


def test_build_unknown_arg_raises() -> None:
    """build raises when unknown argument supplied."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    with pytest.raises(CypherQuerySpecError, match="Unknown argument"):
        q.build(movie_id="M-001", typo_arg="x")


def test_build_no_args_query_builds_with_empty_params() -> None:
    """build returns empty params dict for query with no arguments."""
    q = CypherQuerySpec(
        name="count_movies",
        cypher="MATCH (m:Movie) RETURN count(m) AS n",
    )
    cypher, params = q.build()
    assert params == {}


def test_build_params_model_validates_types() -> None:
    """build validates argument types through Params model when declared."""

    class MovieParams(BaseModel):
        movie_id: str
        limit: int = 10

    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m LIMIT $limit",
        query_args_required=["movie_id"],
        query_args_optional=["limit"],
        Params=MovieParams,
    )
    _, params = q.build(movie_id="M-001", limit=5)
    assert params["limit"] == 5


def test_build_params_model_coerces_compatible_types() -> None:
    """build coerces compatible types through Pydantic."""

    class MovieParams(BaseModel):
        limit: int = 10

    q = CypherQuerySpec(
        name="q",
        cypher="MATCH (m:Movie) RETURN m LIMIT $limit",
        query_args_optional=["limit"],
        Params=MovieParams,
    )
    _, params = q.build(limit="5")
    assert params["limit"] == 5


def test_build_params_model_rejects_incompatible_type() -> None:
    """build raises ValidationError for incompatible types in Params model."""
    from pydantic import ValidationError

    class MovieParams(BaseModel):
        limit: int

    q = CypherQuerySpec(
        name="q",
        cypher="MATCH (m:Movie) RETURN m LIMIT $limit",
        query_args_required=["limit"],
        Params=MovieParams,
    )
    with pytest.raises(ValidationError):
        q.build(limit="not_an_int")


def test_validate_valid_query_returns_no_errors(definition: GraphDefinition) -> None:
    """validate returns no errors for valid query."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    result = q.validate_query(definition)
    errors = [i for i in result.issues if i.severity == Severity.ERROR]
    assert errors == []


def test_validate_unknown_label_surfaces_as_error(definition: GraphDefinition) -> None:
    """validate reports unknown node label as error."""
    q = CypherQuerySpec(
        name="bad_label",
        cypher="MATCH (m:UnknownLabel {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    result = q.validate_query(definition)
    codes = {i.code for i in result.issues if i.severity == Severity.ERROR}
    assert "QUERY_UNKNOWN_NODE_LABEL" in codes


def test_validate_unknown_rel_type_surfaces_as_error(
    definition: GraphDefinition,
) -> None:
    """validate reports unknown relationship type as error."""
    q = CypherQuerySpec(
        name="bad_rel",
        cypher="MATCH (f:Festival)-[:UNKNOWN_REL]->(m:Movie) RETURN m",
        query_args_required=[],
    )
    result = q.validate_query(definition)
    codes = {i.code for i in result.issues if i.severity == Severity.ERROR}
    assert "QUERY_UNKNOWN_REL_TYPE" in codes


def test_validate_without_definition_returns_empty_result() -> None:
    """validate with no definition returns empty result (syntax-only check)."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    result = q.validate_query(None)
    assert result.is_valid


def test_validate_syntax_error_surfaces_regardless_of_definition(
    definition: GraphDefinition,
) -> None:
    """validate reports parse errors even with domain validation."""
    q = CypherQuerySpec(
        name="bad_syntax",
        cypher="THIS IS NOT CYPHER",
        query_args_required=[],
    )
    result = q.validate_query(definition)
    non_info = [i for i in result.issues if i.severity != Severity.INFO]
    assert non_info


def test_validate_valid_rel_type_no_errors(definition: GraphDefinition) -> None:
    """validate accepts valid relationship types in schema."""
    q = CypherQuerySpec(
        name="movies_by_festival",
        cypher="MATCH (f:Festival)-[:HAS_MOVIE]->(m:Movie) RETURN m",
    )
    result = q.validate_query(definition)
    errors = [i for i in result.issues if i.severity == Severity.ERROR]
    assert errors == []


def test_to_dict_preserves_format() -> None:
    """model_dump with by_alias=True returns dict with legacy field names for YAML."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
        query_args_optional=["title"],
        description="Find a movie by ID.",
    )
    d = q.model_dump(by_alias=True, exclude_none=True)
    assert d["query_name"] == "find_movie"
    assert d["query"] == "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
    assert d["query_args_required"] == ["movie_id"]
    assert d["query_args_optional"] == ["title"]
    assert d["description"] == "Find a movie by ID."


def test_to_dict_omits_none_description() -> None:
    """model_dump with exclude_none=True excludes description field when not set."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    d = q.model_dump(by_alias=True, exclude_none=True)
    assert "description" not in d


def test_to_dict_includes_all_fields() -> None:
    """model_dump returns all query metadata with proper field names."""
    q = CypherQuerySpec(
        name="test_query",
        cypher="MATCH (m:Movie) RETURN m",
        query_args_required=["arg1", "arg2"],
        query_args_optional=["arg3"],
        description="Test query description.",
    )
    d = q.model_dump(by_alias=True, exclude_none=True)
    assert set(d.keys()) == {
        "query_name",
        "query",
        "query_args_required",
        "query_args_optional",
        "description",
    }


def test_repr_shows_query_structure() -> None:
    """__repr__ returns string representation with name and arguments."""
    q = CypherQuerySpec(
        name="my_query",
        cypher="MATCH (m:Movie) RETURN m",
        query_args_required=["arg1"],
        query_args_optional=["arg2"],
    )
    repr_str = repr(q)
    assert "my_query" in repr_str
    assert "required" in repr_str
    assert "optional" in repr_str


def test_build_with_multiple_required_args() -> None:
    """build accepts multiple required arguments."""
    q = CypherQuerySpec(
        name="find_relationship",
        cypher="MATCH (f:Festival)-[:HAS_MOVIE]->(m:Movie) "
        "WHERE f.id = $festival_id "
        "AND m.movie_id = $movie_id RETURN f, m",  # NOQA E501
        query_args_required=["festival_id", "movie_id"],
    )
    cypher, params = q.build(festival_id="F-001", movie_id="M-001")
    assert params == {"festival_id": "F-001", "movie_id": "M-001"}
    assert cypher == q.cypher


def test_build_with_multiple_optional_args() -> None:
    """build accepts multiple optional arguments."""
    q = CypherQuerySpec(
        name="search_movies",
        cypher="MATCH (m:Movie) RETURN m LIMIT $limit SKIP $offset",
        query_args_optional=["limit", "offset"],
    )
    cypher, params = q.build(limit=10, offset=5)
    assert params == {"limit": 10, "offset": 5}


def test_build_partial_optional_args() -> None:
    """build accepts subset of optional arguments."""
    q = CypherQuerySpec(
        name="search_movies",
        cypher="MATCH (m:Movie) RETURN m",
        query_args_optional=["limit", "offset", "sort"],
    )
    cypher, params = q.build(limit=10)
    assert params == {"limit": 10}
    assert "offset" not in params
    assert "sort" not in params


def test_validate_returns_validation_result() -> None:
    """validate returns ValidationResult object."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie) RETURN m",
    )
    result = q.validate_query(None)
    assert hasattr(result, "is_valid")
    assert hasattr(result, "issues")
    assert result.is_valid is True


def test_params_model_with_defaults() -> None:
    """build with Params model applies default values when args omitted."""

    class MovieParams(BaseModel):
        movie_id: str
        limit: int = 100

    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie) RETURN m LIMIT $limit",
        query_args_required=["movie_id"],
        query_args_optional=["limit"],
        Params=MovieParams,
    )
    _, params = q.build(movie_id="M-001")
    assert params["movie_id"] == "M-001"
    assert "limit" not in params  # Default not included if not supplied


def test_cypher_access_returns_raw_string() -> None:
    """Query cypher attribute returns the raw unmodified cypher string."""
    cypher_str = "MATCH (m:Movie) WHERE m.title = $title RETURN m"
    q = CypherQuerySpec(
        name="find_by_title",
        cypher=cypher_str,
        query_args_required=["title"],
    )
    assert q.cypher == cypher_str


def test_name_access_returns_query_name() -> None:
    """Query name attribute returns the query identifier."""
    q = CypherQuerySpec(
        name="my_query_name",
        cypher="MATCH (m:Movie) RETURN m",
    )
    assert q.name == "my_query_name"


def test_build_returns_tuple() -> None:
    """build return value is always a tuple of two elements."""
    q = CypherQuerySpec(
        name="test",
        cypher="MATCH (m:Movie) RETURN m",
    )
    result = q.build()
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_build_first_element_is_cypher_string() -> None:
    """build tuple first element is the cypher string unchanged."""
    cypher_str = "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
    q = CypherQuerySpec(
        name="test",
        cypher=cypher_str,
        query_args_required=["movie_id"],
    )
    result_cypher, _ = q.build(movie_id="M-001")
    assert result_cypher == cypher_str


def test_build_second_element_is_params_dict() -> None:
    """build tuple second element is dict of parameters."""
    q = CypherQuerySpec(
        name="test",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    _, params = q.build(movie_id="M-001")
    assert isinstance(params, dict)
    assert params == {"movie_id": "M-001"}


def test_error_message_clear_for_missing_required_args() -> None:
    """Error message for missing args clearly states which args are missing."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id, title: $title}) RETURN m",
        query_args_required=["movie_id", "title"],
    )
    with pytest.raises(CypherQuerySpecError) as exc_info:
        q.build(movie_id="M-001")
    error_msg = str(exc_info.value)
    assert "title" in error_msg
    assert "Missing required" in error_msg


def test_error_message_clear_for_unknown_args() -> None:
    """Error message for unknown args clearly states which args are invalid."""
    q = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    with pytest.raises(CypherQuerySpecError) as exc_info:
        q.build(movie_id="M-001", invalid_arg="x")
    error_msg = str(exc_info.value)
    assert "invalid_arg" in error_msg
    assert "Unknown" in error_msg


def test_multiple_queries_independent() -> None:
    """Multiple query instances are independent."""
    q1 = CypherQuerySpec(
        name="query1",
        cypher="MATCH (m:Movie) RETURN m",
        query_args_required=["arg1"],
    )
    q2 = CypherQuerySpec(
        name="query2",
        cypher="MATCH (f:Festival) RETURN f",
        query_args_required=["arg2"],
    )
    assert q1.name != q2.name
    assert q1.cypher != q2.cypher
    assert q1.query_args_required != q2.query_args_required


def test_empty_query_args_lists() -> None:
    """Query with empty argument lists is valid."""
    q = CypherQuerySpec(
        name="all_movies",
        cypher="MATCH (m:Movie) RETURN m",
        query_args_required=[],
        query_args_optional=[],
    )
    assert q.query_args_required == []
    assert q.query_args_optional == []
    cypher, params = q.build()
    assert params == {}


def test_description_is_optional() -> None:
    """Query can be created without description."""
    q = CypherQuerySpec(
        name="test",
        cypher="MATCH (m:Movie) RETURN m",
    )
    assert q.description is None


def test_description_stored_when_provided() -> None:
    """Query stores description when provided."""
    desc = "This is a test query"
    q = CypherQuerySpec(
        name="test",
        cypher="MATCH (m:Movie) RETURN m",
        description=desc,
    )
    assert q.description == desc


def test_params_model_is_optional() -> None:
    """Query can be created without Params model."""
    q = CypherQuerySpec(
        name="test",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    assert q.Params is None


def test_all_attributes_accessible() -> None:
    """Query attributes are all accessible after construction."""
    q = CypherQuerySpec(
        name="test_query",
        cypher="MATCH (m:Movie) RETURN m",
        query_args_required=["arg1"],
        query_args_optional=["arg2"],
        description="Test",
    )
    assert hasattr(q, "name")
    assert hasattr(q, "cypher")
    assert hasattr(q, "query_args_required")
    assert hasattr(q, "query_args_optional")
    assert hasattr(q, "description")
    assert hasattr(q, "Params")


def test_validate_with_complex_cypher() -> None:
    """validate handles complex multi-clause cypher queries."""
    q = CypherQuerySpec(
        name="complex",
        cypher="""
            MATCH (f:Festival)-[:HAS_MOVIE]->(m:Movie)
            WHERE f.id = $festival_id
            WITH m, f
            OPTIONAL MATCH (m)-[:REVIEWED_BY]->(c:Critic)
            RETURN m, f, c
        """,
        query_args_required=["festival_id"],
    )
    result = q.validate_query(None)
    assert result.is_valid


def test_build_with_complex_parameters() -> None:
    """build handles various parameter types through Params model."""

    class ComplexParams(BaseModel):
        movie_id: str
        year: int
        rating: float
        is_available: bool

    q = CypherQuerySpec(
        name="complex_query",
        cypher="MATCH (m:Movie) RETURN m",
        query_args_required=["movie_id", "year", "rating", "is_available"],
        Params=ComplexParams,
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
