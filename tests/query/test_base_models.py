"""Tests for ReadQuery[P, D] and WriteQuery[P, R] base classes."""

from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.query.base_models import Backend, ReadQuery, WriteQuery


class SampleParams(BaseModel):
    protocol_id: int


class SampleOutput(BaseModel):
    sample_id: str
    label: str


def test_import_base_models_module() -> None:
    """ReadQuery, WriteQuery, and Backend are importable from base_models.py."""
    from orthograph.query.base_models import (  # noqa: F401
        Backend,
        ReadQuery,
        WriteQuery,
    )


def test_read_query_missing_params_raises() -> None:
    """A ReadQuery subclass without Params raises TypeError at class definition time.

    Post-T6: use an unparameterised base so no auto-population fires.
    """
    with pytest.raises(TypeError, match="Params"):

        class BadRead(ReadQuery):  # type: ignore[type-arg]
            Output = SampleOutput
            name = "bad_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_missing_output_raises() -> None:
    """A ReadQuery subclass without Output raises TypeError at class definition time.

    Post-T6: use an unparameterised base so no auto-population fires.
    """
    with pytest.raises(TypeError, match="Output"):

        class BadRead(ReadQuery):  # type: ignore[type-arg]
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
    """A ReadQuery whose Params is not a BaseModel subclass raises TypeError.

    Post-T6: use an unparameterised base so the bad Params value reaches
    _enforce_query_contract directly.
    """
    with pytest.raises(TypeError, match="Params must be a BaseModel subclass"):

        class BadRead(ReadQuery):  # type: ignore[type-arg]
            Params = "not a model"  # type: ignore[assignment]
            Output = SampleOutput
            name = "bad_read"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_read_query_non_basemodel_output_raises() -> None:
    """A ReadQuery whose Output is not a BaseModel subclass raises TypeError.

    Post-T6: use an unparameterised base so the bad Output value reaches
    _enforce_query_contract directly.
    """
    with pytest.raises(TypeError, match="Output must be a BaseModel subclass"):

        class BadRead(ReadQuery):  # type: ignore[type-arg]
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
    """A WriteQuery subclass without Params raises TypeError at definition time.

    Post-T6: use an unparameterised base so no auto-population fires.
    """
    with pytest.raises(TypeError, match="Params"):

        class BadWrite(WriteQuery):  # type: ignore[type-arg]
            name = "bad_write"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("CREATE (n:Sample)", {})

            def interpret_result(self, raw: object) -> int:
                return 1


class ConcreteWrite(WriteQuery[SampleParams, int]):
    name = "concrete_write"
    backend = Backend.CYPHER

    def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
        return ("CREATE (s:Sample {protocol_id: $pid})", {"pid": params.protocol_id})

    def interpret_result(self, raw: object) -> int:
        return 1


def test_write_query_non_basemodel_params_raises() -> None:
    """A WriteQuery whose Params is not a BaseModel subclass raises TypeError.

    Post-T6: use an unparameterised base so the bad Params value reaches
    _enforce_query_contract directly.
    """
    with pytest.raises(TypeError, match="Params must be a BaseModel subclass"):

        class BadWrite(WriteQuery):  # type: ignore[type-arg]
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


def test_write_query_output_defaults_to_none() -> None:
    """WriteQuery subclasses have Output defaulting to None if not explicitly set."""
    assert hasattr(ConcreteWrite, "Output")
    assert ConcreteWrite.Output is None


def test_write_query_with_explicit_output() -> None:
    """A WriteQuery subclass can explicitly declare an Output model."""

    class WriteWithOutput(WriteQuery[SampleParams, dict[str, int]]):
        Params = SampleParams
        Output = SampleOutput
        name = "write_with_output"
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


def test_write_interpret_result_is_abstract() -> None:
    """WriteQuery.interpret_result is abstract;
    attempting instantiation raises TypeError."""

    class BadWrite(WriteQuery[SampleParams, int]):
        Params = SampleParams
        name = "bad_write_no_interpret"
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
    """ReadQuery[P, D] subclass with no explicit Params gets Params = P."""

    class AutoRead(ReadQuery[SampleParams, SampleOutput]):
        Output = SampleOutput
        name = "auto_read_params"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    assert AutoRead.Params is SampleParams


def test_read_query_auto_populates_output_from_generic_arg() -> None:
    """ReadQuery[P, D] subclass with no explicit Output gets Output = D."""

    class AutoRead(ReadQuery[SampleParams, SampleOutput]):
        Params = SampleParams
        name = "auto_read_output"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    assert AutoRead.Output is SampleOutput


def test_read_query_auto_populates_both_from_generic_args() -> None:
    """ReadQuery[P, D] subclass with no ClassVar assignments gets both auto-set."""

    class AutoRead(ReadQuery[SampleParams, SampleOutput]):
        name = "auto_read_both"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    assert AutoRead.Params is SampleParams
    assert AutoRead.Output is SampleOutput


def test_write_query_auto_populates_params_from_generic_arg() -> None:
    """WriteQuery[P, R] subclass with no explicit Params gets Params = P."""

    class AutoWrite(WriteQuery[SampleParams, int]):
        name = "auto_write"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("CREATE (n:Sample)", {})

        def interpret_result(self, raw: object) -> int:
            return 1

    assert AutoWrite.Params is SampleParams


def test_read_query_explicit_classvar_matching_generic_accepted() -> None:
    """Explicit Params/Output that matches the generic arg is accepted (no error)."""

    class ExplicitMatch(ReadQuery[SampleParams, SampleOutput]):
        Params = SampleParams
        Output = SampleOutput
        name = "explicit_match"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    assert ExplicitMatch.Params is SampleParams
    assert ExplicitMatch.Output is SampleOutput


def test_read_query_explicit_params_conflicting_with_generic_raises() -> None:
    """Explicit Params that differs from the generic arg raises TypeError."""

    class OtherParams(BaseModel):
        other: str

    with pytest.raises(TypeError, match="Params"):

        class ConflictRead(ReadQuery[SampleParams, SampleOutput]):
            Params = OtherParams
            Output = SampleOutput
            name = "conflict_read"
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

        class ConflictRead(ReadQuery[SampleParams, SampleOutput]):
            Params = SampleParams
            Output = OtherOutput
            name = "conflict_read_output"
            backend = Backend.CYPHER

            def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
                return ("MATCH (n) RETURN n", {})

            def materialize(self, raw: dict[str, Any]) -> SampleOutput:
                return SampleOutput(**raw)


def test_subclass_of_subclass_inherits_classvars_without_re_declaring() -> None:
    """A subclass of a concrete ReadQuery inherits Params/Output without needing
    to re-declare them and without triggering the conflict check."""

    class Base(ReadQuery[SampleParams, SampleOutput]):
        name = "base_q"
        backend = Backend.CYPHER

        def build(self, params: SampleParams) -> tuple[str, dict[str, Any]]:
            return ("MATCH (n) RETURN n", {})

        def materialize(self, raw: dict[str, Any]) -> SampleOutput:
            return SampleOutput(**raw)

    class Child(Base):
        name = "child_q"

    assert Child.Params is SampleParams
    assert Child.Output is SampleOutput
