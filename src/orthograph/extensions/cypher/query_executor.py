"""Cypher concrete Executor — the single graph-driver I/O seam.

``CypherExecutor`` is the only place a graph session is opened. It accepts a
driver/session factory (Constraint 13 — orthograph never owns a connection),
validates params at the boundary (R4), calls the query's pure ``build()`` (R1),
runs the Cypher, and materialises each record (R3).

After ``build()`` returns a Cypher string, the executor always parses it via
``parse_cypher()`` to verify dialect compliance. For declarative queries (those
with a ``cypher_template`` ClassVar) this is redundant — the same parse already
ran at class-definition time. For imperative queries (those that override
``build()`` without a ``cypher_template`` ClassVar) this runtime parse is the
only syntax check and ensures no malformed Cypher reaches the database.

``read()`` commits nothing; ``write()`` commits — distinct transactional intent.
"""

from typing import Any, Callable, cast

from orthograph.catalogue.typed import D, Executor, P, R, ReadQuery, WriteQuery
from orthograph.extensions.cypher.parser import parse_cypher


class CypherSyntaxError(Exception):
    """Raised when a Cypher string produced by build() does not parse."""


class CypherExecutor(Executor):
    """Concrete ``Executor`` for graph databases (the single graph-driver seam).

    Accepts any driver whose session supports ``.run(cypher, **params)``
    returning an iterable of records, and whose session is usable as a context
    manager. The factory is passed at construction (Constraint 13 — the session
    is never stored as instance state).

    After ``build()`` produces a Cypher string, the executor validates it via
    ``parse_cypher()`` before opening a session. This catches syntax errors at
    runtime — particularly important for imperative queries that skip
    definition-time validation.

    Example (neo4j)::

        driver = GraphDatabase.driver(URI)
        CypherExecutor(driver.session)

    Example (test)::

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

    def read(self, query: ReadQuery[P, D], raw_params: Any) -> list[D]:
        """Validate → build (pure) → parse Cypher → open session → run → materialise.

        No commit.
        """
        params = cast(P, query.Params.model_validate(raw_params))  # R4
        cypher, qparams = query.build(params)  # R1 — pure
        self._validate_cypher(cypher, query.name)  # runtime syntax check
        with self._driver_factory() as session:  # only I/O seam
            # Auto-commit: read() runs a single statement via session.run() and
            # does not open an explicit transaction (unlike write()). This is
            # deliberate — the typed Params/build contract produces exactly one
            # statement per query, so multi-statement read isolation is out of
            # scope. A read that needs read-isolation across statements is not
            # representable here and is not a supported use case.
            records = list(session.run(cypher, **qparams))
            return [query.materialize(dict(rec)) for rec in records]  # R3

    def write(self, query: WriteQuery[P, R], raw_params: Any) -> R:
        """Validate → build → parse Cypher → open session → run → commit.

        Calls ``interpret_result()`` to map the driver result.
        """
        params = cast(P, query.Params.model_validate(raw_params))  # R4
        cypher, qparams = query.build(params)  # R1 — pure
        self._validate_cypher(cypher, query.name)  # runtime syntax check
        with self._driver_factory() as session:  # only I/O seam
            tx = session.begin_transaction()
            try:
                result = tx.run(cypher, **qparams)
                interpreted = query.interpret_result(result)
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
