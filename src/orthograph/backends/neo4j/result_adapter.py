"""Adapt neo4j driver results for orthograph validation."""

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.validation import GraphValidator


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
    graph_definition: GraphDefinition,
) -> dict[str, Any]:
    """Convert a neo4j Node to an orthograph validation dict."""
    label = _pick_primary_label(node.labels, graph_definition)
    props = dict(node.items())
    props["__label__"] = label
    return props


def rel_to_dict(
    rel: Any,
    graph_definition: GraphDefinition,
) -> dict[str, Any]:
    """Convert a neo4j Relationship to an orthograph validation dict."""
    props = dict(rel.items())
    props["__label__"] = rel.type
    props["__source_uid__"] = _resolve_uid(rel.start_node, graph_definition)
    props["__target_uid__"] = _resolve_uid(rel.end_node, graph_definition)
    return props


def records_to_graph_data(
    records: Sequence[Any],
    graph_definition: GraphDefinition,
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
                    nodes.append(node_to_dict(value, graph_definition))
            elif _is_relationship(value):
                eid = value.element_id
                if eid not in seen_rel_ids:
                    seen_rel_ids.add(eid)
                    rels.append(rel_to_dict(value, graph_definition))

    return nodes, rels


def validate_result(
    records: Sequence[Any],
    graph_definition: GraphDefinition,
    result_graph_data_model: GraphDefinition | None = None,
) -> ValidationResult:
    """Validate neo4j driver query results against a :class:`GraphDefinition`.

    When ``result_graph_data_model`` is provided it takes precedence over
    ``graph_definition`` for the validation model.
    """
    effective_graph_data_model = (
        result_graph_data_model
        if result_graph_data_model is not None
        else graph_definition
    )
    nodes, rels = records_to_graph_data(records, effective_graph_data_model)
    validator = GraphValidator(effective_graph_data_model)
    return validator.validate(nodes=nodes, relationships=rels)


# --- Internal helpers ---


def _pick_primary_label(
    labels: frozenset[str],
    graph_definition: GraphDefinition,
) -> str:
    """Select the primary label from a multi-label node."""
    model_labels = graph_definition.node_labels
    matching = labels & model_labels
    if len(matching) == 1:
        return next(iter(matching))
    if len(matching) > 1:
        return sorted(matching)[0]
    return sorted(labels)[0] if labels else "__unknown__"


def _resolve_uid(
    node: Any,
    graph_definition: GraphDefinition,
) -> str:
    """Extract the UID value from a node using the graph_definition's uid_field."""
    if node is None:
        return "__unknown__"
    label = _pick_primary_label(node.labels, graph_definition)
    node_type = graph_definition.get_node_type(label)
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
