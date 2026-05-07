"""Tests for gqlalchemy extension codegen module."""

from __future__ import annotations

from typing import Optional

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.core.types import Cardinality


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
    __source_type__ = PersonNode
    __target_type__ = MovieNode
    role: str


class DirectedRel(RelationshipModel):
    __label__ = "DIRECTED"
    __source_type__ = PersonNode
    __target_type__ = MovieNode


class FriendOfRel(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_type__ = PersonNode
    __target_type__ = PersonNode
    __directed__ = False
    __source_cardinality__ = Cardinality.ZERO_OR_MORE
    since: Optional[str] = None


@pytest.fixture()
def filmography_model() -> GraphDataModel:
    return GraphDataModel(
        name="Filmography",
        node_types=[PersonNode, MovieNode],
        relationship_types=[ActedInRel, DirectedRel],
    )


@pytest.fixture()
def friendship_model() -> GraphDataModel:
    return GraphDataModel(
        name="Friendship",
        node_types=[PersonNode],
        relationship_types=[FriendOfRel],
    )


@pytest.fixture()
def simple_model() -> GraphDataModel:
    return GraphDataModel(
        name="Simple",
        node_types=[SimpleNode],
        relationship_types=[],
    )


# ---------------------------------------------------------------------------
# Tests: GqlAlchemySchema
# ---------------------------------------------------------------------------


class TestGqlAlchemySchema:
    """Tests for the GqlAlchemySchema container."""

    def test_get_node_class_returns_correct_class(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        cls = schema.get_node_class("Person")
        assert cls is not None
        assert cls.label == "Person"

    def test_get_node_class_unknown_label_raises(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        with pytest.raises(KeyError, match="Unknown"):
            schema.get_node_class("NonExistent")

    def test_get_rel_class_returns_correct_class(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        cls = schema.get_rel_class("ACTED_IN")
        assert cls is not None
        assert cls.type == "ACTED_IN"

    def test_get_rel_class_unknown_type_raises(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        with pytest.raises(KeyError, match="Unknown"):
            schema.get_rel_class("NON_EXISTENT")

    def test_schema_contains_all_node_types(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        assert set(schema.node_classes.keys()) == {"Person", "Movie"}

    def test_schema_contains_all_rel_types(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        assert set(schema.rel_classes.keys()) == {"ACTED_IN", "DIRECTED"}


# ---------------------------------------------------------------------------
# Tests: Node class generation
# ---------------------------------------------------------------------------


class TestNodeClassGeneration:
    """Tests for generated GQLAlchemy Node classes."""

    def test_generated_node_inherits_from_gqa_node(
        self, filmography_model: GraphDataModel
    ) -> None:
        from gqlalchemy import Node as GqaNode

        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        assert issubclass(person_cls, GqaNode)

    def test_generated_node_has_correct_label(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        assert person_cls.label == "Person"
        assert "Person" in person_cls.labels

    def test_generated_node_has_correct_required_properties(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        # Instantiate with all required fields
        person = person_cls(name="Alice", age=30)
        assert person.name == "Alice"
        assert person.age == 30

    def test_generated_node_has_correct_optional_properties(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        # Instantiate without optional field
        person = person_cls(name="Alice", age=30)
        assert person.email is None
        # Instantiate with optional field
        person2 = person_cls(name="Bob", age=25, email="bob@example.com")
        assert person2.email == "bob@example.com"

    def test_generated_node_properties_dict(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        person = person_cls(name="Alice", age=30, email="alice@test.com")
        props = person._properties
        assert props["name"] == "Alice"
        assert props["age"] == 30
        assert props["email"] == "alice@test.com"

    def test_generated_node_without_properties(
        self, simple_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(simple_model)
        simple_cls = schema.get_node_class("Simple")
        simple = simple_cls()
        assert simple._properties == {}

    def test_multiple_node_types_are_independent(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        movie_cls = schema.get_node_class("Movie")
        assert person_cls is not movie_cls
        assert person_cls.label != movie_cls.label


# ---------------------------------------------------------------------------
# Tests: Relationship class generation
# ---------------------------------------------------------------------------


class TestRelationshipClassGeneration:
    """Tests for generated GQLAlchemy Relationship classes."""

    def test_generated_rel_inherits_from_gqa_relationship(
        self, filmography_model: GraphDataModel
    ) -> None:
        from gqlalchemy import Relationship as GqaRelationship

        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        acted_cls = schema.get_rel_class("ACTED_IN")
        assert issubclass(acted_cls, GqaRelationship)

    def test_generated_rel_has_correct_type(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        acted_cls = schema.get_rel_class("ACTED_IN")
        assert acted_cls.type == "ACTED_IN"

    def test_generated_rel_with_required_properties(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

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
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        directed_cls = schema.get_rel_class("DIRECTED")
        rel = directed_cls(_start_node_id=1, _end_node_id=2)
        assert rel._properties == {}

    def test_generated_rel_with_optional_properties(
        self, friendship_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(friendship_model)
        friend_cls = schema.get_rel_class("FRIEND_OF")
        # Without optional
        rel1 = friend_cls(_start_node_id=1, _end_node_id=2)
        assert rel1.since is None
        # With optional
        rel2 = friend_cls(_start_node_id=1, _end_node_id=2, since="2024")
        assert rel2.since == "2024"


# ---------------------------------------------------------------------------
# Tests: Type translation
# ---------------------------------------------------------------------------


class TestTypeTranslation:
    """Tests for Pydantic v2 -> v1 type translation."""

    def test_str_type_preserved(self, filmography_model: GraphDataModel) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        annotations = person_cls.__annotations__
        assert annotations["name"] is str

    def test_int_type_preserved(self, filmography_model: GraphDataModel) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        annotations = person_cls.__annotations__
        assert annotations["age"] is int

    def test_optional_type_preserved(self, filmography_model: GraphDataModel) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        # Optional[str] should be present -- instantiate to verify
        person = person_cls(name="Alice", age=30)
        assert person.email is None  # default is None


# ---------------------------------------------------------------------------
# Tests: Pydantic v1/v2 coexistence
# ---------------------------------------------------------------------------


class TestPydanticCoexistence:
    """Verify Pydantic v1 and v2 coexist without conflict."""

    def test_pydantic_v2_is_installed(self) -> None:
        import pydantic

        assert pydantic.VERSION.startswith("2.")

    def test_pydantic_v1_compat_available(self) -> None:
        from pydantic import v1 as pydantic_v1

        assert hasattr(pydantic_v1, "BaseModel")

    def test_orthograph_model_and_gqa_model_coexist(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        gqa_person = schema.get_node_class("Person")

        # Orthograph model (Pydantic v2)
        ortho_person = PersonNode(name="Alice", age=30)
        assert ortho_person.name == "Alice"

        # GQLAlchemy model (Pydantic v1)
        gqa_instance = gqa_person(name="Alice", age=30)
        assert gqa_instance.name == "Alice"

        # They are different classes
        assert type(ortho_person) is not type(gqa_instance)

    def test_generated_class_is_pydantic_v1(
        self, filmography_model: GraphDataModel
    ) -> None:
        from pydantic.v1 import BaseModel as V1BaseModel

        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        assert issubclass(person_cls, V1BaseModel)


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestCodegenEdgeCases:
    """Edge cases and error handling."""

    def test_empty_model_produces_empty_schema(self) -> None:
        """A model with no relationship types produces an empty rel_classes."""
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(
            GraphDataModel(
                name="Empty",
                node_types=[SimpleNode],
                relationship_types=[],
            )
        )
        assert len(schema.node_classes) == 1
        assert len(schema.rel_classes) == 0

    def test_generate_is_idempotent(self, filmography_model: GraphDataModel) -> None:
        """Calling generate twice produces equivalent schemas."""
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema1 = generate_gqlalchemy_classes(filmography_model)
        schema2 = generate_gqlalchemy_classes(filmography_model)

        assert set(schema1.node_classes.keys()) == set(schema2.node_classes.keys())
        assert set(schema1.rel_classes.keys()) == set(schema2.rel_classes.keys())

    def test_generated_node_class_name_is_descriptive(
        self, filmography_model: GraphDataModel
    ) -> None:
        from orthograph.extensions.gqlalchemy.codegen import (
            generate_gqlalchemy_classes,
        )

        schema = generate_gqlalchemy_classes(filmography_model)
        person_cls = schema.get_node_class("Person")
        assert "Person" in person_cls.__name__
