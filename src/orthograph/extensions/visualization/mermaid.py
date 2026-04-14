"""Mermaid diagram generation from GraphDataModel."""

from orthograph.core.graph_data_model import GraphDataModel


def to_mermaid(model: GraphDataModel) -> str:
    """Convert a GraphDataModel to a Mermaid diagram string."""
    lines = ["graph TD"]

    for nt in model.node_types:
        specs = nt.get_property_specs()
        props = ", ".join(
            f"{name}: {info.python_type.__name__}" for name, info in specs.items()
        )
        lines.append(f'    {nt.__label__}["{nt.__label__}<br>{props}"]')

    for rt in model.relationship_types:
        src = rt.__source_type__.__label__
        tgt = rt.__target_type__.__label__
        arrow = "-->" if rt.__directed__ else "---"
        specs = rt.get_property_specs()
        props = ", ".join(
            f"{name}: {info.python_type.__name__}" for name, info in specs.items()
        )
        label_str = rt.__label__
        if props:
            label_str += f"<br>{props}"
        lines.append(f"    {src} {arrow}|{label_str}| {tgt}")

    return "\n".join(lines)
