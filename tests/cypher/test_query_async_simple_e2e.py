"""Async e2e tests for AsyncCypherQueryExecutor against a live Neo4j DB.

Restores the simple-path async coverage removed by E39.9, now on the dedicated
execution surface introduced by E62 / ADR-047.

These tests use the **simple path** — ``CypherQuery`` (no Output model, no
read/write distinction). ``AsyncCypherQueryExecutor`` is typed concretely on
``CypherQuery``; no ``# type: ignore`` is needed.

Requires --neo4j flag:
    pytest --neo4j --neo4j-password <pw> tests/cypher/test_query_async_simple_e2e.py
"""

from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.cypher.bindings import NoIdentifiers
from orthograph.cypher.query import CypherQuery
from orthograph.cypher.query_execution import (
    AsyncCypherQueryExecutor,
    CypherWriteResultSummary,
)


# ---------------------------------------------------------------------------
# Simple-path domain models
# ---------------------------------------------------------------------------


class NoParams(BaseModel): ...


class CreateMovieParams(BaseModel):
    title: str
    released: int


FIND_ALL = CypherQuery(
    query_id="async_simple_find_all_movies",
    cypher_template=(
        "MATCH (m:Movie) RETURN m.title AS title, "
        "m.released AS released ORDER BY m.title"
    ),
    params_schema=NoParams,
    identifiers_schema=NoIdentifiers,
)

CREATE = CypherQuery(
    query_id="async_simple_create_movie",
    cypher_template="CREATE (m:Movie {title: $title, released: $released})",
    params_schema=CreateMovieParams,
    identifiers_schema=NoIdentifiers,
)


# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------


async def _seed(driver: Any) -> None:
    """Seed two Movie nodes via an async session."""
    async with driver.session() as session:
        await session.run(
            "MERGE (m1:Movie {title: 'The Matrix', released: 1999})"
            " MERGE (m2:Movie {title: 'Speed', released: 1994})"
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
async def test_async_simple_fetch_returns_raw_dicts(
    async_neo4j_driver: Any, async_neo4j_clean: None
) -> None:
    """Simple path: await executor.fetch() returns list[dict[str, Any]].

    AsyncCypherQueryExecutor is typed concretely on CypherQuery; fetch() resolves
    to list[dict[str, Any]] with no cast or suppression.
    """
    await _seed(async_neo4j_driver)

    executor = AsyncCypherQueryExecutor(async_neo4j_driver.session)
    results: list[dict[str, Any]] = await executor.fetch(FIND_ALL, {})

    assert {r["title"] for r in results} == {"The Matrix", "Speed"}
    assert all(isinstance(r, dict) for r in results)


@pytest.mark.neo4j
async def test_async_simple_execute_returns_summary(
    async_neo4j_driver: Any, async_neo4j_clean: None
) -> None:
    """Simple path: await executor.execute() returns CypherWriteResultSummary.

    Does not commit — the async session is opened via the factory and the
    caller owns the transaction boundary (ADR-028).
    """
    executor = AsyncCypherQueryExecutor(async_neo4j_driver.session)
    result: CypherWriteResultSummary = await executor.execute(
        CREATE, {"title": "Inception", "released": 2010}
    )

    assert isinstance(result, CypherWriteResultSummary)
    assert result.nodes_created == 1
