"""Tests for gqlalchemy extension query builder module."""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel


# ---------------------------------------------------------------------------
# Test model definitions
# ---------------------------------------------------------------------------


class PersonNode(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    age: int
    email: Optional[str] = None


class MovieNode(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    year: int


class ActedInRel(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    role: str


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(
        name="Filmography",
        node_types=[PersonNode, MovieNode],
        relationship_types=[ActedInRel],
    )


@pytest.fixture()
def mock_db() -> MagicMock:
    """Create a mock GQLAlchemy DatabaseClient."""
    db = MagicMock()
    db.execute_and_fetch = MagicMock(return_value=iter([]))
    return db


# ---------------------------------------------------------------------------
# Mock query builder
# ---------------------------------------------------------------------------


def _make_mock_builder(cypher: str) -> MagicMock:
    """Create a mock query builder that returns the given Cypher string."""
    builder = MagicMock()
    # GQLAlchemy query builders implement __str__ to return Cypher
    builder.__str__ = lambda self: cypher  # type: ignore[misc,assignment]
    # Also set a .construct_query() for the actual query text
    builder.construct_query = MagicMock(return_value=cypher)
    return builder


# ---------------------------------------------------------------------------
# Tests: ValidatedQueryBuilder
# ---------------------------------------------------------------------------


class TestValidatedQueryBuilder:
    """Tests for the query validation bridge."""

    def test_validate_query_valid(
        self, graph_definition: GraphDefinition, mock_db: MagicMock
    ) -> None:
        from orthograph.backends.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        vqb = ValidatedQueryBuilder(graph_definition=graph_definition, db=mock_db)
        builder = _make_mock_builder(
            "MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN p, m;"
        )
        result = vqb.validate_query(builder)
        assert result.is_valid

    def test_validate_query_unknown_label(
        self, graph_definition: GraphDefinition, mock_db: MagicMock
    ) -> None:
        from orthograph.backends.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        vqb = ValidatedQueryBuilder(graph_definition=graph_definition, db=mock_db)
        builder = _make_mock_builder("MATCH (s:Studio) RETURN s;")
        result = vqb.validate_query(builder)
        assert not result.is_valid
        assert any("QUERY_UNKNOWN_NODE_LABEL" in i.code for i in result.errors)

    def test_validate_query_unknown_rel_type(
        self, graph_definition: GraphDefinition, mock_db: MagicMock
    ) -> None:
        from orthograph.backends.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        vqb = ValidatedQueryBuilder(graph_definition=graph_definition, db=mock_db)
        builder = _make_mock_builder(
            "MATCH (p:Person)-[:PRODUCED]->(m:Movie) RETURN p, m;"
        )
        result = vqb.validate_query(builder)
        assert not result.is_valid

    def test_execute_validated_valid_query(
        self, graph_definition: GraphDefinition, mock_db: MagicMock
    ) -> None:
        from orthograph.backends.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        mock_db.execute_and_fetch.return_value = iter([{"count": 5}])
        vqb = ValidatedQueryBuilder(graph_definition=graph_definition, db=mock_db)
        builder = _make_mock_builder("MATCH (p:Person) RETURN count(p) AS count;")
        results = vqb.execute_validated(builder)
        assert len(results) == 1
        assert results[0]["count"] == 5

    def test_execute_validated_invalid_query_raises(
        self, graph_definition: GraphDefinition, mock_db: MagicMock
    ) -> None:
        from orthograph.backends.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )
        from orthograph.diagnostics.result import GraphValidationError

        vqb = ValidatedQueryBuilder(graph_definition=graph_definition, db=mock_db)
        builder = _make_mock_builder("MATCH (s:Studio) RETURN s;")
        with pytest.raises(GraphValidationError):
            vqb.execute_validated(builder)
        mock_db.execute_and_fetch.assert_not_called()

    def test_execute_validated_with_result_validation(
        self, graph_definition: GraphDefinition, mock_db: MagicMock
    ) -> None:
        from orthograph.backends.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        # Return scalar results (no nodes/rels to validate)
        mock_db.execute_and_fetch.return_value = iter([{"name": "Alice"}])
        vqb = ValidatedQueryBuilder(graph_definition=graph_definition, db=mock_db)
        builder = _make_mock_builder("MATCH (p:Person) RETURN p.name AS name;")
        # Should not raise even with result validation (scalars pass)
        results = vqb.execute_validated(builder, validate_results=True)
        assert len(results) == 1

    def test_execute_validated_raw_cypher_string(
        self, graph_definition: GraphDefinition, mock_db: MagicMock
    ) -> None:
        from orthograph.backends.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        mock_db.execute_and_fetch.return_value = iter([])
        vqb = ValidatedQueryBuilder(graph_definition=graph_definition, db=mock_db)
        # Pass a raw Cypher string instead of a builder
        results = vqb.execute_validated("MATCH (p:Person) RETURN p;")
        assert results == []
