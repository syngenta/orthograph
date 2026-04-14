"""Convert a GraphDataModel schema to a NetworkX graph."""

import networkx as nx

from orthograph.core.graph_data_model import GraphDataModel


def schema_to_networkx(model: GraphDataModel) -> nx.MultiDiGraph:  # type: ignore[type-arg]
    """Convert a GraphDataModel to a NetworkX MultiDiGraph (schema visualization).

    Nodes represent node types, edges represent relationship types.
    """
    g: nx.MultiDiGraph = nx.MultiDiGraph()  # type: ignore[type-arg]

    for nt in model.node_types:
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

    for rt in model.relationship_types:
        props = {
            name: info.python_type.__name__
            for name, info in rt.get_property_specs().items()
        }
        g.add_edge(
            rt.__source_type__.__label__,
            rt.__target_type__.__label__,
            label=rt.__label__,
            directed=rt.__directed__,
            properties=props,
            source_cardinality=str(rt.__source_cardinality__),
            target_cardinality=str(rt.__target_cardinality__),
        )

    return g
