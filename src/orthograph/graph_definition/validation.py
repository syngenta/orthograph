"""GraphValidator -- validates graph data against a GraphDefinition."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue, ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel


# Reserved keys in node/relationship data dicts
_NODE_META_KEYS = {"__label__"}
_REL_META_KEYS = {"__label__", "__source_uid__", "__target_uid__"}


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
            data = self._to_dict(node)
            label = data.get("__label__")

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

            props = {k: v for k, v in data.items() if k not in _NODE_META_KEYS}
            allowed = node_type.get_all_property_names()
            extra = set(props.keys()) - allowed
            if extra:
                result.add(
                    ValidationIssue(
                        code="EXTRA_PROPERTIES",
                        severity=Severity.ERROR,
                        entity_type=EntityType.NODE,
                        entity_id=f"node[{i}]:{label}",
                        message=(
                            f"Extra properties not in model: {', '.join(sorted(extra))}"
                        ),
                        context={"extra": sorted(extra)},
                    )
                )
                continue

            try:
                node_type.model_validate(props)
            except PydanticValidationError as e:
                for err in e.errors():
                    result.add(
                        ValidationIssue(
                            code="PROPERTY_VALIDATION_ERROR",
                            severity=Severity.ERROR,
                            entity_type=EntityType.NODE,
                            entity_id=f"node[{i}]:{label}",
                            message=(
                                f"Validation error: {err['msg']} "
                                f"(field: {'.'.join(str(loc) for loc in err['loc'])})"
                            ),
                            context={"pydantic_error": err},
                        )
                    )

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
            data = self._to_rel_dict(rel)
            label = data.get("__label__")

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
                        message=(f"Unknown relationship label: {label}"),
                        context={"label": label},
                    )
                )
                continue

            src_uid = data.get("__source_uid__")
            tgt_uid = data.get("__target_uid__")
            if src_uid is None or tgt_uid is None:
                result.add(
                    ValidationIssue(
                        code="MISSING_ENDPOINT",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"rel[{i}]:{label}",
                        message=(
                            "Relationship missing __source_uid__ or __target_uid__"
                        ),
                    )
                )
                continue

            props = {k: v for k, v in data.items() if k not in _REL_META_KEYS}
            allowed = rel_type.get_all_property_names()
            extra = set(props.keys()) - allowed
            if extra:
                result.add(
                    ValidationIssue(
                        code="EXTRA_PROPERTIES",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"rel[{i}]:{label}",
                        message=(f"Extra properties: {', '.join(sorted(extra))}"),
                        context={"extra": sorted(extra)},
                    )
                )
                continue

            try:
                rel_type.model_validate(props)
            except PydanticValidationError as e:
                for err in e.errors():
                    result.add(
                        ValidationIssue(
                            code="PROPERTY_VALIDATION_ERROR",
                            severity=Severity.ERROR,
                            entity_type=EntityType.RELATIONSHIP,
                            entity_id=f"rel[{i}]:{label}",
                            message=(
                                f"Validation error: {err['msg']} "
                                f"(field: {'.'.join(str(loc) for loc in err['loc'])})"
                            ),
                            context={"pydantic_error": err},
                        )
                    )

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

            # Check source exists
            if src_uid not in node_index:
                result.add(
                    ValidationIssue(
                        code="DANGLING_REFERENCE",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"{label}:{src_uid}->{tgt_uid}",
                        message=(
                            f"Source node '{src_uid}' not found in provided nodes"
                        ),
                        context={
                            "uid": src_uid,
                            "role": "source",
                        },
                    )
                )

            # Check target exists
            if tgt_uid not in node_index:
                result.add(
                    ValidationIssue(
                        code="DANGLING_REFERENCE",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"{label}:{src_uid}->{tgt_uid}",
                        message=(
                            f"Target node '{tgt_uid}' not found in provided nodes"
                        ),
                        context={
                            "uid": tgt_uid,
                            "role": "target",
                        },
                    )
                )

            # Check endpoint types (only if both nodes exist)
            if src_uid in node_index and tgt_uid in node_index:
                src_actual = node_index[src_uid][0]
                tgt_actual = node_index[tgt_uid][0]
                expected_src = rel_type.__source_label__
                expected_tgt = rel_type.__target_label__

                forward_ok = src_actual == expected_src and tgt_actual == expected_tgt
                reverse_ok = (
                    not rel_type.__directed__
                    and src_actual == expected_tgt
                    and tgt_actual == expected_src
                )

                if not forward_ok and not reverse_ok:
                    if rel_type.__directed__:
                        # Report specific endpoint mismatches
                        if src_actual != expected_src:
                            result.add(
                                ValidationIssue(
                                    code="WRONG_ENDPOINT_TYPE",
                                    severity=Severity.ERROR,
                                    entity_type=EntityType.RELATIONSHIP,
                                    entity_id=f"{label}:{src_uid}->{tgt_uid}",
                                    message=(
                                        f"Source node '{src_uid}' has label "
                                        f"'{src_actual}', expected "
                                        f"'{expected_src}'"
                                    ),
                                    context={
                                        "uid": src_uid,
                                        "role": "source",
                                        "actual": src_actual,
                                        "expected": expected_src,
                                    },
                                )
                            )
                        if tgt_actual != expected_tgt:
                            result.add(
                                ValidationIssue(
                                    code="WRONG_ENDPOINT_TYPE",
                                    severity=Severity.ERROR,
                                    entity_type=EntityType.RELATIONSHIP,
                                    entity_id=f"{label}:{src_uid}->{tgt_uid}",
                                    message=(
                                        f"Target node '{tgt_uid}' has label "
                                        f"'{tgt_actual}', expected "
                                        f"'{expected_tgt}'"
                                    ),
                                    context={
                                        "uid": tgt_uid,
                                        "role": "target",
                                        "actual": tgt_actual,
                                        "expected": expected_tgt,
                                    },
                                )
                            )
                    else:
                        # Undirected: neither forward nor reverse matched
                        valid_types = sorted({expected_src, expected_tgt})
                        result.add(
                            ValidationIssue(
                                code="WRONG_ENDPOINT_TYPE",
                                severity=Severity.ERROR,
                                entity_type=EntityType.RELATIONSHIP,
                                entity_id=f"{label}:{src_uid}->{tgt_uid}",
                                message=(
                                    f"Undirected relationship '{label}' "
                                    f"endpoints ({src_actual}, {tgt_actual}) "
                                    f"do not match expected types "
                                    f"({', '.join(valid_types)})"
                                ),
                                context={
                                    "actual_source": src_actual,
                                    "actual_target": tgt_actual,
                                    "expected_types": valid_types,
                                },
                            )
                        )

        return result

    # --- Internal: cardinality checks ---

    def _check_cardinality(
        self,
        node_index: dict[str, tuple[str, str]],
        rel_records: list[tuple[str, str, str, dict[str, Any]]],
    ) -> ValidationResult:
        result = ValidationResult()

        outgoing_counts: dict[tuple[str, str], int] = defaultdict(int)
        incoming_counts: dict[tuple[str, str], int] = defaultdict(int)
        # For undirected: total connections per (uid, rel_label)
        undirected_counts: dict[tuple[str, str], int] = defaultdict(int)

        for label, src_uid, tgt_uid, _ in rel_records:
            rel_type = self.graph_definition.get_relationship_type(label)
            outgoing_counts[(src_uid, label)] += 1
            incoming_counts[(tgt_uid, label)] += 1
            if rel_type and not rel_type.__directed__:
                undirected_counts[(src_uid, label)] += 1
                undirected_counts[(tgt_uid, label)] += 1

        # Check source cardinality for each node
        for uid, (node_label, _) in node_index.items():
            node_type = self.graph_definition.get_node_type(node_label)
            if node_type is None:
                continue

            outgoing_rels = self.graph_definition.get_outgoing_relationship_types(
                node_type
            )
            for rel_type in outgoing_rels:
                cardinality = rel_type.__source_cardinality__

                if not rel_type.__directed__:
                    count = undirected_counts.get((uid, rel_type.__label__), 0)
                else:
                    count = outgoing_counts.get((uid, rel_type.__label__), 0)

                if not cardinality.contains(count):
                    max_str = "N" if cardinality.max is None else str(cardinality.max)
                    direction = "total" if not rel_type.__directed__ else "outgoing"
                    result.add(
                        ValidationIssue(
                            code="CARDINALITY_VIOLATION",
                            severity=Severity.ERROR,
                            entity_type=EntityType.NODE,
                            entity_id=f"{node_label}:{uid}",
                            message=(
                                f"Node '{uid}' ({node_label}) has "
                                f"{count} {direction} "
                                f"{rel_type.__label__} relationships, "
                                f"expected "
                                f"{cardinality.min}..{max_str}"
                            ),
                            context={
                                "rel_label": rel_type.__label__,
                                "direction": direction,
                                "expected_min": cardinality.min,
                                "expected_max": cardinality.max,
                                "actual": count,
                            },
                        )
                    )

            # Check target cardinality (incoming)
            # For undirected rels, skip this check since source cardinality
            # already covers both directions via undirected_counts
            incoming_rels = self.graph_definition.get_incoming_relationship_types(
                node_type
            )
            for rel_type in incoming_rels:
                if not rel_type.__directed__:
                    # Already handled above via undirected_counts
                    continue
                cardinality = rel_type.__target_cardinality__
                count = incoming_counts.get((uid, rel_type.__label__), 0)
                if not cardinality.contains(count):
                    max_str = "N" if cardinality.max is None else str(cardinality.max)
                    result.add(
                        ValidationIssue(
                            code="CARDINALITY_VIOLATION",
                            severity=Severity.ERROR,
                            entity_type=EntityType.NODE,
                            entity_id=f"{node_label}:{uid}",
                            message=(
                                f"Node '{uid}' ({node_label}) has "
                                f"{count} incoming "
                                f"{rel_type.__label__} relationships, "
                                f"expected "
                                f"{cardinality.min}..{max_str}"
                            ),
                            context={
                                "rel_label": rel_type.__label__,
                                "direction": "incoming",
                                "expected_min": cardinality.min,
                                "expected_max": cardinality.max,
                                "actual": count,
                            },
                        )
                    )

        return result

    # --- Internal: entity presence ---

    def _check_entity_presence(
        self,
        nodes: Sequence[dict[str, Any] | NodeModel],
        relationships: Sequence[dict[str, Any] | RelationshipModel],
    ) -> ValidationResult:
        result = ValidationResult()

        present_node_labels: set[str] = set()
        for n in nodes:
            d = self._to_dict(n)
            label = d.get("__label__")
            if label:
                present_node_labels.add(label)

        for nt in self.graph_definition.node_types:
            if not nt.__optional__ and nt.__label__ not in present_node_labels:
                result.add(
                    ValidationIssue(
                        code="MISSING_REQUIRED_TYPE",
                        severity=Severity.ERROR,
                        entity_type=EntityType.NODE,
                        entity_id=nt.__label__,
                        message=(
                            f"Required node type '{nt.__label__}' "
                            "has no instances in data"
                        ),
                    )
                )

        present_rel_labels: set[str] = set()
        for r in relationships:
            d = self._to_rel_dict(r)
            label = d.get("__label__")
            if label:
                present_rel_labels.add(label)

        for rt in self.graph_definition.relationship_types:
            if not rt.__optional__ and rt.__label__ not in present_rel_labels:
                result.add(
                    ValidationIssue(
                        code="MISSING_REQUIRED_TYPE",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=rt.__label__,
                        message=(
                            f"Required relationship type "
                            f"'{rt.__label__}' has no instances in data"
                        ),
                    )
                )

        return result

    # --- Helpers ---

    @staticmethod
    def _to_dict(node: dict[str, Any] | NodeModel) -> dict[str, Any]:
        if isinstance(node, NodeModel):
            d = node.model_dump()
            d["__label__"] = node.__label__
            return d
        return dict(node)

    @staticmethod
    def _to_rel_dict(
        rel: dict[str, Any] | RelationshipModel,
    ) -> dict[str, Any]:
        if isinstance(rel, RelationshipModel):
            d = rel.model_dump()
            d["__label__"] = rel.__label__
            return d
        return dict(rel)
