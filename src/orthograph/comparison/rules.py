"""Rule protocol and standard rule set for the comparison engine.

A **Rule** encapsulates one unit of the satisfaction test:

    *given the left-side object and right-side measurement at an address,
    emit zero or more ValidationIssues if the constraint is not satisfied.*

For :func:`~orthograph.comparison.engine.compare_profile_to_definition` the
convention is **left = declared (definition), right = observed (profile)**,
which is what the satisfaction rules below assume.

Extend the rule set by passing a custom list to
:func:`~orthograph.comparison.engine.compare_profile_to_definition`.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from orthograph.comparison.views import GraphView
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue


@dataclass(frozen=True)
class RuleContext:
    """Ingredients bundle delivered to a rule at a single address.

    Attributes
    ----------
    left_graph:
        The :class:`~orthograph.comparison.views.GraphView` for the left
        operand.  For ``compare_profile_to_definition`` this is the definition
        (declared side).
    right_graph:
        The :class:`~orthograph.comparison.views.GraphView` for the right
        operand.  For ``compare_profile_to_definition`` this is the profile
        (observed side).
    address:
        The shared key for this evaluation — e.g. ``"Person"`` for a
        node-label rule, ``"Person:ACTED_IN:Movie"`` (a ``str(RelTypeKey)``) for
        a relationship-type rule, or ``"Person.name"`` for a property rule.
    left:
        The left-side object at this address (e.g. a ``NodeModel`` subclass,
        a ``TypeInfo``).  ``None`` when the address exists only on the
        right side.
    right:
        The right-side object at this address (e.g. a ``NodeTypeProfile``,
        a ``PropertyProfile``).  ``None`` when the address exists only on
        the left side.
    extra:
        Optional bag for additional context (e.g. ``label``, ``prop_name``,
        ``entity_type`` for property rules).
    """

    left_graph: GraphView
    right_graph: GraphView
    address: str
    left: Any = field(default=None)
    right: Any = field(default=None)
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


def _expected_storage_type(python_type: type) -> type | None:
    """Return the Python *storage* type a declared annotation maps to in a DB.

    For a plain (non-enum) type this is the type itself.  For an
    :class:`enum.Enum` subclass the stored value is the type of the members'
    ``.value`` (``str`` for ``class Genre(str, Enum)`` or a string-valued plain
    enum; ``int`` for an int-valued enum), because a graph database stores the
    enum's underlying scalar — never the Python enum object.  Comparing the
    declared *enum class* against an observed ``"String"`` would otherwise raise
    a spurious ``PROPERTY_TYPE_MISMATCH`` for every enum property; the value-level
    contract is checked by :class:`PropertyEnumValueRule` instead.

    Returns ``None`` when an enum's members carry more than one distinct value
    type (no single storage type), signalling the structural type check to
    stand down.
    """
    import enum

    if isinstance(python_type, type) and issubclass(python_type, enum.Enum):
        value_types = {type(member.value) for member in python_type}
        if len(value_types) == 1:
            return next(iter(value_types))
        return None  # mixed-value-type enum: no single storage type
    return python_type


# ---------------------------------------------------------------------------
# Standard rule set
#
# Address conventions used by the engine:
#   node-label rules   : address = label str
#   rel-type rules     : address = str(RelTypeKey) ("source:LABEL:target")
#   property rules     : address = "<label>.<prop_name>" str (node) or
#                        "<rel_key>.<prop_name>" str (relationship)
#                        extra["label"]       = label str / rel_key str
#                        extra["prop_name"]   = property name str
#                        extra["entity_type"] = EntityType
#   cardinality rules  : address = str(RelTypeKey)
#
# Endpoint mismatch is no longer a dedicated rule: endpoints are
# part of relationship identity, so a different endpoint is a different address
# and surfaces through the presence rules (MISSING_REL_TYPE / UNEXPECTED_REL_TYPE).
#
# Convention for compare_profile_to_definition:
#   left  = declared (definition side)
#   right = observed (profile side)
# ---------------------------------------------------------------------------


@dataclass
class MissingNodeLabelRule:
    """Emits ``MISSING_NODE_LABEL`` (ERROR) when a declared node label is absent
    from the profile."""

    key: str = "node_label.missing"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if context.extra.get("address_type") != "node_label":
            return  # not a node-label address
        if context.right is not None:
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
        if context.extra.get("address_type") != "node_label":
            return  # not a node-label address
        if context.left is not None:
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
        if context.extra.get("address_type") != "rel_type":
            return  # not a rel-type address
        if context.right is not None:
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
        if context.extra.get("address_type") != "rel_type":
            return  # not a rel-type address
        if context.left is not None:
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

        type_info: TypeInfo | None = context.left
        if type_info is None or context.right is not None:
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
        if context.left is not None:
            return  # property is declared — not unexpected
        if context.right is None:
            return  # no observation either — nothing to report
        if "prop_name" not in context.extra:
            return  # not a property address
        from orthograph.graph_profile.models import PropertyProfile

        if not isinstance(context.right, PropertyProfile):
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

        type_info: TypeInfo | None = context.left
        prop_profile: PropertyProfile | None = context.right
        if not isinstance(type_info, TypeInfo) or not isinstance(
            prop_profile, PropertyProfile
        ):
            return  # need both sides as proper types
        if not (type_info.is_required and prop_profile.completeness < 1.0):
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
    """Emits ``PROPERTY_TYPE_MISMATCH`` for each observed type that maps to a
    Python type differing from the declared one.

    Prevalence-aware.  When the profile carries
    ``observed_type_counts`` the rule computes each off-type's **share** of the
    present population and modulates *severity*:

    - share ``>= severity_threshold`` → ERROR (systematic type drift).
    - share ``< severity_threshold``  → WARNING (a handful of dirty rows).

    The off-type share and counts are added to ``context`` and the percentage to
    the message.  The frozen issue ``code`` (``PROPERTY_TYPE_MISMATCH``) is never
    changed (that would need its own ADR).

    When ``observed_type_counts == {}`` (a backend/strategy that supplies only
    distinct type names) the rule is **byte-for-byte identical to its legacy
    behaviour**: ERROR per observed off-type, no prevalence in message or
    context.  The field is additive — this is a hard regression guard.
    """

    key: str = "property.type_mismatch"
    severity_threshold: float = 0.05

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        from orthograph.comparison.engine import db_type_to_python
        from orthograph.graph_definition.property_spec import TypeInfo
        from orthograph.graph_profile.models import PropertyProfile

        type_info: TypeInfo | None = context.left
        prop_profile: PropertyProfile | None = context.right
        if not isinstance(type_info, TypeInfo) or not isinstance(
            prop_profile, PropertyProfile
        ):
            return  # need both sides as proper types
        label: str = context.extra["label"]
        prop_name: str = context.extra["prop_name"]
        entity_type: EntityType = context.extra["entity_type"]
        expected_type = _expected_storage_type(type_info.python_type)
        # An enum whose members carry mixed value types (e.g. some str, some int)
        # has no single storage type; skip the structural type check and let
        # PropertyEnumValueRule reason about the values instead.
        if expected_type is None:
            return

        counts = prop_profile.observed_type_counts
        # Share denominator is the scan's own total (sum of the type counts), not
        # `present_count`.  Counts are intended to partition
        # `present_count`, but that equality is not transactionally enforced;
        #  using the scan's own sum keeps each share
        # internally consistent regardless of any snapshot divergence.
        total = sum(counts.values())

        for obs_type in prop_profile.observed_types:
            py_type = db_type_to_python(obs_type)
            if py_type is None or py_type is expected_type:
                continue

            entity_id = f"{label}.{prop_name}"
            base = (
                f"Property '{prop_name}' on {label} "
                f"has observed type '{obs_type}' "
                f"(Python: {py_type.__name__}), "
                f"expected {expected_type.__name__}"
            )

            # Honest escape: no counts (or this off-type not counted) ⇒ legacy
            # ERROR with the legacy message, no prevalence claim.
            off_type_count = counts.get(obs_type)
            if total == 0 or off_type_count is None:
                yield ValidationIssue(
                    code="PROPERTY_TYPE_MISMATCH",
                    severity=Severity.ERROR,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    message=base,
                )
                continue

            share = off_type_count / total
            severity = (
                Severity.ERROR if share >= self.severity_threshold else Severity.WARNING
            )
            yield ValidationIssue(
                code="PROPERTY_TYPE_MISMATCH",
                severity=severity,
                entity_type=entity_type,
                entity_id=entity_id,
                message=(
                    f"{base} "
                    f"({off_type_count}/{total} = {share:.1%} of observed values)"
                ),
                context={
                    "observed_type": obs_type,
                    "off_type_count": off_type_count,
                    "total_count": total,
                    "off_type_share": share,
                },
            )


@dataclass
class PropertyConstraintPresenceRule:
    """Reconcile a declared-required property against the observed DB constraint.

    Three outcomes, all distinct from the *declared-vs-occurrence* check
    (:class:`PropertyIncompleteRule`):

    - declared-required & ``constraint_required is False`` → ``PROPERTY_UNCONSTRAINED``
      (WARNING): the contract demands presence but no DB constraint guards it.
    - declared-required & ``constraint_required is None`` → ``CONSTRAINT_UNVERIFIABLE``
      (INFO): the backend/strategy could not read constraints — never a
      false verdict.
    - declared (but *not* declared-required, i.e. declared-optional) &
      ``constraint_required is True`` → ``UNDECLARED_CONSTRAINT`` (INFO): the DB is
      stricter than the declaration.  Note the early guard requires a declared
      :class:`TypeInfo` on the left, so a property that is observed but never
      declared does not reach this branch — it is handled upstream by the
      property-presence rules.

    declared-required & ``True`` is the happy path (silent).
    """

    key: str = "property.constraint_presence"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        from orthograph.graph_definition.property_spec import TypeInfo
        from orthograph.graph_profile.models import PropertyProfile

        type_info: TypeInfo | None = context.left
        prop_profile: PropertyProfile | None = context.right
        if not isinstance(type_info, TypeInfo) or not isinstance(
            prop_profile, PropertyProfile
        ):
            return  # need both sides as proper types
        constraint_required = prop_profile.constraint_required
        label: str = context.extra["label"]
        prop_name: str = context.extra["prop_name"]
        entity_type: EntityType = context.extra["entity_type"]
        entity_id = f"{label}.{prop_name}"

        if type_info.is_required:
            if constraint_required is False:
                yield ValidationIssue(
                    code="PROPERTY_UNCONSTRAINED",
                    severity=Severity.WARNING,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    message=(
                        f"Property '{prop_name}' on {label} is declared required "
                        "but no database constraint guarantees its presence"
                    ),
                )
            elif constraint_required is None:
                yield ValidationIssue(
                    code="CONSTRAINT_UNVERIFIABLE",
                    severity=Severity.INFO,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    message=(
                        f"Property '{prop_name}' on {label} is declared required "
                        "but constraint information is unavailable for this "
                        "backend/strategy profile"
                    ),
                )
            # constraint_required is True -> declared-required and DB-backed: silent
        elif constraint_required is True:
            yield ValidationIssue(
                code="UNDECLARED_CONSTRAINT",
                severity=Severity.INFO,
                entity_type=entity_type,
                entity_id=entity_id,
                message=(
                    f"Property '{prop_name}' on {label} is backed by a database "
                    "presence constraint but is not declared required in the model"
                ),
            )


@dataclass
class PropertyEnumValueRule:
    """Compare the observed value distribution against a declared enum.

    Fires only when the declared property type is an :class:`enum.Enum` subclass.
    The declared allowed values are ``{str(member.value) for member in enum}``;
    the observed values are the keys of
    ``PropertyProfile.value_distribution.histogram``.

    - observed value ∉ declared → ``UNDECLARED_PROPERTY_VALUE`` (WARNING): the data
      violates the declared contract.  Emitted for every *shown* value regardless
      of truncation, since a shown value was definitely observed.
    - declared value never observed → ``UNOBSERVED_PROPERTY_VALUE`` (INFO): drift.  Emitted only when the histogram is **complete** (``sample_complete``) — a
      truncated histogram cannot prove a declared value is absent.
    - ``value_distribution`` (or its ``histogram``) is ``None`` →
      ``PROPERTY_VALUE_UNVERIFIABLE`` (INFO): the backend did not supply per-value
      counts — never a false verdict.
     - ``value_distribution.sample_complete is False`` (the histogram was capped at
      ``limit`` and ``other_count`` observations are hidden) →
      ``PROPERTY_VALUE_UNVERIFIABLE`` (INFO): an undeclared value may be hidden in
      the truncated remainder and unobserved declared values cannot be confirmed,
      so the absence-based verdicts stand down.  A declared enum
      should be profiled with a complete histogram so this never fires.
    """  # NOQA E501

    key: str = "property.enum_value"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        import enum

        from orthograph.graph_definition.property_spec import TypeInfo
        from orthograph.graph_profile.models import PropertyProfile

        type_info: TypeInfo | None = context.left
        prop_profile: PropertyProfile | None = context.right
        if not isinstance(type_info, TypeInfo) or not isinstance(
            prop_profile, PropertyProfile
        ):
            return  # need both sides as proper types
        declared = type_info.python_type
        if not (isinstance(declared, type) and issubclass(declared, enum.Enum)):
            return  # value comparison applies only to declared enums

        label: str = context.extra["label"]
        prop_name: str = context.extra["prop_name"]
        entity_type: EntityType = context.extra["entity_type"]
        entity_id = f"{label}.{prop_name}"

        distribution = prop_profile.value_distribution
        if distribution is None or distribution.histogram is None:
            yield ValidationIssue(
                code="PROPERTY_VALUE_UNVERIFIABLE",
                severity=Severity.INFO,
                entity_type=entity_type,
                entity_id=entity_id,
                message=(
                    f"Property '{prop_name}' on {label} is declared as enum "
                    f"'{declared.__name__}' but no observed value distribution is "
                    "available to verify its values"
                ),
            )
            return

        declared_values = {str(member.value) for member in declared}
        observed_values = set(distribution.histogram)

        # Values that ARE shown in the histogram were definitely observed, so an
        # undeclared one among them is a true contract breach regardless of
        # truncation (the more severe direction).
        for value in sorted(observed_values - declared_values):
            yield ValidationIssue(
                code="UNDECLARED_PROPERTY_VALUE",
                severity=Severity.WARNING,
                entity_type=entity_type,
                entity_id=entity_id,
                message=(
                    f"Property '{prop_name}' on {label} has observed value "
                    f"'{value}' not declared in enum '{declared.__name__}'"
                ),
                context={"value": value, "declared": sorted(declared_values)},
            )

        # Truncation honesty: a histogram capped at ``limit``
        # (``sample_complete is False``) hides every value beyond the top-N in
        # ``other_count``.  Two verdicts then become unsafe and must not be made:
        #   * UNOBSERVED_PROPERTY_VALUE — a declared value absent from the *shown*
        #     keys may still live in the truncated remainder, so claiming it was
        #     "never observed" would be a false verdict.
        #   * the *completeness* of the undeclared-value scan — an undeclared
        #     value hidden in the remainder would be silently missed, the exact
        #     data-quality breach this rule exists to surface.
        # We therefore suppress the UNOBSERVED verdict and emit a single
        # PROPERTY_VALUE_UNVERIFIABLE (INFO) signalling the gap — never a false
        # verdict.  A declared enum should be profiled with a complete histogram
        # (no value cap); the inspector enforces this (see GraphInspector).
        if not distribution.sample_complete:
            yield ValidationIssue(
                code="PROPERTY_VALUE_UNVERIFIABLE",
                severity=Severity.INFO,
                entity_type=entity_type,
                entity_id=entity_id,
                message=(
                    f"Property '{prop_name}' on {label} is declared as enum "
                    f"'{declared.__name__}' but its observed value distribution is "
                    f"truncated ({distribution.other_count} observation(s) beyond "
                    f"the top-{distribution.limit} cap are hidden); undeclared "
                    "values in the remainder cannot be detected and unobserved "
                    "declared values cannot be confirmed"
                ),
                context={
                    "limit": distribution.limit,
                    "other_count": distribution.other_count,
                },
            )
            return

        for value in sorted(declared_values - observed_values):
            yield ValidationIssue(
                code="UNOBSERVED_PROPERTY_VALUE",
                severity=Severity.INFO,
                entity_type=entity_type,
                entity_id=entity_id,
                message=(
                    f"Property '{prop_name}' on {label} declares enum value "
                    f"'{value}' which was never observed"
                ),
                context={"value": value},
            )


def _conditional_sides(
    rt_class: Any,
) -> "list[tuple[Any, str]]":
    """Return ``(conditional_card, side)`` for **every** conditional directed side.

    Mirrors the inspector's ``_conditional_sides`` (NetworkX reference): source
    then target; undirected relationships are skipped (they are not partitioned).
    A relationship type conditional on both endpoints yields two entries, each
    enforced against its own per-side observed breakdown.  Returns an
    empty list when no side is conditional.
    """
    from orthograph.graph_definition.models import ConditionalCardinality

    if not rt_class.__directed__:
        return []
    sides: list[tuple[Any, str]] = []
    src_card = rt_class.__source_cardinality__
    if isinstance(src_card, ConditionalCardinality):
        sides.append((src_card, "source"))
    tgt_card = rt_class.__target_cardinality__
    if isinstance(tgt_card, ConditionalCardinality):
        sides.append((tgt_card, "target"))
    return sides


def _single_disc_key(matches: "Iterable[Any]") -> str | None:
    """Return the single discriminator property name across rule predicates.

    The single-``kind`` first cut discriminates on one property per
    endpoint; more (or zero) keys yield ``None`` (the null-partition component),
    matching the inspector's ``_discriminator_value`` convention.
    """
    keys: set[str] = set()
    for match in matches:
        keys.update(match.conditions)
    return next(iter(keys)) if len(keys) == 1 else None


def _partition_props(disc_key: str | None, value: str | None) -> dict[str, object]:
    """Reconstruct an endpoint's discriminator props from a partition value.

    The observed partition carries only the stringified discriminator *value*;
    pairing it with the conditional's referenced property name yields the prop
    map that :meth:`ConditionalCardinality.resolve_for_pair` matches against.
    A null value (no discriminator / absent edge) yields an empty map, so no
    predicate keyed on that property matches — the default bound then applies.
    """
    if disc_key is None or value is None:
        return {}
    return {disc_key: value}


def _degree_bounds(dist: Any) -> "tuple[int, int | None]":
    """Return ``(min, max)`` degree from a partition distribution.

    An absent partition (``dist is None``) — a declared pair never observed —
    counts as degree 0 (the missing-partition convention).  ``max`` is
    ``None`` only when the backend supplied a ``min`` but no ``max``.
    """
    if dist is None:
        return 0, 0
    observed_min = 0 if dist.min is None else int(dist.min)
    observed_max = None if dist.max is None else int(dist.max)
    return observed_min, observed_max


@dataclass
class CardinalityViolationRule:
    """Enforces declared relationship cardinality against observed degree stats.

    Constant declared cardinality: the observed aggregate distribution must lie
    within the declared bounds.  Both ``min`` and ``max`` are checked via
    :meth:`CardinalitySpec.contains` (E41.5), aligning the live-DB aggregate
    verdict with the in-memory per-node verdict (which also checks the full
    bound).  Emits ``CARDINALITY_VIOLATION`` (ERROR) on breach.

    Conditional declared cardinality
    (:class:`~orthograph.graph_definition.models.ConditionalCardinality`):

    - when the side's observed breakdown
      (``source_partitioned_cardinality`` / ``target_partitioned_cardinality``)
      is present, each declared/observed partition's degree is checked against
      its resolved bound; out-of-bounds → ``CARDINALITY_VIOLATION`` (ERROR)
      naming the pair.  An observed partition matching no declared rule yields
      ``CARDINALITY_UNMATCHED_KIND`` (INFO) plus a default-floor
      ``CARDINALITY_VIOLATION`` (ERROR) when a ``min > 0`` default is unmet
      (mirrors the in-memory default floor).
    - when the side's breakdown is absent, falls back to
      ``CARDINALITY_UNVERIFIABLE`` (INFO) — never a false verdict (E40.7).

    A relationship type conditional on **both** endpoints is enforced
    independently per side , matching the in-memory per-side verdict.
    This implements the cardinality rows of the comparison matrix.
    The single-``kind`` first cut assumes one string-valued discriminator per
    endpoint; multi-property / non-string discriminators are a guarded
    follow-on.
    """

    key: str = "rel.cardinality"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        from orthograph.graph_definition.models import RelationshipModel
        from orthograph.graph_profile.models import RelationshipTypeProfile

        rt_class = context.left
        rel_profile = context.right
        if not (
            isinstance(rt_class, type)
            and issubclass(rt_class, RelationshipModel)
            and isinstance(rel_profile, RelationshipTypeProfile)
        ):
            return  # need both sides as proper types
        if rel_profile.cardinality_stats is None:
            return

        label: str = context.address
        conditional_sides = _conditional_sides(rt_class)
        if conditional_sides:
            for card, side in conditional_sides:
                yield from self._compare_conditional(label, rel_profile, card, side)
        else:
            yield from self._compare_constant(label, rt_class, rel_profile)

    def _compare_constant(
        self, label: str, rt_class: Any, rel_profile: Any
    ) -> Iterable[ValidationIssue]:
        """Check the observed aggregate distribution against the declared bound."""
        from orthograph.graph_definition.models import representative_spec

        stats = rel_profile.cardinality_stats
        # E40.3: collapse a possibly-conditional value to a concrete spec
        # (E40.7 tracks per-endpoint resolution).
        src_card = representative_spec(rt_class.source_cardinality())

        if stats.min is None:
            yield ValidationIssue(
                code="CARDINALITY_UNVERIFIABLE",
                severity=Severity.INFO,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=label,
                message=(
                    f"Relationship '{label}' has no observed min degree; "
                    "cardinality bounds cannot be confirmed"
                ),
            )
            return

        # E41.5: check the full bound (both min and max) so the live-DB aggregate
        # verdict matches the in-memory per-node verdict (which uses contains()).
        observed_min = int(stats.min)
        observed_max = None if stats.max is None else int(stats.max)
        breaches_min = not src_card.contains(observed_min)
        breaches_max = observed_max is not None and not src_card.contains(observed_max)
        if breaches_min or breaches_max:
            yield ValidationIssue(
                code="CARDINALITY_VIOLATION",
                severity=Severity.ERROR,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=label,
                message=(
                    f"Relationship '{label}' has observed degrees "
                    f"{observed_min}..{observed_max}, expected "
                    f"{src_card.notation}"
                ),
                context={
                    "observed_min": observed_min,
                    "observed_max": stats.max,
                    "expected_min": src_card.min,
                    "expected_max": src_card.max,
                },
            )

    def _compare_conditional(
        self, label: str, rel_profile: Any, card: Any, side: str
    ) -> Iterable[ValidationIssue]:
        """Enforce per-pair bounds for one conditional declared side (E41.5/E41.7).

        Reads the side-specific observed breakdown
        (``source_partitioned_cardinality`` / ``target_partitioned_cardinality``)
        so a both-endpoint-conditional type is enforced independently per side,
        matching the in-memory per-side verdict.
        """
        from orthograph.graph_profile.models import PartitionKey

        partitioned = (
            rel_profile.source_partitioned_cardinality
            if side == "source"
            else rel_profile.target_partitioned_cardinality
        )
        if partitioned is None:
            yield ValidationIssue(
                code="CARDINALITY_UNVERIFIABLE",
                severity=Severity.INFO,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=label,
                message=(
                    f"Relationship '{label}' has a conditional {side} cardinality "
                    "but the profile carries no per-pair breakdown; bounds cannot "
                    "be confirmed (E40.7 fallback)"
                ),
            )
            return

        src_key = _single_disc_key(r.source for r in card.rules)
        tgt_key = _single_disc_key(r.target for r in card.rules)

        # Build {partition: distribution} once.  Observed partitions carry their
        # BoundedDistribution (decoded with the stored value alongside the key, so
        # the key is never re-derived lossily — finding 2); declared-but-unobserved
        # partitions map to ``None`` (degree 0, the missing-partition convention).
        observed: dict[Any, Any] = {
            self._decode_partition(encoded): dist
            for encoded, dist in partitioned.items()
        }
        declared = {
            PartitionKey(
                source_value=self._rule_value(rule.source, src_key),
                target_value=self._rule_value(rule.target, tgt_key),
            )
            for rule in card.rules
        }
        partitions = {p: observed.get(p) for p in declared | set(observed)}

        # Matched partitions: each is checked against its own resolved bound.
        # Unmatched partitions are grouped by the counted-side discriminator value
        # so the default floor is enforced once against that node-group's *total*
        # side degree (parity with the in-memory per-node floor — finding 1).
        unmatched_by_value: dict[str | None, list[Any]] = {}
        for partition, dist in partitions.items():
            counted_value = (
                partition.source_value if side == "source" else partition.target_value
            )
            counted_key = src_key if side == "source" else tgt_key
            if self._matches_any_rule(card, side, counted_key, counted_value):
                yield from self._check_matched(
                    label, card, side, src_key, tgt_key, partition, dist
                )
            else:
                unmatched_by_value.setdefault(counted_value, []).append(
                    (partition, dist)
                )

        for group in unmatched_by_value.values():
            yield from self._check_unmatched(label, card, group)

    def _check_matched(
        self,
        label: str,
        card: Any,
        side: str,
        src_key: str | None,
        tgt_key: str | None,
        partition: Any,
        dist: Any,
    ) -> Iterable[ValidationIssue]:
        """Check one rule-matched partition against its resolved per-pair bound."""
        observed_min, observed_max = _degree_bounds(dist)
        src_props = _partition_props(src_key, partition.source_value)
        tgt_props = _partition_props(tgt_key, partition.target_value)
        spec = card.resolve_for_pair(src_props, tgt_props)
        if not spec.contains(observed_min) or (
            observed_max is not None and not spec.contains(observed_max)
        ):
            yield ValidationIssue(
                code="CARDINALITY_VIOLATION",
                severity=Severity.ERROR,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=label,
                message=(
                    f"Relationship '{label}' partition "
                    f"(source={partition.source_value!r}, "
                    f"target={partition.target_value!r}) has observed degrees "
                    f"{observed_min}..{observed_max}, expected {spec.notation}"
                ),
                context={
                    "source_value": partition.source_value,
                    "target_value": partition.target_value,
                    "observed_min": observed_min,
                    "observed_max": observed_max,
                    "expected_min": spec.min,
                    "expected_max": spec.max,
                },
            )

    def _check_unmatched(
        self, label: str, card: Any, group: list[Any]
    ) -> Iterable[ValidationIssue]:
        """Emit drift + default-floor for one unmatched counted-side value group.

        A counted-side discriminator value matching no rule is governed solely by
        ``card.default``. The floor is checked once against the
        group's *total* side degree — the sum across the partitions this value
        spans — mirroring the in-memory per-node floor, which checks the node's
        total side degree, not each partition independently (finding 1 / E41.5
        parity).  A single ``CARDINALITY_UNMATCHED_KIND`` INFO is emitted per
        value (drift granularity matching the in-memory once-per-node emission).
        """
        # group is a list of (partition, dist); they share one counted-side value.
        sample_partition = group[0][0]
        total_min = 0
        total_max: int | None = 0
        for _partition, dist in group:
            part_min, part_max = _degree_bounds(dist)
            total_min += part_min
            if part_max is None or total_max is None:
                total_max = None
            else:
                total_max += part_max

        yield ValidationIssue(
            code="CARDINALITY_UNMATCHED_KIND",
            severity=Severity.INFO,
            entity_type=EntityType.RELATIONSHIP,
            entity_id=label,
            message=(
                f"Relationship '{label}' partition "
                f"(source={sample_partition.source_value!r}, "
                f"target={sample_partition.target_value!r}) "
                "matches no declared cardinality rule; the default bound applies"
            ),
            context={
                "source_value": sample_partition.source_value,
                "target_value": sample_partition.target_value,
            },
        )
        default = card.default
        if not default.contains(total_min) or (
            total_max is not None and not default.contains(total_max)
        ):
            yield ValidationIssue(
                code="CARDINALITY_VIOLATION",
                severity=Severity.ERROR,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=label,
                message=(
                    f"Relationship '{label}' partition "
                    f"(source={sample_partition.source_value!r}, "
                    f"target={sample_partition.target_value!r}) matches no rule and "
                    f"has total observed degrees {total_min}..{total_max}, violating "
                    f"the default bound {default.notation}"
                ),
                context={
                    "source_value": sample_partition.source_value,
                    "target_value": sample_partition.target_value,
                    "observed_min": total_min,
                    "observed_max": total_max,
                    "expected_min": default.min,
                    "expected_max": default.max,
                    "default": True,
                },
            )

    @staticmethod
    def _rule_value(match: Any, disc_key: str | None) -> str | None:
        """Stringified value a rule predicate pins for *disc_key* (or None)."""
        if disc_key is None or disc_key not in match.conditions:
            return None
        return str(match.conditions[disc_key])

    @staticmethod
    def _decode_partition(encoded: str) -> Any:
        """Reconstruct a :class:`PartitionKey` from an observed dict key.

        The observed key is ``str(PartitionKey)`` — ``"src=<v>|tgt=<v>"`` with
        ``None`` encoded as the literal ``"null"`` (PartitionKey.__str__).  The
        single-``kind`` first cut (E41) uses simple string discriminator values
        with no ``|``/``=`` separators, so splitting on those delimiters recovers
        the original values; richer values are a guarded follow-on (the stored
        distribution is carried alongside the key by the caller, so the key is
        never used to re-look-up the value — finding 2).
        """
        from orthograph.graph_profile.models import PartitionKey

        src_part, _, tgt_part = encoded.partition("|")
        src_raw = src_part.removeprefix("src=")
        tgt_raw = tgt_part.removeprefix("tgt=")
        return PartitionKey(
            source_value=None if src_raw == "null" else src_raw,
            target_value=None if tgt_raw == "null" else tgt_raw,
        )

    @staticmethod
    def _matches_any_rule(
        card: Any, side: str, counted_key: str | None, counted_value: str | None
    ) -> bool:
        """True when some rule's counted-endpoint predicate matches this value."""
        props = _partition_props(counted_key, counted_value)
        for rule in card.rules:
            own = rule.source if side == "source" else rule.target
            if own.matches(props):
                return True
        return False


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
        PropertyConstraintPresenceRule(),
        PropertyEnumValueRule(),
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

        prop_profile = context.right
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
