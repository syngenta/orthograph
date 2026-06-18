"""Shared fixtures for backend tests (Neo4j, Memgraph, etc.)."""

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
