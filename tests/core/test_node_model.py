"""Tests for orthograph.core.node_model -- NodeModel base class."""

from typing import Optional

import pytest
from pydantic import Field

from orthograph.core.node_model import NodeModel


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
    with pytest.raises(TypeError, match="__label__"):

        class BadNode(NodeModel):
            name: str


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
