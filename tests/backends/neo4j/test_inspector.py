"""Tests for orthograph.backends.neo4j.inspector."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from orthograph.backends.neo4j.inspector import Neo4jInspector, validate_database
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


# --- APOC auto-detection ---


def test_neo4j_detect_apoc_true() -> None:
    """_detect_apoc returns True when apoc.meta procedures are present."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query(
        [{"cnt": 5}],
        ["cnt"],
    )
    inspector = Neo4jInspector()
    assert inspector._detect_apoc(driver) is True


def test_neo4j_detect_apoc_false() -> None:
    """_detect_apoc returns False when no apoc.meta procedures are present."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query(
        [{"cnt": 0}],
        ["cnt"],
    )
    inspector = Neo4jInspector()
    assert inspector._detect_apoc(driver) is False


def test_neo4j_use_apoc_flag_skips_detection() -> None:
    """use_apoc=True skips the SHOW PROCEDURES detection call."""
    driver = MagicMock()
    # Every query returns empty rows; inspect() runs end-to-end with no DB data.
    driver.execute_query.return_value = mock_execute_query([], [])
    inspector = Neo4jInspector(use_apoc=True)
    inspector.inspect(driver)
    # No SHOW PROCEDURES (APOC auto-detect) call was made.
    for call in driver.execute_query.call_args_list:
        assert "SHOW PROCEDURES" not in str(call)


# --- Labels ---


def test_neo4j_inspect_labels() -> None:
    driver = MagicMock()

    call_count = 0
    responses = [
        # _detect_apoc (SHOW PROCEDURES)
        mock_execute_query([{"cnt": 3}], ["cnt"]),
        # node_labels
        mock_execute_query(
            [{"label": "Person"}, {"label": "Movie"}],
            ["label"],
        ),
        # rel_types
        mock_execute_query(
            [{"relationshipType": "ACTED_IN"}],
            ["relationshipType"],
        ),
        # node_properties for Movie (sorted)
        mock_execute_query(
            [
                {
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
            ],
        ),
        # node_properties for Person (sorted)
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
            ],
        ),
        # rel_properties for ACTED_IN
        mock_execute_query(
            [
                {
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 200,
                    "totalObservations": 200,
                },
            ],
        ),
        # endpoint_labels for ACTED_IN (queried first to identify sources)
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person (confirmed source label)
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

    inspector = Neo4jInspector()
    profile = inspector.inspect(driver)

    assert profile.node_labels == {"Person", "Movie"}
    assert profile.relationship_types == {"ACTED_IN"}


# --- Full profile ---


def test_neo4j_inspect_produces_profile() -> None:
    driver = MagicMock()

    call_count = 0
    responses = [
        # _detect_apoc (APOC available)
        mock_execute_query([{"cnt": 3}], ["cnt"]),
        # node_labels
        mock_execute_query(
            [{"label": "Person"}, {"label": "Movie"}],
            ["label"],
        ),
        # rel_types
        mock_execute_query(
            [{"relationshipType": "ACTED_IN"}],
            ["relationshipType"],
        ),
        # node_properties for Movie
        mock_execute_query(
            [
                {
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
                {
                    "propertyName": "year",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
            ],
        ),
        # node_properties for Person
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "propertyName": "age",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "propertyName": "email",
                    "propertyTypes": ["String"],
                    "mandatory": False,
                    "propertyObservations": 50,
                    "totalObservations": 100,
                },
            ],
        ),
        # rel_properties for ACTED_IN
        mock_execute_query(
            [
                {
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 200,
                    "totalObservations": 200,
                },
            ],
        ),
        # endpoint_labels for ACTED_IN (queried first to identify sources)
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person (confirmed source label)
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
        mock_execute_query(
            [
                {
                    "name": "constraint_person_name",
                    "type": "UNIQUENESS",
                    "entityType": "NODE",
                    "labelsOrTypes": ["Person"],
                    "properties": ["name"],
                    "propertyType": None,
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

    inspector = Neo4jInspector()
    profile = inspector.inspect(driver)

    assert profile.source == "neo4j"
    assert profile.node_labels == {"Person", "Movie"}
    assert profile.relationship_types == {"ACTED_IN"}

    # Check node profiles
    person = profile.node_type_profiles["Person"]
    assert "name" in person.property_profiles
    assert "age" in person.property_profiles
    assert person.property_profiles["name"].observed_types == ["String"]
    assert person.property_profiles["name"].is_required is True

    movie = profile.node_type_profiles["Movie"]
    assert "title" in movie.property_profiles
    assert "year" in movie.property_profiles

    # Check rel profile
    acted_in = profile.rel_type_profiles["ACTED_IN"]
    assert "role" in acted_in.property_profiles
    assert acted_in.cardinality_stats is not None
    assert acted_in.cardinality_stats.sample_size == 50

    # endpoint labels populated
    assert acted_in.source_labels == {"Person"}
    assert acted_in.target_labels == {"Movie"}

    # Constraints
    assert len(profile.constraints) == 1
    assert profile.constraints[0].constraint_type == "UNIQUENESS"


# --- validate_database ---


def test_neo4j_validate_database(graph_definition: GraphDefinition) -> None:
    driver = MagicMock()

    call_count = 0
    responses = [
        # _detect_apoc
        mock_execute_query([{"cnt": 1}], ["cnt"]),
        # node_labels
        mock_execute_query(
            [{"label": "Person"}, {"label": "Movie"}],
            ["label"],
        ),
        # rel_types
        mock_execute_query(
            [{"relationshipType": "ACTED_IN"}],
            ["relationshipType"],
        ),
        # node_properties for Movie
        mock_execute_query(
            [
                {
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
                {
                    "propertyName": "year",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
            ],
        ),
        # node_properties for Person
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "propertyName": "age",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "propertyName": "email",
                    "propertyTypes": ["String"],
                    "mandatory": False,
                    "propertyObservations": 50,
                    "totalObservations": 100,
                },
            ],
        ),
        # rel_properties for ACTED_IN
        mock_execute_query(
            [
                {
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 200,
                    "totalObservations": 200,
                },
            ],
        ),
        # endpoint_labels for ACTED_IN (queried first to identify sources)
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person (confirmed source label)
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
