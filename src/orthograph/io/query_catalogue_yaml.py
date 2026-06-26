"""YAML loader for Cypher query catalogues.

Loads a YAML file or string containing a list of query definitions and
returns a list of :class:`~orthograph.cypher.query.CypherQuery` instances.

YAML format
-----------
The top-level structure must be a YAML list. Each entry is a mapping with the
following fields:

**Required:**

+--------------------+-------------------------------------------------------+
| Field              | Description                                           |
+====================+=======================================================+
| ``query_id``       | Unique query identifier.                              |
+--------------------+-------------------------------------------------------+
| ``cypher_template``| Raw Cypher string with ``$param`` and ``<<id>>``      |
|                    | placeholders. No aliases accepted.                    |
+--------------------+-------------------------------------------------------+
| ``params_schema``  | JSON-Schema object describing ``$value`` parameters.  |
|                    | Pass ``{type: object, properties: {}}`` for zero-arg  |
|                    | queries (equivalent to ``NoParams``).                 |
+--------------------+-------------------------------------------------------+

**Optional:**

* ``identifiers_schema`` — JSON-Schema object for ``<<name>>`` identifier
  slots. Omit entirely when no identifier splicing is needed.
* ``description``        — human-readable string.

Example::

    - query_id: find_movie
      cypher_template: "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
      description: "Find a movie by its stable movie_id."
      params_schema:
        title: FindMovieParams
        type: object
        properties:
          movie_id: {type: string, title: MovieId}
        required: [movie_id]

    - query_id: movies_by_year
      cypher_template: >-
        MATCH (m:Movie {released: $released})
        RETURN m.title LIMIT $limit
      params_schema:
        title: MoviesByYearParams
        type: object
        properties:
          released: {type: integer, title: Released}
          limit:    {type: integer, title: Limit, default: 10}
        required: [released]

    - query_id: count_movies
      cypher_template: "MATCH (m:Movie) RETURN count(m) AS total"
      params_schema:
        type: object
        properties: {}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from orthograph.cypher.bindings import NoIdentifiers, NoParams
from orthograph.cypher.exceptions import CypherCatalogueLoadError
from orthograph.cypher.query import CypherQuery
from orthograph.cypher.schema_codec import model_from_json_schema


def load_query_catalogue_string(
    content: str,
) -> list[CypherQuery]:
    """Load query specs from a YAML string.

    Parameters
    ----------
    content:
        A YAML string whose top-level structure is a list of query mappings.

    Returns
    -------
    list[CypherQuery]
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
) -> list[CypherQuery]:
    """Load query specs from a YAML file.

    Parameters
    ----------
    path:
        Path to the YAML file (``str`` or ``pathlib.Path``).

    Returns
    -------
    list[CypherQuery]
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
    return [q.query_id for q in queries]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_queries(data: Any) -> list[CypherQuery]:
    """Build CypherQuery instances from parsed YAML data."""
    if data is None:
        # safe_load("[]") returns [] but safe_load("") returns None
        return []

    if not isinstance(data, list):
        raise CypherCatalogueLoadError(
            "A query catalogue YAML file must have a list as its "
            f"top-level structure, got {type(data).__name__!r}. "
            "Wrap your query entries in a YAML list (start each entry with '- ')."
        )

    queries: list[CypherQuery] = []
    for index, entry in enumerate(data):
        queries.append(_build_one(entry, index))
    return queries


def _build_one(entry: Any, index: int) -> CypherQuery:
    """Parse a single YAML mapping into a CypherQuery."""
    if not isinstance(entry, dict):
        raise CypherCatalogueLoadError(
            f"Entry at index {index} is not a mapping (got {type(entry).__name__!r}). "
            "Each query entry must be a YAML mapping."
        )

    # query_id is required. Accept legacy aliases: query_name (old), name (older)
    query_id = entry.get("query_id") or entry.get("query_name") or entry.get("name")
    cypher_template = entry.get("cypher_template")

    if not query_id:
        raise CypherCatalogueLoadError(
            f"Entry at index {index} is missing the required field 'query_id' "
            "(also checked legacy aliases 'query_name', 'name')."
        )
    if not cypher_template:
        raise CypherCatalogueLoadError(
            f"Entry at index {index} (query_id={query_id!r}) is missing the required "
            "field 'cypher_template'."
        )

    # params_schema is required; absent or empty → NoParams.
    params_schema: dict[str, Any] | None = entry.get("params_schema")
    if params_schema:
        params_schema_model = model_from_json_schema(
            params_schema, model_name=params_schema.get("title")
        )
    else:
        params_schema_model = NoParams

    # identifiers_schema is optional; absent → NoIdentifiers.
    identifiers_schema: dict[str, Any] | None = entry.get("identifiers_schema")
    if identifiers_schema:
        identifiers_schema_model = model_from_json_schema(
            identifiers_schema, model_name=identifiers_schema.get("title")
        )
    else:
        identifiers_schema_model = NoIdentifiers

    description: str | None = entry.get("description")

    return CypherQuery(
        query_id=query_id,
        cypher_template=cypher_template,
        description=description,
        params_schema=params_schema_model,
        identifiers_schema=identifiers_schema_model,
    )
