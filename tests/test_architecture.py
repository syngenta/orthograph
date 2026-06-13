"""Architecture invariant tests.

These tests use Python's ``ast`` module to inspect source text — no external
CLI tools, no vendor imports, fully OS-independent.

Invariants enforced:
  1. No ``backends/<X>`` module imports a *different* ``backends/<Y>``.
  2. Vendor-free layers (``graph_profile/``, ``graph_definition/``,
     ``comparison/``, ``catalogue/``, ``cypher/``, ``diagnostics/``)
     contain no top-level graph-DB vendor import (``neo4j``, ``networkx``,
     ``gqlalchemy``).
  3. ``api/`` contains no top-level concrete-backend import (the sanctioned
     lazy ``importlib``-free thunks live in ``backends/loader.py``, inside
     function bodies, invisible to top-level-only walking).
  4. No ``__init__.py`` under ``src/orthograph/`` contains a convenience
     re-export (any ``import`` or ``from … import`` statement), with the single
     sanctioned exception of ``import importlib.metadata`` in the top-level
     ``orthograph/__init__.py``.
  5. ``diagnostics/`` imports no other ``orthograph`` domain package — it is
     the shared result currency that everything else depends on, so its
     dependency edge must point nowhere in the domain.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path


# ---------------------------------------------------------------------------
# Package root (resolved relative to this test file)
# ---------------------------------------------------------------------------

PKG_ROOT = Path(__file__).resolve().parent.parent / "src" / "orthograph"
assert PKG_ROOT.is_dir(), (
    f"Package root not found at {PKG_ROOT}. "
    "Re-check that the layout matches the expected src/orthograph structure."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BACKENDS = ("neo4j", "memgraph", "networkx", "gqlalchemy")

# Graph-DB drivers / ORMs that must not appear in vendor-free layers.
# graphglot is intentionally excluded: it is cypher/'s own legitimate parser
# dependency (the `cypher` extra), not a graph-DB vendor.
# memgraph is intentionally excluded: there is no `memgraph` Python package;
# memgraph uses the neo4j Bolt driver (see dependencies.py).
FORBIDDEN_VENDORS = ("neo4j", "networkx", "gqlalchemy")

# Vendor-free layers: none of FORBIDDEN_VENDORS may appear as a top-level
# import in any *.py under these subdirectories.
VENDOR_FREE_LAYERS = (
    "graph_profile",
    "graph_definition",
    "comparison",
    "catalogue",
    "cypher",
    "diagnostics",
)

# Domain packages that diagnostics/ must not import from (invariant 5).
# diagnostics/ is the foundation; everything points *to* it, never the reverse.
DOMAIN_PACKAGES = (
    "graph_definition",
    "graph_profile",
    "comparison",
    "catalogue",
    "cypher",
    "backends",
    "api",
    "io",
    "visualization",
)


def _iter_py(dirpath: Path) -> Iterator[Path]:
    """Yield all *.py files under *dirpath* recursively."""
    yield from dirpath.rglob("*.py")


def _top_level_imports(path: Path) -> list[tuple[str, int]]:
    """Return (module_name, lineno) for every top-level import in *path*.

    Only module-level statements are inspected (``tree.body``); imports that
    appear inside function bodies, class bodies, or ``if`` blocks are NOT
    returned.  This is deliberate: it means the sanctioned deferred import
    thunks inside ``backends/loader.py``'s ``load_inspector``/``load_executor``
    functions are correctly invisible to these invariant checks.

    Relative imports whose ``module`` is ``None`` (bare ``from . import x``)
    are skipped — the codebase uses absolute ``orthograph.*`` imports, but we
    guard anyway.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    result: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue  # bare relative import (``from . import x``)
            result.append((node.module, node.lineno))
    return result


# ---------------------------------------------------------------------------
# Test 1 — no cross-backend import
# ---------------------------------------------------------------------------


def test_no_cross_backend_imports() -> None:
    """No ``backends/<X>`` module may import a different ``backends/<Y>``.

    Imports within the same backend (e.g. ``backends/neo4j/inspector.py``
    importing ``orthograph.backends.neo4j.queries``) are legal and are NOT
    flagged.  Only cross-backend imports are violations.
    """
    violations: list[str] = []

    backends_root = PKG_ROOT / "backends"
    for backend in BACKENDS:
        backend_dir = backends_root / backend
        if not backend_dir.is_dir():
            continue
        for py_file in _iter_py(backend_dir):
            for module_name, lineno in _top_level_imports(py_file):
                # Check if this import targets orthograph.backends.<other>
                prefix = "orthograph.backends."
                if not module_name.startswith(prefix):
                    continue
                # Extract the backend segment immediately after the prefix
                rest = module_name[len(prefix) :]
                imported_backend = rest.split(".")[0]
                # Same-backend import is legal; only flag cross-backend
                if imported_backend in BACKENDS and imported_backend != backend:
                    rel = py_file.relative_to(PKG_ROOT.parent.parent)
                    violations.append(
                        f"  {rel}:{lineno} — backends/{backend} imports "
                        f"backends/{imported_backend} "
                        f"(via '{module_name}')"
                    )

    assert not violations, "Cross-backend import violations found:\n" + "\n".join(
        violations
    )


# ---------------------------------------------------------------------------
# Test 2 — vendor-free layers stay vendor-free
# ---------------------------------------------------------------------------


def test_vendor_free_layers_have_no_vendor_imports() -> None:
    """graph_profile/, graph_definition/, comparison/, catalogue/, cypher/
    must not import vendors.

    Forbidden top-level imports: ``neo4j``, ``networkx``, ``gqlalchemy``
    (any import whose module is one of these or starts with ``<vendor>.``).

    ``graphglot`` is intentionally NOT in the forbidden set: it is cypher/'s
    own parser engine (the ``cypher`` extra), not a graph-DB vendor.
    """
    violations: list[str] = []

    for layer in VENDOR_FREE_LAYERS:
        layer_dir = PKG_ROOT / layer
        if not layer_dir.is_dir():
            continue
        for py_file in _iter_py(layer_dir):
            for module_name, lineno in _top_level_imports(py_file):
                root = module_name.split(".")[0]
                if root in FORBIDDEN_VENDORS:
                    rel = py_file.relative_to(PKG_ROOT.parent.parent)
                    violations.append(
                        f"  {rel}:{lineno} — vendor-free layer '{layer}' "
                        f"imports forbidden vendor '{module_name}'"
                    )

    assert not violations, "Vendor-free layer violations found:\n" + "\n".join(
        violations
    )


# ---------------------------------------------------------------------------
# Test 3 — api/ has no top-level concrete-backend import
# ---------------------------------------------------------------------------


def test_api_has_no_top_level_backend_import() -> None:
    """No ``api/*.py`` may have a top-level import of ``orthograph.backends.*``.

    The only sanctioned way to reach a concrete backend from ``api/`` is
    ``orthograph.backends.loader`` — which itself performs deferred imports
    inside function bodies (thunks), not at module top.  Because this test
    walks only top-level statements, those thunks are invisible here, and
    ``database.py``'s ``from orthograph.backends import loader`` (which
    imports the *loader module*, not a concrete backend) correctly passes.
    """
    violations: list[str] = []

    api_dir = PKG_ROOT / "api"
    for py_file in api_dir.glob("*.py"):
        for module_name, lineno in _top_level_imports(py_file):
            if module_name.startswith("orthograph.backends."):
                rel = py_file.relative_to(PKG_ROOT.parent.parent)
                violations.append(
                    f"  {rel}:{lineno} — api/ has top-level backend import "
                    f"'{module_name}'"
                )

    assert not violations, (
        "api/ top-level backend import violations found:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Test 4 — no re-exports in any __init__.py
# ---------------------------------------------------------------------------


def test_no_reexports_in_init_files() -> None:
    """No ``__init__.py`` under ``src/orthograph/`` may contain a re-export.

    A re-export is any ``import`` or ``from … import`` statement at the module
    level.  The single sanctioned exception is the top-level
    ``orthograph/__init__.py``, which is allowed to contain exactly one
    ``import importlib.metadata`` statement (needed for the ``__version__``
    machinery).
    """
    # The one allowed non-docstring statement in the top-level __init__.py
    TOPLEVEL_INIT = PKG_ROOT / "__init__.py"
    ALLOWED_TOPLEVEL_MODULE = "importlib.metadata"

    violations: list[str] = []

    for init_file in PKG_ROOT.rglob("__init__.py"):
        try:
            source = init_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(init_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        rel = init_file.relative_to(PKG_ROOT.parent.parent)

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # Allow importlib.metadata in the top-level __init__ only
                    if (
                        init_file == TOPLEVEL_INIT
                        and alias.name == ALLOWED_TOPLEVEL_MODULE
                    ):
                        continue
                    violations.append(
                        f"  {rel}:{node.lineno} — re-export via 'import {alias.name}'"
                    )
            elif isinstance(node, ast.ImportFrom):
                # All from-imports in __init__.py are forbidden re-exports
                module = node.module or ""
                names = ", ".join(a.name for a in node.names)
                violations.append(
                    f"  {rel}:{node.lineno} — re-export via "
                    f"'from {module} import {names}'"
                )

    assert not violations, "__init__.py re-export violations found:\n" + "\n".join(
        violations
    )


# ---------------------------------------------------------------------------
# Test 5 — diagnostics/ has no domain-package dependencies (invariant 5)
# ---------------------------------------------------------------------------


def test_diagnostics_has_no_domain_deps() -> None:
    """``diagnostics/`` must not import any other ``orthograph`` domain package.

    ``diagnostics`` is the shared result currency — the foundation layer that
    every other package depends on.  Its own import graph must point only to
    the standard library and third-party packages (e.g. ``pydantic``), never
    back into the domain.

    Allowed intra-package import: ``orthograph.diagnostics.*`` (self-reference).
    Forbidden: any ``orthograph.<domain>`` where domain is one of
    ``DOMAIN_PACKAGES``.
    """
    violations: list[str] = []

    diag_dir = PKG_ROOT / "diagnostics"
    if not diag_dir.is_dir():
        return  # nothing to check if the package doesn't exist yet

    for py_file in _iter_py(diag_dir):
        for module_name, lineno in _top_level_imports(py_file):
            if not module_name.startswith("orthograph."):
                continue
            # Strip leading "orthograph." to get the sub-package
            rest = module_name[len("orthograph.") :]
            imported_pkg = rest.split(".")[0]
            if imported_pkg in DOMAIN_PACKAGES:
                rel = py_file.relative_to(PKG_ROOT.parent.parent)
                violations.append(
                    f"  {rel}:{lineno} — diagnostics/ imports domain package "
                    f"'{imported_pkg}' (via '{module_name}')"
                )

    assert not violations, (
        "diagnostics/ domain-dependency violations found:\n" + "\n".join(violations)
    )
