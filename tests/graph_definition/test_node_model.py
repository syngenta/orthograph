"""Tests for orthograph.graph_definition.node_model -- NodeModel base class."""

from typing import ClassVar, Optional

import pytest
from pydantic import Field

from orthograph.graph_definition.exceptions import MissingClassVarError
from orthograph.graph_definition.models import NodeModel


# --- NodeModel definition tests ---


def test_node_model_simple():
    class Person(NodeModel):
        __label__ = "Person"
        __uid_field__ = "name"

        name: str
        age: int

    assert Person.__label__ == "Person"
    assert Person.__uid_field__ == "name"
    assert Person.__optional__ is True


def test_node_model_with_optional_properties():
    class Movie(NodeModel):
        __label__ = "Movie"
        __uid_field__ = "title"

        title: str
        year: int
        rating: Optional[float] = None

    m = Movie(title="Inception", year=2010)
    assert m.title == "Inception"
    assert m.year == 2010
    assert m.rating is None


def test_node_model_with_default():
    class Tag(NodeModel):
        __label__ = "Tag"

        name: str
        color: str = "blue"
        items: list[str] = Field(default_factory=list)

    t = Tag(name="important")
    assert t.color == "blue"
    assert t.items == []


def test_node_model_optional_entity():
    class OptionalNode(NodeModel):
        __label__ = "OptionalNode"
        __optional__ = True

        value: str

    assert OptionalNode.__optional__ is True


def test_node_model_no_uid():
    class SimpleNode(NodeModel):
        __label__ = "SimpleNode"

        data: str

    assert SimpleNode.__uid_field__ is None


def test_node_model_validation():
    class Strict(NodeModel):
        __label__ = "Strict"

        name: str
        count: int

    with pytest.raises(Exception):  # Pydantic validation error
        Strict(name="a", count="not_an_int")


def test_node_model_requires_label():
    with pytest.raises(MissingClassVarError, match="__label__"):

        class BadNode(NodeModel):
            name: str


# --- __uid_field__ definition-time validation tests (E29 T1) ---


def test_uid_field_typo_raises_at_definition_time():
    """__uid_field__ pointing to a non-existent property raises MissingClassVarError."""
    with pytest.raises(MissingClassVarError) as exc_info:

        class BadFieldName(NodeModel):
            __label__ = "BadFieldName"
            __uid_field__ = "naem"

            name: str

    msg = str(exc_info.value)
    assert "BadFieldName" in msg
    assert "naem" in msg
    assert "name" in msg  # declared property must appear in error


def test_uid_field_nullable_raises_at_definition_time():
    """__uid_field__ pointing to a nullable field raises MissingClassVarError."""
    with pytest.raises(MissingClassVarError) as exc_info:

        class NullableUidNode(NodeModel):
            __label__ = "NullableUidNode"
            __uid_field__ = "name"

            name: str | None = None

    msg = str(exc_info.value)
    assert "NullableUidNode" in msg
    assert "name" in msg
    assert "required" in msg.lower() or "optional" in msg.lower()


def test_uid_field_nullable_optional_syntax_raises():
    """Optional[str] variant of nullable uid also raises MissingClassVarError."""
    with pytest.raises(MissingClassVarError):

        class NullableOptional(NodeModel):
            __label__ = "NullableOptional"
            __uid_field__ = "title"

            title: Optional[str] = None


def test_uid_field_valid_does_not_raise():
    """A valid __uid_field__ pointing to a required
    (non-nullable) field causes no error."""

    class ValidNode(NodeModel):
        __label__ = "ValidNode"
        __uid_field__ = "name"

        name: str
        description: Optional[str] = None

    assert ValidNode.__uid_field__ == "name"


def test_no_uid_field_is_unaffected():
    """A subclass with no __uid_field__ set is not affected by the new guard."""

    class NoUidNode(NodeModel):
        __label__ = "NoUidNode"

        name: str

    assert NoUidNode.__uid_field__ is None


# --- Inheritance gap regression tests (E29 T1 follow-up) ---


def test_child_re_annotating_uid_field_as_nullable_raises():
    """A child class that inherits __uid_field__ but re-annotates the targeted
    property as nullable must raise MissingClassVarError at definition time.

    Before the fix, __init_subclass__ only validated when __uid_field__ was in
    cls.__dict__. A child that omits __uid_field__ but overrides the annotation
    to str | None would silently bypass the guard.
    """

    class ParentNode(NodeModel):
        __label__ = "Parent"
        __uid_field__ = "id"
        id: str

    with pytest.raises(MissingClassVarError) as exc_info:

        class ChildNode(ParentNode):
            __label__ = "Child"
            id: str | None = None  # type: ignore[assignment]  # re-annotated as nullable — must be caught

    msg = str(exc_info.value)
    assert "ChildNode" in msg
    assert "id" in msg


def test_child_re_annotating_uid_field_with_optional_syntax_raises():
    """Optional[str] variant of the inheritance-gap re-annotation also raises."""

    class ParentNode2(NodeModel):
        __label__ = "Parent2"
        __uid_field__ = "key"
        key: str

    with pytest.raises(MissingClassVarError):

        class ChildNode2(ParentNode2):
            __label__ = "Child2"
            key: Optional[str] = None  # type: ignore[assignment]


def test_child_that_does_not_override_uid_annotation_is_fine():
    """A child class that inherits __uid_field__ and does NOT re-annotate the
    UID property remains valid — the guard must not fire for it."""

    class ParentNode3(NodeModel):
        __label__ = "Parent3"
        __uid_field__ = "uid"
        uid: str

    class ChildNode3(ParentNode3):
        __label__ = "Child3"
        extra: int = 0

    assert ChildNode3.__uid_field__ == "uid"


def test_child_overriding_non_uid_annotation_is_fine():
    """A child class that re-annotates a non-UID property does not trigger the
    uid-field guard."""

    class ParentNode4(NodeModel):
        __label__ = "Parent4"
        __uid_field__ = "uid"
        uid: str
        description: str

    class ChildNode4(ParentNode4):
        __label__ = "Child4"
        description: Optional[str] = None  # type: ignore[assignment]  # non-UID field → fine

    assert ChildNode4.__uid_field__ == "uid"


def test_child_explicit_uid_field_none_clears_inherited_uid():
    """A child that explicitly sets __uid_field__ = None to clear an inherited
    UID must NOT raise — the explicit None should be honoured, not treated as
    "not set" and fall through to the inherited value."""

    class ParentNode5(NodeModel):
        __label__ = "Parent5"
        __uid_field__: ClassVar[str | None] = "uid"
        uid: str

    class ChildNode5(ParentNode5):
        __label__ = "Child5"
        __uid_field__: ClassVar[str | None] = (
            None  # intentionally clears the inherited UID
        )
        # widening str → str|None to clear UID constraint
        uid: Optional[str] = None  # type: ignore[assignment]

    assert ChildNode5.__uid_field__ is None


# --- NodeModel introspection tests ---


def test_node_model_get_property_specs():
    class Person(NodeModel):
        __label__ = "Person"
        __uid_field__ = "name"

        name: str
        age: int
        email: Optional[str] = None

    specs = Person.get_property_specs()
    assert "name" in specs
    assert specs["name"].python_type is str
    assert specs["name"].is_required is True
    assert "age" in specs
    assert specs["age"].python_type is int
    assert "email" in specs
    assert specs["email"].is_required is False


def test_node_model_get_required_properties():
    class Item(NodeModel):
        __label__ = "Item"

        name: str
        description: Optional[str] = None
        count: int

    required = Item.get_required_property_names()
    assert required == {"name", "count"}


def test_node_model_get_all_property_names():
    class Item(NodeModel):
        __label__ = "Item"

        name: str
        description: Optional[str] = None

    names = Item.get_all_property_names()
    assert names == {"name", "description"}


def test_node_model_label_is_inherited():
    """Subclasses of a concrete NodeModel must define their own __label__."""

    class Base(NodeModel):
        __label__ = "Base"
        name: str

    # A further subclass should work if it defines its own label
    class Child(Base):
        __label__ = "Child"
        extra: int = 0

    assert Child.__label__ == "Child"
    assert Base.__label__ == "Base"


# --- NodeModel serialization tests ---


def test_node_model_to_dict():
    class Person(NodeModel):
        __label__ = "Person"
        __uid_field__ = "name"

        name: str
        age: int

    p = Person(name="Alice", age=30)
    d = p.model_dump()
    assert d == {"name": "Alice", "age": 30}


def test_node_model_from_dict():
    class Person(NodeModel):
        __label__ = "Person"

        name: str
        age: int

    p = Person.model_validate({"name": "Bob", "age": 25})
    assert p.name == "Bob"
    assert p.age == 25
