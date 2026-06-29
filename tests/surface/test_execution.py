"""Tests for orthograph.execution — run typed read/write queries.

Covers:
- run_read: typed Cypher read round-trip via FakeGraphSession -> list[Output]
- run_write: typed Cypher write -> interpreted result
- Error paths: unknown backend, execute-incapable backend (networkx)
- connection_factory is consumer-owned (called per run, nothing stored)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel

from orthograph.cypher.base_models import (
    TypedCypherReadQueryModel,
    TypedCypherWriteQueryModel,
)
from orthograph.dependencies import MissingDependencyError
from orthograph.execution import ReadQueryModel, WriteQueryModel, run_read, run_write
from orthograph.graph_definition.models import NodeModel


# ---------------------------------------------------------------------------
# Domain fixtures
# ---------------------------------------------------------------------------


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    released: int


class ReleasedYearParams(BaseModel):
    released: int


class MoviesByYear(TypedCypherReadQueryModel[ReleasedYearParams, Movie]):
    params_schema = ReleasedYearParams
    Output = Movie
    query_id = "exec_movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title, m.released"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(title=raw["m.title"], released=raw["m.released"])


class CreateMovie(TypedCypherWriteQueryModel[ReleasedYearParams, int]):
    params_schema = ReleasedYearParams
    query_id = "exec_create_movie"
    cypher_template = "CREATE (m:Movie {released: $released})"

    def interpret_result(self, raw: Any) -> int:
        return int(raw.nodes_created)


# ---------------------------------------------------------------------------
# Fake session helpers (mirror tests/api/test_database.py)
# ---------------------------------------------------------------------------


@dataclass
class FakeCounters:
    nodes_created: int = 0
    nodes_deleted: int = 0
    relationships_created: int = 0
    relationships_deleted: int = 0
    properties_set: int = 0


@dataclass
class FakeSummary:
    counters: FakeCounters = field(default_factory=FakeCounters)


@dataclass
class FakeWriteResult:
    _summary: FakeSummary = field(default_factory=FakeSummary)

    def consume(self) -> FakeSummary:
        return self._summary

    def __iter__(self):
        return iter([])


class FakeTransaction:
    def __init__(self, session: "FakeGraphSession") -> None:
        self._session = session

    def run(self, cypher: str, **params: Any) -> Any:
        return self._session.run(cypher, **params)

    def commit(self) -> None:
        self._session.committed = True

    def rollback(self) -> None:
        self._session.rolled_back = True


class FakeGraphSession:
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


# ---------------------------------------------------------------------------
# run_read
# ---------------------------------------------------------------------------


def test_run_read_round_trips_typed_query() -> None:
    session = FakeGraphSession(
        records=[
            {"m.title": "The Matrix", "m.released": 1999},
            {"m.title": "Inception", "m.released": 2010},
        ]
    )
    result = run_read("neo4j", lambda: session, MoviesByYear(), {"released": 1999})
    assert result == [
        Movie(title="The Matrix", released=1999),
        Movie(title="Inception", released=2010),
    ]
    assert len(session.run_calls) == 1


def test_run_read_connection_factory_is_consumer_owned() -> None:
    call_count = 0
    sessions: list[FakeGraphSession] = []

    def factory() -> FakeGraphSession:
        nonlocal call_count
        call_count += 1
        s = FakeGraphSession(
            records=[{"m.title": f"Movie{call_count}", "m.released": 2000}]
        )
        sessions.append(s)
        return s

    run_read("neo4j", factory, MoviesByYear(), {"released": 2000})
    run_read("neo4j", factory, MoviesByYear(), {"released": 2000})
    assert call_count == 2
    assert len(sessions[0].run_calls) == 1
    assert len(sessions[1].run_calls) == 1


# ---------------------------------------------------------------------------
# run_write
# ---------------------------------------------------------------------------


def test_run_write_returns_interpreted_result() -> None:
    session = FakeGraphSession(nodes_created=1)
    result = run_write("neo4j", lambda: session, CreateMovie(), {"released": 1999})
    assert result == 1
    assert session.committed is True
    assert session.rolled_back is False


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_run_read_unknown_backend_raises() -> None:
    with pytest.raises(MissingDependencyError, match="Unknown execution backend"):
        run_read("nonsense", lambda: object(), MoviesByYear(), {})


def test_run_read_execute_incapable_backend_raises() -> None:
    """networkx has no executor wired -> MissingDependencyError."""
    with pytest.raises(MissingDependencyError):
        run_read("networkx", lambda: object(), MoviesByYear(), {})


def test_run_write_unknown_backend_raises() -> None:
    with pytest.raises(MissingDependencyError, match="Unknown execution backend"):
        run_write("nonsense", lambda: object(), CreateMovie(), {})


# ---------------------------------------------------------------------------
# Re-exports
# ---------------------------------------------------------------------------


def test_typed_query_bases_are_reexported() -> None:
    assert ReadQueryModel is not None
    assert WriteQueryModel is not None
