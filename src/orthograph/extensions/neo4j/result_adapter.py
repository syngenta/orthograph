"""Adapt neo4j driver results for orthograph validation."""

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from orthograph.core.errors import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.validator import GraphValidator


@runtime_checkable
class NodeLike(Protocol):
    """Protocol matching neo4j.graph.Node interface."""

    labels: frozenset[str]
    element_id: str

    def get(self, key: str, default: Any = None) -> Any: ...
    def items(self) -> Any: ...


@runtime_checkable
class RelationshipLike(Protocol):
    """Protocol matching neo4j.graph.Relationship interface."""

    type: str
    element_id: str
    start_node: Any
    end_node: Any

    def items(self) -> Any: ...


@runtime_checkable
class RecordLike(Protocol):
    """Protocol matching neo4j.Record interface."""

    def keys(self) -> list[str]: ...
    def values(self) -> list[Any]: ...
    def items(self) -> list[tuple[str, Any]]: ...


def node_to_dict(
    node: Any,
    model: GraphDataModel,
) -> dict[str, Any]:
    """Convert a neo4j Node to an orthograph validation dict."""
    label = _pick_primary_label(node.labels, model)
    props = dict(node.items())
    props["__label__"] = label
    return props


def rel_to_dict(
    rel: Any,
    model: GraphDataModel,
) -> dict[str, Any]:
    """Convert a neo4j Relationship to an orthograph validation dict."""
    props = dict(rel.items())
    props["__label__"] = rel.type
    props["__source_uid__"] = _resolve_uid(rel.start_node, model)
    props["__target_uid__"] = _resolve_uid(rel.end_node, model)
    return props


def records_to_graph_data(
    records: Sequence[Any],
    model: GraphDataModel,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract nodes and relationships from neo4j Records.

    Inspects each value in each record. Objects with a ``labels``
    attribute (frozenset) are treated as nodes; objects with ``type``
    and ``start_node`` attributes are treated as relationships.
    Scalars are skipped.
    """
    seen_node_ids: set[str] = set()
    seen_rel_ids: set[str] = set()
    nodes: list[dict[str, Any]] = []
    rels: list[dict[str, Any]] = []

    for record in records:
        for _, value in record.items():
            if _is_node(value):
                eid = value.element_id
                if eid not in seen_node_ids:
                    seen_node_ids.add(eid)
                    nodes.append(node_to_dict(value, model))
            elif _is_relationship(value):
                eid = value.element_id
                if eid not in seen_rel_ids:
                    seen_rel_ids.add(eid)
                    rels.append(rel_to_dict(value, model))

    return nodes, rels


def validate_result(
    records: Sequence[Any],
    model: GraphDataModel,
    result_model: GraphDataModel | None = None,
) -> ValidationResult:
    """Validate neo4j driver query results against a GraphDataModel.

    Args:
        records: Query result records from the neo4j driver.
        model: The GraphDataModel to validate against. If *result_model*
            is provided, this parameter is ignored and *result_model*
            is used instead.
        result_model: Optional specific model for the query's expected
            output. If provided, validation uses this model.
    """
    effective_model = result_model if result_model is not None else model
    nodes, rels = records_to_graph_data(records, effective_model)
    validator = GraphValidator(effective_model)
    return validator.validate(nodes=nodes, relationships=rels)


# --- Internal helpers ---


def _pick_primary_label(
    labels: frozenset[str],
    model: GraphDataModel,
) -> str:
    """Select the primary label from a multi-label node."""
    model_labels = model.node_labels
    matching = labels & model_labels
    if len(matching) == 1:
        return next(iter(matching))
    if len(matching) > 1:
        return sorted(matching)[0]
    return sorted(labels)[0] if labels else "__unknown__"


def _resolve_uid(
    node: Any,
    model: GraphDataModel,
) -> str:
    """Extract the UID value from a node using the model's uid_field."""
    if node is None:
        return "__unknown__"
    label = _pick_primary_label(node.labels, model)
    node_type = model.get_node_type(label)
    if node_type and node_type.__uid_field__:
        uid_val = node.get(node_type.__uid_field__)
        if uid_val is not None:
            return str(uid_val)
    return str(node.element_id)


def _is_node(value: Any) -> bool:
    """Check if a value looks like a neo4j Node."""
    return (
        hasattr(value, "labels")
        and isinstance(getattr(value, "labels", None), frozenset)
        and hasattr(value, "element_id")
        and hasattr(value, "items")
    )


def _is_relationship(value: Any) -> bool:
    """Check if a value looks like a neo4j Relationship."""
    if _is_node(value):
        return False
    return (
        hasattr(value, "type")
        and hasattr(value, "start_node")
        and hasattr(value, "end_node")
        and hasattr(value, "element_id")
        and isinstance(getattr(value, "type", None), str)
    )
