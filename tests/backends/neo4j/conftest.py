"""Shared fixtures for Neo4j extension tests."""

from typing import Any
from unittest.mock import MagicMock

# Import shared backend fixtures from parent conftest
from tests.backends.conftest import make_record, mock_execute_query  # noqa: F401


def mock_node(
    labels: frozenset[str],
    properties: dict[str, Any],
    element_id: str = "eid:1",
) -> MagicMock:
    """Create a mock neo4j Node."""
    node = MagicMock()
    node.labels = labels
    node.element_id = element_id
    node.__iter__ = MagicMock(return_value=iter(properties.keys()))
    node.__getitem__ = MagicMock(side_effect=properties.__getitem__)
    node.get = MagicMock(side_effect=properties.get)
    node.items = MagicMock(return_value=properties.items())
    node.keys = MagicMock(return_value=properties.keys())
    node.__len__ = MagicMock(return_value=len(properties))
    return node


def mock_rel(
    rel_type: str,
    properties: dict[str, Any],
    start: MagicMock | None = None,
    end: MagicMock | None = None,
    element_id: str = "eid:r1",
) -> MagicMock:
    """Create a mock neo4j Relationship."""
    rel = MagicMock()
    rel.type = rel_type
    rel.element_id = element_id
    rel.start_node = start
    rel.end_node = end
    # Explicitly mark as NOT a node (labels is None, not frozenset)
    rel.labels = None
    rel.__iter__ = MagicMock(return_value=iter(properties.keys()))
    rel.__getitem__ = MagicMock(side_effect=properties.__getitem__)
    rel.get = MagicMock(side_effect=properties.get)
    rel.items = MagicMock(return_value=properties.items())
    rel.keys = MagicMock(return_value=properties.keys())
    rel.__len__ = MagicMock(return_value=len(properties))
    return rel


def mock_record(values: dict[str, Any]) -> MagicMock:
    """Create a mock neo4j Record."""
    record = MagicMock()
    record.__getitem__ = MagicMock(side_effect=values.__getitem__)
    record.keys = MagicMock(return_value=list(values.keys()))
    record.values = MagicMock(return_value=list(values.values()))
    record.items = MagicMock(return_value=list(values.items()))
    return record
