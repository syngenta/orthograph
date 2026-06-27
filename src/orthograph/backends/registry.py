"""Single registry of every named backend.

Each :class:`BackendSpec` records both the adapter wiring (inspector/executor thunks)
and the availability metadata (pip-extra, kind, probe modules).

This is the only file that needs updating when a new backend is added.
The corresponding ``[project.optional-dependencies]`` entry in ``pyproject.toml``
must also be updated manually.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol

from orthograph.graph_profile.inspection import GraphInspector
from orthograph.query.base_models import Executor


Kind = Literal["db-driver", "orm", "in-memory", "tool"]


class ExecutorClass(Protocol):
    """A constructable :class:`~orthograph.query.base_models.Executor`."""

    def __call__(self, driver_factory: Callable[[], Any]) -> Executor: ...


# ---------------------------------------------------------------------------
# Deferred-import thunks
# ---------------------------------------------------------------------------
# Each thunk is a plain module-level function so that:
#   - the import is unconditionally lazy (vendor package may not be installed);
#   - a rename of the target class is caught by the type-checker / linter,
#     not silently at runtime;
#   - the body is visible to static analysis and IDEs.


def _neo4j_inspector() -> type[GraphInspector]:
    from orthograph.backends.neo4j.inspector import Neo4jInspector

    return Neo4jInspector


def _memgraph_inspector() -> type[GraphInspector]:
    from orthograph.backends.memgraph.inspector import MemgraphInspector

    return MemgraphInspector


def _networkx_inspector() -> type[GraphInspector]:
    from orthograph.backends.networkx.inspector import NetworkxInspector

    return NetworkxInspector


def _cypher_executor() -> ExecutorClass:
    from orthograph.cypher.query_execution import CypherExecutor

    return CypherExecutor


# ---------------------------------------------------------------------------
# BackendSpec and BackendCapabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendSpec:
    """Adapter-wiring and availability record for one named backend.

    ``pip_extra`` is the pip install extra name (e.g., ``neo4j``).
    ``kind`` categorizes the backend (``db-driver``, ``orm``, ``in-memory``, ``tool``).
    ``probe_modules`` is the tuple of module names to import-check for availability.

    ``inspector`` is ``None`` for backends with no inspection adapter.
    ``executor`` is ``None`` when no typed query executor exists.
    ``deferred_executor_reason`` carries an actionable error message for
    backends whose executor is intentionally absent; raises with this message
    instead of the generic error.

    ``inspector_init_kwargs`` names the keyword arguments routed to the
    inspector **constructor**; every other inspection keyword is routed to its
    ``inspect()`` **call**.  This is the one place that knows each backend's
    constructor-vs-call split, keeping the public API facade thin.
    """

    pip_extra: str
    kind: Kind
    probe_modules: tuple[str, ...]
    inspector: Callable[[], type[GraphInspector]] | None = None
    executor: Callable[[], ExecutorClass] | None = None
    deferred_executor_reason: str | None = None
    inspector_init_kwargs: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BackendCapabilities:
    """What a named backend can do, derived from its :class:`BackendSpec`.

    ``can_inspect`` is True when the backend has an inspection adapter;
    ``can_execute`` is True when it has a typed-query executor. Both are read
    directly from the registry — no vendor package is imported.
    """

    can_inspect: bool
    can_execute: bool


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------
# Memgraph deliberately shares the neo4j Bolt driver; both probe ``neo4j``.
# Add one entry here and one [project.optional-dependencies] entry in pyproject.toml.

BACKENDS: dict[str, BackendSpec] = {
    "neo4j": BackendSpec(
        pip_extra="neo4j",
        kind="db-driver",
        probe_modules=("neo4j",),
        inspector=_neo4j_inspector,
        executor=_cypher_executor,
        inspector_init_kwargs=frozenset({"strategy", "value_counts_top_n"}),
    ),
    "memgraph": BackendSpec(
        pip_extra="memgraph",
        kind="db-driver",
        probe_modules=("neo4j",),
        inspector=_memgraph_inspector,
        executor=_cypher_executor,
        inspector_init_kwargs=frozenset({"value_counts_top_n"}),
    ),
    "networkx": BackendSpec(
        pip_extra="networkx",
        kind="in-memory",
        probe_modules=("networkx",),
        inspector=_networkx_inspector,
        executor=None,
        inspector_init_kwargs=frozenset({"value_counts_top_n"}),
    ),
    "cypher": BackendSpec(
        pip_extra="cypher",
        kind="tool",
        probe_modules=("graphglot",),
        inspector=None,
        executor=_cypher_executor,
    ),
    "gqlalchemy": BackendSpec(
        pip_extra="gqlalchemy",
        kind="orm",
        probe_modules=("gqlalchemy",),
        inspector=None,
        executor=None,
        deferred_executor_reason=(
            "Typed-query execution is not available for the 'gqlalchemy' builder "
            "backend. Execute GQLAlchemy builder queries via "
            "orthograph.backends.gqlalchemy.query_builder.ValidatedQueryBuilder."
        ),
    ),
    "ipython": BackendSpec(
        pip_extra="notebooks",
        kind="tool",
        probe_modules=("IPython",),
        inspector=None,
        executor=None,
    ),
}
