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

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol, runtime_checkable

from orthograph.comparison.type_mapping import db_type_to_python
from orthograph.comparison.views import GraphView
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue
from orthograph.graph_definition.models import (
    ConditionalCardinality,
    PropMatch,
    RelationshipModel,
    representative_spec,
)
from orthograph.graph_definition.property_spec import TypeInfo
from orthograph.graph_profile.models import (
    BoundedDistribution,
    PartitionKey,
    PropertyProfile,
    RelationshipTypeProfile,
)


class _PropertyAddress(NamedTuple):
    """The label / property / entity coordinates a property rule operates on.

    Reads ``label``, ``prop_name`` and ``entity_type`` from the engine-stamped
    ``RuleContext.extra`` and derives the ``label.prop_name`` issue id once, so
    the property rules share one preamble instead of repeating it.
    """

    label: str
    prop_name: str
    entity_type: EntityType
    entity_id: str

    @classmethod
    def from_context(cls, context: "RuleContext") -> "_PropertyAddress":
        label: str = context.extra[LABEL]
        prop_name: str = context.extra[PROP_NAME]
        return cls(
            label=label,
            prop_name=prop_name,
            entity_type=context.extra[ENTITY_TYPE],
            entity_id=f"{label}.{prop_name}",
        )


# One partition and its observed degree distribution.
class _PartitionDegree(NamedTuple):
    """One partition paired with its observed degree distribution.

    ``stats is None`` means the partition was declared but never observed →
    degree 0 (the missing-partition convention).
    """

    partition: PartitionKey
    stats: BoundedDistribution | None


# ---------------------------------------------------------------------------
# RuleContext.extra contract — named keys and address-type values
#
# ``RuleContext.extra`` is a loosely-typed ``dict[str, Any]`` whose keys form a
# string-keyed contract between the *producer* (the engine in ``engine.py``,
# which stamps the dict per address) and the *consumers* (every rule in this
# module and in ``diff_rules.py``).  The constants below name that contract so
# no rule or producer hard-codes a bare string.
#
# Keys, and which addresses carry them:
#
#   ADDRESS_TYPE   present on node-label and rel-type addresses; its value is
#                  one of ``ADDR_NODE_LABEL`` / ``ADDR_REL_TYPE``.  Absent on
#                  property addresses.
#   LABEL          property addresses only — the owning node label str or the
#                  ``str(RelTypeKey)`` for a relationship property.
#   PROP_NAME      property addresses only — the property name str.
#   ENTITY_TYPE    property addresses only — the :class:`EntityType` of the
#                  owning entity (``NODE`` or ``RELATIONSHIP``).
#   MAX_DISTINCT_COUNT  optional; supplied only by callers that inject
#                  :class:`PropertyDistinctCountRule` (not in ``standard_rules``).
#
# ``left`` / ``right`` hold the address's left/right object (or ``None`` when
# the address exists on only one side):
#   - node-label address : ``NodeModel`` subclass / ``NodeTypeProfile``
#   - rel-type address    : ``RelationshipModel`` subclass / ``RelationshipTypeProfile``
#   - property address    : ``TypeInfo`` (declared) / ``PropertyProfile`` (observed)
# ---------------------------------------------------------------------------

# extra keys
ADDRESS_TYPE = "address_type"
LABEL = "label"
PROP_NAME = "prop_name"
ENTITY_TYPE = "entity_type"
MAX_DISTINCT_COUNT = "max_distinct_count"

# extra[ADDRESS_TYPE] values
ADDR_NODE_LABEL = "node_label"
ADDR_REL_TYPE = "rel_type"


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
        String-keyed context bag.  Its keys and values are the contract named
        by the ``ADDRESS_TYPE`` / ``LABEL`` / ``PROP_NAME`` / ``ENTITY_TYPE`` /
        ``MAX_DISTINCT_COUNT`` constants above (with ``ADDRESS_TYPE`` taking the
        ``ADDR_NODE_LABEL`` / ``ADDR_REL_TYPE`` values); see the module-level
        note for which keys each address kind carries.
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
    if isinstance(python_type, type) and issubclass(python_type, enum.Enum):
        value_types = {type(member.value) for member in python_type}
        if len(value_types) == 1:
            return next(iter(value_types))
        return None  # mixed-value-type enum: no single storage type
    return python_type


# ---------------------------------------------------------------------------
# Standard rule set
#
# Address conventions used by the engine (extra keys named by the constants
# defined above — ADDRESS_TYPE/LABEL/PROP_NAME/ENTITY_TYPE):
#   node-label rules   : address = label str
#   rel-type rules     : address = str(RelTypeKey) ("source:LABEL:target")
#   property rules     : address = "<label>.<prop_name>" str (node) or
#                        "<rel_key>.<prop_name>" str (relationship)
#                        extra[LABEL]       = label str / rel_key str
#                        extra[PROP_NAME]   = property name str
#                        extra[ENTITY_TYPE] = EntityType
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


# ---------------------------------------------------------------------------
# Label/rel-type presence rules
#
# The four rules below share one shape: address-kind guard → if the side that
# must be empty is in fact present, presence is satisfied → otherwise the
# address *is* the entity id, so emit one issue.  ``_presence_issues`` holds
# that shape once; each thin rule supplies its address kind, which side must be
# empty, and the issue fields.
#
# A "missing" finding fires when the *observed* side (right) is absent for a
# declared address; an "unexpected" finding fires when the *declared* side
# (left) is absent for an observed address.
# ---------------------------------------------------------------------------

_OBSERVED_SIDE = "right"  # absent → declared-but-not-observed → "missing"
_DECLARED_SIDE = "left"  # absent → observed-but-not-declared → "unexpected"


def _presence_issues(
    context: RuleContext,
    *,
    address_type: str,
    side_that_must_be_empty: str,  # _OBSERVED_SIDE / _DECLARED_SIDE
    code: str,
    severity: Severity,
    entity_type: EntityType,
    message_template: str,  # one ``{address}`` placeholder
) -> Iterable[ValidationIssue]:
    """Emit one presence issue at a node-label/rel-type ``address`` when
    ``side_that_must_be_empty`` is absent."""
    if context.extra.get(ADDRESS_TYPE) != address_type:
        return  # not my address kind
    side = context.right if side_that_must_be_empty == _OBSERVED_SIDE else context.left
    if side is not None:
        return  # that side is present — presence is satisfied
    address: str = context.address
    yield ValidationIssue(
        code=code,
        severity=severity,
        entity_type=entity_type,
        entity_id=address,
        message=message_template.format(address=address),
    )


@dataclass
class MissingNodeLabelRule:
    """Emits ``MISSING_NODE_LABEL`` (ERROR) when a declared node label is absent
    from the profile."""

    key: str = "node_label.missing"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        return _presence_issues(
            context,
            address_type=ADDR_NODE_LABEL,
            side_that_must_be_empty=_OBSERVED_SIDE,
            code="MISSING_NODE_LABEL",
            severity=Severity.ERROR,
            entity_type=EntityType.NODE,
            message_template=(
                "Model defines node type '{address}' but no instances found in profile"
            ),
        )


@dataclass
class UnexpectedNodeLabelRule:
    """Emits ``UNEXPECTED_NODE_LABEL`` (WARNING) when a profile node label is
    not in the model."""

    key: str = "node_label.unexpected"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        return _presence_issues(
            context,
            address_type=ADDR_NODE_LABEL,
            side_that_must_be_empty=_DECLARED_SIDE,
            code="UNEXPECTED_NODE_LABEL",
            severity=Severity.WARNING,
            entity_type=EntityType.NODE,
            message_template=(
                "Profile contains node label '{address}' not defined in model"
            ),
        )


@dataclass
class MissingRelTypeRule:
    """Emits ``MISSING_REL_TYPE`` (ERROR) when a declared relationship type is
    absent from the profile."""

    key: str = "rel_type.missing"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        return _presence_issues(
            context,
            address_type=ADDR_REL_TYPE,
            side_that_must_be_empty=_OBSERVED_SIDE,
            code="MISSING_REL_TYPE",
            severity=Severity.ERROR,
            entity_type=EntityType.RELATIONSHIP,
            message_template=(
                "Model defines relationship type '{address}' "
                "but no instances found in profile"
            ),
        )


@dataclass
class UnexpectedRelTypeRule:
    """Emits ``UNEXPECTED_REL_TYPE`` (WARNING) when a profile relationship type
    is not in the model."""

    key: str = "rel_type.unexpected"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        return _presence_issues(
            context,
            address_type=ADDR_REL_TYPE,
            side_that_must_be_empty=_DECLARED_SIDE,
            code="UNEXPECTED_REL_TYPE",
            severity=Severity.WARNING,
            entity_type=EntityType.RELATIONSHIP,
            message_template=(
                "Profile contains relationship type '{address}' not defined in model"
            ),
        )


@dataclass
class MissingPropertyRule:
    """Emits ``MISSING_PROPERTY`` (ERROR) when a required declared property has
    no ``PropertyProfile``."""

    key: str = "property.missing"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        type_info: TypeInfo | None = context.left
        if type_info is None or context.right is not None:
            return  # no declaration or property was observed — not applicable
        if not isinstance(type_info, TypeInfo):
            return  # context is not a property address
        if not type_info.is_required:
            return  # optional property missing from profile is not an error
        label: str = context.extra[LABEL]
        prop_name: str = context.extra[PROP_NAME]
        entity_type: EntityType = context.extra[ENTITY_TYPE]
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
        if PROP_NAME not in context.extra:
            return  # not a property address
        if not isinstance(context.right, PropertyProfile):
            return  # not a property observation
        label: str = context.extra[LABEL]
        prop_name: str = context.extra[PROP_NAME]
        entity_type: EntityType = context.extra[ENTITY_TYPE]
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
        type_info: TypeInfo | None = context.left
        prop_profile: PropertyProfile | None = context.right
        if not isinstance(type_info, TypeInfo) or not isinstance(
            prop_profile, PropertyProfile
        ):
            return  # need both sides as proper types
        if not (type_info.is_required and prop_profile.completeness < 1.0):
            return
        label: str = context.extra[LABEL]
        prop_name: str = context.extra[PROP_NAME]
        entity_type: EntityType = context.extra[ENTITY_TYPE]
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
        type_info: TypeInfo | None = context.left
        prop_profile: PropertyProfile | None = context.right
        if not isinstance(type_info, TypeInfo) or not isinstance(
            prop_profile, PropertyProfile
        ):
            return  # need both sides as proper types
        expected_type = _expected_storage_type(type_info.python_type)
        # An enum whose members carry mixed value types (e.g. some str, some int)
        # has no single storage type; skip the structural type check and let
        # PropertyEnumValueRule reason about the values instead.
        if expected_type is None:
            return

        address = _PropertyAddress.from_context(context)
        yield from self._type_mismatch_issues(prop_profile, expected_type, address)

    def _type_mismatch_issues(
        self,
        prop_profile: PropertyProfile,
        expected_type: type,
        address: "_PropertyAddress",
    ) -> Iterable[ValidationIssue]:
        """One ``PROPERTY_TYPE_MISMATCH`` per observed off-type, prevalence-aware."""
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

            base = (
                f"Property '{address.prop_name}' on {address.label} "
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
                    entity_type=address.entity_type,
                    entity_id=address.entity_id,
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
                entity_type=address.entity_type,
                entity_id=address.entity_id,
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
        type_info: TypeInfo | None = context.left
        prop_profile: PropertyProfile | None = context.right
        if not isinstance(type_info, TypeInfo) or not isinstance(
            prop_profile, PropertyProfile
        ):
            return  # need both sides as proper types
        constraint_required = prop_profile.constraint_required
        label: str = context.extra[LABEL]
        prop_name: str = context.extra[PROP_NAME]
        entity_type: EntityType = context.extra[ENTITY_TYPE]
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
        type_info: TypeInfo | None = context.left
        prop_profile: PropertyProfile | None = context.right
        if not isinstance(type_info, TypeInfo) or not isinstance(
            prop_profile, PropertyProfile
        ):
            return  # need both sides as proper types
        declared = type_info.python_type
        if not (isinstance(declared, type) and issubclass(declared, enum.Enum)):
            return  # value comparison applies only to declared enums

        address = _PropertyAddress.from_context(context)

        distribution = prop_profile.value_distribution
        if distribution is None or distribution.histogram is None:
            yield self._missing_distribution_issue(declared, address)
            return

        declared_values = {str(member.value) for member in declared}
        observed_values = set(distribution.histogram)

        yield from self._undeclared_value_issues(
            declared, declared_values, observed_values, address
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
            yield self._truncated_issue(declared, distribution, address)
            return

        yield from self._unobserved_value_issues(
            declared_values, observed_values, address
        )

    @staticmethod
    def _missing_distribution_issue(
        declared: type[enum.Enum], address: "_PropertyAddress"
    ) -> ValidationIssue:
        """No per-value counts at all → ``PROPERTY_VALUE_UNVERIFIABLE``."""
        return ValidationIssue(
            code="PROPERTY_VALUE_UNVERIFIABLE",
            severity=Severity.INFO,
            entity_type=address.entity_type,
            entity_id=address.entity_id,
            message=(
                f"Property '{address.prop_name}' on {address.label} is declared "
                f"as enum '{declared.__name__}' but no observed value distribution "
                "is available to verify its values"
            ),
        )

    @staticmethod
    def _undeclared_value_issues(
        declared: type[enum.Enum],
        declared_values: set[str],
        observed_values: set[str],
        address: "_PropertyAddress",
    ) -> Iterable[ValidationIssue]:
        """One ``UNDECLARED_PROPERTY_VALUE`` per observed value not in the enum.

        Values that ARE shown in the histogram were definitely observed, so an
        undeclared one among them is a true contract breach regardless of
        truncation (the more severe direction).
        """
        for value in sorted(observed_values - declared_values):
            yield ValidationIssue(
                code="UNDECLARED_PROPERTY_VALUE",
                severity=Severity.WARNING,
                entity_type=address.entity_type,
                entity_id=address.entity_id,
                message=(
                    f"Property '{address.prop_name}' on {address.label} has "
                    f"observed value '{value}' not declared in enum "
                    f"'{declared.__name__}'"
                ),
                context={"value": value, "declared": sorted(declared_values)},
            )

    @staticmethod
    def _truncated_issue(
        declared: type[enum.Enum],
        distribution: BoundedDistribution,
        address: "_PropertyAddress",
    ) -> ValidationIssue:
        """Histogram capped → ``PROPERTY_VALUE_UNVERIFIABLE`` for absence verdicts."""
        return ValidationIssue(
            code="PROPERTY_VALUE_UNVERIFIABLE",
            severity=Severity.INFO,
            entity_type=address.entity_type,
            entity_id=address.entity_id,
            message=(
                f"Property '{address.prop_name}' on {address.label} is declared "
                f"as enum '{declared.__name__}' but its observed value "
                f"distribution is truncated ({distribution.other_count} "
                f"observation(s) beyond the top-{distribution.limit} cap are "
                "hidden); undeclared values in the remainder cannot be detected "
                "and unobserved declared values cannot be confirmed"
            ),
            context={
                "limit": distribution.limit,
                "other_count": distribution.other_count,
            },
        )

    @staticmethod
    def _unobserved_value_issues(
        declared_values: set[str],
        observed_values: set[str],
        address: "_PropertyAddress",
    ) -> Iterable[ValidationIssue]:
        """One ``UNOBSERVED_PROPERTY_VALUE`` per declared value never observed."""
        for value in sorted(declared_values - observed_values):
            yield ValidationIssue(
                code="UNOBSERVED_PROPERTY_VALUE",
                severity=Severity.INFO,
                entity_type=address.entity_type,
                entity_id=address.entity_id,
                message=(
                    f"Property '{address.prop_name}' on {address.label} declares "
                    f"enum value '{value}' which was never observed"
                ),
                context={"value": value},
            )


def _conditional_sides(
    rt_class: type[RelationshipModel],
) -> list[tuple[ConditionalCardinality, str]]:
    """Return ``(conditional_card, side)`` for **every** conditional directed side.

    Mirrors the inspector's ``_conditional_sides`` (NetworkX reference): source
    then target; undirected relationships are skipped (they are not partitioned).
    A relationship type conditional on both endpoints yields two entries, each
    enforced against its own per-side observed breakdown.  Returns an
    empty list when no side is conditional.
    """
    if not rt_class.__directed__:
        return []
    sides: list[tuple[ConditionalCardinality, str]] = []
    src_card = rt_class.source_cardinality()
    if isinstance(src_card, ConditionalCardinality):
        sides.append((src_card, "source"))
    tgt_card = rt_class.target_cardinality()
    if isinstance(tgt_card, ConditionalCardinality):
        sides.append((tgt_card, "target"))
    return sides


def _declared_endpoint_map(match: PropMatch) -> dict[str, str | None]:
    """Stringified condition map for one endpoint of a declared rule.

    Mirrors the observed :class:`PartitionKey` endpoint maps the producers emit:
    a wildcard ``PropMatch()`` (no conditions) yields ``{}``; otherwise each
    condition value is stringified the same way the inspector stringifies the
    observed discriminator value, so a declared map compares equal to its
    observed counterpart.
    """
    return {k: str(v) for k, v in match.conditions.items()}


def _degree_bounds(dist: BoundedDistribution | None) -> tuple[int, int | None]:
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
        self,
        label: str,
        rt_class: type[RelationshipModel],
        rel_profile: RelationshipTypeProfile,
    ) -> Iterable[ValidationIssue]:
        """Check the observed aggregate distribution against the declared bound."""
        stats = rel_profile.cardinality_stats
        assert stats is not None  # __call__ guards on cardinality_stats presence
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
        self,
        label: str,
        rel_profile: RelationshipTypeProfile,
        card: ConditionalCardinality,
        side: str,
    ) -> Iterable[ValidationIssue]:
        """Enforce per-pair bounds for one conditional declared side (E41.5/E41.7).

        Reads the side-specific observed breakdown
        (``source_partitioned_cardinality`` / ``target_partitioned_cardinality``)
        so a both-endpoint-conditional type is enforced independently per side,
        matching the in-memory per-side verdict.
        """
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

        # Build {partition: distribution} once.  Observed rows carry their
        # name-bearing PartitionKey directly (no string parse — the key is
        # self-describing); declared-but-unobserved partitions map to ``None``
        # (degree 0, the missing-partition convention).  An observed partition
        # overrides its declared counterpart by PartitionKey (map) equality.
        partitions: dict[PartitionKey, BoundedDistribution | None] = {}
        for rule in card.rules:
            declared_key = PartitionKey(
                source=_declared_endpoint_map(rule.source),
                target=_declared_endpoint_map(rule.target),
            )
            partitions.setdefault(declared_key, None)
        for row in partitioned:
            partitions[row.key] = row.stats

        # Matched partitions: each is checked against its own resolved bound.
        # Unmatched partitions are grouped by the counted-side discriminator map
        # so the default floor is enforced once against that node-group's *total*
        # side degree (parity with the in-memory per-node floor — finding 1).  The
        # counted map keys the group via its (hashable) frozenset of items.
        unmatched_by_value: dict[
            frozenset[tuple[str, str | None]], list[_PartitionDegree]
        ] = {}
        for partition, dist in partitions.items():
            counted_map = partition.source if side == "source" else partition.target
            if self._matches_any_rule(card, side, counted_map):
                yield from self._check_matched(label, card, partition, dist)
            else:
                group_key = frozenset(counted_map.items())
                unmatched_by_value.setdefault(group_key, []).append(
                    _PartitionDegree(partition, dist)
                )

        for group in unmatched_by_value.values():
            yield from self._check_unmatched(label, card, group)

    def _check_matched(
        self,
        label: str,
        card: ConditionalCardinality,
        partition: PartitionKey,
        dist: BoundedDistribution | None,
    ) -> Iterable[ValidationIssue]:
        """Check one rule-matched partition against its resolved per-pair bound."""
        observed_min, observed_max = _degree_bounds(dist)
        # The partition's name-bearing maps ARE the endpoint props; feed them to
        # resolve_for_pair directly (no name re-derivation, no value-only round-trip).
        spec = card.resolve_for_pair(partition.source, partition.target)
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
                    f"(source={partition.source!r}, "
                    f"target={partition.target!r}) has observed degrees "
                    f"{observed_min}..{observed_max}, expected {spec.notation}"
                ),
                context={
                    "source": partition.source,
                    "target": partition.target,
                    "observed_min": observed_min,
                    "observed_max": observed_max,
                    "expected_min": spec.min,
                    "expected_max": spec.max,
                },
            )

    def _check_unmatched(
        self, label: str, card: ConditionalCardinality, group: list[_PartitionDegree]
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
        # The group shares one counted-side map; any member names the value pair.
        sample_partition = group[0].partition
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
                f"(source={sample_partition.source!r}, "
                f"target={sample_partition.target!r}) "
                "matches no declared cardinality rule; the default bound applies"
            ),
            context={
                "source": sample_partition.source,
                "target": sample_partition.target,
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
                    f"(source={sample_partition.source!r}, "
                    f"target={sample_partition.target!r}) matches no rule and "
                    f"has total observed degrees {total_min}..{total_max}, violating "
                    f"the default bound {default.notation}"
                ),
                context={
                    "source": sample_partition.source,
                    "target": sample_partition.target,
                    "observed_min": total_min,
                    "observed_max": total_max,
                    "expected_min": default.min,
                    "expected_max": default.max,
                    "default": True,
                },
            )

    @staticmethod
    def _matches_any_rule(
        card: ConditionalCardinality, side: str, counted_map: Mapping[str, str | None]
    ) -> bool:
        """True when some rule's counted-endpoint predicate matches this map.

        The observed name-bearing endpoint map *is* the props, so it is fed to
        :meth:`PropMatch.matches` directly — no name re-derivation, no value-only
        round-trip.
        """
        for rule in card.rules:
            own = rule.source if side == "source" else rule.target
            if own.matches(counted_map):
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
    exceeds ``extra[MAX_DISTINCT_COUNT]``.

    Not included in :func:`standard_rules` — inject explicitly when needed.
    """

    key: str = "property.distinct_count"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        prop_profile = context.right
        max_distinct: int | None = context.extra.get(MAX_DISTINCT_COUNT)
        if not isinstance(prop_profile, PropertyProfile):
            return  # not a property address
        if max_distinct is None:
            return  # declared constraint not supplied — skip
        if prop_profile.distinct_count is None:
            return  # observed measurement not populated — skip

        if prop_profile.distinct_count > max_distinct:
            label: str = context.extra[LABEL]
            prop_name: str = context.extra[PROP_NAME]
            entity_type: EntityType = context.extra[ENTITY_TYPE]
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
