"""NetworkX integration: schema visualization and graph validation."""

from typing import Any

import networkx as nx

from orthograph.core.errors import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.validator import GraphValidator


def schema_to_networkx(model: GraphDataModel) -> nx.MultiDiGraph:
    """Convert a GraphDataModel to a NetworkX MultiDiGraph (schema visualization).

    Nodes represent node types, edges represent relationship types.
    """
    g = nx.MultiDiGraph()

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


def validate_networkx_graph(
    graph: nx.MultiDiGraph,
    model: GraphDataModel,
) -> ValidationResult:
    """Validate a NetworkX graph's data against a GraphDataModel.

    Extracts nodes and edges from the nx graph and validates them
    using GraphValidator. Maps nx node IDs to uid_field values for
    referential integrity.
    """
    node_id_to_uid: dict[str, str] = {}

    nodes: list[dict[str, Any]] = []
    for node_id, attrs in graph.nodes(data=True):
        node_data: dict[str, Any] = dict(attrs)
        label = node_data.get("__label__")

        if label:
            nt = model.get_node_type(label)
            if nt and nt.__uid_field__ and nt.__uid_field__ in node_data:
                uid_val = str(node_data[nt.__uid_field__])
                node_id_to_uid[str(node_id)] = uid_val

        nodes.append(node_data)

    relationships: list[dict[str, Any]] = []
    for src, tgt, attrs in graph.edges(data=True):
        rel_data: dict[str, Any] = dict(attrs)
        src_uid = node_id_to_uid.get(str(src), str(src))
        tgt_uid = node_id_to_uid.get(str(tgt), str(tgt))
        rel_data["__source_uid__"] = src_uid
        rel_data["__target_uid__"] = tgt_uid
        relationships.append(rel_data)

    validator = GraphValidator(model)
    return validator.validate(nodes=nodes, relationships=relationships)
