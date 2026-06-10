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
    "03.02_neo4j_end_to_end.ipynb": "neo4j",
    "03.04_gqlalchemy_database_interaction.ipynb": "neo4j",
}


def pytest_ignore_collect(collection_path: Path, config) -> bool | None:  # noqa: ANN001
    """Ignore DB-requiring notebooks unless the CLI flag is passed."""
    if collection_path.parent != _HERE:
        return None

    name = collection_path.name
    if name not in _DB_NOTEBOOKS:
        return None

    required_flag = f"--{_DB_NOTEBOOKS[name]}"
    if not config.getoption(required_flag, default=False):
        return True  # Ignore this file

    return None  # Collect normally
