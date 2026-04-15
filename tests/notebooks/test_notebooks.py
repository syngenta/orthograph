"""
Notebook regression tests using pytest-nbval.

Run with:
    pytest tests/notebooks/test_notebooks.py --nbval-lax

Use --nbval-lax to ignore output differences (matplotlib figures, etc.)
while still catching cell execution errors.

Add new notebooks to NOTEBOOKS to include them in CI.
Notebook 07 (neo4j_end_to_end) is excluded because it requires a live
Neo4j database connection.
"""

from pathlib import Path

import pytest


# Two parents up from tests/notebooks/test_notebooks.py -> project root
NOTEBOOKS_DIR = Path(__file__).resolve().parent.parent.parent / "notebooks"

# All notebooks safe to run without external services.
# Notebook 07 (neo4j_end_to_end) is excluded -- it requires a live Neo4j instance.
NOTEBOOKS = [
    NOTEBOOKS_DIR / "01_defining_a_graph_data_model.ipynb",
    NOTEBOOKS_DIR / "02_validating_graph_data.ipynb",
    NOTEBOOKS_DIR / "03_optionality_and_cardinality.ipynb",
    NOTEBOOKS_DIR / "04_yaml_configuration.ipynb",
    NOTEBOOKS_DIR / "05_cypher_query_generation.ipynb",
    NOTEBOOKS_DIR / "06_networkx_inspection_and_validation.ipynb",
    NOTEBOOKS_DIR / "08_visualization.ipynb",
]


@pytest.mark.parametrize(
    "notebook_path",
    [pytest.param(nb, id=nb.name) for nb in NOTEBOOKS],
)
def test_notebook_exists(notebook_path: Path) -> None:
    """Confirm the notebook file is present before nbval attempts to run it."""
    assert notebook_path.exists(), (
        f"Notebook not found: {notebook_path}\n"
        "Add the notebook or remove it from NOTEBOOKS in this file."
    )
