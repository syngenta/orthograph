"""Tests for the query spec catalogue YAML loader.

Covers:
  - Loading from a YAML string (load_query_catalogue_string)
  - Loading from a YAML file (load_query_catalogue_file)
  - Round-trip: load → model_dump() output matches source YAML fields
  - Legacy field names: query_name / query field names accepted
  - Standard names: name / cypher field names also accepted
  - query_args_required / query_args_optional defaults to [] when absent
  - description field is optional
  - Multi-query YAML file
  - Missing required field 'query_name' or 'query' raises CypherCatalogueLoadError
  - Malformed YAML raises CypherCatalogueLoadError
  - YAML with a non-list top-level structure raises CypherCatalogueLoadError
  - list_catalogue_queries() returns all names from a YAML string/file
"""

from pathlib import Path

import pytest

from orthograph.cypher.exceptions import CypherCatalogueLoadError
from orthograph.cypher.query_spec import CypherQuerySpec
from orthograph.io.query_catalogue_yaml import (
    list_catalogue_queries,
    load_query_catalogue_file,
    load_query_catalogue_string,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOCTIS_YAML = """\
- query_name: find_movie
  query: "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
  query_args_required: [movie_id]
  query_args_optional: []
  description: "Find a movie by its stable movie_id."

- query_name: movies_by_festival
  query: |
    MATCH (f:Festival {id: $festival_id})-[:HAS_MOVIE]->(m:Movie)
    RETURN m
  query_args_required: [festival_id]
  description: "All movies linked to a festival."
"""

ORTHOGRAPH_ALIAS_YAML = """\
- name: find_movie
  cypher: "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
  query_args_required: [movie_id]
"""

MINIMAL_YAML = """\
- query_name: count_movies
  query: "MATCH (m:Movie) RETURN count(m) AS n"
"""

MISSING_QUERY_NAME_YAML = """\
- query: "MATCH (m:Movie) RETURN m"
"""

MISSING_QUERY_YAML = """\
- query_name: find_movie
"""

EMPTY_YAML = "[]"

NON_LIST_YAML = """\
query_name: find_movie
query: "MATCH (m:Movie) RETURN m"
"""

MALFORMED_YAML = """\
- query_name: [unclosed
"""


# ---------------------------------------------------------------------------
# load_query_catalogue_string
# ---------------------------------------------------------------------------


class TestLoadFromString:
    def test_loads_legacy_yaml(self):
        """Load YAML with legacy field names."""
        queries = load_query_catalogue_string(NOCTIS_YAML)
        assert len(queries) == 2
        assert all(isinstance(q, CypherQuerySpec) for q in queries)

    def test_legacy_field_names_mapped(self):
        """Legacy field names query_name and query are correctly mapped."""
        queries = load_query_catalogue_string(NOCTIS_YAML)
        first = queries[0]
        assert first.name == "find_movie"
        assert "$movie_id" in first.cypher
        assert first.query_args_required == ["movie_id"]
        assert first.query_args_optional == []
        assert first.description == "Find a movie by its stable movie_id."

    def test_standard_field_names(self):
        """Standard field names name and cypher are accepted."""
        queries = load_query_catalogue_string(ORTHOGRAPH_ALIAS_YAML)
        assert len(queries) == 1
        assert queries[0].name == "find_movie"
        assert "$movie_id" in queries[0].cypher

    def test_missing_query_args_default_to_empty(self):
        queries = load_query_catalogue_string(MINIMAL_YAML)
        q = queries[0]
        assert q.query_args_required == []
        assert q.query_args_optional == []

    def test_description_optional(self):
        queries = load_query_catalogue_string(MINIMAL_YAML)
        assert queries[0].description is None

    def test_empty_list_returns_empty(self):
        queries = load_query_catalogue_string(EMPTY_YAML)
        assert queries == []

    def test_missing_query_name_raises(self):
        with pytest.raises(CypherCatalogueLoadError, match="query_name"):
            load_query_catalogue_string(MISSING_QUERY_NAME_YAML)

    def test_missing_query_body_raises(self):
        with pytest.raises(CypherCatalogueLoadError, match="query"):
            load_query_catalogue_string(MISSING_QUERY_YAML)

    def test_non_list_top_level_raises(self):
        with pytest.raises(CypherCatalogueLoadError, match="list"):
            load_query_catalogue_string(NON_LIST_YAML)

    def test_malformed_yaml_raises(self):
        with pytest.raises(CypherCatalogueLoadError):
            load_query_catalogue_string(MALFORMED_YAML)

    def test_multi_query_names(self):
        queries = load_query_catalogue_string(NOCTIS_YAML)
        names = [q.name for q in queries]
        assert names == ["find_movie", "movies_by_festival"]


# ---------------------------------------------------------------------------
# load_query_catalogue_file
# ---------------------------------------------------------------------------


class TestLoadFromFile:
    def test_loads_from_file(self, tmp_path: Path):
        f = tmp_path / "queries.yaml"
        f.write_text(NOCTIS_YAML, encoding="utf-8")
        queries = load_query_catalogue_file(f)
        assert len(queries) == 2

    def test_missing_file_raises_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_query_catalogue_file(tmp_path / "nonexistent.yaml")

    def test_string_path_accepted(self, tmp_path: Path):
        f = tmp_path / "queries.yaml"
        f.write_text(MINIMAL_YAML, encoding="utf-8")
        queries = load_query_catalogue_file(str(f))
        assert len(queries) == 1


# ---------------------------------------------------------------------------
# list_catalogue_queries
# ---------------------------------------------------------------------------


class TestListQueries:
    def test_returns_names_from_string(self):
        names = list_catalogue_queries(NOCTIS_YAML)
        assert names == ["find_movie", "movies_by_festival"]

    def test_returns_names_from_file(self, tmp_path: Path):
        f = tmp_path / "queries.yaml"
        f.write_text(NOCTIS_YAML, encoding="utf-8")
        names = list_catalogue_queries(f)
        assert names == ["find_movie", "movies_by_festival"]

    def test_empty_returns_empty(self):
        assert list_catalogue_queries(EMPTY_YAML) == []


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_to_dict_preserves_legacy_field_names(self):
        """Round-trip preserves legacy field names for compatibility."""
        queries = load_query_catalogue_string(NOCTIS_YAML)
        d = queries[0].model_dump(by_alias=True, exclude_none=True)
        assert d["query_name"] == "find_movie"
        assert "query" in d
        assert d["query_args_required"] == ["movie_id"]
        assert d["query_args_optional"] == []
        assert d["description"] == "Find a movie by its stable movie_id."

    def test_to_dict_omits_none_description(self):
        queries = load_query_catalogue_string(MINIMAL_YAML)
        d = queries[0].model_dump(by_alias=True, exclude_none=True)
        assert "description" not in d
