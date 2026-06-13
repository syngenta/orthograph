"""Backend-name → adapter loader.

Maps backend names to deferred-import thunks for inspector and executor classes.
Imports are deferred so optional vendor packages are never imported at module load.
"""

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from orthograph.dependencies import MissingDependencyError, require
from orthograph.graph_profile.inspection import GraphInspector
from orthograph.query.base_models import Executor


# ---------------------------------------------------------------------------
# ExecutorClass — the constructable-executor protocol
# ---------------------------------------------------------------------------
# ``Executor`` is an ABC with no declared ``__init__``.  Callers need to
# instantiate the returned class with a connection factory.  This Protocol
# captures that shape so mypy can verify the call site in ``api/database.py``
# without requiring a concrete import there.


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
# BackendSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendSpec:
    """Adapter-wiring record for one named backend.

    ``inspector`` is ``None`` for backends with no inspection adapter.
    ``executor`` is ``None`` when no typed query executor exists.
    ``deferred_executor_reason`` carries an actionable error message for
    backends whose executor is intentionally absent; ``load_executor`` raises
    with this message instead of the generic "unknown backend" text.
    """

    inspector: Callable[[], type[GraphInspector]] | None
    executor: Callable[[], ExecutorClass] | None
    deferred_executor_reason: str | None = None


# ---------------------------------------------------------------------------
# Backend wiring table
# ---------------------------------------------------------------------------
# Vendor names appear exactly here and nowhere else in the adapter-loading
# path.  Add one BackendSpec per new backend; register the same name in
# orthograph.dependencies for the availability check.

_BACKENDS: dict[str, BackendSpec] = {
    "neo4j": BackendSpec(
        inspector=_neo4j_inspector,
        executor=_cypher_executor,
    ),
    "memgraph": BackendSpec(
        inspector=_memgraph_inspector,
        executor=_cypher_executor,
    ),
    "networkx": BackendSpec(
        inspector=_networkx_inspector,
        executor=None,
    ),
    "cypher": BackendSpec(
        inspector=None,
        executor=_cypher_executor,
    ),
    "gqlalchemy": BackendSpec(
        inspector=None,
        executor=None,
        deferred_executor_reason=(
            "Typed-query execution is not available for the 'gqlalchemy' builder "
            "backend. Execute GQLAlchemy builder queries via "
            "orthograph.backends.gqlalchemy.query_builder.ValidatedQueryBuilder."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------


def load_inspector(name: str) -> type[GraphInspector]:
    """Return the inspector class for ``name`` after verifying its dependencies.

    Raises
    ------
    MissingDependencyError
        If ``name`` is unknown, its dependencies are not installed, or it has
        no inspection adapter.
    """
    spec = _BACKENDS.get(name)
    if spec is None or spec.inspector is None:
        known = ", ".join(sorted(n for n, s in _BACKENDS.items() if s.inspector))
        raise MissingDependencyError(
            f"Unknown backend {name!r}. Known backends: {known}."
        )
    require(name)
    return spec.inspector()


def load_executor(name: str) -> ExecutorClass:
    """Return the Executor class for ``name`` after verifying its dependencies.

    Raises
    ------
    MissingDependencyError
        If ``name`` is unknown, its dependencies are not installed, or its
        executor is not available for this backend.
    """
    spec = _BACKENDS.get(name)
    if spec is not None and spec.deferred_executor_reason is not None:
        raise MissingDependencyError(spec.deferred_executor_reason)
    if spec is None or spec.executor is None:
        known = ", ".join(
            sorted(
                n
                for n, s in _BACKENDS.items()
                if s.executor is not None or s.deferred_executor_reason is not None
            )
        )
        raise MissingDependencyError(
            f"Unknown execution backend {name!r}. Known backends: {known}."
        )
    require(name)
    return spec.executor()
