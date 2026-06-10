"""Tests for gqlalchemy extension query builder module."""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel


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
    __source_type__ = PersonNode
    __target_type__ = MovieNode
    role: str


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
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
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        vqb = ValidatedQueryBuilder(model=model, db=mock_db)
        builder = _make_mock_builder(
            "MATCH (p:Person)-[:ACTED_IN]->(m:Movie) RETURN p, m;"
        )
        result = vqb.validate_query(builder)
        assert result.is_valid

    def test_validate_query_unknown_label(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        vqb = ValidatedQueryBuilder(model=model, db=mock_db)
        builder = _make_mock_builder("MATCH (s:Studio) RETURN s;")
        result = vqb.validate_query(builder)
        assert not result.is_valid
        assert any("QUERY_UNKNOWN_NODE_LABEL" in i.code for i in result.errors)

    def test_validate_query_unknown_rel_type(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        vqb = ValidatedQueryBuilder(model=model, db=mock_db)
        builder = _make_mock_builder(
            "MATCH (p:Person)-[:PRODUCED]->(m:Movie) RETURN p, m;"
        )
        result = vqb.validate_query(builder)
        assert not result.is_valid

    def test_execute_validated_valid_query(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        mock_db.execute_and_fetch.return_value = iter([{"count": 5}])
        vqb = ValidatedQueryBuilder(model=model, db=mock_db)
        builder = _make_mock_builder("MATCH (p:Person) RETURN count(p) AS count;")
        results = vqb.execute_validated(builder)
        assert len(results) == 1
        assert results[0]["count"] == 5

    def test_execute_validated_invalid_query_raises(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.core.exceptions import GraphValidationError
        from orthograph.extensions.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        vqb = ValidatedQueryBuilder(model=model, db=mock_db)
        builder = _make_mock_builder("MATCH (s:Studio) RETURN s;")
        with pytest.raises(GraphValidationError):
            vqb.execute_validated(builder)
        mock_db.execute_and_fetch.assert_not_called()

    def test_execute_validated_with_result_validation(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        # Return scalar results (no nodes/rels to validate)
        mock_db.execute_and_fetch.return_value = iter([{"name": "Alice"}])
        vqb = ValidatedQueryBuilder(model=model, db=mock_db)
        builder = _make_mock_builder("MATCH (p:Person) RETURN p.name AS name;")
        # Should not raise even with result validation (scalars pass)
        results = vqb.execute_validated(builder, validate_results=True)
        assert len(results) == 1

    def test_execute_validated_raw_cypher_string(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.query_builder import (
            ValidatedQueryBuilder,
        )

        mock_db.execute_and_fetch.return_value = iter([])
        vqb = ValidatedQueryBuilder(model=model, db=mock_db)
        # Pass a raw Cypher string instead of a builder
        results = vqb.execute_validated("MATCH (p:Person) RETURN p;")
        assert results == []
