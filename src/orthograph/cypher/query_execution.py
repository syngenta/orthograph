"""Concrete Executor — the single graph-driver I/O seam.

Opens a session per call, validates params, calls ``build()``, parses the
produced Cypher (catches imperative-query syntax errors before they hit the
driver), runs the statement, and materialises each record.

Neither ``read()`` nor ``write()`` commits or rolls back — the caller owns the transaction
boundary. The factory yields the session or live transaction to run against.
"""  # NOQA 501

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, cast

from orthograph.cypher.exceptions import CypherSyntaxError
from orthograph.cypher.parser import parse_cypher
from orthograph.cypher.query import CypherQuery
from orthograph.query.base_models import (
    AsyncExecutor,
    D,
    Executor,
    P,
    R,
    ReadQueryModel,
    WriteQueryModel,
)


@dataclass
class CypherWriteResultSummary:
    """Vendor-free summary of a Cypher write operation.

    Wraps the ``SummaryCounters`` from ``neo4j.Result.consume().counters``
    and satisfies the :class:`~orthograph.query.write_result.WriteResultSummary`
    protocol, making ``interpret_result`` implementations testable without a
    live driver.

    Example::

        # In a TypedCypherWriteQueryModel.interpret_result implementation:
        def interpret_result(self, raw: WriteResultSummary) -> int:
            return raw.nodes_created
    """

    nodes_created: int = 0
    nodes_deleted: int = 0
    relationships_created: int = 0
    relationships_deleted: int = 0
    properties_set: int = 0

    @classmethod
    def from_neo4j_result(cls, result: Any) -> "CypherWriteResultSummary":
        """Build from a neo4j ``Result`` by consuming it and reading counters."""
        return _summary_from_counters(result.consume().counters)


def _summary_from_counters(counters: Any) -> "CypherWriteResultSummary":
    """Build a CypherWriteResultSummary from a neo4j SummaryCounters-shaped object.

    The caller (sync or async executor) is responsible for having already consumed
    the driver result; this helper only reads the five mutation counters.
    """
    return CypherWriteResultSummary(
        nodes_created=counters.nodes_created,
        nodes_deleted=counters.nodes_deleted,
        relationships_created=counters.relationships_created,
        relationships_deleted=counters.relationships_deleted,
        properties_set=counters.properties_set,
    )


class CypherExecutor(Executor):
    """Concrete ``Executor`` for graph databases.

    Accepts any driver whose session supports ``.run(cypher, **params)``
    returning an iterable of records, and whose session is usable as a context
    manager.  The factory is passed at construction; the session is never stored.

    Example (neo4j)::

        driver = GraphDatabase.driver(URI)
        CypherExecutor(driver.session)

    Example (test doubles)::

        CypherExecutor(lambda: FakeGraphSession(records))
    """

    def __init__(self, driver_factory: Callable[[], Any]) -> None:
        self._driver_factory = driver_factory

    @staticmethod
    def _validate_cypher(cypher: str, query_name: str) -> None:
        """Parse the Cypher string; raise CypherSyntaxError if it fails."""
        try:
            parse_cypher(cypher)
        except Exception as exc:
            raise CypherSyntaxError(
                f"Query '{query_name}' produced unparseable Cypher: {exc}"
            ) from exc

    def _prepare_statement(
        self, query: Any, raw_params: Any
    ) -> tuple[str, dict[str, Any], str]:
        """Shared read/write prologue: validate → build → parse.

        Returns ``(cypher, qparams, query_identity)`` ready to hand to a
        session.  The only difference between ``read`` and ``write`` is what
        happens *after* this — transaction handling — so the prologue lives
        here once and the two verbs keep their distinct I/O tails.
        """
        params_model = query.params_schema
        query_identity = query.query_id
        params = params_model.model_validate(raw_params)
        cypher, qparams = query.build(params)
        self._validate_cypher(cypher, query_identity)  # runtime syntax check
        return cypher, qparams, query_identity

    def read(self, query: ReadQueryModel[P, D], raw_params: Any) -> list[D]:
        """Validate params → build → parse Cypher → run → materialise (no commit)."""
        cypher, qparams, _ = self._prepare_statement(query, raw_params)
        with self._driver_factory() as session:  # only I/O seam
            # Auto-commit: read() runs a single statement via session.run() and
            # does not open an explicit transaction (unlike write()). This is
            # deliberate — the typed params/build contract produces exactly one
            # statement per query, so multi-statement read isolation is out of
            # scope. A read that needs read-isolation across statements is not
            # representable here and is not a supported use case.
            records = list(session.run(cypher, **qparams))
            return [query.materialize(dict(rec)) for rec in records]

    def write(self, query: WriteQueryModel[P, R], raw_params: Any) -> R:
        """Validate params → build → parse Cypher → run → interpret_result (no commit).

        The caller owns the transaction boundary (ADR-028). Pass a session whose
        context-manager exit auto-commits for standalone writes, or pass a live transaction
        and commit externally. Any rows projected by a RETURN clause are discarded — write
        results come from the mutation counters via interpret_result.
        """  # NOQA E501
        cypher, qparams, _ = self._prepare_statement(query, raw_params)
        with self._driver_factory() as session:
            result = session.run(cypher, **qparams)
            summary = _summary_from_counters(result.consume().counters)
        return query.interpret_result(summary)


class AsyncCypherExecutor(AsyncExecutor):
    """Async Executor for graph databases. Caller owns the transaction (ADR-028).

    Accepts an async factory yielding an AsyncSession or a live AsyncTransaction
    (any object with ``async run()``); runs the statement and NEVER commits or
    rolls back.

    The factory pattern mirrors the sync CypherExecutor: pass a callable returning an
    async context manager, not a live session. Open/close happens per call.

    Example (neo4j async, auto-commit session)::

        AsyncCypherExecutor(lambda: driver.session())

    Example (caller-owned transaction, e.g. MP transaction_context)::

        AsyncCypherExecutor(lambda: live_async_tx)
    """

    def __init__(self, driver_factory: Callable[[], Any]) -> None:
        self._driver_factory = driver_factory

    async def read(self, query: ReadQueryModel[P, D], raw_params: Any) -> list[D]:
        """Validate params → build → parse Cypher → run → materialize (no commit)."""
        params = cast(P, query.params_schema.model_validate(raw_params))
        cypher, qparams = query.build(params)
        CypherExecutor._validate_cypher(cypher, query.query_id)
        async with self._driver_factory() as session:
            result = await session.run(cypher, **qparams)
            records = [dict(rec) async for rec in result]
        # materialize() is called outside the async-with: it is pure and sync (ADR-028).
        return [query.materialize(rec) for rec in records]

    async def write(self, query: WriteQueryModel[P, R], raw_params: Any) -> R:
        """Validate params → build → parse Cypher → run → interpret_result.

        No commit — caller owns the transaction boundary (ADR-028).
        """
        params = cast(P, query.params_schema.model_validate(raw_params))
        cypher, qparams = query.build(params)
        CypherExecutor._validate_cypher(cypher, query.query_id)
        async with self._driver_factory() as session:
            result = await session.run(cypher, **qparams)
            summary = _summary_from_counters((await result.consume()).counters)
        return query.interpret_result(summary)


class CypherQueryExecutor:
    """Executor for the simple-path CypherQuery. Caller owns the transaction (ADR-028).

    CypherQuery declares no Output model and makes no read/write distinction, so this
    executor exposes two operations named by return shape:

    - fetch()   -> list[dict[str, Any]]    (a RETURN query)
    - execute() -> CypherWriteResultSummary (a mutation)

    It never commits or rolls back;
    the factory yields the session or a live transaction.
    """

    def __init__(self, driver_factory: Callable[[], Any]) -> None:
        self._driver_factory = driver_factory

    def fetch(self, query: CypherQuery, raw_params: Any) -> list[dict[str, Any]]:
        """Validate params → build → parse Cypher → run → return raw list[dict]."""
        params = query.params_schema.model_validate(raw_params)
        cypher, qparams = query.build(params)
        CypherExecutor._validate_cypher(cypher, query.query_id)
        with self._driver_factory() as session:
            records = list(session.run(cypher, **qparams))
            return [query.materialize(dict(rec)) for rec in records]

    def execute(self, query: CypherQuery, raw_params: Any) -> CypherWriteResultSummary:
        """Validate params → build → parse Cypher
        → run → return write summary (no commit)."""
        params = query.params_schema.model_validate(raw_params)
        cypher, qparams = query.build(params)
        CypherExecutor._validate_cypher(cypher, query.query_id)
        with self._driver_factory() as session:
            result = session.run(cypher, **qparams)
            return _summary_from_counters(result.consume().counters)


class AsyncCypherQueryExecutor:
    """Async executor for the simple-path CypherQuery. C
    aller owns the transaction.

    Mirrors CypherQueryExecutor for the async driver surface.
    Never commits or rolls back.
    """

    def __init__(self, driver_factory: Callable[[], Any]) -> None:
        self._driver_factory = driver_factory

    async def fetch(self, query: CypherQuery, raw_params: Any) -> list[dict[str, Any]]:
        """Validate params → build → parse Cypher
        → async run → return raw list[dict]."""
        params = query.params_schema.model_validate(raw_params)
        cypher, qparams = query.build(params)
        CypherExecutor._validate_cypher(cypher, query.query_id)
        async with self._driver_factory() as session:
            result = await session.run(cypher, **qparams)
            records = [dict(rec) async for rec in result]
        # materialize() called outside async-with: pure/sync .
        return [query.materialize(rec) for rec in records]

    async def execute(
        self, query: CypherQuery, raw_params: Any
    ) -> CypherWriteResultSummary:
        """Validate params → build → parse Cypher → async run → return write summary."""
        params = query.params_schema.model_validate(raw_params)
        cypher, qparams = query.build(params)
        CypherExecutor._validate_cypher(cypher, query.query_id)
        async with self._driver_factory() as session:
            result = await session.run(cypher, **qparams)
            return _summary_from_counters((await result.consume()).counters)
