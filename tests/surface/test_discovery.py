"""Tests for orthograph.discovery — typed selection + capability discovery.

Covers:
- available(): subset of backend_names(), only installed (is_available mocked)
- can_inspect / can_execute: match loader capabilities per backend
- is_available: delegates to dependencies.is_available
- Error paths: unknown backend raises MissingDependencyError;
  is_available("nope") is False
"""

from __future__ import annotations

import pytest

from orthograph import discovery as api_discovery
from orthograph.backends import loader
from orthograph.dependencies import MissingDependencyError


# ---------------------------------------------------------------------------
# available()
# ---------------------------------------------------------------------------


def test_available_is_subset_of_backend_names() -> None:
    available = api_discovery.available()
    assert set(available).issubset(set(loader.backend_names()))


def test_available_contains_only_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    installed = {"neo4j", "networkx"}
    monkeypatch.setattr(
        "orthograph.discovery.dependencies.is_available",
        lambda name: name in installed,
    )
    available = api_discovery.available()
    assert set(available) == installed & set(loader.backend_names())


def test_available_empty_when_nothing_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "orthograph.discovery.dependencies.is_available",
        lambda name: False,
    )
    assert api_discovery.available() == []


# ---------------------------------------------------------------------------
# is_available — delegates to dependencies.is_available
# ---------------------------------------------------------------------------


def test_is_available_unknown_returns_false() -> None:
    assert api_discovery.is_available("nope") is False


def test_is_available_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "orthograph.discovery.dependencies.is_available",
        lambda name: name == "neo4j",
    )
    assert api_discovery.is_available("neo4j") is True
    assert api_discovery.is_available("networkx") is False


# ---------------------------------------------------------------------------
# can_inspect / can_execute — match loader capabilities
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("backend", "can_inspect", "can_execute"),
    [
        ("neo4j", True, True),
        ("memgraph", True, True),
        ("networkx", True, False),
        ("cypher", False, True),
        ("gqlalchemy", False, False),
    ],
)
def test_capabilities_match_loader(
    backend: str, can_inspect: bool, can_execute: bool
) -> None:
    assert api_discovery.can_inspect(backend) is can_inspect
    assert api_discovery.can_execute(backend) is can_execute
    caps = loader.capabilities(backend)
    assert api_discovery.can_inspect(backend) is caps.can_inspect
    assert api_discovery.can_execute(backend) is caps.can_execute


def test_can_inspect_unknown_raises() -> None:
    with pytest.raises(MissingDependencyError):
        api_discovery.can_inspect("nope")


def test_can_execute_unknown_raises() -> None:
    with pytest.raises(MissingDependencyError):
        api_discovery.can_execute("nope")
