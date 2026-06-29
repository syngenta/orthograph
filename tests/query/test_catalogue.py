"""Tests for QueryCatalogue and QueryDescription.

The catalogue is a typed object registry: it stores ReadQueryModel / WriteQueryModel
instances and introspects them via describe(). Queries reference their Output
model by direct import — there is no string-key model lookup.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.query.base_models import Backend, ReadQueryModel, WriteQueryModel
from orthograph.query.catalogue import QueryCatalogue, QueryDescription


class ProtocolParams(BaseModel):
    protocol_id: int


class SampleOutput(BaseModel):
    sample_id: str
    label: str


class SamplesByProtocol(ReadQueryModel[ProtocolParams, SampleOutput]):
    params_schema = ProtocolParams
    Output = SampleOutput
    query_id = "samples_by_protocol"
    backend = Backend.CYPHER

    def build(self, params: ProtocolParams) -> tuple[str, dict[str, Any]]:
        return ("MATCH (s:Sample) RETURN s", {"pid": params.protocol_id})

    def materialize(self, raw: dict[str, Any]) -> SampleOutput:
        return SampleOutput(**raw)


class SamplesByProtocolSql(ReadQueryModel[ProtocolParams, SampleOutput]):
    """Same logical read, different backend, identical Output type."""

    params_schema = ProtocolParams
    Output = SampleOutput
    query_id = "samples_by_protocol_sql"
    backend = Backend.SQLALCHEMY

    def build(self, params: ProtocolParams) -> str:
        return "SELECT sample_id, label FROM sample"

    def materialize(self, raw: dict[str, Any]) -> SampleOutput:
        return SampleOutput(**raw)


class CreateSample(WriteQueryModel[ProtocolParams, int]):
    params_schema = ProtocolParams
    query_id = "create_sample"
    backend = Backend.CYPHER

    def build(self, params: ProtocolParams) -> tuple[str, dict[str, Any]]:
        return ("CREATE (s:Sample {protocol_id: $pid})", {"pid": params.protocol_id})

    def interpret_result(self, raw: object) -> int:
        return 1


class CreateSampleWithOutput(WriteQueryModel[ProtocolParams, dict[str, Any]]):
    params_schema = ProtocolParams
    Output = SampleOutput
    query_id = "create_sample_with_output"
    backend = Backend.CYPHER

    def build(self, params: ProtocolParams) -> tuple[str, dict[str, Any]]:
        return ("CREATE (s:Sample {protocol_id: $pid})", {"pid": params.protocol_id})

    def interpret_result(self, raw: object) -> dict[str, Any]:
        return {"sample_id": "S001", "label": "new"}


def test_import_catalogue_module() -> None:
    """QueryCatalogue and QueryDescription import from catalogue.py."""
    from orthograph.query.catalogue import (  # noqa: F401
        QueryCatalogue,
        QueryDescription,
    )


def test_register_read_returns_the_query() -> None:
    """register_read returns the registered query (usable as a decorator-ish handle)."""
    query_catalogue = QueryCatalogue()
    q = SamplesByProtocol()
    assert query_catalogue.register_read(q) is q


def test_register_write_returns_the_query() -> None:
    """register_write returns the registered query."""
    query_catalogue = QueryCatalogue()
    q = CreateSample()
    assert query_catalogue.register_write(q) is q


def test_describe_returns_read_and_write() -> None:
    """describe() returns one QueryDescription per registered query."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())
    query_catalogue.register_write(CreateSample())

    descriptions = {d.query_id: d for d in query_catalogue.describe()}

    assert set(descriptions) == {"samples_by_protocol", "create_sample"}
    assert all(isinstance(d, QueryDescription) for d in descriptions.values())


def test_describe_read_has_correct_kind_and_backend() -> None:
    """A registered read is described with kind='read' and its backend."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())

    (read_desc,) = query_catalogue.describe()
    assert read_desc.kind == "read"
    assert read_desc.backend == Backend.CYPHER


def test_describe_write_has_correct_kind_and_backend() -> None:
    """A registered write is described with kind='write' and its backend."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_write(CreateSample())

    (write_desc,) = query_catalogue.describe()
    assert write_desc.kind == "write"
    assert write_desc.backend == Backend.CYPHER


def test_read_params_and_output_schema_present() -> None:
    """A read's params_schema and output_schema match the model JSON schemas."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())

    (read_desc,) = query_catalogue.describe()
    assert read_desc.params_schema == ProtocolParams.model_json_schema()
    assert read_desc.output_schema == SampleOutput.model_json_schema()


def test_write_output_schema_is_none() -> None:
    """A write has output_schema=None (writes declare no Output)."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_write(CreateSample())

    (write_desc,) = query_catalogue.describe()
    assert write_desc.output_schema is None
    assert write_desc.params_schema == ProtocolParams.model_json_schema()


def test_write_with_explicit_output_has_schema() -> None:
    """A write that declares an Output has its schema in the description."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_write(CreateSampleWithOutput())

    (write_desc,) = query_catalogue.describe()
    assert write_desc.output_schema == SampleOutput.model_json_schema()
    assert write_desc.params_schema == ProtocolParams.model_json_schema()


def test_duplicate_read_name_raises_value_error() -> None:
    """Registering two reads with the same name raises ValueError."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())
    with pytest.raises(ValueError, match="samples_by_protocol"):
        query_catalogue.register_read(SamplesByProtocol())


def test_duplicate_write_name_raises_value_error() -> None:
    """Registering two writes with the same name raises ValueError."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_write(CreateSample())
    with pytest.raises(ValueError, match="create_sample"):
        query_catalogue.register_write(CreateSample())


def test_read_and_write_sharing_a_name_raises_value_error() -> None:
    """A read and a write cannot share a name within one catalogue."""

    class ClashingWrite(WriteQueryModel[ProtocolParams, int]):
        params_schema = ProtocolParams
        query_id = "samples_by_protocol"  # same name as the read
        backend = Backend.CYPHER

        def build(self, params: ProtocolParams) -> tuple[str, dict[str, Any]]:
            return ("CREATE (s:Sample)", {})

        def interpret_result(self, raw: object) -> int:
            return 1

    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())
    with pytest.raises(ValueError, match="samples_by_protocol"):
        query_catalogue.register_write(ClashingWrite())


def test_names_lists_all_registered_names() -> None:
    """names() returns every registered query name (reads and writes)."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())
    query_catalogue.register_write(CreateSample())
    assert sorted(query_catalogue.names()) == ["create_sample", "samples_by_protocol"]


def test_two_backends_same_logical_read_share_output_schema() -> None:
    """Two backends for the same logical read expose identical output_schema."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())  # CYPHER
    query_catalogue.register_read(SamplesByProtocolSql())  # SQLALCHEMY

    by_name = {d.query_id: d for d in query_catalogue.describe()}
    cypher = by_name["samples_by_protocol"]
    sql = by_name["samples_by_protocol_sql"]

    assert cypher.backend != sql.backend
    assert cypher.output_schema == sql.output_schema


def test_describe_filtered_by_backend() -> None:
    """describe(backend=...) returns only queries targeting that backend."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())  # CYPHER read
    query_catalogue.register_read(SamplesByProtocolSql())  # SQLALCHEMY read
    query_catalogue.register_write(CreateSample())  # CYPHER write

    cypher = query_catalogue.describe(backend=Backend.CYPHER)
    assert {d.query_id for d in cypher} == {"samples_by_protocol", "create_sample"}
    assert all(d.backend == Backend.CYPHER for d in cypher)

    sql = query_catalogue.describe(backend=Backend.SQLALCHEMY)
    assert {d.query_id for d in sql} == {"samples_by_protocol_sql"}


def test_describe_no_backend_returns_all() -> None:
    """describe() with no backend returns every query (unchanged behaviour)."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())
    query_catalogue.register_read(SamplesByProtocolSql())
    query_catalogue.register_write(CreateSample())
    assert len(query_catalogue.describe()) == 3


def test_describe_filter_with_no_matches_returns_empty() -> None:
    """describe(backend=...) returns [] when no query targets that backend."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())  # CYPHER only
    assert query_catalogue.describe(backend=Backend.GQLALCHEMY) == []


def test_names_filtered_by_backend() -> None:
    """names(backend=...) returns only names of queries targeting that backend."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())  # CYPHER
    query_catalogue.register_read(SamplesByProtocolSql())  # SQLALCHEMY
    query_catalogue.register_write(CreateSample())  # CYPHER

    assert sorted(query_catalogue.names(backend=Backend.CYPHER)) == [
        "create_sample",
        "samples_by_protocol",
    ]
    assert query_catalogue.names(backend=Backend.SQLALCHEMY) == [
        "samples_by_protocol_sql"
    ]


def test_names_no_backend_returns_all() -> None:
    """names() with no backend returns every name (unchanged behaviour)."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())
    query_catalogue.register_write(CreateSample())
    assert sorted(query_catalogue.names()) == ["create_sample", "samples_by_protocol"]


def test_queries_returns_registered_instances() -> None:
    """queries() returns the registered query objects (reads then writes)."""
    query_catalogue = QueryCatalogue()
    read = SamplesByProtocol()
    write = CreateSample()
    query_catalogue.register_read(read)
    query_catalogue.register_write(write)
    assert query_catalogue.queries() == [read, write]


def test_queries_filtered_by_backend() -> None:
    """queries(backend=...) returns only instances targeting that backend."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())  # CYPHER
    sql = SamplesByProtocolSql()  # SQLALCHEMY
    query_catalogue.register_read(sql)
    assert query_catalogue.queries(backend=Backend.SQLALCHEMY) == [sql]


def test_read_output_class_is_the_actual_class() -> None:
    """A read's output_class is the Output model class (not the JSON schema dict)."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())

    (read_desc,) = query_catalogue.describe()
    assert read_desc.output_class is SampleOutput
    assert isinstance(read_desc.output_class, type)
    assert issubclass(read_desc.output_class, BaseModel)


def test_write_without_output_has_none_output_class() -> None:
    """A write without Output has output_class=None."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_write(CreateSample())

    (write_desc,) = query_catalogue.describe()
    assert write_desc.output_class is None


def test_write_with_output_has_output_class() -> None:
    """A write with explicit Output has output_class set to the Output model."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_write(CreateSampleWithOutput())

    (write_desc,) = query_catalogue.describe()
    assert write_desc.output_class is SampleOutput
    assert isinstance(write_desc.output_class, type)
    assert issubclass(write_desc.output_class, BaseModel)


def test_output_class_separate_from_output_schema() -> None:
    """output_class (the class) and output_schema (the dict) are both present."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())

    (read_desc,) = query_catalogue.describe()
    assert read_desc.output_class is SampleOutput
    assert read_desc.output_schema == SampleOutput.model_json_schema()
    assert isinstance(read_desc.output_schema, dict)
    assert isinstance(read_desc.output_class, type)


# ---------------------------------------------------------------------------
# get(name) — single-query lookup
# ---------------------------------------------------------------------------


def test_get_returns_description_for_registered_read() -> None:
    """get(name) returns the QueryDescription for a registered read query."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())

    desc = query_catalogue.get("samples_by_protocol")
    assert desc.query_id == "samples_by_protocol"
    assert desc.kind == "read"
    assert desc.output_class is SampleOutput


def test_get_returns_description_for_registered_write() -> None:
    """get(name) returns the QueryDescription for a registered write query."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_write(CreateSample())

    desc = query_catalogue.get("create_sample")
    assert desc.query_id == "create_sample"
    assert desc.kind == "write"


def test_get_raises_key_error_for_unknown_name() -> None:
    """get(name) raises KeyError when the name is not registered."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())

    with pytest.raises(KeyError, match="no_such_query"):
        query_catalogue.get("no_such_query")


def test_get_raises_key_error_on_empty_catalogue() -> None:
    """get(name) raises KeyError on a catalogue with no registered queries."""
    with pytest.raises(KeyError):
        QueryCatalogue().get("anything")


def test_get_result_matches_describe_for_same_name() -> None:
    """get(name) returns the same object as the matching entry in describe()."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(SamplesByProtocol())
    query_catalogue.register_write(CreateSample())

    assert query_catalogue.get("samples_by_protocol") == query_catalogue.describe()[0]
    assert query_catalogue.get("create_sample") == query_catalogue.describe()[1]
