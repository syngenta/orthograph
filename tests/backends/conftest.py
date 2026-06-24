"""Shared fixtures for backend tests (Neo4j, Memgraph, etc.)."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock


def make_record(data: dict[str, Any]) -> MagicMock:
    """Create a mock record that supports dict() conversion."""
    record = MagicMock()
    record.__iter__ = MagicMock(return_value=iter(data.keys()))
    record.__getitem__ = MagicMock(side_effect=data.__getitem__)
    record.keys = MagicMock(return_value=list(data.keys()))
    record.values = MagicMock(return_value=list(data.values()))
    record.items = MagicMock(return_value=list(data.items()))
    record.__len__ = MagicMock(return_value=len(data))
    record.__contains__ = MagicMock(side_effect=data.__contains__)
    return record


def mock_execute_query(
    rows: list[dict[str, Any]],
    keys: list[str] | None = None,
) -> tuple[list[MagicMock], MagicMock, list[str]]:
    """Build a return value for driver.execute_query(...)."""
    records = [make_record(row) for row in rows]
    if keys is None:
        keys = list(rows[0].keys()) if rows else []
    return (records, MagicMock(), keys)


def ordered_side_effect_with_counts(
    ordered_responses: list[Any],
    *,
    default_count: int = 0,
    default_present_count: int = 0,
) -> Callable[..., Any]:
    """Build a ``side_effect`` that serves ``ordered_responses`` by call order,
    but transparently answers the dedicated instance-count queries
    (``RETURN count(n) AS count`` / ``RETURN count(r) AS count``) and the
    per-property present-count queries (``… AS present_count``) out of
    band.

    The count queries (``neo4j.inspect.node_count`` / ``rel_count``) are issued
    per node label / relationship type independently of properties.  They are
    distinctive (``count(n) AS count`` / ``count(r) AS count``) and carry no
    ordering significance for the property/cardinality assertions, so this
    wrapper keeps existing strict-ordered ``responses`` lists valid without
    interleaving a count response after every label / rel type.

    The present-count queries (``neo4j.inspect.node_present_count`` /
    ``rel_present_count``) are issued per APOC-strategy property to supersede
    APOC's sampled ``propertyObservations`` (ADR-036); they are served out of
    band for the same reason.

    ``default_count`` / ``default_present_count`` are returned for every count /
    present-count query (tests that assert a specific value should pass their own).
    """
    ordered_iter = iter(ordered_responses)

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": default_count}], ["count"])
        if "AS present_count" in cypher:
            return mock_execute_query(
                [{"present_count": default_present_count}], ["present_count"]
            )
        return next(ordered_iter)

    return side_effect
