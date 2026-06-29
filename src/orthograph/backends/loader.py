"""Backend-name → adapter loader.

The wiring table lives in :mod:`orthograph.backends.registry`.
This module exposes the public load_inspector / load_executor / capabilities API.
"""

from typing import Any

from orthograph.backends.neo4j.inspector import Neo4jInspectionStrategy
from orthograph.backends.registry import (
    BACKENDS,
    AsyncExecutorClass,
    BackendCapabilities,
    BackendSpec,
    ExecutorClass,
)
from orthograph.dependencies import MissingDependencyError, require
from orthograph.graph_profile.inspection import GraphInspector
from orthograph.graph_profile.models import GraphProfile


__all__ = [
    "BackendCapabilities",
    "BackendSpec",
    "Neo4jInspectionStrategy",
    "backend_names",
    "capabilities",
    "load_async_executor",
    "load_executor",
    "load_inspector",
    "run_inspection",
]

# For backward compatibility with existing tests that access _BACKENDS
_BACKENDS = BACKENDS


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------


def backend_names() -> list[str]:
    """Return every wired backend name, sorted.

    Derived solely from ``BACKENDS`` so the name set has a single source.
    """
    return sorted(BACKENDS)


def capabilities(name: str) -> BackendCapabilities:
    """Return the inspect/execute capabilities for ``name``.

    Derived from the backend's :class:`BackendSpec`: ``can_inspect`` when an
    inspection adapter is wired, ``can_execute`` when a typed-query executor is
    wired. Does not import any vendor package — reads the table only.

    Raises
    ------
    MissingDependencyError
        If ``name`` is not a wired backend.
    """
    spec = BACKENDS.get(name)
    if spec is None:
        raise MissingDependencyError(
            f"Unknown backend {name!r}. Known backends: {', '.join(backend_names())}."
        )
    return BackendCapabilities(
        can_inspect=spec.inspector is not None,
        can_execute=spec.executor is not None,
    )


def load_inspector(name: str) -> type[GraphInspector]:
    """Return the inspector class for ``name`` after verifying its dependencies.

    Raises
    ------
    MissingDependencyError
        If ``name`` is unknown, its dependencies are not installed, or it has
        no inspection adapter.
    """
    spec = BACKENDS.get(name)
    if spec is None or spec.inspector is None:
        known = ", ".join(sorted(n for n, s in BACKENDS.items() if s.inspector))
        raise MissingDependencyError(
            f"Unknown backend {name!r}. Known backends: {known}."
        )
    require(name)
    return spec.inspector()


def run_inspection(
    name: str, connection: Any, **inspection_kwargs: Any
) -> GraphProfile:
    """Inspect ``connection`` with backend ``name`` and return a ``GraphProfile``.

    Owns the constructor-vs-call split: keyword arguments named in the backend's
    :attr:`BackendSpec.inspector_init_kwargs` are routed to the inspector
    **constructor**; all others are passed to its ``inspect()`` **call**.  This
    keeps the public API facade thin — the per-backend knowledge of which knob
    configures the instance vs the call lives here, beside the registry.

    Raises
    ------
    MissingDependencyError
        If ``name`` is unknown, its dependencies are not installed, or it has
        no inspection adapter.
    TypeError
        If ``inspection_kwargs`` contains a key the backend does not accept.
    """
    spec = BACKENDS[name] if name in BACKENDS else None
    inspector_cls = load_inspector(name)  # validates name + dependencies
    assert spec is not None  # load_inspector would have raised otherwise

    init_keys = spec.inspector_init_kwargs
    init_kwargs = {k: v for k, v in inspection_kwargs.items() if k in init_keys}
    call_kwargs = {k: v for k, v in inspection_kwargs.items() if k not in init_keys}

    return inspector_cls(**init_kwargs).inspect(connection, **call_kwargs)


def load_executor(name: str) -> ExecutorClass:
    """Return the Executor class for ``name`` after verifying its dependencies.

    Raises
    ------
    MissingDependencyError
        If ``name`` is unknown, its dependencies are not installed, or its
        executor is not available for this backend.
    """
    spec = BACKENDS.get(name)
    if spec is not None and spec.deferred_executor_reason is not None:
        raise MissingDependencyError(spec.deferred_executor_reason)
    if spec is None or spec.executor is None:
        known = ", ".join(
            sorted(
                n
                for n, s in BACKENDS.items()
                if s.executor is not None or s.deferred_executor_reason is not None
            )
        )
        raise MissingDependencyError(
            f"Unknown execution backend {name!r}. Known backends: {known}."
        )
    require(name)
    return spec.executor()


def load_async_executor(name: str) -> AsyncExecutorClass:
    """Return the AsyncExecutor class for ``name`` after verifying its dependencies.

    Raises
    ------
    MissingDependencyError
        If ``name`` is unknown, its dependencies are not installed, or async
        execution is not available for this backend.
    """
    spec = BACKENDS.get(name)
    if spec is not None and spec.deferred_executor_reason is not None:
        raise MissingDependencyError(spec.deferred_executor_reason)
    if spec is None or spec.async_executor is None:
        known = ", ".join(
            sorted(
                n
                for n, s in BACKENDS.items()
                if s.async_executor is not None
                or s.deferred_executor_reason is not None
            )
        )
        raise MissingDependencyError(
            f"Unknown execution backend {name!r}. Known backends: {known}."
        )
    require(name)
    return spec.async_executor()
