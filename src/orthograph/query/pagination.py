"""Pagination support for typed read queries.

Provides a mixin base class for Params models that support skip/limit pagination.
"""

from pydantic import BaseModel, Field


class PaginatedParams(BaseModel):
    """Mixin for read query params that support skip/limit pagination.

    Use this as a base class for your Params model to add pagination fields:

        class MoviesByYearParams(PaginatedParams):
            released: int

    Import directly from this module:

        from orthograph.query.pagination import PaginatedParams
    """

    skip: int = Field(default=0, ge=0, description="Number of records to skip")
    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum records to return (1-1000)",
    )
