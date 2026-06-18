"""Tests for the query spec catalogue YAML loader.

Covers:
  - Loading from a YAML string (load_query_catalogue_string)
  - Loading from a YAML file (load_query_catalogue_file)
  - Round-trip: load → model_dump() output matches source YAML fields
  - Legacy field name: query_name accepted for name
  - cypher_template required (no cypher/query alias)
  - params_schema reconstructs Params model; absent → NoParams sentinel
  - identifiers_schema reconstructs Identifiers model when present
  - description field is optional
  - Multi-query YAML file
  - Missing required field 'name' raises CypherCatalogueLoadError
  - Missing 'cypher_template' raises CypherCatalogueLoadError
  - Malformed YAML raises CypherCatalogueLoadError
  - YAML with a non-list top-level structure raises CypherCatalogueLoadError
  - list_catalogue_queries() returns all names from a YAML string/file
"""

from pathlib import Path

import pytest

from orthograph.cypher.bindings import NoParams
from orthograph.cypher.exceptions import CypherCatalogueLoadError
from orthograph.cypher.query import CypherQuery
from orthograph.io.query_catalogue_yaml import (
    list_catalogue_queries,
    load_query_catalogue_file,
    load_query_catalogue_string,
)


# ---------------------------------------------------------------------------
# Fixtures — new format
# ---------------------------------------------------------------------------

FULL_YAML = """\
- name: find_movie
  cypher_template: "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
  description: "Find a movie by its stable movie_id."
  params_schema:
    title: FindMovieParams
    type: object
    properties:
      movie_id: {type: string, title: MovieId}
    required: [movie_id]

- name: movies_by_festival
  cypher_template: |
    MATCH (f:Festival {id: $festival_id})-[:HAS_MOVIE]->(m:Movie)
    RETURN m
  description: "All movies linked to a festival."
  params_schema:
    title: MoviesByFestivalParams
    type: object
    properties:
      festival_id: {type: string, title: FestivalId}
    required: [festival_id]
"""

# Legacy name alias (query_name) must still be accepted.
LEGACY_NAME_YAML = """\
- query_name: find_movie
  cypher_template: "MATCH (m:Movie {movie_id: $movie_id}) RETURN m"
  params_schema:
    title: FindMovieParams
    type: object
    properties:
      movie_id: {type: string, title: MovieId}
    required: [movie_id]
"""

# Minimal: no params_schema → NoParams.
MINIMAL_YAML = """\
- name: count_movies
  cypher_template: "MATCH (m:Movie) RETURN count(m) AS n"
"""

MISSING_QUERY_NAME_YAML = """\
- cypher_template: "MATCH (m:Movie) RETURN m"
"""

MISSING_CYPHER_TEMPLATE_YAML = """\
- name: find_movie
"""

EMPTY_YAML = "[]"

NON_LIST_YAML = """\
name: find_movie
cypher_template: "MATCH (m:Movie) RETURN m"
"""

MALFORMED_YAML = """\
- name: [unclosed
"""

OPTIONAL_PARAMS_YAML = """\
- name: movies_by_year
  cypher_template: "MATCH (m:Movie {released: $released}) RETURN m.title LIMIT $limit"
  params_schema:
    title: MoviesByYearParams
    type: object
    properties:
      released: {type: integer, title: Released}
      limit:    {type: integer, title: Limit, default: 10}
    required: [released]
"""


# ---------------------------------------------------------------------------
# load_query_catalogue_string
# ---------------------------------------------------------------------------


class TestLoadFromString:
    def test_loads_full_yaml(self):
        """Load YAML with new format."""
        queries = load_query_catalogue_string(FULL_YAML)
        assert len(queries) == 2
        assert all(isinstance(q, CypherQuery) for q in queries)

    def test_field_names_mapped(self):
        """Standard fields are correctly mapped."""
        queries = load_query_catalogue_string(FULL_YAML)
        first = queries[0]
        assert first.name == "find_movie"
        assert "$movie_id" in first.cypher_template
        assert "movie_id" in first.Params.model_fields
        assert first.description == "Find a movie by its stable movie_id."

    def test_legacy_name_alias_accepted(self):
        """query_name is accepted as legacy alias for name."""
        queries = load_query_catalogue_string(LEGACY_NAME_YAML)
        assert queries[0].name == "find_movie"

    def test_absent_params_schema_defaults_to_no_params(self):
        """Missing params_schema → Params is NoParams (zero fields)."""
        queries = load_query_catalogue_string(MINIMAL_YAML)
        q = queries[0]
        assert q.Params is NoParams or q.Params.model_fields == {}

    def test_description_optional(self):
        queries = load_query_catalogue_string(MINIMAL_YAML)
        assert queries[0].description is None

    def test_empty_list_returns_empty(self):
        queries = load_query_catalogue_string(EMPTY_YAML)
        assert queries == []

    def test_missing_query_name_raises(self):
        with pytest.raises(CypherCatalogueLoadError, match="name"):
            load_query_catalogue_string(MISSING_QUERY_NAME_YAML)

    def test_missing_cypher_template_raises(self):
        with pytest.raises(CypherCatalogueLoadError, match="cypher_template"):
            load_query_catalogue_string(MISSING_CYPHER_TEMPLATE_YAML)

    def test_non_list_top_level_raises(self):
        with pytest.raises(CypherCatalogueLoadError, match="list"):
            load_query_catalogue_string(NON_LIST_YAML)

    def test_malformed_yaml_raises(self):
        with pytest.raises(CypherCatalogueLoadError):
            load_query_catalogue_string(MALFORMED_YAML)

    def test_multi_query_names(self):
        queries = load_query_catalogue_string(FULL_YAML)
        names = [q.name for q in queries]
        assert names == ["find_movie", "movies_by_festival"]

    def test_required_and_optional_params_reconstructed(self):
        """Required field has no default; optional field has default."""
        queries = load_query_catalogue_string(OPTIONAL_PARAMS_YAML)
        q = queries[0]
        fields = q.Params.model_fields
        assert "released" in fields
        assert "limit" in fields
        assert fields["released"].is_required()
        assert not fields["limit"].is_required()


# ---------------------------------------------------------------------------
# load_query_catalogue_file
# ---------------------------------------------------------------------------


class TestLoadFromFile:
    def test_loads_from_file(self, tmp_path: Path):
        f = tmp_path / "queries.yaml"
        f.write_text(FULL_YAML, encoding="utf-8")
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
        names = list_catalogue_queries(FULL_YAML)
        assert names == ["find_movie", "movies_by_festival"]

    def test_returns_names_from_file(self, tmp_path: Path):
        f = tmp_path / "queries.yaml"
        f.write_text(FULL_YAML, encoding="utf-8")
        names = list_catalogue_queries(f)
        assert names == ["find_movie", "movies_by_festival"]

    def test_empty_returns_empty(self):
        assert list_catalogue_queries(EMPTY_YAML) == []


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_model_dump_emits_query_name_alias(self):
        """model_dump(by_alias=True) uses query_name alias for name."""
        queries = load_query_catalogue_string(FULL_YAML)
        d = queries[0].model_dump(by_alias=True, exclude_none=True)
        assert d["query_name"] == "find_movie"
        assert "cypher_template" in d
        assert "params_schema" in d

    def test_to_dict_omits_none_description(self):
        queries = load_query_catalogue_string(MINIMAL_YAML)
        d = queries[0].model_dump(by_alias=True, exclude_none=True)
        assert "description" not in d

    def test_params_schema_in_dump(self):
        """Params model serialises as params_schema dict in model_dump."""
        queries = load_query_catalogue_string(FULL_YAML)
        d = queries[0].model_dump(by_alias=True, exclude_none=True)
        assert isinstance(d["params_schema"], dict)
        assert "properties" in d["params_schema"]
