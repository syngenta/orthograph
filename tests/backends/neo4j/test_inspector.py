"""Tests for orthograph.backends.neo4j.inspector."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from orthograph.backends.neo4j.inspector import (
    Neo4jInspectionStrategy,
    Neo4jInspector,
    validate_database,
)
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


# --- Strategy auto-detection ---


def test_neo4j_detect_strategy_apoc() -> None:
    """_detect_strategy returns APOC when apoc.meta procedures are present."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query(
        [{"cnt": 5}],
        ["cnt"],
    )
    inspector = Neo4jInspector()
    assert inspector._detect_strategy(driver) is Neo4jInspectionStrategy.APOC


def test_neo4j_detect_strategy_schema() -> None:
    """_detect_strategy → SCHEMA when apoc.meta absent but db.schema present."""
    driver = MagicMock()

    call_count = 0
    responses = [
        # apoc.meta probe → absent
        mock_execute_query([{"cnt": 0}], ["cnt"]),
        # db.schema.nodeTypeProperties probe → present
        mock_execute_query([{"cnt": 1}], ["cnt"]),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect
    inspector = Neo4jInspector()
    assert inspector._detect_strategy(driver) is Neo4jInspectionStrategy.SCHEMA


def test_neo4j_detect_strategy_cypher() -> None:
    """_detect_strategy returns CYPHER when neither apoc.meta nor db.schema present."""
    driver = MagicMock()

    call_count = 0
    responses = [
        # apoc.meta probe → absent
        mock_execute_query([{"cnt": 0}], ["cnt"]),
        # db.schema.nodeTypeProperties probe → absent
        mock_execute_query([{"cnt": 0}], ["cnt"]),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect
    inspector = Neo4jInspector()
    assert inspector._detect_strategy(driver) is Neo4jInspectionStrategy.CYPHER


def test_neo4j_explicit_strategy_skips_detection() -> None:
    """An explicit strategy skips the SHOW PROCEDURES detection calls."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query([], [])
    inspector = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER)
    inspector.inspect(driver)
    for call in driver.execute_query.call_args_list:
        assert "SHOW PROCEDURES" not in str(call)


# --- use_apoc deprecation shim ---


def test_use_apoc_true_emits_deprecation_and_maps_to_apoc() -> None:
    """use_apoc=True emits DeprecationWarning and behaves as strategy=APOC."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query([], [])
    with pytest.warns(DeprecationWarning):
        inspector = Neo4jInspector(use_apoc=True)
    inspector.inspect(driver)
    # APOC path skips the SHOW PROCEDURES auto-detect probe.
    for call in driver.execute_query.call_args_list:
        assert "SHOW PROCEDURES" not in str(call)


def test_use_apoc_false_emits_deprecation_and_maps_to_cypher() -> None:
    """use_apoc=False emits DeprecationWarning and behaves as strategy=CYPHER."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query([], [])
    with pytest.warns(DeprecationWarning):
        inspector = Neo4jInspector(use_apoc=False)
    inspector.inspect(driver)
    for call in driver.execute_query.call_args_list:
        assert "SHOW PROCEDURES" not in str(call)


def test_use_apoc_none_emits_deprecation_and_maps_to_auto() -> None:
    """use_apoc=None (explicitly passed) emits DeprecationWarning and auto-detects."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query([{"cnt": 5}], ["cnt"])
    with pytest.warns(DeprecationWarning):
        Neo4jInspector(use_apoc=None)


def test_no_args_does_not_warn() -> None:
    """Constructing with no args (default auto) must not emit a warning."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        Neo4jInspector()  # must not raise


# --- SCHEMA strategy merge (counts from scan + types from db.schema) ---


def _schema_strategy_responses() -> list[Any]:
    """Ordered driver responses for a SCHEMA-strategy inspect() run.

    One node label (Person) with two scanned properties (name: complete,
    email: partial) and one rel type (ACTED_IN) with one property (role).
    db.schema reports types for name/email/role; it also reports a property
    (nickname) NOT seen by the scan, which must be ignored (the scan is the
    source of truth for which properties exist + their counts).
    """
    return [
        # _detect_strategy: apoc.meta absent
        mock_execute_query([{"cnt": 0}], ["cnt"]),
        # _detect_strategy: db.schema present
        mock_execute_query([{"cnt": 1}], ["cnt"]),
        # node_labels
        mock_execute_query([{"label": "Person"}], ["label"]),
        # rel_types
        mock_execute_query([{"relationshipType": "ACTED_IN"}], ["relationshipType"]),
        # bulk db.schema node types
        mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                },
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "propertyName": "email",
                    "propertyTypes": ["String"],
                    "mandatory": False,
                },
            ],
        ),
        # bulk db.schema rel types
        mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": False,
                },
            ],
        ),
        # CypherNodePropertiesQuery for Person (true counts, types=[])
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": [],
                    "mandatory": True,
                    "propertyObservations": 10,
                    "totalObservations": 10,
                },
                {
                    "propertyName": "email",
                    "propertyTypes": [],
                    "mandatory": False,
                    "propertyObservations": 4,
                    "totalObservations": 10,
                },
            ],
        ),
        # CypherRelPropertiesQuery for ACTED_IN (true counts, types=[])
        mock_execute_query(
            [
                {
                    "propertyName": "role",
                    "propertyTypes": [],
                    "mandatory": True,
                    "propertyObservations": 7,
                    "totalObservations": 7,
                },
            ],
        ),
        # endpoint_labels for ACTED_IN
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person
        mock_execute_query(
            [
                {
                    "min_degree": 1,
                    "max_degree": 2,
                    "avg_degree": 1.5,
                    "sample_size": 10,
                },
            ],
        ),
        # constraints
        mock_execute_query([], []),
    ]


def test_schema_strategy_merges_counts_and_types() -> None:
    """SCHEMA: counts come from the scan, observed_types from db.schema.*."""
    driver = MagicMock()
    call_count = 0
    responses = _schema_strategy_responses()

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver)

    person = profile.node_type_profiles["Person"]
    # Counts come from the pure-Cypher scan (true completeness).
    name = person.property_profiles["name"]
    assert name.present_count == 10
    assert name.total_count == 10
    # Types come from db.schema.*.
    assert name.observed_types == ["String"]

    email = person.property_profiles["email"]
    assert email.present_count == 4
    assert email.total_count == 10
    assert email.observed_types == ["String"]

    # Rel: counts from scan, types from db.schema.
    acted_in = profile.rel_type_profiles["ACTED_IN"]
    role = acted_in.property_profiles["role"]
    assert role.present_count == 7
    assert role.total_count == 7
    assert role.observed_types == ["String"]


def test_schema_strategy_scan_only_property_keeps_empty_types() -> None:
    """A property seen by the scan but not by db.schema keeps observed_types=[]."""
    driver = MagicMock()
    call_count = 0
    responses = _schema_strategy_responses()
    # Drop the db.schema 'email' type row: only 'name' has a db.schema type now.
    responses[4] = mock_execute_query(
        [
            {
                "nodeType": ":`Person`",
                "nodeLabels": ["Person"],
                "propertyName": "name",
                "propertyTypes": ["String"],
                "mandatory": True,
            },
        ],
    )

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver)
    person = profile.node_type_profiles["Person"]
    # name still gets its type; email (scan-only) keeps [].
    assert person.property_profiles["name"].observed_types == ["String"]
    assert person.property_profiles["email"].observed_types == []
    # Counts unaffected for both.
    assert person.property_profiles["email"].present_count == 4
    assert person.property_profiles["email"].total_count == 10


def test_apoc_strategy_regression_lock() -> None:
    """APOC strategy: output is the existing APOC behaviour, unchanged.

    apoc.meta present → APOC selected; no db.schema query is issued and the
    profile carries APOC-derived counts and types.
    """
    driver = MagicMock()
    call_count = 0
    responses = [
        # _detect_strategy: apoc.meta present → APOC (no db.schema probe)
        mock_execute_query([{"cnt": 3}], ["cnt"]),
        # node_labels
        mock_execute_query([{"label": "Person"}], ["label"]),
        # rel_types
        mock_execute_query([], []),
        # apoc node_properties for Person
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
        # constraints
        mock_execute_query([], []),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver)
    name = profile.node_type_profiles["Person"].property_profiles["name"]
    assert name.present_count == 100
    assert name.observed_types == ["String"]
    # No db.schema query was issued on the APOC path.
    for call in driver.execute_query.call_args_list:
        assert "db.schema" not in str(call)


def test_apoc_null_property_row_is_skipped() -> None:
    """APOC's null-property sentinel row (property-less type) is skipped.

    Regression lock for the propertyName=None bug: APOC emits one row with
    propertyName=None for a label/rel-type that has no properties; the builder
    must skip it rather than raise.
    """
    driver = MagicMock()
    call_count = 0
    responses = [
        # _detect_strategy: apoc.meta present
        mock_execute_query([{"cnt": 3}], ["cnt"]),
        # node_labels
        mock_execute_query([{"label": "Empty"}], ["label"]),
        # rel_types
        mock_execute_query([], []),
        # apoc node_properties for Empty → only a null-property sentinel row
        mock_execute_query(
            [
                {
                    "propertyName": None,
                    "propertyTypes": None,
                    "mandatory": False,
                    "propertyObservations": 0,
                    "totalObservations": 0,
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

    profile = Neo4jInspector().inspect(driver)
    # The label exists but has no properties (sentinel skipped, no error).
    assert profile.node_type_profiles["Empty"].property_profiles == {}


# --- Labels ---


def test_neo4j_inspect_labels() -> None:
    driver = MagicMock()

    call_count = 0
    responses = [
        # _detect_strategy (SHOW PROCEDURES → apoc.meta present → APOC)
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
        # _detect_strategy (apoc.meta present → APOC)
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
        # _detect_strategy (apoc.meta present → APOC)
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
