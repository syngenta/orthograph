"""Convert a GraphDefinition schema to a NetworkX graph."""

from __future__ import annotations

import networkx as nx

from orthograph.graph_definition.graph_definition import GraphDefinition


def schema_to_networkx(graph_definition: GraphDefinition) -> nx.MultiDiGraph[str]:
    """Convert a GraphDefinition to a NetworkX MultiDiGraph (schema visualization).

    Nodes represent node types, edges represent relationship types.
    """
    g: nx.MultiDiGraph[str] = nx.MultiDiGraph()

    for nt in graph_definition.node_types:
        props = {
            name: info.python_type.__name__
            for name, info in nt.get_property_specs().items()
        }
        g.add_node(
            nt.__label__,
            uid_field=nt.__uid_field__,
            properties=props,
            optional=nt.__optional__,
        )

    for rt in graph_definition.relationship_types:
        props = {
            name: info.python_type.__name__
            for name, info in rt.get_property_specs().items()
        }
        g.add_edge(
            rt.__source_label__,
            rt.__target_label__,
            label=rt.__label__,
            directed=rt.__directed__,
            properties=props,
            source_cardinality=str(rt.source_cardinality()),
            target_cardinality=str(rt.target_cardinality()),
        )

    return g
