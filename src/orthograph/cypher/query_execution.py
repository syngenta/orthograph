"""Concrete Executor — the single graph-driver I/O seam.

Opens a session per call, validates params, calls ``build()``, parses the
produced Cypher (catches imperative-query syntax errors before they hit the
driver), runs the statement, and materialises each record.

``read()`` does not commit; ``write()`` commits.
"""

from typing import Any, Callable, cast

from orthograph.cypher.exceptions import CypherSyntaxError
from orthograph.cypher.parser import parse_cypher
from orthograph.query.base_models import D, Executor, P, R, ReadQuery, WriteQuery


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

    def read(self, query: ReadQuery[P, D], raw_params: Any) -> list[D]:
        """Validate params → build → parse Cypher → run → materialise (no commit)."""
        params = cast(P, query.Params.model_validate(raw_params))
        cypher, qparams = query.build(params)
        self._validate_cypher(cypher, query.name)  # runtime syntax check
        with self._driver_factory() as session:  # only I/O seam
            # Auto-commit: read() runs a single statement via session.run() and
            # does not open an explicit transaction (unlike write()). This is
            # deliberate — the typed Params/build contract produces exactly one
            # statement per query, so multi-statement read isolation is out of
            # scope. A read that needs read-isolation across statements is not
            # representable here and is not a supported use case.
            records = list(session.run(cypher, **qparams))
            return [query.materialize(dict(rec)) for rec in records]

    def write(self, query: WriteQuery[P, R], raw_params: Any) -> R:
        """Validate params → build → parse Cypher → run → commit."""
        params = cast(P, query.Params.model_validate(raw_params))
        cypher, qparams = query.build(params)
        self._validate_cypher(cypher, query.name)  # runtime syntax check
        with self._driver_factory() as session:  # only I/O seam
            tx = session.begin_transaction()
            try:
                result = tx.run(cypher, **qparams)
                interpreted = query.materialize(result)
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
