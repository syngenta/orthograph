"""Symmetric diff rule family for the comparison engine.

Each rule implements the :class:`~orthograph.comparison.rules.Rule` Protocol,
reads ``context.left`` / ``context.right`` symmetrically, and emits only
``Severity.INFO`` issues.

This module is created in E27.T4.  The :func:`diff_rules` factory is
imported by :mod:`orthograph.comparison.engine` for
:func:`~orthograph.comparison.engine.compare_profiles` and
:func:`~orthograph.comparison.engine.compare_definitions`.

Two questions, two rule families (per E27 spec):

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
# Endpoint helpers (profile ↔ profile)
# ---------------------------------------------------------------------------


def _endpoint_issues_profile(
    rt: str,
    left: RelationshipTypeProfile,
    right: RelationshipTypeProfile,
) -> Iterable[ValidationIssue]:
    """Yield ENDPOINTS_CHANGED issues for a profile ↔ profile comparison."""
    for role, left_labels, right_labels in (
        ("source", left.source_labels, right.source_labels),
        ("target", left.target_labels, right.target_labels),
    ):
        if left_labels != right_labels:
            yield ValidationIssue(
                code="ENDPOINTS_CHANGED",
                severity=Severity.INFO,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=rt,
                message=(
                    f"Relationship '{rt}' {role} labels differ: "
                    f"left={sorted(left_labels)} right={sorted(right_labels)}"
                ),
                context={
                    "role": role,
                    "left": sorted(left_labels),
                    "right": sorted(right_labels),
                },
            )


def _endpoint_issues_definition(
    rt: str,
    left: type[RelationshipModel],
    right: type[RelationshipModel],
) -> Iterable[ValidationIssue]:
    """Yield ENDPOINTS_CHANGED issues for a definition ↔ definition comparison."""
    for role, left_val, right_val in (
        ("source", left.__source_label__, right.__source_label__),
        ("target", left.__target_label__, right.__target_label__),
        ("directed", left.__directed__, right.__directed__),
    ):
        if left_val != right_val:
            yield ValidationIssue(
                code="ENDPOINTS_CHANGED",
                severity=Severity.INFO,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=rt,
                message=(
                    f"Relationship '{rt}' {role} "
                    f"{'label' if role != 'directed' else 'flag'} differs: "
                    f"left={left_val!r} right={right_val!r}"
                ),
                context={"role": role, "left": left_val, "right": right_val},
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
    if (
        l_stats.min_degree == r_stats.min_degree
        and l_stats.max_degree == r_stats.max_degree
    ):
        return None
    return ValidationIssue(
        code="CARDINALITY_CHANGED",
        severity=Severity.INFO,
        entity_type=EntityType.RELATIONSHIP,
        entity_id=rt,
        message=(
            f"Relationship '{rt}' cardinality differs: "
            f"left min={l_stats.min_degree} max={l_stats.max_degree}, "
            f"right min={r_stats.min_degree} max={r_stats.max_degree}"
        ),
        context={
            "left_min": l_stats.min_degree,
            "left_max": l_stats.max_degree,
            "right_min": r_stats.min_degree,
            "right_max": r_stats.max_degree,
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
    """Emits ``ENDPOINTS_CHANGED`` (INFO) when both sides define a relationship
    type but the source or target label sets differ.

    Handles:

    - ``RelationshipTypeProfile`` ↔ ``RelationshipTypeProfile``  (profile ↔ profile):
      compare ``source_labels`` and ``target_labels``.
    - ``RelationshipModel`` subclass ↔ ``RelationshipModel`` subclass
      (definition ↔ definition): compare ``__source_label__``, ``__target_label__``,
      and ``__directed__``.
    """

    key: str = "diff.rel.endpoints_changed"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        if context.extra.get("address_type") != "rel_type":
            return
        if context.left is None or context.right is None:
            return

        rt: str = context.address
        kind = _rel_operand_kind(context.left, context.right)
        if kind == "profile":
            yield from _endpoint_issues_profile(rt, context.left, context.right)
        elif kind == "definition":
            yield from _endpoint_issues_definition(rt, context.left, context.right)


@dataclass
class CardinalityChangedRule:
    """Emits ``CARDINALITY_CHANGED`` (INFO) when both sides define a relationship
    type but cardinality information differs.

    Handles:

    - ``RelationshipTypeProfile`` ↔ ``RelationshipTypeProfile``: compare
      ``cardinality_stats.min_degree`` / ``max_degree``; skips when either
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
    ]
