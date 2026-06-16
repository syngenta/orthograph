"""Tests for orthograph.api.model — load, save, validate, validate_query/queries."""

from pathlib import Path
from typing import Any

import pytest

from orthograph.api.model import (
    load,
    save,
    validate,
    validate_query,
    validate_query_catalogue,
    validate_query_catalogue_against_profile,
)
from orthograph.cypher.base_models import CypherReadQuery
from orthograph.cypher.bindings import NoParams
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.graph_profile.models import (
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
)
from orthograph.query.catalogue import QueryCatalogue


# ---------------------------------------------------------------------------
# Minimal domain model fixture
# ---------------------------------------------------------------------------

_YAML = """\
name: TestGraph
node_types:
  Person:
    uid_field: name
    properties:
      name: {type: str, required: true}
      age: {type: int, required: true}
relationship_types:
  KNOWS:
    source: Person
    target: Person
    directed: true
"""


class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    age: int


class Knows(RelationshipModel):
    __label__ = "KNOWS"
    __source_label__ = "Person"
    __target_label__ = "Person"


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(name="Test", node_types=[Person], relationship_types=[Knows])


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_returns_valid_for_good_data(
    graph_definition: GraphDefinition,
) -> None:
    nodes = [{"__label__": "Person", "name": "Alice", "age": 30}]
    result = validate(graph_definition, nodes)
    assert result.is_valid


def test_validate_returns_error_for_unknown_label(
    graph_definition: GraphDefinition,
) -> None:
    nodes = [{"__label__": "Robot", "name": "R2D2", "age": 0}]
    result = validate(graph_definition, nodes)
    assert not result.is_valid
    codes = {issue.code for issue in result.issues}
    assert "UNKNOWN_NODE_LABEL" in codes


def test_validate_with_relationships(graph_definition: GraphDefinition) -> None:
    nodes = [
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Person", "name": "Bob", "age": 25},
    ]
    rels = [
        {
            "__label__": "KNOWS",
            "__source_uid__": "Alice",
            "__target_uid__": "Bob",
        }
    ]
    result = validate(graph_definition, nodes, relationships=rels)
    assert result.is_valid


def test_validate_default_relationships_is_none(
    graph_definition: GraphDefinition,
) -> None:
    nodes = [{"__label__": "Person", "name": "Alice", "age": 30}]
    result = validate(graph_definition, nodes)
    assert result.is_valid


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------


def test_load_from_yaml_string() -> None:
    loaded = load(_YAML)
    assert isinstance(loaded, GraphDefinition)
    labels = {nt.__label__ for nt in loaded.node_types}
    assert "Person" in labels


def test_load_from_path(tmp_path: Path) -> None:
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(_YAML, encoding="utf-8")
    loaded = load(schema_file)
    assert isinstance(loaded, GraphDefinition)


def test_load_str_is_yaml_content_not_a_path(tmp_path: Path) -> None:
    """A str is always parsed as YAML content; a file path must be a Path."""
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(_YAML, encoding="utf-8")
    with pytest.raises(TypeError):
        load(str(schema_file))


def test_save_and_load_roundtrip(
    graph_definition: GraphDefinition, tmp_path: Path
) -> None:
    out_file = tmp_path / "out.yaml"
    save(graph_definition, out_file)
    assert out_file.exists()
    loaded = load(out_file)
    assert {nt.__label__ for nt in loaded.node_types} == {
        nt.__label__ for nt in graph_definition.node_types
    }
    assert {rt.__label__ for rt in loaded.relationship_types} == {
        rt.__label__ for rt in graph_definition.relationship_types
    }


def test_save_accepts_string_path(
    graph_definition: GraphDefinition, tmp_path: Path
) -> None:
    out_file = tmp_path / "out.yaml"
    save(graph_definition, str(out_file))
    assert out_file.exists()


# ---------------------------------------------------------------------------
# validate_query
# ---------------------------------------------------------------------------


def test_validate_query_clean(graph_definition: GraphDefinition) -> None:
    """A query whose label and property are in the model passes."""
    result = validate_query("MATCH (p:Person {name: $name}) RETURN p", graph_definition)
    assert result.is_valid


def test_validate_query_unknown_label(graph_definition: GraphDefinition) -> None:
    """A query referencing a label not in the
    model surfaces QUERY_UNKNOWN_NODE_LABEL."""
    result = validate_query("MATCH (r:Robot) RETURN r", graph_definition)
    assert not result.is_valid
    codes = {i.code for i in result.errors}
    assert "QUERY_UNKNOWN_NODE_LABEL" in codes


def test_validate_query_unparseable_returns_result_not_exception(
    graph_definition: GraphDefinition,
) -> None:
    """A syntactically unparseable query must not raise — it must return a result."""
    from orthograph.diagnostics.result import ValidationResult

    result = validate_query("THIS IS NOT CYPHER %%%", graph_definition)
    assert isinstance(result, ValidationResult)
    assert not result.is_valid
    assert any(e.code == "QUERY_PARSE_ERROR" for e in result.errors)


# ---------------------------------------------------------------------------
# validate_query_catalogue
# ---------------------------------------------------------------------------


def test_validate_query_catalogue_clean(graph_definition: GraphDefinition) -> None:
    """A catalogue of model-consistent queries produces no errors.

    FindPerson uses whole-node ``RETURN p`` with ``Output = Person`` (NodeModel).
    Under the tiered alignment check this is the VALID/no-INFO case — assert that
    no ``QUERY_RETURN_OUTPUT_MISMATCH`` issues appear.
    """
    from pydantic import BaseModel as PydanticBase

    class P(PydanticBase):
        age: int

    class FindPerson(CypherReadQuery[P, Person]):
        Params = P
        Output = Person
        name = "find_person_clean"
        cypher_template = "MATCH (p:Person {age: $age}) RETURN p"

        def materialize(self, raw: dict[str, Any]) -> Person:
            return Person(name=raw.get("name", "x"), age=raw.get("age", 0))

    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(FindPerson())
    result = validate_query_catalogue(query_catalogue, graph_definition)
    assert result.is_valid
    assert not any(i.code == "QUERY_RETURN_OUTPUT_MISMATCH" for i in result.issues), (
        "Whole-node RETURN p against Person NodeModel must not emit mismatch issues"
    )


def test_validate_query_catalogue_drifted_label(
    graph_definition: GraphDefinition,
) -> None:
    """A catalogue with a drifted label produces an error without touching a DB."""

    class FindDrifted(CypherReadQuery[NoParams, Person]):
        Params = NoParams
        Output = Person
        name = "find_drifted"
        cypher_template = "MATCH (u:OldLabel) RETURN u"

        def materialize(self, raw: dict[str, Any]) -> Person:
            return Person(name="x", age=0)

    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(FindDrifted())
    result = validate_query_catalogue(query_catalogue, graph_definition)
    assert not result.is_valid
    assert any("OldLabel" in i.message for i in result.errors)


# ---------------------------------------------------------------------------
# validate_query_catalogue_against_profile
# ---------------------------------------------------------------------------


@pytest.fixture()
def node_only_model() -> GraphDefinition:
    """A model with only a Person node type — no relationships — so the profile
    fixture does not need to declare relationship profiles."""
    return GraphDefinition(name="NodeOnly", node_types=[Person], relationship_types=[])


def _person_profile() -> GraphProfile:
    return GraphProfile(
        source="test",
        node_type_profiles={
            "Person": NodeTypeProfile(
                label="Person",
                count=5,
                property_profiles={
                    "name": PropertyProfile(
                        name="name",
                        present_count=5,
                        total_count=5,
                        observed_types=["String"],
                    ),
                    "age": PropertyProfile(
                        name="age",
                        present_count=5,
                        total_count=5,
                        observed_types=["Long"],
                    ),
                },
            )
        },
    )


def test_validate_query_catalogue_against_profile_all_clean(
    node_only_model: GraphDefinition,
) -> None:
    """Clean catalogue + matching profile => no errors from either pass.

    Q uses whole-node ``RETURN p`` with ``Output = Person`` — verify the result
    is valid AND that no ``QUERY_RETURN_OUTPUT_MISMATCH`` issues are emitted
    (previously this emitted false INFO for the whole-node case).
    """
    from pydantic import BaseModel as PydanticBase

    class P(PydanticBase):
        age: int

    class Q(CypherReadQuery[P, Person]):
        Params = P
        Output = Person
        name = "q_clean"
        cypher_template = "MATCH (p:Person {age: $age}) RETURN p"

        def materialize(self, raw: dict[str, Any]) -> Person:
            return Person(name=raw.get("name", "x"), age=raw.get("age", 0))

    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(Q())
    result = validate_query_catalogue_against_profile(
        query_catalogue, _person_profile(), node_only_model
    )
    assert result.is_valid
    assert not any(i.code == "QUERY_RETURN_OUTPUT_MISMATCH" for i in result.issues), (
        "Whole-node RETURN p against Person NodeModel must not emit mismatch issues"
    )


def test_validate_query_catalogue_against_profile_merges_both_passes(
    node_only_model: GraphDefinition,
) -> None:
    """Errors from the query pass AND the profile pass both appear in the result."""

    class QDrifted(CypherReadQuery[NoParams, Person]):
        Params = NoParams
        Output = Person
        name = "q_drifted"
        cypher_template = "MATCH (g:Ghost) RETURN g"

        def materialize(self, raw: dict[str, Any]) -> Person:
            return Person(name="x", age=0)

    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(QDrifted())
    empty_profile = GraphProfile(source="test", node_type_profiles={})
    result = validate_query_catalogue_against_profile(
        query_catalogue, empty_profile, node_only_model
    )

    assert not result.is_valid
    codes = {i.code for i in result.errors}
    # query pass → unknown label; profile pass → missing node label
    assert "QUERY_UNKNOWN_NODE_LABEL" in codes
    assert "MISSING_NODE_LABEL" in codes


def test_validate_query_catalogue_against_profile_never_touches_connection(
    node_only_model: GraphDefinition,
) -> None:
    """The profile is passed in; no backend name or connection is needed."""
    query_catalogue = QueryCatalogue()
    # Empty catalogue + empty profile against
    # a model with a required type = profile ERROR
    result = validate_query_catalogue_against_profile(
        query_catalogue, GraphProfile(source="test"), node_only_model
    )
    assert not result.is_valid
    assert any(i.code == "MISSING_NODE_LABEL" for i in result.errors)
