"""Symmetric diff rule family for the comparison engine.

Each rule implements the :class:`~orthograph.comparison.rules.Rule` Protocol,
reads ``context.left`` / ``context.right`` symmetrically, and emits only
``Severity.INFO`` issues.

This module implements the symmetric diff rules.

Two questions, two rule families:

- **Satisfaction** (profile ↔ definition): ``standard_rules()`` — asymmetric,
  uses left=declared/right=observed semantics, emits ERROR/WARNING/INFO.
- **Diff** (profile ↔ profile, definition ↔ definition): ``diff_rules()`` —
  symmetric, neutral left/right semantics, emits INFO only.

Address conventions (set by the engine, same as ``rules.py``):

- Node-label address  : ``extra["address_type"] == "node_label"``; ``left``/
  ``right`` are ``NodeTypeProfile`` or ``NodeModel`` subclass (or ``None``).
- Rel-type address    : ``extra["address_type"] == "rel_type"``; same shape
  with ``RelationshipTypeProfile`` or ``RelationshipModel`` subclass.
- Property address    : ``extra["prop_name"]`` present; ``left``/``right`` are
  ``TypeInfo`` (definition) or ``PropertyProfile`` (profile), or ``None``.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from orthograph.comparison.rules import Rule, RuleContext
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue
from orthograph.graph_definition.models import RelationshipModel, representative_spec
from orthograph.graph_definition.property_spec import TypeInfo
from orthograph.graph_profile.models import PropertyProfile, RelationshipTypeProfile


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
    """Return (left_types, right_types) as sets if they differ, else None.

    Imports ``db_type_to_python`` lazily to avoid a circular dependency at
    module load time.
    """
    from orthograph.comparison.engine import db_type_to_python

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
    from orthograph.graph_definition.models import ConditionalCardinality

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
# Node-label diff rules
# ---------------------------------------------------------------------------


@dataclass
class NodeLabelOnlyInLeftRule:
    """Emits ``NODE_LABEL_ONLY_IN_LEFT`` (INFO) when a node label is present in
    the left operand but absent from the right operand."""

    key: str = "diff.node_label.only_in_left"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if context.extra.get("address_type") != "node_label":
            return
        if context.left is None or context.right is not None:
            return
        label: str = context.address
        yield ValidationIssue(
            code="NODE_LABEL_ONLY_IN_LEFT",
            severity=Severity.INFO,
            entity_type=EntityType.NODE,
            entity_id=label,
            message=f"Node label '{label}' is present in left but not in right",
        )


@dataclass
class NodeLabelOnlyInRightRule:
    """Emits ``NODE_LABEL_ONLY_IN_RIGHT`` (INFO) when a node label is present in
    the right operand but absent from the left operand."""

    key: str = "diff.node_label.only_in_right"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if context.extra.get("address_type") != "node_label":
            return
        if context.right is None or context.left is not None:
            return
        label: str = context.address
        yield ValidationIssue(
            code="NODE_LABEL_ONLY_IN_RIGHT",
            severity=Severity.INFO,
            entity_type=EntityType.NODE,
            entity_id=label,
            message=f"Node label '{label}' is present in right but not in left",
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
        if context.extra.get("address_type") != "rel_type":
            return
        if context.left is None or context.right is not None:
            return
        rt: str = context.address
        yield ValidationIssue(
            code="REL_TYPE_ONLY_IN_LEFT",
            severity=Severity.INFO,
            entity_type=EntityType.RELATIONSHIP,
            entity_id=rt,
            message=f"Relationship type '{rt}' is present in left but not in right",
        )


@dataclass
class RelTypeOnlyInRightRule:
    """Emits ``REL_TYPE_ONLY_IN_RIGHT`` (INFO) when a relationship type is present
    in the right operand but absent from the left operand."""

    key: str = "diff.rel_type.only_in_right"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if context.extra.get("address_type") != "rel_type":
            return
        if context.right is None or context.left is not None:
            return
        rt: str = context.address
        yield ValidationIssue(
            code="REL_TYPE_ONLY_IN_RIGHT",
            severity=Severity.INFO,
            entity_type=EntityType.RELATIONSHIP,
            entity_id=rt,
            message=f"Relationship type '{rt}' is present in right but not in left",
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
        if "prop_name" not in context.extra:
            return
        if context.left is None or context.right is not None:
            return
        label: str = context.extra["label"]
        prop_name: str = context.extra["prop_name"]
        entity_type: EntityType = context.extra["entity_type"]
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
        if "prop_name" not in context.extra:
            return
        if context.right is None or context.left is not None:
            return
        label: str = context.extra["label"]
        prop_name: str = context.extra["prop_name"]
        entity_type: EntityType = context.extra["entity_type"]
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
        if "prop_name" not in context.extra:
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
        label: str = context.extra["label"]
        prop_name: str = context.extra["prop_name"]
        entity_type: EntityType = context.extra["entity_type"]
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
        if context.extra.get("address_type") != "rel_type":
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
        if context.extra.get("address_type") != "rel_type":
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
        from orthograph.graph_profile.models import (
            NodeTypeProfile,
            RelationshipTypeProfile,
        )

        address_type = context.extra.get("address_type")
        if address_type not in ("node_label", "rel_type"):
            return  # only the type-level addresses carry a total count
        # Both operands must be the profile class matching the address; this
        # keeps the rule self-contained and rejects any node/rel mix.
        expected = (
            NodeTypeProfile if address_type == "node_label" else RelationshipTypeProfile
        )
        left = context.left
        right = context.right
        if not isinstance(left, expected) or not isinstance(right, expected):
            return
        if left.count == right.count:
            return

        entity_type = (
            EntityType.NODE if address_type == "node_label" else EntityType.RELATIONSHIP
        )
        kind = "Node label" if address_type == "node_label" else "Relationship type"
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
        CountChangedRule(),
    ]
