import networkx as nx

from orthograph.graph_schema import GraphSchema


def to_networkx(schema: GraphSchema) -> nx.MultiDiGraph:
    """
    Convert a GraphSchema to a NetworkX MultiDiGraph.

    Args:
        schema (GraphSchema): The schema to convert.

    Returns:
        nx.MultiDiGraph: A NetworkX graph representation of the schema.
    """
    g = nx.MultiDiGraph()

    # Add nodes
    for label, node_spec in schema.node_specs.items():
        g.add_node(label, type="node", properties=node_spec.properties)

    # Add edges (relationships)
    for label, rel_spec in schema.relationship_specs.items():
        g.add_edge(
            rel_spec.source_type,
            rel_spec.target_type,
            key=label,
            type="relationship",
            properties=rel_spec.properties,
            directed=rel_spec.directed,
        )

    return g


def to_mermaid(schema: GraphSchema) -> str:
    """
    Convert a GraphSchema to a Mermaid diagram string.

    Args:
        schema (GraphSchema): The schema to convert.

    Returns:
        str: A Mermaid diagram string representing the schema.
    """
    mermaid_lines = ["graph TD"]

    # Add nodes
    for label, node_spec in schema.node_specs.items():
        properties = ", ".join(f"{k}: {v}" for k, v in node_spec.properties.items())
        mermaid_lines.append(f'    {label}["{label}<br>{properties}"]')

    # Add relationships
    for label, rel_spec in schema.relationship_specs.items():
        source, target = rel_spec.node_types
        arrow = "-->" if rel_spec.directed else "---"
        properties = ", ".join(f"{k}: {v}" for k, v in rel_spec.properties.items())
        mermaid_lines.append(f"    {source} {arrow}|{label}<br>{properties}| {target}")

    return "\n".join(mermaid_lines)
