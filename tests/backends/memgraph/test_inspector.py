"""Tests for orthograph.backends.memgraph.inspector."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from orthograph.backends.memgraph.inspector import MemgraphInspector, validate_database
from orthograph.graph_definition.graph_definition import GraphDefinition
from tests.backends.conftest import mock_execute_query
from tests.fixtures.conftest import ActedIn, Movie, Person


# --- Fixtures ---


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )


# --- inspect produces profile ---


def test_memgraph_inspect_produces_profile() -> None:
    driver = MagicMock()

    call_count = 0
    responses = [
        # node_properties
        mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "age",
                    "propertyTypes": ["Int"],
                },
                {
                    "nodeType": ":`Movie`",
                    "nodeLabels": ["Movie"],
                    "mandatory": True,
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                },
            ],
        ),
        # rel_properties
        mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "mandatory": True,
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                },
            ],
        ),
        # endpoint_labels for ACTED_IN (queried before cardinality)
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person
        mock_execute_query(
            [
                {
                    "min_degree": 1,
                    "max_degree": 3,
                    "avg_degree": 2.0,
                    "sample_size": 10,
                },
            ],
        ),
        # constraints
        mock_execute_query(
            [
                {
                    "constraint type": "UNIQUE",
                    "entity type": "NODE",
                    "label": "Person",
                    "properties": ["name"],
                },
            ],
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    inspector = MemgraphInspector()
    profile = inspector.inspect(driver)

    assert profile.source == "memgraph"
    assert profile.node_labels == {"Person", "Movie"}
    assert profile.relationship_types == {"ACTED_IN"}

    # Check node profiles
    person = profile.node_type_profiles["Person"]
    assert "name" in person.property_profiles
    assert "age" in person.property_profiles
    assert person.property_profiles["name"].observed_types == ["String"]

    movie = profile.node_type_profiles["Movie"]
    assert "title" in movie.property_profiles

    # Check rel profile
    acted_in = profile.rel_type_profiles["ACTED_IN"]
    assert "role" in acted_in.property_profiles

    # source/target labels populated
    assert acted_in.source_labels == {"Person"}
    assert acted_in.target_labels == {"Movie"}
    assert acted_in.cardinality_stats is not None
    assert acted_in.cardinality_stats.sample_size == 10

    # Constraints
    assert len(profile.constraints) == 1
    assert profile.constraints[0].constraint_type == "UNIQUE"
    assert profile.constraints[0].labels == ["Person"]


# --- validate_database ---


def test_memgraph_validate_database(graph_definition: GraphDefinition) -> None:
    driver = MagicMock()

    call_count = 0
    responses = [
        # node_properties
        mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "age",
                    "propertyTypes": ["Int"],
                },
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": False,
                    "propertyName": "email",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Movie`",
                    "nodeLabels": ["Movie"],
                    "mandatory": True,
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Movie`",
                    "nodeLabels": ["Movie"],
                    "mandatory": True,
                    "propertyName": "year",
                    "propertyTypes": ["Int"],
                },
            ],
        ),
        # rel_properties
        mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "mandatory": True,
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                },
            ],
        ),
        # endpoint_labels for ACTED_IN (parity query — before constraints)
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person
        mock_execute_query(
            [
                {
                    "min_degree": 0,
                    "max_degree": 5,
                    "avg_degree": 2.0,
                    "sample_size": 50,
                },
            ],
        ),
        # constraints
        mock_execute_query([], []),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    result = validate_database(driver, graph_definition)
    assert result.is_valid, [str(e) for e in result.errors]
