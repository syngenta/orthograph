"""Tests for the orthograph root convenience surface (ADR-041).

Verifies that the seven capability modules are accessible directly from
``orthograph``, that each root name is a real ``orthograph.<name>`` module,
and that importing ``orthograph`` does not eagerly load any optional DB-vendor
package (neo4j, networkx, gqlalchemy).
"""

from __future__ import annotations

import subprocess
import sys
import types


# ---------------------------------------------------------------------------
# Fixtures: the expected root surface
# ---------------------------------------------------------------------------

EXPECTED_MODULES = [
    "definition",
    "profile",
    "compare",
    "queries",
    "execution",
    "discovery",
    "rendering",
]


# ---------------------------------------------------------------------------
# Surface completeness
# ---------------------------------------------------------------------------


def test_all_modules_present_on_root() -> None:
    """Every expected capability module is accessible on the root package."""
    import orthograph

    for name in EXPECTED_MODULES:
        assert hasattr(orthograph, name), (
            f"orthograph.{name} not found — expected a root-surface module"
        )


def test_all_in_dunder_all() -> None:
    """Every expected module is listed in ``orthograph.__all__``."""
    import orthograph

    for name in EXPECTED_MODULES:
        assert name in orthograph.__all__, f"'{name}' missing from orthograph.__all__"


def test_all_are_module_objects() -> None:
    """Each root name resolves to a module (not a class, function, or None)."""
    import orthograph

    for name in EXPECTED_MODULES:
        obj = getattr(orthograph, name)
        assert isinstance(obj, types.ModuleType), (
            f"orthograph.{name} is {type(obj).__name__}, expected a module"
        )


# ---------------------------------------------------------------------------
# Identity: root names are the real orthograph.<name> modules
# ---------------------------------------------------------------------------


def test_root_names_are_real_root_modules() -> None:
    """``orthograph.<name>`` resolves to ``orthograph.<name>`` (not a sub-package)."""
    import orthograph

    for name in EXPECTED_MODULES:
        mod = getattr(orthograph, name)
        assert mod.__name__ == f"orthograph.{name}", (
            f"orthograph.{name}.__name__ is '{mod.__name__}', "
            f"expected 'orthograph.{name}'"
        )


def test_from_import_resolves() -> None:
    """``from orthograph.<name> import X`` works for all seven modules."""
    from orthograph.compare import Rule, profile_to_definition
    from orthograph.definition import CardinalitySpec, GraphDefinition, NodeModel
    from orthograph.discovery import available
    from orthograph.execution import ReadQuery, WriteQuery
    from orthograph.profile import GraphProfile, inspect_networkx
    from orthograph.queries import QueryCatalogue, new_catalogue
    from orthograph.rendering import RenderFormat, render_model

    assert NodeModel is not None
    assert GraphDefinition is not None
    assert CardinalitySpec is not None
    assert GraphProfile is not None
    assert inspect_networkx is not None
    assert profile_to_definition is not None
    assert Rule is not None
    assert QueryCatalogue is not None
    assert new_catalogue is not None
    assert ReadQuery is not None
    assert WriteQuery is not None
    assert available is not None
    assert render_model is not None
    assert RenderFormat is not None


# ---------------------------------------------------------------------------
# Verbs and types are reachable through the root modules
# ---------------------------------------------------------------------------


def test_key_verbs_reachable() -> None:
    """Spot-check that important verbs are reachable via the root surface."""
    import orthograph

    assert callable(orthograph.profile.inspect_neo4j)
    assert callable(orthograph.profile.inspect_networkx)
    assert callable(orthograph.profile.inspect_memgraph)
    assert callable(orthograph.profile.check_connection)
    assert callable(orthograph.compare.profile_to_definition)
    assert callable(orthograph.compare.profiles)
    assert callable(orthograph.compare.definitions)
    assert callable(orthograph.definition.validate_data)
    assert callable(orthograph.definition.validate_definition)
    assert callable(orthograph.definition.load_from_file)
    assert callable(orthograph.definition.save_to_file)
    assert callable(orthograph.queries.check_syntax)
    assert callable(orthograph.queries.validate)
    assert callable(orthograph.queries.validate_catalogue)
    assert callable(orthograph.queries.load_catalogue)
    assert callable(orthograph.queries.generate_crud)
    assert callable(orthograph.execution.run_read)
    assert callable(orthograph.execution.run_write)
    assert callable(orthograph.discovery.available)
    assert callable(orthograph.discovery.can_inspect)
    assert callable(orthograph.discovery.can_execute)
    assert callable(orthograph.rendering.render_model)
    assert callable(orthograph.rendering.render_profile)
    assert callable(orthograph.rendering.render_result)


def test_key_types_reachable() -> None:
    """Spot-check that important types are reachable via the root surface."""
    import orthograph

    assert orthograph.definition.GraphDefinition is not None
    assert orthograph.definition.NodeModel is not None
    assert orthograph.definition.RelationshipModel is not None
    assert orthograph.profile.GraphProfile is not None
    assert orthograph.queries.QueryCatalogue is not None
    assert orthograph.queries.CypherQuery is not None
    assert orthograph.queries.CypherReadQuery is not None
    assert orthograph.queries.CypherWriteQuery is not None
    assert orthograph.execution.ReadQuery is not None
    assert orthograph.execution.WriteQuery is not None
    assert orthograph.rendering.RenderFormat is not None


# ---------------------------------------------------------------------------
# Optional-dependency isolation: DB vendors must NOT load on import orthograph
# ---------------------------------------------------------------------------


def test_import_orthograph_pulls_no_db_vendor() -> None:
    """Importing ``orthograph`` must not eagerly load any DB-vendor package.

    Runs in a subprocess to get a clean ``sys.modules``.
    graphglot is now a core dep and is expected to load; the DB drivers
    (neo4j, networkx, gqlalchemy) must stay deferred.
    """
    code = (
        "import sys, orthograph; "
        "bad = [m for m in sys.modules if m.split('.')[0] in ('neo4j','networkx','gqlalchemy')]; "  # NOQA E501
        "print(bad)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    loaded = eval(result.stdout.strip())  # noqa: S307  — controlled subprocess output
    assert loaded == [], f"import orthograph eagerly loaded DB-vendor modules: {loaded}"
