"""
Notebook inventory and existence checks.

This file documents which notebooks exist and verifies they're present
on disk.  Actual notebook execution is handled by nbval when running:

    pytest notebooks/ --nbval-lax

DB-requiring notebooks are excluded from collection by
``notebooks/conftest.py`` unless the relevant CLI flag is passed:

    pytest notebooks/ --nbval-lax --neo4j      # include Neo4j notebooks
    pytest notebooks/ --nbval-lax --memgraph   # include Memgraph notebooks

See the root ``conftest.py`` for marker/flag definitions.
"""

import json
import re
from pathlib import Path

import pytest


NOTEBOOKS_DIR = Path(__file__).resolve().parent.parent.parent / "notebooks"

# All notebooks in the project, grouped by module.
ALL_NOTEBOOKS = [
    # Module 01 -- Schema Design & Fundamentals
    NOTEBOOKS_DIR / "01.01_create_a_graph_definition.ipynb",
    NOTEBOOKS_DIR / "01.02_validating_graph_data.ipynb",
    NOTEBOOKS_DIR / "01.03_what_is_cardinality.ipynb",
    NOTEBOOKS_DIR / "01.04_optionality_and_cardinality.ipynb",
    NOTEBOOKS_DIR / "01.05_conditional_cardinality.ipynb",
    # Module 02 -- Schema Portability & Visualization
    NOTEBOOKS_DIR / "02.01_yaml_configuration.ipynb",
    NOTEBOOKS_DIR / "02.02_visualization.ipynb",
    # Module 03 -- Cypher & Query Contracts
    NOTEBOOKS_DIR / "03.01_cypher_generation.ipynb",
    NOTEBOOKS_DIR / "03.02_cypher_query_definitions.ipynb",
    NOTEBOOKS_DIR / "03.03_cypher_query_usage.ipynb",
    NOTEBOOKS_DIR / "03.04_typed_query_contracts.ipynb",
    NOTEBOOKS_DIR / "03.05_result_shapes_and_materialization.ipynb",
    # Module 04 -- Backend Integration
    NOTEBOOKS_DIR / "04.01_networkx_backend.ipynb",
    NOTEBOOKS_DIR / "04.02_neo4j_backend.ipynb",
    NOTEBOOKS_DIR / "04.03_gqlalchemy_backend.ipynb",
    # Module 05 -- Comparison & Drift Detection
    NOTEBOOKS_DIR / "05.01_profile_vs_definition.ipynb",
    NOTEBOOKS_DIR / "05.02_profile_vs_profile.ipynb",
    NOTEBOOKS_DIR / "05.03_definition_vs_definition.ipynb",
    # Module 06 -- Framework Integration
    NOTEBOOKS_DIR / "06.01_fastapi_integration.ipynb",
]

# Pattern that matches the old (removed) bare ``compare`` import.
# The renamed function is ``compare_profile_to_definition``.
_STALE_COMPARE_IMPORT = re.compile(
    r"from\s+orthograph\.comparison\.engine\s+import\b[^;#\n]*\bcompare\b(?!_)"
)


@pytest.mark.parametrize(
    "notebook_path",
    [pytest.param(nb, id=nb.name) for nb in ALL_NOTEBOOKS],
)
def test_notebook_exists(notebook_path: Path) -> None:
    """Confirm all documented notebooks are present on disk."""
    assert notebook_path.exists(), (
        f"Notebook not found: {notebook_path}\n"
        "Either add the notebook or remove it from ALL_NOTEBOOKS."
    )


@pytest.mark.parametrize(
    "notebook_path",
    [pytest.param(nb, id=nb.name) for nb in ALL_NOTEBOOKS],
)
def test_notebook_no_stale_compare_import(notebook_path: Path) -> None:
    """Notebooks must not import the removed bare ``compare`` function.

    After E27, the function was renamed to ``compare_profile_to_definition``.
    Any notebook still importing ``compare`` will raise ``ImportError`` at
    runtime.
    """
    if not notebook_path.exists():
        pytest.skip("notebook not on disk — covered by test_notebook_exists")

    nb = json.loads(notebook_path.read_text(encoding="utf-8"))
    violations: list[str] = []
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        if _STALE_COMPARE_IMPORT.search(src):
            violations.append(f"  cell {i}: {src.strip()[:120]!r}")

    assert not violations, (
        f"Notebook {notebook_path.name} contains stale 'import compare' "
        f"(should be 'import compare_profile_to_definition'):\n" + "\n".join(violations)
    )
