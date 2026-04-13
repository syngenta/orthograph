"""Schema comparison logic for database schema introspection."""

from orthograph.core.errors import ValidationIssue, ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.types import EntityType, Severity
from orthograph.extensions._shared.schema_types import IntrospectedSchema, PropertyInfo


# --- DB type to Python type mapping ---

_DB_TYPE_MAP: dict[str, type] = {
    "String": str,
    "Long": int,
    "Integer": int,
    "Int": int,
    "Double": float,
    "Float": float,
    "Boolean": bool,
    "Bool": bool,
    "StringArray": list,
    "LongArray": list,
    "DoubleArray": list,
    "List": list,
}


def db_type_to_python(db_type: str) -> type | None:
    """Map a database type string to a Python type. Returns None if unknown."""
    return _DB_TYPE_MAP.get(db_type)


# --- Schema comparison ---


def compare_schema(
    introspected: IntrospectedSchema,
    model: GraphDataModel,
) -> ValidationResult:
    """Compare an introspected database schema against a GraphDataModel."""
    result = ValidationResult()
    _check_node_labels(introspected, model, result)
    _check_rel_types(introspected, model, result)
    _check_node_properties(introspected, model, result)
    _check_rel_properties(introspected, model, result)
    return result


def _check_node_labels(
    introspected: IntrospectedSchema,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    model_labels = model.node_labels
    db_labels = introspected.node_labels

    for label in model_labels - db_labels:
        result.add(
            ValidationIssue(
                code="DB_MISSING_NODE_LABEL",
                severity=Severity.ERROR,
                entity_type=EntityType.NODE,
                entity_id=label,
                message=f"Model defines node type '{label}' "
                "but it does not exist in the database",
            )
        )

    for label in db_labels - model_labels:
        result.add(
            ValidationIssue(
                code="DB_UNEXPECTED_NODE_LABEL",
                severity=Severity.WARNING,
                entity_type=EntityType.NODE,
                entity_id=label,
                message=f"Database has node label '{label}' not defined in the model",
            )
        )


def _check_rel_types(
    introspected: IntrospectedSchema,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    model_types = model.relationship_labels
    db_types = introspected.relationship_types

    for rel_type in model_types - db_types:
        result.add(
            ValidationIssue(
                code="DB_MISSING_REL_TYPE",
                severity=Severity.ERROR,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=rel_type,
                message=f"Model defines relationship type "
                f"'{rel_type}' but it does not exist "
                "in the database",
            )
        )

    for rel_type in db_types - model_types:
        result.add(
            ValidationIssue(
                code="DB_UNEXPECTED_REL_TYPE",
                severity=Severity.WARNING,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=rel_type,
                message=f"Database has relationship type "
                f"'{rel_type}' not defined in the model",
            )
        )


def _check_node_properties(
    introspected: IntrospectedSchema,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for nt in model.node_types:
        label = nt.__label__
        db_props = introspected.node_properties.get(label, [])
        _check_entity_properties(label, EntityType.NODE, nt, db_props, result)


def _check_rel_properties(
    introspected: IntrospectedSchema,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for rt in model.relationship_types:
        label = rt.__label__
        db_props = introspected.rel_properties.get(label, [])
        _check_entity_properties(label, EntityType.RELATIONSHIP, rt, db_props, result)


def _check_entity_properties(
    label: str,
    entity_type: EntityType,
    model_type: type,
    db_props: list[PropertyInfo],
    result: ValidationResult,
) -> None:
    """Check properties for a single node or relationship type."""
    model_specs = model_type.get_property_specs()  # type: ignore[attr-defined]
    db_prop_map = {p.name: p for p in db_props}

    for prop_name, type_info in model_specs.items():
        if prop_name not in db_prop_map:
            if type_info.is_required:
                result.add(
                    ValidationIssue(
                        code="DB_MISSING_PROPERTY",
                        severity=Severity.ERROR,
                        entity_type=entity_type,
                        entity_id=f"{label}.{prop_name}",
                        message=f"Required property '{prop_name}' "
                        f"on {label} not found in database",
                    )
                )
            continue

        db_prop = db_prop_map[prop_name]

        # Type check
        expected_type = type_info.python_type
        for db_type_str in db_prop.types:
            py_type = db_type_to_python(db_type_str)
            if py_type is not None and py_type is not expected_type:
                result.add(
                    ValidationIssue(
                        code="DB_PROPERTY_TYPE_MISMATCH",
                        severity=Severity.ERROR,
                        entity_type=entity_type,
                        entity_id=f"{label}.{prop_name}",
                        message=f"Property '{prop_name}' on {label} "
                        f"has DB type '{db_type_str}' "
                        f"(maps to {py_type.__name__}), "
                        f"expected {expected_type.__name__}",
                        context={
                            "db_type": db_type_str,
                            "expected_python_type": expected_type.__name__,
                            "actual_python_type": py_type.__name__,
                        },
                    )
                )

        # Optionality check
        if type_info.is_required and not db_prop.mandatory:
            result.add(
                ValidationIssue(
                    code="DB_PROPERTY_OPTIONAL_MISMATCH",
                    severity=Severity.WARNING,
                    entity_type=entity_type,
                    entity_id=f"{label}.{prop_name}",
                    message=f"Property '{prop_name}' on {label} is "
                    "required in model but not present on all "
                    "database entities",
                    context={
                        "observation_count": db_prop.observation_count,
                        "total_count": db_prop.total_count,
                    },
                )
            )

    # Unexpected properties
    model_prop_names = set(model_specs.keys())
    for db_prop in db_props:
        if db_prop.name not in model_prop_names:
            result.add(
                ValidationIssue(
                    code="DB_UNEXPECTED_PROPERTY",
                    severity=Severity.INFO,
                    entity_type=entity_type,
                    entity_id=f"{label}.{db_prop.name}",
                    message=f"Database property '{db_prop.name}' "
                    f"on {label} not defined in model",
                )
            )
