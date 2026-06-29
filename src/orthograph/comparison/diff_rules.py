"""Symmetric diff rule family for the comparison engine.

Each rule implements the :class:`~orthograph.comparison.rules.Rule` Protocol,
reads ``context.left`` / ``context.right`` symmetrically, and emits only
``Severity.INFO`` issues.

This module implements the symmetric diff rules.

Two questions, two rule families:

- **Satisfaction** (profile ↔ definition): ``standard_rules()`` in ``rules.py``
  — asymmetric, uses left=declared/right=observed semantics, emits
  ERROR/WARNING/INFO.
- **Diff** (profile ↔ profile, definition ↔ definition): ``diff_rules()`` here
  — symmetric, neutral left/right semantics, emits INFO only.

Why this module's type-comparison logic is not consolidated with ``rules.py``:
the apparent similarity is coincidental.  ``PropertyTypeMismatchRule``
(satisfaction) checks observed types against *one* declared storage type and
modulates severity by prevalence — inputs are always ``(TypeInfo,
PropertyProfile)``.  ``PropertyTypeChangedRule`` (diff) compares two *sets* of
resolved Python types, or two declared ``python_type`` fields, for equality —
inputs are same-kind pairs ``(TypeInfo, TypeInfo)`` or ``(PropertyProfile,
PropertyProfile)``.  A shared core would need to dispatch across these shapes,
adding more machinery than it removes.  Likewise, ``_rel_operand_kind`` exists
here because the diff path must distinguish profile↔profile from
definition↔definition at runtime; the satisfaction path has a structurally fixed
``(DefinitionView, ProfileView)`` pairing set at the engine call site, so no
runtime dispatch is needed there.  The only genuinely shared piece — the
DB-type-string → Python-type mapping — already lives in ``type_mapping.py``
and is imported by both modules.

Address conventions (set by the engine, same as ``rules.py``; the ``extra``
keys are named by the ``ADDRESS_TYPE`` / ``LABEL`` / ``PROP_NAME`` /
``ENTITY_TYPE`` constants imported from ``rules.py``):

- Node-label address  : ``extra[ADDRESS_TYPE] == ADDR_NODE_LABEL``; ``left``/
  ``right`` are ``NodeTypeProfile`` or ``NodeModel`` subclass (or ``None``).
- Rel-type address    : ``extra[ADDRESS_TYPE] == ADDR_REL_TYPE``; same shape
  with ``RelationshipTypeProfile`` or ``RelationshipModel`` subclass.
- Property address    : ``extra[PROP_NAME]`` present; ``left``/``right`` are
  ``TypeInfo`` (definition) or ``PropertyProfile`` (profile), or ``None``.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from orthograph.comparison.rules import (
    ADDR_NODE_LABEL,
    ADDR_REL_TYPE,
    ADDRESS_TYPE,
    ENTITY_TYPE,
    LABEL,
    PROP_NAME,
    Rule,
    RuleContext,
)
from orthograph.comparison.type_mapping import db_type_to_python
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue
from orthograph.graph_definition.models import (
    ConditionalCardinality,
    RelationshipModel,
    representative_spec,
)
from orthograph.graph_definition.property_spec import TypeInfo
from orthograph.graph_profile.models import (
    NodeTypeProfile,
    PartitionedCardinalityRow,
    PropertyProfile,
    RelationshipTypeProfile,
)


# ---------------------------------------------------------------------------
# Relationship operand kind resolution
# ---------------------------------------------------------------------------

RelKind = Literal["profile", "definition"]


def _rel_operand_kind(left: object, right: object) -> RelKind | None:
    """Return 'profile' or 'definition' if both operands are the same rel kind.

    Returns None when the operands are mixed or unrecognised (e.g. profile vs
    definition — only arises in compare_profile_to_definition which uses
    standard_rules(), not diff_rules()).
    """
    if isinstance(left, RelationshipTypeProfile) and isinstance(
        right, RelationshipTypeProfile
    ):
        return "profile"
    if (
        isinstance(left, type)
        and issubclass(left, RelationshipModel)
        and isinstance(right, type)
        and issubclass(right, RelationshipModel)
    ):
        return "definition"
    return None


# ---------------------------------------------------------------------------
# Property type helpers
# ---------------------------------------------------------------------------


def _resolved_definition_types(
    left: TypeInfo, right: TypeInfo
) -> tuple[object, object] | None:
    """Return (left_desc, right_desc) if the Python types differ, else None."""
    if left.python_type is right.python_type:
        return None
    return left.python_type, right.python_type


def _resolved_profile_types(
    left: PropertyProfile, right: PropertyProfile
) -> tuple[object, object] | None:
    """Return (left_types, right_types) as sets if they differ, else None."""
    left_types = {
        (m if (m := db_type_to_python(t)) is not None else t)
        for t in left.observed_types
    }
    right_types = {
        (m if (m := db_type_to_python(t)) is not None else t)
        for t in right.observed_types
    }
    if not left_types or not right_types:
        return None
    if left_types == right_types:
        return None
    return left_types, right_types


# ---------------------------------------------------------------------------
# Endpoint helpers (definition ↔ definition)
# ---------------------------------------------------------------------------


def _endpoint_issues_definition(
    rt: str,
    left: type[RelationshipModel],
    right: type[RelationshipModel],
) -> Iterable[ValidationIssue]:
    """Yield ENDPOINTS_CHANGED issues for a definition ↔ definition comparison.

     The source/target labels are part of relationship *identity*
    (encoded in the address), so a difference in either is a different address
    and is reported by the presence rules — never here.  Only the
    ``__directed__`` flag remains an *attribute* delta, so this rule shrinks to
    the direction-flag signal.
    """
    if left.__directed__ != right.__directed__:
        yield ValidationIssue(
            code="ENDPOINTS_CHANGED",
            severity=Severity.INFO,
            entity_type=EntityType.RELATIONSHIP,
            entity_id=rt,
            message=(
                f"Relationship '{rt}' directed flag differs: "
                f"left={left.__directed__!r} right={right.__directed__!r}"
            ),
            context={
                "role": "directed",
                "left": left.__directed__,
                "right": right.__directed__,
            },
        )


# ---------------------------------------------------------------------------
# Cardinality helpers (profile ↔ profile and definition ↔ definition)
# ---------------------------------------------------------------------------


def _cardinality_issue_profile(
    rt: str,
    left: RelationshipTypeProfile,
    right: RelationshipTypeProfile,
) -> ValidationIssue | None:
    """Return a CARDINALITY_CHANGED issue if stats differ, else None."""
    if left.cardinality_stats is None or right.cardinality_stats is None:
        return None
    l_stats = left.cardinality_stats
    r_stats = right.cardinality_stats
    if l_stats.min == r_stats.min and l_stats.max == r_stats.max:
        return None
    return ValidationIssue(
        code="CARDINALITY_CHANGED",
        severity=Severity.INFO,
        entity_type=EntityType.RELATIONSHIP,
        entity_id=rt,
        message=(
            f"Relationship '{rt}' cardinality differs: "
            f"left min={l_stats.min} max={l_stats.max}, "
            f"right min={r_stats.min} max={r_stats.max}"
        ),
        context={
            "left_min": l_stats.min,
            "left_max": l_stats.max,
            "right_min": r_stats.min,
            "right_max": r_stats.max,
        },
    )


def _partitioned_cardinality_issues_profile(
    rt: str,
    left: RelationshipTypeProfile,
    right: RelationshipTypeProfile,
) -> Iterable[ValidationIssue]:
    """Yield ``PARTITIONED_CARDINALITY_CHANGED`` (INFO) per differing partition.

    Matches partitions across the two profiles by :class:`PartitionKey` **map
    equality**, so partitions discriminating the same value on *different*
    properties (``{"type": "combine"}`` vs ``{"stage": "combine"}``) no longer
    collide — they surface as a removed + an added partition.  A partition on one
    side only emits a ``left_only`` / ``right_only`` delta; a partition on both
    sides with differing degree ``stats`` (``min``/``max``) emits a ``stats``
    delta.  Both per-side breakdowns are diffed.  Deterministic: partitions are
    visited in ``str(key)`` order.  Total count is excluded (ADR-034 §6).
    """
    for side in ("source", "target"):
        left_rows = getattr(left, f"{side}_partitioned_cardinality") or []
        right_rows = getattr(right, f"{side}_partitioned_cardinality") or []
        left_by_key = {row.key: row for row in left_rows}
        right_by_key = {row.key: row for row in right_rows}
        for key in sorted(left_by_key.keys() | right_by_key.keys(), key=str):
            left_row = left_by_key.get(key)
            right_row = right_by_key.get(key)
            issue = _partition_delta(rt, side, left_row, right_row)
            if issue is not None:
                yield issue


def _partition_delta(
    rt: str,
    side: str,
    left_row: PartitionedCardinalityRow | None,
    right_row: PartitionedCardinalityRow | None,
) -> ValidationIssue | None:
    """Build the per-partition delta for one matched/unmatched (left, right) pair.

    At least one of ``left_row`` / ``right_row`` is non-``None`` (the caller only
    visits keys present on some side).
    """
    if right_row is None:
        assert left_row is not None
        return ValidationIssue(
            code="PARTITIONED_CARDINALITY_CHANGED",
            severity=Severity.INFO,
            entity_type=EntityType.RELATIONSHIP,
            entity_id=rt,
            message=(
                f"Relationship '{rt}' {side}-side partition {left_row.key} "
                "is present in left but not in right"
            ),
            context={"side": side, "change": "left_only", "key": str(left_row.key)},
        )
    if left_row is None:
        return ValidationIssue(
            code="PARTITIONED_CARDINALITY_CHANGED",
            severity=Severity.INFO,
            entity_type=EntityType.RELATIONSHIP,
            entity_id=rt,
            message=(
                f"Relationship '{rt}' {side}-side partition {right_row.key} "
                "is present in right but not in left"
            ),
            context={"side": side, "change": "right_only", "key": str(right_row.key)},
        )
    # Present on both sides: a delta only when the degree bounds differ.
    l_stats = left_row.stats
    r_stats = right_row.stats
    if l_stats.min == r_stats.min and l_stats.max == r_stats.max:
        return None
    return ValidationIssue(
        code="PARTITIONED_CARDINALITY_CHANGED",
        severity=Severity.INFO,
        entity_type=EntityType.RELATIONSHIP,
        entity_id=rt,
        message=(
            f"Relationship '{rt}' {side}-side partition {left_row.key} "
            f"cardinality differs: left min={l_stats.min} max={l_stats.max}, "
            f"right min={r_stats.min} max={r_stats.max}"
        ),
        context={
            "side": side,
            "change": "stats",
            "key": str(left_row.key),
            "left_min": l_stats.min,
            "left_max": l_stats.max,
            "right_min": r_stats.min,
            "right_max": r_stats.max,
        },
    )


def _cardinality_issue_definition(
    rt: str,
    left: type[RelationshipModel],
    right: type[RelationshipModel],
) -> ValidationIssue | None:
    """Return a CARDINALITY_CHANGED issue if source cardinalities differ, else None.

    When either side is a
    :class:`~orthograph.graph_definition.models.ConditionalCardinality`,
    structural equality (``==``) is used and the context omits ``.min``/``.max``
    keys (which do not exist on conditional specs).
    """
    l_card = left.source_cardinality()
    r_card = right.source_cardinality()
    if l_card == r_card:
        return None

    either_conditional = isinstance(l_card, ConditionalCardinality) or isinstance(
        r_card, ConditionalCardinality
    )

    if either_conditional:
        return ValidationIssue(
            code="CARDINALITY_CHANGED",
            severity=Severity.INFO,
            entity_type=EntityType.RELATIONSHIP,
            entity_id=rt,
            message=(
                f"Relationship '{rt}' source cardinality differs: "
                f"left={l_card!r} right={r_card!r}"
            ),
            context={},
        )

    # Both sides are constant CardinalitySpec — include min/max in context.
    l_spec = representative_spec(l_card)
    r_spec = representative_spec(r_card)
    return ValidationIssue(
        code="CARDINALITY_CHANGED",
        severity=Severity.INFO,
        entity_type=EntityType.RELATIONSHIP,
        entity_id=rt,
        message=(
            f"Relationship '{rt}' source cardinality differs: "
            f"left={l_card!r} right={r_card!r}"
        ),
        context={
            "left_min": l_spec.min,
            "left_max": l_spec.max,
            "right_min": r_spec.min,
            "right_max": r_spec.max,
        },
    )


# ---------------------------------------------------------------------------
# Node-label / rel-type "only in one operand" diff rules
#
# The four rules below share one shape: address-kind guard → present on *my*
# side and absent on the other → the address *is* the entity id, emit one INFO
# issue.  ``_only_on_side_issues`` holds that shape once; each thin rule supplies
# its address kind, the side it reports on, code, entity type, and message.
# ---------------------------------------------------------------------------

_LEFT = "left"
_RIGHT = "right"


def _only_on_side_issues(
    context: RuleContext,
    *,
    address_type: str,
    present_side: str,  # _LEFT / _RIGHT
    code: str,
    entity_type: EntityType,
    message_template: str,  # one ``{address}`` placeholder
) -> Iterable[ValidationIssue]:
    """Emit one INFO issue when the node-label/rel-type ``address`` is present on
    ``present_side`` and absent on the other."""
    if context.extra.get(ADDRESS_TYPE) != address_type:
        return  # not my address kind
    if present_side == _LEFT:
        present, absent = context.left, context.right
    else:
        present, absent = context.right, context.left
    if present is None or absent is not None:
        return  # not a one-sided presence on my side
    address: str = context.address
    yield ValidationIssue(
        code=code,
        severity=Severity.INFO,
        entity_type=entity_type,
        entity_id=address,
        message=message_template.format(address=address),
    )


# ---------------------------------------------------------------------------
# Node-label diff rules
# ---------------------------------------------------------------------------


@dataclass
class NodeLabelOnlyInLeftRule:
    """Emits ``NODE_LABEL_ONLY_IN_LEFT`` (INFO) when a node label is present in
    the left operand but absent from the right operand."""

    key: str = "diff.node_label.only_in_left"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        return _only_on_side_issues(
            context,
            address_type=ADDR_NODE_LABEL,
            present_side=_LEFT,
            code="NODE_LABEL_ONLY_IN_LEFT",
            entity_type=EntityType.NODE,
            message_template=(
                "Node label '{address}' is present in left but not in right"
            ),
        )


@dataclass
class NodeLabelOnlyInRightRule:
    """Emits ``NODE_LABEL_ONLY_IN_RIGHT`` (INFO) when a node label is present in
    the right operand but absent from the left operand."""

    key: str = "diff.node_label.only_in_right"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        return _only_on_side_issues(
            context,
            address_type=ADDR_NODE_LABEL,
            present_side=_RIGHT,
            code="NODE_LABEL_ONLY_IN_RIGHT",
            entity_type=EntityType.NODE,
            message_template=(
                "Node label '{address}' is present in right but not in left"
            ),
        )


# ---------------------------------------------------------------------------
# Relationship-type diff rules
# ---------------------------------------------------------------------------


@dataclass
class RelTypeOnlyInLeftRule:
    """Emits ``REL_TYPE_ONLY_IN_LEFT`` (INFO) when a relationship type is present
    in the left operand but absent from the right operand."""

    key: str = "diff.rel_type.only_in_left"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        return _only_on_side_issues(
            context,
            address_type=ADDR_REL_TYPE,
            present_side=_LEFT,
            code="REL_TYPE_ONLY_IN_LEFT",
            entity_type=EntityType.RELATIONSHIP,
            message_template=(
                "Relationship type '{address}' is present in left but not in right"
            ),
        )


@dataclass
class RelTypeOnlyInRightRule:
    """Emits ``REL_TYPE_ONLY_IN_RIGHT`` (INFO) when a relationship type is present
    in the right operand but absent from the left operand."""

    key: str = "diff.rel_type.only_in_right"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        return _only_on_side_issues(
            context,
            address_type=ADDR_REL_TYPE,
            present_side=_RIGHT,
            code="REL_TYPE_ONLY_IN_RIGHT",
            entity_type=EntityType.RELATIONSHIP,
            message_template=(
                "Relationship type '{address}' is present in right but not in left"
            ),
        )


# ---------------------------------------------------------------------------
# Property diff rules
# ---------------------------------------------------------------------------


@dataclass
class PropertyOnlyInLeftRule:
    """Emits ``PROPERTY_ONLY_IN_LEFT`` (INFO) when a property exists in the left
    operand but is absent from the right operand."""

    key: str = "diff.property.only_in_left"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if PROP_NAME not in context.extra:
            return
        if context.left is None or context.right is not None:
            return
        label: str = context.extra[LABEL]
        prop_name: str = context.extra[PROP_NAME]
        entity_type: EntityType = context.extra[ENTITY_TYPE]
        yield ValidationIssue(
            code="PROPERTY_ONLY_IN_LEFT",
            severity=Severity.INFO,
            entity_type=entity_type,
            entity_id=f"{label}.{prop_name}",
            message=(
                f"Property '{prop_name}' on {label} is present in left but not in right"
            ),
        )


@dataclass
class PropertyOnlyInRightRule:
    """Emits ``PROPERTY_ONLY_IN_RIGHT`` (INFO) when a property exists in the
    right operand but is absent from the left operand."""

    key: str = "diff.property.only_in_right"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if PROP_NAME not in context.extra:
            return
        if context.right is None or context.left is not None:
            return
        label: str = context.extra[LABEL]
        prop_name: str = context.extra[PROP_NAME]
        entity_type: EntityType = context.extra[ENTITY_TYPE]
        yield ValidationIssue(
            code="PROPERTY_ONLY_IN_RIGHT",
            severity=Severity.INFO,
            entity_type=entity_type,
            entity_id=f"{label}.{prop_name}",
            message=(
                f"Property '{prop_name}' on {label} is present in right but not in left"
            ),
        )


@dataclass
class PropertyTypeChangedRule:
    """Emits ``PROPERTY_TYPE_CHANGED`` (INFO) when both sides declare a property
    but the resolved Python type differs.

    Handles two operand shapes:

    - ``TypeInfo`` (definition ↔ definition): compare ``python_type`` directly.
    - ``PropertyProfile`` (profile ↔ profile): map ``observed_types`` through
      ``db_type_to_python`` and compare the resulting *sets* of Python types.

    Does **not** fire for mixed shapes (``TypeInfo`` vs ``PropertyProfile``) —
    that combination only arises in ``compare_profile_to_definition``, which
    uses ``standard_rules()``, not ``diff_rules()``.
    """

    key: str = "diff.property.type_changed"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if PROP_NAME not in context.extra:
            return
        if context.left is None or context.right is None:
            return

        left = context.left
        right = context.right

        if isinstance(left, TypeInfo) and isinstance(right, TypeInfo):
            resolved = _resolved_definition_types(left, right)
        elif isinstance(left, PropertyProfile) and isinstance(right, PropertyProfile):
            resolved = _resolved_profile_types(left, right)
        else:
            # Mixed shape — only arises in compare_profile_to_definition
            return

        if resolved is None:
            return

        left_desc, right_desc = resolved
        label: str = context.extra[LABEL]
        prop_name: str = context.extra[PROP_NAME]
        entity_type: EntityType = context.extra[ENTITY_TYPE]
        yield ValidationIssue(
            code="PROPERTY_TYPE_CHANGED",
            severity=Severity.INFO,
            entity_type=entity_type,
            entity_id=f"{label}.{prop_name}",
            message=(
                f"Property '{prop_name}' on {label} "
                f"has type {left_desc!r} in left "
                f"and {right_desc!r} in right"
            ),
            context={"left": left_desc, "right": right_desc},
        )


# ---------------------------------------------------------------------------
# Endpoint / cardinality diff rules
# ---------------------------------------------------------------------------


@dataclass
class EndpointsChangedRule:
    """Emits ``ENDPOINTS_CHANGED`` (INFO) when two definition operands share a
    relationship-type identity but differ in the ``__directed__`` flag.

    Source/target labels are part of relationship *identity* (the
    address), so an endpoint difference is a different address and surfaces via
    the presence rules (``REL_TYPE_ONLY_IN_LEFT`` / ``..._RIGHT``) — never here.
    Direction (``__directed__``) is the only endpoint-related *attribute* left to
    compare, and only the declared side carries it:

    - ``RelationshipModel`` subclass ↔ ``RelationshipModel`` subclass
      (definition ↔ definition): compare ``__directed__``.
    - ``RelationshipTypeProfile`` ↔ ``RelationshipTypeProfile``: silent — the
      profile carries no direction field and its endpoints are identity.
    """

    key: str = "diff.rel.endpoints_changed"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if context.extra.get(ADDRESS_TYPE) != ADDR_REL_TYPE:
            return
        if context.left is None or context.right is None:
            return

        rt: str = context.address
        kind = _rel_operand_kind(context.left, context.right)
        if kind == "definition":
            yield from _endpoint_issues_definition(rt, context.left, context.right)


@dataclass
class CardinalityChangedRule:
    """Emits ``CARDINALITY_CHANGED`` (INFO) when both sides define a relationship
    type but cardinality information differs.

    Handles:

    - ``RelationshipTypeProfile`` ↔ ``RelationshipTypeProfile``: compare
      ``cardinality_stats.min`` / ``max``; skips when either
      ``cardinality_stats`` is ``None``.
    - ``RelationshipModel`` subclass ↔ ``RelationshipModel`` subclass: compare
      ``__source_cardinality__``; skips when both are the default
      ``ZERO_OR_MORE``.
    """

    key: str = "diff.rel.cardinality_changed"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if context.extra.get(ADDRESS_TYPE) != ADDR_REL_TYPE:
            return
        if context.left is None or context.right is None:
            return

        rt: str = context.address
        kind = _rel_operand_kind(context.left, context.right)
        if kind == "profile":
            issue = _cardinality_issue_profile(rt, context.left, context.right)
        elif kind == "definition":
            issue = _cardinality_issue_definition(rt, context.left, context.right)
        else:
            return
        if issue is not None:
            yield issue


@dataclass
class PartitionedCardinalityChangedRule:
    """Emits ``PARTITIONED_CARDINALITY_CHANGED`` (INFO) per differing partition.

    Profile ↔ profile only: matches the per-side partitioned-cardinality rows of
    two :class:`RelationshipTypeProfile` operands by :class:`PartitionKey` **map
    equality**, so partitions discriminating different properties no longer
    collide (``{"type": ...}`` ≠ ``{"stage": ...}``).  A partition present on one
    side only, or with differing degree ``stats``, emits a per-partition delta.
    Definition operands carry no observed breakdown, so the rule is silent for
    them.  Closes the profile↔profile partition row of ADR-034 §8 honestly.
    """

    key: str = "diff.rel.partitioned_cardinality_changed"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if context.extra.get(ADDRESS_TYPE) != ADDR_REL_TYPE:
            return
        if context.left is None or context.right is None:
            return
        if _rel_operand_kind(context.left, context.right) != "profile":
            return
        yield from _partitioned_cardinality_issues_profile(
            context.address, context.left, context.right
        )


@dataclass
class CountChangedRule:
    """Emits ``COUNT_CHANGED`` (INFO) when both sides observe a node label or
    relationship type but the entity ``count`` differs.

    Total count is **diff-only**: it never participates in profile↔description
    comparison.  It applies only to :class:`NodeTypeProfile` /
    :class:`RelationshipTypeProfile` operands — definition operands carry no
    observed count, so the rule is silent for them.
    """

    key: str = "diff.count_changed"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        address_type = context.extra.get(ADDRESS_TYPE)
        if address_type not in (ADDR_NODE_LABEL, ADDR_REL_TYPE):
            return  # only the type-level addresses carry a total count
        # Both operands must be the profile class matching the address; this
        # keeps the rule self-contained and rejects any node/rel mix.
        expected = (
            NodeTypeProfile
            if address_type == ADDR_NODE_LABEL
            else RelationshipTypeProfile
        )
        left = context.left
        right = context.right
        if not isinstance(left, expected) or not isinstance(right, expected):
            return
        if left.count == right.count:
            return

        entity_type = (
            EntityType.NODE
            if address_type == ADDR_NODE_LABEL
            else EntityType.RELATIONSHIP
        )
        kind = "Node label" if address_type == ADDR_NODE_LABEL else "Relationship type"
        yield ValidationIssue(
            code="COUNT_CHANGED",
            severity=Severity.INFO,
            entity_type=entity_type,
            entity_id=context.address,
            message=(
                f"{kind} '{context.address}' count differs: "
                f"left={left.count} right={right.count}"
            ),
            context={"left": left.count, "right": right.count},
        )


# ---------------------------------------------------------------------------
# Diff rule set factory
# ---------------------------------------------------------------------------


def diff_rules() -> list[Rule]:
    """Return the ordered symmetric diff rule list."""
    return [
        NodeLabelOnlyInLeftRule(),
        NodeLabelOnlyInRightRule(),
        RelTypeOnlyInLeftRule(),
        RelTypeOnlyInRightRule(),
        PropertyOnlyInLeftRule(),
        PropertyOnlyInRightRule(),
        PropertyTypeChangedRule(),
        EndpointsChangedRule(),
        CardinalityChangedRule(),
        PartitionedCardinalityChangedRule(),
        CountChangedRule(),
    ]
