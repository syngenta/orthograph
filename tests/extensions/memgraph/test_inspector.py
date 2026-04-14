"""Tests for orthograph.extensions.memgraph.inspector."""

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.extensions.memgraph import MemgraphInspector, validate_database

from .conftest import mock_execute_query


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

    inspector = MemgraphInspector(driver)
    profile = inspector.inspect()

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

    # Constraints
    assert len(profile.constraints) == 1
    assert profile.constraints[0].constraint_type == "UNIQUE"
    assert profile.constraints[0].labels == ["Person"]


# --- validate_database ---


def test_memgraph_validate_database(model: GraphDataModel) -> None:
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
        # constraints
        mock_execute_query([], []),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    result = validate_database(driver, model)
    assert result.is_valid, [str(e) for e in result.errors]
