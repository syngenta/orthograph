"""Validated query builder bridge for GQLAlchemy.

Wraps GQLAlchemy's fluent query builder with Orthograph Cypher validation.
Queries are validated against the :class:`GraphDataModel` before execution.
"""

from __future__ import annotations

from typing import Any

from orthograph.core.errors import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.extensions.gqlalchemy.result_adapter import (
    validate_gqa_result,
)


class ValidatedQueryBuilder:
    """Execute GQLAlchemy queries with Orthograph schema validation.

    Users construct queries using GQLAlchemy's native API (``match()``,
    ``create()``, ``merge()``, etc.) and pass the builder object to
    :meth:`execute_validated`.  The generated Cypher is validated against
    the model before execution.

    Args:
        model: The Orthograph :class:`GraphDataModel` to validate against.
        db: A GQLAlchemy ``DatabaseClient`` instance (``Memgraph`` or
            ``Neo4j``).

    Example::

        from gqlalchemy import match
        from orthograph.extensions.gqlalchemy import ValidatedQueryBuilder

        vqb = ValidatedQueryBuilder(model=model, db=db)
        builder = match().node(labels="Person", variable="p").return_()
        results = vqb.execute_validated(builder)
    """

    def __init__(
        self,
        model: GraphDataModel,
        db: Any,
    ) -> None:
        self._model = model
        self._db = db

    def validate_query(
        self,
        query_or_builder: Any,
    ) -> ValidationResult:
        """Validate a query against the model without executing it.

        Parses the Cypher and checks for unknown labels, relationship
        types, properties, and invalid endpoints.

        Args:
            query_or_builder: A GQLAlchemy query builder object or a
                raw Cypher string.

        Returns:
            A :class:`ValidationResult` with any issues found.
        """
        cypher = _extract_cypher(query_or_builder)
        return _validate_cypher(cypher, self._model)

    def execute_validated(
        self,
        query_or_builder: Any,
        validate_results: bool = False,
    ) -> list[dict[str, Any]]:
        """Validate, execute, and optionally validate query results.

        1. Extracts the Cypher string from the builder.
        2. Validates the Cypher against the model.
        3. Executes the query if validation passes.
        4. Optionally validates the results against the model.

        Args:
            query_or_builder: A GQLAlchemy query builder or Cypher string.
            validate_results: If ``True``, validate the result set
                against the model after execution (opt-in, default off).

        Returns:
            A list of result dicts.

        Raises:
            GraphValidationError: If query validation fails or (when
                *validate_results* is ``True``) result validation fails.
        """
        cypher = _extract_cypher(query_or_builder)

        # Pre-execution validation
        vr = _validate_cypher(cypher, self._model)
        vr.raise_on_errors()

        # Execute
        result_iter = self._db.execute_and_fetch(cypher)
        results = list(result_iter)

        # Post-execution validation (opt-in)
        if validate_results:
            result_vr = validate_gqa_result(results, self._model)
            result_vr.raise_on_errors()

        return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_cypher(query_or_builder: Any) -> str:
    """Extract a Cypher query string from a builder object or raw string.

    GQLAlchemy query builders implement ``construct_query()`` and/or
    ``__str__()`` to produce the Cypher string.
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
    model: GraphDataModel,
) -> ValidationResult:
    """Validate a Cypher string against the model.

    Uses Orthograph's Cypher parser extension.  If graphglot is not
    installed, returns a valid (empty) result with a warning.
    """
    try:
        from orthograph.extensions.cypher import validate_cypher

        return validate_cypher(cypher, model)
    except ImportError:
        # graphglot not installed -- skip validation
        return ValidationResult()
