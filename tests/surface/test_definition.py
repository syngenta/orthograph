"""Tests for orthograph.definition.

The declared-side facade: author / load_from_file / save_to_file / validate.
Splits the overloaded ``validate`` into ``validate_definition`` (structural
consistency) vs ``validate_data`` (records against the contract).
"""

from pathlib import Path

import pytest

from orthograph.definition import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    GraphDefinition,
    NodeModel,
    PropMatch,
    RelationshipModel,
    load_from_file,
    save_to_file,
    validate_data,
    validate_definition,
)
from orthograph.diagnostics.result import ValidationResult
from orthograph.io.formats import DefinitionFormat
from tests.fixtures.conftest import Person


_YAML = """\
name: TestGraph
node_types:
  Person:
    uid_field: name
    properties:
      name: {type: str, required: true}
      age: {type: int, required: true}
relationship_types:
  - label: KNOWS
    source: Person
    target: Person
    directed: true
"""


class Knows(RelationshipModel):
    __label__ = "KNOWS"
    __source_label__ = "Person"
    __target_label__ = "Person"


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(name="Test", node_types=[Person], relationship_types=[Knows])


# ---------------------------------------------------------------------------
# load_from_file / save_to_file (round-trip)
# ---------------------------------------------------------------------------


def test_load_from_file_round_trip(tmp_path: Path) -> None:
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(_YAML, encoding="utf-8")
    loaded = load_from_file(schema_file)
    assert isinstance(loaded, GraphDefinition)
    labels = {nt.__label__ for nt in loaded.node_types}
    assert "Person" in labels


def test_save_then_load_round_trip(
    tmp_path: Path, graph_definition: GraphDefinition
) -> None:
    out = tmp_path / "out.yaml"
    save_to_file(graph_definition, out)
    assert out.exists()
    reloaded = load_from_file(out)
    assert isinstance(reloaded, GraphDefinition)
    assert {nt.__label__ for nt in reloaded.node_types} == {"Person"}


def test_format_defaults_to_yaml(tmp_path: Path) -> None:
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(_YAML, encoding="utf-8")
    explicit = load_from_file(schema_file, format=DefinitionFormat.YAML)
    default = load_from_file(schema_file)
    assert {nt.__label__ for nt in explicit.node_types} == {
        nt.__label__ for nt in default.node_types
    }


# ---------------------------------------------------------------------------
# validate_definition (structural consistency)
# ---------------------------------------------------------------------------


def test_validate_definition_valid(graph_definition: GraphDefinition) -> None:
    result = validate_definition(graph_definition)
    assert isinstance(result, ValidationResult)
    assert result.is_valid


def test_validate_definition_flags_structural_issue() -> None:
    """A node type with no relationships is structurally suspect (isolated).

    Structural *errors* (e.g. undefined node refs) are rejected at construction
    time, so ``validate_definition`` surfaces the remaining structural issues —
    here an ``ISOLATED_NODE`` warning.
    """

    class Company(NodeModel):
        __label__ = "Company"
        __uid_field__ = "name"
        name: str

    # Person+Knows are connected; Company participates in no relationship.
    suspect = GraphDefinition(
        name="Suspect",
        node_types=[Person, Company],
        relationship_types=[Knows],
    )
    result = validate_definition(suspect)
    assert "ISOLATED_NODE" in {issue.code for issue in result.issues}


# ---------------------------------------------------------------------------
# validate_data (records against the contract)
# ---------------------------------------------------------------------------


def test_validate_data_accepts_valid_records(
    graph_definition: GraphDefinition,
) -> None:
    nodes = [{"__label__": "Person", "name": "Alice", "age": 30}]
    result = validate_data(graph_definition, nodes)
    assert result.is_valid


def test_validate_data_flags_invalid_record(
    graph_definition: GraphDefinition,
) -> None:
    nodes = [{"__label__": "Robot", "name": "R2D2", "age": 0}]
    result = validate_data(graph_definition, nodes)
    assert not result.is_valid
    assert "UNKNOWN_NODE_LABEL" in {issue.code for issue in result.issues}


def test_validate_data_with_relationships(
    graph_definition: GraphDefinition,
) -> None:
    nodes = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Person", "name": "Bob", "age": 25},
    ]
    rels = [{"__label__": "KNOWS", "__source_uid__": "Alice", "__target_uid__": "Bob"}]
    result = validate_data(graph_definition, nodes, relationships=rels)
    assert result.is_valid


# ---------------------------------------------------------------------------
# re-exported authoring primitives
# ---------------------------------------------------------------------------


def test_authoring_primitives_importable() -> None:
    assert NodeModel is not None
    assert RelationshipModel is not None
    assert CardinalitySpec is not None
    assert ConditionalCardinality is not None
    assert ConditionalRule is not None
    assert PropMatch is not None
