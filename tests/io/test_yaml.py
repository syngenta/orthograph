"""Tests for orthograph.io.yaml -- YAML config loading/saving."""

from pathlib import Path

import pytest

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    Cardinality,
    NodeModel,
    RelationshipModel,
)
from orthograph.io.yaml import load_yaml_file, load_yaml_string, save_yaml_file


@pytest.fixture()
def simple_yaml_content() -> str:
    return """\
name: "Filmography"
version: "1.0.0"

node_types:
  Person:
    uid_field: name
    properties:
      name: {type: str, required: true}
      age: {type: int, required: true}
      email: {type: str, required: false}

  Movie:
    uid_field: title
    properties:
      title: {type: str, required: true}
      year: {type: int, required: true}

relationship_types:
  ACTED_IN:
    source: Person
    target: Movie
    directed: true
    source_cardinality: {min: 0, max: null}
    target_cardinality: {min: 0, max: null}
    properties:
      role: {type: str, required: true}

  DIRECTED:
    source: Person
    target: Movie
    directed: true
"""


@pytest.fixture()
def simple_yaml_file(tmp_path: Path, simple_yaml_content: str) -> Path:
    p = tmp_path / "schema.yaml"
    p.write_text(simple_yaml_content)
    return p


# --- YAML loading tests ---


def test_yaml_load_from_string(simple_yaml_content: str):
    graph_definition = load_yaml_string(simple_yaml_content)
    assert isinstance(graph_definition, GraphDefinition)
    assert graph_definition.name == "Filmography"
    assert graph_definition.version == "1.0.0"


def test_yaml_load_node_types(simple_yaml_content: str):
    graph_definition = load_yaml_string(simple_yaml_content)
    assert graph_definition.node_labels == {"Person", "Movie"}


def test_yaml_node_uid_field(simple_yaml_content: str):
    graph_definition = load_yaml_string(simple_yaml_content)
    person = graph_definition.get_node_type("Person")
    assert person is not None
    assert person.__uid_field__ == "name"


def test_yaml_node_properties(simple_yaml_content: str):
    graph_definition = load_yaml_string(simple_yaml_content)
    person = graph_definition.get_node_type("Person")
    assert person is not None
    props = person.get_all_property_names()
    assert props == {"name", "age", "email"}


def test_yaml_required_vs_optional_properties(simple_yaml_content: str):
    graph_definition = load_yaml_string(simple_yaml_content)
    person = graph_definition.get_node_type("Person")
    assert person is not None
    required = person.get_required_property_names()
    assert "name" in required
    assert "age" in required
    assert "email" not in required


def test_yaml_load_relationship_types(simple_yaml_content: str):
    graph_definition = load_yaml_string(simple_yaml_content)
    assert graph_definition.relationship_labels == {"ACTED_IN", "DIRECTED"}


def test_yaml_relationship_endpoints(simple_yaml_content: str):
    graph_definition = load_yaml_string(simple_yaml_content)
    acted_in = graph_definition.get_relationship_type("ACTED_IN")
    assert acted_in is not None
    assert acted_in.__source_label__ == "Person"
    assert acted_in.__target_label__ == "Movie"


def test_yaml_relationship_cardinality(simple_yaml_content: str):
    graph_definition = load_yaml_string(simple_yaml_content)
    acted_in = graph_definition.get_relationship_type("ACTED_IN")
    assert acted_in is not None
    assert acted_in.__source_cardinality__ == Cardinality.ZERO_OR_MORE
    assert acted_in.__target_cardinality__ == Cardinality.ZERO_OR_MORE


def test_yaml_relationship_default_cardinality(simple_yaml_content: str):
    graph_definition = load_yaml_string(simple_yaml_content)
    directed = graph_definition.get_relationship_type("DIRECTED")
    assert directed is not None
    # Default cardinality when not specified
    assert directed.__source_cardinality__ == Cardinality.ZERO_OR_MORE
    assert directed.__target_cardinality__ == Cardinality.ZERO_OR_MORE


def test_yaml_load_from_file(simple_yaml_file: Path):
    graph_definition = load_yaml_file(simple_yaml_file)
    assert graph_definition.name == "Filmography"
    assert graph_definition.node_labels == {"Person", "Movie"}


def test_yaml_load_nonexistent_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_yaml_file(tmp_path / "nonexistent.yaml")


def test_yaml_missing_name_raises_value_error():
    content = """\
node_types:
  Person:
    properties:
      name: str
"""
    with pytest.raises(ValueError, match="missing required field 'name'"):
        load_yaml_string(content)


def test_yaml_relationship_missing_source_raises_value_error():
    content = """\
name: "Test"
relationship_types:
  KNOWS:
    target: Person
"""
    with pytest.raises(ValueError, match="KNOWS.*missing required field 'source'"):
        load_yaml_string(content)


def test_yaml_relationship_missing_target_raises_value_error():
    content = """\
name: "Test"
relationship_types:
  KNOWS:
    source: Person
"""
    with pytest.raises(ValueError, match="KNOWS.*missing required field 'target'"):
        load_yaml_string(content)


# --- YAML with optional entities tests ---


def test_yaml_optional_node_type():
    content = """\
name: "Test"
node_types:
  Req:
    optional: false
    properties:
      val: {type: str, required: true}
  Opt:
    optional: true
    properties:
      val: {type: str, required: true}
relationship_types: {}
"""
    graph_definition = load_yaml_string(content)
    req = graph_definition.get_node_type("Req")
    opt = graph_definition.get_node_type("Opt")
    assert req is not None
    assert req.__optional__ is False
    assert opt is not None
    assert opt.__optional__ is True


# --- YAML round-trip tests ---


def test_yaml_save_and_load(tmp_path: Path):
    class A(NodeModel):
        __label__ = "A"
        __uid_field__ = "name"
        name: str
        count: int

    class B(NodeModel):
        __label__ = "B"
        val: str

    class AB(RelationshipModel):
        __label__ = "A_TO_B"
        __source_label__ = "A"
        __target_label__ = "B"
        weight: float

    graph_definition = GraphDefinition(
        name="RoundTrip",
        version="2.0.0",
        node_types=[A, B],
        relationship_types=[AB],
    )

    path = tmp_path / "roundtrip.yaml"
    save_yaml_file(graph_definition, path)

    loaded = load_yaml_file(path)
    assert loaded.name == "RoundTrip"
    assert loaded.version == "2.0.0"
    assert loaded.node_labels == {"A", "B"}
    assert loaded.relationship_labels == {"A_TO_B"}

    a_type = loaded.get_node_type("A")
    assert a_type is not None
    assert a_type.__uid_field__ == "name"
    assert a_type.get_required_property_names() == {"name", "count"}
