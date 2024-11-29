import json

import pytest

from orthograph.graph_schema import GraphSchema


@pytest.fixture()
def schema_string():
    json_str = json.dumps(
        {
            "name": "noc",
            "node_specs": {
                "1": {"label": "Molecule", "properties": {}},
                "2": {"label": "ChemicalEquation", "properties": {}},
            },
            "relationship_specs": {
                "1": {
                    "label": "REACTANT",
                    "node_types": ["Molecule", "ChemicalEquation"],
                    "directed": True,
                },
                "2": {
                    "label": "PRODUCT",
                    "node_types": ["ChemicalEquation", "Molecule"],
                    "directed": True,
                },
            },
        }
    )
    return json_str


def test_noc_behavior(schema_string):
    gs = GraphSchema.from_json(json_str=schema_string)
    nle = gs.get_node_label_enum()
    rte = gs.get_relationship_label_enum()
    # nodes labels in the schemas
    assert all([x in [e.value for e in nle] for x in ["Molecule", "ChemicalEquation"]])
    # relationship labels in the schema
    assert all([x in [e.value for e in rte] for x in ["REACTANT", "PRODUCT"]])
    print(f"Nodes in schema: {[e.value for e in nle]}")
    print(f"Relationships in schema: {[e.value for e in rte]}")
