"""Convert GQLAlchemy query results to Orthograph validation dicts.

This module mirrors ``orthograph.extensions.neo4j.result_adapter`` but
operates on GQLAlchemy ``Node`` and ``Relationship`` instances rather
than raw neo4j driver objects.
"""

from __future__ import annotations

from typing import Any

from orthograph.core.exceptions import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.validator import GraphValidator


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def gqa_node_to_dict(
    node: Any,
    model: GraphDataModel,
) -> dict[str, Any]:
    """Convert a GQLAlchemy Node instance to an Orthograph validation dict.

    The returned dict has ``__label__`` set to the node's primary label
    (matched against the model when multiple labels exist) and all
    properties as top-level keys.

    Args:
        node: A GQLAlchemy ``Node`` instance (or any object with
            ``_labels`` and ``_properties`` attributes).
        model: The Orthograph :class:`GraphDataModel` for label matching.

    Returns:
        A dict suitable for :meth:`GraphValidator.validate_nodes`.
    """
    labels: set[str] = getattr(node, "_labels", set())
    properties: dict[str, Any] = dict(getattr(node, "_properties", {}))
    label = _pick_primary_label(labels, model)
    properties["__label__"] = label
    return properties


def gqa_relationship_to_dict(
    rel: Any,
    model: GraphDataModel,
) -> dict[str, Any]:
    """Convert a GQLAlchemy Relationship instance to a validation dict.

    The returned dict has ``__label__`` set to the relationship type,
    ``__source_uid__`` and ``__target_uid__`` set to the start/end
    node IDs (as strings), and all properties as top-level keys.

    Args:
        rel: A GQLAlchemy ``Relationship`` instance (or any object with
            ``_type``/``type``, ``_start_node_id``, ``_end_node_id``,
            and ``_properties`` attributes).
        model: The Orthograph :class:`GraphDataModel` (currently unused
            for relationships, reserved for future endpoint resolution).

    Returns:
        A dict suitable for :meth:`GraphValidator.validate_relationships`.
    """
    rel_type: str = getattr(rel, "type", getattr(rel, "_type", ""))
    properties: dict[str, Any] = dict(getattr(rel, "_properties", {}))
    properties["__label__"] = rel_type
    properties["__source_uid__"] = str(getattr(rel, "_start_node_id", ""))
    properties["__target_uid__"] = str(getattr(rel, "_end_node_id", ""))
    return properties


def gqa_results_to_graph_data(
    results: list[dict[str, Any]],
    model: GraphDataModel,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract nodes and relationships from GQLAlchemy query result dicts.

    Inspects each value in each result dict.  Objects that look like
    GQLAlchemy ``Node`` instances (have ``_labels`` and ``_properties``)
    are extracted as nodes.  Objects that look like ``Relationship``
    instances (have ``_start_node_id``, ``_end_node_id``, ``_properties``)
    are extracted as relationships.  Scalar values are skipped.

    Args:
        results: A list of dicts as returned by
            ``db.execute_and_fetch(query)``.
        model: The Orthograph :class:`GraphDataModel` for label matching.

    Returns:
        A tuple of ``(node_dicts, relationship_dicts)``.
    """
    nodes: list[dict[str, Any]] = []
    rels: list[dict[str, Any]] = []

    for row in results:
        for value in row.values():
            if _is_gqa_node(value):
                nodes.append(gqa_node_to_dict(value, model))
            elif _is_gqa_relationship(value):
                rels.append(gqa_relationship_to_dict(value, model))

    return nodes, rels


def validate_gqa_result(
    results: list[dict[str, Any]],
    model: GraphDataModel,
) -> ValidationResult:
    """Validate GQLAlchemy query results against an Orthograph model.

    Extracts nodes and relationships from the results, converts them
    to Orthograph validation dicts, and runs the full
    :class:`GraphValidator` pipeline.

    Args:
        results: Query result dicts from GQLAlchemy.
        model: The :class:`GraphDataModel` to validate against.

    Returns:
        A :class:`ValidationResult` with any issues found.
    """
    nodes, rels = gqa_results_to_graph_data(results, model)
    validator = GraphValidator(model)
    return validator.validate(nodes=nodes, relationships=rels)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pick_primary_label(
    labels: set[str],
    model: GraphDataModel,
) -> str:
    """Select the primary label from a multi-label node.

    Prefers labels that match the model.  Falls back to alphabetical
    sorting if no model match or multiple matches exist.
    """
    model_labels = model.node_labels
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
