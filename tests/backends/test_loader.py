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

import pytest

from orthograph.backends import loader
from orthograph.backends.loader import BackendSpec
from orthograph.dependencies import MissingDependencyError
from orthograph.graph_profile.inspection import GraphInspector
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
    spec = BackendSpec(inspector=None, executor=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.inspector = lambda: GraphInspector  # type: ignore[misc]


def test_all_declared_backends_have_a_spec() -> None:
    for name in ("neo4j", "memgraph", "networkx", "cypher", "gqlalchemy"):
        assert name in loader._BACKENDS, f"Missing BackendSpec for {name!r}"
