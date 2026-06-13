"""Convert GQLAlchemy query results to Orthograph validation dicts."""

from __future__ import annotations

from typing import Any

from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.validation import GraphValidator


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def gqa_node_to_dict(
    node: Any,
    graph_definition: GraphDefinition,
) -> dict[str, Any]:
    """Convert a GQLAlchemy Node to an Orthograph validation dict.

    Sets ``__label__`` to the primary label matched against ``graph_definition``
    when multiple labels exist.
    """
    labels: set[str] = getattr(node, "_labels", set())
    properties: dict[str, Any] = dict(getattr(node, "_properties", {}))
    label = _pick_primary_label(labels, graph_definition)
    properties["__label__"] = label
    return properties


def gqa_relationship_to_dict(
    rel: Any,
    graph_definition: GraphDefinition,
) -> dict[str, Any]:
    """Convert a GQLAlchemy Relationship to an Orthograph validation dict.

    ``graph_definition`` is accepted for API symmetry with the node converter
    but is not used.
    """
    rel_type: str = getattr(rel, "type", getattr(rel, "_type", ""))
    properties: dict[str, Any] = dict(getattr(rel, "_properties", {}))
    properties["__label__"] = rel_type
    properties["__source_uid__"] = str(getattr(rel, "_start_node_id", ""))
    properties["__target_uid__"] = str(getattr(rel, "_end_node_id", ""))
    return properties


def gqa_results_to_graph_data(
    results: list[dict[str, Any]],
    graph_definition: GraphDefinition,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract nodes and relationships from GQLAlchemy query result dicts.

    Scalars are skipped.  Returns ``(node_dicts, relationship_dicts)``.
    """
    nodes: list[dict[str, Any]] = []
    rels: list[dict[str, Any]] = []

    for row in results:
        for value in row.values():
            if _is_gqa_node(value):
                nodes.append(gqa_node_to_dict(value, graph_definition))
            elif _is_gqa_relationship(value):
                rels.append(gqa_relationship_to_dict(value, graph_definition))

    return nodes, rels


def validate_gqa_result(
    results: list[dict[str, Any]],
    graph_definition: GraphDefinition,
) -> ValidationResult:
    """Validate GQLAlchemy query results against ``graph_definition``."""
    nodes, rels = gqa_results_to_graph_data(results, graph_definition)
    validator = GraphValidator(graph_definition)
    return validator.validate(nodes=nodes, relationships=rels)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pick_primary_label(
    labels: set[str],
    graph_definition: GraphDefinition,
) -> str:
    """Select the primary label from a multi-label node.

    Prefers labels matching the model; falls back to alphabetical order.
    """
    model_labels = graph_definition.node_labels
    matching = labels & model_labels
    if len(matching) == 1:
        return next(iter(matching))
    if len(matching) > 1:
        return sorted(matching)[0]
    return sorted(labels)[0] if labels else "__unknown__"


def _is_gqa_node(value: Any) -> bool:
    """Check if a value looks like a GQLAlchemy Node instance."""
    return (
        hasattr(value, "_labels")
        and hasattr(value, "_properties")
        and isinstance(getattr(value, "_labels", None), (set, frozenset))
    )


def _is_gqa_relationship(value: Any) -> bool:
    """Check if a value looks like a GQLAlchemy Relationship instance."""
    if _is_gqa_node(value):
        return False
    return (
        hasattr(value, "_start_node_id")
        and hasattr(value, "_end_node_id")
        and hasattr(value, "_properties")
    )
