"""Validate a GraphProfile against a GraphDataModel."""

from orthograph.core.errors import ValidationIssue, ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.types import EntityType, Severity
from orthograph.extensions.models import GraphProfile, PropertyProfile


# --- DB type to Python type mapping ---

_DB_TYPE_MAP: dict[str, type] = {
    "String": str,
    "str": str,
    "Long": int,
    "Integer": int,
    "Int": int,
    "int": int,
    "Double": float,
    "Float": float,
    "float": float,
    "Boolean": bool,
    "Bool": bool,
    "bool": bool,
    "StringArray": list,
    "LongArray": list,
    "DoubleArray": list,
    "List": list,
    "list": list,
}


def db_type_to_python(db_type: str) -> type | None:
    """Map a database type string to a Python type."""
    return _DB_TYPE_MAP.get(db_type)


def validate_profile(
    profile: GraphProfile,
    model: GraphDataModel,
) -> ValidationResult:
    """Compare a GraphProfile against a GraphDataModel."""
    result = ValidationResult()
    _check_node_labels(profile, model, result)
    _check_rel_types(profile, model, result)
    _check_node_properties(profile, model, result)
    _check_rel_properties(profile, model, result)
    _check_rel_endpoints(profile, model, result)
    _check_cardinality(profile, model, result)
    return result


def _check_node_labels(
    profile: GraphProfile,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for label in model.node_labels - profile.node_labels:
        result.add(
            ValidationIssue(
                code="MISSING_NODE_LABEL",
                severity=Severity.ERROR,
                entity_type=EntityType.NODE,
                entity_id=label,
                message=(
                    f"Model defines node type '{label}' "
                    "but no instances found in profile"
                ),
            )
        )
    for label in profile.node_labels - model.node_labels:
        result.add(
            ValidationIssue(
                code="UNEXPECTED_NODE_LABEL",
                severity=Severity.WARNING,
                entity_type=EntityType.NODE,
                entity_id=label,
                message=(f"Profile contains node label '{label}' not defined in model"),
            )
        )


def _check_rel_types(
    profile: GraphProfile,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for rt in model.relationship_labels - profile.relationship_types:
        result.add(
            ValidationIssue(
                code="MISSING_REL_TYPE",
                severity=Severity.ERROR,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=rt,
                message=(
                    f"Model defines relationship type '{rt}' "
                    "but no instances found in profile"
                ),
            )
        )
    for rt in profile.relationship_types - model.relationship_labels:
        result.add(
            ValidationIssue(
                code="UNEXPECTED_REL_TYPE",
                severity=Severity.WARNING,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=rt,
                message=(
                    f"Profile contains relationship type '{rt}' not defined in model"
                ),
            )
        )


def _check_node_properties(
    profile: GraphProfile,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for nt in model.node_types:
        label = nt.__label__
        node_profile = profile.node_type_profiles.get(label)
        if node_profile is None:
            continue
        _check_entity_properties(
            label, EntityType.NODE, nt, node_profile.property_profiles, result
        )


def _check_rel_properties(
    profile: GraphProfile,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for rt in model.relationship_types:
        label = rt.__label__
        rel_profile = profile.rel_type_profiles.get(label)
        if rel_profile is None:
            continue
        _check_entity_properties(
            label,
            EntityType.RELATIONSHIP,
            rt,
            rel_profile.property_profiles,
            result,
        )


def _check_entity_properties(
    label: str,
    entity_type: EntityType,
    model_type: type,
    profile_props: dict[str, PropertyProfile],
    result: ValidationResult,
) -> None:
    model_specs = model_type.get_property_specs()  # type: ignore[attr-defined]

    for prop_name, type_info in model_specs.items():
        prop_profile = profile_props.get(prop_name)

        if prop_profile is None:
            if type_info.is_required:
                result.add(
                    ValidationIssue(
                        code="MISSING_PROPERTY",
                        severity=Severity.ERROR,
                        entity_type=entity_type,
                        entity_id=f"{label}.{prop_name}",
                        message=(
                            f"Required property '{prop_name}' "
                            f"on {label} not found in profile"
                        ),
                    )
                )
            continue

        # Type check
        expected_type = type_info.python_type
        for obs_type in prop_profile.observed_types:
            py_type = db_type_to_python(obs_type)
            if py_type is not None and py_type is not expected_type:
                result.add(
                    ValidationIssue(
                        code="PROPERTY_TYPE_MISMATCH",
                        severity=Severity.ERROR,
                        entity_type=entity_type,
                        entity_id=f"{label}.{prop_name}",
                        message=(
                            f"Property '{prop_name}' on {label} "
                            f"has observed type '{obs_type}' "
                            f"(Python: {py_type.__name__}), "
                            f"expected {expected_type.__name__}"
                        ),
                    )
                )

        # Completeness check
        if type_info.is_required and not prop_profile.is_mandatory:
            result.add(
                ValidationIssue(
                    code="PROPERTY_INCOMPLETE",
                    severity=Severity.WARNING,
                    entity_type=entity_type,
                    entity_id=f"{label}.{prop_name}",
                    message=(
                        f"Required property '{prop_name}' on "
                        f"{label} is only {prop_profile.completeness:.1%} "
                        "complete"
                    ),
                    context={
                        "present_count": prop_profile.present_count,
                        "total_count": prop_profile.total_count,
                        "completeness": prop_profile.completeness,
                    },
                )
            )

    # Unexpected properties
    model_prop_names = set(model_specs.keys())
    for prop_name in profile_props:
        if prop_name not in model_prop_names:
            result.add(
                ValidationIssue(
                    code="UNEXPECTED_PROPERTY",
                    severity=Severity.INFO,
                    entity_type=entity_type,
                    entity_id=f"{label}.{prop_name}",
                    message=(
                        f"Property '{prop_name}' on {label} "
                        "found in profile but not in model"
                    ),
                )
            )


def _check_rel_endpoints(
    profile: GraphProfile,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for rt in model.relationship_types:
        label = rt.__label__
        rel_profile = profile.rel_type_profiles.get(label)
        if rel_profile is None:
            continue

        expected_src = rt.__source_type__.__label__
        expected_tgt = rt.__target_type__.__label__

        for src in rel_profile.source_labels:
            if src != expected_src:
                result.add(
                    ValidationIssue(
                        code="INVALID_ENDPOINT",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=label,
                        message=(
                            f"Relationship '{label}' has source "
                            f"label '{src}', expected '{expected_src}'"
                        ),
                        context={
                            "role": "source",
                            "actual": src,
                            "expected": expected_src,
                        },
                    )
                )

        for tgt in rel_profile.target_labels:
            if tgt != expected_tgt:
                result.add(
                    ValidationIssue(
                        code="INVALID_ENDPOINT",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=label,
                        message=(
                            f"Relationship '{label}' has target "
                            f"label '{tgt}', expected '{expected_tgt}'"
                        ),
                        context={
                            "role": "target",
                            "actual": tgt,
                            "expected": expected_tgt,
                        },
                    )
                )


def _check_cardinality(
    profile: GraphProfile,
    model: GraphDataModel,
    result: ValidationResult,
) -> None:
    for rt in model.relationship_types:
        label = rt.__label__
        rel_profile = profile.rel_type_profiles.get(label)
        if rel_profile is None or rel_profile.cardinality_stats is None:
            continue

        stats = rel_profile.cardinality_stats
        src_card = rt.__source_cardinality__

        if not src_card.contains(stats.min_degree):
            max_str = "N" if src_card.max is None else str(src_card.max)
            result.add(
                ValidationIssue(
                    code="CARDINALITY_VIOLATION",
                    severity=Severity.ERROR,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=label,
                    message=(
                        f"Relationship '{label}' has min degree "
                        f"{stats.min_degree}, expected "
                        f"{src_card.min}..{max_str}"
                    ),
                    context={
                        "observed_min": stats.min_degree,
                        "observed_max": stats.max_degree,
                        "expected_min": src_card.min,
                        "expected_max": src_card.max,
                    },
                )
            )
