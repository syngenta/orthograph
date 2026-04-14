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


def test_validate_cardinality_zero_or_more_accepts_zero():
    """ZERO_OR_MORE on source side must accept nodes with 0 relationships."""

    class ZPerson(NodeModel):
        __label__ = "ZPerson"
        __uid_field__ = "name"
        name: str

    class ZProject(NodeModel):
        __label__ = "ZProject"
        __uid_field__ = "name"
        name: str

    class ZWorksOn(RelationshipModel):
        __label__ = "Z_WORKS_ON"
        __source_type__ = ZPerson
        __target_type__ = ZProject
        __source_cardinality__ = Cardinality.ZERO_OR_MORE  # 0..* -- optional
        __target_cardinality__ = Cardinality.ZERO_OR_MORE

    model = GraphDataModel(
        name="ZeroOrMoreTest",
        node_types=[ZPerson, ZProject],
        relationship_types=[ZWorksOn],
    )
    v = GraphValidator(model)

    # Bob has 0 WORKS_ON relationships -- should be valid under ZERO_OR_MORE
    nodes: list[dict[str, Any]] = [
        {"__label__": "ZPerson", "name": "Alice"},
        {"__label__": "ZPerson", "name": "Bob"},
        {"__label__": "ZProject", "name": "Alpha"},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "Z_WORKS_ON",
            "__source_uid__": "Alice",
            "__target_uid__": "Alpha",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid
    assert not any(e.code == "CARDINALITY_VIOLATION" for e in result.errors)


def test_validate_cardinality_one_or_more_rejects_zero():
    """ONE_OR_MORE on source side must reject nodes with 0 relationships."""

    class OPerson(NodeModel):
        __label__ = "OPerson"
        __uid_field__ = "name"
        name: str

    class OProject(NodeModel):
        __label__ = "OProject"
        __uid_field__ = "name"
        name: str

    class OWorksOn(RelationshipModel):
        __label__ = "O_WORKS_ON"
        __source_type__ = OPerson
        __target_type__ = OProject
        __source_cardinality__ = Cardinality.ONE_OR_MORE  # 1..* -- mandatory
        __target_cardinality__ = Cardinality.ZERO_OR_MORE

    model = GraphDataModel(
        name="OneOrMoreTest",
        node_types=[OPerson, OProject],
        relationship_types=[OWorksOn],
    )
    v = GraphValidator(model)

    # Bob has 0 WORKS_ON -- should fail under ONE_OR_MORE
    nodes: list[dict[str, Any]] = [
        {"__label__": "OPerson", "name": "Alice"},
        {"__label__": "OPerson", "name": "Bob"},
        {"__label__": "OProject", "name": "Alpha"},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "O_WORKS_ON",
            "__source_uid__": "Alice",
            "__target_uid__": "Alpha",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert not result.is_valid
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(card_errors) == 1
    assert "Bob" in card_errors[0].message
    assert "0 outgoing" in card_errors[0].message


def test_validate_cardinality_zero_or_more_vs_one_or_more_same_data():
    """Side-by-side: same data is valid under ZERO_OR_MORE but invalid under
    ONE_OR_MORE when a node has zero relationships."""

    class SPerson(NodeModel):
        __label__ = "SPerson"
        __uid_field__ = "name"
        name: str

    class SProject(NodeModel):
        __label__ = "SProject"
        __uid_field__ = "name"
        name: str

    class SWorksOnRelaxed(RelationshipModel):
        __label__ = "S_WORKS_ON_R"
        __source_type__ = SPerson
        __target_type__ = SProject
        __source_cardinality__ = Cardinality.ZERO_OR_MORE

    class SWorksOnStrict(RelationshipModel):
        __label__ = "S_WORKS_ON_S"
        __source_type__ = SPerson
        __target_type__ = SProject
        __source_cardinality__ = Cardinality.ONE_OR_MORE

    relaxed = GraphDataModel(
        name="Relaxed",
        node_types=[SPerson, SProject],
        relationship_types=[SWorksOnRelaxed],
    )
    strict = GraphDataModel(
        name="Strict",
        node_types=[SPerson, SProject],
        relationship_types=[SWorksOnStrict],
    )

    # Alice works on Alpha, Bob has 0 relationships
    nodes: list[dict[str, Any]] = [
        {"__label__": "SPerson", "name": "Alice"},
        {"__label__": "SPerson", "name": "Bob"},
        {"__label__": "SProject", "name": "Alpha"},
    ]
    rels_relaxed: list[dict[str, Any]] = [
        {
            "__label__": "S_WORKS_ON_R",
            "__source_uid__": "Alice",
            "__target_uid__": "Alpha",
        },
    ]
    rels_strict: list[dict[str, Any]] = [
        {
            "__label__": "S_WORKS_ON_S",
            "__source_uid__": "Alice",
            "__target_uid__": "Alpha",
        },
    ]

    # Relaxed: valid (Bob with 0 is fine)
    result_relaxed = GraphValidator(relaxed).validate(nodes, rels_relaxed)
    assert result_relaxed.is_valid

    # Strict: invalid (Bob with 0 violates ONE_OR_MORE)
    result_strict = GraphValidator(strict).validate(nodes, rels_strict)
    assert not result_strict.is_valid
    assert any(e.code == "CARDINALITY_VIOLATION" for e in result_strict.errors)


def test_validate_target_cardinality_violation():
    """Target cardinality violation: too many incoming relationships."""

    class TAuthor(NodeModel):
        __label__ = "TAuthor"
        __uid_field__ = "name"
        name: str

    class TBook(NodeModel):
        __label__ = "TBook"
        __uid_field__ = "title"
        title: str

    class TWrote(RelationshipModel):
        __label__ = "T_WROTE"
        __source_type__ = TAuthor
        __target_type__ = TBook
        __source_cardinality__ = Cardinality.ZERO_OR_MORE
        __target_cardinality__ = Cardinality.ONE  # each book has exactly 1 author

    model = GraphDataModel(
        name="TargetCard",
        node_types=[TAuthor, TBook],
        relationship_types=[TWrote],
    )
    v = GraphValidator(model)

    # "Dune" has 2 authors -- violates target cardinality ONE
    nodes: list[dict[str, Any]] = [
        {"__label__": "TAuthor", "name": "Frank"},
        {"__label__": "TAuthor", "name": "Brian"},
        {"__label__": "TBook", "title": "Dune"},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "T_WROTE",
            "__source_uid__": "Frank",
            "__target_uid__": "Dune",
        },
        {
            "__label__": "T_WROTE",
            "__source_uid__": "Brian",
            "__target_uid__": "Dune",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert not result.is_valid
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(card_errors) == 1
    assert "Dune" in card_errors[0].message
    assert "incoming" in card_errors[0].message


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


# --- Undirected relationship validation tests ---


class Company(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


class FriendOf(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_type__ = Person
    __target_type__ = Person
    __directed__ = False
    __source_cardinality__ = Cardinality.ZERO_OR_MORE


class Collaborates(RelationshipModel):
    __label__ = "COLLABORATES"
    __source_type__ = Person
    __target_type__ = Company
    __directed__ = False


@pytest.fixture()
def social_model() -> GraphDataModel:
    return GraphDataModel(
        name="Social",
        node_types=[Person],
        relationship_types=[FriendOf],
    )


@pytest.fixture()
def cross_undirected_model() -> GraphDataModel:
    return GraphDataModel(
        name="CrossUndirected",
        node_types=[Person, Company],
        relationship_types=[Collaborates],
    )


def test_undirected_same_type_forward_valid(social_model: GraphDataModel):
    """Undirected same-type: forward direction is valid."""
    v = GraphValidator(social_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Person", "name": "Bob", "age": 25},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "FRIEND_OF",
            "__source_uid__": "Alice",
            "__target_uid__": "Bob",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid


def test_undirected_same_type_reverse_valid(social_model: GraphDataModel):
    """Undirected same-type: reverse direction is also valid."""
    v = GraphValidator(social_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Person", "name": "Bob", "age": 25},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "FRIEND_OF",
            "__source_uid__": "Bob",
            "__target_uid__": "Alice",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid


def test_undirected_cross_type_forward_valid(
    cross_undirected_model: GraphDataModel,
):
    """Undirected cross-type: Person->Company (forward) is valid."""
    v = GraphValidator(cross_undirected_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Company", "name": "Acme"},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "COLLABORATES",
            "__source_uid__": "Alice",
            "__target_uid__": "Acme",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid


def test_undirected_cross_type_reverse_valid(
    cross_undirected_model: GraphDataModel,
):
    """Undirected cross-type: Company->Person (reversed) should also be valid."""
    v = GraphValidator(cross_undirected_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Company", "name": "Acme"},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "COLLABORATES",
            "__source_uid__": "Acme",
            "__target_uid__": "Alice",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid


def test_undirected_cross_type_wrong_types_rejected(
    cross_undirected_model: GraphDataModel,
):
    """Undirected cross-type: neither direction matches (wrong types) is rejected."""
    v = GraphValidator(cross_undirected_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Person", "name": "Bob", "age": 25},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "COLLABORATES",
            "__source_uid__": "Alice",
            "__target_uid__": "Bob",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert not result.is_valid
    assert any(e.code == "WRONG_ENDPOINT_TYPE" for e in result.errors)


def test_directed_cross_type_reverse_rejected(filmography_model: GraphDataModel):
    """Directed relationship: reverse direction is rejected."""
    v = GraphValidator(filmography_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Movie", "title": "Inception", "year": 2010},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Inception",  # Movie, not Person
            "__target_uid__": "Alice",  # Person, not Movie
            "role": "Cobb",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert not result.is_valid
    assert any(e.code == "WRONG_ENDPOINT_TYPE" for e in result.errors)


def test_undirected_cardinality_counts_both_directions(
    social_model: GraphDataModel,
):
    """Undirected cardinality counts both outgoing and incoming."""
    v = GraphValidator(social_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Person", "name": "Bob", "age": 25},
        {"__label__": "Person", "name": "Carol", "age": 35},
    ]
    # Alice has 1 outgoing + 1 incoming = 2 total FRIEND_OF
    rels: list[dict[str, Any]] = [
        {
            "__label__": "FRIEND_OF",
            "__source_uid__": "Alice",
            "__target_uid__": "Bob",
        },
        {
            "__label__": "FRIEND_OF",
            "__source_uid__": "Carol",
            "__target_uid__": "Alice",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid


def test_undirected_cardinality_violation():
    """Undirected cardinality violation when total exceeds max."""

    class LimitedFriend(RelationshipModel):
        __label__ = "LIMITED_FRIEND"
        __source_type__ = Person
        __target_type__ = Person
        __directed__ = False
        __source_cardinality__ = CardinalitySpec(min=0, max=1)

    model = GraphDataModel(
        name="Limited",
        node_types=[Person],
        relationship_types=[LimitedFriend],
    )
    v = GraphValidator(model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Person", "name": "Bob", "age": 25},
        {"__label__": "Person", "name": "Carol", "age": 35},
    ]
    # Alice has 1 outgoing + 1 incoming = 2 total, exceeds max=1
    rels: list[dict[str, Any]] = [
        {
            "__label__": "LIMITED_FRIEND",
            "__source_uid__": "Alice",
            "__target_uid__": "Bob",
        },
        {
            "__label__": "LIMITED_FRIEND",
            "__source_uid__": "Carol",
            "__target_uid__": "Alice",
        },
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert not result.is_valid
    assert any(e.code == "CARDINALITY_VIOLATION" for e in result.errors)
