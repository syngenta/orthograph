"""Tests for gqlalchemy extension result adapter module."""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    NodeModel,
    RelationshipModel,
)


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
    __target_cardinality__ = "1..*"
    role: str


class DirectedRel(RelationshipModel):
    __label__ = "DIRECTED"
    __source_label__ = "Person"
    __target_label__ = "Movie"


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(
        name="Filmography",
        node_types=[PersonNode, MovieNode],
        relationship_types=[ActedInRel, DirectedRel],
    )


# ---------------------------------------------------------------------------
# Mock helpers for GQLAlchemy objects
# ---------------------------------------------------------------------------


def _make_mock_gqa_node(
    labels: set[str],
    properties: dict[str, Any],
    node_id: int = 1,
) -> MagicMock:
    """Create a mock that behaves like a GQLAlchemy Node instance."""
    mock = MagicMock()
    mock._labels = labels
    mock._id = node_id
    mock._properties = properties

    # Set properties as direct attributes (GQLAlchemy style)
    for key, val in properties.items():
        setattr(mock, key, val)

    # Make it iterable like dict for properties access
    mock.__class__ = MagicMock
    mock.__class__.__name__ = "_Gqa_Node"

    return mock


def _make_mock_gqa_relationship(
    rel_type: str,
    properties: dict[str, Any],
    start_node_id: int = 1,
    end_node_id: int = 2,
    rel_id: int = 100,
) -> MagicMock:
    """Create a mock that behaves like a GQLAlchemy Relationship instance."""
    mock = MagicMock()
    mock._type = rel_type
    mock.type = rel_type
    mock._id = rel_id
    mock._start_node_id = start_node_id
    mock._end_node_id = end_node_id
    mock._properties = properties

    for key, val in properties.items():
        setattr(mock, key, val)

    return mock


# ---------------------------------------------------------------------------
# Tests: gqa_node_to_dict
# ---------------------------------------------------------------------------


class TestGqaNodeToDict:
    """Tests for converting GQLAlchemy Node instances to validation dicts."""

    def test_node_to_dict_basic(self, graph_definition: GraphDefinition) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            gqa_node_to_dict,
        )

        mock_node = _make_mock_gqa_node(
            labels={"Person"},
            properties={"name": "Alice", "age": 30},
        )
        result = gqa_node_to_dict(mock_node, graph_definition)
        assert result["__label__"] == "Person"
        assert result["name"] == "Alice"
        assert result["age"] == 30

    def test_node_to_dict_with_optional_property(
        self, graph_definition: GraphDefinition
    ) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            gqa_node_to_dict,
        )

        mock_node = _make_mock_gqa_node(
            labels={"Person"},
            properties={"name": "Alice", "age": 30, "email": "a@b.com"},
        )
        result = gqa_node_to_dict(mock_node, graph_definition)
        assert result["email"] == "a@b.com"

    def test_node_to_dict_multi_label_picks_model_match(
        self, graph_definition: GraphDefinition
    ) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            gqa_node_to_dict,
        )

        mock_node = _make_mock_gqa_node(
            labels={"Person", "Actor"},
            properties={"name": "Alice", "age": 30},
        )
        result = gqa_node_to_dict(mock_node, graph_definition)
        assert result["__label__"] == "Person"

    def test_node_to_dict_no_matching_label(
        self, graph_definition: GraphDefinition
    ) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            gqa_node_to_dict,
        )

        mock_node = _make_mock_gqa_node(
            labels={"Unknown"},
            properties={"x": 1},
        )
        result = gqa_node_to_dict(mock_node, graph_definition)
        assert result["__label__"] == "Unknown"


# ---------------------------------------------------------------------------
# Tests: gqa_relationship_to_dict
# ---------------------------------------------------------------------------


class TestGqaRelationshipToDict:
    """Tests for converting GQLAlchemy Relationship instances."""

    def test_rel_to_dict_basic(self, graph_definition: GraphDefinition) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            gqa_relationship_to_dict,
        )

        mock_rel = _make_mock_gqa_relationship(
            rel_type="ACTED_IN",
            properties={"role": "Neo"},
            start_node_id=1,
            end_node_id=2,
        )
        result = gqa_relationship_to_dict(mock_rel, graph_definition)
        assert result["__label__"] == "ACTED_IN"
        assert result["role"] == "Neo"
        assert "__source_uid__" in result
        assert "__target_uid__" in result

    def test_rel_to_dict_without_properties(
        self, graph_definition: GraphDefinition
    ) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            gqa_relationship_to_dict,
        )

        mock_rel = _make_mock_gqa_relationship(
            rel_type="DIRECTED",
            properties={},
        )
        result = gqa_relationship_to_dict(mock_rel, graph_definition)
        assert result["__label__"] == "DIRECTED"


# ---------------------------------------------------------------------------
# Tests: gqa_results_to_graph_data
# ---------------------------------------------------------------------------


class TestGqaResultsToGraphData:
    """Tests for extracting nodes/rels from GQLAlchemy result dicts."""

    def test_extracts_nodes_from_results(
        self, graph_definition: GraphDefinition
    ) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            gqa_results_to_graph_data,
        )

        mock_node = _make_mock_gqa_node(
            labels={"Person"},
            properties={"name": "Alice", "age": 30},
        )
        results: list[dict[str, Any]] = [{"p": mock_node}]
        nodes, rels = gqa_results_to_graph_data(results, graph_definition)
        assert len(nodes) == 1
        assert nodes[0]["__label__"] == "Person"
        assert len(rels) == 0

    def test_extracts_relationships_from_results(
        self, graph_definition: GraphDefinition
    ) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            gqa_results_to_graph_data,
        )

        mock_rel = _make_mock_gqa_relationship(
            rel_type="ACTED_IN",
            properties={"role": "Neo"},
        )
        results: list[dict[str, Any]] = [{"r": mock_rel}]
        nodes, rels = gqa_results_to_graph_data(results, graph_definition)
        assert len(rels) == 1
        assert rels[0]["__label__"] == "ACTED_IN"

    def test_mixed_nodes_and_rels(self, graph_definition: GraphDefinition) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            gqa_results_to_graph_data,
        )

        mock_node = _make_mock_gqa_node(
            labels={"Person"},
            properties={"name": "Alice", "age": 30},
        )
        mock_rel = _make_mock_gqa_relationship(
            rel_type="ACTED_IN",
            properties={"role": "Neo"},
        )
        results: list[dict[str, Any]] = [
            {"p": mock_node, "r": mock_rel},
        ]
        nodes, rels = gqa_results_to_graph_data(results, graph_definition)
        assert len(nodes) == 1
        assert len(rels) == 1

    def test_skips_scalar_values(self, graph_definition: GraphDefinition) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            gqa_results_to_graph_data,
        )

        results: list[dict[str, Any]] = [
            {"count": 42, "name": "Alice"},
        ]
        nodes, rels = gqa_results_to_graph_data(results, graph_definition)
        assert len(nodes) == 0
        assert len(rels) == 0


# ---------------------------------------------------------------------------
# Tests: validate_gqa_result
# ---------------------------------------------------------------------------


class TestValidateGqaResult:
    """Tests for validating GQLAlchemy query results against a model."""

    def test_valid_node_result(self, graph_definition: GraphDefinition) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            validate_gqa_result,
        )

        mock_node = _make_mock_gqa_node(
            labels={"Person"},
            properties={"name": "Alice", "age": 30},
        )
        results: list[dict[str, Any]] = [{"p": mock_node}]
        vr = validate_gqa_result(results, graph_definition)
        assert vr.is_valid

    def test_invalid_node_result_missing_property(
        self, graph_definition: GraphDefinition
    ) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            validate_gqa_result,
        )

        mock_node = _make_mock_gqa_node(
            labels={"Movie"},
            properties={"title": "The Matrix"},  # missing 'year'
        )
        results: list[dict[str, Any]] = [{"m": mock_node}]
        vr = validate_gqa_result(results, graph_definition)
        assert not vr.is_valid
        assert any("PROPERTY_VALIDATION_ERROR" in i.code for i in vr.errors)

    def test_unknown_label_in_result(self, graph_definition: GraphDefinition) -> None:
        from orthograph.backends.gqlalchemy.result_adapter import (
            validate_gqa_result,
        )

        mock_node = _make_mock_gqa_node(
            labels={"UnknownType"},
            properties={"x": 1},
        )
        results: list[dict[str, Any]] = [{"n": mock_node}]
        vr = validate_gqa_result(results, graph_definition)
        assert not vr.is_valid
        assert any("UNKNOWN_NODE_LABEL" in i.code for i in vr.errors)
