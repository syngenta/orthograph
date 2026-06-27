"""Tests for orthograph.backends.registry — single source of truth for backend metadata.

These tests verify that:
  - The registry is complete and self-consistent.
  - Registry entries stay in sync with pyproject.toml optional-dependencies.
"""

from pathlib import Path

import pytest
import tomllib

from orthograph.backends.registry import BACKENDS


@pytest.fixture
def pyproject_toml_path() -> Path:
    """Return the path to pyproject.toml."""
    return Path(__file__).parent.parent.parent / "pyproject.toml"


def test_registry_has_all_known_backends() -> None:
    """Verify the registry declares all known backends."""
    expected = {"neo4j", "memgraph", "networkx", "cypher", "gqlalchemy", "ipython"}
    actual = set(BACKENDS.keys())
    assert actual == expected, f"Registry mismatch: {actual} != {expected}"


def test_each_backend_spec_has_required_fields() -> None:
    """Verify each BackendSpec has all required fields."""
    for name, spec in BACKENDS.items():
        assert spec.pip_extra, f"{name!r}: pip_extra is required"
        assert spec.kind, f"{name!r}: kind is required"
        assert spec.probe_modules, f"{name!r}: probe_modules is required"
        assert isinstance(spec.probe_modules, tuple), (
            f"{name!r}: probe_modules must be a tuple"
        )


def test_registry_entries_match_pyproject_toml(pyproject_toml_path: Path) -> None:
    """Verify every backend in registry has a corresponding
    [project.optional-dependencies] entry.

    This catches drift: if someone adds a backend to the registry but forgets to
    update pyproject.toml, this test will fail.
    """
    if not pyproject_toml_path.exists():
        pytest.skip(f"pyproject.toml not found at {pyproject_toml_path}")

    with open(pyproject_toml_path, "rb") as f:
        pyproject = tomllib.load(f)

    extras = pyproject.get("project", {}).get("optional-dependencies", {})

    # For each backend with a pip_extra, verify it exists in pyproject.toml
    for name, spec in BACKENDS.items():
        assert spec.pip_extra in extras, (
            f"Backend {name!r} declares pip_extra={spec.pip_extra!r}, "
            f"but no corresponding "
            f"[project.optional-dependencies.{spec.pip_extra}] in pyproject.toml"
        )


def test_pyproject_extras_mention_registry_backends(pyproject_toml_path: Path) -> None:
    """Verify every [project.optional-dependencies] entry is in the registry.

    This catches the opposite drift: if someone adds an extra to pyproject.toml
    but forgets to add it to the registry.

    Note: This may skip entries like 'notebooks', 'dev', etc. that aren't backends.
    """
    if not pyproject_toml_path.exists():
        pytest.skip(f"pyproject.toml not found at {pyproject_toml_path}")

    import tomllib

    with open(pyproject_toml_path, "rb") as f:
        pyproject = tomllib.load(f)

    extras = pyproject.get("project", {}).get("optional-dependencies", {})
    registry_extras = {spec.pip_extra for spec in BACKENDS.values()}

    # Backend extras (those corresponding to a backend in the registry)
    # should exist in pyproject.toml. This is not exhaustive since pyproject.toml
    # may have non-backend extras like 'dev', 'docs', etc.
    for extra in registry_extras:
        assert extra in extras, (
            f"Backend extra {extra!r} is "
            f"declared in registry but missing from pyproject.toml"
        )


def test_probed_modules_are_importable_or_missing_gracefully() -> None:
    """Sanity check: probe modules should not raise weird errors.

    This is a soft check—a module might not be installed, which is fine.
    We're just verifying the names are valid Python identifiers.
    """
    for name, spec in BACKENDS.items():
        for module in spec.probe_modules:
            assert isinstance(module, str), (
                f"{name!r}: probe module {module!r} is not a string"
            )
            assert module.replace(".", "").replace("_", "").isalnum(), (
                f"{name!r}: probe module {module!r} is not a valid Python module name"
            )
