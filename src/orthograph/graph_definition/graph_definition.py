"""GraphDefinition — the declared graph structure."""

from enum import Enum
from typing import Any

from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import (
    GraphValidationError,
    ValidationIssue,
    ValidationResult,
)
from orthograph.graph_definition.models import NodeModel, RelationshipModel


class GraphDefinition:
    """Declared graph structure: node types, relationship types, and constraints.

    Validates structural consistency at construction and raises
    :class:`~orthograph.diagnostics.result.GraphValidationError` on errors.

    **Thread-safe and immutable:** All state is set during construction and
    cannot be modified after initialization. Safe for concurrent read access.
    """

    def __init__(
        self,
        name: str,
        node_types: list[type[NodeModel]],
        relationship_types: list[type[RelationshipModel]],
        version: str | None = None,
    ) -> None:
        # Use object.__setattr__ to bypass the freeze check during construction
        object.__setattr__(self, "_initialized", False)

        self.name = name
        self.version = version

        self._node_type_map: dict[str, type[NodeModel]] = {}
        self._rel_type_map: dict[str, type[RelationshipModel]] = {}

        for nt in node_types:
            self._node_type_map[nt.__label__] = nt
        for rt in relationship_types:
            self._rel_type_map[rt.__label__] = rt

        self.node_types = list(node_types)
        self.relationship_types = list(relationship_types)

        # Validate and raise on errors
        result = self._check_structure()
        errors = result.errors
        if errors:
            raise GraphValidationError(errors)

        # Mark initialization complete; all future assignments will be blocked
        object.__setattr__(self, "_initialized", True)

    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent attribute modification after initialization."""
        if object.__getattribute__(self, "_initialized"):
            raise AttributeError(
                f"GraphDefinition is frozen after initialization; "
                f"cannot set attribute '{name}'"
            )
        object.__setattr__(self, name, value)

    # --- Lookup ---

    def get_node_type(self, label: str) -> type[NodeModel] | None:
        return self._node_type_map.get(label)

    def get_relationship_type(self, label: str) -> type[RelationshipModel] | None:
        return self._rel_type_map.get(label)

    @property
    def node_labels(self) -> set[str]:
        return set(self._node_type_map.keys())

    @property
    def relationship_labels(self) -> set[str]:
        return set(self._rel_type_map.keys())

    # --- Relationship queries ---

    def get_outgoing_relationship_types(
        self, node_type: type[NodeModel]
    ) -> list[type[RelationshipModel]]:
        label = node_type.__label__
        result: list[type[RelationshipModel]] = []
        for rt in self.relationship_types:
            if rt.__source_label__ == label:
                result.append(rt)
            elif not rt.__directed__ and rt.__target_label__ == label:
                # Undirected: also outgoing from target node type
                result.append(rt)
        return result

    def get_incoming_relationship_types(
        self, node_type: type[NodeModel]
    ) -> list[type[RelationshipModel]]:
        label = node_type.__label__
        result: list[type[RelationshipModel]] = []
        for rt in self.relationship_types:
            if rt.__target_label__ == label:
                result.append(rt)
            elif not rt.__directed__ and rt.__source_label__ == label:
                # Undirected: also incoming to source node type
                result.append(rt)
        return result

    # --- Enum generation ---

    def get_node_label_enum(self) -> Any:
        return Enum(
            "NodeLabel",
            {label: label for label in self._node_type_map},
        )

    def get_relationship_label_enum(self) -> Any:
        return Enum(
            "RelationshipLabel",
            {label: label for label in self._rel_type_map},
        )

    # --- Structural validation ---

    def validate_structure(self) -> ValidationResult:
        return self._check_structure()

    def _check_structure(self) -> ValidationResult:
        result = ValidationResult()
        self._check_duplicate_labels(result)
        self._check_undefined_node_refs(result)
        self._check_isolated_nodes(result)
        return result

    def _check_duplicate_labels(self, result: ValidationResult) -> None:
        seen_nodes: set[str] = set()
        for nt in self.node_types:
            if nt.__label__ in seen_nodes:
                result.add(
                    ValidationIssue(
                        code="DUPLICATE_NODE_LABEL",
                        severity=Severity.ERROR,
                        entity_type=EntityType.NODE,
                        entity_id=nt.__label__,
                        message=(f"Duplicate node label: {nt.__label__}"),
                    )
                )
            seen_nodes.add(nt.__label__)

        seen_rels: set[str] = set()
        for rt in self.relationship_types:
            if rt.__label__ in seen_rels:
                result.add(
                    ValidationIssue(
                        code="DUPLICATE_RELATIONSHIP_LABEL",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=rt.__label__,
                        message=(f"Duplicate relationship label: {rt.__label__}"),
                    )
                )
            seen_rels.add(rt.__label__)

    def _check_undefined_node_refs(self, result: ValidationResult) -> None:
        node_labels = self.node_labels
        for rt in self.relationship_types:
            src = rt.__source_label__
            tgt = rt.__target_label__
            if src not in node_labels:
                result.add(
                    ValidationIssue(
                        code="UNDEFINED_NODE_TYPE",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=rt.__label__,
                        message=(
                            f"Relationship {rt.__label__} references "
                            f"undefined source node type: {src}"
                        ),
                        context={"node_label": src, "role": "source"},
                    )
                )
            if tgt not in node_labels:
                result.add(
                    ValidationIssue(
                        code="UNDEFINED_NODE_TYPE",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=rt.__label__,
                        message=(
                            f"Relationship {rt.__label__} references "
                            f"undefined target node type: {tgt}"
                        ),
                        context={"node_label": tgt, "role": "target"},
                    )
                )

    def _check_isolated_nodes(self, result: ValidationResult) -> None:
        connected: set[str] = set()
        for rt in self.relationship_types:
            connected.add(rt.__source_label__)
            connected.add(rt.__target_label__)

        for nt in self.node_types:
            if nt.__label__ not in connected:
                result.add(
                    ValidationIssue(
                        code="ISOLATED_NODE",
                        severity=Severity.WARNING,
                        entity_type=EntityType.NODE,
                        entity_id=nt.__label__,
                        message=(
                            f"Node type {nt.__label__} is not "
                            "connected by any relationship"
                        ),
                    )
                )
