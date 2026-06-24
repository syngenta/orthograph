"""Pytest configuration for notebook collection via nbval.

Controls which notebooks are collected when running:
    pytest notebooks/ --nbval-lax

Notebooks that require a live database are excluded from collection
unless the corresponding CLI flag is passed (--neo4j, --memgraph).
Those flags are registered in the root ``conftest.py``, which pytest
loads for every invocation regardless of the target directory.

Usage:
    pytest notebooks/ --nbval-lax              # CI-safe notebooks only
    pytest notebooks/ --nbval-lax --neo4j      # + Neo4j notebooks
    pytest notebooks/ --nbval-lax --memgraph   # + Memgraph notebooks
"""

from pathlib import Path


_HERE = Path(__file__).parent

# Map each DB-requiring notebook to the CLI flag that enables it.
_DB_NOTEBOOKS: dict[str, str] = {
    "03.03_cypher_query_usage.ipynb": "neo4j",
    "04.02_neo4j_backend.ipynb": "neo4j",
    "04.03_gqlalchemy_backend.ipynb": "memgraph",
    "04.06_cypher_query_definitions.ipynb": "neo4j",
}

# Notebooks that require optional UI dependencies (dash, plotly) and cannot run
# in standard CI.  Excluded from collection unconditionally unless the
# NOTEBOOKS_UI environment variable is set to "1".
_UI_NOTEBOOKS: set[str] = {
    "06.01_fastapi_integration.ipynb",
    "06.02_dash_profile_explorer.ipynb",
}


def pytest_ignore_collect(collection_path: Path, config) -> bool | None:  # noqa: ANN001
    """Ignore DB-requiring and UI notebooks unless the corresponding flag is passed."""
    if collection_path.parent != _HERE:
        return None

    name = collection_path.name

    # UI notebooks: skip unless NOTEBOOKS_UI=1 is set in the environment.
    if name in _UI_NOTEBOOKS:
        import os

        if os.environ.get("NOTEBOOKS_UI") != "1":
            return True  # Ignore this file

    if name not in _DB_NOTEBOOKS:
        return None

    required_flag = f"--{_DB_NOTEBOOKS[name]}"
    if not config.getoption(required_flag, default=False):
        return True  # Ignore this file

    return None  # Collect normally
