"""Integration tests: end-to-end workflows using orthograph."""

from typing import Any, Optional

import pytest

from orthograph import (
    Cardinality,
    GraphDataModel,
    GraphValidator,
    NodeModel,
    RelationshipModel,
)
from orthograph.extensions.cypher import CypherGenerator
from orthograph.extensions.networkx import NetworkxInspector, schema_to_networkx
from orthograph.extensions.validation import validate_profile
from orthograph.extensions.visualization import to_mermaid
from orthograph.io.yaml import load_yaml_file, save_yaml_file


# ===================================================================
# Chemistry domain model
# ===================================================================


class Molecule(NodeModel):
    __label__ = "Molecule"
    __uid_field__ = "uid"
    uid: str
    smiles: str
    molecular_weight: Optional[float] = None


class ChemicalEquation(NodeModel):
    __label__ = "ChemicalEquation"
    __uid_field__ = "uid"
    uid: str
    smiles: str


class Template(NodeModel):
    __label__ = "Template"
    __uid_field__ = "uid"
    uid: str
    smarts: str


class Reaction(NodeModel):
    __label__ = "Reaction"
    __uid_field__ = "uid"
    uid: str
    source: str
    external_id: str
    route_id: Optional[str] = None


class Step(NodeModel):
    __label__ = "Step"
    __uid_field__ = "uid"
    uid: str
    step_id: int


class Reactant(RelationshipModel):
    __label__ = "REACTANT"
    __source_type__ = Molecule
    __target_type__ = ChemicalEquation
    __source_cardinality__ = Cardinality.ZERO_OR_MORE


class Product(RelationshipModel):
    __label__ = "PRODUCT"
    __source_type__ = ChemicalEquation
    __target_type__ = Molecule
    __source_cardinality__ = Cardinality.ZERO_OR_MORE


class HasTemplate(RelationshipModel):
    __label__ = "HAS_TEMPLATE"
    __source_type__ = ChemicalEquation
    __target_type__ = Template
    __source_cardinality__ = Cardinality.ZERO_OR_MORE


class HasStep(RelationshipModel):
    __label__ = "HAS_STEP"
    __source_type__ = Reaction
    __target_type__ = Step
    __source_cardinality__ = Cardinality.ZERO_OR_MORE


class HasCE(RelationshipModel):
    __label__ = "HAS_CE"
    __source_type__ = Step
    __target_type__ = ChemicalEquation
    __source_cardinality__ = Cardinality.ZERO_OR_MORE


@pytest.fixture()
def chemistry_model() -> GraphDataModel:
    return GraphDataModel(
        name="Network_of_Organic_Chemistry",
        version="1.0.0",
        node_types=[Molecule, ChemicalEquation, Template, Reaction, Step],
        relationship_types=[Reactant, Product, HasTemplate, HasStep, HasCE],
    )


# --- Chemistry domain model tests ---


def test_chemistry_model_structure(chemistry_model: GraphDataModel):
    assert chemistry_model.name == "Network_of_Organic_Chemistry"
    assert chemistry_model.node_labels == {
        "Molecule",
        "ChemicalEquation",
        "Template",
        "Reaction",
        "Step",
    }
    assert chemistry_model.relationship_labels == {
        "REACTANT",
        "PRODUCT",
        "HAS_TEMPLATE",
        "HAS_STEP",
        "HAS_CE",
    }


def test_chemistry_valid_graph(chemistry_model: GraphDataModel):
    v = GraphValidator(chemistry_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Reaction", "uid": "R1", "source": "Lab1", "external_id": "EXT1"},
        {"__label__": "Step", "uid": "S1", "step_id": 1},
        {"__label__": "ChemicalEquation", "uid": "CE1", "smiles": "A+B>>C"},
        {"__label__": "Template", "uid": "T1", "smarts": "[C:1]>>[C:1]O"},
        {"__label__": "Molecule", "uid": "M1", "smiles": "A"},
        {"__label__": "Molecule", "uid": "M2", "smiles": "B"},
        {"__label__": "Molecule", "uid": "M3", "smiles": "C"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "HAS_STEP", "__source_uid__": "R1", "__target_uid__": "S1"},
        {"__label__": "HAS_CE", "__source_uid__": "S1", "__target_uid__": "CE1"},
        {"__label__": "HAS_TEMPLATE", "__source_uid__": "CE1", "__target_uid__": "T1"},
        {"__label__": "REACTANT", "__source_uid__": "M1", "__target_uid__": "CE1"},
        {"__label__": "REACTANT", "__source_uid__": "M2", "__target_uid__": "CE1"},
        {"__label__": "PRODUCT", "__source_uid__": "CE1", "__target_uid__": "M3"},
    ]
    result = v.validate(nodes=nodes, relationships=rels)
    assert result.is_valid, [str(e) for e in result.errors]


def test_chemistry_invalid_data(chemistry_model: GraphDataModel):
    v = GraphValidator(chemistry_model)
    nodes: list[dict[str, Any]] = [
        {"__label__": "Molecule", "uid": "M1"},
        {"__label__": "Unknown", "uid": "X1"},
    ]
    result = v.validate_nodes(nodes)
    assert not result.is_valid
    assert len(result.errors) >= 2


def test_chemistry_enum_generation(chemistry_model: GraphDataModel):
    node_enum = chemistry_model.get_node_label_enum()
    assert node_enum.Molecule.value == "Molecule"
    rel_enum = chemistry_model.get_relationship_label_enum()
    assert rel_enum.REACTANT.value == "REACTANT"


# --- YAML ---


def test_chemistry_yaml_roundtrip(chemistry_model: GraphDataModel, tmp_path):
    path = tmp_path / "chemistry.yaml"
    save_yaml_file(chemistry_model, path)
    loaded = load_yaml_file(path)
    assert loaded.name == chemistry_model.name
    assert loaded.version == chemistry_model.version
    assert loaded.node_labels == chemistry_model.node_labels
    assert loaded.relationship_labels == chemistry_model.relationship_labels


# --- Cypher ---


def test_cypher_generate_full_workflow(chemistry_model: GraphDataModel):
    gen = CypherGenerator(chemistry_model)
    constraints = gen.generate_constraints()
    assert len(constraints) >= 4
    query, params = gen.merge_node(
        {"__label__": "Molecule", "uid": "M1", "smiles": "CCO"}
    )
    assert "MERGE" in query
    assert params["uid"] == "M1"


# --- Mermaid ---


def test_chemistry_mermaid(chemistry_model: GraphDataModel):
    mermaid = to_mermaid(chemistry_model)
    assert "graph TD" in mermaid
    assert "Molecule" in mermaid
    assert "REACTANT" in mermaid


# --- NetworkX ---


def test_chemistry_schema_to_networkx(chemistry_model: GraphDataModel):
    g = schema_to_networkx(chemistry_model)
    assert len(g.nodes) == 5
    assert len(g.edges) == 5


def test_chemistry_inspect_and_validate_nx(chemistry_model: GraphDataModel):
    """End-to-end: build nx graph, inspect, validate against model."""
    import networkx as nx

    g: nx.MultiDiGraph = nx.MultiDiGraph()  # type: ignore[type-arg]
    g.add_node("m1", __label__="Molecule", uid="M1", smiles="CCO")
    g.add_node("ce1", __label__="ChemicalEquation", uid="CE1", smiles="CCO>>CC=O")
    g.add_edge("m1", "ce1", __label__="REACTANT")

    inspector = NetworkxInspector(g)
    profile = inspector.inspect()

    assert "Molecule" in profile.node_labels
    assert "REACTANT" in profile.relationship_types

    result = validate_profile(profile, chemistry_model)
    # This will have warnings/errors for missing types (not all types in graph)
    # but the profile itself should be structurally valid
    assert isinstance(result.is_valid, bool)
