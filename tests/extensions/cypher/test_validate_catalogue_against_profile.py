"""Tests for validate_catalogue_against_profile.

This combines the two existing validation passes into one merged result:

  * ``validate_catalogue(catalogue, model)``  — the queries vs the model (static)
  * ``validate_profile(profile, model)``       — the live DB shape vs the model

It takes a ``GraphProfile`` (already produced by a ``GraphInspector``), so it
never owns a driver. Both halves reuse existing functions; this only merges them.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.catalogue.registry import QueryCatalogue
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.extensions.cypher import (
    CypherReadQuery,
    validate_catalogue_against_profile,
)
from orthograph.extensions.models import GraphProfile, NodeTypeProfile, PropertyProfile


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    released: int


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(name="Film", node_types=[Movie], relationship_types=[])


def _matching_profile() -> GraphProfile:
    """A profile whose shape matches the Movie model (no profile errors)."""
    return GraphProfile(
        source="test",
        node_type_profiles={
            "Movie": NodeTypeProfile(
                label="Movie",
                count=10,
                property_profiles={
                    "title": PropertyProfile(
                        name="title",
                        present_count=10,
                        total_count=10,
                        observed_types=["String"],
                    ),
                    "released": PropertyProfile(
                        name="released",
                        present_count=10,
                        total_count=10,
                        observed_types=["Long"],
                    ),
                },
            )
        },
    )


class ReleasedYearParams(BaseModel):
    released: int


class TitleParams(BaseModel):
    title: str


class MoviesByYear(CypherReadQuery[ReleasedYearParams, Movie]):
    Params = ReleasedYearParams
    Output = Movie
    name = "movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title, m.released"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(title=raw["m.title"], released=raw["m.released"])


class MoviesByBadLabel(CypherReadQuery[TitleParams, Movie]):
    Params = TitleParams
    Output = Movie
    name = "movies_by_bad_label"
    cypher_template = "MATCH (f:Film {title: $title}) RETURN f.title"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(title=raw["f.title"], released=0)


def test_import() -> None:
    """validate_catalogue_against_profile imports from the cypher extension."""
    from orthograph.extensions.cypher import (  # noqa: F401
        validate_catalogue_against_profile,
    )


def test_clean_query_and_matching_profile_is_valid(model: GraphDataModel) -> None:
    """Good queries + a matching DB profile => no errors."""
    cat = QueryCatalogue()
    cat.register_read(MoviesByYear())

    result = validate_catalogue_against_profile(cat, _matching_profile(), model)

    assert result.is_valid


def test_query_error_surfaces(model: GraphDataModel) -> None:
    """A model-violating query surfaces an ERROR even when the profile matches."""
    cat = QueryCatalogue()
    cat.register_read(MoviesByBadLabel())

    result = validate_catalogue_against_profile(cat, _matching_profile(), model)

    assert not result.is_valid
    assert any("Film" in i.message for i in result.errors)


def test_profile_mismatch_surfaces(model: GraphDataModel) -> None:
    """A DB profile missing a modelled label surfaces a profile ERROR."""
    cat = QueryCatalogue()
    cat.register_read(MoviesByYear())  # clean query

    empty_profile = GraphProfile(source="test", node_type_profiles={})
    result = validate_catalogue_against_profile(cat, empty_profile, model)

    assert not result.is_valid
    # The missing-node-label check comes from validate_profile, not the query pass.
    assert any(i.code == "MISSING_NODE_LABEL" for i in result.errors)


def test_both_passes_merge(model: GraphDataModel) -> None:
    """Query errors and profile errors are merged into one result."""
    cat = QueryCatalogue()
    cat.register_read(MoviesByBadLabel())  # query ERROR

    empty_profile = GraphProfile(source="test", node_type_profiles={})  # profile ERROR
    result = validate_catalogue_against_profile(cat, empty_profile, model)

    assert any("Film" in i.message for i in result.errors)  # from query pass
    assert any(i.code == "MISSING_NODE_LABEL" for i in result.errors)  # from profile
