"""Tests for GqlAlchemyReadQueryModel / GqlAlchemyWriteQueryModel (E8.1).

Exercises the three validation-report sketches: value-only (no Identifiers),
label-only, and relationship (label + rel_type). No live database — build()
is pure and returns a GQLAlchemy builder object, asserted via construct_query().
"""

from typing import Any

import pytest
from gqlalchemy import match
from pydantic import BaseModel

from orthograph.backends.gqlalchemy.base_models import (
    GqlAlchemyReadQueryModel,
    GqlAlchemyWriteQueryModel,
    validated_label,
)
from orthograph.cypher.bindings import NoParams
from orthograph.cypher.exceptions import CypherIdentifierError
from orthograph.graph_definition.models import NodeModel
from orthograph.query.base_models import Backend


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class PersonRow(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str


class NameParams(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# Sketch 1 — value-only query (Params, no Identifiers)
# ---------------------------------------------------------------------------


class PeopleByName(GqlAlchemyReadQueryModel[NameParams, PersonRow]):
    params_schema = NameParams
    Output = PersonRow
    query_id = "people_by_name"

    def build(self, params: NameParams) -> Any:
        return (
            match()
            .node(labels="Person", variable="n")
            .where(item="n.name", operator="=", literal=params.name)
            .return_(results="n")
        )

    def materialize(self, raw: dict[str, Any]) -> PersonRow:
        return PersonRow(name=raw["n.name"])


# ---------------------------------------------------------------------------
# Sketch 2 — label-only query (dynamic label via Identifiers)
# ---------------------------------------------------------------------------


class NodesByLabel(GqlAlchemyReadQueryModel[NoParams, PersonRow]):
    class identifiers_schema(BaseModel):
        label: str

    params_schema = NoParams
    Output = PersonRow
    query_id = "nodes_by_label"

    def build(self, params: NoParams) -> Any:
        label = validated_label(self._identifiers.label, field_name="label")  # type: ignore[attr-defined]
        return match().node(labels=label, variable="n").return_(results="n")

    def materialize(self, raw: dict[str, Any]) -> PersonRow:
        return PersonRow(name=raw["n.name"])


# ---------------------------------------------------------------------------
# Sketch 3 — relationship query (label + rel_type)
# ---------------------------------------------------------------------------


class RelByType(GqlAlchemyReadQueryModel[NoParams, PersonRow]):
    class identifiers_schema(BaseModel):
        label: str
        rel_type: str

    params_schema = NoParams
    Output = PersonRow
    query_id = "rel_by_type"

    def build(self, params: NoParams) -> Any:
        label = validated_label(self._identifiers.label, field_name="label")  # type: ignore[attr-defined]
        rel = validated_label(self._identifiers.rel_type, field_name="rel_type")  # type: ignore[attr-defined]
        return (
            match()
            .node(labels=label, variable="n")
            .to(relationship_type=rel, variable="r")
            .node(variable="m")
            .return_(results="n")
        )

    def materialize(self, raw: dict[str, Any]) -> PersonRow:
        return PersonRow(name=raw["n.name"])


# ---------------------------------------------------------------------------
# Write smoke query
# ---------------------------------------------------------------------------


class CreatePerson(GqlAlchemyWriteQueryModel[NameParams, int]):
    params_schema = NameParams
    query_id = "create_person"

    def build(self, params: NameParams) -> Any:
        from gqlalchemy import create

        return create().node(labels="Person", variable="n").return_(results="n")

    def interpret_result(self, raw: object) -> int:
        return 1


# ---------------------------------------------------------------------------
# Fake executor helper (defined at module level, used in test 9)
# ---------------------------------------------------------------------------


class _FakeExecutor:
    def read(self, query: Any, raw_params: Any) -> list[Any]:
        params = query.params_schema.model_validate(raw_params)
        builder = query.build(params)  # builder object, not a tuple
        assert hasattr(builder, "construct_query")
        return [query.materialize({"n.name": "Alice"})]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_import_gqlalchemy_query_base_models() -> None:
    from orthograph.backends.gqlalchemy.base_models import (  # noqa: F401
        GqlAlchemyReadQueryModel,
        GqlAlchemyWriteQueryModel,
    )


def test_backend_tag_is_gqlalchemy() -> None:
    assert PeopleByName.backend is Backend.GQLALCHEMY
    assert CreatePerson.backend is Backend.GQLALCHEMY


def test_value_only_build_returns_builder_not_tuple() -> None:
    q = PeopleByName()
    b = q.build(NameParams(name="Alice"))
    assert not isinstance(b, tuple)
    assert hasattr(b, "construct_query")
    cypher = b.construct_query()
    assert "Person" in cypher and "Alice" in cypher


def test_label_only_build_uses_dynamic_label() -> None:
    q = NodesByLabel(identifiers={"label": "Person"})
    b = q.build(NoParams())
    assert not isinstance(b, tuple)
    assert "Person" in b.construct_query()


def test_relationship_build_uses_label_and_rel_type() -> None:
    q = RelByType(identifiers={"label": "Person", "rel_type": "ACTED_IN"})
    b = q.build(NoParams())
    assert not isinstance(b, tuple)
    cypher = b.construct_query()
    assert "Person" in cypher and "ACTED_IN" in cypher


def test_injected_label_raises_via_validate_identifier() -> None:
    q = NodesByLabel(identifiers={"label": "x) DETACH DELETE (n"})
    with pytest.raises(CypherIdentifierError):
        q.build(NoParams())


def test_rel_type_field_validates_as_relationship_type() -> None:
    q = RelByType(identifiers={"label": "Person", "rel_type": "BAD]-(x"})
    with pytest.raises(CypherIdentifierError):
        q.build(NoParams())


def test_materialize_returns_output_nodemodel() -> None:
    row = PeopleByName().materialize({"n.name": "Alice"})
    assert isinstance(row, PersonRow) and row.name == "Alice"


def test_build_flows_through_executor_without_tuple_assumption() -> None:
    out = _FakeExecutor().read(PeopleByName(), {"name": "Alice"})
    assert out == [PersonRow(name="Alice")]


def test_write_build_returns_builder_and_backend_tag() -> None:
    q = CreatePerson()
    b = q.build(NameParams(name="Alice"))
    assert not isinstance(b, tuple)
    assert hasattr(b, "construct_query")
    assert q.interpret_result(object()) == 1
