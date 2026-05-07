"""Tests for gqlalchemy extension client module."""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from orthograph.core.errors import GraphValidationError
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


class DirectedRel(RelationshipModel):
    __label__ = "DIRECTED"
    __source_type__ = PersonNode
    __target_type__ = MovieNode


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
        name="Filmography",
        node_types=[PersonNode, MovieNode],
        relationship_types=[ActedInRel, DirectedRel],
    )


@pytest.fixture()
def mock_db() -> MagicMock:
    """Create a mock GQLAlchemy DatabaseClient."""
    db = MagicMock()
    # simulate save_node returning the node with an _id
    db.save_node = MagicMock(side_effect=_mock_save_node)
    db.save_relationship = MagicMock(side_effect=_mock_save_rel)
    db.execute_and_fetch = MagicMock(return_value=iter([]))
    return db


def _mock_save_node(node: Any) -> Any:
    """Mock save_node that sets _id and returns the node."""
    node._id = 42
    return node


def _mock_save_rel(rel: Any) -> Any:
    """Mock save_relationship that sets _id and returns the rel."""
    rel._id = 100
    return rel


# ---------------------------------------------------------------------------
# Tests: GqlAlchemyClient initialization
# ---------------------------------------------------------------------------


class TestClientInit:
    """Tests for GqlAlchemyClient construction."""

    def test_client_creates_with_model_and_db(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        assert client.model is model

    def test_client_generates_schema(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        assert "Person" in client.schema.node_classes
        assert "ACTED_IN" in client.schema.rel_classes


# ---------------------------------------------------------------------------
# Tests: save_node
# ---------------------------------------------------------------------------


class TestSaveNode:
    """Tests for client.save_node() with validation."""

    def test_save_valid_node(self, model: GraphDataModel, mock_db: MagicMock) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        result = client.save_node({"name": "Alice", "age": 30}, node_type="Person")
        assert result is not None
        mock_db.save_node.assert_called_once()

    def test_save_node_with_optional_property(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        result = client.save_node(
            {"name": "Alice", "age": 30, "email": "a@b.com"},
            node_type="Person",
        )
        assert result is not None

    def test_save_node_missing_required_property_raises(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        with pytest.raises(GraphValidationError):
            client.save_node({"title": "The Matrix"}, node_type="Movie")
        mock_db.save_node.assert_not_called()

    def test_save_node_wrong_type_raises(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        with pytest.raises(GraphValidationError):
            client.save_node(
                {"name": "Alice", "age": "not_a_number"},
                node_type="Person",
            )
        mock_db.save_node.assert_not_called()

    def test_save_node_extra_properties_rejected(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        with pytest.raises(GraphValidationError):
            client.save_node(
                {"name": "Alice", "age": 30, "unknown_prop": "x"},
                node_type="Person",
            )
        mock_db.save_node.assert_not_called()

    def test_save_node_unknown_type_raises(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        with pytest.raises(GraphValidationError):
            client.save_node({"name": "NYC"}, node_type="City")
        mock_db.save_node.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: save_relationship
# ---------------------------------------------------------------------------


class TestSaveRelationship:
    """Tests for client.save_relationship() with validation."""

    def test_save_valid_relationship(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        result = client.save_relationship(
            {"role": "Neo"},
            rel_type="ACTED_IN",
            start_node_id=1,
            end_node_id=2,
        )
        assert result is not None
        mock_db.save_relationship.assert_called_once()

    def test_save_relationship_missing_required_property_raises(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        with pytest.raises(GraphValidationError):
            client.save_relationship(
                {},  # 'role' is required for ACTED_IN
                rel_type="ACTED_IN",
                start_node_id=1,
                end_node_id=2,
            )
        mock_db.save_relationship.assert_not_called()

    def test_save_relationship_unknown_type_raises(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        with pytest.raises(GraphValidationError):
            client.save_relationship(
                {},
                rel_type="PRODUCES",
                start_node_id=1,
                end_node_id=2,
            )
        mock_db.save_relationship.assert_not_called()

    def test_save_relationship_without_properties(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        client = GqlAlchemyClient(model=model, db=mock_db)
        result = client.save_relationship(
            {},
            rel_type="DIRECTED",
            start_node_id=1,
            end_node_id=2,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: execute (raw passthrough)
# ---------------------------------------------------------------------------


class TestExecute:
    """Tests for client.execute() raw passthrough."""

    def test_execute_delegates_to_db(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        mock_db.execute_and_fetch.return_value = iter([{"count": 42}])
        client = GqlAlchemyClient(model=model, db=mock_db)
        results = client.execute("MATCH (n) RETURN count(n) AS count")
        assert len(results) == 1
        assert results[0]["count"] == 42

    def test_execute_with_params(
        self, model: GraphDataModel, mock_db: MagicMock
    ) -> None:
        from orthograph.extensions.gqlalchemy.client import (
            GqlAlchemyClient,
        )

        mock_db.execute_and_fetch.return_value = iter([])
        client = GqlAlchemyClient(model=model, db=mock_db)
        client.execute(
            "MATCH (n:Person {name: $name}) RETURN n",
            params={"name": "Alice"},
        )
        mock_db.execute_and_fetch.assert_called_once()
