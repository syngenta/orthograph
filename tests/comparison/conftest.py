"""Shared test fixtures for comparison tests."""

import pytest

# Import shared fixtures and models from centralized location
from tests.fixtures.conftest import (
    ActedIn,
    City,
    Directed,
    LivesIn,
    Movie,
    Person,
)


@pytest.fixture()
def filmography_model():
    """GraphDefinition with Person, Movie,
    City nodes and ActedIn, LivesIn, Directed relationships."""
    from orthograph.graph_definition.graph_definition import GraphDefinition

    return GraphDefinition(
        name="Filmography",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn, LivesIn, Directed],
    )
