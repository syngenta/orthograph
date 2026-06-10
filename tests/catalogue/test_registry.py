"""Tests for QueryCatalogue and QueryDescription (T5).

The catalogue is a typed object registry: it stores ReadQuery / WriteQuery
instances and introspects them via describe(). Queries reference their Output
model by direct import — there is no string-key model lookup.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.catalogue.registry import QueryCatalogue, QueryDescription
from orthograph.catalogue.typed import Backend, ReadQuery, WriteQuery


class ProtocolParams(BaseModel):
    protocol_id: int


class SampleOutput(BaseModel):
    sample_id: str
    label: str


class SamplesByProtocol(ReadQuery[ProtocolParams, SampleOutput]):
    Params = ProtocolParams
    Output = SampleOutput
    name = "samples_by_protocol"
    backend = Backend.CYPHER

    def build(self, params: ProtocolParams) -> tuple[str, dict[str, Any]]:
        return ("MATCH (s:Sample) RETURN s", {"pid": params.protocol_id})

    def materialize(self, raw: dict[str, Any]) -> SampleOutput:
        return SampleOutput(**raw)


class SamplesByProtocolSql(ReadQuery[ProtocolParams, SampleOutput]):
    """Same logical read, different backend, identical Output type."""

    Params = ProtocolParams
    Output = SampleOutput
    name = "samples_by_protocol_sql"
    backend = Backend.SQLALCHEMY

    def build(self, params: ProtocolParams) -> str:
        return "SELECT sample_id, label FROM sample"

    def materialize(self, raw: dict[str, Any]) -> SampleOutput:
        return SampleOutput(**raw)


class CreateSample(WriteQuery[ProtocolParams, int]):
    Params = ProtocolParams
    name = "create_sample"
    backend = Backend.CYPHER

    def build(self, params: ProtocolParams) -> tuple[str, dict[str, Any]]:
        return ("CREATE (s:Sample {protocol_id: $pid})", {"pid": params.protocol_id})

    def interpret_result(self, raw: object) -> int:
        return 1


def test_import_registry() -> None:
    """QueryCatalogue and QueryDescription import from registry.py."""
    from orthograph.catalogue.registry import (  # noqa: F401
        QueryCatalogue,
        QueryDescription,
    )


def test_register_read_returns_the_query() -> None:
    """register_read returns the registered query (usable as a decorator-ish handle)."""
    cat = QueryCatalogue()
    q = SamplesByProtocol()
    assert cat.register_read(q) is q


def test_register_write_returns_the_query() -> None:
    """register_write returns the registered query."""
    cat = QueryCatalogue()
    q = CreateSample()
    assert cat.register_write(q) is q


def test_describe_returns_read_and_write() -> None:
    """describe() returns one QueryDescription per registered query."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())
    cat.register_write(CreateSample())

    descriptions = {d.name: d for d in cat.describe()}

    assert set(descriptions) == {"samples_by_protocol", "create_sample"}
    assert all(isinstance(d, QueryDescription) for d in descriptions.values())


def test_describe_read_has_correct_kind_and_backend() -> None:
    """A registered read is described with kind='read' and its backend."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())

    (read_desc,) = cat.describe()
    assert read_desc.kind == "read"
    assert read_desc.backend == Backend.CYPHER


def test_describe_write_has_correct_kind_and_backend() -> None:
    """A registered write is described with kind='write' and its backend."""
    cat = QueryCatalogue()
    cat.register_write(CreateSample())

    (write_desc,) = cat.describe()
    assert write_desc.kind == "write"
    assert write_desc.backend == Backend.CYPHER


def test_read_params_and_output_schema_present() -> None:
    """A read's params_schema and output_schema match the model JSON schemas."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())

    (read_desc,) = cat.describe()
    assert read_desc.params_schema == ProtocolParams.model_json_schema()
    assert read_desc.output_schema == SampleOutput.model_json_schema()


def test_write_output_schema_is_none() -> None:
    """A write has output_schema=None (writes declare no Output)."""
    cat = QueryCatalogue()
    cat.register_write(CreateSample())

    (write_desc,) = cat.describe()
    assert write_desc.output_schema is None
    assert write_desc.params_schema == ProtocolParams.model_json_schema()


def test_duplicate_read_name_raises_value_error() -> None:
    """Registering two reads with the same name raises ValueError."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())
    with pytest.raises(ValueError, match="samples_by_protocol"):
        cat.register_read(SamplesByProtocol())


def test_duplicate_write_name_raises_value_error() -> None:
    """Registering two writes with the same name raises ValueError."""
    cat = QueryCatalogue()
    cat.register_write(CreateSample())
    with pytest.raises(ValueError, match="create_sample"):
        cat.register_write(CreateSample())


def test_read_and_write_sharing_a_name_raises_value_error() -> None:
    """A read and a write cannot share a name within one catalogue."""

    class ClashingWrite(WriteQuery[ProtocolParams, int]):
        Params = ProtocolParams
        name = "samples_by_protocol"  # same name as the read
        backend = Backend.CYPHER

        def build(self, params: ProtocolParams) -> tuple[str, dict[str, Any]]:
            return ("CREATE (s:Sample)", {})

        def interpret_result(self, raw: object) -> int:
            return 1

    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())
    with pytest.raises(ValueError, match="samples_by_protocol"):
        cat.register_write(ClashingWrite())


def test_names_lists_all_registered_names() -> None:
    """names() returns every registered query name (reads and writes)."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())
    cat.register_write(CreateSample())
    assert sorted(cat.names()) == ["create_sample", "samples_by_protocol"]


def test_two_backends_same_logical_read_share_output_schema() -> None:
    """Two backends for the same logical read expose identical output_schema."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())  # CYPHER
    cat.register_read(SamplesByProtocolSql())  # SQLALCHEMY

    by_name = {d.name: d for d in cat.describe()}
    cypher = by_name["samples_by_protocol"]
    sql = by_name["samples_by_protocol_sql"]

    assert cypher.backend != sql.backend
    assert cypher.output_schema == sql.output_schema


def test_describe_filtered_by_backend() -> None:
    """describe(backend=...) returns only queries targeting that backend."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())  # CYPHER read
    cat.register_read(SamplesByProtocolSql())  # SQLALCHEMY read
    cat.register_write(CreateSample())  # CYPHER write

    cypher = cat.describe(backend=Backend.CYPHER)
    assert {d.name for d in cypher} == {"samples_by_protocol", "create_sample"}
    assert all(d.backend == Backend.CYPHER for d in cypher)

    sql = cat.describe(backend=Backend.SQLALCHEMY)
    assert {d.name for d in sql} == {"samples_by_protocol_sql"}


def test_describe_no_backend_returns_all() -> None:
    """describe() with no backend returns every query (unchanged behaviour)."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())
    cat.register_read(SamplesByProtocolSql())
    cat.register_write(CreateSample())
    assert len(cat.describe()) == 3


def test_describe_filter_with_no_matches_returns_empty() -> None:
    """describe(backend=...) returns [] when no query targets that backend."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())  # CYPHER only
    assert cat.describe(backend=Backend.GQLALCHEMY) == []


def test_names_filtered_by_backend() -> None:
    """names(backend=...) returns only names of queries targeting that backend."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())  # CYPHER
    cat.register_read(SamplesByProtocolSql())  # SQLALCHEMY
    cat.register_write(CreateSample())  # CYPHER

    assert sorted(cat.names(backend=Backend.CYPHER)) == [
        "create_sample",
        "samples_by_protocol",
    ]
    assert cat.names(backend=Backend.SQLALCHEMY) == ["samples_by_protocol_sql"]


def test_names_no_backend_returns_all() -> None:
    """names() with no backend returns every name (unchanged behaviour)."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())
    cat.register_write(CreateSample())
    assert sorted(cat.names()) == ["create_sample", "samples_by_protocol"]


def test_queries_returns_registered_instances() -> None:
    """queries() returns the registered query objects (reads then writes)."""
    cat = QueryCatalogue()
    read = SamplesByProtocol()
    write = CreateSample()
    cat.register_read(read)
    cat.register_write(write)
    assert cat.queries() == [read, write]


def test_queries_filtered_by_backend() -> None:
    """queries(backend=...) returns only instances targeting that backend."""
    cat = QueryCatalogue()
    cat.register_read(SamplesByProtocol())  # CYPHER
    sql = SamplesByProtocolSql()  # SQLALCHEMY
    cat.register_read(sql)
    assert cat.queries(backend=Backend.SQLALCHEMY) == [sql]
