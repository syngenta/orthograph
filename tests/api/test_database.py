"""Tests for orthograph.api.database — inspect, validate, query, execute.

Covers:
- inspect: returns GraphProfile for all backends (contract, cross-backend)
- validate: returns ValidationResult (database-vs-model, named verb)
- query / execute: typed Cypher round-trips via FakeGraphSession
- Error paths: unknown backend, gqlalchemy deferred, bad params
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import networkx as nx
import pytest
from pydantic import BaseModel

from orthograph.api.database import execute, inspect, query, validate
from orthograph.cypher.base_models import CypherReadQuery, CypherWriteQuery
from orthograph.dependencies import MissingDependencyError
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel
from orthograph.graph_profile.models import GraphProfile
from tests.fixtures.conftest import Person


# ---------------------------------------------------------------------------
# Domain fixtures
# ---------------------------------------------------------------------------


# Test-specific Movie model with 'released' field instead of 'year'
class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    released: int


@pytest.fixture()
def empty_model() -> GraphDefinition:
    return GraphDefinition(name="Tiny", node_types=[Person], relationship_types=[])


# ---------------------------------------------------------------------------
# Fake driver / session helpers
# ---------------------------------------------------------------------------


def _empty_driver() -> MagicMock:
    driver = MagicMock()
    driver.execute_query.return_value = ([], MagicMock(), [])
    return driver


def _networkx_graph() -> nx.MultiDiGraph[str]:
    g: nx.MultiDiGraph[str] = nx.MultiDiGraph()
    g.add_node("p1", __label__="Person", name="Alice")
    return g


def _connection_for(backend: str) -> Any:
    if backend == "networkx":
        return _networkx_graph()
    return _empty_driver()


# ---------------------------------------------------------------------------
# inspect — contract (cross-backend)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["neo4j", "memgraph", "networkx"])
def test_inspect_returns_graph_profile(backend: str) -> None:
    profile = inspect(backend, _connection_for(backend))
    assert isinstance(profile, GraphProfile)
    assert profile.source == backend
    assert isinstance(profile.node_type_profiles, dict)
    assert isinstance(profile.rel_type_profiles, dict)
    assert isinstance(profile.constraints, list)


def test_inspect_networkx_profiles_the_graph() -> None:
    profile = inspect("networkx", _networkx_graph())
    assert isinstance(profile, GraphProfile)
    assert "Person" in profile.node_labels


def test_inspect_unknown_backend_raises() -> None:
    with pytest.raises(MissingDependencyError):
        inspect("nonsense", _empty_driver())


# ---------------------------------------------------------------------------
# validate — database-vs-model (named verb)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["neo4j", "memgraph", "networkx"])
def test_validate_returns_validation_result(
    backend: str, empty_model: GraphDefinition
) -> None:
    result = validate(backend, _connection_for(backend), empty_model)
    assert isinstance(result, ValidationResult)


def test_validate_is_distinct_from_inspect() -> None:
    """validate returns ValidationResult; inspect returns GraphProfile."""
    conn = _empty_driver()
    graph_definition = GraphDefinition(
        name="M", node_types=[Person], relationship_types=[]
    )
    assert isinstance(inspect("neo4j", conn), GraphProfile)
    assert isinstance(
        validate("neo4j", _empty_driver(), graph_definition), ValidationResult
    )


# ---------------------------------------------------------------------------
# query / execute — typed Cypher via FakeGraphSession
# ---------------------------------------------------------------------------


class ReleasedYearParams(BaseModel):
    released: int


# Note: Movie imported from tests.fixtures.conftest


class MoviesByYear(CypherReadQuery[ReleasedYearParams, Movie]):
    Params = ReleasedYearParams
    Output = Movie
    name = "db_movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title, m.released"

    def materialize(self, raw: dict[str, Any]) -> Movie:
        return Movie(title=raw["m.title"], released=raw["m.released"])


class CreateMovie(CypherWriteQuery[ReleasedYearParams, int]):
    Params = ReleasedYearParams
    name = "db_create_movie"
    cypher_template = "CREATE (m:Movie {released: $released})"

    def interpret_result(self, raw: Any) -> int:
        return int(raw.nodes_created)


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


def test_query_dispatches_to_cypher_executor() -> None:
    session = FakeGraphSession(
        records=[
            {"m.title": "The Matrix", "m.released": 1999},
            {"m.title": "Inception", "m.released": 2010},
        ]
    )
    result = query("neo4j", lambda: session, MoviesByYear(), {"released": 1999})
    assert result == [
        Movie(title="The Matrix", released=1999),
        Movie(title="Inception", released=2010),
    ]
    assert len(session.run_calls) == 1


def test_query_via_memgraph_name() -> None:
    session = FakeGraphSession(
        records=[{"m.title": "Memgraph Movie", "m.released": 2020}]
    )
    result = query("memgraph", lambda: session, MoviesByYear(), {"released": 2020})
    assert result == [Movie(title="Memgraph Movie", released=2020)]


def test_execute_dispatches_to_cypher_executor() -> None:
    session = FakeGraphSession(nodes_created=1)
    result = execute("neo4j", lambda: session, CreateMovie(), {"released": 1999})
    assert result == 1
    assert session.committed is True
    assert session.rolled_back is False


def test_connection_factory_is_consumer_owned() -> None:
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

    query("neo4j", factory, MoviesByYear(), {"released": 2000})
    query("neo4j", factory, MoviesByYear(), {"released": 2000})
    assert call_count == 2
    assert len(sessions[0].run_calls) == 1
    assert len(sessions[1].run_calls) == 1


def test_query_gqlalchemy_raises_clear_error() -> None:
    with pytest.raises(MissingDependencyError, match="not available"):
        query("gqlalchemy", lambda: object(), MoviesByYear(), {})


def test_query_gqlalchemy_error_names_validated_query_builder() -> None:
    with pytest.raises(MissingDependencyError, match="ValidatedQueryBuilder"):
        query("gqlalchemy", lambda: object(), MoviesByYear(), {})


def test_query_unknown_backend_raises() -> None:
    with pytest.raises(MissingDependencyError, match="Unknown execution backend"):
        query("nonsense", lambda: object(), MoviesByYear(), {})


def test_query_bad_params_raise_before_session_run() -> None:
    session = FakeGraphSession(records=[])
    with pytest.raises(Exception):
        query("neo4j", lambda: session, MoviesByYear(), {"released": "not-an-int"})
    assert session.run_calls == []


# ---------------------------------------------------------------------------
# Custom rule injection (C4)
# ---------------------------------------------------------------------------


def test_validate_with_custom_rules_sees_custom_issue() -> None:
    """A custom rule injected via compare_profile_to_definition is applied and its issue
    is returned in the result."""
    from collections.abc import Iterable
    from dataclasses import dataclass

    from orthograph.comparison.engine import compare_profile_to_definition
    from orthograph.comparison.rules import RuleContext
    from orthograph.diagnostics.classification import EntityType, Severity
    from orthograph.diagnostics.result import ValidationIssue
    from orthograph.graph_profile.models import GraphProfile, NodeTypeProfile

    @dataclass
    class SentinelRule:
        key: str = "test.sentinel"

        def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
            yield ValidationIssue(
                code="SENTINEL",
                severity=Severity.INFO,
                entity_type=EntityType.NODE,
                entity_id="sentinel",
                message="Custom sentinel rule fired",
            )

    model = GraphDefinition(name="test", node_types=[Person], relationship_types=[])
    profile = GraphProfile(
        source="test",
        node_type_profiles={"Person": NodeTypeProfile(label="Person", count=1)},
    )
    result = compare_profile_to_definition(profile, model, rules=[SentinelRule()])
    codes = [i.code for i in result.issues]
    assert "SENTINEL" in codes


def test_validate_api_with_custom_rules_sees_custom_issue() -> None:
    """rules kwarg is threaded through api/database.validate."""
    from collections.abc import Iterable
    from dataclasses import dataclass
    from unittest.mock import patch

    from orthograph.comparison.rules import RuleContext
    from orthograph.diagnostics.classification import EntityType, Severity
    from orthograph.diagnostics.result import ValidationIssue
    from orthograph.graph_profile.models import GraphProfile, NodeTypeProfile

    @dataclass
    class SentinelRule:
        key: str = "test.sentinel_api"

        def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
            yield ValidationIssue(
                code="SENTINEL_API",
                severity=Severity.INFO,
                entity_type=EntityType.NODE,
                entity_id="sentinel",
                message="API sentinel rule fired",
            )

    model = GraphDefinition(name="test", node_types=[Person], relationship_types=[])
    fake_profile = GraphProfile(
        source="test",
        node_type_profiles={"Person": NodeTypeProfile(label="Person", count=1)},
    )

    with patch("orthograph.api.database.inspect", return_value=fake_profile):
        result = validate(
            backend="networkx",
            connection=object(),
            graph_definition=model,
            rules=[SentinelRule()],
        )

    codes = [i.code for i in result.issues]
    assert "SENTINEL_API" in codes


def test_validate_with_empty_rules_emits_no_standard_issues() -> None:
    """Passing rules=[] suppresses the standard rule set entirely."""
    from orthograph.comparison.engine import compare_profile_to_definition
    from orthograph.graph_profile.models import GraphProfile

    model = GraphDefinition(name="test", node_types=[Person], relationship_types=[])
    # Profile intentionally missing Person — would normally raise MISSING_NODE_LABEL
    profile = GraphProfile(source="test")
    result = compare_profile_to_definition(profile, model, rules=[])
    assert result.issues == []
