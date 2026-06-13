"""Tests for Executor ABC, ReadPort, and QueryBackedReadPort."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from orthograph.query.base_models import (
    Backend,
    Executor,
    QueryBackedReadPort,
    ReadPort,
    ReadQuery,
    WriteQuery,
)


class ProtocolParams(BaseModel):
    protocol_id: int


class SampleRecord(BaseModel):
    sample_id: str
    label: str


class ConcreteRead(ReadQuery[ProtocolParams, SampleRecord]):
    Params = ProtocolParams
    Output = SampleRecord
    name = "samples_by_protocol"
    backend = Backend.CYPHER

    def build(self, params: ProtocolParams) -> tuple[str, dict[str, Any]]:
        return (
            "MATCH (s:Sample {protocol_id: $pid}) RETURN s.sample_id, s.label",
            {"pid": params.protocol_id},
        )

    def materialize(self, raw: dict[str, Any]) -> SampleRecord:
        return SampleRecord(**raw)


class ConcreteWrite(WriteQuery[ProtocolParams, int]):
    Params = ProtocolParams
    name = "create_sample"
    backend = Backend.CYPHER

    def build(self, params: ProtocolParams) -> tuple[str, dict[str, Any]]:
        return ("CREATE (s:Sample {protocol_id: $pid})", {"pid": params.protocol_id})

    def materialize(self, raw: object) -> int:
        return 1


def test_import_executor_readport() -> None:
    """Executor, ReadPort, QueryBackedReadPort importable from base_models.py."""
    from orthograph.query.base_models import (  # noqa: F401
        Executor,
        QueryBackedReadPort,
        ReadPort,
    )


def test_executor_cannot_be_instantiated() -> None:
    """Executor is abstract and cannot be instantiated directly."""
    with pytest.raises(TypeError):
        Executor()  # type: ignore[abstract]


def test_read_port_cannot_be_instantiated() -> None:
    """ReadPort is abstract and cannot be instantiated directly."""
    with pytest.raises(TypeError):
        ReadPort()  # type: ignore[abstract]


def test_query_backed_read_port_delegates_to_executor_read() -> None:
    """fetch() calls executor.read() with the bound query and the given params."""
    query = ConcreteRead()
    executor = MagicMock(spec=Executor)
    expected = [SampleRecord(sample_id="S001", label="alpha")]
    executor.read.return_value = expected

    port = QueryBackedReadPort(query, executor)
    result = port.fetch(ProtocolParams(protocol_id=42))

    executor.read.assert_called_once_with(query, ProtocolParams(protocol_id=42))
    assert result == expected


def test_two_ports_with_same_output_satisfy_same_read_port_annotation() -> None:
    """Two ports with different executors satisfy the same ReadPort annotation.

    The static half of the claim (both QueryBackedReadPort instances are
    assignable to ``ReadPort[ProtocolParams, SampleRecord]``) is enforced by
    mypy on the annotations below. The runtime half is asserted here: both are
    ReadPort instances and are interchangeable in a single typed container.
    """
    executor_a = MagicMock(spec=Executor)
    executor_b = MagicMock(spec=Executor)

    port_a: ReadPort[ProtocolParams, SampleRecord] = QueryBackedReadPort(
        ConcreteRead(), executor_a
    )
    port_b: ReadPort[ProtocolParams, SampleRecord] = QueryBackedReadPort(
        ConcreteRead(), executor_b
    )

    assert isinstance(port_a, ReadPort)
    assert isinstance(port_b, ReadPort)

    # Both ports drop into one container declared against the shared annotation,
    # demonstrating they are mutually substitutable behind ReadPort[P, D].
    ports: list[ReadPort[ProtocolParams, SampleRecord]] = [port_a, port_b]
    assert all(isinstance(port, ReadPort) for port in ports)
    assert all(isinstance(port, QueryBackedReadPort) for port in ports)


def test_fetch_returns_executor_read_result() -> None:
    """fetch() returns exactly the list that executor.read() produces."""
    query = ConcreteRead()
    executor = MagicMock(spec=Executor)
    records = [
        SampleRecord(sample_id="X1", label="foo"),
        SampleRecord(sample_id="X2", label="bar"),
    ]
    executor.read.return_value = records

    port = QueryBackedReadPort(query, executor)
    assert port.fetch(ProtocolParams(protocol_id=1)) is records
