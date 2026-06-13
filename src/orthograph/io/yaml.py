"""YAML loading and saving for GraphDefinition definitions."""

from pathlib import Path
from typing import Any, Optional

import yaml

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    Cardinality,
    CardinalitySpec,
    NodeModel,
    RelationshipModel,
)


# Map YAML type strings to Python types
_TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
}


def load_yaml_string(content: str) -> GraphDefinition:
    """Load a GraphDefinition from a YAML string."""
    data = yaml.safe_load(content)
    return _build_model(data)


def load_yaml_file(path: Path) -> GraphDefinition:
    """Load a GraphDefinition from a YAML file."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    content = path.read_text(encoding="utf-8")
    return load_yaml_string(content)


def save_yaml_file(graph_definition: GraphDefinition, path: Path) -> None:
    """Save a GraphDefinition to a YAML file."""
    data = _serialize_model(graph_definition)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _build_model(data: dict[str, Any]) -> GraphDefinition:
    """Build a GraphDefinition from parsed YAML data."""
    name = data["name"]
    version = data.get("version")

    node_types_data = data.get("node_types", {})
    node_classes: dict[str, type[NodeModel]] = {}
    for label, spec in node_types_data.items():
        node_cls = _build_node_class(label, spec)
        node_classes[label] = node_cls

    rel_types_data = data.get("relationship_types", {})
    rel_classes: list[type[RelationshipModel]] = []
    for label, spec in rel_types_data.items():
        rel_cls = _build_rel_class(label, spec)
        rel_classes.append(rel_cls)

    return GraphDefinition(
        name=name,
        version=version,
        node_types=list(node_classes.values()),
        relationship_types=rel_classes,
    )


def _build_node_class(label: str, spec: dict[str, Any]) -> type[NodeModel]:
    """Dynamically create a NodeModel subclass from YAML spec."""
    uid_field = spec.get("uid_field")
    optional = spec.get("optional", True)
    properties = spec.get("properties", {})

    annotations: dict[str, Any] = {}
    defaults: dict[str, Any] = {}

    for prop_name, prop_spec in properties.items():
        python_type = _resolve_yaml_type(prop_spec)
        required = (
            prop_spec.get("required", True) if isinstance(prop_spec, dict) else True
        )

        if required:
            annotations[prop_name] = python_type
        else:
            annotations[prop_name] = Optional[python_type]
            defaults[prop_name] = None

    namespace: dict[str, Any] = {
        "__annotations__": annotations,
        "__label__": label,
        "__uid_field__": uid_field,
        "__optional__": optional,
        "__module__": __name__,
        "__qualname__": label,
    }
    namespace.update(defaults)

    cls = type(label, (NodeModel,), namespace)
    return cls


def _build_rel_class(
    label: str,
    spec: dict[str, Any],
) -> type[RelationshipModel]:
    """Dynamically create a RelationshipModel subclass from YAML spec."""
    source_label = spec["source"]
    target_label = spec["target"]
    directed = spec.get("directed", True)
    optional = spec.get("optional", True)
    properties = spec.get("properties", {})

    source_cardinality = _parse_cardinality(spec.get("source_cardinality"))
    target_cardinality = _parse_cardinality(spec.get("target_cardinality"))

    annotations: dict[str, Any] = {}
    defaults: dict[str, Any] = {}

    for prop_name, prop_spec in properties.items():
        python_type = _resolve_yaml_type(prop_spec)
        required = (
            prop_spec.get("required", True) if isinstance(prop_spec, dict) else True
        )

        if required:
            annotations[prop_name] = python_type
        else:
            annotations[prop_name] = Optional[python_type]
            defaults[prop_name] = None

    namespace: dict[str, Any] = {
        "__annotations__": annotations,
        "__label__": label,
        "__source_label__": source_label,
        "__target_label__": target_label,
        "__directed__": directed,
        "__optional__": optional,
        "__source_cardinality__": source_cardinality,
        "__target_cardinality__": target_cardinality,
        "__module__": __name__,
        "__qualname__": label,
    }
    namespace.update(defaults)

    cls = type(label, (RelationshipModel,), namespace)
    return cls


def _resolve_yaml_type(prop_spec: Any) -> type:
    """Resolve a YAML property spec to a Python type."""
    if isinstance(prop_spec, dict):
        type_str = prop_spec.get("type", "str")
    elif isinstance(prop_spec, str):
        type_str = prop_spec
    else:
        type_str = "str"
    return _TYPE_MAP.get(type_str, str)


def _parse_cardinality(
    spec: dict[str, Any] | None,
) -> CardinalitySpec:
    """Parse a cardinality spec from YAML."""
    if spec is None:
        return Cardinality.ZERO_OR_MORE
    min_val = spec.get("min", 0)
    max_val = spec.get("max")  # None means unbounded
    return CardinalitySpec(min=min_val, max=max_val)


def _serialize_model(graph_definition: GraphDefinition) -> dict[str, Any]:
    """Serialize a GraphDefinition to a YAML-compatible dict."""
    data: dict[str, Any] = {
        "name": graph_definition.name,
    }
    if graph_definition.version:
        data["version"] = graph_definition.version

    node_types: dict[str, Any] = {}
    for nt in graph_definition.node_types:
        node_spec = _serialize_node_type(nt)
        node_types[nt.__label__] = node_spec
    data["node_types"] = node_types

    rel_types: dict[str, Any] = {}
    for rt in graph_definition.relationship_types:
        rel_spec = _serialize_rel_type(rt)
        rel_types[rt.__label__] = rel_spec
    data["relationship_types"] = rel_types

    return data


def _serialize_node_type(nt: type[NodeModel]) -> dict[str, Any]:
    """Serialize a NodeModel class to a YAML-compatible dict."""
    spec: dict[str, Any] = {}
    if nt.__uid_field__:
        spec["uid_field"] = nt.__uid_field__
    if not nt.__optional__:
        spec["optional"] = False

    props: dict[str, Any] = {}
    prop_specs = nt.get_property_specs()
    for name, info in prop_specs.items():
        type_name = _reverse_type_map(info.python_type)
        props[name] = {
            "type": type_name,
            "required": info.is_required,
        }
    spec["properties"] = props
    return spec


def _serialize_rel_type(
    rt: type[RelationshipModel],
) -> dict[str, Any]:
    """Serialize a RelationshipModel class to a YAML-compatible dict."""
    spec: dict[str, Any] = {
        "source": rt.__source_label__,
        "target": rt.__target_label__,
        "directed": rt.__directed__,
    }
    if not rt.__optional__:
        spec["optional"] = False

    src_card = rt.__source_cardinality__
    tgt_card = rt.__target_cardinality__
    spec["source_cardinality"] = {
        "min": src_card.min,
        "max": src_card.max,
    }
    spec["target_cardinality"] = {
        "min": tgt_card.min,
        "max": tgt_card.max,
    }

    props: dict[str, Any] = {}
    prop_specs = rt.get_property_specs()
    for name, info in prop_specs.items():
        type_name = _reverse_type_map(info.python_type)
        props[name] = {
            "type": type_name,
            "required": info.is_required,
        }
    if props:
        spec["properties"] = props

    return spec


def _reverse_type_map(python_type: type) -> str:
    """Convert a Python type back to a YAML type string."""
    for name, t in _TYPE_MAP.items():
        if t is python_type:
            return name
    return "str"
