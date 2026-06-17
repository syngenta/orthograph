"""YAML loader for Cypher query spec catalogues.

Loads a YAML file or string containing a list of query definitions and
returns a list of :class:`~orthograph.cypher.query_spec.CypherQuerySpec`
instances.

YAML format
-----------
The top-level structure must be a YAML list. Each entry is a mapping with the
following fields:

**Required** (one of two naming conventions accepted):

+-------------------------------+-------------------------------------------+
| Legacy field name             | Orthograph standard                       |
+===============================+===========================================+
| ``query_name``                | ``name``                                  |
+-------------------------------+-------------------------------------------+
| ``query``                     | ``cypher``                                |
+-------------------------------+-------------------------------------------+

Both naming conventions are accepted for flexibility:

* Existing YAML files with legacy field names load without modification.
* New files written with standard names are equally valid.

**Optional:**

* ``query_args_required`` — list of parameter names (default: ``[]``)
* ``query_args_optional`` — list of parameter names (default: ``[]``)
* ``description``         — human-readable string

Example (legacy field names)::

    - query_name: find_movie
      query: "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
      query_args_required: [movie_id]
      description: "Find a movie by its stable movie_id."

    - query_name: movies_by_festival
      query: |
        MATCH (f:Festival {id: $festival_id})-[:HAS_MOVIE]->(m:Movie)
        RETURN m
      query_args_required: [festival_id]

Example (Orthograph standard names)::

    - name: find_movie
      cypher: "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
      query_args_required: [movie_id]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from orthograph.cypher.exceptions import CypherCatalogueLoadError
from orthograph.cypher.query_spec import CypherQuerySpec


def load_query_catalogue_string(
    content: str,
) -> list[CypherQuerySpec]:
    """Load query specs from a YAML string.

    Parameters
    ----------
    content:
        A YAML string whose top-level structure is a list of query mappings.

    Returns
    -------
    list[CypherQuerySpec]
        One instance per entry in the list, in order.

    Raises
    ------
    CypherCatalogueLoadError
        If the YAML is malformed, the top-level is not a list, or any entry
        is missing a required field.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise CypherCatalogueLoadError(f"Failed to parse YAML content: {exc}") from exc

    return _build_queries(data)


def load_query_catalogue_file(
    path: str | Path,
) -> list[CypherQuerySpec]:
    """Load query specs from a YAML file.

    Parameters
    ----------
    path:
        Path to the YAML file (``str`` or ``pathlib.Path``).

    Returns
    -------
    list[CypherQuerySpec]
        One instance per entry in the file, in order.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    CypherCatalogueLoadError
        If the YAML is malformed, the top-level is not a list, or any entry
        is missing a required field.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Query catalogue file not found: {p}")
    content = p.read_text(encoding="utf-8")
    return load_query_catalogue_string(content)


def list_catalogue_queries(source: str | Path) -> list[str]:
    """Return the names of all queries in a YAML catalogue.

    Accepts either a YAML string or a file path.  Useful for discovery
    without constructing full query objects.

    Parameters
    ----------
    source:
        A YAML string or a ``pathlib.Path`` / string path to a YAML file.

    Returns
    -------
    list[str]
        Query names in the order they appear in the source.
    """
    # Check if source is a Path instance or a string pointing to an existing file.
    # Strings containing newlines can never be valid file paths (on any OS), so
    # skip the filesystem probe entirely to avoid OSError: ENAMETOOLONG on Linux
    # with Python < 3.14 (where Path.exists() does not suppress that errno).
    is_file = False
    if isinstance(source, Path):
        is_file = source.exists()
    elif isinstance(source, str):
        if "\n" not in source:
            try:
                is_file = Path(source).exists()
            except OSError:
                # Remaining edge cases (e.g. other OS-level path errors).
                is_file = False

    if is_file:
        queries = load_query_catalogue_file(source)
    else:
        # source is guaranteed to be a string if is_file is False
        yaml_content = (
            source if isinstance(source, str) else source.read_text(encoding="utf-8")
        )
        queries = load_query_catalogue_string(yaml_content)
    return [q.name for q in queries]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_queries(data: Any) -> list[CypherQuerySpec]:
    """Build CypherQuerySpec instances from parsed YAML data."""
    if data is None:
        # safe_load("[]") returns [] but safe_load("") returns None
        return []

    if not isinstance(data, list):
        raise CypherCatalogueLoadError(
            "A query catalogue YAML file must have a list as its "
            f"top-level structure, got {type(data).__name__!r}. "
            "Wrap your query entries in a YAML list (start each entry with '- ')."
        )

    queries: list[CypherQuerySpec] = []
    for index, entry in enumerate(data):
        queries.append(_build_one(entry, index))
    return queries


def _build_one(entry: Any, index: int) -> CypherQuerySpec:
    """Parse a single YAML mapping into a CypherQuerySpec."""
    if not isinstance(entry, dict):
        raise CypherCatalogueLoadError(
            f"Entry at index {index} is not a mapping (got {type(entry).__name__!r}). "
            "Each query entry must be a YAML mapping."
        )

    # Accept both legacy field names and Orthograph standard names.
    name = entry.get("query_name") or entry.get("name")
    cypher = entry.get("query") or entry.get("cypher")

    if not name:
        raise CypherCatalogueLoadError(
            f"Entry at index {index} is missing a required field. "
            "Provide either 'query_name' (legacy) or 'name' (standard)."
        )
    if not cypher:
        raise CypherCatalogueLoadError(
            f"Entry at index {index} (query_name={name!r}) is missing a required "
            "field. Provide either 'query' (legacy) or 'cypher' (standard)."
        )

    query_args_required: list[str] = list(entry.get("query_args_required") or [])
    query_args_optional: list[str] = list(entry.get("query_args_optional") or [])
    description: str | None = entry.get("description")

    return CypherQuerySpec(
        name=name,
        cypher=cypher,
        query_args_required=query_args_required,
        query_args_optional=query_args_optional,
        description=description,
    )
