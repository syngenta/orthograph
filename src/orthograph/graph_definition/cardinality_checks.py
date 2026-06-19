"""Definition-time checks for ConditionalCardinality rule sets.

Each check is a dataclass implementing the :class:`RuleSetCheck` Protocol.
:func:`standard_cardinality_checks` returns the ordered standard list.

Extend by appending additional :class:`RuleSetCheck` implementations to a
custom list and passing it to ``GraphDefinition`` (E41+).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue
from orthograph.graph_definition.models import (
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
)


@runtime_checkable
class RuleSetCheck(Protocol):
    """Protocol for a single definition-time cardinality check.

    ``code`` : str
        Stable issue code emitted when the check fails.

    ``__call__(rel_label, side, card, self_node, other_node)``
        Run the check.  Return an empty iterable when satisfied; yield
        issues otherwise.  ``side`` is ``"source"`` or ``"target"``.

        Absolute convention (ADR-032 §1a): ``self_node`` is always the
        relationship's **source-label** node and ``other_node`` the
        **target-label** node, for both sides — so ``rule.source`` predicates are
        validated against ``self_node`` and ``rule.target`` against ``other_node``
        regardless of which cardinality side is being checked.
    """

    code: str

    def __call__(
        self,
        rel_label: str,
        side: str,
        card: ConditionalCardinality,
        self_node: type[NodeModel],
        other_node: type[NodeModel],
    ) -> Iterable[ValidationIssue]: ...


# ---------------------------------------------------------------------------
# Helpers shared across checks
# ---------------------------------------------------------------------------


def _can_comatch(a: ConditionalRule, b: ConditionalRule) -> bool:
    """Return True when rules *a* and *b* can simultaneously match the same pair.

    Two rules cannot co-match when either endpoint's predicate maps the same key
    to different values — the pair cannot satisfy both conditions at once.
    Otherwise they can co-match (keys absent on one side impose no constraint).
    """
    for key, val_a in a.source.conditions.items():
        if key in b.source.conditions and b.source.conditions[key] != val_a:
            return False
    for key, val_a in a.target.conditions.items():
        if key in b.target.conditions and b.target.conditions[key] != val_a:
            return False
    return True


def _same_specificity(a: ConditionalRule, b: ConditionalRule) -> bool:
    """Return True when rules *a* and *b* share the same combined specificity score."""
    return (a.source.specificity + a.target.specificity) == (
        b.source.specificity + b.target.specificity
    )


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------


@dataclass
class DiscriminatorPropertyExistsCheck:
    """Reject rules that key on property names not declared on the relevant node.

    Emits ``CARDINALITY_UNKNOWN_DISCRIMINATOR`` for every unknown key.
    """

    code: str = "CARDINALITY_UNKNOWN_DISCRIMINATOR"

    def __call__(
        self,
        rel_label: str,
        side: str,
        card: ConditionalCardinality,
        self_node: type[NodeModel],
        other_node: type[NodeModel],
    ) -> Iterable[ValidationIssue]:
        self_props = self_node.get_all_property_names()
        other_props = other_node.get_all_property_names()

        for rule in card.rules:
            for key in rule.source.conditions:
                if key not in self_props:
                    yield ValidationIssue(
                        code=self.code,
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=rel_label,
                        message=(
                            f"{rel_label} {side} cardinality discriminates on "
                            f"{self_node.__name__}.{key}, but {key!r} is not a "
                            f"declared property of {self_node.__name__}."
                        ),
                        context={"side": side, "node": self_node.__name__, "key": key},
                    )
            for key in rule.target.conditions:
                if key not in other_props:
                    yield ValidationIssue(
                        code=self.code,
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=rel_label,
                        message=(
                            f"{rel_label} {side} cardinality discriminates on "
                            f"{other_node.__name__}.{key}, but {key!r} is not a "
                            f"declared property of {other_node.__name__}."
                        ),
                        context={"side": side, "node": other_node.__name__, "key": key},
                    )


@dataclass
class DiscriminatorRequiredCheck:
    """Reject rules that key on optional (nullable) properties.

    Emits ``CARDINALITY_DISCRIMINATOR_OPTIONAL`` for every optional discriminator key.
    """

    code: str = "CARDINALITY_DISCRIMINATOR_OPTIONAL"

    def __call__(
        self,
        rel_label: str,
        side: str,
        card: ConditionalCardinality,
        self_node: type[NodeModel],
        other_node: type[NodeModel],
    ) -> Iterable[ValidationIssue]:
        self_required = self_node.get_required_property_names()
        other_required = other_node.get_required_property_names()

        # Collect all unique discriminator keys used across all rules per endpoint
        self_keys: set[str] = set()
        other_keys: set[str] = set()
        for rule in card.rules:
            self_keys.update(rule.source.conditions)
            other_keys.update(rule.target.conditions)

        for key in self_keys:
            if key not in self_required:
                yield ValidationIssue(
                    code=self.code,
                    severity=Severity.ERROR,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rel_label,
                    message=(
                        f"{rel_label} {side} cardinality discriminates on "
                        f"{self_node.__name__}.{key}, but {key} is optional "
                        f"(nullable); make it required or remove the rule."
                    ),
                    context={"side": side, "node": self_node.__name__, "key": key},
                )
        for key in other_keys:
            if key not in other_required:
                yield ValidationIssue(
                    code=self.code,
                    severity=Severity.ERROR,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rel_label,
                    message=(
                        f"{rel_label} {side} cardinality discriminates on "
                        f"{other_node.__name__}.{key}, but {key} is optional "
                        f"(nullable); make it required or remove the rule."
                    ),
                    context={"side": side, "node": other_node.__name__, "key": key},
                )


@dataclass
class DuplicateRuleKeyCheck:
    """Reject two rules with identical (source.conditions, target.conditions).

    Emits ``CARDINALITY_DUPLICATE_RULE``.
    """

    code: str = "CARDINALITY_DUPLICATE_RULE"

    def __call__(
        self,
        rel_label: str,
        side: str,
        card: ConditionalCardinality,
        self_node: type[NodeModel],
        other_node: type[NodeModel],
    ) -> Iterable[ValidationIssue]:
        seen: list[tuple[dict[str, object], dict[str, object]]] = []
        for rule in card.rules:
            key = (dict(rule.source.conditions), dict(rule.target.conditions))
            if key in seen:
                yield ValidationIssue(
                    code=self.code,
                    severity=Severity.ERROR,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rel_label,
                    message=(
                        f"{rel_label} {side} cardinality has duplicate rule "
                        f"for predicates source={dict(rule.source.conditions)!r} "
                        f"target={dict(rule.target.conditions)!r}."
                    ),
                    context={
                        "side": side,
                        "source_conditions": dict(rule.source.conditions),
                        "target_conditions": dict(rule.target.conditions),
                    },
                )
            else:
                seen.append(key)


@dataclass
class AmbiguousOverlapCheck:
    """Reject rule pairs that can co-match and share equal specificity.

    Emits ``CARDINALITY_AMBIGUOUS_RULES``.
    Narrow-overrides-broad (unequal specificity) is intentional and not flagged.
    """

    code: str = "CARDINALITY_AMBIGUOUS_RULES"

    def __call__(
        self,
        rel_label: str,
        side: str,
        card: ConditionalCardinality,
        self_node: type[NodeModel],
        other_node: type[NodeModel],
    ) -> Iterable[ValidationIssue]:
        rules = card.rules
        for i, a in enumerate(rules):
            for b in rules[i + 1 :]:
                if _same_specificity(a, b) and _can_comatch(a, b):
                    yield ValidationIssue(
                        code=self.code,
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=rel_label,
                        message=(
                            f"{rel_label} {side} cardinality has ambiguous rules "
                            f"of equal specificity that can co-match: "
                            f"source={dict(a.source.conditions)!r}/"
                            f"target={dict(a.target.conditions)!r} vs "
                            f"source={dict(b.source.conditions)!r}/"
                            f"target={dict(b.target.conditions)!r}."
                        ),
                        context={
                            "side": side,
                            "rule_a": {
                                "source": dict(a.source.conditions),
                                "target": dict(a.target.conditions),
                            },
                            "rule_b": {
                                "source": dict(b.source.conditions),
                                "target": dict(b.target.conditions),
                            },
                        },
                    )


@dataclass
class ForbiddenCatchAllRuleCheck:
    """Reject any rule whose source and target are both wildcards (match-all).

    Emits ``CARDINALITY_CATCHALL_RULE``.  Use ``default`` instead.
    """

    code: str = "CARDINALITY_CATCHALL_RULE"

    def __call__(
        self,
        rel_label: str,
        side: str,
        card: ConditionalCardinality,
        self_node: type[NodeModel],
        other_node: type[NodeModel],
    ) -> Iterable[ValidationIssue]:
        for rule in card.rules:
            if rule.source.is_wildcard and rule.target.is_wildcard:
                yield ValidationIssue(
                    code=self.code,
                    severity=Severity.ERROR,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=rel_label,
                    message=(
                        f"{rel_label} {side} cardinality contains a (*, *) "
                        f"catch-all rule. Use 'default' instead."
                    ),
                    context={"side": side},
                )


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def standard_cardinality_checks() -> list[RuleSetCheck]:
    """Return the ordered standard list of definition-time cardinality checks."""
    return [
        DiscriminatorPropertyExistsCheck(),
        DiscriminatorRequiredCheck(),
        DuplicateRuleKeyCheck(),
        AmbiguousOverlapCheck(),
        ForbiddenCatchAllRuleCheck(),
    ]
