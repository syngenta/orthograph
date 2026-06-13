"""Integration proof: the same ReadPort yields identical domain objects
regardless of the raw record shape behind it.

This demonstrates the swappable-read property end to end. We prove it with two
Cypher executors fed differently-shaped records, and with two distinct queries
that share one ``Output`` model bound behind the same ``ReadPort[P, D]``
annotation.
"""

from typing import Any

from pydantic import BaseModel

from orthograph.cypher.base_models import CypherReadQuery
from orthograph.cypher.query_execution import CypherExecutor
from orthograph.graph_definition.models import NodeModel
from orthograph.query.base_models import (
    Executor,
    QueryBackedReadPort,
    ReadPort,
)


class ProtocolParams(BaseModel):
    protocol_id: int


class Sample(NodeModel):
    __label__ = "Sample"
    __uid_field__ = "sample_id"
    sample_id: str
    label: str


# Two raw record shapes carrying the SAME data under DIFFERENT keys. A storage
# swap (or a query rewrite) changes the record shape; the domain object must not.
RECORDS_SHAPE_A: list[dict[str, Any]] = [
    {"s.sample_id": "S001", "s.label": "alpha"},
    {"s.sample_id": "S002", "s.label": "beta"},
]
RECORDS_SHAPE_B: list[dict[str, Any]] = [
    {"sample_id": "S001", "label": "alpha"},
    {"sample_id": "S002", "label": "beta"},
]


class SamplesByProtocolShapeA(CypherReadQuery[ProtocolParams, Sample]):
    """Materialises the dotted-key record shape (``s.sample_id``)."""

    Params = ProtocolParams
    Output = Sample
    name = "samples_by_protocol_shape_a"
    cypher_template = (
        "MATCH (s:Sample {protocol_id: $protocol_id}) RETURN s.sample_id, s.label"
    )

    def materialize(self, raw: dict[str, Any]) -> Sample:
        return Sample(sample_id=raw["s.sample_id"], label=raw["s.label"])


class SamplesByProtocolShapeB(CypherReadQuery[ProtocolParams, Sample]):
    """Same logical read and Output, but materialises the plain-key shape."""

    Params = ProtocolParams
    Output = Sample
    name = "samples_by_protocol_shape_b"
    cypher_template = (
        "MATCH (s:Sample {protocol_id: $protocol_id}) "
        "RETURN s.sample_id AS sample_id, s.label AS label"
    )

    def materialize(self, raw: dict[str, Any]) -> Sample:
        return Sample(sample_id=raw["sample_id"], label=raw["label"])


class FakeGraphSession:
    """Minimal context-manager session returning canned records from run()."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def __enter__(self) -> "FakeGraphSession":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        return list(self._records)


def test_same_port_different_record_shapes_identical_output() -> None:
    """Two queries (different record shapes) behind one ReadPort type produce
    identical domain objects."""
    port_a: ReadPort[ProtocolParams, Sample] = QueryBackedReadPort(
        SamplesByProtocolShapeA(),
        CypherExecutor(lambda: FakeGraphSession(RECORDS_SHAPE_A)),
    )
    port_b: ReadPort[ProtocolParams, Sample] = QueryBackedReadPort(
        SamplesByProtocolShapeB(),
        CypherExecutor(lambda: FakeGraphSession(RECORDS_SHAPE_B)),
    )

    result_a = port_a.fetch(ProtocolParams(protocol_id=1))
    result_b = port_b.fetch(ProtocolParams(protocol_id=1))

    assert result_a == result_b
    assert result_a == [
        Sample(sample_id="S001", label="alpha"),
        Sample(sample_id="S002", label="beta"),
    ]


def test_swapping_executor_does_not_change_callers_type() -> None:
    """A caller depending on ReadPort[P, D] is unaffected by which executor backs it."""

    def caller(port: ReadPort[ProtocolParams, Sample]) -> list[str]:
        return [s.sample_id for s in port.fetch(ProtocolParams(protocol_id=1))]

    port_a = QueryBackedReadPort(
        SamplesByProtocolShapeA(),
        CypherExecutor(lambda: FakeGraphSession(RECORDS_SHAPE_A)),
    )
    port_b = QueryBackedReadPort(
        SamplesByProtocolShapeB(),
        CypherExecutor(lambda: FakeGraphSession(RECORDS_SHAPE_B)),
    )

    assert caller(port_a) == caller(port_b) == ["S001", "S002"]


def test_ports_are_substitutable_executor_instances() -> None:
    """Both ports satisfy ReadPort and carry distinct Executor instances."""
    ex_a: Executor = CypherExecutor(lambda: FakeGraphSession(RECORDS_SHAPE_A))
    ex_b: Executor = CypherExecutor(lambda: FakeGraphSession(RECORDS_SHAPE_B))

    port_a = QueryBackedReadPort(SamplesByProtocolShapeA(), ex_a)
    port_b = QueryBackedReadPort(SamplesByProtocolShapeB(), ex_b)

    assert isinstance(port_a, ReadPort)
    assert isinstance(port_b, ReadPort)
    assert ex_a is not ex_b
