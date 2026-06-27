"""Architecture invariant tests.

These tests use Python's ``ast`` module to inspect source text — no external
CLI tools, no vendor imports, fully OS-independent.

Invariants enforced:
  1. No ``backends/<X>`` module imports a *different* ``backends/<Y>``.
  2. Vendor-free layers (``graph_profile/``, ``graph_definition/``,
     ``comparison/``, ``catalogue/``, ``cypher/``, ``diagnostics/``)
     contain no top-level graph-DB vendor import (``neo4j``, ``networkx``,
     ``gqlalchemy``).
  3. The seven root capability modules (``definition.py``, ``profile.py``,
     ``compare.py``, ``queries.py``, ``execution.py``, ``discovery.py``,
     ``rendering.py``) contain no top-level direct ``orthograph.backends.*``
     import beyond the sanctioned ``orthograph.backends.loader`` seam.
  4. No ``__init__.py`` under ``src/orthograph/`` contains a convenience
     re-export (any ``import`` or ``from … import`` statement), with the
     sanctioned exceptions in the top-level ``orthograph/__init__.py``:
     ``import importlib.metadata`` and
     ``from orthograph import <capability-module-name>``.
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
    "io",
    "visualization",
)

# The seven root capability modules (ADR-041).
ROOT_CAPABILITY_MODULES = (
    "definition",
    "profile",
    "compare",
    "queries",
    "execution",
    "discovery",
    "rendering",
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
# Test 3 — root capability modules have no top-level concrete-backend import
# ---------------------------------------------------------------------------


def test_root_capability_modules_have_no_top_level_backend_import() -> None:
    """No root capability module may have a top-level import of
    ``orthograph.backends.*`` (beyond the sanctioned ``loader`` seam).

    The only sanctioned way to reach a concrete backend is via
    ``orthograph.backends.loader`` — which itself performs deferred imports
    inside function bodies (thunks), not at module top.  Because this test
    walks only top-level statements, those thunks are invisible here, and
    ``from orthograph.backends import loader`` correctly passes.
    """
    violations: list[str] = []

    for module_name in ROOT_CAPABILITY_MODULES:
        py_file = PKG_ROOT / f"{module_name}.py"
        if not py_file.exists():
            continue
        for imported, lineno in _top_level_imports(py_file):
            if imported.startswith("orthograph.backends."):
                rel = py_file.relative_to(PKG_ROOT.parent.parent)
                violations.append(
                    f"  {rel}:{lineno} — root capability module has top-level "
                    f"backend import '{imported}'"
                )

    assert not violations, (
        "Root capability module top-level backend import violations found:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Test 4 — no re-exports in any __init__.py (semantic rule)
#
# Policy (ADR-041):
#   • The root orthograph/__init__.py may:
#       – import importlib.metadata  (for __version__)
#       – from orthograph import <capability-module>  (submodule promotions)
#   • Every OTHER __init__.py under src/orthograph/ must remain import-free.
#   • No __init__.py may import directly from a deep orthograph sub-package
#     (e.g. graph_definition, cypher, backends).
#
# The key principle: the seven root capability modules are the single curated
# exposure surface; the root __init__ promotes them as attributes and nothing
# else.
# ---------------------------------------------------------------------------


def test_no_reexports_in_init_files() -> None:
    """Enforce the semantic re-export policy (ADR-041).

    For the root ``orthograph/__init__.py``:

    * ``import importlib.metadata`` is allowed (``__version__`` machinery).
    * ``from orthograph import <name>`` is allowed when ``<name>`` is one of
      the seven root capability modules — the managed submodule promotion.
    * Any other import is a violation.

    For every other ``__init__.py``:

    * Zero imports of any kind — unchanged from the original invariant.
    """
    TOPLEVEL_INIT = PKG_ROOT / "__init__.py"
    ALLOWED_TOPLEVEL_BARE_IMPORT = "importlib.metadata"
    ALLOWED_TOPLEVEL_FROM_MODULE = "orthograph"

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
                    if (
                        init_file == TOPLEVEL_INIT
                        and alias.name == ALLOWED_TOPLEVEL_BARE_IMPORT
                    ):
                        continue
                    violations.append(
                        f"  {rel}:{node.lineno} — disallowed 'import {alias.name}'"
                    )

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [a.name for a in node.names]
                names_str = ", ".join(names)
                if init_file == TOPLEVEL_INIT:
                    if module == ALLOWED_TOPLEVEL_FROM_MODULE and all(
                        n in ROOT_CAPABILITY_MODULES for n in names
                    ):
                        # Allowed: root promotes only the seven capability modules
                        continue
                    violations.append(
                        f"  {rel}:{node.lineno} — root __init__ may only do "
                        f"'from orthograph import <capability-module>', got "
                        f"'from {module} import {names_str}'"
                    )
                else:
                    violations.append(
                        f"  {rel}:{node.lineno} — re-export in non-root __init__ via "
                        f"'from {module} import {names_str}'"
                    )

    assert not violations, "__init__.py policy violations found:\n" + "\n".join(
        violations
    )


def test_root_surface_is_real_root_modules() -> None:
    """Every name the root promotes must resolve to a real ``orthograph.<name>``
    module (not a deep sub-package).

    Ensures the root cannot silently acquire a deep re-export.
    """
    import orthograph

    for name in orthograph.__all__:
        mod = getattr(orthograph, name)
        assert mod.__name__ == f"orthograph.{name}", (
            f"orthograph.{name} resolves to '{mod.__name__}', "
            f"expected 'orthograph.{name}'"
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
