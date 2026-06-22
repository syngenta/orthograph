"""Plain text table renderers for GraphDefinition, GraphProfile, ValidationResult."""

from orthograph.diagnostics.result import ValidationIssue, ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import CardinalitySpec, ConditionalCardinality
from orthograph.graph_profile.models import BoundedDistribution, GraphProfile


def _format_conditional(card: ConditionalCardinality) -> str:
    """Format a ConditionalCardinality as a compact summary string.

    Example: `{(source,target):1..2; (split,nothing):0..0; default:0..*}`.
    """
    rule_parts: list[str] = []
    for rule in card.rules:
        source_vals = dict(rule.source.conditions) if rule.source.conditions else "*"
        target_vals = dict(rule.target.conditions) if rule.target.conditions else "*"
        rule_parts.append(f"({source_vals},{target_vals}):{rule.spec.notation}")

    all_parts = rule_parts + [f"default:{card.default.notation}"]
    return "{" + "; ".join(all_parts) + "}"


def _format_cardinality(spec: CardinalitySpec | ConditionalCardinality) -> str:
    """Format a CardinalitySpec or ConditionalCardinality as a compact string.

    For CardinalitySpec: '0..1', '1..*', etc.
    For ConditionalCardinality: compact summary with rules and default.
    """
    if isinstance(spec, ConditionalCardinality):
        return _format_conditional(spec)
    return spec.notation


def _render_node_types(graph_definition: GraphDefinition) -> list[str]:
    """Render the node-types section for model_to_text."""
    lines: list[str] = ["Node Types", "-" * 60]
    for nt in graph_definition.node_types:
        optional_tag = " (optional)" if nt.__optional__ else ""
        lines.append(f"  {nt.__label__}{optional_tag}")
        for name, info in nt.get_property_specs().items():
            type_name = info.python_type.__name__
            req = "required" if info.is_required else "optional"
            uid = " [UID]" if name == nt.__uid_field__ else ""
            lines.append(f"    {name}: {type_name} ({req}){uid}")
        lines.append("")
    return lines


def _render_relationship_types(graph_definition: GraphDefinition) -> list[str]:
    """Render the relationship-types section for model_to_text."""
    lines: list[str] = ["Relationship Types", "-" * 60]
    for rt in graph_definition.relationship_types:
        src = rt.__source_label__
        tgt = rt.__target_label__
        direction = "-->" if rt.__directed__ else "---"
        src_card = _format_cardinality(rt.source_cardinality())
        tgt_card = _format_cardinality(rt.target_cardinality())
        lines.append(f"  {rt.__label__}: {src} {direction} {tgt}")
        lines.append(f"    cardinality: [{src_card}] source, [{tgt_card}] target")
        for name, info in rt.get_property_specs().items():
            type_name = info.python_type.__name__
            req = "required" if info.is_required else "optional"
            lines.append(f"    {name}: {type_name} ({req})")
        lines.append("")
    return lines


def model_to_text(graph_definition: GraphDefinition) -> str:
    """Render a GraphDefinition as a plain text table.

    Shows node types with their properties (name, type, required/optional,
    UID marker), and relationship types with endpoints and cardinality.
    """
    header: list[str] = [f"Model: {graph_definition.name}"]
    if graph_definition.version:
        header.append(f"Version: {graph_definition.version}")
    header.append("")

    lines = (
        header
        + _render_node_types(graph_definition)
        + _render_relationship_types(graph_definition)
    )
    return "\n".join(lines)


def _format_value_distribution(dist: BoundedDistribution) -> str:
    """Render a BoundedDistribution compactly.

    Shows top-N histogram entries; appends a ``+N more`` truncation marker when
    ``sample_complete=False``.  Returns an empty string when ``histogram`` is
    ``None``.
    """
    if dist.histogram is None:
        return ""
    pairs = ", ".join(f"{k}:{v}" for k, v in dist.histogram.items())
    suffix = f", +{dist.other_count} more" if not dist.sample_complete else ""
    return f"[{pairs}{suffix}]"


def profile_to_text(profile: GraphProfile) -> str:
    """Render a GraphProfile as a plain text table.

    Shows node types with instance counts and property completeness,
    and relationship types with counts, endpoints, and cardinality stats.
    """
    lines: list[str] = [
        f"Profile: {profile.source}",
        f"Timestamp: {profile.timestamp}",
        "",
        "Node Types",
        "-" * 60,
    ]

    # --- Node types ---

    for label, ntp in profile.node_type_profiles.items():
        lines.append(f"  {label} ({ntp.count} instances)")
        for prop_name, pp in ntp.property_profiles.items():
            pct = f"{pp.completeness:.0%}"
            types_str = ", ".join(pp.observed_types) if pp.observed_types else "n/a"
            constraint_tag = (
                " [constrained]"
                if pp.constraint_required is True
                else " [unconstrained]"
                if pp.constraint_required is False
                else ""
            )
            dist_str = (
                f" values={_format_value_distribution(pp.value_distribution)}"
                if pp.value_distribution is not None
                and pp.value_distribution.histogram is not None
                else ""
            )
            lines.append(
                f"    {prop_name}: {pct} complete "
                f"({pp.present_count}/{pp.total_count})"
                f"{constraint_tag} types=[{types_str}]{dist_str}"
            )
        lines.append("")

    # --- Relationship types ---
    lines.append("Relationship Types")
    lines.append("-" * 60)

    for rel_type, rtp in profile.rel_type_profiles.items():
        lines.append(f"  {rel_type} ({rtp.count} instances)")
        lines.append(f"    sources: {sorted(rtp.source_labels)}")
        lines.append(f"    targets: {sorted(rtp.target_labels)}")
        if rtp.cardinality_stats:
            cs = rtp.cardinality_stats
            mean_str = f"{cs.mean:.1f}" if cs.mean is not None else "n/a"
            lines.append(
                f"    cardinality: min={cs.min}, max={cs.max}, "
                f"avg={mean_str}, sample_size={cs.count}"
            )
        for prop_name, pp in rtp.property_profiles.items():
            pct = f"{pp.completeness:.0%}"
            types_str = ", ".join(pp.observed_types) if pp.observed_types else "n/a"
            constraint_tag = (
                " [constrained]"
                if pp.constraint_required is True
                else " [unconstrained]"
                if pp.constraint_required is False
                else ""
            )
            dist_str = (
                f" values={_format_value_distribution(pp.value_distribution)}"
                if pp.value_distribution is not None
                and pp.value_distribution.histogram is not None
                else ""
            )
            lines.append(
                f"    {prop_name}: {pct} complete "
                f"({pp.present_count}/{pp.total_count})"
                f"{constraint_tag} types=[{types_str}]{dist_str}"
            )
        lines.append("")

    return "\n".join(lines)


def result_to_text(result: ValidationResult) -> str:
    """Render a ValidationResult as a plain text summary.

    Groups issues by entity, with severity-coded prefixes:
    [ERROR], [WARNING], [INFO].
    """
    lines: list[str] = []

    status = "PASS" if result.is_valid else "FAIL"
    lines.append(f"Validation: {status}")
    lines.append(
        f"  Errors: {len(result.errors)}, "
        f"Warnings: {len(result.warnings)}, "
        f"Total issues: {len(result.issues)}"
    )
    lines.append("")

    if not result.issues:
        lines.append("No issues found.")
        return "\n".join(lines)

    # Group issues by entity_id
    grouped: dict[str, list[ValidationIssue]] = {}
    for issue in result.issues:
        key = f"{issue.entity_type.value}:{issue.entity_id}"
        grouped.setdefault(key, []).append(issue)

    lines.append("Issues")
    lines.append("-" * 60)

    for entity_key, issues in grouped.items():
        lines.append(f"  {entity_key}")
        for issue in issues:
            sev = issue.severity.value.upper()
            lines.append(f"    [{sev}] {issue.code}: {issue.message}")
            if issue.context:
                lines.append(f"      context: {issue.context}")
        lines.append("")

    return "\n".join(lines)
