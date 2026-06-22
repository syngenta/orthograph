"""Tests for orthograph.io.yaml -- YAML config loading/saving."""

from pathlib import Path

import pytest

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
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
    assert acted_in.__source_cardinality__ == CardinalitySpec(min=0, max=None)
    assert acted_in.__target_cardinality__ == CardinalitySpec(min=0, max=None)


def test_yaml_relationship_default_cardinality(simple_yaml_content: str):
    graph_definition = load_yaml_string(simple_yaml_content)
    directed = graph_definition.get_relationship_type("DIRECTED")
    assert directed is not None
    # Default cardinality when not specified
    assert directed.__source_cardinality__ == CardinalitySpec(min=0, max=None)
    assert directed.__target_cardinality__ == CardinalitySpec(min=0, max=None)


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


# --- conditional cardinality must not crash YAML serialization ---


def test_yaml_save_conditional_cardinality_uses_default_bound(tmp_path: Path):
    """Serializing a RelationshipModel with ConditionalCardinality round-trips
    the full conditional rules (full round-trip of conditional cardinality)."""

    class CDirector(NodeModel):
        __label__ = "CDirector"
        __uid_field__ = "name"
        name: str
        kind: str  # required — discriminators must be required properties

    class CFilm(NodeModel):
        __label__ = "CFilm"
        __uid_field__ = "title"
        title: str

    conditional = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "documentary"}),
                target=PropMatch(),
                spec="1..*",
            ),
        ),
        default="1..1",
    )

    class CDirected(RelationshipModel):
        __label__ = "C_DIRECTED"
        __source_label__ = "CDirector"
        __target_label__ = "CFilm"
        __source_cardinality__ = conditional

    graph_definition = GraphDefinition(
        name="CondCardinality",
        node_types=[CDirector, CFilm],
        relationship_types=[CDirected],
    )

    path = tmp_path / "conditional.yaml"
    # Must not raise.
    save_yaml_file(graph_definition, path)

    loaded = load_yaml_file(path)
    rel = loaded.get_relationship_type("C_DIRECTED")
    assert rel is not None
    # full conditional round-trip — the loaded cardinality equals the original.
    assert rel.__source_cardinality__ == conditional


# --- YAML round-trip for conditional cardinality ---


_CONDITIONAL_YAML = """\
name: "Operations"

node_types:
  Operation:
    uid_field: id
    properties:
      id: {type: str, required: true}
      kind: {type: str, required: true}

  Sample:
    uid_field: id
    properties:
      id: {type: str, required: true}
      kind: {type: str, required: true}

relationship_types:
  HAS_OUTPUT:
    source: Operation
    target: Sample
    directed: true
    source_cardinality:
      conditional:
        rules:
          - when:
              source: {kind: subsampling}
              target: {kind: subsampling}
            min: 1
            max: 2
          - when:
              source: {kind: split}
              target: {}
            min: 0
            max: 0
        default: {min: 0, max: null}
"""


def test_yaml_parse_conditional_cardinality():
    """Scope: conditional source_cardinality YAML parses to ConditionalCardinality
    with correct rules and default."""
    gd = load_yaml_string(_CONDITIONAL_YAML)
    rel = gd.get_relationship_type("HAS_OUTPUT")
    assert rel is not None
    card = rel.__source_cardinality__
    assert isinstance(card, ConditionalCardinality)
    assert card.default == CardinalitySpec(min=0, max=None)
    assert len(card.rules) == 2
    # rule 0: subsampling→subsampling = 1..2
    r0 = card.rules[0]
    assert r0.source == PropMatch({"kind": "subsampling"})
    assert r0.target == PropMatch({"kind": "subsampling"})
    assert r0.spec == CardinalitySpec(min=1, max=2)
    # rule 1: split→wildcard = 0..0
    r1 = card.rules[1]
    assert r1.source == PropMatch({"kind": "split"})
    assert r1.target == PropMatch()
    assert r1.spec == CardinalitySpec(min=0, max=0)


def test_yaml_conditional_cardinality_round_trip():
    """Scope: model → serialize → parse yields an equal ConditionalCardinality."""

    class OpNode(NodeModel):
        __label__ = "Op"
        __uid_field__ = "id"
        id: str
        kind: str

    class SampleNode(NodeModel):
        __label__ = "Smp"
        __uid_field__ = "id"
        id: str
        kind: str

    conditional = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch({"kind": "subsampling"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
            ConditionalRule(
                source=PropMatch({"kind": "split"}),
                target=PropMatch(),
                spec=CardinalitySpec(min=0, max=0),
            ),
        ),
        default=CardinalitySpec(min=0, max=None),
    )

    class HasOutput(RelationshipModel):
        __label__ = "HAS_OUTPUT"
        __source_label__ = "Op"
        __target_label__ = "Smp"
        __source_cardinality__ = conditional

    import yaml as _yaml

    from orthograph.graph_definition.graph_definition import GraphDefinition

    gd = GraphDefinition(
        name="RoundTripConditional",
        node_types=[OpNode, SampleNode],
        relationship_types=[HasOutput],
    )

    raw = _yaml.dump(
        __import__(
            "orthograph.io.yaml", fromlist=["_serialize_model"]
        )._serialize_model(gd),
        default_flow_style=False,
        sort_keys=False,
    )
    loaded = load_yaml_string(raw)
    rel = loaded.get_relationship_type("HAS_OUTPUT")
    assert rel is not None
    loaded_card = rel.__source_cardinality__
    assert isinstance(loaded_card, ConditionalCardinality)
    assert loaded_card == conditional


def test_yaml_parse_notation_string_cardinality():
    """Scope: YAML with notation-string cardinality values parses correctly."""
    content = """\
name: "Notation"
node_types:
  A:
    uid_field: id
    properties:
      id: {type: str, required: true}
  B:
    uid_field: id
    properties:
      id: {type: str, required: true}
relationship_types:
  CONNECTS:
    source: A
    target: B
    directed: true
    source_cardinality: "1..*"
    target_cardinality: "0..1"
"""
    gd = load_yaml_string(content)
    rel = gd.get_relationship_type("CONNECTS")
    assert rel is not None
    assert rel.__source_cardinality__ == CardinalitySpec(min=1, max=None)
    assert rel.__target_cardinality__ == CardinalitySpec(min=0, max=1)


def test_yaml_flat_cardinality_regression():
    """Scope: existing flat {min, max} YAML still parses and round-trips correctly."""
    content = """\
name: "Flat"
node_types:
  A:
    uid_field: id
    properties:
      id: {type: str, required: true}
  B:
    uid_field: id
    properties:
      id: {type: str, required: true}
relationship_types:
  CONNECTS:
    source: A
    target: B
    directed: true
    source_cardinality: {min: 1, max: 3}
    target_cardinality: {min: 0, max: null}
"""
    gd = load_yaml_string(content)
    rel = gd.get_relationship_type("CONNECTS")
    assert rel is not None
    assert rel.__source_cardinality__ == CardinalitySpec(min=1, max=3)
    assert rel.__target_cardinality__ == CardinalitySpec(min=0, max=None)

    # Serialize and parse back
    import yaml as _yaml

    from orthograph.io.yaml import _serialize_model  # noqa: PLC0415

    raw = _yaml.dump(_serialize_model(gd), default_flow_style=False, sort_keys=False)
    loaded = load_yaml_string(raw)
    rel2 = loaded.get_relationship_type("CONNECTS")
    assert rel2 is not None
    assert rel2.__source_cardinality__ == CardinalitySpec(min=1, max=3)
    assert rel2.__target_cardinality__ == CardinalitySpec(min=0, max=None)


def test_yaml_legacy_conditional_cardinality_still_parses():
    """Scope: legacy conditional YAML using min/max keys
    in rules still parses (back-compat)."""
    # _CONDITIONAL_YAML uses old-style min/max rule keys — must still work.
    gd = load_yaml_string(_CONDITIONAL_YAML)
    rel = gd.get_relationship_type("HAS_OUTPUT")
    assert rel is not None
    card = rel.__source_cardinality__
    assert isinstance(card, ConditionalCardinality)
    assert card.default == CardinalitySpec(min=0, max=None)
    assert len(card.rules) == 2


def test_yaml_conditional_round_trip_emits_notation():
    """Scope: serialized conditional YAML uses notation strings for leaves."""
    import yaml as _yaml

    from orthograph.io.yaml import _serialize_model  # noqa: PLC0415

    class OpNode(NodeModel):
        __label__ = "OpN"
        __uid_field__ = "id"
        id: str
        kind: str

    class SmpNode(NodeModel):
        __label__ = "SmpN"
        __uid_field__ = "id"
        id: str

    cond = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "fast"}),
                target=PropMatch(),
                spec=CardinalitySpec(min=1, max=2),
            ),
        ),
        default=CardinalitySpec(min=0, max=None),
    )

    class Edge(RelationshipModel):
        __label__ = "EDGE"
        __source_label__ = "OpN"
        __target_label__ = "SmpN"
        __source_cardinality__ = cond

    from orthograph.graph_definition.graph_definition import (
        GraphDefinition,  # noqa: PLC0415
    )

    gd = GraphDefinition(
        name="NotationEmit",
        node_types=[OpNode, SmpNode],
        relationship_types=[Edge],
    )

    serialized = _serialize_model(gd)
    src_card = serialized["relationship_types"]["EDGE"]["source_cardinality"]
    assert isinstance(src_card, dict)
    cond_data = src_card["conditional"]
    # default must be a notation string
    assert cond_data["default"] == "0..*"
    # rule spec must be a notation string
    assert cond_data["rules"][0]["spec"] == "1..2"

    # Full round-trip must equal the original
    raw = _yaml.dump(serialized, default_flow_style=False, sort_keys=False)
    loaded = load_yaml_string(raw)
    rel = loaded.get_relationship_type("EDGE")
    assert rel is not None
    assert rel.__source_cardinality__ == cond
