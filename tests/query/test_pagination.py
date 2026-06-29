"""Tests for PaginatedParams mixin.

PaginatedParams provides reusable skip/limit pagination fields
that compose into Params models without breaking __init_subclass__ enforcement.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from orthograph.query.base_models import Backend, ReadQueryModel
from orthograph.query.catalogue import QueryCatalogue
from orthograph.query.pagination import PaginatedParams


class MovieOutput:
    """Dummy output for testing (not a BaseModel, just for test structure)."""

    pass


def test_paginated_params_has_skip_field() -> None:
    """PaginatedParams has a skip field with ge=0 constraint."""
    from pydantic import BaseModel

    class Output(BaseModel):
        title: str

    # Should construct with default skip=0
    params = PaginatedParams()
    assert params.skip == 0

    # Should allow positive skip values
    params = PaginatedParams(skip=10)
    assert params.skip == 10

    # Should reject negative skip
    with pytest.raises(ValidationError):
        PaginatedParams(skip=-1)


def test_paginated_params_has_limit_field() -> None:
    """PaginatedParams has a limit field with ge=1, le=1000 constraints."""
    # Default limit should be 100
    params = PaginatedParams()
    assert params.limit == 100

    # Should allow values in range [1, 1000]
    params = PaginatedParams(limit=500)
    assert params.limit == 500

    # Should reject limit < 1
    with pytest.raises(ValidationError):
        PaginatedParams(limit=0)

    # Should reject limit > 1000
    with pytest.raises(ValidationError):
        PaginatedParams(limit=1001)

    # Should accept boundary values
    params = PaginatedParams(limit=1)
    assert params.limit == 1

    params = PaginatedParams(limit=1000)
    assert params.limit == 1000


def test_paginated_params_composes_into_query_params() -> None:
    """PaginatedParams-based Params models work with __init_subclass__."""
    from pydantic import BaseModel

    class MovieOutput(BaseModel):
        title: str
        released: int

    class MoviesByYearParams(PaginatedParams):
        """Params that adds domain-specific field to pagination fields."""

        released: int

    # Should construct with inherited pagination fields
    params = MoviesByYearParams(released=2020)
    assert params.released == 2020
    assert params.skip == 0  # default
    assert params.limit == 100  # default

    # Should allow all fields to be set
    params = MoviesByYearParams(released=2020, skip=5, limit=50)
    assert params.released == 2020
    assert params.skip == 5
    assert params.limit == 50


def test_paginated_params_in_read_query_without_errors() -> None:
    """A ReadQueryModel can use a Params model that inherits from PaginatedParams.

    This test confirms __init_subclass__ enforcement still works correctly
    when Params inherits from PaginatedParams.
    """
    from pydantic import BaseModel

    class MovieOutput(BaseModel):
        title: str
        released: int

    class MoviesByYearParams(PaginatedParams):
        released: int

    # Should not raise TypeError during class definition
    class GetMoviesByYear(ReadQueryModel[MoviesByYearParams, MovieOutput]):
        query_id = "movies_by_year"
        backend = Backend.CYPHER

        def build(self, params: MoviesByYearParams) -> tuple[str, dict[str, Any]]:
            return (
                "MATCH (m:Movie {released: $released}) "
                "RETURN m SKIP $skip LIMIT $limit",
                {
                    "released": params.released,
                    "skip": params.skip,
                    "limit": params.limit,
                },
            )

        def materialize(self, raw: dict[str, Any]) -> MovieOutput:
            return MovieOutput(**raw)

    # Should be able to instantiate and use the query
    query = GetMoviesByYear()
    params = MoviesByYearParams(released=2020, skip=10, limit=25)
    # build() is pure, so we can call it directly
    cypher_str, cypher_params = query.build(params)
    assert cypher_str is not None
    assert cypher_params["released"] == 2020
    assert cypher_params["skip"] == 10
    assert cypher_params["limit"] == 25


def test_paginated_params_appears_in_query_description() -> None:
    """PaginatedParams fields appear in params_schema from QueryCatalogue.describe()."""
    from pydantic import BaseModel

    class MovieOutput(BaseModel):
        title: str
        released: int

    class MoviesByYearParams(PaginatedParams):
        released: int

    class GetMoviesByYear(ReadQueryModel[MoviesByYearParams, MovieOutput]):
        query_id = "movies_by_year"
        backend = Backend.CYPHER

        def build(self, params: MoviesByYearParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (m:Movie) RETURN m", {})

        def materialize(self, raw: dict[str, Any]) -> MovieOutput:
            return MovieOutput(**raw)

    cat = QueryCatalogue()
    cat.register_read(GetMoviesByYear())
    descriptions = cat.describe()
    # Find the query description for our query
    desc = next((d for d in descriptions if d.query_id == "movies_by_year"), None)
    assert desc is not None

    # params_schema should be the JSON schema of MoviesByYearParams
    params_schema = desc.params_schema
    assert params_schema is not None
    assert "properties" in params_schema

    # Should have all three fields: released, skip, limit
    props = params_schema["properties"]
    assert "released" in props
    assert "skip" in props
    assert "limit" in props

    # skip and limit should come from PaginatedParams
    assert props["skip"]["type"] == "integer"
    assert props["skip"]["default"] == 0
    assert props["skip"]["minimum"] == 0  # ge=0 becomes minimum: 0

    assert props["limit"]["type"] == "integer"
    assert props["limit"]["default"] == 100
    assert props["limit"]["minimum"] == 1  # ge=1
    assert props["limit"]["maximum"] == 1000  # le=1000
