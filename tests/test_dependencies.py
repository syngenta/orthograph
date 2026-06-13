"""Tests for orthograph.dependencies — the single availability authority."""

import pytest

import orthograph.dependencies as dependencies
from orthograph.dependencies import MissingDependencyError


def test_known_backends_are_declared() -> None:
    for name in ("neo4j", "memgraph", "networkx", "gqlalchemy", "cypher"):
        assert name in dependencies._BACKENDS


def test_is_available_unknown_is_false() -> None:
    assert dependencies.is_available("nonsense") is False


def test_require_unknown_raises_with_known_list() -> None:
    with pytest.raises(MissingDependencyError, match="Unknown backend"):
        dependencies.require("nonsense")


def test_require_installed_backend_does_not_raise() -> None:
    # networkx is a test dependency, so it must be importable here.
    assert dependencies.is_available("networkx") is True
    dependencies.require("networkx")  # must not raise


def test_require_missing_dependency_names_the_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the probe to report neo4j as missing.
    real_module_present = dependencies._module_present

    def fake_module_present(name: str) -> bool:
        if name == "neo4j":
            return False
        return real_module_present(name)

    monkeypatch.setattr(dependencies, "_module_present", fake_module_present)

    with pytest.raises(MissingDependencyError, match=r"orthograph\[neo4j\]"):
        dependencies.require("neo4j")


def test_memgraph_shares_neo4j_driver_probe() -> None:
    # Both memgraph and neo4j probe the neo4j package (documented shared driver).
    _, _, neo4j_probes = dependencies._BACKENDS["neo4j"]
    _, _, memgraph_probes = dependencies._BACKENDS["memgraph"]
    assert memgraph_probes == neo4j_probes == ("neo4j",)
