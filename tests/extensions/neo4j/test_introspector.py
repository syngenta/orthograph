"""Tests for orthograph.extensions.neo4j.introspector."""

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.extensions.neo4j import Neo4jSchemaIntrospector, validate_database


# --- Fixtures ---


class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    age: int
    email: Optional[str] = None


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    year: int


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_type__ = Person
    __target_type__ = Movie
    role: str


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )


def _make_record(data: dict[str, Any]) -> MagicMock:
    """Create a mock record that supports dict() conversion."""
    record = MagicMock()
    record.__iter__ = MagicMock(return_value=iter(data.keys()))
    record.__getitem__ = MagicMock(side_effect=data.__getitem__)
    record.keys = MagicMock(return_value=list(data.keys()))
    record.values = MagicMock(return_value=list(data.values()))
    record.items = MagicMock(return_value=list(data.items()))
    # Make dict(record) work via __iter__ + __getitem__
    record.__len__ = MagicMock(return_value=len(data))
    # Support the pattern dict(record) by making it iterable over keys
    record.__contains__ = MagicMock(side_effect=data.__contains__)

    # The introspector uses dict(record), so we need to make sure
    # the mock supports that. The simplest approach: monkeypatch __iter__
    # to yield keys and __getitem__ to return values.
    def _dict_method():
        return data.copy()

    record.__dict_copy__ = _dict_method
    return record


def _mock_execute_query(rows: list[dict[str, Any]], keys: list[str] | None = None):
    """Build a return value for driver.execute_query(...)."""
    records = [_make_record(row) for row in rows]
    if keys is None:
        keys = list(rows[0].keys()) if rows else []
    return (records, MagicMock(), keys)


# --- has_apoc tests ---


def test_neo4j_has_apoc_true():
    driver = MagicMock()
    driver.execute_query.return_value = _mock_execute_query([{"cnt": 5}], ["cnt"])
    introspector = Neo4jSchemaIntrospector(driver)
    assert introspector.has_apoc() is True


def test_neo4j_has_apoc_false():
    driver = MagicMock()
    driver.execute_query.return_value = _mock_execute_query([{"cnt": 0}], ["cnt"])
    introspector = Neo4jSchemaIntrospector(driver)
    assert introspector.has_apoc() is False


# --- _get_labels tests ---


def test_neo4j_get_labels():
    driver = MagicMock()
    driver.execute_query.return_value = _mock_execute_query(
        [{"label": "Person"}, {"label": "Movie"}], ["label"]
    )
    introspector = Neo4jSchemaIntrospector(driver)
    labels = introspector._get_labels()
    assert labels == {"Person", "Movie"}


# --- _get_rel_types tests ---


def test_neo4j_get_rel_types():
    driver = MagicMock()
    driver.execute_query.return_value = _mock_execute_query(
        [{"relationshipType": "ACTED_IN"}], ["relationshipType"]
    )
    introspector = Neo4jSchemaIntrospector(driver)
    rel_types = introspector._get_rel_types()
    assert rel_types == {"ACTED_IN"}


# --- introspect with APOC ---


def test_neo4j_introspect_with_apoc():
    driver = MagicMock()

    call_count = 0
    responses = [
        # _get_labels
        _mock_execute_query([{"label": "Person"}, {"label": "Movie"}], ["label"]),
        # _get_rel_types
        _mock_execute_query([{"relationshipType": "ACTED_IN"}], ["relationshipType"]),
        # _get_constraints
        _mock_execute_query(
            [
                {
                    "name": "constraint_person_name",
                    "type": "UNIQUENESS",
                    "entityType": "NODE",
                    "labelsOrTypes": ["Person"],
                    "properties": ["name"],
                    "propertyType": None,
                }
            ],
            [
                "name",
                "type",
                "entityType",
                "labelsOrTypes",
                "properties",
                "propertyType",
            ],
        ),
        # has_apoc
        _mock_execute_query([{"cnt": 3}], ["cnt"]),
        # _get_node_properties_apoc
        _mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "nodeType": ":`Person`",
                    "propertyName": "age",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "nodeType": ":`Movie`",
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
            ],
            [
                "nodeType",
                "propertyName",
                "propertyTypes",
                "mandatory",
                "propertyObservations",
                "totalObservations",
            ],
        ),
        # _get_rel_properties_apoc
        _mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 200,
                    "totalObservations": 200,
                },
            ],
            [
                "relType",
                "propertyName",
                "propertyTypes",
                "mandatory",
                "propertyObservations",
                "totalObservations",
            ],
        ),
    ]

    def side_effect(*args, **kwargs):
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    introspector = Neo4jSchemaIntrospector(driver)
    schema = introspector.introspect()

    assert schema.node_labels == {"Person", "Movie"}
    assert schema.relationship_types == {"ACTED_IN"}
    assert "Person" in schema.node_properties
    assert "Movie" in schema.node_properties
    assert "ACTED_IN" in schema.rel_properties
    assert len(schema.constraints) == 1
    assert schema.constraints[0].constraint_type == "UNIQUENESS"

    # Verify node properties
    person_props = {p.name: p for p in schema.node_properties["Person"]}
    assert "name" in person_props
    assert "age" in person_props
    assert person_props["name"].mandatory is True
    assert person_props["name"].types == ["String"]


# --- introspect without APOC (fallback) ---


def test_neo4j_introspect_without_apoc():
    driver = MagicMock()

    call_count = 0
    responses = [
        # _get_labels
        _mock_execute_query([{"label": "Person"}, {"label": "Movie"}], ["label"]),
        # _get_rel_types
        _mock_execute_query([{"relationshipType": "ACTED_IN"}], ["relationshipType"]),
        # _get_constraints
        _mock_execute_query([], []),
        # has_apoc
        _mock_execute_query([{"cnt": 0}], ["cnt"]),
        # _get_node_properties_fallback for "Movie" (sorted order)
        _mock_execute_query(
            [
                {"key": "title", "cnt": 50, "total": 50, "mandatory": True},
                {"key": "year", "cnt": 50, "total": 50, "mandatory": True},
            ],
            ["key", "cnt", "total", "mandatory"],
        ),
        # _get_node_properties_fallback for "Person" (sorted order)
        _mock_execute_query(
            [
                {"key": "name", "cnt": 100, "total": 100, "mandatory": True},
                {"key": "age", "cnt": 100, "total": 100, "mandatory": True},
            ],
            ["key", "cnt", "total", "mandatory"],
        ),
    ]

    def side_effect(*args, **kwargs):
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    introspector = Neo4jSchemaIntrospector(driver)
    schema = introspector.introspect()

    assert schema.node_labels == {"Person", "Movie"}
    assert schema.relationship_types == {"ACTED_IN"}
    assert "Person" in schema.node_properties
    assert "Movie" in schema.node_properties
    # Fallback doesn't populate rel_properties
    assert schema.rel_properties == {}

    # Verify fallback properties have empty types
    person_props = {p.name: p for p in schema.node_properties["Person"]}
    assert person_props["name"].types == []
    assert person_props["name"].mandatory is True
    assert person_props["name"].observation_count == 100


# --- validate_database end-to-end ---


def test_neo4j_validate_database(model: GraphDataModel):
    driver = MagicMock()

    call_count = 0
    responses = [
        # _get_labels
        _mock_execute_query([{"label": "Person"}, {"label": "Movie"}], ["label"]),
        # _get_rel_types
        _mock_execute_query([{"relationshipType": "ACTED_IN"}], ["relationshipType"]),
        # _get_constraints
        _mock_execute_query([], []),
        # has_apoc
        _mock_execute_query([{"cnt": 1}], ["cnt"]),
        # _get_node_properties_apoc
        _mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "nodeType": ":`Person`",
                    "propertyName": "age",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "nodeType": ":`Person`",
                    "propertyName": "email",
                    "propertyTypes": ["String"],
                    "mandatory": False,
                    "propertyObservations": 50,
                    "totalObservations": 100,
                },
                {
                    "nodeType": ":`Movie`",
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
                {
                    "nodeType": ":`Movie`",
                    "propertyName": "year",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
            ],
            [
                "nodeType",
                "propertyName",
                "propertyTypes",
                "mandatory",
                "propertyObservations",
                "totalObservations",
            ],
        ),
        # _get_rel_properties_apoc
        _mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 200,
                    "totalObservations": 200,
                },
            ],
            [
                "relType",
                "propertyName",
                "propertyTypes",
                "mandatory",
                "propertyObservations",
                "totalObservations",
            ],
        ),
    ]

    def side_effect(*args, **kwargs):
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    result = validate_database(driver, model)
    assert result.is_valid, [str(e) for e in result.errors]
