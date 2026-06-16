"""GraphValidator -- validates graph data against a GraphDefinition."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue, ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel


# Type alias for the (label, src_uid, tgt_uid, props) tuple used internally
_RelRecord = tuple[str, str, str, dict[str, Any]]

# Degree counters: maps (uid, rel_label) → count
_DegreeCounts = dict[tuple[str, str], int]


# ---------------------------------------------------------------------------
# Input unpacking helpers
# ---------------------------------------------------------------------------


def _unpack_node(
    node: dict[str, Any] | NodeModel,
) -> tuple[str | None, dict[str, Any]]:
    """Return (label, props) from a node dict or NodeModel instance.

    ``props`` contains only property fields — never any dunder meta keys.
    """
    if isinstance(node, NodeModel):
        return node.__label__, node.model_dump()
    data = dict(node)
    return data.pop("__label__", None), data


def _unpack_rel(
    rel: dict[str, Any] | RelationshipModel,
) -> tuple[str | None, str | None, str | None, dict[str, Any]]:
    """Return (label, src_uid, tgt_uid, props) from a relationship dict or instance.

    ``props`` contains only property fields — never any dunder meta keys.
    For a ``RelationshipModel`` instance, ``src_uid`` and ``tgt_uid`` are
    always ``None`` because endpoint identity is not part of the model schema;
    callers that pass model instances must not require endpoint-uid validation.
    """
    if isinstance(rel, RelationshipModel):
        return rel.__label__, None, None, rel.model_dump()
    data = dict(rel)
    label = data.pop("__label__", None)
    src_uid = data.pop("__source_uid__", None)
    tgt_uid = data.pop("__target_uid__", None)
    return label, src_uid, tgt_uid, data


def _check_endpoint_types(
    label: str,
    src_uid: str,
    tgt_uid: str,
    src_actual: str,
    tgt_actual: str,
    rel_type: type[RelationshipModel],
) -> list[ValidationIssue]:
    """Return endpoint-type issues for a single relationship instance.

    Called only when both source and target nodes are present in the node index.
    Returns an empty list when endpoints are valid.
    """
    expected_src = rel_type.__source_label__
    expected_tgt = rel_type.__target_label__

    forward_ok = src_actual == expected_src and tgt_actual == expected_tgt
    reverse_ok = (
        not rel_type.__directed__
        and src_actual == expected_tgt
        and tgt_actual == expected_src
    )
    if forward_ok or reverse_ok:
        return []

    entity_id = f"{label}:{src_uid}->{tgt_uid}"

    if not rel_type.__directed__:
        valid_types = sorted({expected_src, expected_tgt})
        return [
            ValidationIssue(
                code="WRONG_ENDPOINT_TYPE",
                severity=Severity.ERROR,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=entity_id,
                message=(
                    f"Undirected relationship '{label}' "
                    f"endpoints ({src_actual}, {tgt_actual}) "
                    f"do not match expected types ({', '.join(valid_types)})"
                ),
                context={
                    "actual_source": src_actual,
                    "actual_target": tgt_actual,
                    "expected_types": valid_types,
                },
            )
        ]

    # Directed: report each mismatched endpoint individually
    issues: list[ValidationIssue] = []
    for uid, actual, expected, role in (
        (src_uid, src_actual, expected_src, "source"),
        (tgt_uid, tgt_actual, expected_tgt, "target"),
    ):
        if actual != expected:
            issues.append(
                ValidationIssue(
                    code="WRONG_ENDPOINT_TYPE",
                    severity=Severity.ERROR,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=entity_id,
                    message=(
                        f"{role.capitalize()} node '{uid}' has label '{actual}', "
                        f"expected '{expected}'"
                    ),
                    context={
                        "uid": uid,
                        "role": role,
                        "actual": actual,
                        "expected": expected,
                    },
                )
            )
    return issues


def _cardinality_violation_issue(
    uid: str,
    node_label: str,
    rel_type: type[RelationshipModel],
    direction: str,
    count: int,
) -> ValidationIssue | None:
    """Return a CARDINALITY_VIOLATION issue if ``count`` is out of range, else None."""
    cardinality = (
        rel_type.__source_cardinality__
        if direction != "incoming"
        else rel_type.__target_cardinality__
    )
    if cardinality.contains(count):
        return None
    max_str = "N" if cardinality.max is None else str(cardinality.max)
    return ValidationIssue(
        code="CARDINALITY_VIOLATION",
        severity=Severity.ERROR,
        entity_type=EntityType.NODE,
        entity_id=f"{node_label}:{uid}",
        message=(
            f"Node '{uid}' ({node_label}) has {count} {direction} "
            f"{rel_type.__label__} relationships, "
            f"expected {cardinality.min}..{max_str}"
        ),
        context={
            "rel_label": rel_type.__label__,
            "direction": direction,
            "expected_min": cardinality.min,
            "expected_max": cardinality.max,
            "actual": count,
        },
    )


def _collect_present_labels(
    items: Sequence[dict[str, Any] | NodeModel | RelationshipModel],
    *,
    unpack: Any,
) -> set[str]:
    """Return the set of ``__label__`` values present in *items*."""
    labels: set[str] = set()
    for item in items:
        label = unpack(item)[0]
        if label:
            labels.add(label)
    return labels


def _pydantic_issues(
    entity_type: EntityType,
    entity_id: str,
    exc: PydanticValidationError,
) -> list[ValidationIssue]:
    """Convert a PydanticValidationError into a list of ValidationIssues."""
    return [
        ValidationIssue(
            code="PROPERTY_VALIDATION_ERROR",
            severity=Severity.ERROR,
            entity_type=entity_type,
            entity_id=entity_id,
            message=(
                f"Validation error: {err['msg']} "
                f"(field: {'.'.join(str(loc) for loc in err['loc'])})"
            ),
            context={"pydantic_error": err},
        )
        for err in exc.errors()
    ]


def _extra_properties_issue(
    entity_type: EntityType,
    entity_id: str,
    extra: set[str],
) -> ValidationIssue:
    """Return an EXTRA_PROPERTIES issue for ``extra`` property keys."""
    return ValidationIssue(
        code="EXTRA_PROPERTIES",
        severity=Severity.ERROR,
        entity_type=entity_type,
        entity_id=entity_id,
        message=f"Extra properties not in model: {', '.join(sorted(extra))}",
        context={"extra": sorted(extra)},
    )


def _count_rel_degrees(
    rel_records: list[_RelRecord],
    graph_definition: GraphDefinition,
) -> tuple[_DegreeCounts, _DegreeCounts, _DegreeCounts]:
    """Accumulate outgoing, incoming, and undirected degree counts.

    Returns ``(outgoing_counts, incoming_counts, undirected_counts)`` where
    each maps ``(uid, rel_label)`` to the number of occurrences.
    Undirected counts include both endpoints for each undirected relationship.
    """
    outgoing: _DegreeCounts = defaultdict(int)
    incoming: _DegreeCounts = defaultdict(int)
    undirected: _DegreeCounts = defaultdict(int)

    for label, src_uid, tgt_uid, _ in rel_records:
        outgoing[(src_uid, label)] += 1
        incoming[(tgt_uid, label)] += 1
        rel_type = graph_definition.get_relationship_type(label)
        if rel_type and not rel_type.__directed__:
            undirected[(src_uid, label)] += 1
            undirected[(tgt_uid, label)] += 1

    return outgoing, incoming, undirected


def _check_node_cardinality(
    uid: str,
    node_label: str,
    node_type: Any,
    graph_definition: GraphDefinition,
    outgoing: _DegreeCounts,
    incoming: _DegreeCounts,
    undirected: _DegreeCounts,
) -> list[ValidationIssue]:
    """Return cardinality violations for a single node across all its rel types."""
    issues: list[ValidationIssue] = []

    for rel_type in graph_definition.get_outgoing_relationship_types(node_type):
        direction = "total" if not rel_type.__directed__ else "outgoing"
        counts = undirected if not rel_type.__directed__ else outgoing
        count = counts.get((uid, rel_type.__label__), 0)
        issue = _cardinality_violation_issue(
            uid, node_label, rel_type, direction, count
        )
        if issue is not None:
            issues.append(issue)

    for rel_type in graph_definition.get_incoming_relationship_types(node_type):
        if not rel_type.__directed__:
            continue
        count = incoming.get((uid, rel_type.__label__), 0)
        issue = _cardinality_violation_issue(
            uid, node_label, rel_type, "incoming", count
        )
        if issue is not None:
            issues.append(issue)

    return issues


class GraphValidator:
    """Validates graph data (nodes + relationships) against a GraphDefinition.

    Performs: label checks, property validation, referential integrity,
    cardinality checks, and entity presence checks.
    """

    def __init__(self, graph_definition: GraphDefinition) -> None:
        self.graph_definition = graph_definition

    def validate(
        self,
        nodes: Sequence[dict[str, Any] | NodeModel],
        relationships: Sequence[dict[str, Any] | RelationshipModel] | None = None,
    ) -> ValidationResult:
        """Full graph validation: nodes, relationships, references, cardinality."""
        result = ValidationResult()

        if relationships is None:
            relationships = []

        node_result, node_index = self._validate_and_index_nodes(nodes)
        result.merge(node_result)

        rel_result, rel_records = self._validate_and_collect_rels(relationships)
        result.merge(rel_result)

        # Referential integrity + endpoint type checks
        ref_result = self._check_referential_integrity(rel_records, node_index)
        result.merge(ref_result)

        # Cardinality checks
        card_result = self._check_cardinality(node_index, rel_records)
        result.merge(card_result)

        # Entity presence checks
        presence_result = self._check_entity_presence(nodes, relationships)
        result.merge(presence_result)

        return result

    def validate_nodes(
        self, nodes: Sequence[dict[str, Any] | NodeModel]
    ) -> ValidationResult:
        """Validate nodes only (no referential or cardinality checks)."""
        result, _ = self._validate_and_index_nodes(nodes)
        return result

    def validate_relationships(
        self,
        relationships: Sequence[dict[str, Any] | RelationshipModel],
    ) -> ValidationResult:
        """Validate relationships only (no referential checks)."""
        result, _ = self._validate_and_collect_rels(relationships)
        return result

    # --- Internal: node validation ---

    def _validate_and_index_nodes(
        self, nodes: Sequence[dict[str, Any] | NodeModel]
    ) -> tuple[ValidationResult, dict[str, tuple[str, str]]]:
        """Validate nodes and build uid->(label, uid) index.

        Returns (result, {uid: (label, uid)}) for referential checks.
        """
        result = ValidationResult()
        node_index: dict[str, tuple[str, str]] = {}

        for i, node in enumerate(nodes):
            label, props = _unpack_node(node)

            if label is None:
                result.add(
                    ValidationIssue(
                        code="MISSING_LABEL",
                        severity=Severity.ERROR,
                        entity_type=EntityType.NODE,
                        entity_id=f"node[{i}]",
                        message="Node is missing __label__ field",
                    )
                )
                continue

            node_type = self.graph_definition.get_node_type(label)
            if node_type is None:
                result.add(
                    ValidationIssue(
                        code="UNKNOWN_NODE_LABEL",
                        severity=Severity.ERROR,
                        entity_type=EntityType.NODE,
                        entity_id=f"node[{i}]",
                        message=f"Unknown node label: {label}",
                        context={"label": label},
                    )
                )
                continue

            entity_id = f"node[{i}]:{label}"
            extra = set(props.keys()) - node_type.get_all_property_names()
            if extra:
                result.add(_extra_properties_issue(EntityType.NODE, entity_id, extra))
                continue

            try:
                node_type.model_validate(props)
            except PydanticValidationError as e:
                for issue in _pydantic_issues(EntityType.NODE, entity_id, e):
                    result.add(issue)

            uid_field = node_type.__uid_field__
            if uid_field and uid_field in props:
                uid_val = str(props[uid_field])
                node_index[uid_val] = (label, uid_val)

        return result, node_index

    # --- Internal: relationship validation ---

    def _validate_and_collect_rels(
        self,
        relationships: Sequence[dict[str, Any] | RelationshipModel],
    ) -> tuple[ValidationResult, list[tuple[str, str, str, dict[str, Any]]]]:
        """Validate relationships and collect (label, src_uid, tgt_uid, props).

        Returns (result, records) for referential/cardinality checks.
        """
        result = ValidationResult()
        records: list[tuple[str, str, str, dict[str, Any]]] = []

        for i, rel in enumerate(relationships):
            label, src_uid, tgt_uid, props = _unpack_rel(rel)

            if label is None:
                result.add(
                    ValidationIssue(
                        code="MISSING_LABEL",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"rel[{i}]",
                        message="Relationship is missing __label__",
                    )
                )
                continue

            rel_type = self.graph_definition.get_relationship_type(label)
            if rel_type is None:
                result.add(
                    ValidationIssue(
                        code="UNKNOWN_RELATIONSHIP_LABEL",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"rel[{i}]",
                        message=f"Unknown relationship label: {label}",
                        context={"label": label},
                    )
                )
                continue

            if src_uid is None or tgt_uid is None:
                result.add(
                    ValidationIssue(
                        code="MISSING_ENDPOINT",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"rel[{i}]:{label}",
                        message="Relationship missing __source_uid__ or __target_uid__",
                    )
                )
                continue

            entity_id = f"rel[{i}]:{label}"
            extra = set(props.keys()) - rel_type.get_all_property_names()
            if extra:
                result.add(
                    _extra_properties_issue(EntityType.RELATIONSHIP, entity_id, extra)
                )
                continue

            try:
                rel_type.model_validate(props)
            except PydanticValidationError as e:
                for issue in _pydantic_issues(EntityType.RELATIONSHIP, entity_id, e):
                    result.add(issue)

            records.append((label, str(src_uid), str(tgt_uid), props))

        return result, records

    # --- Internal: referential integrity ---

    def _check_referential_integrity(
        self,
        rel_records: list[tuple[str, str, str, dict[str, Any]]],
        node_index: dict[str, tuple[str, str]],
    ) -> ValidationResult:
        result = ValidationResult()

        for label, src_uid, tgt_uid, _ in rel_records:
            rel_type = self.graph_definition.get_relationship_type(label)
            if rel_type is None:
                continue

            entity_id = f"{label}:{src_uid}->{tgt_uid}"

            for uid, role in ((src_uid, "source"), (tgt_uid, "target")):
                if uid not in node_index:
                    result.add(
                        ValidationIssue(
                            code="DANGLING_REFERENCE",
                            severity=Severity.ERROR,
                            entity_type=EntityType.RELATIONSHIP,
                            entity_id=entity_id,
                            message=f"{role.capitalize()} node "
                            f"'{uid}' not found in provided nodes",
                            context={"uid": uid, "role": role},
                        )
                    )

            if src_uid in node_index and tgt_uid in node_index:
                src_actual = node_index[src_uid][0]
                tgt_actual = node_index[tgt_uid][0]
                for issue in _check_endpoint_types(
                    label, src_uid, tgt_uid, src_actual, tgt_actual, rel_type
                ):
                    result.add(issue)

        return result

    # --- Internal: cardinality checks ---

    def _check_cardinality(
        self,
        node_index: dict[str, tuple[str, str]],
        rel_records: list[tuple[str, str, str, dict[str, Any]]],
    ) -> ValidationResult:
        result = ValidationResult()
        outgoing, incoming, undirected = _count_rel_degrees(
            rel_records, self.graph_definition
        )

        for uid, (node_label, _) in node_index.items():
            node_type = self.graph_definition.get_node_type(node_label)
            if node_type is None:
                continue
            for issue in _check_node_cardinality(
                uid,
                node_label,
                node_type,
                self.graph_definition,
                outgoing,
                incoming,
                undirected,
            ):
                result.add(issue)

        return result

    # --- Internal: entity presence ---

    def _check_entity_presence(
        self,
        nodes: Sequence[dict[str, Any] | NodeModel],
        relationships: Sequence[dict[str, Any] | RelationshipModel],
    ) -> ValidationResult:
        result = ValidationResult()

        present_node_labels = _collect_present_labels(nodes, unpack=_unpack_node)
        for nt in self.graph_definition.node_types:
            if not nt.__optional__ and nt.__label__ not in present_node_labels:
                result.add(
                    ValidationIssue(
                        code="MISSING_REQUIRED_TYPE",
                        severity=Severity.ERROR,
                        entity_type=EntityType.NODE,
                        entity_id=nt.__label__,
                        message=f"Required node type "
                        f"'{nt.__label__}' has no instances in data",
                    )
                )

        present_rel_labels = _collect_present_labels(relationships, unpack=_unpack_rel)
        for rt in self.graph_definition.relationship_types:
            if not rt.__optional__ and rt.__label__ not in present_rel_labels:
                result.add(
                    ValidationIssue(
                        code="MISSING_REQUIRED_TYPE",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=rt.__label__,
                        message=f"Required relationship type "
                        f"'{rt.__label__}' has no instances in data",
                    )
                )

        return result
