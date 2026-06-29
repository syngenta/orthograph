"""Run typed read/write queries against a backend.

Two direction-named verbs, each stating its result shape:

* ``run_read``  — execute a typed read query; returns ``list[Output]``.
* ``run_write`` — execute a typed write query; returns the interpreted result.

Both receive a **connection factory**: a callable returning a session context
manager (NOT a driver — that is the ``profile.inspect_*`` argument).
Orthograph opens and closes every connection per call and stores nothing.

``ReadQueryModel``/``WriteQueryModel`` are re-exported here so consumers can type their
query subclasses without reaching into ``orthograph.query.*``.
"""

from typing import Any, Callable

from orthograph.backends import loader
from orthograph.cypher.query_execution import (
    CypherExecutor,
    CypherWriteResultSummary,
)
from orthograph.query.base_models import (
    Backend,
    D,
    P,
    QueryBackedReadPort,
    R,
    ReadPort,
    ReadQueryModel,
    WriteQueryModel,
)


__all__ = [
    "ReadQueryModel",
    "WriteQueryModel",
    "run_read",
    "run_write",
    "CypherExecutor",
    "CypherWriteResultSummary",
    "ReadPort",
    "QueryBackedReadPort",
    "Backend",
]


def run_read(
    backend: str,
    connection_factory: Callable[[], Any],
    read_query: ReadQueryModel[P, D],
    params: Any,
) -> list[D]:
    """Execute a typed read query against ``backend``; return ``list[Output]``.

    Operand: a typed read query. ``connection_factory`` is a callable returning
    a session context manager, opened and closed per call.
    """
    executor_cls = loader.load_executor(name=backend)
    return executor_cls(connection_factory).read(query=read_query, raw_params=params)


def run_write(
    backend: str,
    connection_factory: Callable[[], Any],
    write_query: WriteQueryModel[P, R],
    params: Any,
) -> R:
    """Execute a typed write query against ``backend``; return the result.

    Operand: a typed write query. ``connection_factory`` is a callable returning
    a session context manager, opened and closed per call.
    """
    executor_cls = loader.load_executor(name=backend)
    return executor_cls(connection_factory).write(query=write_query, raw_params=params)
