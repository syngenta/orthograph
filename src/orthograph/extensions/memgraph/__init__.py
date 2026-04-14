"""Memgraph extension for orthograph."""

from orthograph.extensions.memgraph.inspector import (
    MemgraphInspector,
    validate_database,
)


__all__ = [
    "MemgraphInspector",
    "validate_database",
]
