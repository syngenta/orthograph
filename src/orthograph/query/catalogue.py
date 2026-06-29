"""QueryCatalogue — a typed object registry for multiple query types.

The catalogue stores query *instances* and introspects them via ``describe()``.
Queries reference their Output model by direct import (a Pydantic class), so the
catalogue never performs string-key model lookup and the return type of a read
stays statically known.

Execution is separate — see ``orthograph.query.base_models``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from orthograph.cypher.query import CypherQuery
from orthograph.query.base_models import (
    Backend,
    D,
    P,
    R,
    ReadQueryModel,
    WriteQueryModel,
)


@dataclass(frozen=True)
class QueryDescription:
    """A backend-neutral description of one registered query.

    Produced by ``QueryCatalogue.describe()``. ``output_schema`` is ``None``
    for writes (writes declare no ``Output``); for reads it is the declared
    Output model's JSON schema.

    ``output_class`` is the actual Output class (not the JSON schema dict) for
    queries that declare it; ``None`` for queries without an Output.
    """

    query_id: str
    kind: Literal["read", "write"]
    backend: Backend
    params_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    output_class: type[BaseModel] | None


class QueryCatalogue:
    """A typed object registry for query instances (read, write, and simple).

    Register queries with ``register_read`` / ``register_write`` /
    ``register_cypher_query`` and introspect them with ``describe()`` /
    ``names()``. Names are unique across all three kinds within a single
    catalogue; a duplicate raises ``ValueError``.

    This is a stateful service, not a value object — instances are not compared
    or hashed by their registry contents (it is a plain class, like the sibling
    ``CypherExecutor`` / ``QueryBackedReadPort`` services).
    """

    def __init__(self) -> None:
        self._reads: dict[str, ReadQueryModel[Any, Any]] = {}
        self._writes: dict[str, WriteQueryModel[Any, Any]] = {}
        self._cypher_queries: dict[str, CypherQuery] = {}

    def _reject_duplicate(self, name: str) -> None:
        if name in self._reads or name in self._writes or name in self._cypher_queries:
            raise ValueError(f"a query named {name!r} is already registered")

    def register_read(self, query: ReadQueryModel[P, D]) -> ReadQueryModel[P, D]:
        """Register a read query. Returns the query. Raises on duplicate name."""
        self._reject_duplicate(query.query_id)
        self._reads[query.query_id] = query
        return query

    def register_write(self, query: WriteQueryModel[P, R]) -> WriteQueryModel[P, R]:
        """Register a write query. Returns the query. Raises on duplicate name."""
        self._reject_duplicate(query.query_id)
        self._writes[query.query_id] = query
        return query

    def register_cypher_query(self, query: CypherQuery) -> CypherQuery:
        """Register a simple CypherQuery. Returns the query. Raises on duplicate name.

        Simple queries are stored separately from typed ReadQueryModel / WriteQueryModel
        instances but participate in ``queries()`` and ``validate_query_catalogue``
        so that YAML-loaded queries receive the same static validation as typed ones.
        """
        self._reject_duplicate(query.query_id)
        self._cypher_queries[query.query_id] = query
        return query

    def queries(
        self, backend: Backend | None = None
    ) -> list[ReadQueryModel[Any, Any] | WriteQueryModel[Any, Any] | CypherQuery]:
        """Return the registered query instances (reads, then writes, then simple).

        Unlike ``describe()`` (which returns backend-neutral descriptions), this
        exposes the query objects themselves so backend-specific tooling — e.g. a
        Cypher validator that needs each query's ``cypher_template`` — can inspect
        them. Filtered by ``backend`` when given.
        """
        all_queries: list[
            ReadQueryModel[Any, Any] | WriteQueryModel[Any, Any] | CypherQuery
        ] = [
            *self._reads.values(),
            *self._writes.values(),
            *self._cypher_queries.values(),
        ]
        if backend is not None:
            return [q for q in all_queries if q.backend == backend]
        return all_queries

    def names(self, backend: Backend | None = None) -> list[str]:
        """Return registered query names.

        Ordering is all reads then all writes, each in registration order — not
        global registration order across the two kinds.

        If ``backend`` is given, only names of queries targeting that backend are
        returned; ``None`` (the default) returns every name.
        """
        return [d.query_id for d in self.describe(backend=backend)]

    def get(self, name: str) -> QueryDescription:
        """Return the ``QueryDescription`` for a single registered query by name.

        Raises ``KeyError`` if no query with that name has been registered.
        """
        for desc in self.describe():
            if desc.query_id == name:
                return desc
        raise KeyError(f"no query named {name!r} is registered")

    def describe(self, backend: Backend | None = None) -> list[QueryDescription]:
        """Return a QueryDescription for each registered query.

        Ordering matches ``names()``: all reads, then all writes, then all
        simple CypherQuery instances, each in registration order.

        If ``backend`` is given, only queries targeting that backend are
        described; ``None`` (the default) describes every query.
        """
        descriptions: list[QueryDescription] = []
        for q in self.queries():
            if isinstance(q, CypherQuery):
                kind: Literal["read", "write"] = "read"
                output_schema = None
                output_class = None
            elif isinstance(q, WriteQueryModel):
                kind = "write"
                output_schema = (
                    q.Output.model_json_schema() if q.Output is not None else None
                )
                output_class = q.Output
            else:  # ReadQueryModel
                kind = "read"
                output_schema = q.Output.model_json_schema()
                output_class = q.Output
            descriptions.append(
                QueryDescription(
                    query_id=q.query_id,
                    kind=kind,
                    backend=q.backend,
                    params_schema=q.params_schema.model_json_schema(),
                    output_schema=output_schema,
                    output_class=output_class,
                )
            )
        if backend is not None:
            descriptions = [d for d in descriptions if d.backend == backend]
        return descriptions
