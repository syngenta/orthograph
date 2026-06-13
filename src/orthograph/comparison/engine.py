"""Compare a :class:`GraphProfile` against a :class:`GraphDefinition`.

The engine walks each address in the shared declared/observed address space,
builds a :class:`~orthograph.comparison.rules.RuleContext`, calls every
applicable rule, and collects :class:`~orthograph.diagnostics.result.ValidationIssue` s.
"""

from collections.abc import Sequence
from typing import Protocol

from orthograph.comparison.rules import Rule, RuleContext, standard_rules
from orthograph.diagnostics.classification import EntityType
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.property_spec import TypeInfo
from orthograph.graph_profile.models import GraphProfile, PropertyProfile


class _HasPropertySpecs(Protocol):
    """Protocol for types that expose ``get_property_specs()``."""

    @classmethod
    def get_property_specs(cls) -> dict[str, TypeInfo]: ...


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


def compare(
    profile: GraphProfile,
    graph_definition: GraphDefinition,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Compare a :class:`GraphProfile` against a :class:`GraphDefinition`.

    Parameters
    ----------
    rules:
        Rule set to apply.  Defaults to
        :func:`~orthograph.comparison.rules.standard_rules`.
        Pass a custom list to extend or replace the standard behaviour.
    """
    active_rules: Sequence[Rule] = rules if rules is not None else standard_rules()
    result = ValidationResult()

    def _apply(ctx: RuleContext) -> None:
        for rule in active_rules:
            for issue in rule(ctx):
                result.add(issue)

    # ------------------------------------------------------------------
    # 1. Node-label addresses
    # ------------------------------------------------------------------
    declared_labels = graph_definition.node_labels
    observed_labels = profile.node_labels

    for label in declared_labels - observed_labels:
        _apply(
            RuleContext(
                graph_definition=graph_definition,
                profile=profile,
                address=label,
                declared=label,
                observed=None,
            )
        )
    for label in observed_labels - declared_labels:
        _apply(
            RuleContext(
                graph_definition=graph_definition,
                profile=profile,
                address=label,
                declared=None,
                observed=profile.node_type_profiles[label],
            )
        )

    # ------------------------------------------------------------------
    # 2. Relationship-type addresses
    # ------------------------------------------------------------------
    declared_rel_types = graph_definition.relationship_labels
    observed_rel_types = profile.relationship_types

    for rt in declared_rel_types - observed_rel_types:
        _apply(
            RuleContext(
                graph_definition=graph_definition,
                profile=profile,
                address=rt,
                declared=rt,
                observed=None,
            )
        )
    for rt in observed_rel_types - declared_rel_types:
        _apply(
            RuleContext(
                graph_definition=graph_definition,
                profile=profile,
                address=rt,
                declared=None,
                observed=profile.rel_type_profiles[rt],
            )
        )

    # ------------------------------------------------------------------
    # 3. Property addresses — node types
    # ------------------------------------------------------------------
    for node_type in graph_definition.node_types:
        node_label = node_type.__label__
        node_profile = profile.node_type_profiles.get(node_label)
        if node_profile is None:
            continue
        _walk_properties(
            graph_definition=graph_definition,
            profile=profile,
            label=node_label,
            entity_type=EntityType.NODE,
            model_type=node_type,
            profile_props=node_profile.property_profiles,
            active_rules=active_rules,
            result=result,
        )

    # ------------------------------------------------------------------
    # 4. Property addresses — relationship types
    # ------------------------------------------------------------------
    for rel_type in graph_definition.relationship_types:
        rel_label = rel_type.__label__
        rel_profile = profile.rel_type_profiles.get(rel_label)
        if rel_profile is None:
            continue
        _walk_properties(
            graph_definition=graph_definition,
            profile=profile,
            label=rel_label,
            entity_type=EntityType.RELATIONSHIP,
            model_type=rel_type,
            profile_props=rel_profile.property_profiles,
            active_rules=active_rules,
            result=result,
        )

    # ------------------------------------------------------------------
    # 5. Endpoint + cardinality addresses — rel types in both
    # ------------------------------------------------------------------
    for rel_type in graph_definition.relationship_types:
        rel_label = rel_type.__label__
        rel_profile = profile.rel_type_profiles.get(rel_label)
        if rel_profile is None:
            continue
        _apply(
            RuleContext(
                graph_definition=graph_definition,
                profile=profile,
                address=rel_label,
                declared=rel_type,
                observed=rel_profile,
            )
        )

    return result


def _walk_properties(
    graph_definition: GraphDefinition,
    profile: GraphProfile,
    label: str,
    entity_type: EntityType,
    model_type: type[_HasPropertySpecs],
    profile_props: dict[str, PropertyProfile],
    active_rules: Sequence[Rule],
    result: ValidationResult,
) -> None:
    """Walk all property addresses for one entity type and apply rules."""
    model_specs = model_type.get_property_specs()
    all_prop_names = set(model_specs) | set(profile_props)

    for prop_name in all_prop_names:
        type_info = model_specs.get(prop_name)
        prop_profile = profile_props.get(prop_name)
        address = f"{label}.{prop_name}"
        extra = {
            "label": label,
            "prop_name": prop_name,
            "entity_type": entity_type,
        }
        ctx = RuleContext(
            graph_definition=graph_definition,
            profile=profile,
            address=address,
            declared=type_info,
            observed=prop_profile,
            extra=extra,
        )
        for rule in active_rules:
            for issue in rule(ctx):
                result.add(issue)
