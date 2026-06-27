"""Tests for orthograph.queries — the query-governance facade module.

Covers: assembled catalogue load (the ergonomics fix vs the old list-returning
``load_query_catalogue``), empty-catalogue authoring, simple-query building,
auto-CRUD generation, and the three validation verbs.
"""

from pathlib import Path

import pytest

from orthograph import queries
from orthograph.cypher.bindings import NoIdentifiers, NoParams
from orthograph.cypher.query import CypherQuery
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import (
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
)
from orthograph.query.catalogue import QueryCatalogue
from tests.fixtures.conftest import Person


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CATALOGUE_YAML = """\
- query_id: find_person
  cypher_template: "MATCH (p:Person {name: $name}) RETURN p"
  params_schema:
    title: FindPersonParams
    type: object
    properties:
      name: {type: string, title: Name}
    required: [name]
- query_id: count_people
  cypher_template: "MATCH (p:Person) RETURN count(p) AS total"
  params_schema:
    type: object
    properties: {}
"""


@pytest.fixture()
def person_definition() -> GraphDefinition:
    return GraphDefinition(name="Test", node_types=[Person], relationship_types=[])


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


# ---------------------------------------------------------------------------
# load_catalogue — the assembled-catalogue ergonomics fix
# ---------------------------------------------------------------------------


def test_load_catalogue_returns_assembled_catalogue(
    person_definition: GraphDefinition,
) -> None:
    catalogue = queries.load_catalogue(_CATALOGUE_YAML)
    assert isinstance(catalogue, QueryCatalogue)
    assert set(catalogue.names()) == {"find_person", "count_people"}


def test_load_catalogue_validates_against_matching_definition(
    person_definition: GraphDefinition,
) -> None:
    catalogue = queries.load_catalogue(_CATALOGUE_YAML)
    result = queries.validate_catalogue(catalogue, person_definition)
    assert result.is_valid


def test_load_catalogue_from_file(tmp_path: Path) -> None:
    yaml_file = tmp_path / "catalogue.yaml"
    yaml_file.write_text(_CATALOGUE_YAML, encoding="utf-8")
    catalogue = queries.load_catalogue(yaml_file)
    assert isinstance(catalogue, QueryCatalogue)
    assert set(catalogue.names()) == {"find_person", "count_people"}


# ---------------------------------------------------------------------------
# new_catalogue
# ---------------------------------------------------------------------------


def test_new_catalogue_is_empty() -> None:
    catalogue = queries.new_catalogue()
    assert isinstance(catalogue, QueryCatalogue)
    assert catalogue.names() == []


def test_new_catalogue_accepts_registration() -> None:
    catalogue = queries.new_catalogue()
    query = queries.simple_query(
        "find_person",
        "MATCH (p:Person {name: $name}) RETURN p",
        params=_name_params_model(),
    )
    catalogue.register_cypher_query(query)
    assert catalogue.names() == ["find_person"]


def _name_params_model() -> type:
    from pydantic import BaseModel

    class NameParams(BaseModel):
        name: str

    return NameParams


# ---------------------------------------------------------------------------
# simple_query
# ---------------------------------------------------------------------------


def test_simple_query_builds_usable_cypher_query() -> None:
    query = queries.simple_query(
        "find_person",
        "MATCH (p:Person {name: $name}) RETURN p",
        params=_name_params_model(),
    )
    assert isinstance(query, CypherQuery)
    assert query.query_id == "find_person"
    built = query.build(name="Alice")
    assert built.params == {"name": "Alice"}


def test_simple_query_defaults_to_no_params() -> None:
    query = queries.simple_query(
        "count_people",
        "MATCH (p:Person) RETURN count(p) AS total",
    )
    assert query.params_schema is NoParams
    assert query.identifiers_schema in (None, NoIdentifiers)


def test_validate_query_accepts_string(person_definition: GraphDefinition) -> None:
    result = queries.validate_query(
        "MATCH (p:Person {name: $name}) RETURN p", person_definition
    )
    assert isinstance(result, ValidationResult)
    assert result.is_valid


def test_validate_query_accepts_cypher_query(
    person_definition: GraphDefinition,
) -> None:
    query = queries.simple_query(
        "find_person",
        "MATCH (p:Person {name: $name}) RETURN p",
        params=_name_params_model(),
    )
    result = queries.validate_query(query, person_definition)
    assert isinstance(result, ValidationResult)
    assert result.is_valid


# ---------------------------------------------------------------------------
# generate_crud
# ---------------------------------------------------------------------------


def test_generate_crud_produces_catalogue_for_uid_node(
    person_definition: GraphDefinition,
) -> None:
    catalogue = queries.generate_crud(person_definition)
    assert isinstance(catalogue, QueryCatalogue)
    names = set(catalogue.names())
    assert "match_person_by_uid" in names
    assert "merge_person" in names
    assert "create_person" in names
    assert "delete_person_by_uid" in names


def test_generate_crud_catalogue_validates_against_definition(
    person_definition: GraphDefinition,
) -> None:
    catalogue = queries.generate_crud(person_definition)
    result = queries.validate_catalogue(catalogue, person_definition)
    assert result.is_valid


def test_generate_crud_skips_node_without_uid() -> None:
    from orthograph.graph_definition.models import NodeModel

    class Event(NodeModel):
        __label__ = "Event"
        kind: str

    definition = GraphDefinition(
        name="NoUid", node_types=[Event], relationship_types=[]
    )
    catalogue = queries.generate_crud(definition)
    # create_event has no UID requirement, but match/merge/delete by uid do.
    names = set(catalogue.names())
    assert "match_event_by_uid" not in names
    assert "merge_event" not in names
    assert "delete_event_by_uid" not in names


# ---------------------------------------------------------------------------
# validate_catalogue / validate_catalogue_against_profile parity
# ---------------------------------------------------------------------------


def test_validate_catalogue_matches_underlying(
    person_definition: GraphDefinition,
) -> None:
    import orthograph.cypher.validation as _v

    catalogue = queries.load_catalogue(_CATALOGUE_YAML)
    facade = queries.validate_catalogue(catalogue, person_definition)
    direct = _v.validate_query_catalogue(catalogue, person_definition)
    assert facade.is_valid == direct.is_valid
    assert {i.code for i in facade.issues} == {i.code for i in direct.issues}


def test_validate_catalogue_against_profile_matches_underlying(
    person_definition: GraphDefinition,
) -> None:
    import orthograph.cypher.validation as _v

    catalogue = queries.load_catalogue(_CATALOGUE_YAML)
    profile = _person_profile()
    facade = queries.validate_catalogue_against_profile(
        catalogue, profile, person_definition
    )
    direct = _v.validate_query_catalogue_against_profile(
        catalogue, profile, person_definition
    )
    assert facade.is_valid == direct.is_valid
    assert {i.code for i in facade.issues} == {i.code for i in direct.issues}
