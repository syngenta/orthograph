"""GQLAlchemy query builder with Orthograph Cypher validation."""

from __future__ import annotations

from typing import Any

from orthograph.backends.gqlalchemy.result_adapter import (
    validate_gqa_result,
)
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition


class ValidatedQueryBuilder:
    """Executes GQLAlchemy queries with Orthograph schema validation.

    Construct queries using the GQLAlchemy fluent API and pass the builder
    to :meth:`execute_validated`.

    Example::

        from gqlalchemy import match
        from orthograph.backends.gqlalchemy.query_builder import ValidatedQueryBuilder

        vqb = ValidatedQueryBuilder(graph_definition=graph_definition, db=db)
        builder = match().node(labels="Person", variable="p").return_()
        results = vqb.execute_validated(builder)
    """

    def __init__(
        self,
        graph_definition: GraphDefinition,
        db: Any,
    ) -> None:
        self._graph_data_model = graph_definition
        self._db = db

    def validate_query(
        self,
        query_or_builder: Any,
    ) -> ValidationResult:
        """Validate a query against the model without executing it."""
        cypher = _extract_cypher(query_or_builder)
        return _validate_cypher(cypher, self._graph_data_model)

    def execute_validated(
        self,
        query_or_builder: Any,
        validate_results: bool = False,
    ) -> list[dict[str, Any]]:
        """Validate then execute a query; optionally validate results.

        Parameters
        ----------
        validate_results:
            When ``True``, result data is validated against the model
            after execution (opt-in, default off).

        Raises
        ------
        GraphValidationError
            If query or result validation fails.
        """
        cypher = _extract_cypher(query_or_builder)

        # Pre-execution validation
        vr = _validate_cypher(cypher, self._graph_data_model)
        vr.raise_on_errors()

        # Execute
        result_iter = self._db.execute_and_fetch(cypher)
        results = list(result_iter)

        # Post-execution validation (opt-in)
        if validate_results:
            result_vr = validate_gqa_result(results, self._graph_data_model)
            result_vr.raise_on_errors()

        return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_cypher(query_or_builder: Any) -> str:
    """Return a Cypher string from a builder or raw string.

    Tries ``construct_query()`` first, then falls back to ``str()``.
    """
    if isinstance(query_or_builder, str):
        return query_or_builder

    # Try construct_query() first (GQLAlchemy's primary method)
    if hasattr(query_or_builder, "construct_query"):
        return str(query_or_builder.construct_query())

    # Fall back to str()
    return str(query_or_builder)


def _validate_cypher(
    cypher: str,
    graph_definition: GraphDefinition,
) -> ValidationResult:
    """Validate a Cypher string against ``graph_definition``.

    Raises :class:`~orthograph.dependencies.MissingDependencyError` if the
    ``cypher`` extra is not installed; never silently returns a passing result.
    """
    from orthograph.dependencies import require

    require("cypher")
    from orthograph.cypher.parser import validate_cypher

    return validate_cypher(cypher, graph_definition)
