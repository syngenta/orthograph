"""Tests for validate_query_catalogue_against_profile.

This combines the two existing validation passes into one merged result:

  * ``validate_query_catalogue(query_catalogue, graph_definition)``
    — the queries vs the model (static)
  * ``compare(profile, graph_definition)``
    — the live DB shape vs the model

It takes a ``GraphProfile`` (already produced by a ``GraphInspector``), so it
never owns a driver. Both halves reuse existing functions; this only merges them.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.cypher.base_models import CypherReadQuery
from orthograph.cypher.validation import (
    validate_query_catalogue_against_profile,
)
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel
from orthograph.graph_profile.models import (
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
)
from orthograph.query.catalogue import QueryCatalogue


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    released: int


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(name="Film", node_types=[Movie], relationship_types=[])


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
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(**raw["m"])


class MoviesByBadLabel(CypherReadQuery[TitleParams, Movie]):
    Params = TitleParams
    Output = Movie
    name = "movies_by_bad_label"
    cypher_template = "MATCH (f:Film {title: $title}) RETURN f.title"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(title=raw["f.title"], released=0)


def test_import() -> None:
    """validate_query_catalogue_against_profile imports from the cypher extension."""
    from orthograph.cypher.validation import (  # noqa: F401
        validate_query_catalogue_against_profile,
    )


def test_clean_query_and_matching_profile_is_valid(
    graph_definition: GraphDefinition,
) -> None:
    """Good queries + a matching DB profile => no errors."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(MoviesByYear())

    result = validate_query_catalogue_against_profile(
        query_catalogue, _matching_profile(), graph_definition
    )

    assert result.is_valid


def test_query_error_surfaces(graph_definition: GraphDefinition) -> None:
    """A model-violating query surfaces an ERROR even when the profile matches."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(MoviesByBadLabel())

    result = validate_query_catalogue_against_profile(
        query_catalogue, _matching_profile(), graph_definition
    )

    assert not result.is_valid
    assert any("Film" in i.message for i in result.errors)


def test_profile_mismatch_surfaces(graph_definition: GraphDefinition) -> None:
    """A DB profile missing a modelled label surfaces a profile ERROR."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(MoviesByYear())  # clean query

    empty_profile = GraphProfile(source="test", node_type_profiles={})
    result = validate_query_catalogue_against_profile(
        query_catalogue, empty_profile, graph_definition
    )

    assert not result.is_valid
    # The missing-node-label check comes from compare, not the query pass.
    assert any(i.code == "MISSING_NODE_LABEL" for i in result.errors)


def test_both_passes_merge(graph_definition: GraphDefinition) -> None:
    """Query errors and profile errors are merged into one result."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(MoviesByBadLabel())  # query ERROR

    empty_profile = GraphProfile(source="test", node_type_profiles={})  # profile ERROR
    result = validate_query_catalogue_against_profile(
        query_catalogue, empty_profile, graph_definition
    )

    assert any("Film" in i.message for i in result.errors)  # from query pass
    assert any(i.code == "MISSING_NODE_LABEL" for i in result.errors)  # from profile
