"""Tests for orthograph.backends.loader — the backend adapter-wiring seam.

These tests exercise the public interface of the loader (load_inspector,
load_executor) directly.  The loader is the seam between the consumer-facing
api/ layer and the concrete vendor adapters; testing it here verifies that:

  - returned classes satisfy the typed ABCs (GraphInspector, Executor);
  - unknown names produce a clear, actionable error;
  - deferred backends (gqlalchemy executor / E8) produce the right message;
  - availability is checked before the thunk is called (dependencies.require).
"""

import dataclasses
from unittest.mock import MagicMock

import pytest

from orthograph.backends import loader
from orthograph.backends.loader import BackendCapabilities, BackendSpec
from orthograph.dependencies import MissingDependencyError
from orthograph.graph_profile.inspection import GraphInspector
from orthograph.graph_profile.models import GraphProfile
from orthograph.query.base_models import Executor


# ---------------------------------------------------------------------------
# load_inspector — happy paths
# ---------------------------------------------------------------------------


def test_load_inspector_neo4j_returns_graph_inspector_subclass() -> None:
    cls = loader.load_inspector("neo4j")
    assert issubclass(cls, GraphInspector)


def test_load_inspector_memgraph_returns_graph_inspector_subclass() -> None:
    cls = loader.load_inspector("memgraph")
    assert issubclass(cls, GraphInspector)


def test_load_inspector_networkx_returns_graph_inspector_subclass() -> None:
    cls = loader.load_inspector("networkx")
    assert issubclass(cls, GraphInspector)


def test_load_inspector_returns_distinct_classes_per_backend() -> None:
    neo4j_cls = loader.load_inspector("neo4j")
    memgraph_cls = loader.load_inspector("memgraph")
    networkx_cls = loader.load_inspector("networkx")
    assert neo4j_cls is not memgraph_cls
    assert neo4j_cls is not networkx_cls
    assert memgraph_cls is not networkx_cls


# ---------------------------------------------------------------------------
# load_inspector — error paths
# ---------------------------------------------------------------------------


def test_load_inspector_unknown_raises_missing_dependency_error() -> None:
    with pytest.raises(MissingDependencyError, match="Unknown backend"):
        loader.load_inspector("nonsense")


def test_load_inspector_unknown_names_known_backends_in_message() -> None:
    with pytest.raises(MissingDependencyError, match="neo4j"):
        loader.load_inspector("nonsense")


def test_load_inspector_backend_with_no_inspector_raises() -> None:
    # "cypher" is a tool entry with no inspection adapter.
    with pytest.raises(MissingDependencyError, match="Unknown backend"):
        loader.load_inspector("cypher")


# ---------------------------------------------------------------------------
# load_executor — happy paths
# ---------------------------------------------------------------------------


def test_load_executor_neo4j_produces_executor_instance() -> None:
    cls = loader.load_executor("neo4j")
    assert isinstance(cls(lambda: None), Executor)


def test_load_executor_memgraph_produces_executor_instance() -> None:
    cls = loader.load_executor("memgraph")
    assert isinstance(cls(lambda: None), Executor)


def test_load_executor_cypher_produces_executor_instance() -> None:
    # "cypher" has no inspector but does have an executor.
    cls = loader.load_executor("cypher")
    assert isinstance(cls(lambda: None), Executor)


def test_load_executor_neo4j_and_memgraph_share_cypher_executor() -> None:
    # Both Cypher-dialect backends are backed by the same CypherExecutor.
    assert loader.load_executor("neo4j") is loader.load_executor("memgraph")


# ---------------------------------------------------------------------------
# load_executor — deferred / error paths
# ---------------------------------------------------------------------------


def test_load_executor_gqlalchemy_raises_missing_dependency_error() -> None:
    with pytest.raises(MissingDependencyError):
        loader.load_executor("gqlalchemy")


def test_load_executor_gqlalchemy_message_mentions_unavailable() -> None:
    with pytest.raises(MissingDependencyError, match="not available"):
        loader.load_executor("gqlalchemy")


def test_load_executor_gqlalchemy_message_references_validated_query_builder() -> None:
    with pytest.raises(MissingDependencyError, match="ValidatedQueryBuilder"):
        loader.load_executor("gqlalchemy")


def test_load_executor_unknown_raises_missing_dependency_error() -> None:
    with pytest.raises(MissingDependencyError, match="Unknown execution backend"):
        loader.load_executor("nonsense")


def test_load_executor_networkx_raises_unknown_execution_backend() -> None:
    # networkx has an inspector but no executor.
    with pytest.raises(MissingDependencyError, match="Unknown execution backend"):
        loader.load_executor("networkx")


# ---------------------------------------------------------------------------
# BackendSpec — structural
# ---------------------------------------------------------------------------


def test_backend_spec_is_frozen() -> None:
    spec = BackendSpec(
        pip_extra="test",
        kind="db-driver",
        probe_modules=("test_module",),
        inspector=None,
        executor=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.inspector = lambda: GraphInspector  # type: ignore[misc]


def test_all_declared_backends_have_a_spec() -> None:
    for name in ("neo4j", "memgraph", "networkx", "cypher", "gqlalchemy"):
        assert name in loader._BACKENDS, f"Missing BackendSpec for {name!r}"


# ---------------------------------------------------------------------------
# backend_names — single-source name set
# ---------------------------------------------------------------------------


def test_backend_names_returns_the_five_wired_names_sorted() -> None:
    assert loader.backend_names() == sorted(
        ["neo4j", "memgraph", "networkx", "cypher", "gqlalchemy", "ipython"]
    )


def test_backend_names_has_no_duplicates() -> None:
    names = loader.backend_names()
    assert len(names) == len(set(names))


def test_backend_names_derives_from_backends_table() -> None:
    assert set(loader.backend_names()) == set(loader._BACKENDS)


# ---------------------------------------------------------------------------
# capabilities — per-backend inspect/execute join
# ---------------------------------------------------------------------------


def test_capabilities_networkx_is_inspect_only() -> None:
    caps = loader.capabilities("networkx")
    assert caps == BackendCapabilities(can_inspect=True, can_execute=False)


def test_capabilities_cypher_is_execute_only() -> None:
    caps = loader.capabilities("cypher")
    assert caps == BackendCapabilities(can_inspect=False, can_execute=True)


def test_capabilities_neo4j_can_do_both() -> None:
    caps = loader.capabilities("neo4j")
    assert caps == BackendCapabilities(can_inspect=True, can_execute=True)


def test_capabilities_gqlalchemy_can_do_neither() -> None:
    caps = loader.capabilities("gqlalchemy")
    assert caps == BackendCapabilities(can_inspect=False, can_execute=False)


def test_capabilities_unknown_raises_missing_dependency_error() -> None:
    with pytest.raises(MissingDependencyError, match="Unknown backend"):
        loader.capabilities("nope")


def test_backend_capabilities_is_frozen() -> None:
    caps = BackendCapabilities(can_inspect=True, can_execute=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        caps.can_inspect = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# run_inspection — constructor-vs-call kwarg split
# ---------------------------------------------------------------------------
# The split is the registry's BackendSpec.inspector_init_kwargs: init kwargs go
# to the inspector constructor, every other kwarg to its inspect() call.  These
# tests mock the resolved inspector class (via load_inspector) and assert the
# routing, so they need no live vendor driver.


def _mock_inspector(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    """Patch loader.load_inspector to return a mock class; return (cls, instance)."""
    sentinel = GraphProfile(source="test")
    instance = MagicMock()
    instance.inspect.return_value = sentinel
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr(loader, "load_inspector", lambda name: cls)
    return cls, instance


def test_run_inspection_neo4j_splits_init_and_call_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls, instance = _mock_inspector(monkeypatch)
    connection = object()

    result = loader.run_inspection(
        "neo4j",
        connection,
        strategy="STRAT",
        value_counts_top_n=10,
        database="prod",
        graph_definition="GD",
    )

    assert isinstance(result, GraphProfile)
    # strategy + value_counts_top_n configure the instance; the rest is the call.
    cls.assert_called_once_with(strategy="STRAT", value_counts_top_n=10)
    instance.inspect.assert_called_once_with(
        connection, database="prod", graph_definition="GD"
    )


def test_run_inspection_memgraph_only_value_counts_to_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls, instance = _mock_inspector(monkeypatch)
    connection = object()

    loader.run_inspection(
        "memgraph", connection, value_counts_top_n=5, graph_definition="GD"
    )

    cls.assert_called_once_with(value_counts_top_n=5)
    instance.inspect.assert_called_once_with(connection, graph_definition="GD")


def test_run_inspection_networkx_only_value_counts_to_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls, instance = _mock_inspector(monkeypatch)
    connection = object()

    loader.run_inspection(
        "networkx", connection, value_counts_top_n=3, graph_definition="GD"
    )

    cls.assert_called_once_with(value_counts_top_n=3)
    instance.inspect.assert_called_once_with(connection, graph_definition="GD")


def test_run_inspection_no_kwargs_constructs_with_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls, instance = _mock_inspector(monkeypatch)
    connection = object()

    loader.run_inspection("neo4j", connection)

    cls.assert_called_once_with()
    instance.inspect.assert_called_once_with(connection)


def test_run_inspection_unknown_backend_raises() -> None:
    with pytest.raises(MissingDependencyError, match="Unknown backend"):
        loader.run_inspection("nonsense", object())
