"""Typed query catalogue — the public surface of the typed query track.

Queries are Python classes, not config: their return type is statically known,
there is no string-key dispatch, and no YAML (see epic E16 OPEN DECISION).

Exports:
  - ``ReadQuery`` / ``WriteQuery`` — the typed query contract (pure build +
    per-record materialise).
  - ``Executor`` — the single session seam (read ≠ write).
  - ``ReadPort`` / ``QueryBackedReadPort`` — store-neutral read capability for
    swappable backends.
  - ``Backend`` — descriptive backend tag (not a dispatch switch).
  - ``QueryCatalogue`` / ``QueryDescription`` — typed object registry and its
    introspection record.
"""

from orthograph.catalogue.registry import QueryCatalogue, QueryDescription
from orthograph.catalogue.typed import (
    Backend,
    Executor,
    QueryBackedReadPort,
    ReadPort,
    ReadQuery,
    WriteQuery,
)


__all__ = [
    "Backend",
    "Executor",
    "QueryBackedReadPort",
    "QueryCatalogue",
    "QueryDescription",
    "ReadPort",
    "ReadQuery",
    "WriteQuery",
]
