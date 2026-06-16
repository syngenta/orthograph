"""Tests for CypherExecutor using a FakeGraphSession (no live DB).

Proves the single I/O seam: read() validates params (R4), calls the pure
build() (R1), runs against a fake session, and materialises each record (R3).
"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.cypher.base_models import CypherReadQuery, CypherWriteQuery
from orthograph.cypher.query_execution import CypherExecutor, CypherWriteResultSummary
from orthograph.graph_definition.models import NodeModel
from orthograph.query.write_result import WriteResultSummary


class ReleasedYearParams(BaseModel):
    released: int


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    released: int


class MoviesByYearCypher(CypherReadQuery[ReleasedYearParams, Movie]):
    """Declarative read — default build() uses cypher_template."""

    Params = ReleasedYearParams
    Output = Movie
    name = "movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title, m.released"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(title=raw["m.title"], released=raw["m.released"])


class CreateMovieCypher(CypherWriteQuery[ReleasedYearParams, int]):
    """Declarative write — default build() uses cypher_template."""

    Params = ReleasedYearParams
    name = "create_movie"
    cypher_template = "CREATE (m:Movie {released: $released})"

    def interpret_result(self, raw: WriteResultSummary) -> int:
        return raw.nodes_created


@dataclass
class FakeCounters:
    """Minimal stand-in for neo4j SummaryCounters."""

    nodes_created: int = 0
    nodes_deleted: int = 0
    relationships_created: int = 0
    relationships_deleted: int = 0
    properties_set: int = 0


@dataclass
class FakeSummary:
    """Minimal stand-in for neo4j ResultSummary."""

    counters: FakeCounters = field(default_factory=FakeCounters)


@dataclass
class FakeWriteResult:
    """Minimal stand-in for a neo4j Result on the write path.

    ``CypherWriteResultSummary.from_neo4j_result`` calls ``result.consume().counters``.
    """

    _summary: FakeSummary = field(default_factory=FakeSummary)

    def consume(self) -> FakeSummary:
        return self._summary

    def __iter__(self):
        return iter([])


class FakeTransaction:
    """Minimal stand-in for a graph driver transaction.

    Supports ``.run(cypher, **params)`` and explicit ``commit()``/``rollback()``.
    """

    def __init__(self, session: "FakeGraphSession") -> None:
        self._session = session

    def run(self, cypher: str, **params: Any) -> Any:
        return self._session.run(cypher, **params)

    def commit(self) -> None:
        self._session.committed = True

    def rollback(self) -> None:
        self._session.rolled_back = True


class FakeGraphSession:
    """Minimal stand-in for a graph driver session.

    Supports the context-manager + ``.run(cypher, **params)`` contract that
    CypherExecutor depends on. Records the calls it received so tests can assert
    that run() was (or was not) invoked.

    ``run()`` returns a ``FakeWriteResult`` when ``nodes_created`` is set
    (write path), otherwise the list of read records.
    """

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        nodes_created: int = 0,
    ) -> None:
        self._records = records or []
        self._nodes_created = nodes_created
        self._is_write = nodes_created > 0
        self.run_calls: list[tuple[str, dict[str, Any]]] = []
        self.committed: bool = False
        self.rolled_back: bool = False

    def __enter__(self) -> "FakeGraphSession":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def begin_transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def run(self, cypher: str, **params: Any) -> Any:
        self.run_calls.append((cypher, params))
        if self._is_write:
            return FakeWriteResult(
                FakeSummary(FakeCounters(nodes_created=self._nodes_created))
            )
        return list(self._records)


def test_import_cypher_executor() -> None:
    """CypherExecutor imports from the cypher package."""
    from orthograph.cypher.query_execution import CypherExecutor  # noqa: F401


def test_read_materialises_fake_records_into_output() -> None:
    """read() returns declared Output NodeModel instances from fake records."""
    session = FakeGraphSession(
        records=[
            {"m.title": "The Matrix", "m.released": 1999},
            {"m.title": "The Matrix Reloaded", "m.released": 2003},
        ]
    )
    executor = CypherExecutor(lambda: session)

    result = executor.read(MoviesByYearCypher(), {"released": 1999})

    assert result == [
        Movie(title="The Matrix", released=1999),
        Movie(title="The Matrix Reloaded", released=2003),
    ]
    assert all(isinstance(m, Movie) for m in result)


def test_read_passes_built_cypher_and_params_to_session() -> None:
    """read() runs the built Cypher with the built params on the session."""
    session = FakeGraphSession(records=[])
    executor = CypherExecutor(lambda: session)

    executor.read(MoviesByYearCypher(), {"released": 1999})

    assert len(session.run_calls) == 1
    cypher, params = session.run_calls[0]
    assert "MATCH (m:Movie" in cypher
    assert params == {"released": 1999}


def test_read_bad_params_raise_before_run() -> None:
    """Invalid params raise (R4) before the session's run() is ever called."""
    session = FakeGraphSession(records=[])
    executor = CypherExecutor(lambda: session)

    with pytest.raises(Exception):
        executor.read(MoviesByYearCypher(), {"released": "not-an-int-x"})

    assert session.run_calls == []


def test_write_materializes_result() -> None:
    """write() runs the built Cypher and maps the result via interpret_result()."""
    session = FakeGraphSession(nodes_created=1)
    executor = CypherExecutor(lambda: session)

    result = executor.write(CreateMovieCypher(), {"released": 1999})

    assert result == 1
    assert len(session.run_calls) == 1
    cypher, params = session.run_calls[0]
    assert cypher.startswith("CREATE (m:Movie")
    assert params == {"released": 1999}


def test_write_bad_params_raise_before_run() -> None:
    """Invalid write params raise before run() is called."""
    session = FakeGraphSession()
    executor = CypherExecutor(lambda: session)

    with pytest.raises(Exception):
        executor.write(CreateMovieCypher(), {"released": "bad-x"})

    assert session.run_calls == []


def test_write_commits_transaction() -> None:
    """write() explicitly commits the transaction on success."""
    session = FakeGraphSession(nodes_created=1)
    executor = CypherExecutor(lambda: session)

    executor.write(CreateMovieCypher(), {"released": 2003})

    assert session.committed is True
    assert session.rolled_back is False


# --- Runtime Cypher validation (catches imperative syntax errors) ---


def test_read_unparseable_cypher_raises_before_session_run() -> None:
    """Unparseable Cypher from build() raises CypherSyntaxError before run()."""
    import warnings

    from orthograph.cypher.bindings import CypherQuery
    from orthograph.cypher.exceptions import CypherSyntaxError

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)

        class BadImperativeRead(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "bad_imperative_read"

            def build(self, params: ReleasedYearParams) -> CypherQuery:
                return ("THIS IS NOT VALID CYPHER {{{{", {"released": params.released})

            def materialize(self, raw: dict[str, Any]) -> Movie:
                return Movie(title=raw["t"], released=raw["y"])

    session = FakeGraphSession(records=[])
    executor = CypherExecutor(lambda: session)

    with pytest.raises(CypherSyntaxError, match="unparseable Cypher"):
        executor.read(BadImperativeRead(), {"released": 1999})

    assert session.run_calls == []


def test_write_unparseable_cypher_raises_before_session_run() -> None:
    """If build() produces unparseable Cypher on write, CypherSyntaxError is raised."""
    import warnings

    from orthograph.cypher.bindings import CypherQuery
    from orthograph.cypher.exceptions import CypherSyntaxError

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)

        class BadImperativeWrite(CypherWriteQuery[ReleasedYearParams, int]):
            Params = ReleasedYearParams
            name = "bad_imperative_write"

            def build(self, params: ReleasedYearParams) -> CypherQuery:
                return ("NOT CYPHER AT ALL !!!", {"released": params.released})

            def interpret_result(self, raw: Any) -> int:
                return 1

    session = FakeGraphSession()
    executor = CypherExecutor(lambda: session)

    with pytest.raises(CypherSyntaxError, match="unparseable Cypher"):
        executor.write(BadImperativeWrite(), {"released": 1999})

    assert session.run_calls == []


# --- WriteResultSummary protocol ---


def test_write_result_summary_protocol_satisfied_by_cypher_impl() -> None:
    """CypherWriteResultSummary satisfies the WriteResultSummary protocol."""
    summary = CypherWriteResultSummary(
        nodes_created=2,
        nodes_deleted=0,
        relationships_created=1,
        relationships_deleted=0,
        properties_set=4,
    )
    assert isinstance(summary, WriteResultSummary)
    assert summary.nodes_created == 2
    assert summary.relationships_created == 1
    assert summary.properties_set == 4


def test_write_result_summary_satisfied_by_simple_dataclass() -> None:
    """A plain dataclass with the required fields satisfies WriteResultSummary.

    This is the unit-testability guarantee: no driver dependency required.
    """
    from dataclasses import dataclass

    @dataclass
    class StubSummary:
        nodes_created: int = 0
        nodes_deleted: int = 0
        relationships_created: int = 0
        relationships_deleted: int = 0
        properties_set: int = 0

    stub = StubSummary(nodes_created=3, properties_set=6)
    assert isinstance(stub, WriteResultSummary)
    assert stub.nodes_created == 3
    assert stub.properties_set == 6
