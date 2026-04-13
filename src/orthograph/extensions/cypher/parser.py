"""Cypher query parsing and validation against a GraphDataModel.

Uses a strategy pattern for the parser backend. Default: graphglot.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from graphglot.dialect import Dialect
from graphglot.lineage import LineageAnalyzer
from graphglot.lineage.models import BindingKind, LineageGraph

from orthograph.core.errors import ValidationIssue, ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.types import EntityType, Severity


@dataclass(frozen=True)
class PatternInfo:
    """A single graph pattern extracted from a Cypher query."""

    source_label: str | None
    relationship_type: str | None
    target_label: str | None
    direction: Literal["outgoing", "incoming", "undirected"] = "outgoing"


@dataclass
class CypherQueryInfo:
    """Structural information extracted from a parsed Cypher query."""

    node_labels: set[str] = field(default_factory=set)
    relationship_types: set[str] = field(default_factory=set)
    property_accesses: dict[str, set[str]] = field(default_factory=dict)
    variable_bindings: dict[str, str] = field(default_factory=dict)
    query_intent: str = "read"
    patterns: list[PatternInfo] = field(default_factory=list)


@runtime_checkable
class CypherParserStrategy(Protocol):
    """Protocol for Cypher parser backends."""

    def parse(self, query: str) -> CypherQueryInfo: ...


class GraphglotParser:
    """Cypher parser using graphglot."""

    def __init__(self, dialect: str = "neo4j") -> None:
        self._dialect = Dialect.get_or_raise(dialect)

    def parse(self, query: str) -> CypherQueryInfo:
        ast = self._dialect.parse(query)
        lg = LineageAnalyzer().analyze(ast[0])
        return self._extract(lg)

    def _extract(self, lg: LineageGraph) -> CypherQueryInfo:
        info = CypherQueryInfo()

        # Extract bindings (variables bound to labels/types)
        for binding_id in lg.bindings:
            binding = lg.nodes[binding_id]
            name = binding.name
            label_expr = binding.label_expression

            if binding.kind == BindingKind.NODE:
                if label_expr:
                    info.node_labels.add(str(label_expr))
                if name and label_expr:
                    info.variable_bindings[name] = str(label_expr)
            elif binding.kind == BindingKind.EDGE:
                if label_expr:
                    info.relationship_types.add(str(label_expr))
                if name and label_expr:
                    info.variable_bindings[name] = str(label_expr)

        # Extract property accesses
        for prop_id in lg.property_refs:
            prop_node = lg.nodes[prop_id]
            prop_name = prop_node.property_name
            # Find which binding this property ref depends on
            owner_var = self._find_prop_owner(prop_id, lg, info.variable_bindings)
            if owner_var:
                if owner_var not in info.property_accesses:
                    info.property_accesses[owner_var] = set()
                info.property_accesses[owner_var].add(prop_name)

        # Extract patterns (relationship connections)
        info.patterns = self._extract_patterns(lg, info)

        # Determine query intent
        info.query_intent = self._detect_intent(lg)

        return info

    @staticmethod
    def _find_prop_owner(
        prop_id: str,
        lg: LineageGraph,
        variable_bindings: dict[str, str],
    ) -> str | None:
        """Find the variable that owns a property reference."""
        for edge in lg.edges:
            if edge.source_id == prop_id:
                target = lg.nodes.get(edge.target_id)
                if target and hasattr(target, "name"):
                    name = target.name
                    if name in variable_bindings:
                        return name
            if edge.target_id == prop_id:
                source = lg.nodes.get(edge.source_id)
                if source and hasattr(source, "name"):
                    name = source.name
                    if name in variable_bindings:
                        return name
        return None

    @staticmethod
    def _extract_patterns(
        lg: LineageGraph,
        info: CypherQueryInfo,
    ) -> list[PatternInfo]:
        """Extract relationship patterns from bindings."""
        patterns: list[PatternInfo] = []
        bindings_list = list(lg.bindings)
        binding_nodes = [lg.nodes[b] for b in bindings_list]

        i = 0
        while i < len(binding_nodes):
            b = binding_nodes[i]
            if b.kind == BindingKind.NODE and i + 2 < len(binding_nodes):
                edge = binding_nodes[i + 1]
                target = binding_nodes[i + 2]
                if edge.kind == BindingKind.EDGE and target.kind == BindingKind.NODE:
                    patterns.append(
                        PatternInfo(
                            source_label=(
                                str(b.label_expression) if b.label_expression else None
                            ),
                            relationship_type=(
                                str(edge.label_expression)
                                if edge.label_expression
                                else None
                            ),
                            target_label=(
                                str(target.label_expression)
                                if target.label_expression
                                else None
                            ),
                        )
                    )
                    i += 3
                    continue
            i += 1
        return patterns

    @staticmethod
    def _detect_intent(lg: LineageGraph) -> str:
        """Detect whether the query is read, write, or read_write."""
        has_mutation = len(list(lg.mutations)) > 0
        has_output = len(list(lg.outputs)) > 0
        if has_mutation and has_output:
            return "read_write"
        if has_mutation:
            return "write"
        return "read"


# --- Module-level default parser ---

_DEFAULT_PARSER: CypherParserStrategy = GraphglotParser()


def parse_cypher(
    query: str,
    parser: CypherParserStrategy | None = None,
) -> CypherQueryInfo:
    """Parse a Cypher query and extract structural information."""
    if not query or not query.strip():
        raise ValueError("Query string must not be empty")
    p = parser or _DEFAULT_PARSER
    return p.parse(query)


def validate_cypher(
    query: str,
    model: GraphDataModel,
    parser: CypherParserStrategy | None = None,
) -> ValidationResult:
    """Validate a Cypher query string against a GraphDataModel."""
    info = parse_cypher(query, parser)
    result = ValidationResult()
    _check_labels(info, model, result)
    _check_rel_types(info, model, result)
    _check_properties(info, model, result)
    _check_endpoints(info, model, result)
    return result


def _check_labels(
    info: CypherQueryInfo,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for label in info.node_labels:
        if model.get_node_type(label) is None:
            result.add(
                ValidationIssue(
                    code="QUERY_UNKNOWN_NODE_LABEL",
                    severity=Severity.ERROR,
                    entity_type=EntityType.NODE,
                    entity_id=label,
                    message=f"Query references node label '{label}' not in model",
                )
            )


def _check_rel_types(
    info: CypherQueryInfo,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for rel_type in info.relationship_types:
        if model.get_relationship_type(rel_type) is None:
            result.add(
                ValidationIssue(
                    code="QUERY_UNKNOWN_REL_TYPE",
                    severity=Severity.ERROR,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rel_type,
                    message=f"Query references relationship type "
                    f"'{rel_type}' not in model",
                )
            )


def _check_properties(
    info: CypherQueryInfo,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for var_name, prop_names in info.property_accesses.items():
        label = info.variable_bindings.get(var_name)
        if label is None:
            continue

        node_type = model.get_node_type(label)
        rel_type = model.get_relationship_type(label)
        entity_cls = node_type or rel_type
        if entity_cls is None:
            continue

        allowed = entity_cls.get_all_property_names()
        for prop in prop_names:
            if prop not in allowed:
                result.add(
                    ValidationIssue(
                        code="QUERY_UNKNOWN_PROPERTY",
                        severity=Severity.ERROR,
                        entity_type=(
                            EntityType.NODE if node_type else EntityType.RELATIONSHIP
                        ),
                        entity_id=f"{label}.{prop}",
                        message=f"Query accesses property "
                        f"'{prop}' on {label} "
                        "which is not in the model",
                    )
                )


def _check_endpoints(
    info: CypherQueryInfo,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for pat in info.patterns:
        if not pat.relationship_type or not pat.source_label or not pat.target_label:
            continue

        rel_type = model.get_relationship_type(pat.relationship_type)
        if rel_type is None:
            continue

        expected_src = rel_type.__source_type__.__label__
        expected_tgt = rel_type.__target_type__.__label__

        if pat.source_label != expected_src or pat.target_label != expected_tgt:
            result.add(
                ValidationIssue(
                    code="QUERY_INVALID_ENDPOINT",
                    severity=Severity.ERROR,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=pat.relationship_type,
                    message=f"Query pattern "
                    f"(:{pat.source_label})-[:{pat.relationship_type}]->"
                    f"(:{pat.target_label}) does not match model "
                    f"(:{expected_src})-[:{pat.relationship_type}]->"
                    f"(:{expected_tgt})",
                    context={
                        "expected_source": expected_src,
                        "expected_target": expected_tgt,
                        "actual_source": pat.source_label,
                        "actual_target": pat.target_label,
                    },
                )
            )
