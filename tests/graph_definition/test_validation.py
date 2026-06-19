"""Tests for orthograph.graph_definition.validation -- GraphValidator engine."""

from typing import Any

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
    RelationshipModel,
)
from orthograph.graph_definition.validation import (
    GraphValidator,
    _unpack_node,
    _unpack_rel,
)
from tests.graph_definition.conftest import (  # noqa: F401 — re-exported for type-checker
    ActedIn,
    City,
    Collaborates,
    Company,
    Directed,
    FriendOf,
    LivesIn,
    Movie,
    Person,
)


# --- Validate nodes tests ---


def test_validate_nodes_valid_dict(filmography_model: GraphDefinition):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([{"__label__": "Person", "name": "Alice", "age": 30}])
    assert result.is_valid


def test_validate_nodes_valid_model_instance(filmography_model: GraphDefinition):
    v = GraphValidator(filmography_model)
    p = Person(name="Alice", age=30)
    result = v.validate_nodes([p])
    assert result.is_valid


def test_validate_nodes_unknown_label(filmography_model: GraphDefinition):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([{"__label__": "City", "name": "London"}])
    assert not result.is_valid
    assert result.errors[0].code == "UNKNOWN_NODE_LABEL"


def test_validate_nodes_missing_label_field(filmography_model: GraphDefinition):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([{"name": "Alice", "age": 30}])
    assert not result.is_valid
    assert result.errors[0].code == "MISSING_LABEL"


def test_validate_nodes_missing_required_property(filmography_model: GraphDefinition):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([{"__label__": "Person", "name": "Alice"}])
    assert not result.is_valid
    assert any(e.code == "PROPERTY_VALIDATION_ERROR" for e in result.errors)


def test_validate_nodes_wrong_property_type(filmography_model: GraphDefinition):
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
    filmography_model: GraphDefinition,
):
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([{"__label__": "Person", "name": "Alice", "age": 30}])
    assert result.is_valid


def test_validate_nodes_optional_property_can_be_none(
    filmography_model: GraphDefinition,
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


def test_validate_nodes_extra_properties_rejected(filmography_model: GraphDefinition):
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


def test_validate_nodes_multiple(filmography_model: GraphDefinition):
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


def test_validate_nodes_collects_all_errors(filmography_model: GraphDefinition):
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


def test_validate_relationships_valid_dict(filmography_model: GraphDefinition):
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


def test_validate_relationships_unknown_label(filmography_model: GraphDefinition):
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


def test_validate_relationships_missing_label(filmography_model: GraphDefinition):
    v = GraphValidator(filmography_model)
    rels: list[dict[str, Any]] = [
        {"__source_uid__": "a", "__target_uid__": "b"},
    ]
    result = v.validate_relationships(rels)
    assert not result.is_valid
    assert result.errors[0].code == "MISSING_LABEL"


def test_validate_relationships_missing_required_property(
    filmography_model: GraphDefinition,
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


def test_validate_relationships_missing_source_uid(filmography_model: GraphDefinition):
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


def test_validate_relationships_missing_target_uid(filmography_model: GraphDefinition):
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


def test_validate_referential_integrity_valid(filmography_model: GraphDefinition):
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
    filmography_model: GraphDefinition,
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
    filmography_model: GraphDefinition,
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
    filmography_model: GraphDefinition,
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


def test_validate_cardinality_satisfied(full_model: GraphDefinition):
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


def test_validate_cardinality_violation_too_few(full_model: GraphDefinition):
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
        __source_label__ = "StrictPerson"
        __target_label__ = "StrictMovie"
        __source_cardinality__ = CardinalitySpec(min=0, max=1)

    graph_definition = GraphDefinition(
        name="Strict",
        node_types=[StrictPerson, StrictMovie],
        relationship_types=[OnlyOneRole],
    )

    v = GraphValidator(graph_definition)
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
        __source_label__ = "ZPerson"
        __target_label__ = "ZProject"
        __source_cardinality__ = "0..*"  # 0..* -- optional
        __target_cardinality__ = "0..*"

    graph_definition = GraphDefinition(
        name="ZeroOrMoreTest",
        node_types=[ZPerson, ZProject],
        relationship_types=[ZWorksOn],
    )
    v = GraphValidator(graph_definition)

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
        __source_label__ = "OPerson"
        __target_label__ = "OProject"
        __source_cardinality__ = "1..*"  # 1..* -- mandatory
        __target_cardinality__ = "0..*"

    graph_definition = GraphDefinition(
        name="OneOrMoreTest",
        node_types=[OPerson, OProject],
        relationship_types=[OWorksOn],
    )
    v = GraphValidator(graph_definition)

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
        __source_label__ = "SPerson"
        __target_label__ = "SProject"
        __source_cardinality__ = "0..*"

    class SWorksOnStrict(RelationshipModel):
        __label__ = "S_WORKS_ON_S"
        __source_label__ = "SPerson"
        __target_label__ = "SProject"
        __source_cardinality__ = "1..*"

    relaxed = GraphDefinition(
        name="Relaxed",
        node_types=[SPerson, SProject],
        relationship_types=[SWorksOnRelaxed],
    )
    strict = GraphDefinition(
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
        __source_label__ = "TAuthor"
        __target_label__ = "TBook"
        __source_cardinality__ = "0..*"
        __target_cardinality__ = "1..1"  # each book has exactly 1 author

    graph_definition = GraphDefinition(
        name="TargetCard",
        node_types=[TAuthor, TBook],
        relationship_types=[TWrote],
    )
    v = GraphValidator(graph_definition)

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

    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Req, Opt],
        relationship_types=[],
    )
    v = GraphValidator(graph_definition)
    # No nodes at all -- Req is required, Opt is optional
    result = v.validate(nodes=[], relationships=[])
    assert not result.is_valid
    assert any(e.code == "MISSING_REQUIRED_TYPE" for e in result.errors)


def test_validate_entity_presence_optional_node_type_can_be_missing():
    class Opt(NodeModel):
        __label__ = "Opt"
        __optional__ = True
        val: str

    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Opt],
        relationship_types=[],
    )
    v = GraphValidator(graph_definition)
    result = v.validate(nodes=[], relationships=[])
    assert result.is_valid


def test_validate_entity_presence_required_relationship_type_missing():
    class N(NodeModel):
        __label__ = "N"
        __optional__ = True
        val: str

    class ReqRel(RelationshipModel):
        __label__ = "REQ_REL"
        __source_label__ = "N"
        __target_label__ = "N"
        __optional__ = False

    graph_definition = GraphDefinition(
        name="Test",
        node_types=[N],
        relationship_types=[ReqRel],
    )
    v = GraphValidator(graph_definition)
    result = v.validate(nodes=[], relationships=[])
    assert not result.is_valid
    assert any(e.code == "MISSING_REQUIRED_TYPE" for e in result.errors)


# --- Validate full graph tests ---


def test_validate_full_graph_complete_valid(filmography_model: GraphDefinition):
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


def test_undirected_same_type_forward_valid(social_model: GraphDefinition):
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


def test_undirected_same_type_reverse_valid(social_model: GraphDefinition):
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
    cross_undirected_model: GraphDefinition,
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
    cross_undirected_model: GraphDefinition,
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
    cross_undirected_model: GraphDefinition,
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


def test_directed_cross_type_reverse_rejected(filmography_model: GraphDefinition):
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
    social_model: GraphDefinition,
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
        __source_label__ = "Person"
        __target_label__ = "Person"
        __directed__ = False
        __source_cardinality__ = CardinalitySpec(min=0, max=1)

    graph_definition = GraphDefinition(
        name="Limited",
        node_types=[Person],
        relationship_types=[LimitedFriend],
    )
    v = GraphValidator(graph_definition)
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


# ---------------------------------------------------------------------------
# _unpack_node / _unpack_rel unit tests
# Guard against regressions where meta keys leak into props or are misread.
# ---------------------------------------------------------------------------


def test_unpack_node_model_instance_no_label_in_props():
    """NodeModel instance: __label__ must not appear in props."""
    p = Person(name="Alice", age=30)
    label, props = _unpack_node(p)
    assert label == "Person"
    assert "__label__" not in props
    assert props == {"name": "Alice", "age": 30, "email": None}


def test_unpack_node_dict_label_removed_from_props():
    """Raw dict: __label__ is consumed and must not remain in props."""
    label, props = _unpack_node({"__label__": "Person", "name": "Alice", "age": 30})
    assert label == "Person"
    assert "__label__" not in props
    assert props == {"name": "Alice", "age": 30}


def test_unpack_node_dict_missing_label_returns_none():
    label, props = _unpack_node({"name": "Alice", "age": 30})
    assert label is None
    assert "__label__" not in props


def test_unpack_rel_dict_all_meta_removed_from_props():
    """Raw dict: all three dunder meta keys are consumed; only props remain."""
    label, src, tgt, props = _unpack_rel(
        {
            "__label__": "ACTED_IN",
            "__source_uid__": "Alice",
            "__target_uid__": "Inception",
            "role": "Cobb",
        }
    )
    assert label == "ACTED_IN"
    assert src == "Alice"
    assert tgt == "Inception"
    assert props == {"role": "Cobb"}
    assert "__label__" not in props
    assert "__source_uid__" not in props
    assert "__target_uid__" not in props


def test_unpack_rel_model_instance_uids_are_none():
    """RelationshipModel instance: src/tgt uids are None (model carries no uid)."""

    class Knows(RelationshipModel):
        __label__ = "KNOWS"
        __source_label__ = "Person"
        __target_label__ = "Person"
        since: int

    r = Knows(since=2020)
    label, src, tgt, props = _unpack_rel(r)
    assert label == "KNOWS"
    assert src is None
    assert tgt is None
    assert props == {"since": 2020}
    assert "__label__" not in props


def test_validate_nodes_model_instance_no_false_extra_properties(
    filmography_model,
):
    """NodeModel instances must never trigger EXTRA_PROPERTIES from __label__."""
    v = GraphValidator(filmography_model)
    result = v.validate_nodes([Person(name="Alice", age=30)])
    assert result.is_valid
    assert not any(e.code == "EXTRA_PROPERTIES" for e in result.errors)


def test_validate_relationships_model_instance_triggers_missing_endpoint(
    filmography_model,
):
    """RelationshipModel instances have no uid info: MISSING_ENDPOINT is expected.

    Documents the contract: callers that want referential validation
    must supply dicts with __source_uid__ / __target_uid__.
    """
    v = GraphValidator(filmography_model)

    class ActedInInstance(RelationshipModel):
        __label__ = "ACTED_IN"
        __source_label__ = "Person"
        __target_label__ = "Movie"
        role: str

    result = v.validate_relationships([ActedInInstance(role="Cobb")])
    assert not result.is_valid
    assert any(e.code == "MISSING_ENDPOINT" for e in result.errors)


# ---------------------------------------------------------------------------
# Regression: _check_entity_presence must check both node AND rel presence
# (guards against the duplicate-return bug where the rel half was dead code)
# ---------------------------------------------------------------------------


def test_entity_presence_reports_both_missing_node_and_rel_types():
    """Both a required node type and a required rel type absent: both reported."""

    class ReqNode(NodeModel):
        __label__ = "ReqNode"
        __optional__ = False
        val: str

    class ReqRel(RelationshipModel):
        __label__ = "REQ_REL"
        __source_label__ = "ReqNode"
        __target_label__ = "ReqNode"
        __optional__ = False

    gd = GraphDefinition(
        name="BothRequired",
        node_types=[ReqNode],
        relationship_types=[ReqRel],
    )
    v = GraphValidator(gd)
    result = v.validate(nodes=[], relationships=[])

    assert not result.is_valid
    missing_codes = [e.code for e in result.errors if e.code == "MISSING_REQUIRED_TYPE"]
    # Must report one for the node type and one for the rel type
    assert len(missing_codes) == 2
    entity_ids = {
        e.entity_id for e in result.errors if e.code == "MISSING_REQUIRED_TYPE"
    }
    assert "ReqNode" in entity_ids
    assert "REQ_REL" in entity_ids


# --- E40.3/E40.5: conditional cardinality on the validation path ---


def test_validate_conditional_cardinality_does_not_crash():
    """Scope: a ConditionalCardinality side validates per-pair without raising
    AttributeError, and a documentary director with zero films violates the
    ('documentary', '*') rule (declared partition, missing → 0)."""

    class CDirector(NodeModel):
        __label__ = "CDirector"
        __uid_field__ = "name"
        name: str
        kind: str  # required — E40.4 requires discriminators to be required props

    class CFilm(NodeModel):
        __label__ = "CFilm"
        __uid_field__ = "title"
        title: str

    # A documentary director must direct at least one film (wildcard target);
    # any other kind falls to the permissive default.
    conditional = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "documentary"}),
                target=PropMatch(),
                spec="1..*",
            ),
        ),
        default="0..*",
    )

    class CDirected(RelationshipModel):
        __label__ = "C_DIRECTED"
        __source_label__ = "CDirector"
        __target_label__ = "CFilm"
        __source_cardinality__ = conditional
        __target_cardinality__ = "0..*"

    graph_definition = GraphDefinition(
        name="ConditionalCardinality",
        node_types=[CDirector, CFilm],
        relationship_types=[CDirected],
    )
    v = GraphValidator(graph_definition)

    # Nolan (documentary) has zero films → violates ONE_OR_MORE;
    # Kubrick (feature) falls to the permissive default → no violation.
    nodes: list[dict[str, Any]] = [
        {"__label__": "CDirector", "name": "Nolan", "kind": "documentary"},
        {"__label__": "CDirector", "name": "Kubrick", "kind": "feature"},
        {"__label__": "CFilm", "title": "Inception"},
    ]
    rels: list[dict[str, Any]] = [
        {
            "__label__": "C_DIRECTED",
            "__source_uid__": "Kubrick",
            "__target_uid__": "Inception",
        },
    ]

    # Must not raise; resolution is per-pair.
    result = v.validate(nodes=nodes, relationships=rels)

    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert any("Nolan" in e.entity_id for e in card_errors)
    assert not any("Kubrick" in e.entity_id for e in card_errors)


# ---------------------------------------------------------------------------
# E40.5: in-memory partitioned conditional-cardinality validation (ADR-029)
# ---------------------------------------------------------------------------


def _operation_sample_model(
    source_cardinality: ConditionalCardinality,
) -> GraphDefinition:
    """Build the ADR-029 Operation -[HAS_OUTPUT]-> Sample model with a given
    source-side conditional cardinality (both nodes discriminated by ``kind``)."""

    class Operation(NodeModel):
        __label__ = "Operation"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class Sample(NodeModel):
        __label__ = "Sample"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class HasOutput(RelationshipModel):
        __label__ = "HAS_OUTPUT"
        __source_label__ = "Operation"
        __target_label__ = "Sample"
        __source_cardinality__ = source_cardinality
        __target_cardinality__ = "0..*"

    return GraphDefinition(
        name="OperationSample",
        node_types=[Operation, Sample],
        relationship_types=[HasOutput],
    )


def test_conditional_deciding_scenario_valid_with_permissive_default():
    """Scope: ADR-029 deciding scenario resolves valid when default is ZERO_OR_MORE."""
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch({"kind": "subsampling"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
        ),
        default="0..*",
    )
    gd = _operation_sample_model(card)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Operation", "uid": "op1", "kind": "subsampling"},
        {"__label__": "Sample", "uid": "s1", "kind": "subsampling"},
        {"__label__": "Sample", "uid": "s2", "kind": "subsampling"},
        {"__label__": "Sample", "uid": "s3", "kind": "nothing"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "HAS_OUTPUT", "__source_uid__": "op1", "__target_uid__": "s1"},
        {"__label__": "HAS_OUTPUT", "__source_uid__": "op1", "__target_uid__": "s2"},
        {"__label__": "HAS_OUTPUT", "__source_uid__": "op1", "__target_uid__": "s3"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    assert result.is_valid
    assert not any(e.code == "CARDINALITY_VIOLATION" for e in result.errors)


def test_conditional_deciding_scenario_violation_with_zero_default():
    """Scope: ADR-029 deciding scenario emits one violation naming
    (subsampling, nothing) when default is ZERO."""
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch({"kind": "subsampling"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
        ),
        default="0..0",
    )
    gd = _operation_sample_model(card)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Operation", "uid": "op1", "kind": "subsampling"},
        {"__label__": "Sample", "uid": "s1", "kind": "subsampling"},
        {"__label__": "Sample", "uid": "s2", "kind": "subsampling"},
        {"__label__": "Sample", "uid": "s3", "kind": "nothing"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "HAS_OUTPUT", "__source_uid__": "op1", "__target_uid__": "s1"},
        {"__label__": "HAS_OUTPUT", "__source_uid__": "op1", "__target_uid__": "s2"},
        {"__label__": "HAS_OUTPUT", "__source_uid__": "op1", "__target_uid__": "s3"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(card_errors) == 1
    issue = card_errors[0]
    assert issue.context["source_kind"] == "subsampling"
    assert issue.context["target_kind"] == "nothing"
    assert issue.context["actual"] == 1


def test_conditional_missing_partition_counted_as_zero_violates_min():
    """Scope: a declared rule with min>0 on an unobserved partition violates
    (missing partition counted as 0)."""
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "combine"}),
                target=PropMatch({"kind": "nothing"}),
                spec=CardinalitySpec(min=2, max=2),
            ),
        ),
        default="0..*",
    )
    gd = _operation_sample_model(card)
    # A combine Operation with zero nothing-outputs: the (combine, nothing)
    # partition is absent → counted as 0 → EXACTLY(2) min unmet.
    nodes: list[dict[str, Any]] = [
        {"__label__": "Operation", "uid": "op1", "kind": "combine"},
        {"__label__": "Sample", "uid": "s1", "kind": "nothing"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=[])
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(card_errors) == 1
    assert card_errors[0].context["target_kind"] == "nothing"
    assert card_errors[0].context["actual"] == 0


def test_conditional_observed_partition_violates_wildcard_rule():
    """Scope: a discard Operation with one output violates ('discard','*'): ZERO."""
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "discard"}),
                target=PropMatch(),
                spec="0..0",
            ),
        ),
        default="0..*",
    )
    gd = _operation_sample_model(card)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Operation", "uid": "op1", "kind": "discard"},
        {"__label__": "Sample", "uid": "s1", "kind": "nothing"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "HAS_OUTPUT", "__source_uid__": "op1", "__target_uid__": "s1"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(card_errors) == 1
    assert card_errors[0].context["source_kind"] == "discard"


def test_conditional_unmatched_kind_emits_info_no_error():
    """Scope: an Operation whose kind matches no rule and no wildcard emits
    CARDINALITY_UNMATCHED_KIND (INFO) and no error under a permissive default."""
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch({"kind": "subsampling"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
        ),
        default="0..*",
    )
    gd = _operation_sample_model(card)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Operation", "uid": "op1", "kind": "lyophilize"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=[])
    assert result.is_valid
    info = [i for i in result.issues if i.code == "CARDINALITY_UNMATCHED_KIND"]
    assert len(info) == 1
    assert info[0].severity.value == "info"
    assert info[0].context["source_kind"] == "lyophilize"


def test_conditional_target_cardinality_partitioned_by_source_kind():
    """Scope: a target-side conditional cardinality partitions a target node's
    incoming edges by the source node's kind, symmetrically to the source side."""

    class Producer(NodeModel):
        __label__ = "Producer"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class Artifact(NodeModel):
        __label__ = "Artifact"
        __uid_field__ = "uid"
        uid: str
        kind: str

    # Each Artifact{kind:final} must have exactly 2 incoming edges from
    # Producer{kind:assembler}; default permits anything.
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "assembler"}),
                target=PropMatch({"kind": "final"}),
                spec=CardinalitySpec(min=2, max=2),
            ),
        ),
        default="0..*",
    )

    class Produces(RelationshipModel):
        __label__ = "PRODUCES"
        __source_label__ = "Producer"
        __target_label__ = "Artifact"
        __target_cardinality__ = card

    gd = GraphDefinition(
        name="ProducerArtifact",
        node_types=[Producer, Artifact],
        relationship_types=[Produces],
    )
    # final Artifact has only 1 incoming assembler edge → violates min=2.
    nodes: list[dict[str, Any]] = [
        {"__label__": "Producer", "uid": "p1", "kind": "assembler"},
        {"__label__": "Artifact", "uid": "a1", "kind": "final"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "PRODUCES", "__source_uid__": "p1", "__target_uid__": "a1"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(card_errors) == 1
    assert card_errors[0].context["source_kind"] == "assembler"
    assert card_errors[0].context["target_kind"] == "final"
    assert card_errors[0].context["actual"] == 1


def test_conditional_default_floor_enforced_on_unmatched_zero_edge_node():
    """Scope: an unmatched node with zero edges violates a default with min>0
    (ADR-029 §5/§7 default floor — no silent pass)."""
    # subsampling consumes nothing; every other kind must consume at least one.
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch(),
                spec="0..0",
            ),
        ),
        default="1..*",
    )
    gd = _operation_sample_model(card)
    # A combine Operation matches no rule and has zero outputs → default ONE_OR_MORE
    # is violated (total degree 0).
    nodes: list[dict[str, Any]] = [
        {"__label__": "Operation", "uid": "op1", "kind": "combine"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=[])
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(card_errors) == 1
    issue = card_errors[0]
    assert issue.context["default"] is True
    assert issue.context["source_kind"] == "combine"
    assert issue.context["actual"] == 0
    # The drift INFO is still emitted alongside the enforced floor.
    assert any(i.code == "CARDINALITY_UNMATCHED_KIND" for i in result.issues)


def test_conditional_permissive_default_admits_zero_edge_unmatched_node():
    """Scope: a permissive default (min=0) lets an unmatched zero-edge node pass;
    only the drift INFO is emitted, no violation (default floor never fires)."""
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch(),
                spec="0..0",
            ),
        ),
        default="0..*",
    )
    gd = _operation_sample_model(card)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Operation", "uid": "op1", "kind": "combine"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=[])
    assert result.is_valid
    assert not any(e.code == "CARDINALITY_VIOLATION" for e in result.errors)
    info = [i for i in result.issues if i.code == "CARDINALITY_UNMATCHED_KIND"]
    assert len(info) == 1
