"""Vendor-free write result protocol.

Defines the structural contract that any write-result object must satisfy so
that ``WriteQueryModel.interpret_result`` implementations are testable without a
live database driver.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class WriteResultSummary(Protocol):
    """Vendor-free contract for the result of a write operation.

    Both the real neo4j driver result (via CypherWriteResultSummary) and
    test doubles must satisfy this protocol.
    """

    @property
    def nodes_created(self) -> int: ...

    @property
    def nodes_deleted(self) -> int: ...

    @property
    def relationships_created(self) -> int: ...

    @property
    def relationships_deleted(self) -> int: ...

    @property
    def properties_set(self) -> int: ...
