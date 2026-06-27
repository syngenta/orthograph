"""Tests for orthograph.profile — inspect a backend into a GraphProfile.

The facade is thin: every verb delegates to
``orthograph.backends.loader.run_inspection`` (the constructor-vs-call kwarg
split and dispatch are tested in ``tests/backends/test_loader.py``).  These
tests cover the facade's own behaviour:

- the per-backend verbs forward the right backend name + kwargs to the loader;
- ``check_connection`` validates the borrowed connection shape;
- the live networkx path produces a real GraphProfile;
- ``GraphProfile`` / ``Neo4jInspectionStrategy`` are re-exported.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import networkx as nx
import pytest

from orthograph.profile import (
    GraphProfile,
    Neo4jInspectionStrategy,
    check_connection,
    inspect_memgraph,
    inspect_neo4j,
    inspect_networkx,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _networkx_graph() -> nx.MultiDiGraph[str]:
    g: nx.MultiDiGraph[str] = nx.MultiDiGraph()
    g.add_node("p1", __label__="Person", name="Alice")
    return g


def _fake_driver() -> MagicMock:
    """A minimal stand-in that looks like a neo4j.Driver to check_connection."""
    d = MagicMock()
    d.execute_query = MagicMock()
    return d


# ---------------------------------------------------------------------------
# Live behaviour (no mock)
# ---------------------------------------------------------------------------


def test_inspect_networkx_verb_returns_graph_profile() -> None:
    profile = inspect_networkx(_networkx_graph())
    assert isinstance(profile, GraphProfile)
    assert profile.source == "networkx"
    assert "Person" in profile.node_labels


# ---------------------------------------------------------------------------
# Verbs delegate to loader.run_inspection with the right name + kwargs
# ---------------------------------------------------------------------------


def test_inspect_networkx_delegates_to_run_inspection() -> None:
    from orthograph.graph_definition.graph_definition import GraphDefinition

    g = _networkx_graph()
    gd = MagicMock(spec=GraphDefinition)
    sentinel = GraphProfile(source="networkx")
    with pytest.MonkeyPatch.context() as mp:
        run = MagicMock(return_value=sentinel)
        mp.setattr("orthograph.profile.loader.run_inspection", run)

        result = inspect_networkx(g, value_counts_top_n=5, graph_definition=gd)

    assert result is sentinel
    run.assert_called_once_with(
        "networkx", g, value_counts_top_n=5, graph_definition=gd
    )


def test_inspect_neo4j_delegates_to_run_inspection() -> None:
    from orthograph.graph_definition.graph_definition import GraphDefinition

    driver = _fake_driver()
    gd = MagicMock(spec=GraphDefinition)
    sentinel = GraphProfile(source="neo4j")
    with pytest.MonkeyPatch.context() as mp:
        run = MagicMock(return_value=sentinel)
        mp.setattr("orthograph.profile.loader.run_inspection", run)

        result = inspect_neo4j(
            driver,
            database="staging",
            strategy=Neo4jInspectionStrategy.APOC,
            value_counts_top_n=10,
            graph_definition=gd,
        )

    assert result is sentinel
    run.assert_called_once_with(
        "neo4j",
        driver,
        database="staging",
        strategy=Neo4jInspectionStrategy.APOC,
        value_counts_top_n=10,
        graph_definition=gd,
    )


def test_inspect_memgraph_delegates_to_run_inspection() -> None:
    from orthograph.graph_definition.graph_definition import GraphDefinition

    driver = _fake_driver()
    gd = MagicMock(spec=GraphDefinition)
    sentinel = GraphProfile(source="memgraph")
    with pytest.MonkeyPatch.context() as mp:
        run = MagicMock(return_value=sentinel)
        mp.setattr("orthograph.profile.loader.run_inspection", run)

        result = inspect_memgraph(driver, value_counts_top_n=15, graph_definition=gd)

    assert result is sentinel
    run.assert_called_once_with(
        "memgraph", driver, value_counts_top_n=15, graph_definition=gd
    )


# ---------------------------------------------------------------------------
# check_connection
# ---------------------------------------------------------------------------


def test_check_connection_passes_valid_neo4j_driver() -> None:
    driver = _fake_driver()
    assert check_connection("neo4j", driver) is driver


def test_check_connection_passes_valid_memgraph_driver() -> None:
    driver = _fake_driver()
    assert check_connection("memgraph", driver) is driver


def test_check_connection_passes_valid_networkx_graph() -> None:
    g = _networkx_graph()
    assert check_connection("networkx", g) is g


def test_check_connection_rejects_non_driver_for_neo4j() -> None:
    with pytest.raises(TypeError, match="BoltDriver"):
        check_connection("neo4j", object())


def test_check_connection_rejects_non_graph_for_networkx() -> None:
    with pytest.raises(TypeError, match="MultiDiGraph"):
        check_connection("networkx", object())


def test_check_connection_raises_for_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unknown inspectable backend"):
        check_connection("nonsense", object())


# ---------------------------------------------------------------------------
# Re-exports
# ---------------------------------------------------------------------------


def test_neo4j_inspection_strategy_is_exported() -> None:
    assert Neo4jInspectionStrategy.APOC is not None
    assert Neo4jInspectionStrategy.SCHEMA is not None
    assert Neo4jInspectionStrategy.CYPHER is not None
