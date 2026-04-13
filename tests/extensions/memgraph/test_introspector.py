"""Tests for orthograph.extensions.memgraph.introspector."""

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.extensions.memgraph import (
    MemgraphSchemaIntrospector,
    validate_database,
)


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
    record.__len__ = MagicMock(return_value=len(data))
    record.__contains__ = MagicMock(side_effect=data.__contains__)
    return record


def _mock_execute_query(rows: list[dict[str, Any]], keys: list[str] | None = None):
    """Build a return value for driver.execute_query(...)."""
    records = [_make_record(row) for row in rows]
    if keys is None:
        keys = list(rows[0].keys()) if rows else []
    return (records, MagicMock(), keys)


# --- _get_node_properties tests ---


def test_memgraph_get_node_properties():
    driver = MagicMock()
    driver.execute_query.return_value = _mock_execute_query(
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
        ["nodeType", "nodeLabels", "mandatory", "propertyName", "propertyTypes"],
    )
    introspector = MemgraphSchemaIntrospector(driver)
    labels, props = introspector._get_node_properties()

    assert labels == {"Person", "Movie"}
    assert "Person" in props
    assert "Movie" in props
    person_props = {p.name: p for p in props["Person"]}
    assert "name" in person_props
    assert "age" in person_props
    assert person_props["name"].mandatory is True
    assert person_props["name"].types == ["String"]


# --- _get_rel_properties tests ---


def test_memgraph_get_rel_properties():
    driver = MagicMock()
    driver.execute_query.return_value = _mock_execute_query(
        [
            {
                "relType": ":`ACTED_IN`",
                "mandatory": True,
                "propertyName": "role",
                "propertyTypes": ["String"],
            },
        ],
        ["relType", "mandatory", "propertyName", "propertyTypes"],
    )
    introspector = MemgraphSchemaIntrospector(driver)
    rel_types, props = introspector._get_rel_properties()

    assert rel_types == {"ACTED_IN"}
    assert "ACTED_IN" in props
    assert len(props["ACTED_IN"]) == 1
    assert props["ACTED_IN"][0].name == "role"
    assert props["ACTED_IN"][0].mandatory is True


# --- full introspect ---


def test_memgraph_introspect():
    driver = MagicMock()

    call_count = 0
    responses = [
        # _get_node_properties
        _mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Movie`",
                    "nodeLabels": ["Movie"],
                    "mandatory": True,
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                },
            ],
            ["nodeType", "nodeLabels", "mandatory", "propertyName", "propertyTypes"],
        ),
        # _get_rel_properties
        _mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "mandatory": True,
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                },
            ],
            ["relType", "mandatory", "propertyName", "propertyTypes"],
        ),
        # _get_constraints
        _mock_execute_query(
            [
                {
                    "constraint type": "UNIQUE",
                    "entity type": "NODE",
                    "label": "Person",
                    "properties": ["name"],
                },
            ],
            ["constraint type", "entity type", "label", "properties"],
        ),
    ]

    def side_effect(*args, **kwargs):
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    introspector = MemgraphSchemaIntrospector(driver)
    schema = introspector.introspect()

    assert schema.node_labels == {"Person", "Movie"}
    assert schema.relationship_types == {"ACTED_IN"}
    assert "Person" in schema.node_properties
    assert "Movie" in schema.node_properties
    assert "ACTED_IN" in schema.rel_properties
    assert len(schema.constraints) == 1
    assert schema.constraints[0].constraint_type == "UNIQUE"
    assert schema.constraints[0].labels == ["Person"]


# --- validate_database end-to-end ---


def test_memgraph_validate_database(model: GraphDataModel):
    driver = MagicMock()

    call_count = 0
    responses = [
        # _get_node_properties
        _mock_execute_query(
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
            ["nodeType", "nodeLabels", "mandatory", "propertyName", "propertyTypes"],
        ),
        # _get_rel_properties
        _mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "mandatory": True,
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                },
            ],
            ["relType", "mandatory", "propertyName", "propertyTypes"],
        ),
        # _get_constraints
        _mock_execute_query([], []),
    ]

    def side_effect(*args, **kwargs):
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    result = validate_database(driver, model)
    assert result.is_valid, [str(e) for e in result.errors]
