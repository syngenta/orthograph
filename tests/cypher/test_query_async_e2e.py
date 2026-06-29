"""Async e2e tests for AsyncCypherExecutor against a live Neo4j DB.

Focus: prove asyncronicity only — that the async path awaits correctly and that
the executor never commits (caller owns the transaction boundary, ADR-028).
Bulk behaviour (param validation, bad Cypher, etc.) is already covered by the
sync unit tests in tests/cypher/test_query_execution.py.

These tests use the **typed path** — ``TypedCypherReadQueryModel`` /
``TypedCypherWriteQueryModel``. These inherit from ``ReadQueryModel[P, D]`` /
``WriteQueryModel[P, R]`` so the executor signatures resolve without casts:
``read()`` returns ``list[D]``, ``write()`` returns ``R``.

The simple path (``CypherQuery``) gets its own dedicated execution surface and
async coverage under E62 / ADR-047; it is intentionally not exercised here.

Requires --neo4j flag:
    pytest --neo4j --neo4j-password <pw> tests/cypher/test_query_async_e2e.py
"""

from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.cypher.base_models import (
    TypedCypherReadQueryModel,
    TypedCypherWriteQueryModel,
)
from orthograph.cypher.query_execution import AsyncCypherExecutor


# ---------------------------------------------------------------------------
# Typed-path domain models (read)
# ---------------------------------------------------------------------------


class MovieParams(BaseModel):
    pass


class MovieRow(BaseModel):
    title: str
    released: int | None = None


class FindAllMovies(TypedCypherReadQueryModel[MovieParams, MovieRow]):
    query_id = "async_typed_find_all_movies"
    cypher_template = (
        "MATCH (m:Movie) RETURN m.title AS title, "
        "m.released AS released ORDER BY m.title"
    )

    def materialize(self, raw: Any) -> MovieRow:
        return MovieRow.model_validate(raw)


# ---------------------------------------------------------------------------
# Typed-path domain models (write)
# ---------------------------------------------------------------------------


class CreateMovieParams(BaseModel):
    title: str
    released: int


class CreateMovie(TypedCypherWriteQueryModel[CreateMovieParams, int]):
    query_id = "async_typed_create_movie"
    cypher_template = "CREATE (m:Movie {title: $title, released: $released})"

    def interpret_result(self, raw: Any) -> int:
        return int(raw.nodes_created)


# ---------------------------------------------------------------------------
# Async seed helper
# ---------------------------------------------------------------------------


async def _seed(driver: Any) -> None:
    """Seed two Movie nodes via an async session."""
    async with driver.session() as session:
        await session.run(
            "MERGE (m1:Movie {title: 'The Matrix', released: 1999})"
            " MERGE (m2:Movie {title: 'Speed', released: 1994})"
        )


# ---------------------------------------------------------------------------
# Typed-path tests (ReadQueryModel[P, D] / WriteQueryModel[P, R])
# These carry full static types — no cast required.
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
async def test_async_typed_read_materialises_records(
    async_neo4j_driver: Any, async_neo4j_clean: None
) -> None:
    """Typed path: await executor.read() returns list[MovieRow] — fully typed.

    TypedCypherReadQueryModel[MovieParams, MovieRow] is a genuine
    ReadQueryModel[MovieParams, MovieRow], so executor.read() resolves D=MovieRow
    and the return type is list[MovieRow] with no cast.
    """
    await _seed(async_neo4j_driver)

    executor = AsyncCypherExecutor(async_neo4j_driver.session)
    query = FindAllMovies()
    results: list[MovieRow] = await executor.read(query, {})

    assert len(results) == 2
    titles = {r.title for r in results}
    assert titles == {"The Matrix", "Speed"}
    assert all(isinstance(r, MovieRow) for r in results)


@pytest.mark.neo4j
async def test_async_typed_write_returns_interpreted_result(
    async_neo4j_driver: Any, async_neo4j_clean: None
) -> None:
    """Typed path: await executor.write() returns int — fully typed.

    TypedCypherWriteQueryModel[CreateMovieParams, int] is a genuine
    WriteQueryModel[CreateMovieParams, int], so executor.write() resolves R=int
    and the return type is int with no cast.
    """
    executor = AsyncCypherExecutor(async_neo4j_driver.session)
    query = CreateMovie()
    result: int = await executor.write(query, {"title": "Inception", "released": 2010})

    assert result == 1


@pytest.mark.neo4j
async def test_async_typed_write_does_not_auto_commit(
    async_neo4j_driver: Any, async_neo4j_clean: None
) -> None:
    """Typed path: executor runs the statement but does NOT commit — caller owns tx (ADR-028).

    Protocol:
    1. Open an explicit AsyncTransaction via begin_transaction().
    2. Wrap it in a no-exit async CM factory so the executor's async with does
       not close/commit the transaction on exit.
    3. Write a node via the executor.
    4. Before committing, read in a *separate* session — node NOT yet visible.
    5. Commit the transaction explicitly.
    6. Read again in a separate session — node IS now visible.
    """  # NOQA E501
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _tx_factory():
        """Yield the live tx without closing it on exit — caller commits explicitly."""
        yield tx

    query = CreateMovie()

    async with async_neo4j_driver.session() as tx_session:
        tx = await tx_session.begin_transaction()
        try:
            executor = AsyncCypherExecutor(_tx_factory)
            await executor.write(query, {"title": "Interstellar", "released": 2014})

            # Before commit: node must NOT be visible in a separate session.
            async with async_neo4j_driver.session() as check_session:
                check_result = await check_session.run(
                    "MATCH (m:Movie {title: 'Interstellar'}) RETURN m.title AS title"
                )
                rows = [rec async for rec in check_result]
            assert rows == [], (
                "Node was visible before commit — executor auto-committed"
            )

            # Caller commits explicitly.
            await tx.commit()
        except Exception:
            if not tx.closed():
                await tx.rollback()
            raise

    # After commit: node MUST be visible.
    async with async_neo4j_driver.session() as verify_session:
        verify_result = await verify_session.run(
            "MATCH (m:Movie {title: 'Interstellar'}) RETURN m.title AS title"
        )
        rows = [rec async for rec in verify_result]
    assert len(rows) == 1, "Node not visible after explicit commit"
