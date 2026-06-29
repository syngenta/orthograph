"""Run typed read/write queries against a backend.

Four direction-named verbs for the **typed path**, each stating its result shape:

* ``run_read``       — execute a typed read query (sync); returns ``list[Output]``.
* ``run_write``      — execute a typed write query (sync); returns the interpreted
  result.
* ``run_read_async`` — async: execute a typed read query; returns ``list[Output]``.
* ``run_write_async`` — async: execute a typed write query; returns the interpreted
  result.

Four verbs for the **simple path** (``CypherQuery`` — Cypher-only, no backend name):

* ``run_cypher_fetch``         — execute a ``CypherQuery`` RETURN (sync); returns
  ``list[dict[str, Any]]``.
* ``run_cypher_execute``       — execute a ``CypherQuery`` mutation (sync); returns
  ``CypherWriteResultSummary``.
* ``run_cypher_fetch_async``   — async variant of ``run_cypher_fetch``.
* ``run_cypher_execute_async`` — async variant of ``run_cypher_execute``.

Both sets of verbs receive a **connection factory**: a callable returning a session
context manager (NOT a driver). Orthograph opens and closes every connection per call
and stores nothing. Neither verb commits or rolls back — the caller owns the transaction
boundary (ADR-028).

The simple-path verbs take **no backend name**: ``CypherQuery`` is Cypher-only.

``ReadQueryModel``/``WriteQueryModel`` and ``AsyncExecutor``/``AsyncReadPort``/
``AsyncQueryBackedReadPort`` are re-exported here so consumers can type their
query subclasses and async ports without reaching into ``orthograph.query.*``.
"""  # NOQA E501

from typing import Any, Callable

from orthograph.backends import loader
from orthograph.cypher.query import CypherQuery
from orthograph.cypher.query_execution import (
    AsyncCypherQueryExecutor,
    CypherExecutor,
    CypherQueryExecutor,
    CypherWriteResultSummary,
)
from orthograph.query.base_models import (
    AsyncExecutor,
    AsyncQueryBackedReadPort,
    AsyncReadPort,
    Backend,
    D,
    P,
    QueryBackedReadPort,
    R,
    ReadPort,
    ReadQueryModel,
    WriteQueryModel,
)


__all__ = [
    "ReadQueryModel",
    "WriteQueryModel",
    "run_read",
    "run_write",
    "run_read_async",
    "run_write_async",
    "run_cypher_fetch",
    "run_cypher_execute",
    "run_cypher_fetch_async",
    "run_cypher_execute_async",
    "CypherExecutor",
    "CypherQueryExecutor",
    "AsyncCypherQueryExecutor",
    "CypherWriteResultSummary",
    "ReadPort",
    "QueryBackedReadPort",
    "AsyncExecutor",
    "AsyncReadPort",
    "AsyncQueryBackedReadPort",
    "Backend",
]


def run_read(
    backend: str,
    connection_factory: Callable[[], Any],
    read_query: ReadQueryModel[P, D],
    params: Any,
) -> list[D]:
    """Execute a typed read query against ``backend``; return ``list[Output]``.

    Operand: a typed read query. ``connection_factory`` is a callable returning
    a session context manager, opened and closed per call.
    """
    executor_cls = loader.load_executor(name=backend)
    return executor_cls(connection_factory).read(query=read_query, raw_params=params)


def run_write(
    backend: str,
    connection_factory: Callable[[], Any],
    write_query: WriteQueryModel[P, R],
    params: Any,
) -> R:
    """Execute a typed write query against ``backend``; return the result.

    Operand: a typed write query. ``connection_factory`` is a callable returning
    a session context manager, opened and closed per call.
    """
    executor_cls = loader.load_executor(name=backend)
    return executor_cls(connection_factory).write(query=write_query, raw_params=params)


async def run_read_async(
    backend: str,
    connection_factory: Callable[[], Any],
    read_query: ReadQueryModel[P, D],
    params: Any,
) -> list[D]:
    """Async: execute a typed read query against ``backend``; return ``list[Output]``.

    The caller owns the transaction boundary (ADR-028); ``connection_factory``
    yields an async session or a live async transaction.
    """
    executor_cls = loader.load_async_executor(name=backend)
    return await executor_cls(connection_factory).read(
        query=read_query, raw_params=params
    )


async def run_write_async(
    backend: str,
    connection_factory: Callable[[], Any],
    write_query: WriteQueryModel[P, R],
    params: Any,
) -> R:
    """Async: execute a typed write query against ``backend``; return the result.

    Does not commit — the caller owns the transaction boundary (ADR-028).
    """
    executor_cls = loader.load_async_executor(name=backend)
    return await executor_cls(connection_factory).write(
        query=write_query, raw_params=params
    )


def run_cypher_fetch(
    connection_factory: Callable[[], Any],
    query: CypherQuery,
    params: Any,
) -> list[dict[str, Any]]:
    """Execute a simple-path ``CypherQuery`` RETURN; return raw ``list[dict]`` rows.

    ``CypherQuery`` is Cypher-only — no backend name is taken.
    ``connection_factory`` yields a session or live transaction; the caller owns
    the transaction boundary.
    """
    return CypherQueryExecutor(connection_factory).fetch(query, params)


def run_cypher_execute(
    connection_factory: Callable[[], Any],
    query: CypherQuery,
    params: Any,
) -> CypherWriteResultSummary:
    """Execute a simple-path ``CypherQuery`` mutation; return the write summary.

    Does not commit — the caller owns the transaction boundary (ADR-028).
    """
    return CypherQueryExecutor(connection_factory).execute(query, params)


async def run_cypher_fetch_async(
    connection_factory: Callable[[], Any],
    query: CypherQuery,
    params: Any,
) -> list[dict[str, Any]]:
    """Async: execute a simple-path ``CypherQuery`` RETURN;
    return raw ``list[dict]`` rows."""
    return await AsyncCypherQueryExecutor(connection_factory).fetch(query, params)


async def run_cypher_execute_async(
    connection_factory: Callable[[], Any],
    query: CypherQuery,
    params: Any,
) -> CypherWriteResultSummary:
    """Async: execute a simple-path ``CypherQuery`` mutation;
    return the write summary."""
    return await AsyncCypherQueryExecutor(connection_factory).execute(query, params)
