"""Tests for ReadQueryModel[P, D] and WriteQueryModel[P, R] base classes."""

from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.query.base_models import Backend, ReadQueryModel, WriteQueryModel


class SampleParams(BaseModel):
    protocol_id: int


class SampleOutput(BaseModel):
    sample_id: str
    label: str


def test_import_base_models_module() -> None:
    """Import ReadQueryModel, WriteQueryModel, and Backend."""
    from orthograph.query.base_models import (  # noqa: F401
        Backend,
        ReadQueryModel,
        WriteQueryModel,
    )


def test_read_query_missing_params_raises() -> None:
    """ReadQueryModel missing Params raises TypeError at class definition time.

    Post-T6: use an unparameterised base so no auto-population fires.
    """
    with pytest.raises(TypeError, match="params_schema"):

        class BadRead(ReadQueryModel):  # type: ignore[type-arg]
            Output = SampleOutput
            query_id = "bad_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_missing_output_raises() -> None:
    """ReadQueryModel missing Output raises TypeError at class definition time.

    Post-T6: use an unparameterised base so no auto-population fires.
    """
    with pytest.raises(TypeError, match="Output"):

        class BadRead(ReadQueryModel):  # type: ignore[type-arg]
            params_schema = SampleParams
            query_id = "bad_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_missing_name_raises() -> None:
    """ReadQueryModel missing query_id raises TypeError at definition time."""
    with pytest.raises(TypeError, match="query_id"):

        class BadRead(ReadQueryModel[SampleParams, SampleOutput]):
            params_schema = SampleParams
            Output = SampleOutput
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_missing_backend_raises() -> None:
    """A ReadQueryModel subclass without backend raises TypeError at definition time."""
    with pytest.raises(TypeError, match="backend"):

        class BadRead(ReadQueryModel[SampleParams, SampleOutput]):
            params_schema = SampleParams
            Output = SampleOutput
            query_id = "bad_read"

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_non_basemodel_params_raises() -> None:
    """A ReadQueryModel whose Params is not a BaseModel subclass raises TypeError.

    Post-T6: use an unparameterised base so the bad Params value reaches
    _enforce_query_contract directly.
    """
    with pytest.raises(TypeError, match="params_schema must be a BaseModel subclass"):

        class BadRead(ReadQueryModel):  # type: ignore[type-arg]
            params_schema = "not a model"  # type: ignore[assignment]
            Output = SampleOutput
            query_id = "bad_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_non_basemodel_output_raises() -> None:
    """A ReadQueryModel whose Output is not a BaseModel subclass raises TypeError.

    Post-T6: use an unparameterised base so the bad Output value reaches
    _enforce_query_contract directly.
    """
    with pytest.raises(TypeError, match="Output must be a BaseModel subclass"):

        class BadRead(ReadQueryModel):  # type: ignore[type-arg]
            params_schema = SampleParams
            Output = 123  # type: ignore[assignment]
            query_id = "bad_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_non_backend_value_raises() -> None:
    """A ReadQueryModel whose backend is not a Backend value raises TypeError."""
    with pytest.raises(TypeError, match="backend must be a Backend value"):

        class BadRead(ReadQueryModel[SampleParams, SampleOutput]):
            params_schema = SampleParams
            Output = SampleOutput
            query_id = "bad_read"
            backend = "cypher"  # type: ignore[assignment]

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


class ConcreteRead(ReadQueryModel[SampleParams, SampleOutput]):
    query_id = "concrete_read"
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
    """A WriteQueryModel subclass without Params raises TypeError at definition time.

    Post-T6: use an unparameterised base so no auto-population fires.
    """
    with pytest.raises(TypeError, match="params_schema"):

        class BadWrite(WriteQueryModel):  # type: ignore[type-arg]
            query_id = "bad_write"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("CREATE (n:Sample)", {})

            def interpret_result(self, raw: object) -> int:
                return 1


class ConcreteWrite(WriteQueryModel[SampleParams, int]):
    query_id = "concrete_write"
    backend = Backend.CYPHER

    def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
        return ("CREATE (s:Sample {protocol_id: $pid})", {"pid": params.protocol_id})

    def interpret_result(self, raw: object) -> int:
        return 1


def test_write_query_non_basemodel_params_raises() -> None:
    """A WriteQueryModel whose Params is not a BaseModel subclass raises TypeError.

    Post-T6: use an unparameterised base so the bad Params value reaches
    _enforce_query_contract directly.
    """
    with pytest.raises(TypeError, match="params_schema must be a BaseModel subclass"):

        class BadWrite(WriteQueryModel):  # type: ignore[type-arg]
            params_schema = object()  # type: ignore[assignment]
            query_id = "bad_write"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("CREATE (n:Sample)", {})

            def interpret_result(self, raw: object) -> int:
                return 1


def test_write_query_non_backend_value_raises() -> None:
    """A WriteQueryModel whose backend is not a Backend value raises TypeError."""
    with pytest.raises(TypeError, match="backend must be a Backend value"):

        class BadWrite(WriteQueryModel[SampleParams, int]):
            params_schema = SampleParams
            query_id = "bad_write"
            backend = "cypher"  # type: ignore[assignment]

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("CREATE (n:Sample)", {})

            def interpret_result(self, raw: object) -> int:
                return 1


def test_write_query_output_defaults_to_none() -> None:
    """WriteQueryModel has Output defaulting to None if not explicitly set."""
    assert hasattr(ConcreteWrite, "Output")
    assert ConcreteWrite.Output is None


def test_write_query_with_explicit_output() -> None:
    """A WriteQueryModel subclass can explicitly declare an Output model."""

    class WriteWithOutput(WriteQueryModel[SampleParams, dict[str, int]]):
        params_schema = SampleParams
        Output = SampleOutput
        query_id = "write_with_output"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return (
                "CREATE (s:Sample {protocol_id: $pid})",
                {"pid": params.protocol_id},
            )

        def interpret_result(self, raw: object) -> dict[str, int]:
            return {"created": 1}

    assert WriteWithOutput.Output is SampleOutput


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

    class AbstractCypherRead(ReadQueryModel[SampleParams, SampleOutput]):
        pass

    class ConcreteFromIntermediate(AbstractCypherRead):
        params_schema = SampleParams
        Output = SampleOutput
        query_id = "concrete_from_intermediate"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    assert ConcreteFromIntermediate.query_id == "concrete_from_intermediate"


def test_write_interpret_result_is_abstract() -> None:
    """WriteQueryModel.interpret_result is abstract;
    attempting instantiation raises TypeError."""

    class BadWrite(WriteQueryModel[SampleParams, int]):
        params_schema = SampleParams
        query_id = "bad_write_no_interpret"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("CREATE (n:Sample)", {})

    # Attempting to instantiate the abstract subclass raises TypeError
    with pytest.raises(TypeError, match="interpret_result"):
        BadWrite()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# T6: Auto-populate Params/Output from generic args
# ---------------------------------------------------------------------------


def test_read_query_auto_populates_params_from_generic_arg() -> None:
    """ReadQueryModel[P, D] subclass with no explicit Params gets Params = P."""

    class AutoRead(ReadQueryModel[SampleParams, SampleOutput]):
        Output = SampleOutput
        query_id = "auto_read_params"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    assert AutoRead.params_schema is SampleParams


def test_read_query_auto_populates_output_from_generic_arg() -> None:
    """ReadQueryModel[P, D] subclass with no explicit Output gets Output = D."""

    class AutoRead(ReadQueryModel[SampleParams, SampleOutput]):
        params_schema = SampleParams
        query_id = "auto_read_output"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    assert AutoRead.Output is SampleOutput


def test_read_query_auto_populates_both_from_generic_args() -> None:
    """ReadQueryModel[P, D] subclass with no ClassVar assignments gets both auto-set."""

    class AutoRead(ReadQueryModel[SampleParams, SampleOutput]):
        query_id = "auto_read_both"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    assert AutoRead.params_schema is SampleParams
    assert AutoRead.Output is SampleOutput


def test_write_query_auto_populates_params_from_generic_arg() -> None:
    """WriteQueryModel[P, R] subclass with no explicit Params gets Params = P."""

    class AutoWrite(WriteQueryModel[SampleParams, int]):
        query_id = "auto_write"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("CREATE (n:Sample)", {})

        def interpret_result(self, raw: object) -> int:
            return 1

    assert AutoWrite.params_schema is SampleParams


def test_read_query_explicit_classvar_matching_generic_accepted() -> None:
    """Explicit Params/Output that matches the generic arg is accepted (no error)."""

    class ExplicitMatch(ReadQueryModel[SampleParams, SampleOutput]):
        params_schema = SampleParams
        Output = SampleOutput
        query_id = "explicit_match"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    assert ExplicitMatch.params_schema is SampleParams
    assert ExplicitMatch.Output is SampleOutput


def test_read_query_explicit_params_conflicting_with_generic_raises() -> None:
    """Explicit Params that differs from the generic arg raises TypeError."""

    class OtherParams(BaseModel):
        other: str

    with pytest.raises(TypeError, match="params_schema"):

        class ConflictRead(ReadQueryModel[SampleParams, SampleOutput]):
            params_schema = OtherParams
            Output = SampleOutput
            query_id = "conflict_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_explicit_output_conflicting_with_generic_raises() -> None:
    """Explicit Output that differs from the generic arg raises TypeError."""

    class OtherOutput(BaseModel):
        other: str

    with pytest.raises(TypeError, match="Output"):

        class ConflictRead(ReadQueryModel[SampleParams, SampleOutput]):
            params_schema = SampleParams
            Output = OtherOutput
            query_id = "conflict_read_output"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_subclass_of_subclass_inherits_classvars_without_re_declaring() -> None:
    """A subclass of a concrete ReadQueryModel inherits Params/Output without needing
    to re-declare them and without triggering the conflict check."""

    class Base(ReadQueryModel[SampleParams, SampleOutput]):
        query_id = "base_q"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    class Child(Base):
        query_id = "child_q"

    assert Child.params_schema is SampleParams
    assert Child.Output is SampleOutput
