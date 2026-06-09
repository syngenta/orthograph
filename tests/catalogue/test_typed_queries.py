"""Tests for ReadQuery[P, D] and WriteQuery[P, R] base classes."""

from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.catalogue.typed import Backend, ReadQuery, WriteQuery


class SampleParams(BaseModel):
    protocol_id: int


class SampleOutput(BaseModel):
    sample_id: str
    label: str


def test_import_typed_module() -> None:
    """ReadQuery, WriteQuery, and Backend are importable from typed.py."""
    from orthograph.catalogue.typed import Backend, ReadQuery, WriteQuery  # noqa: F401


def test_read_query_missing_params_raises() -> None:
    """A ReadQuery subclass without Params raises TypeError at class definition time."""
    with pytest.raises(TypeError, match="Params"):

        class BadRead(ReadQuery[SampleParams, SampleOutput]):
            Output = SampleOutput
            name = "bad_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_missing_output_raises() -> None:
    """A ReadQuery subclass without Output raises TypeError at class definition time."""
    with pytest.raises(TypeError, match="Output"):

        class BadRead(ReadQuery[SampleParams, SampleOutput]):
            Params = SampleParams
            name = "bad_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_missing_name_raises() -> None:
    """A ReadQuery subclass without name raises TypeError at class definition time."""
    with pytest.raises(TypeError, match="name"):

        class BadRead(ReadQuery[SampleParams, SampleOutput]):
            Params = SampleParams
            Output = SampleOutput
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_missing_backend_raises() -> None:
    """A ReadQuery subclass without backend raises TypeError at definition time."""
    with pytest.raises(TypeError, match="backend"):

        class BadRead(ReadQuery[SampleParams, SampleOutput]):
            Params = SampleParams
            Output = SampleOutput
            name = "bad_read"

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_non_basemodel_params_raises() -> None:
    """A ReadQuery whose Params is not a BaseModel subclass raises TypeError."""
    with pytest.raises(TypeError, match="Params must be a BaseModel subclass"):

        class BadRead(ReadQuery[SampleParams, SampleOutput]):
            Params = "not a model"  # type: ignore[assignment]
            Output = SampleOutput
            name = "bad_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_non_basemodel_output_raises() -> None:
    """A ReadQuery whose Output is not a BaseModel subclass raises TypeError."""
    with pytest.raises(TypeError, match="Output must be a BaseModel subclass"):

        class BadRead(ReadQuery[SampleParams, SampleOutput]):
            Params = SampleParams
            Output = 123  # type: ignore[assignment]
            name = "bad_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_non_backend_value_raises() -> None:
    """A ReadQuery whose backend is not a Backend value raises TypeError."""
    with pytest.raises(TypeError, match="backend must be a Backend value"):

        class BadRead(ReadQuery[SampleParams, SampleOutput]):
            Params = SampleParams
            Output = SampleOutput
            name = "bad_read"
            backend = "cypher"  # type: ignore[assignment]

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


class ConcreteRead(ReadQuery[SampleParams, SampleOutput]):
    Params = SampleParams
    Output = SampleOutput
    name = "concrete_read"
    backend = Backend.CYPHER

    def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
        return (
            "MATCH (s:Sample) WHERE s.protocol_id = $pid RETURN s.sample_id, s.label",
            {"pid": params.protocol_id},
        )

    def materialize(self, raw: dict[str, Any]) -> SampleOutput:
        return SampleOutput(**raw)


def test_concrete_read_build_returns_non_none() -> None:
    """build() returns a non-None value without requiring any backend session."""
    query = ConcreteRead()
    result = query.build(SampleParams(protocol_id=42))
    assert result is not None


def test_concrete_read_build_no_session_needed() -> None:
    """build() is a pure function — it runs with no executor or connection."""
    query = ConcreteRead()
    cypher, qparams = query.build(SampleParams(protocol_id=7))
    assert isinstance(cypher, str)
    assert isinstance(qparams, dict)


def test_concrete_read_materialize_returns_output_instance() -> None:
    """materialize() maps a raw record dict to the declared Output type."""
    query = ConcreteRead()
    result = query.materialize({"sample_id": "S001", "label": "alpha"})
    assert isinstance(result, SampleOutput)
    assert result.sample_id == "S001"
    assert result.label == "alpha"


def test_write_query_missing_params_raises() -> None:
    """A WriteQuery subclass without Params raises TypeError at definition time."""
    with pytest.raises(TypeError, match="Params"):

        class BadWrite(WriteQuery[SampleParams, int]):
            name = "bad_write"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("CREATE (n:Sample)", {})

            def interpret_result(self, raw: object) -> int:
                return 1


class ConcreteWrite(WriteQuery[SampleParams, int]):
    Params = SampleParams
    name = "concrete_write"
    backend = Backend.CYPHER

    def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
        return ("CREATE (s:Sample {protocol_id: $pid})", {"pid": params.protocol_id})

    def interpret_result(self, raw: object) -> int:
        return 1


def test_write_query_non_basemodel_params_raises() -> None:
    """A WriteQuery whose Params is not a BaseModel subclass raises TypeError."""
    with pytest.raises(TypeError, match="Params must be a BaseModel subclass"):

        class BadWrite(WriteQuery[SampleParams, int]):
            Params = object()  # type: ignore[assignment]
            name = "bad_write"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("CREATE (n:Sample)", {})

            def interpret_result(self, raw: object) -> int:
                return 1


def test_write_query_non_backend_value_raises() -> None:
    """A WriteQuery whose backend is not a Backend value raises TypeError."""
    with pytest.raises(TypeError, match="backend must be a Backend value"):

        class BadWrite(WriteQuery[SampleParams, int]):
            Params = SampleParams
            name = "bad_write"
            backend = "cypher"  # type: ignore[assignment]

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("CREATE (n:Sample)", {})

            def interpret_result(self, raw: object) -> int:
                return 1


def test_write_query_has_no_output_attribute() -> None:
    """WriteQuery subclasses do not require and should not carry an Output ClassVar."""
    assert not hasattr(ConcreteWrite, "Output")


def test_write_query_build_returns_non_none() -> None:
    """build() returns a non-None value without requiring any backend session."""
    query = ConcreteWrite()
    assert query.build(SampleParams(protocol_id=5)) is not None


def test_write_query_interpret_result() -> None:
    """interpret_result() maps the raw driver result to the declared return type."""
    query = ConcreteWrite()
    assert query.interpret_result(object()) == 1


def test_intermediate_abstract_subclass_does_not_raise() -> None:
    """An intermediate class with unimplemented abstract methods is not checked."""

    class AbstractCypherRead(ReadQuery[SampleParams, SampleOutput]):
        pass

    class ConcreteFromIntermediate(AbstractCypherRead):
        Params = SampleParams
        Output = SampleOutput
        name = "concrete_from_intermediate"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    assert ConcreteFromIntermediate.name == "concrete_from_intermediate"
