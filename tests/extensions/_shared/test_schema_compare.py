"""Tests for orthograph.extensions._shared -- schema comparison."""

from typing import Optional

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.extensions._shared import (
    IntrospectedSchema,
    PropertyInfo,
    compare_schema,
    db_type_to_python,
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


class Directed(RelationshipModel):
    __label__ = "DIRECTED"
    __source_type__ = Person
    __target_type__ = Movie


@pytest.fixture()
def filmography_model() -> GraphDataModel:
    return GraphDataModel(
        name="Filmography",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )


def _complete_props() -> tuple[
    dict[str, list[PropertyInfo]], dict[str, list[PropertyInfo]]
]:
    """Return node_properties and rel_properties that match the model."""
    node_props = {
        "Person": [
            PropertyInfo("name", ["String"], True, 100, 100),
            PropertyInfo("age", ["Long"], True, 100, 100),
            PropertyInfo("email", ["String"], False, 50, 100),
        ],
        "Movie": [
            PropertyInfo("title", ["String"], True, 50, 50),
            PropertyInfo("year", ["Long"], True, 50, 50),
        ],
    }
    rel_props = {
        "ACTED_IN": [
            PropertyInfo("role", ["String"], True, 200, 200),
        ],
    }
    return node_props, rel_props


# --- IntrospectedSchema construction tests ---


def test_introspected_schema_creation():
    schema = IntrospectedSchema(
        node_labels={"Person", "Movie"},
        relationship_types={"ACTED_IN"},
    )
    assert schema.node_labels == {"Person", "Movie"}
    assert schema.relationship_types == {"ACTED_IN"}
    assert schema.node_properties == {}
    assert schema.rel_properties == {}


def test_property_info_creation():
    p = PropertyInfo(
        name="age",
        types=["Long"],
        mandatory=True,
        observation_count=100,
        total_count=100,
    )
    assert p.name == "age"
    assert p.mandatory is True
    assert p.observation_count == 100


# --- compare_schema tests ---


def test_compare_schema_perfect_match(filmography_model: GraphDataModel):
    np, rp = _complete_props()
    introspected = IntrospectedSchema(
        node_labels={"Person", "Movie"},
        relationship_types={"ACTED_IN", "DIRECTED"},
        node_properties=np,
        rel_properties=rp,
    )
    result = compare_schema(introspected, filmography_model)
    assert result.is_valid, [str(e) for e in result.errors]


def test_compare_schema_missing_node_label(
    filmography_model: GraphDataModel,
):
    introspected = IntrospectedSchema(
        node_labels={"Person"},
        relationship_types={"ACTED_IN", "DIRECTED"},
    )
    result = compare_schema(introspected, filmography_model)
    assert not result.is_valid
    assert any(e.code == "DB_MISSING_NODE_LABEL" for e in result.errors)


def test_compare_schema_unexpected_node_label(
    filmography_model: GraphDataModel,
):
    np, rp = _complete_props()
    introspected = IntrospectedSchema(
        node_labels={"Person", "Movie", "City"},
        relationship_types={"ACTED_IN", "DIRECTED"},
        node_properties=np,
        rel_properties=rp,
    )
    result = compare_schema(introspected, filmography_model)
    assert result.is_valid
    assert any(e.code == "DB_UNEXPECTED_NODE_LABEL" for e in result.warnings)


def test_compare_schema_missing_rel_type(
    filmography_model: GraphDataModel,
):
    introspected = IntrospectedSchema(
        node_labels={"Person", "Movie"},
        relationship_types={"ACTED_IN"},
    )
    result = compare_schema(introspected, filmography_model)
    assert not result.is_valid
    assert any(e.code == "DB_MISSING_REL_TYPE" for e in result.errors)


def test_compare_schema_unexpected_rel_type(
    filmography_model: GraphDataModel,
):
    np, rp = _complete_props()
    introspected = IntrospectedSchema(
        node_labels={"Person", "Movie"},
        relationship_types={"ACTED_IN", "DIRECTED", "FRIEND_OF"},
        node_properties=np,
        rel_properties=rp,
    )
    result = compare_schema(introspected, filmography_model)
    assert result.is_valid
    assert any(e.code == "DB_UNEXPECTED_REL_TYPE" for e in result.warnings)


def test_compare_schema_missing_required_property(
    filmography_model: GraphDataModel,
):
    introspected = IntrospectedSchema(
        node_labels={"Person", "Movie"},
        relationship_types={"ACTED_IN", "DIRECTED"},
        node_properties={
            "Person": [
                PropertyInfo("name", ["String"], True, 100, 100),
                # age is missing entirely from DB
            ],
        },
    )
    result = compare_schema(introspected, filmography_model)
    assert not result.is_valid
    assert any(e.code == "DB_MISSING_PROPERTY" for e in result.errors)


def test_compare_schema_property_type_mismatch(
    filmography_model: GraphDataModel,
):
    introspected = IntrospectedSchema(
        node_labels={"Person", "Movie"},
        relationship_types={"ACTED_IN", "DIRECTED"},
        node_properties={
            "Person": [
                PropertyInfo("name", ["String"], True, 100, 100),
                PropertyInfo("age", ["String"], True, 100, 100),
            ],
        },
    )
    result = compare_schema(introspected, filmography_model)
    assert not result.is_valid
    assert any(e.code == "DB_PROPERTY_TYPE_MISMATCH" for e in result.errors)


def test_compare_schema_optional_mismatch(
    filmography_model: GraphDataModel,
):
    np, rp = _complete_props()
    np["Person"] = [
        PropertyInfo("name", ["String"], False, 80, 100),
        PropertyInfo("age", ["Long"], True, 100, 100),
        PropertyInfo("email", ["String"], False, 50, 100),
    ]
    introspected = IntrospectedSchema(
        node_labels={"Person", "Movie"},
        relationship_types={"ACTED_IN", "DIRECTED"},
        node_properties=np,
        rel_properties=rp,
    )
    result = compare_schema(introspected, filmography_model)
    assert result.is_valid
    assert any(e.code == "DB_PROPERTY_OPTIONAL_MISMATCH" for e in result.warnings)


def test_compare_schema_unexpected_property(
    filmography_model: GraphDataModel,
):
    np, rp = _complete_props()
    np["Person"].append(PropertyInfo("phone", ["String"], False, 30, 100))
    introspected = IntrospectedSchema(
        node_labels={"Person", "Movie"},
        relationship_types={"ACTED_IN", "DIRECTED"},
        node_properties=np,
        rel_properties=rp,
    )
    result = compare_schema(introspected, filmography_model)
    assert result.is_valid
    assert any(e.code == "DB_UNEXPECTED_PROPERTY" for e in result.issues)


# --- DB type mapping tests ---


def test_db_type_maps_to_python_type():
    assert db_type_to_python("String") is str
    assert db_type_to_python("Long") is int
    assert db_type_to_python("Integer") is int
    assert db_type_to_python("Int") is int
    assert db_type_to_python("Double") is float
    assert db_type_to_python("Float") is float
    assert db_type_to_python("Boolean") is bool


def test_db_type_unknown_returns_none():
    assert db_type_to_python("Point3D") is None
    assert db_type_to_python("Duration") is None
