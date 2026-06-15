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

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from orthograph.comparison.rules import Rule, RuleContext
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue


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

        from orthograph.comparison.engine import db_type_to_python
        from orthograph.graph_definition.property_spec import TypeInfo
        from orthograph.graph_profile.models import PropertyProfile

        left = context.left
        right = context.right

        # Definition ↔ definition: both sides are TypeInfo
        if isinstance(left, TypeInfo) and isinstance(right, TypeInfo):
            if left.python_type is right.python_type:
                return
            left_desc: object = left.python_type
            right_desc: object = right.python_type

        # Profile ↔ profile: both sides are PropertyProfile
        elif isinstance(left, PropertyProfile) and isinstance(right, PropertyProfile):
            left_types = {
                (m if (m := db_type_to_python(t)) is not None else t)
                for t in left.observed_types
            }
            right_types = {
                (m if (m := db_type_to_python(t)) is not None else t)
                for t in right.observed_types
            }
            # Skip if either descriptor is empty (no type information)
            if not left_types or not right_types:
                return
            if left_types == right_types:
                return
            left_desc = left_types
            right_desc = right_types

        else:
            # Mixed shape — skip (only arises in compare_profile_to_definition)
            return

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

        from orthograph.graph_definition.models import RelationshipModel
        from orthograph.graph_profile.models import RelationshipTypeProfile

        left = context.left
        right = context.right
        rt: str = context.address

        # Profile ↔ profile
        if isinstance(left, RelationshipTypeProfile) and isinstance(
            right, RelationshipTypeProfile
        ):
            if left.source_labels != right.source_labels:
                yield ValidationIssue(
                    code="ENDPOINTS_CHANGED",
                    severity=Severity.INFO,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rt,
                    message=(
                        f"Relationship '{rt}' source labels differ: "
                        f"left={sorted(left.source_labels)} "
                        f"right={sorted(right.source_labels)}"
                    ),
                    context={
                        "role": "source",
                        "left": sorted(left.source_labels),
                        "right": sorted(right.source_labels),
                    },
                )
            if left.target_labels != right.target_labels:
                yield ValidationIssue(
                    code="ENDPOINTS_CHANGED",
                    severity=Severity.INFO,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rt,
                    message=(
                        f"Relationship '{rt}' target labels differ: "
                        f"left={sorted(left.target_labels)} "
                        f"right={sorted(right.target_labels)}"
                    ),
                    context={
                        "role": "target",
                        "left": sorted(left.target_labels),
                        "right": sorted(right.target_labels),
                    },
                )
            return

        # Definition ↔ definition
        if (
            isinstance(left, type)
            and issubclass(left, RelationshipModel)
            and isinstance(right, type)
            and issubclass(right, RelationshipModel)
        ):
            if left.__source_label__ != right.__source_label__:
                yield ValidationIssue(
                    code="ENDPOINTS_CHANGED",
                    severity=Severity.INFO,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rt,
                    message=(
                        f"Relationship '{rt}' source label differs: "
                        f"left='{left.__source_label__}' "
                        f"right='{right.__source_label__}'"
                    ),
                    context={
                        "role": "source",
                        "left": left.__source_label__,
                        "right": right.__source_label__,
                    },
                )
            if left.__target_label__ != right.__target_label__:
                yield ValidationIssue(
                    code="ENDPOINTS_CHANGED",
                    severity=Severity.INFO,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rt,
                    message=(
                        f"Relationship '{rt}' target label differs: "
                        f"left='{left.__target_label__}' "
                        f"right='{right.__target_label__}'"
                    ),
                    context={
                        "role": "target",
                        "left": left.__target_label__,
                        "right": right.__target_label__,
                    },
                )
            if left.__directed__ != right.__directed__:
                yield ValidationIssue(
                    code="ENDPOINTS_CHANGED",
                    severity=Severity.INFO,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rt,
                    message=(
                        f"Relationship '{rt}' directed flag differs: "
                        f"left={left.__directed__} right={right.__directed__}"
                    ),
                    context={
                        "role": "directed",
                        "left": left.__directed__,
                        "right": right.__directed__,
                    },
                )


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

        from orthograph.graph_definition.models import RelationshipModel
        from orthograph.graph_profile.models import RelationshipTypeProfile

        left = context.left
        right = context.right
        rt: str = context.address

        # Profile ↔ profile
        if isinstance(left, RelationshipTypeProfile) and isinstance(
            right, RelationshipTypeProfile
        ):
            if left.cardinality_stats is None or right.cardinality_stats is None:
                return
            l_stats = left.cardinality_stats
            r_stats = right.cardinality_stats
            if (
                l_stats.min_degree != r_stats.min_degree
                or l_stats.max_degree != r_stats.max_degree
            ):
                yield ValidationIssue(
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
            return

        # Definition ↔ definition
        if (
            isinstance(left, type)
            and issubclass(left, RelationshipModel)
            and isinstance(right, type)
            and issubclass(right, RelationshipModel)
        ):
            l_card = left.__source_cardinality__
            r_card = right.__source_cardinality__
            if l_card != r_card:
                yield ValidationIssue(
                    code="CARDINALITY_CHANGED",
                    severity=Severity.INFO,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rt,
                    message=(
                        f"Relationship '{rt}' source cardinality differs: "
                        f"left={l_card!r} right={r_card!r}"
                    ),
                    context={
                        "left_min": l_card.min,
                        "left_max": l_card.max,
                        "right_min": r_card.min,
                        "right_max": r_card.max,
                    },
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
    ]
