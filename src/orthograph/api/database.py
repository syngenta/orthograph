"""Public database API — operations against a live graph backend.

Four verbs, all backend-dispatched:

* ``inspect``  — read the database's current shape into a :class:`GraphProfile`.
* ``validate`` — compare that profile against a :class:`GraphDefinition`.
* ``query``    — execute a typed read query; returns ``list[Output]``.
* ``execute``  — execute a typed write query; returns the interpreted result.

``inspect`` and ``validate`` receive a **driver**; ``query`` and ``execute``
receive a **connection factory** callable returning a session context manager.
Orthograph opens and closes every connection per call and stores nothing.
"""

from collections.abc import Sequence
from typing import Any, Callable

from orthograph.backends import loader
from orthograph.comparison.engine import compare_profile_to_definition
from orthograph.comparison.rules import Rule
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import GraphProfile
from orthograph.query.base_models import D, P, R, ReadQuery, WriteQuery


def inspect(
    backend: str,
    connection: Any,
    **backend_kwargs: Any,
) -> GraphProfile:
    """Inspect ``connection`` with the named ``backend``; return a
    :class:`GraphProfile`.

    ``backend_kwargs`` are forwarded to the adapter (e.g. ``database=`` for neo4j).
    """
    inspector_cls = loader.load_inspector(name=backend)
    return inspector_cls().inspect(connection=connection, **backend_kwargs)


def validate(
    backend: str,
    connection: Any,
    graph_definition: GraphDefinition,
    rules: Sequence[Rule] | None = None,
    **backend_kwargs: Any,
) -> ValidationResult:
    """Inspect ``connection`` and validate the resulting profile against
    ``graph_definition``.

    ``backend_kwargs`` are forwarded to the backend adapter (e.g. ``database=``
    for neo4j).  ``rules`` overrides the default comparison rule set.
    """
    profile = inspect(backend=backend, connection=connection, **backend_kwargs)
    return compare_profile_to_definition(
        profile=profile, graph_definition=graph_definition, rules=rules
    )


def query(
    backend: str,
    connection_factory: Callable[[], Any],
    read_query: ReadQuery[P, D],
    params: Any,
) -> list[D]:
    """Execute a typed read query against ``backend``; return ``list[Output]``."""
    executor_cls = loader.load_executor(name=backend)
    return executor_cls(connection_factory).read(query=read_query, raw_params=params)


def execute(
    backend: str,
    connection_factory: Callable[[], Any],
    write_query: WriteQuery[P, R],
    params: Any,
) -> R:
    """Execute a typed write query against ``backend``; return the result."""
    executor_cls = loader.load_executor(name=backend)
    return executor_cls(connection_factory).write(query=write_query, raw_params=params)
