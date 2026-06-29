"""Concrete Executor — the single graph-driver I/O seam.

Opens a session per call, validates params, calls ``build()``, parses the
produced Cypher (catches imperative-query syntax errors before they hit the
driver), runs the statement, and materialises each record.

``read()`` does not commit; ``write()`` commits.
"""

from dataclasses import dataclass
from typing import Any, Callable

from orthograph.cypher.exceptions import CypherSyntaxError
from orthograph.cypher.parser import parse_cypher
from orthograph.query.base_models import (
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
        counters = result.consume().counters
        return cls(
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
        """Validate params → build → parse Cypher → run → commit.

        The driver result is consumed immediately via
        :meth:`CypherWriteResultSummary.from_neo4j_result`, which calls
        ``result.consume()`` and exposes only the five mutation counters
        (``nodes_created``, ``nodes_deleted``, ``relationships_created``,
        ``relationships_deleted``, ``properties_set``).  Any rows projected
        by a ``RETURN`` clause in the template are intentionally discarded —
        write queries express their result through ``interpret_result`` acting
        on those counters, not on returned row data.
        """
        cypher, qparams, _ = self._prepare_statement(query, raw_params)
        with self._driver_factory() as session:  # only I/O seam
            tx = session.begin_transaction()
            try:
                result = tx.run(cypher, **qparams)
                summary = CypherWriteResultSummary.from_neo4j_result(result)
                interpreted = query.interpret_result(summary)
                tx.commit()
            except BaseException:
                try:
                    tx.rollback()
                except Exception:
                    # A rollback failure (e.g. dropped connection) must not
                    # mask the original error. Swallow it so the original
                    # exception propagates with its traceback intact.
                    pass
                raise
            return interpreted
