"""Tests for gqlalchemy extension codegen module."""

from __future__ import annotations

from typing import Optional

import pydantic
import pytest
from gqlalchemy import Node as GqaNode
from gqlalchemy import Relationship as GqaRelationship

from orthograph.backends.gqlalchemy.codegen import (
    generate_gqlalchemy_classes,
)
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    NodeModel,
    RelationshipModel,
)


# ---------------------------------------------------------------------------
# Test model definitions (local to this test module)
# ---------------------------------------------------------------------------


class PersonNode(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    age: int
    email: Optional[str] = None


class MovieNode(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    year: int


class SimpleNode(NodeModel):
    __label__ = "Simple"
    pass


class ActedInRel(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    role: str


class DirectedRel(RelationshipModel):
    __label__ = "DIRECTED"
    __source_label__ = "Person"
    __target_label__ = "Movie"


class FriendOfRel(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_label__ = "Person"
    __target_label__ = "Person"
    __directed__ = False
    __source_cardinality__ = "0..*"
    since: Optional[str] = None


@pytest.fixture()
def filmography_model() -> GraphDefinition:
    return GraphDefinition(
        name="Filmography",
        node_types=[PersonNode, MovieNode],
        relationship_types=[ActedInRel, DirectedRel],
    )


@pytest.fixture()
def friendship_model() -> GraphDefinition:
    return GraphDefinition(
        name="Friendship",
        node_types=[PersonNode],
        relationship_types=[FriendOfRel],
    )


@pytest.fixture()
def simple_model() -> GraphDefinition:
    return GraphDefinition(
        name="Simple",
        node_types=[SimpleNode],
        relationship_types=[],
    )


# ---------------------------------------------------------------------------
# Tests: Schema Operations
# ---------------------------------------------------------------------------


def test_get_node_class_returns_correct_class(
    filmography_model: GraphDefinition,
) -> None:
    """Verify schema lookup retrieves correct node class."""
    schema = generate_gqlalchemy_classes(filmography_model)
    cls = schema.get_node_class("Person")
    assert cls is not None
    assert cls.label == "Person"


def test_get_node_class_unknown_label_raises(
    filmography_model: GraphDefinition,
) -> None:
    """Ensure schema raises KeyError for unknown node labels."""
    schema = generate_gqlalchemy_classes(filmography_model)
    with pytest.raises(KeyError, match="Unknown"):
        schema.get_node_class("NonExistent")


def test_get_rel_class_returns_correct_class(
    filmography_model: GraphDefinition,
) -> None:
    """Verify schema lookup retrieves correct relationship class."""
    schema = generate_gqlalchemy_classes(filmography_model)
    cls = schema.get_rel_class("ACTED_IN")
    assert cls is not None
    assert cls.type == "ACTED_IN"


def test_get_rel_class_unknown_type_raises(
    filmography_model: GraphDefinition,
) -> None:
    """Ensure schema raises KeyError for unknown relationship types."""
    schema = generate_gqlalchemy_classes(filmography_model)
    with pytest.raises(KeyError, match="Unknown"):
        schema.get_rel_class("NON_EXISTENT")


def test_schema_contains_all_node_types(
    filmography_model: GraphDefinition,
) -> None:
    """Verify schema includes all defined node types."""
    schema = generate_gqlalchemy_classes(filmography_model)
    assert set(schema.node_classes.keys()) == {"Person", "Movie"}


def test_schema_contains_all_rel_types(
    filmography_model: GraphDefinition,
) -> None:
    """Verify schema includes all defined relationship types."""
    schema = generate_gqlalchemy_classes(filmography_model)
    assert set(schema.rel_classes.keys()) == {"ACTED_IN", "DIRECTED"}


# ---------------------------------------------------------------------------
# Tests: Node Class Generation
# ---------------------------------------------------------------------------


def test_generated_node_inherits_from_gqa_node(
    filmography_model: GraphDefinition,
) -> None:
    """Ensure generated nodes inherit from GQLAlchemy Node base."""
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    assert issubclass(person_cls, GqaNode)


def test_generated_node_has_correct_label(
    filmography_model: GraphDefinition,
) -> None:
    """Verify generated node preserves correct label attribute."""
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    assert person_cls.label == "Person"
    assert "Person" in person_cls.labels


def test_generated_node_has_correct_required_properties(
    filmography_model: GraphDefinition,
) -> None:
    """Verify generated nodes accept and store required fields."""
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    # Instantiate with all required fields
    person = person_cls(name="Alice", age=30)
    assert person.name == "Alice"
    assert person.age == 30


def test_generated_node_has_correct_optional_properties(
    filmography_model: GraphDefinition,
) -> None:
    """Verify generated nodes handle optional fields correctly."""
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    # Instantiate without optional field
    person = person_cls(name="Alice", age=30)
    assert person.email is None
    # Instantiate with optional field
    person2 = person_cls(name="Bob", age=25, email="bob@example.com")
    assert person2.email == "bob@example.com"


def test_generated_node_properties_dict(
    filmography_model: GraphDefinition,
) -> None:
    """Verify generated nodes expose properties as dict."""
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    person = person_cls(name="Alice", age=30, email="alice@test.com")
    props = person._properties
    assert props["name"] == "Alice"
    assert props["age"] == 30
    assert props["email"] == "alice@test.com"


def test_generated_node_without_properties(
    simple_model: GraphDefinition,
) -> None:
    """Verify generated nodes work even with no properties."""
    schema = generate_gqlalchemy_classes(simple_model)
    simple_cls = schema.get_node_class("Simple")
    simple = simple_cls()
    assert simple._properties == {}


def test_multiple_node_types_are_independent(
    filmography_model: GraphDefinition,
) -> None:
    """Verify each generated node type is distinct and independent."""
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    movie_cls = schema.get_node_class("Movie")
    assert person_cls is not movie_cls
    assert person_cls.label != movie_cls.label


# ---------------------------------------------------------------------------
# Tests: Relationship Class Generation
# ---------------------------------------------------------------------------


def test_generated_rel_inherits_from_gqa_relationship(
    filmography_model: GraphDefinition,
) -> None:
    """Ensure generated relationships inherit from GQLAlchemy base."""
    schema = generate_gqlalchemy_classes(filmography_model)
    acted_cls = schema.get_rel_class("ACTED_IN")
    assert issubclass(acted_cls, GqaRelationship)


def test_generated_rel_has_correct_type(
    filmography_model: GraphDefinition,
) -> None:
    """Verify generated relationship preserves correct type."""
    schema = generate_gqlalchemy_classes(filmography_model)
    acted_cls = schema.get_rel_class("ACTED_IN")
    assert acted_cls.type == "ACTED_IN"


def test_generated_rel_with_required_properties(
    filmography_model: GraphDefinition,
) -> None:
    """Verify generated relationships handle required properties."""
    schema = generate_gqlalchemy_classes(filmography_model)
    acted_cls = schema.get_rel_class("ACTED_IN")
    rel = acted_cls(
        _start_node_id=1,
        _end_node_id=2,
        role="Neo",
    )
    assert rel.role == "Neo"
    assert rel._properties["role"] == "Neo"


def test_generated_rel_without_properties(
    filmography_model: GraphDefinition,
) -> None:
    """Verify generated relationships work with no properties."""
    schema = generate_gqlalchemy_classes(filmography_model)
    directed_cls = schema.get_rel_class("DIRECTED")
    rel = directed_cls(_start_node_id=1, _end_node_id=2)
    assert rel._properties == {}


def test_generated_rel_with_optional_properties(
    friendship_model: GraphDefinition,
) -> None:
    """Verify generated relationships handle optional properties."""
    schema = generate_gqlalchemy_classes(friendship_model)
    friend_cls = schema.get_rel_class("FRIEND_OF")
    # Without optional
    rel1 = friend_cls(_start_node_id=1, _end_node_id=2)
    assert rel1.since is None
    # With optional
    rel2 = friend_cls(_start_node_id=1, _end_node_id=2, since="2024")
    assert rel2.since == "2024"


# ---------------------------------------------------------------------------
# Tests: Type Translation
# ---------------------------------------------------------------------------


def test_str_type_preserved(
    filmography_model: GraphDefinition,
) -> None:
    """Verify string type annotations are preserved in generated classes."""
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    annotations = person_cls.__annotations__
    assert annotations["name"] is str


def test_int_type_preserved(
    filmography_model: GraphDefinition,
) -> None:
    """Verify integer type annotations are preserved."""
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    annotations = person_cls.__annotations__
    assert annotations["age"] is int


def test_optional_type_preserved(
    filmography_model: GraphDefinition,
) -> None:
    """Verify Optional types work correctly in generated classes."""
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    # Optional[str] should be present -- instantiate to verify
    person = person_cls(name="Alice", age=30)
    assert person.email is None  # default is None


# ---------------------------------------------------------------------------
# Tests: Pydantic v1/v2 Coexistence
# ---------------------------------------------------------------------------


def test_pydantic_v2_is_installed() -> None:
    """Confirm Pydantic v2 is available for compatibility testing."""
    assert pydantic.VERSION.startswith("2.")


def test_orthograph_model_and_gqa_model_coexist(
    filmography_model: GraphDefinition,
) -> None:
    """Verify Orthograph v2 and GQLAlchemy models coexist."""
    schema = generate_gqlalchemy_classes(filmography_model)
    gqa_person = schema.get_node_class("Person")

    # Orthograph model (Pydantic v2)
    ortho_person = PersonNode(name="Alice", age=30)
    assert ortho_person.name == "Alice"

    # GQLAlchemy model
    gqa_instance = gqa_person(name="Alice", age=30)
    assert gqa_instance.name == "Alice"

    # They are different classes
    assert type(ortho_person) is not type(gqa_instance)


def test_generated_class_is_pydantic_basemodel(
    filmography_model: GraphDefinition,
) -> None:
    """Verify generated classes inherit from BaseModel."""
    gqa_base_model = next(
        base for base in GqaNode.__mro__ if base.__name__ == "BaseModel"
    )
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    assert issubclass(person_cls, gqa_base_model)


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


def test_empty_model_produces_empty_schema() -> None:
    """Verify schema handles models with no relationships."""
    schema = generate_gqlalchemy_classes(
        GraphDefinition(
            name="Empty",
            node_types=[SimpleNode],
            relationship_types=[],
        )
    )
    assert len(schema.node_classes) == 1
    assert len(schema.rel_classes) == 0


def test_generate_is_idempotent(
    filmography_model: GraphDefinition,
) -> None:
    """Verify repeated generation produces consistent results."""
    schema1 = generate_gqlalchemy_classes(filmography_model)
    schema2 = generate_gqlalchemy_classes(filmography_model)

    assert set(schema1.node_classes.keys()) == set(schema2.node_classes.keys())
    assert set(schema1.rel_classes.keys()) == set(schema2.rel_classes.keys())


def test_generated_node_class_name_is_descriptive(
    filmography_model: GraphDefinition,
) -> None:
    """Verify generated node classes have descriptive names."""
    schema = generate_gqlalchemy_classes(filmography_model)
    person_cls = schema.get_node_class("Person")
    assert "Person" in person_cls.__name__
