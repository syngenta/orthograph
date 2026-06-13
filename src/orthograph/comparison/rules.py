"""Rule protocol and standard rule set for the comparison engine.

A **Rule** encapsulates one unit of the satisfaction test:

    *given the declared constraint and observed measurement at an address,
    emit zero or more ValidationIssues if the constraint is not satisfied.*

Extend the rule set by passing a custom list to
:func:`~orthograph.comparison.engine.compare`.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import GraphProfile


@dataclass(frozen=True)
class RuleContext:
    """Ingredients bundle delivered to a rule at a single address.

    Attributes
    ----------
    address:
        The shared key for this evaluation — e.g. ``"Person"`` for a
        node-label rule, ``"ACTED_IN"`` for a relationship-type rule,
        or ``"Person.name"`` for a property rule.
    declared:
        The declared object at this address (e.g. a ``NodeModel`` subclass,
        a ``TypeInfo``).  ``None`` when the address exists only on the
        observed side.
    observed:
        The observed object at this address (e.g. a ``NodeTypeProfile``,
        a ``PropertyProfile``).  ``None`` when the address exists only on
        the declared side.
    extra:
        Optional bag for additional context (e.g. ``label``, ``prop_name``,
        ``entity_type`` for property rules).
    """

    graph_definition: GraphDefinition
    profile: GraphProfile
    address: str
    declared: Any = field(default=None)
    observed: Any = field(default=None)
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Rule(Protocol):
    """Structural protocol for a comparison rule.

    ``key`` : str
        Short stable identifier (e.g. ``"node_label.presence"``).

    ``__call__(context: RuleContext) -> Iterable[ValidationIssue]``
        Apply the rule.  Return an empty iterable when satisfied; yield
        issues otherwise.  Must not raise.
    """

    key: str

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]: ...


# ---------------------------------------------------------------------------
# Standard rule set
#
# Address conventions used by the engine:
#   node-label rules   : address = label str
#   rel-type rules     : address = rel_type str
#   property rules     : address = "<label>.<prop_name>" str
#                        extra["label"]       = label str
#                        extra["prop_name"]   = property name str
#                        extra["entity_type"] = EntityType
#   endpoint rules     : address = rel_type str
#   cardinality rules  : address = rel_type str
# ---------------------------------------------------------------------------


@dataclass
class MissingNodeLabelRule:
    """Emits ``MISSING_NODE_LABEL`` (ERROR) when a declared node label is absent
    from the profile."""

    key: str = "node_label.missing"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if "prop_name" in context.extra:
            return  # property address — not a node-label context
        if context.observed is not None:
            return  # label present in profile — not missing
        label: str = context.address
        yield ValidationIssue(
            code="MISSING_NODE_LABEL",
            severity=Severity.ERROR,
            entity_type=EntityType.NODE,
            entity_id=label,
            message=(
                f"Model defines node type '{label}' but no instances found in profile"
            ),
        )


@dataclass
class UnexpectedNodeLabelRule:
    """Emits ``UNEXPECTED_NODE_LABEL`` (WARNING) when a profile node label is
    not in the model."""

    key: str = "node_label.unexpected"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if "prop_name" in context.extra:
            return  # property address — not a node-label context
        if context.declared is not None:
            return  # label is declared — not unexpected
        label: str = context.address
        yield ValidationIssue(
            code="UNEXPECTED_NODE_LABEL",
            severity=Severity.WARNING,
            entity_type=EntityType.NODE,
            entity_id=label,
            message=f"Profile contains node label '{label}' not defined in model",
        )


@dataclass
class MissingRelTypeRule:
    """Emits ``MISSING_REL_TYPE`` (ERROR) when a declared relationship type is
    absent from the profile."""

    key: str = "rel_type.missing"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if "prop_name" in context.extra:
            return  # property address — not a rel-type context
        if context.observed is not None:
            return  # rel type present in profile — not missing
        rt: str = context.address
        yield ValidationIssue(
            code="MISSING_REL_TYPE",
            severity=Severity.ERROR,
            entity_type=EntityType.RELATIONSHIP,
            entity_id=rt,
            message=(
                f"Model defines relationship type '{rt}' "
                "but no instances found in profile"
            ),
        )


@dataclass
class UnexpectedRelTypeRule:
    """Emits ``UNEXPECTED_REL_TYPE`` (WARNING) when a profile relationship type
    is not in the model."""

    key: str = "rel_type.unexpected"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if "prop_name" in context.extra:
            return  # property address — not a rel-type context
        if context.declared is not None:
            return  # rel type is declared — not unexpected
        rt: str = context.address
        yield ValidationIssue(
            code="UNEXPECTED_REL_TYPE",
            severity=Severity.WARNING,
            entity_type=EntityType.RELATIONSHIP,
            entity_id=rt,
            message=f"Profile contains relationship type '{rt}' not defined in model",
        )


@dataclass
class MissingPropertyRule:
    """Emits ``MISSING_PROPERTY`` (ERROR) when a required declared property has
    no ``PropertyProfile``."""

    key: str = "property.missing"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        from orthograph.graph_definition.property_spec import TypeInfo

        type_info: TypeInfo | None = context.declared
        if type_info is None or context.observed is not None:
            return  # no declaration or property was observed — not applicable
        if not isinstance(type_info, TypeInfo):
            return  # context is not a property address
        if not type_info.is_required:
            return  # optional property missing from profile is not an error
        label: str = context.extra["label"]
        prop_name: str = context.extra["prop_name"]
        entity_type: EntityType = context.extra["entity_type"]
        yield ValidationIssue(
            code="MISSING_PROPERTY",
            severity=Severity.ERROR,
            entity_type=entity_type,
            entity_id=f"{label}.{prop_name}",
            message=(
                f"Required property '{prop_name}' on {label} not found in profile"
            ),
        )


@dataclass
class UnexpectedPropertyRule:
    """Emits ``UNEXPECTED_PROPERTY`` (INFO) when an observed property is not in
    the model."""

    key: str = "property.unexpected"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if context.declared is not None:
            return  # property is declared — not unexpected
        if context.observed is None:
            return  # no observation either — nothing to report
        if "prop_name" not in context.extra:
            return  # not a property address
        from orthograph.graph_profile.models import PropertyProfile

        if not isinstance(context.observed, PropertyProfile):
            return  # not a property observation
        label: str = context.extra["label"]
        prop_name: str = context.extra["prop_name"]
        entity_type: EntityType = context.extra["entity_type"]
        yield ValidationIssue(
            code="UNEXPECTED_PROPERTY",
            severity=Severity.INFO,
            entity_type=entity_type,
            entity_id=f"{label}.{prop_name}",
            message=(
                f"Property '{prop_name}' on {label} found in profile but not in model"
            ),
        )


@dataclass
class PropertyIncompleteRule:
    """Emits ``PROPERTY_INCOMPLETE`` (WARNING) when a required property is not
    100% present across observed entities."""

    key: str = "property.incomplete"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        from orthograph.graph_definition.property_spec import TypeInfo
        from orthograph.graph_profile.models import PropertyProfile

        type_info: TypeInfo | None = context.declared
        prop_profile: PropertyProfile | None = context.observed
        if not isinstance(type_info, TypeInfo) or not isinstance(
            prop_profile, PropertyProfile
        ):
            return  # need both sides as proper types
        if not (type_info.is_required and not prop_profile.is_required):
            return
        label: str = context.extra["label"]
        prop_name: str = context.extra["prop_name"]
        entity_type: EntityType = context.extra["entity_type"]
        yield ValidationIssue(
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


@dataclass
class PropertyTypeMismatchRule:
    """Emits ``PROPERTY_TYPE_MISMATCH`` (ERROR) for each observed type that maps
    to a Python type differing from the declared one."""

    key: str = "property.type_mismatch"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        from orthograph.comparison.engine import db_type_to_python
        from orthograph.graph_definition.property_spec import TypeInfo
        from orthograph.graph_profile.models import PropertyProfile

        type_info: TypeInfo | None = context.declared
        prop_profile: PropertyProfile | None = context.observed
        if not isinstance(type_info, TypeInfo) or not isinstance(
            prop_profile, PropertyProfile
        ):
            return  # need both sides as proper types
        label: str = context.extra["label"]
        prop_name: str = context.extra["prop_name"]
        entity_type: EntityType = context.extra["entity_type"]
        expected_type = type_info.python_type
        for obs_type in prop_profile.observed_types:
            py_type = db_type_to_python(obs_type)
            if py_type is not None and py_type is not expected_type:
                yield ValidationIssue(
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


@dataclass
class InvalidEndpointRule:
    """Emits ``INVALID_ENDPOINT`` (ERROR) for each source or target label
    outside the declared set.

    Respects undirected relationships (both label orientations are valid).
    """

    key: str = "rel.endpoint"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        from orthograph.graph_definition.models import RelationshipModel
        from orthograph.graph_profile.models import RelationshipTypeProfile

        rt_class = context.declared
        rel_profile = context.observed
        if not (
            isinstance(rt_class, type)
            and issubclass(rt_class, RelationshipModel)
            and isinstance(rel_profile, RelationshipTypeProfile)
        ):
            return  # need both sides as proper types
        label: str = context.address

        expected_src = rt_class.__source_label__
        expected_tgt = rt_class.__target_label__
        valid_sources: set[str] = {expected_src}
        valid_targets: set[str] = {expected_tgt}
        if not rt_class.__directed__:
            valid_sources.add(expected_tgt)
            valid_targets.add(expected_src)

        for src in rel_profile.source_labels:
            if src not in valid_sources:
                yield ValidationIssue(
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
        for tgt in rel_profile.target_labels:
            if tgt not in valid_targets:
                yield ValidationIssue(
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


@dataclass
class CardinalityViolationRule:
    """Emits ``CARDINALITY_VIOLATION`` (ERROR) when the observed minimum degree
    falls outside the declared ``CardinalitySpec`` bounds."""

    key: str = "rel.cardinality"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        from orthograph.graph_definition.models import RelationshipModel
        from orthograph.graph_profile.models import RelationshipTypeProfile

        rt_class = context.declared
        rel_profile = context.observed
        if not (
            isinstance(rt_class, type)
            and issubclass(rt_class, RelationshipModel)
            and isinstance(rel_profile, RelationshipTypeProfile)
        ):
            return  # need both sides as proper types
        if rel_profile.cardinality_stats is None:
            return

        label: str = context.address
        stats = rel_profile.cardinality_stats
        src_card = rt_class.__source_cardinality__

        if not src_card.contains(stats.min_degree):
            max_str = "N" if src_card.max is None else str(src_card.max)
            yield ValidationIssue(
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


# ---------------------------------------------------------------------------
# Standard rule set factory
# ---------------------------------------------------------------------------


def standard_rules() -> list[Rule]:
    """Return the ordered standard rule list."""
    return [
        MissingNodeLabelRule(),
        UnexpectedNodeLabelRule(),
        MissingRelTypeRule(),
        UnexpectedRelTypeRule(),
        MissingPropertyRule(),
        UnexpectedPropertyRule(),
        PropertyIncompleteRule(),
        PropertyTypeMismatchRule(),
        InvalidEndpointRule(),
        CardinalityViolationRule(),
    ]


# ---------------------------------------------------------------------------
# Extension rule (not in standard_rules)
# ---------------------------------------------------------------------------


@dataclass
class PropertyDistinctCountRule:
    """Emits ``DISTINCT_COUNT_EXCEEDED`` (INFO) when ``PropertyProfile.distinct_count``
    exceeds ``extra["max_distinct_count"]``.

    Not included in :func:`standard_rules` — inject explicitly when needed.
    """

    key: str = "property.distinct_count"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        from orthograph.graph_profile.models import PropertyProfile

        prop_profile = context.observed
        max_distinct: int | None = context.extra.get("max_distinct_count")
        if not isinstance(prop_profile, PropertyProfile):
            return  # not a property address
        if max_distinct is None:
            return  # declared constraint not supplied — skip
        if prop_profile.distinct_count is None:
            return  # observed measurement not populated — skip

        if prop_profile.distinct_count > max_distinct:
            label: str = context.extra["label"]
            prop_name: str = context.extra["prop_name"]
            entity_type: EntityType = context.extra["entity_type"]
            yield ValidationIssue(
                code="DISTINCT_COUNT_EXCEEDED",
                severity=Severity.INFO,
                entity_type=entity_type,
                entity_id=f"{label}.{prop_name}",
                message=(
                    f"Property '{prop_name}' on {label} has "
                    f"{prop_profile.distinct_count} distinct values, "
                    f"expected at most {max_distinct}"
                ),
                context={
                    "observed_distinct_count": prop_profile.distinct_count,
                    "max_distinct_count": max_distinct,
                },
            )
