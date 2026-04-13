"""Tests for orthograph.core.validator -- GraphValidator engine."""

from typing import Any, Optional

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.core.types import Cardinality, CardinalitySpec
from orthograph.core.validator import GraphValidator


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


class City(NodeModel):
    __label__ = "City"
    __uid_field__ = "name"

    name: str


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_type__ = Person
    __target_type__ = Movie
    __source_cardinality__ = Cardinality.ZERO_OR_MORE
    __target_cardinality__ = Cardinality.ZERO_OR_MORE

    role: str


class Directed(RelationshipModel):
    __label__ = "DIRECTED"
    __source_type__ = Person
    __target_type__ = Movie


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_type__ = Person
    __target_type__ = City
    __source_cardinality__ = Cardinality.ONE
    __target_cardinality__ = Cardinality.ZERO_OR_MORE


@pytest.fixture()
def filmography_model() -> GraphDataModel:
    return GraphDataModel(
        name="Filmography",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )


@pytest.fixture()
def full_model() -> GraphDataModel:
    return GraphDataModel(
        name="Full",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn, Directed, LivesIn],
    )


# --- Validate nodes tests ---


def test_validate_nodes_valid_dict(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([{"__label__": "Person", "name": "Alice", "age": 30}])
    assert result.is_valid


def test_validate_nodes_valid_model_instance(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    p = Person(name="Alice", age=30)
    result = v.validate_nodes([p])
    assert result.is_valid


def test_validate_nodes_unknown_label(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([{"__label__": "City", "name": "London"}])
    assert not result.is_valid
    assert result.errors[0].code == "UNKNOWN_NODE_LABEL"


def test_validate_nodes_missing_label_field(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([{"name": "Alice", "age": 30}])
    assert not result.is_valid
    assert result.errors[0].code == "MISSING_LABEL"


def test_validate_nodes_missing_required_property(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([{"__label__": "Person", "name": "Alice"}])
    assert not result.is_valid
    assert any(e.code == "PROPERTY_VALIDATION_ERROR" for e in result.errors)


def test_validate_nodes_wrong_property_type(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes(
        [
            {
                "__label__": "Person",
                "name": "Alice",
                "age": "not_an_int",
            }
        ]
    )
    assert not result.is_valid


def test_validate_nodes_optional_property_can_be_absent(
    filmography_model: GraphDataModel,
):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([{"__label__": "Person", "name": "Alice", "age": 30}])
    assert result.is_valid


def test_validate_nodes_optional_property_can_be_none(
    filmography_model: GraphDataModel,
):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes(
        [
            {
                "__label__": "Person",
                "name": "Alice",
                "age": 30,
                "email": None,
            }
        ]
    )
    assert result.is_valid


def test_validate_nodes_extra_properties_rejected(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes(
        [
            {
                "__label__": "Person",
                "name": "Alice",
                "age": 30,
                "unknown_prop": "value",
            }
        ]
    )
    assert not result.is_valid
    assert any(e.code == "EXTRA_PROPERTIES" for e in result.errors)


def test_validate_nodes_multiple(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes(
        [
            {"__label__": "Person", "name": "Alice", "age": 30},
            {
                "__label__": "Movie",
                "title": "Inception",
                "year": 2010,
            },
            {"__label__": "Person", "name": "Bob", "age": 25},
        ]
    )
    assert result.is_valid


def test_validate_nodes_collects_all_errors(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes(
        [
            {"__label__": "Unknown"},
            {"name": "no_label"},
            {"__label__": "Person", "name": "Alice"},  # missing age
        ]
    )
    assert not result.is_valid
    assert len(result.errors) >= 3


# --- Validate relationships tests ---


def test_validate_relationships_valid_dict(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Movie", "title": "Inception", "year": 2010},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Alice",
            "__target_uid__": "Inception",
            "role": "Cobb",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid


def test_validate_relationships_unknown_label(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    rels: list[dict[str, Any]] = [
        {
            "__label__": "FAKE_REL",
            "__source_uid__": "a",
            "__target_uid__": "b",
        },
    ]
    result = v.validate_relationships(rels)
    assert not result.is_valid
    assert result.errors[0].code == "UNKNOWN_RELATIONSHIP_LABEL"


def test_validate_relationships_missing_label(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    rels: list[dict[str, Any]] = [
        {"__source_uid__": "a", "__target_uid__": "b"},
    ]
    result = v.validate_relationships(rels)
    assert not result.is_valid
    assert result.errors[0].code == "MISSING_LABEL"


def test_validate_relationships_missing_required_property(
    filmography_model: GraphDataModel,
):
    v = GraphValidator(filmography_model)
    rels: list[dict[str, Any]] = [
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Alice",
            "__target_uid__": "Inception",
            # missing 'role'
        },
    ]
    result = v.validate_relationships(rels)
    assert not result.is_valid


def test_validate_relationships_missing_source_uid(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    rels: list[dict[str, Any]] = [
        {
            "__label__": "DIRECTED",
            "__target_uid__": "Inception",
        },
    ]
    result = v.validate_relationships(rels)
    assert not result.is_valid
    assert any(e.code == "MISSING_ENDPOINT" for e in result.errors)


def test_validate_relationships_missing_target_uid(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    rels: list[dict[str, Any]] = [
        {
            "__label__": "DIRECTED",
            "__source_uid__": "Alice",
        },
    ]
    result = v.validate_relationships(rels)
    assert not result.is_valid
    assert any(e.code == "MISSING_ENDPOINT" for e in result.errors)


# --- Validate referential integrity tests ---


def test_validate_referential_integrity_valid(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Movie", "title": "Inception", "year": 2010},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Alice",
            "__target_uid__": "Inception",
            "role": "Cobb",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid


def test_validate_referential_integrity_dangling_source(
    filmography_model: GraphDataModel,
):
    v = GraphValidator(filmography_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Movie", "title": "Inception", "year": 2010},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Ghost",
            "__target_uid__": "Inception",
            "role": "Cobb",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert not result.is_valid
    assert any(e.code == "DANGLING_REFERENCE" for e in result.errors)


def test_validate_referential_integrity_dangling_target(
    filmography_model: GraphDataModel,
):
    v = GraphValidator(filmography_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Alice",
            "__target_uid__": "Ghost",
            "role": "Cobb",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert not result.is_valid
    assert any(e.code == "DANGLING_REFERENCE" for e in result.errors)


def test_validate_referential_integrity_wrong_source_type(
    filmography_model: GraphDataModel,
):
    v = GraphValidator(filmography_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Movie", "title": "A", "year": 2020},
        {"__label__": "Movie", "title": "B", "year": 2021},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "A",  # Movie, not Person
            "__target_uid__": "B",
            "role": "X",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert not result.is_valid
    assert any(e.code == "WRONG_ENDPOINT_TYPE" for e in result.errors)


# --- Validate cardinality tests ---


def test_validate_cardinality_satisfied(full_model: GraphDataModel):
    v = GraphValidator(full_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "City", "name": "London"},
        {"__label__": "Movie", "title": "Inception", "year": 2010},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "LIVES_IN",
            "__source_uid__": "Alice",
            "__target_uid__": "London",
        },
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Alice",
            "__target_uid__": "Inception",
            "role": "Cobb",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid


def test_validate_cardinality_violation_too_few(full_model: GraphDataModel):
    v = GraphValidator(full_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Movie", "title": "Inception", "year": 2010},
    ]
    # Person has no LIVES_IN but cardinality requires exactly ONE
    rels: list[dict[str, Any]] = [
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Alice",
            "__target_uid__": "Inception",
            "role": "Cobb",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert not result.is_valid
    assert any(e.code == "CARDINALITY_VIOLATION" for e in result.errors)


def test_validate_cardinality_violation_too_many():
    class StrictPerson(NodeModel):
        __label__ = "StrictPerson"
        __uid_field__ = "name"
        name: str

    class StrictMovie(NodeModel):
        __label__ = "StrictMovie"
        __uid_field__ = "title"
        title: str

    class OnlyOneRole(RelationshipModel):
        __label__ = "ONLY_ONE"
        __source_type__ = StrictPerson
        __target_type__ = StrictMovie
        __source_cardinality__ = CardinalitySpec(min=0, max=1)

    model = GraphDataModel(
        name="Strict",
        node_types=[StrictPerson, StrictMovie],
        relationship_types=[OnlyOneRole],
    )

    v = GraphValidator(model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "StrictPerson", "name": "Alice"},
        {"__label__": "StrictMovie", "title": "A"},
        {"__label__": "StrictMovie", "title": "B"},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "ONLY_ONE",
            "__source_uid__": "Alice",
            "__target_uid__": "A",
        },
        {
            "__label__": "ONLY_ONE",
            "__source_uid__": "Alice",
            "__target_uid__": "B",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert not result.is_valid
    assert any(e.code == "CARDINALITY_VIOLATION" for e in result.errors)


# --- Validate entity presence tests ---


def test_validate_entity_presence_required_node_type_missing():
    class Req(NodeModel):
        __label__ = "Req"
        __optional__ = False
        val: str

    class Opt(NodeModel):
        __label__ = "Opt"
        val: str  # default __optional__ = True

    model = GraphDataModel(
        name="Test",
        node_types=[Req, Opt],
        relationship_types=[],
    )
    v = GraphValidator(model)
    # No nodes at all -- Req is required, Opt is optional
    result = v.validate(nodes=[], relationships=[])
    assert not result.is_valid
    assert any(e.code == "MISSING_REQUIRED_TYPE" for e in result.errors)


def test_validate_entity_presence_optional_node_type_can_be_missing():
    class Opt(NodeModel):
        __label__ = "Opt"
        __optional__ = True
        val: str

    model = GraphDataModel(
        name="Test",
        node_types=[Opt],
        relationship_types=[],
    )
    v = GraphValidator(model)
    result = v.validate(nodes=[], relationships=[])
    assert result.is_valid


def test_validate_entity_presence_required_relationship_type_missing():
    class N(NodeModel):
        __label__ = "N"
        __optional__ = True
        val: str

    class ReqRel(RelationshipModel):
        __label__ = "REQ_REL"
        __source_type__ = N
        __target_type__ = N
        __optional__ = False

    model = GraphDataModel(
        name="Test",
        node_types=[N],
        relationship_types=[ReqRel],
    )
    v = GraphValidator(model)
    result = v.validate(nodes=[], relationships=[])
    assert not result.is_valid
    assert any(e.code == "MISSING_REQUIRED_TYPE" for e in result.errors)


# --- Validate full graph tests ---


def test_validate_full_graph_complete_valid(filmography_model: GraphDataModel):
    v = GraphValidator(filmography_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {
            "__label__": "Person",
            "name": "Bob",
            "age": 25,
            "email": "bob@x.com",
        },
        {"__label__": "Movie", "title": "Inception", "year": 2010},
        {"__label__": "Movie", "title": "Tenet", "year": 2020},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Alice",
            "__target_uid__": "Inception",
            "role": "Cobb",
        },
        {
            "__label__": "DIRECTED",
            "__source_uid__": "Bob",
            "__target_uid__": "Tenet",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid
