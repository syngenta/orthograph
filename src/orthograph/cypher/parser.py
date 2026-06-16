"""Cypher query parsing and validation against a GraphDefinition.

Uses a strategy pattern for the parser backend. Default: graphglot.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from graphglot.dialect import Dialect
from graphglot.lineage import LineageAnalyzer
from graphglot.lineage.models import BindingKind, LineageGraph

from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue, ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition


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
        self._extract_bindings(lg, info)
        self._extract_property_accesses(lg, info)
        info.patterns = self._extract_patterns(lg, info)
        info.query_intent = self._detect_intent(lg)
        return info

    def _extract_bindings(self, lg: LineageGraph, info: CypherQueryInfo) -> None:
        """Populate ``info.node_labels``, ``info.relationship_types``, and
        ``info.variable_bindings`` from the lineage graph."""
        for binding_id in lg.bindings:
            binding = lg.nodes[binding_id]
            label_expr = binding.label_expression
            label_str = str(label_expr) if label_expr else None

            if binding.kind == BindingKind.NODE:
                target_set = info.node_labels
            elif binding.kind == BindingKind.EDGE:
                target_set = info.relationship_types
            else:
                continue

            if label_str:
                target_set.add(label_str)
                if binding.name:
                    info.variable_bindings[binding.name] = label_str

    def _extract_property_accesses(
        self, lg: LineageGraph, info: CypherQueryInfo
    ) -> None:
        """Populate ``info.property_accesses`` from property references."""
        for prop_id in lg.property_refs:
            prop_node = lg.nodes[prop_id]
            prop_name = prop_node.property_name
            owner_var = self._find_prop_owner(prop_id, lg, info.variable_bindings)
            if owner_var:
                info.property_accesses.setdefault(owner_var, set()).add(prop_name)

    @staticmethod
    def _find_prop_owner(
        prop_id: str,
        lg: LineageGraph,
        variable_bindings: dict[str, str],
    ) -> str | None:
        """Find the variable that owns a property reference.

        For each edge that touches ``prop_id``, the adjacent node is the
        candidate owner. The first candidate whose name is in
        ``variable_bindings`` is returned.
        """
        for edge in lg.edges:
            if edge.source_id == prop_id:
                candidate_id = edge.target_id
            elif edge.target_id == prop_id:
                candidate_id = edge.source_id
            else:
                continue
            node = lg.nodes.get(candidate_id)
            if node and hasattr(node, "name") and node.name in variable_bindings:
                return node.name
        return None

    @staticmethod
    def _extract_patterns(
        lg: LineageGraph,
        info: CypherQueryInfo,
    ) -> list[PatternInfo]:
        """Extract non-overlapping (node, edge, node) triples from bindings.

        Advances by 3 when a NODE-EDGE-NODE triple is matched so patterns do
        not overlap; advances by 1 otherwise.
        """
        binding_nodes = [lg.nodes[b] for b in lg.bindings]
        patterns: list[PatternInfo] = []
        i = 0
        while i < len(binding_nodes) - 2:
            a, b, c = binding_nodes[i], binding_nodes[i + 1], binding_nodes[i + 2]
            if (
                a.kind == BindingKind.NODE
                and b.kind == BindingKind.EDGE
                and c.kind == BindingKind.NODE
            ):
                patterns.append(
                    PatternInfo(
                        source_label=str(a.label_expression)
                        if a.label_expression
                        else None,
                        relationship_type=str(b.label_expression)
                        if b.label_expression
                        else None,
                        target_label=str(c.label_expression)
                        if c.label_expression
                        else None,
                    )
                )
                i += 3
            else:
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
    graph_definition: GraphDefinition,
    parser: CypherParserStrategy | None = None,
) -> ValidationResult:
    """Validate a Cypher query string against a GraphDefinition.

    Always returns a :class:`ValidationResult`.  A parse failure is returned
    as a ``QUERY_PARSE_ERROR`` issue (severity ERROR) rather than raised.
    """
    try:
        info = parse_cypher(query, parser)
    except Exception as exc:
        result = ValidationResult()
        result.add(
            ValidationIssue(
                code="QUERY_PARSE_ERROR",
                severity=Severity.ERROR,
                entity_type=EntityType.QUERY,
                entity_id=query,
                message=f"Query could not be parsed: {exc}",
            )
        )
        return result
    result = ValidationResult()
    _check_labels(info, graph_definition, result)
    _check_rel_types(info, graph_definition, result)
    _check_properties(info, graph_definition, result)
    _check_endpoints(info, graph_definition, result)
    return result


def _check_labels(
    info: CypherQueryInfo,
    graph_definition: GraphDefinition,
    result: ValidationResult,
) -> None:
    for label in info.node_labels:
        if graph_definition.get_node_type(label) is None:
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
    graph_definition: GraphDefinition,
    result: ValidationResult,
) -> None:
    for rel_type in info.relationship_types:
        if graph_definition.get_relationship_type(rel_type) is None:
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
    graph_definition: GraphDefinition,
    result: ValidationResult,
) -> None:
    for var_name, prop_names in info.property_accesses.items():
        label = info.variable_bindings.get(var_name)
        if label is None:
            continue

        node_type = graph_definition.get_node_type(label)
        rel_type = graph_definition.get_relationship_type(label)
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


def _pattern_endpoint_issue(
    pat: PatternInfo,
    graph_definition: GraphDefinition,
) -> ValidationIssue | None:
    """Return a QUERY_INVALID_ENDPOINT issue if ``pat``
    violates the model, else None."""
    if not pat.relationship_type or not pat.source_label or not pat.target_label:
        return None

    rel_type = graph_definition.get_relationship_type(pat.relationship_type)
    if rel_type is None:
        return None

    expected_src = rel_type.__source_label__
    expected_tgt = rel_type.__target_label__
    forward_ok = pat.source_label == expected_src and pat.target_label == expected_tgt
    reverse_ok = (
        not rel_type.__directed__
        and pat.source_label == expected_tgt
        and pat.target_label == expected_src
    )
    if forward_ok or reverse_ok:
        return None

    return ValidationIssue(
        code="QUERY_INVALID_ENDPOINT",
        severity=Severity.ERROR,
        entity_type=EntityType.RELATIONSHIP,
        entity_id=pat.relationship_type,
        message=(
            f"Query pattern (:{pat.source_label})-[:{pat.relationship_type}]->"
            f"(:{pat.target_label}) does not match model "
            f"(:{expected_src})-[:{pat.relationship_type}]->(:{expected_tgt})"
        ),
        context={
            "expected_source": expected_src,
            "expected_target": expected_tgt,
            "actual_source": pat.source_label,
            "actual_target": pat.target_label,
        },
    )


def _check_endpoints(
    info: CypherQueryInfo,
    graph_definition: GraphDefinition,
    result: ValidationResult,
) -> None:
    for pat in info.patterns:
        issue = _pattern_endpoint_issue(pat, graph_definition)
        if issue is not None:
            result.add(issue)
