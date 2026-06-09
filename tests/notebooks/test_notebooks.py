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

from pathlib import Path

import pytest


NOTEBOOKS_DIR = Path(__file__).resolve().parent.parent.parent / "notebooks"

# All notebooks in the project, grouped by section.
ALL_NOTEBOOKS = [
    # 01 -- Core
    NOTEBOOKS_DIR / "01.01_defining_a_graph_data_model.ipynb",
    NOTEBOOKS_DIR / "01.02_validating_graph_data.ipynb",
    NOTEBOOKS_DIR / "01.03_optionality_and_cardinality.ipynb",
    NOTEBOOKS_DIR / "01.04_visualization.ipynb",
    # 02 -- Serialization / IO
    NOTEBOOKS_DIR / "02.01_yaml_configuration.ipynb",
    NOTEBOOKS_DIR / "02.02_cypher_query_generation.ipynb",
    # 03 -- Extensions
    NOTEBOOKS_DIR / "03.01_networkx_inspection_and_validation.ipynb",
    NOTEBOOKS_DIR / "03.02_neo4j_end_to_end.ipynb",
    NOTEBOOKS_DIR / "03.03_gqlalchemy_integration.ipynb",
    NOTEBOOKS_DIR / "03.04_gqlalchemy_database_interaction.ipynb",
    # 04 -- Query Catalogue
    NOTEBOOKS_DIR / "04.01_typed_cypher_queries.ipynb",
]


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
