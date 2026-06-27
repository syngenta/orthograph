"""Mermaid diagram renderers for GraphDefinition."""

import base64

from orthograph.dependencies import require
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import CardinalitySpec, ConditionalCardinality


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


def _mermaid_ink_url(graph: str) -> str:
    """Build a mermaid.ink image URL from a Mermaid diagram string."""
    graph_bytes = graph.encode("utf-8")
    base64_string = base64.urlsafe_b64encode(graph_bytes).decode("ascii")
    return f"https://mermaid.ink/img/{base64_string}"


def display_mermaid(obj: "GraphDefinition | str") -> None:
    """Render a Mermaid diagram inline in Jupyter.

    Accepts a raw Mermaid string or a ``GraphDefinition``.
    Requires IPython (Jupyter) and an internet connection.

    Raises
    ------
    ImportError
        If IPython is not available.
    TypeError
        If *obj* is not a supported type.
    """
    require("ipython")
    from IPython.display import Image, display

    if isinstance(obj, str):
        mermaid_text = obj
    elif isinstance(obj, GraphDefinition):
        mermaid_text = model_to_mermaid(obj)
    else:
        raise TypeError(
            f"Cannot render object of type {type(obj).__name__}. "
            "Expected a Mermaid string or GraphDefinition."
        )

    url = _mermaid_ink_url(mermaid_text)
    display(Image(url=url))


def model_to_mermaid(graph_definition: GraphDefinition) -> str:
    """Convert a GraphDefinition to a Mermaid diagram string.

    Shows nodes with properties (type, required/optional, UID marker) and
    relationships with cardinality labels.
    """
    lines = ["graph TD"]

    for nt in graph_definition.node_types:
        specs = nt.get_property_specs()
        prop_parts: list[str] = []
        for name, info in specs.items():
            type_name = info.python_type.__name__
            marker = "" if info.is_required else "?"
            uid_marker = " UID" if name == nt.__uid_field__ else ""
            prop_parts.append(f"{name}: {type_name}{marker}{uid_marker}")
        props = ", ".join(prop_parts)
        lines.append(f'    {nt.__label__}["{nt.__label__}<br>{props}"]')

    for rt in graph_definition.relationship_types:
        src = rt.__source_label__
        tgt = rt.__target_label__
        arrow = "-->" if rt.__directed__ else "---"

        # Build label with relationship name, properties, and cardinality
        label_parts: list[str] = [rt.__label__]

        specs = rt.get_property_specs()
        if specs:
            props = ", ".join(
                f"{name}: {info.python_type.__name__}" for name, info in specs.items()
            )
            label_parts.append(props)

        src_card = _format_cardinality(rt.source_cardinality())
        tgt_card = _format_cardinality(rt.target_cardinality())
        label_parts.append(f"{src_card} : {tgt_card}")

        label_str = " ".join(label_parts)
        lines.append(f"    {src} {arrow}|{label_str}| {tgt}")

    return "\n".join(lines)
