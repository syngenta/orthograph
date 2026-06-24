"""Unit tests for the Rule abstraction and standard rule set.

C1 tests cover:
* RuleContext construction and field access.
* The Rule Protocol — isinstance check via runtime_checkable.
* A minimal concrete rule satisfies the Protocol and produces issues.
* A rule that yields no issues when the constraint is satisfied.
* RuleContext defaults (left/right None, extra empty dict).

C2 tests cover:
* Each standard rule emits the exact code + severity as its legacy _check_*
  counterpart (hard constraint).
* Satisfaction path: rule emits no issues when constraint is met.
* standard_rules() returns all ten rule instances in order.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import pytest

from orthograph.comparison.rules import (
    CardinalityViolationRule,
    InvalidEndpointRule,
    MissingNodeLabelRule,
    MissingPropertyRule,
    MissingRelTypeRule,
    PropertyConstraintPresenceRule,
    PropertyEnumValueRule,
    PropertyIncompleteRule,
    PropertyTypeMismatchRule,
    Rule,
    RuleContext,
    UnexpectedNodeLabelRule,
    UnexpectedPropertyRule,
    UnexpectedRelTypeRule,
    standard_rules,
)
from orthograph.comparison.views import DefinitionView, ProfileView
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
    RelationshipModel,
)
from orthograph.graph_definition.property_spec import TypeInfo
from orthograph.graph_profile.models import (
    BoundedDistribution,
    CardinalityStats,
    GraphProfile,
    NodeTypeProfile,
    PartitionKey,
    PropertyProfile,
    RelationshipTypeProfile,
)


# ---------------------------------------------------------------------------
# Minimal model + profile for context construction
# ---------------------------------------------------------------------------


class _ANode(NodeModel):
    __label__ = "A"
    name: str


_MODEL = GraphDefinition(name="test", node_types=[_ANode], relationship_types=[])
_PROFILE = GraphProfile(
    source="test",
    node_type_profiles={
        "A": NodeTypeProfile(label="A", count=1),
    },
)


# ---------------------------------------------------------------------------
# Helpers — minimal concrete Rule implementations
# ---------------------------------------------------------------------------


@dataclass
class _AlwaysPassRule:
    """A rule that never emits issues."""

    key: str = "test.always_pass"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        return []


@dataclass
class _AlwaysFailRule:
    """A rule that always emits one issue regardless of context."""

    key: str = "test.always_fail"

    def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
        yield ValidationIssue(
            code="TEST_FAILURE",
            severity=Severity.ERROR,
            entity_type=EntityType.NODE,
            entity_id=context.address,
            message=f"Rule '{self.key}' always fails at '{context.address}'",
        )


# ---------------------------------------------------------------------------
# RuleContext tests
# ---------------------------------------------------------------------------


def test_rule_context_fields():
    ctx = RuleContext(
        left_graph=DefinitionView(_MODEL),
        right_graph=ProfileView(_PROFILE),
        address="A",
        left=_ANode,
        right=_PROFILE.node_type_profiles["A"],
    )
    assert ctx.address == "A"
    assert ctx.left is _ANode
    assert ctx.right is _PROFILE.node_type_profiles["A"]
    assert isinstance(ctx.left_graph, DefinitionView)
    assert isinstance(ctx.right_graph, ProfileView)


def test_rule_context_defaults():
    ctx = RuleContext(
        left_graph=DefinitionView(_MODEL),
        right_graph=ProfileView(_PROFILE),
        address="missing_label",
    )
    assert ctx.left is None
    assert ctx.right is None
    assert ctx.extra == {}


def test_rule_context_extra():
    ctx = RuleContext(
        left_graph=DefinitionView(_MODEL),
        right_graph=ProfileView(_PROFILE),
        address="A",
        extra={"hint": "value"},
    )
    assert ctx.extra == {"hint": "value"}


def test_rule_context_is_frozen():
    ctx = RuleContext(
        left_graph=DefinitionView(_MODEL),
        right_graph=ProfileView(_PROFILE),
        address="A",
    )
    with pytest.raises((AttributeError, TypeError)):
        ctx.address = "B"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Rule Protocol — isinstance check
# ---------------------------------------------------------------------------


def test_always_pass_rule_satisfies_protocol():
    rule = _AlwaysPassRule()
    assert isinstance(rule, Rule)


def test_always_fail_rule_satisfies_protocol():
    rule = _AlwaysFailRule()
    assert isinstance(rule, Rule)


def test_object_without_key_does_not_satisfy_protocol():
    """An object with __call__ but no key attribute does not satisfy Rule."""

    class _NoKey:
        def __call__(self, context: RuleContext) -> Iterable[ValidationIssue]:
            return []

    # runtime_checkable only checks for __call__ and key attribute presence
    # at isinstance time — _NoKey has no 'key' attribute so it fails
    assert not isinstance(_NoKey(), Rule)


# ---------------------------------------------------------------------------
# Rule behaviour tests
# ---------------------------------------------------------------------------


def test_always_pass_rule_emits_no_issues():
    rule = _AlwaysPassRule()
    ctx = RuleContext(
        left_graph=DefinitionView(_MODEL),
        right_graph=ProfileView(_PROFILE),
        address="A",
    )
    issues = list(rule(ctx))
    assert issues == []


def test_always_fail_rule_emits_one_issue():
    rule = _AlwaysFailRule()
    ctx = RuleContext(
        left_graph=DefinitionView(_MODEL),
        right_graph=ProfileView(_PROFILE),
        address="X",
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "TEST_FAILURE"
    assert issues[0].severity == Severity.ERROR
    assert issues[0].entity_id == "X"


def test_rule_key_is_accessible():
    rule = _AlwaysFailRule(key="custom.key")
    assert rule.key == "custom.key"


def test_rule_produces_validation_issue_instances():
    rule = _AlwaysFailRule()
    ctx = RuleContext(
        left_graph=DefinitionView(_MODEL),
        right_graph=ProfileView(_PROFILE),
        address="A",
    )
    for issue in rule(ctx):
        assert isinstance(issue, ValidationIssue)


# ===========================================================================
# C2 — Standard rule set tests
#
# Each test asserts:
#   (a) the rule emits the exact code + severity as the legacy _check_*
#   (b) the rule emits nothing when the constraint is satisfied
# ===========================================================================


# ---------------------------------------------------------------------------
# Fixtures — small declared model + observed profile for rule tests
# ---------------------------------------------------------------------------


class _Person(NodeModel):
    __label__ = "Person"
    name: str
    age: Optional[int] = None


class _Movie(NodeModel):
    __label__ = "Movie"
    title: str


class _ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    __source_cardinality__ = "1..*"


_STD_MODEL = GraphDefinition(
    name="std_test",
    node_types=[_Person, _Movie],
    relationship_types=[_ActedIn],
)

_STD_PROFILE = GraphProfile(
    source="test",
    node_type_profiles={
        "Person": NodeTypeProfile(
            label="Person",
            count=2,
            property_profiles={
                "name": PropertyProfile(
                    name="name",
                    present_count=2,
                    total_count=2,
                    observed_types=["String"],
                ),
                "age": PropertyProfile(
                    name="age",
                    present_count=1,
                    total_count=2,
                    observed_types=["Long"],
                ),
            },
        ),
        "Movie": NodeTypeProfile(label="Movie", count=1),
    },
    rel_type_profiles={
        "ACTED_IN": RelationshipTypeProfile(
            rel_type="ACTED_IN",
            count=3,
            source_labels={"Person"},
            target_labels={"Movie"},
            cardinality_stats=CardinalityStats(count=2, min=1, max=3, mean=1.5),
        ),
    },
)


def _ctx(**kwargs: Any) -> RuleContext:
    """Shorthand: build a RuleContext with _STD_MODEL + _STD_PROFILE."""
    return RuleContext(
        left_graph=DefinitionView(_STD_MODEL),
        right_graph=ProfileView(_STD_PROFILE),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# MissingNodeLabelRule
# ---------------------------------------------------------------------------


def test_missing_node_label_rule_code_and_severity():
    rule = MissingNodeLabelRule()
    issues = list(rule(_ctx(address="Ghost", extra={"address_type": "node_label"})))
    assert len(issues) == 1
    assert issues[0].code == "MISSING_NODE_LABEL"
    assert issues[0].severity == Severity.ERROR
    assert issues[0].entity_type == EntityType.NODE
    assert issues[0].entity_id == "Ghost"


def test_missing_node_label_rule_satisfies_protocol():
    assert isinstance(MissingNodeLabelRule(), Rule)


# ---------------------------------------------------------------------------
# UnexpectedNodeLabelRule
# ---------------------------------------------------------------------------


def test_unexpected_node_label_rule_code_and_severity():
    rule = UnexpectedNodeLabelRule()
    ntp = NodeTypeProfile(label="Extra", count=5)
    issues = list(
        rule(_ctx(address="Extra", right=ntp, extra={"address_type": "node_label"}))
    )
    assert len(issues) == 1
    assert issues[0].code == "UNEXPECTED_NODE_LABEL"
    assert issues[0].severity == Severity.WARNING
    assert issues[0].entity_type == EntityType.NODE


def test_unexpected_node_label_rule_satisfies_protocol():
    assert isinstance(UnexpectedNodeLabelRule(), Rule)


# ---------------------------------------------------------------------------
# MissingRelTypeRule
# ---------------------------------------------------------------------------


def test_missing_rel_type_rule_code_and_severity():
    rule = MissingRelTypeRule()
    issues = list(rule(_ctx(address="DIRECTED", extra={"address_type": "rel_type"})))
    assert len(issues) == 1
    assert issues[0].code == "MISSING_REL_TYPE"
    assert issues[0].severity == Severity.ERROR
    assert issues[0].entity_type == EntityType.RELATIONSHIP


def test_missing_rel_type_rule_satisfies_protocol():
    assert isinstance(MissingRelTypeRule(), Rule)


# ---------------------------------------------------------------------------
# UnexpectedRelTypeRule
# ---------------------------------------------------------------------------


def test_unexpected_rel_type_rule_code_and_severity():
    rule = UnexpectedRelTypeRule()
    issues = list(rule(_ctx(address="LIVES_IN", extra={"address_type": "rel_type"})))
    assert len(issues) == 1
    assert issues[0].code == "UNEXPECTED_REL_TYPE"
    assert issues[0].severity == Severity.WARNING
    assert issues[0].entity_type == EntityType.RELATIONSHIP


def test_unexpected_rel_type_rule_satisfies_protocol():
    assert isinstance(UnexpectedRelTypeRule(), Rule)


# ---------------------------------------------------------------------------
# MissingPropertyRule
# ---------------------------------------------------------------------------


def test_missing_property_rule_code_and_severity():
    from orthograph.graph_definition.property_spec import TypeInfo

    rule = MissingPropertyRule()
    ctx = _ctx(
        address="Person.score",
        left=TypeInfo(python_type=int, is_required=True),
        right=None,
        extra={"label": "Person", "prop_name": "score", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "MISSING_PROPERTY"
    assert issues[0].severity == Severity.ERROR
    assert issues[0].entity_id == "Person.score"


def test_missing_property_rule_satisfies_protocol():
    assert isinstance(MissingPropertyRule(), Rule)


# ---------------------------------------------------------------------------
# UnexpectedPropertyRule
# ---------------------------------------------------------------------------


def test_unexpected_property_rule_code_and_severity():
    rule = UnexpectedPropertyRule()
    pp = PropertyProfile(name="bonus", present_count=2, total_count=2)
    ctx = _ctx(
        address="Person.bonus",
        left=None,
        right=pp,
        extra={"label": "Person", "prop_name": "bonus", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "UNEXPECTED_PROPERTY"
    assert issues[0].severity == Severity.INFO
    assert issues[0].entity_id == "Person.bonus"


def test_unexpected_property_rule_satisfies_protocol():
    assert isinstance(UnexpectedPropertyRule(), Rule)


# ---------------------------------------------------------------------------
# PropertyIncompleteRule
# ---------------------------------------------------------------------------


def test_property_incomplete_rule_code_and_severity():
    from orthograph.graph_definition.property_spec import TypeInfo

    rule = PropertyIncompleteRule()
    # declared required=True, observed present_count < total_count → incomplete
    ctx = _ctx(
        address="Person.age",
        left=TypeInfo(python_type=int, is_required=True),
        right=PropertyProfile(name="age", present_count=1, total_count=2),
        extra={"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_INCOMPLETE"
    assert issues[0].severity == Severity.WARNING


def test_property_incomplete_rule_no_issue_when_complete():
    from orthograph.graph_definition.property_spec import TypeInfo

    rule = PropertyIncompleteRule()
    ctx = _ctx(
        address="Person.name",
        left=TypeInfo(python_type=str, is_required=True),
        right=PropertyProfile(name="name", present_count=2, total_count=2),
        extra={"label": "Person", "prop_name": "name", "entity_type": EntityType.NODE},
    )
    assert list(rule(ctx)) == []


def test_property_incomplete_rule_no_issue_when_not_required():
    from orthograph.graph_definition.property_spec import TypeInfo

    rule = PropertyIncompleteRule()
    ctx = _ctx(
        address="Person.age",
        left=TypeInfo(python_type=int, is_required=False),
        right=PropertyProfile(name="age", present_count=1, total_count=2),
        extra={"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE},
    )
    assert list(rule(ctx)) == []


def test_property_incomplete_rule_satisfies_protocol():
    assert isinstance(PropertyIncompleteRule(), Rule)


# ---------------------------------------------------------------------------
# PropertyTypeMismatchRule
# ---------------------------------------------------------------------------


def test_property_type_mismatch_rule_code_and_severity():
    from orthograph.graph_definition.property_spec import TypeInfo

    rule = PropertyTypeMismatchRule()
    # declared str, observed Long (maps to int) → mismatch
    ctx = _ctx(
        address="Person.age",
        left=TypeInfo(python_type=str, is_required=True),
        right=PropertyProfile(
            name="age",
            present_count=2,
            total_count=2,
            observed_types=["Long"],
        ),
        extra={"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_TYPE_MISMATCH"
    assert issues[0].severity == Severity.ERROR


def test_property_type_mismatch_rule_no_issue_when_types_match():
    from orthograph.graph_definition.property_spec import TypeInfo

    rule = PropertyTypeMismatchRule()
    ctx = _ctx(
        address="Person.name",
        left=TypeInfo(python_type=str, is_required=True),
        right=PropertyProfile(
            name="name",
            present_count=2,
            total_count=2,
            observed_types=["String"],
        ),
        extra={"label": "Person", "prop_name": "name", "entity_type": EntityType.NODE},
    )
    assert list(rule(ctx)) == []


def test_property_type_mismatch_rule_satisfies_protocol():
    assert isinstance(PropertyTypeMismatchRule(), Rule)


# ---------------------------------------------------------------------------
# PropertyTypeMismatchRule — prevalence
# ---------------------------------------------------------------------------


def test_property_type_mismatch_empty_counts_byte_for_byte_today():
    """observed_type_counts == {} → identical to legacy behaviour (regression guard)."""
    rule = PropertyTypeMismatchRule()
    ctx = _ctx(
        address="Person.age",
        left=TypeInfo(python_type=str, is_required=True),
        right=PropertyProfile(
            name="age",
            present_count=2,
            total_count=2,
            observed_types=["Long"],
            observed_type_counts={},
        ),
        extra={"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_TYPE_MISMATCH"
    assert issues[0].severity == Severity.ERROR
    assert issues[0].message == (
        "Property 'age' on Person has observed type 'Long' (Python: int), expected str"
    )
    # No prevalence context when counts are absent.
    assert "off_type_share" not in (issues[0].context or {})


def test_property_type_mismatch_systematic_share_is_error():
    """A systematic off-type share (>= threshold) → ERROR with prevalence in message."""
    rule = PropertyTypeMismatchRule()
    ctx = _ctx(
        address="Person.age",
        left=TypeInfo(python_type=str, is_required=True),
        right=PropertyProfile(
            name="age",
            present_count=100,
            total_count=100,
            observed_types=["String", "Long"],
            observed_type_counts={"String": 40, "Long": 60},
        ),
        extra={"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_TYPE_MISMATCH"
    assert issues[0].severity == Severity.ERROR
    # 60 of 100 are the off-type 'Long'.
    assert "60.0%" in issues[0].message
    assert issues[0].context["off_type_count"] == 60
    assert issues[0].context["total_count"] == 100
    assert issues[0].context["off_type_share"] == pytest.approx(0.6)


def test_property_type_mismatch_negligible_share_is_warning():
    """A negligible off-type share (< threshold) → WARNING, code unchanged."""
    rule = PropertyTypeMismatchRule()
    ctx = _ctx(
        address="Person.age",
        left=TypeInfo(python_type=str, is_required=True),
        right=PropertyProfile(
            name="age",
            present_count=1000,
            total_count=1000,
            observed_types=["String", "Long"],
            observed_type_counts={"String": 999, "Long": 1},
        ),
        extra={"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_TYPE_MISMATCH"
    assert issues[0].severity == Severity.WARNING
    assert "0.1%" in issues[0].message
    assert issues[0].context["off_type_share"] == pytest.approx(0.001)


def test_property_type_mismatch_share_at_threshold_is_error():
    """Off-type share exactly at the threshold counts as systematic (ERROR)."""
    rule = PropertyTypeMismatchRule(severity_threshold=0.05)
    ctx = _ctx(
        address="Person.age",
        left=TypeInfo(python_type=str, is_required=True),
        right=PropertyProfile(
            name="age",
            present_count=100,
            total_count=100,
            observed_types=["String", "Long"],
            observed_type_counts={"String": 95, "Long": 5},
        ),
        extra={"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].severity == Severity.ERROR


def test_property_type_mismatch_per_off_type_share_with_multiple_mismatches():
    """Each off-type is judged on its own share (one issue per mismatching type)."""
    rule = PropertyTypeMismatchRule(severity_threshold=0.05)
    ctx = _ctx(
        address="Person.age",
        left=TypeInfo(python_type=str, is_required=True),
        right=PropertyProfile(
            name="age",
            present_count=100,
            total_count=100,
            observed_types=["String", "Long", "Double"],
            observed_type_counts={"String": 50, "Long": 49, "Double": 1},
        ),
        extra={"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    by_type = {i.context["observed_type"]: i for i in issues}
    assert by_type["Long"].severity == Severity.ERROR  # 49% systematic
    assert by_type["Double"].severity == Severity.WARNING  # 1% negligible


def test_property_type_mismatch_off_type_absent_from_populated_counts_is_legacy_error():
    """A populated counts map missing one off-type → legacy ERROR for that type.

    By ADR-035 invariant a populated value scan should count every present
    off-type, so this combination is not expected in practice. The rule's
    honest escape never invents a share: an off-type absent from a populated
    map falls back to the legacy ERROR with no prevalence claim.
    """
    rule = PropertyTypeMismatchRule(severity_threshold=0.05)
    ctx = _ctx(
        address="Person.age",
        left=TypeInfo(python_type=str, is_required=True),
        # 'Double' is observed as an off-type but absent from the counts map.
        right=PropertyProfile(
            name="age",
            present_count=100,
            total_count=100,
            observed_types=["String", "Long", "Double"],
            observed_type_counts={"String": 50, "Long": 50},
        ),
        extra={"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    by_type = {i.context["observed_type"] if i.context else None: i for i in issues}
    # 'Long' has a share (50/100) → systematic ERROR with prevalence context.
    assert by_type["Long"].severity == Severity.ERROR
    assert by_type["Long"].context["off_type_share"] == pytest.approx(0.5)
    # 'Double' is uncounted → legacy ERROR, no prevalence, empty context.
    double = next(i for i in issues if i.context in (None, {}))
    assert double.code == "PROPERTY_TYPE_MISMATCH"
    assert double.severity == Severity.ERROR
    assert "of observed values" not in double.message
    assert "off_type_share" not in (double.context or {})


def test_property_type_mismatch_matching_types_excluded_from_share():
    """The off-type share is over the full present population, not just off-types."""
    rule = PropertyTypeMismatchRule(severity_threshold=0.05)
    ctx = _ctx(
        address="Person.name",
        left=TypeInfo(python_type=str, is_required=True),
        # only 'Long' is off-type; 'String' matches and stays silent.
        right=PropertyProfile(
            name="name",
            present_count=200,
            total_count=200,
            observed_types=["String", "Long"],
            observed_type_counts={"String": 198, "Long": 2},
        ),
        extra={"label": "Person", "prop_name": "name", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1  # only the off-type 'Long'
    assert issues[0].context["off_type_share"] == pytest.approx(0.01)  # 2/200
    assert issues[0].severity == Severity.WARNING


# ---------------------------------------------------------------------------
# InvalidEndpointRule
# ---------------------------------------------------------------------------


def test_invalid_endpoint_rule_code_and_severity():
    rule = InvalidEndpointRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=1,
        source_labels={"WrongNode"},  # declared source is Person
        target_labels={"Movie"},
    )
    ctx = _ctx(
        address="ACTED_IN",
        left=_ActedIn,
        right=rtp,
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "INVALID_ENDPOINT"
    assert issues[0].severity == Severity.ERROR
    assert issues[0].entity_type == EntityType.RELATIONSHIP


def test_invalid_endpoint_rule_no_issue_when_valid():
    rule = InvalidEndpointRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=1,
        source_labels={"Person"},
        target_labels={"Movie"},
    )
    ctx = _ctx(address="ACTED_IN", left=_ActedIn, right=rtp)
    assert list(rule(ctx)) == []


def test_invalid_endpoint_rule_satisfies_protocol():
    assert isinstance(InvalidEndpointRule(), Rule)


# ---------------------------------------------------------------------------
# CardinalityViolationRule
# ---------------------------------------------------------------------------


def test_cardinality_violation_rule_code_and_severity():
    rule = CardinalityViolationRule()
    # _ActedIn has source_cardinality ONE_OR_MORE (min=1); min=0 violates
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=2,
        source_labels={"Person"},
        target_labels={"Movie"},
        cardinality_stats=CardinalityStats(count=2, min=0, max=3, mean=1.5),
    )
    ctx = _ctx(address="ACTED_IN", left=_ActedIn, right=rtp)
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "CARDINALITY_VIOLATION"
    assert issues[0].severity == Severity.ERROR
    assert issues[0].entity_type == EntityType.RELATIONSHIP


def test_cardinality_violation_rule_no_issue_when_satisfied():
    rule = CardinalityViolationRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=2,
        source_labels={"Person"},
        target_labels={"Movie"},
        cardinality_stats=CardinalityStats(count=2, min=1, max=3, mean=2.0),
    )
    ctx = _ctx(address="ACTED_IN", left=_ActedIn, right=rtp)
    assert list(rule(ctx)) == []


def test_cardinality_violation_rule_no_issue_when_no_stats():
    rule = CardinalityViolationRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=0,
        source_labels={"Person"},
        target_labels={"Movie"},
    )
    ctx = _ctx(address="ACTED_IN", left=_ActedIn, right=rtp)
    assert list(rule(ctx)) == []


def test_cardinality_violation_rule_satisfies_protocol():
    assert isinstance(CardinalityViolationRule(), Rule)


# ---------------------------------------------------------------------------
# standard_rules()
# ---------------------------------------------------------------------------


def test_standard_rules_returns_twelve_rules():
    rules = standard_rules()
    assert len(rules) == 12


def test_standard_rules_all_satisfy_protocol():
    for rule in standard_rules():
        assert isinstance(rule, Rule), f"{rule!r} does not satisfy Rule protocol"


def test_standard_rules_keys_are_unique():
    keys = [r.key for r in standard_rules()]
    assert len(keys) == len(set(keys)), "Duplicate keys in standard_rules()"


def test_standard_rules_expected_keys():
    expected = {
        "node_label.missing",
        "node_label.unexpected",
        "rel_type.missing",
        "rel_type.unexpected",
        "property.missing",
        "property.unexpected",
        "property.incomplete",
        "property.type_mismatch",
        "property.constraint_presence",
        "property.enum_value",
        "rel.endpoint",
        "rel.cardinality",
    }
    assert {r.key for r in standard_rules()} == expected


# ===========================================================================
# How to add a Case-B comparable rule (ADR-015 §3) — reference recipe
#
# Use this section as a template when you need to compare a new declared
# constraint against a new observed measurement.
#
# RECIPE — three steps, zero engine changes:
#
#   Step 1. Add the observed measurement to a profile model as a new field
#           (e.g. PropertyProfile.distinct_count).  Default to None/{} so
#           existing construction sites are unaffected.
#
#   Step 2. Write one Rule dataclass:
#           - key: str  — a stable dot-namespaced identifier
#           - __call__(context) -> Iterable[ValidationIssue]
#             * guard: return early if context.observed / context.declared are
#               not the right types (the engine calls all rules per context)
#             * emit a ValidationIssue with a new code (never reuse an old one)
#
#   Step 3. Inject via compare(..., rules=standard_rules() + [MyRule()])
#           The comparison engine is never modified.
#
# PropertyDistinctCountRule (D2) is the reference implementation.
# ===========================================================================


def test_distinct_count_rule_satisfies_protocol():
    """Step 2 check: the rule conforms to the Rule Protocol."""
    from orthograph.comparison.rules import PropertyDistinctCountRule

    assert isinstance(PropertyDistinctCountRule(), Rule)


def test_distinct_count_rule_emits_exactly_one_issue_when_exceeded():
    """Rule fires when observed distinct_count exceeds the declared max.

    Asserts:
    - exactly 1 issue emitted (not "at least 1")
    - code is the new DISTINCT_COUNT_EXCEEDED (never an existing code)
    - severity is INFO
    """
    from orthograph.comparison.rules import PropertyDistinctCountRule

    rule = PropertyDistinctCountRule()
    pp = PropertyProfile(
        name="status",
        present_count=100,
        total_count=100,
        distinct_count=50,  # observed: 50 distinct values
    )
    ctx = _ctx(
        address="Person.status",
        right=pp,
        extra={
            "label": "Person",
            "prop_name": "status",
            "entity_type": EntityType.NODE,
            "max_distinct_count": 10,  # declared: at most 10
        },
    )
    issues = list(rule(ctx))
    assert len(issues) == 1  # exact count — not ">= 1"
    assert issues[0].code == "DISTINCT_COUNT_EXCEEDED"
    assert issues[0].severity == Severity.INFO


def test_distinct_count_rule_emits_zero_issues_when_within_bound():
    """Rule is silent when the constraint is satisfied."""
    from orthograph.comparison.rules import PropertyDistinctCountRule

    rule = PropertyDistinctCountRule()
    pp = PropertyProfile(
        name="status",
        present_count=100,
        total_count=100,
        distinct_count=5,  # 5 <= 10 — constraint satisfied
    )
    ctx = _ctx(
        address="Person.status",
        right=pp,
        extra={
            "label": "Person",
            "prop_name": "status",
            "entity_type": EntityType.NODE,
            "max_distinct_count": 10,
        },
    )
    assert list(rule(ctx)) == []  # exactly zero issues


def test_distinct_count_rule_emits_zero_issues_when_not_populated():
    """Rule is silent when the observed measurement is absent (distinct_count=None).

    Backends that cannot provide distinct counts leave the field at its
    default None.  The rule must not error or spuriously fire.
    """
    from orthograph.comparison.rules import PropertyDistinctCountRule

    rule = PropertyDistinctCountRule()
    pp = PropertyProfile(
        name="x",
        present_count=5,
        total_count=5,
        # distinct_count defaults to None — measurement not available
    )
    ctx = _ctx(
        address="Person.x",
        right=pp,
        extra={
            "label": "Person",
            "prop_name": "x",
            "entity_type": EntityType.NODE,
            "max_distinct_count": 10,
        },
    )
    assert list(rule(ctx)) == []  # exactly zero issues


def test_distinct_count_rule_emits_zero_issues_without_declared_constraint():
    """Rule is silent when the declared constraint is absent from extra.

    The constraint is opt-in: if max_distinct_count is not in extra the rule
    skips silently.  Standard contexts never supply this key.
    """
    from orthograph.comparison.rules import PropertyDistinctCountRule

    rule = PropertyDistinctCountRule()
    pp = PropertyProfile(name="x", present_count=5, total_count=5, distinct_count=99)
    ctx = _ctx(
        address="Person.x",
        right=pp,
        # no max_distinct_count in extra → constraint not declared
        extra={"label": "Person", "prop_name": "x", "entity_type": EntityType.NODE},
    )
    assert list(rule(ctx)) == []  # exactly zero issues


def test_case_b_extension_via_injection():
    """End-to-end recipe demonstration: Case-B extension via rules injection.

    This test shows how to add a comparable rule in production:

        Step 1 (already done): PropertyProfile.distinct_count field exists.

        Step 2 (the rule): BoundDistinctCountRule — pre-binds max_distinct so
        the engine doesn't need to know about the declared constraint. The rule
        itself carries the declared side; the engine stays unchanged.

        Step 3 (injection): compare(..., rules=standard_rules() + [rule])

    Assertions use exact counts so the test fails loudly if behaviour shifts.

    Profile setup (against _STD_MODEL: Person[name:str, age:Optional[int]],
    Movie[title:str], ACTED_IN Person->Movie ONE_OR_MORE):

        Person (200 nodes):
            name  — present 200/200, distinct_count=200
                    (exceeds max_distinct=100 → 1 Case-B issue)
            age   — present 150/200, distinct_count=80
                    (Optional, so incomplete is fine; within max_distinct=100)
        Movie  (10 nodes): no property_profiles supplied
                    → title is required but absent → 1 MISSING_PROPERTY
        ACTED_IN (300): source=Person, target=Movie, no cardinality_stats
                    → no cardinality issue

    Standard issues:  1  (MISSING_PROPERTY Movie.title)
    Case-B issues:    1  (DISTINCT_COUNT_EXCEEDED Person.name)
    Total:            2
    """
    from collections.abc import Iterable as _Iterable
    from dataclasses import dataclass as _dc

    from orthograph.comparison.engine import compare_profile_to_definition
    from orthograph.comparison.rules import standard_rules
    from orthograph.graph_profile.models import NodeTypeProfile

    # ------------------------------------------------------------------
    # Step 2 — define the Case-B rule (carries its own declared constraint)
    # ------------------------------------------------------------------
    @_dc
    class BoundDistinctCountRule:
        """A Case-B rule pre-bound to a declared max_distinct value.

        The declared constraint lives inside the rule; the engine never
        sees it.  This is the idiomatic Case-B injection pattern.
        """

        key: str = "property.distinct_count.bound"
        max_distinct: int = 100

        def __call__(self, context: RuleContext) -> _Iterable[ValidationIssue]:
            from orthograph.graph_profile.models import PropertyProfile as _PP

            prop_profile = context.right
            if not isinstance(prop_profile, _PP):
                return  # not a property context
            if prop_profile.distinct_count is None:
                return  # measurement absent — skip
            if "prop_name" not in context.extra:
                return  # not a property address
            if prop_profile.distinct_count > self.max_distinct:
                label = context.extra["label"]
                prop_name = context.extra["prop_name"]
                entity_type = context.extra["entity_type"]
                yield ValidationIssue(
                    code="DISTINCT_COUNT_EXCEEDED",
                    severity=Severity.INFO,
                    entity_type=entity_type,
                    entity_id=f"{label}.{prop_name}",
                    message=(
                        f"Property '{prop_name}' on {label} has "
                        f"{prop_profile.distinct_count} distinct values, "
                        f"expected at most {self.max_distinct}"
                    ),
                )

    # ------------------------------------------------------------------
    # Step 1 already done — build a profile that uses distinct_count
    # ------------------------------------------------------------------
    profile = GraphProfile(
        source="test",
        node_type_profiles={
            "Person": NodeTypeProfile(
                label="Person",
                count=200,
                property_profiles={
                    "name": PropertyProfile(
                        name="name",
                        present_count=200,
                        total_count=200,
                        observed_types=["String"],
                        distinct_count=200,  # exceeds max_distinct=100 → issue
                    ),
                    "age": PropertyProfile(
                        name="age",
                        present_count=150,
                        total_count=200,  # Optional field — no PROPERTY_INCOMPLETE
                        observed_types=["Long"],
                        distinct_count=80,  # within max_distinct=100 → no issue
                    ),
                },
            ),
            "Movie": NodeTypeProfile(
                label="Movie",
                count=10,
                # no property_profiles → Movie.title (required) → MISSING_PROPERTY
            ),
        },
        rel_type_profiles={
            "ACTED_IN": RelationshipTypeProfile(
                rel_type="ACTED_IN",
                count=300,
                source_labels={"Person"},
                target_labels={"Movie"},
                # no cardinality_stats → no CARDINALITY_VIOLATION
            ),
        },
    )

    # ------------------------------------------------------------------
    # Step 3 — inject: standard rules + one new Case-B rule
    # No changes to validation.py or rules.py required.
    # ------------------------------------------------------------------
    rules = standard_rules() + [BoundDistinctCountRule(max_distinct=100)]
    result = compare_profile_to_definition(profile, _STD_MODEL, rules=rules)

    # --- exact counts ---
    distinct_issues = [i for i in result.issues if i.code == "DISTINCT_COUNT_EXCEEDED"]
    missing_issues = [i for i in result.issues if i.code == "MISSING_PROPERTY"]

    assert len(distinct_issues) == 1, (
        f"Expected exactly 1 DISTINCT_COUNT_EXCEEDED (Person.name); "
        f"got {[i.entity_id for i in distinct_issues]}"
    )
    assert distinct_issues[0].entity_id == "Person.name"

    assert len(missing_issues) == 1, (
        f"Expected exactly 1 MISSING_PROPERTY (Movie.title); "
        f"got {[i.entity_id for i in missing_issues]}"
    )
    assert missing_issues[0].entity_id == "Movie.title"

    # E45.4: Person.name is declared-required but the profile carries no
    # constraint_required (None) → PropertyConstraintPresenceRule emits one
    # CONSTRAINT_UNVERIFIABLE (INFO).
    unverifiable = [i for i in result.issues if i.code == "CONSTRAINT_UNVERIFIABLE"]
    assert len(unverifiable) == 1
    assert unverifiable[0].entity_id == "Person.name"

    # Total: 3 issues — 1 MISSING_PROPERTY, 1 injected Case-B, 1 CONSTRAINT_UNVERIFIABLE
    assert len(result.issues) == 3, (
        f"Expected exactly 3 issues total; got {len(result.issues)}: "
        + str([(i.code, i.entity_id) for i in result.issues])
    )


# ===========================================================================
# CardinalityViolationRule: conditional side → CARDINALITY_UNVERIFIABLE
# ===========================================================================


class _OperationNode(NodeModel):
    """Discriminated operation node for conditional cardinality tests."""

    __label__ = "Operation"
    kind: str


class _SampleNode(NodeModel):
    """Sample node for conditional cardinality tests."""

    __label__ = "Sample"
    kind: str


class _HasOutputConditional(RelationshipModel):
    """HAS_OUTPUT with a conditional source cardinality."""

    __label__ = "HAS_OUTPUT"
    __source_label__ = "Operation"
    __target_label__ = "Sample"
    __source_cardinality__ = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch({"kind": "subsampling"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
        ),
        default="0..*",
    )


_E407_MODEL = GraphDefinition(
    name="e407_test",
    node_types=[_OperationNode, _SampleNode],
    relationship_types=[_HasOutputConditional],
)

_E407_PROFILE = GraphProfile(
    source="e407_test",
    node_type_profiles={
        "Operation": NodeTypeProfile(label="Operation", count=1),
        "Sample": NodeTypeProfile(label="Sample", count=2),
    },
    rel_type_profiles={
        "HAS_OUTPUT": RelationshipTypeProfile(
            rel_type="HAS_OUTPUT",
            count=2,
            source_labels={"Operation"},
            target_labels={"Sample"},
            cardinality_stats=CardinalityStats(count=1, min=1, max=2, mean=1.5),
        ),
    },
)


def _e407_ctx(**kwargs: Any) -> RuleContext:
    """Build a RuleContext with E40.7 model + profile."""
    return RuleContext(
        left_graph=DefinitionView(_E407_MODEL),
        right_graph=ProfileView(_E407_PROFILE),
        **kwargs,
    )


def test_cardinality_violation_rule_conditional_yields_unverifiable():
    """Scope: CardinalityViolationRule yields exactly one CARDINALITY_UNVERIFIABLE
    (INFO) when the declared source cardinality is ConditionalCardinality."""
    rule = CardinalityViolationRule()
    rtp = RelationshipTypeProfile(
        rel_type="HAS_OUTPUT",
        count=2,
        source_labels={"Operation"},
        target_labels={"Sample"},
        cardinality_stats=CardinalityStats(count=1, min=1, max=2, mean=1.5),
    )
    ctx = _e407_ctx(address="HAS_OUTPUT", left=_HasOutputConditional, right=rtp)
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "CARDINALITY_UNVERIFIABLE"
    assert issues[0].severity == Severity.INFO
    assert issues[0].entity_type == EntityType.RELATIONSHIP
    assert issues[0].entity_id == "HAS_OUTPUT"


def test_cardinality_violation_rule_conditional_no_cardinality_violation():
    """Scope: CardinalityViolationRule never emits CARDINALITY_VIOLATION when
    the declared cardinality is conditional — only CARDINALITY_UNVERIFIABLE."""
    rule = CardinalityViolationRule()
    rtp = RelationshipTypeProfile(
        rel_type="HAS_OUTPUT",
        count=0,
        source_labels={"Operation"},
        target_labels={"Sample"},
        cardinality_stats=CardinalityStats(count=0, min=0, max=0, mean=0.0),
    )
    ctx = _e407_ctx(address="HAS_OUTPUT", left=_HasOutputConditional, right=rtp)
    codes = [i.code for i in rule(ctx)]
    assert "CARDINALITY_VIOLATION" not in codes


def test_cardinality_violation_rule_constant_unchanged_regression():
    """Scope: CardinalityViolationRule still emits CARDINALITY_VIOLATION for a
    constant-spec declared cardinality (regression guard)."""
    rule = CardinalityViolationRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=2,
        source_labels={"Person"},
        target_labels={"Movie"},
        cardinality_stats=CardinalityStats(count=2, min=0, max=3, mean=1.5),
    )
    ctx = _ctx(address="ACTED_IN", left=_ActedIn, right=rtp)
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "CARDINALITY_VIOLATION"


# ===========================================================================
# Comparison rules: presence (3 sources), enum/value, total-count diff-only
#
# Implements the ADR-034 §8 non-cardinality rows.  Settled severities
# (recorded in ADR-034 §8):
#   - PROPERTY_INCOMPLETE          WARNING  (declared-required & completeness<1)
#   - PROPERTY_UNCONSTRAINED       WARNING  (declared-required & constraint False)
#   - UNDECLARED_CONSTRAINT        INFO     (constraint True & not declared-required)
#   - CONSTRAINT_UNVERIFIABLE      INFO     (declared-required & constraint None)
#   - UNDECLARED_PROPERTY_VALUE    WARNING  (declared enum; observed value not in enum)
#   - UNOBSERVED_PROPERTY_VALUE    INFO     (declared enum value never observed)
#   - PROPERTY_VALUE_UNVERIFIABLE  INFO     (declared enum; value_distribution None)
# ===========================================================================


class _Status(Enum):
    """Declared enum for value-comparison tests."""

    ACTIVE = "active"
    INACTIVE = "inactive"


# ---------------------------------------------------------------------------
# PropertyIncompleteRule — declared-required vs occurrence (ADR-034 §8)
# ---------------------------------------------------------------------------


def test_property_incomplete_rule_fires_on_completeness_below_one():
    """Declared-required + completeness < 1.0 → PROPERTY_INCOMPLETE (WARNING)."""
    rule = PropertyIncompleteRule()
    ctx = _ctx(
        address="Person.age",
        left=TypeInfo(python_type=int, is_required=True),
        right=PropertyProfile(name="age", present_count=3, total_count=5),
        extra={"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_INCOMPLETE"
    assert issues[0].severity == Severity.WARNING


# ---------------------------------------------------------------------------
# PropertyConstraintPresenceRule — declared-required vs constraint (3 outcomes)
# ---------------------------------------------------------------------------


def _constraint_ctx(
    constraint_required: bool | None, *, is_required: bool = True
) -> RuleContext:
    return _ctx(
        address="Person.name",
        left=TypeInfo(python_type=str, is_required=is_required),
        right=PropertyProfile(
            name="name",
            present_count=5,
            total_count=5,
            constraint_required=constraint_required,
        ),
        extra={"label": "Person", "prop_name": "name", "entity_type": EntityType.NODE},
    )


def test_constraint_presence_rule_satisfies_protocol():
    assert isinstance(PropertyConstraintPresenceRule(), Rule)


def test_constraint_presence_rule_declared_required_false_warns():
    """Declared-required & constraint_required is False → PROPERTY_UNCONSTRAINED."""
    rule = PropertyConstraintPresenceRule()
    issues = list(rule(_constraint_ctx(False)))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_UNCONSTRAINED"
    assert issues[0].severity == Severity.WARNING
    assert issues[0].entity_id == "Person.name"


def test_constraint_presence_rule_declared_required_none_unverifiable():
    """Declared-required & constraint_required is None → CONSTRAINT_UNVERIFIABLE."""
    rule = PropertyConstraintPresenceRule()
    issues = list(rule(_constraint_ctx(None)))
    assert len(issues) == 1
    assert issues[0].code == "CONSTRAINT_UNVERIFIABLE"
    assert issues[0].severity == Severity.INFO


def test_constraint_presence_rule_declared_required_true_silent():
    """Declared-required & constraint_required is True → no issue (the happy path)."""
    rule = PropertyConstraintPresenceRule()
    assert list(rule(_constraint_ctx(True))) == []


def test_constraint_presence_rule_undeclared_constraint_info():
    """constraint True, not declared-required → UNDECLARED_CONSTRAINT (INFO)."""
    rule = PropertyConstraintPresenceRule()
    issues = list(rule(_constraint_ctx(True, is_required=False)))
    assert len(issues) == 1
    assert issues[0].code == "UNDECLARED_CONSTRAINT"
    assert issues[0].severity == Severity.INFO


def test_constraint_presence_rule_optional_false_or_none_silent():
    """Not declared-required + constraint False/None → nothing to report."""
    rule = PropertyConstraintPresenceRule()
    assert list(rule(_constraint_ctx(False, is_required=False))) == []
    assert list(rule(_constraint_ctx(None, is_required=False))) == []


# ---------------------------------------------------------------------------
# PropertyEnumValueRule — declared enum vs observed value_distribution
# ---------------------------------------------------------------------------


def _enum_ctx(distribution: BoundedDistribution | None) -> RuleContext:
    return _ctx(
        address="Person.status",
        left=TypeInfo(python_type=_Status, is_required=True),
        right=PropertyProfile(
            name="status",
            present_count=5,
            total_count=5,
            value_distribution=distribution,
        ),
        extra={
            "label": "Person",
            "prop_name": "status",
            "entity_type": EntityType.NODE,
        },
    )


def test_enum_value_rule_satisfies_protocol():
    assert isinstance(PropertyEnumValueRule(), Rule)


def test_enum_value_rule_undeclared_value_warns():
    """Observed value not in the declared enum → UNDECLARED_PROPERTY_VALUE (WARNING)."""
    rule = PropertyEnumValueRule()
    dist = BoundedDistribution(count=5, histogram={"active": 3, "pending": 2})
    issues = list(rule(_enum_ctx(dist)))
    undeclared = [i for i in issues if i.code == "UNDECLARED_PROPERTY_VALUE"]
    assert len(undeclared) == 1
    assert undeclared[0].severity == Severity.WARNING
    assert undeclared[0].entity_id == "Person.status"
    assert "pending" in undeclared[0].message


def test_enum_value_rule_unobserved_declared_value_info():
    """Declared enum value never observed → UNOBSERVED_PROPERTY_VALUE (INFO)."""
    rule = PropertyEnumValueRule()
    dist = BoundedDistribution(count=5, histogram={"active": 5})
    issues = list(rule(_enum_ctx(dist)))
    unobserved = [i for i in issues if i.code == "UNOBSERVED_PROPERTY_VALUE"]
    assert len(unobserved) == 1
    assert unobserved[0].severity == Severity.INFO
    assert "inactive" in unobserved[0].message


def test_enum_value_rule_all_values_match_silent():
    """All observed values declared and all declared values observed → no issue."""
    rule = PropertyEnumValueRule()
    dist = BoundedDistribution(count=5, histogram={"active": 3, "inactive": 2})
    assert list(rule(_enum_ctx(dist))) == []


def test_enum_value_rule_none_distribution_unverifiable():
    """Declared enum but value_distribution is None → PROPERTY_VALUE_UNVERIFIABLE."""
    rule = PropertyEnumValueRule()
    issues = list(rule(_enum_ctx(None)))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_VALUE_UNVERIFIABLE"
    assert issues[0].severity == Severity.INFO


def test_enum_value_rule_no_histogram_unverifiable():
    """Declared enum, distribution present but histogram None → unverifiable."""
    rule = PropertyEnumValueRule()
    dist = BoundedDistribution(count=5)  # histogram defaults to None
    issues = list(rule(_enum_ctx(dist)))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_VALUE_UNVERIFIABLE"


def test_enum_value_rule_silent_for_non_enum_property():
    """Non-enum declared property → rule no-ops (value comparison is enum-only)."""
    rule = PropertyEnumValueRule()
    ctx = _ctx(
        address="Person.name",
        left=TypeInfo(python_type=str, is_required=True),
        right=PropertyProfile(
            name="name",
            present_count=5,
            total_count=5,
            value_distribution=BoundedDistribution(
                count=5, histogram={"alice": 3, "bob": 2}
            ),
        ),
        extra={"label": "Person", "prop_name": "name", "entity_type": EntityType.NODE},
    )
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# PropertyEnumValueRule — truncated value_distribution (ADR-034 §2 honesty)
#
# A histogram capped at ``limit`` (``sample_complete is False``) hides
# ``other_count`` observations.  The rule must NOT make absence-based verdicts on
# a truncated histogram: an undeclared value could be hidden in the remainder
# (silent false negative — the severe direction), and a declared value absent
# from the shown keys could still be present in the remainder (false UNOBSERVED).
# ---------------------------------------------------------------------------


def test_enum_value_rule_truncated_histogram_is_unverifiable_not_unobserved():
    """Truncated histogram → PROPERTY_VALUE_UNVERIFIABLE, never a false UNOBSERVED.

    Only 'active' is shown; 'inactive' is absent from the shown keys but may be
    among the 40 hidden observations, so claiming it was 'never observed' would be
    a false verdict.  The rule emits a single UNVERIFIABLE INFO instead.
    """
    rule = PropertyEnumValueRule()
    dist = BoundedDistribution(
        count=100,
        histogram={"active": 60},
        sample_complete=False,
        limit=1,
        other_count=40,
    )
    issues = list(rule(_enum_ctx(dist)))
    codes = {i.code for i in issues}
    assert "PROPERTY_VALUE_UNVERIFIABLE" in codes
    assert "UNOBSERVED_PROPERTY_VALUE" not in codes
    unverifiable = next(i for i in issues if i.code == "PROPERTY_VALUE_UNVERIFIABLE")
    assert unverifiable.severity == Severity.INFO
    assert unverifiable.context["other_count"] == 40
    assert unverifiable.context["limit"] == 1


def test_enum_value_rule_truncated_histogram_still_flags_shown_undeclared_value():
    """A shown value not in the enum is a true breach even when truncated.

    'pending' is in the shown histogram (definitely observed) → WARNING fires;
    the truncation INFO is also emitted to flag that further undeclared values
    may be hidden.
    """
    rule = PropertyEnumValueRule()
    dist = BoundedDistribution(
        count=100,
        histogram={"active": 50, "pending": 30},
        sample_complete=False,
        limit=2,
        other_count=20,
    )
    issues = list(rule(_enum_ctx(dist)))
    undeclared = [i for i in issues if i.code == "UNDECLARED_PROPERTY_VALUE"]
    assert len(undeclared) == 1
    assert undeclared[0].severity == Severity.WARNING
    assert "pending" in undeclared[0].message
    # Truncation is still signalled.
    assert any(i.code == "PROPERTY_VALUE_UNVERIFIABLE" for i in issues)
    # No false UNOBSERVED while truncated.
    assert not any(i.code == "UNOBSERVED_PROPERTY_VALUE" for i in issues)


def test_enum_value_rule_complete_histogram_still_reports_unobserved():
    """A *complete* histogram (sample_complete) keeps the UNOBSERVED verdict."""
    rule = PropertyEnumValueRule()
    dist = BoundedDistribution(
        count=100, histogram={"active": 100}, sample_complete=True
    )
    issues = list(rule(_enum_ctx(dist)))
    assert [i.code for i in issues] == ["UNOBSERVED_PROPERTY_VALUE"]
    assert not any(i.code == "PROPERTY_VALUE_UNVERIFIABLE" for i in issues)


# ---------------------------------------------------------------------------
# PropertyTypeMismatchRule — enum-typed properties (no spurious mismatch)
#
# A graph DB stores an enum's underlying scalar (a String for a str-valued enum,
# a Long for an int-valued enum), never the Python enum object.  The structural
# type check must compare the observed DB type against the enum's *value* type,
# not the enum class — otherwise every enum property a backend reports as
# 'String' raises a false PROPERTY_TYPE_MISMATCH ERROR.
# ---------------------------------------------------------------------------


def _type_ctx(python_type: type, observed_types: list[str]) -> RuleContext:
    return _ctx(
        address="Movie.genre",
        left=TypeInfo(python_type=python_type, is_required=True),
        right=PropertyProfile(
            name="genre",
            present_count=10,
            total_count=10,
            observed_types=observed_types,
        ),
        extra={"label": "Movie", "prop_name": "genre", "entity_type": EntityType.NODE},
    )


def test_type_mismatch_rule_no_false_mismatch_for_str_valued_plain_enum():
    """Plain str-valued enum observed as 'String' → no PROPERTY_TYPE_MISMATCH."""
    rule = PropertyTypeMismatchRule()

    class Genre(Enum):
        DRAMA = "drama"
        ACTION = "action"

    assert list(rule(_type_ctx(Genre, ["String"]))) == []


def test_type_mismatch_rule_no_false_mismatch_for_str_mixin_enum():
    """str-mixin enum observed as 'String' → no PROPERTY_TYPE_MISMATCH."""
    rule = PropertyTypeMismatchRule()

    class Genre(str, Enum):
        DRAMA = "drama"

    assert list(rule(_type_ctx(Genre, ["String"]))) == []


def test_type_mismatch_rule_no_false_mismatch_for_int_valued_enum():
    """int-valued enum observed as 'Long' → no PROPERTY_TYPE_MISMATCH."""
    rule = PropertyTypeMismatchRule()

    class Rating(Enum):
        LOW = 1
        HIGH = 2

    assert list(rule(_type_ctx(Rating, ["Long"]))) == []


def test_type_mismatch_rule_flags_enum_observed_as_wrong_scalar():
    """str-valued enum observed as 'Long' IS a genuine mismatch → ERROR.

    The enum's storage type is ``str``; a 'Long' observation is a real
    structural breach (the data is stored as an int, not the enum's string).
    """
    rule = PropertyTypeMismatchRule()

    class Genre(Enum):
        DRAMA = "drama"

    issues = list(rule(_type_ctx(Genre, ["Long"])))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_TYPE_MISMATCH"
    assert issues[0].severity == Severity.ERROR


def test_type_mismatch_rule_mixed_value_type_enum_stands_down():
    """An enum with mixed value types has no single storage type → rule no-ops."""
    rule = PropertyTypeMismatchRule()

    class Mixed(Enum):
        A = "a"
        B = 2  # str + int members → no single storage type

    assert list(rule(_type_ctx(Mixed, ["String"]))) == []
    assert list(rule(_type_ctx(Mixed, ["Long"]))) == []


# ---------------------------------------------------------------------------
# End-to-end: enum-typed property through compare_profile_to_definition
#
# The user-facing contract: when a property is declared as an enum, comparison
# must flag both sides of the value-coverage question and must NOT raise a
# spurious type mismatch:
#   * observed value not in the enum  → UNDECLARED_PROPERTY_VALUE (WARNING, severe)
#   * declared value never observed   → UNOBSERVED_PROPERTY_VALUE (INFO, benign)
#   * enum stored as its scalar       → no PROPERTY_TYPE_MISMATCH
# ---------------------------------------------------------------------------


def test_e2e_enum_property_flags_both_coverage_directions_no_type_mismatch():
    """compare_profile_to_definition surfaces both coverage signals for an enum."""
    import enum

    from orthograph.comparison.engine import compare_profile_to_definition

    class Genre(str, enum.Enum):
        DRAMA = "drama"
        ACTION = "action"
        COMEDY = "comedy"

    class Movie(NodeModel):
        __label__ = "Movie"
        __uid_field__ = "title"
        title: str
        genre: Genre

    model = GraphDefinition(name="Films", node_types=[Movie], relationship_types=[])

    # Observed: drama + action present; 'romance' undeclared; 'comedy' never seen.
    profile = GraphProfile(
        source="test",
        node_type_profiles={
            "Movie": NodeTypeProfile(
                label="Movie",
                count=10,
                property_profiles={
                    "title": PropertyProfile(
                        name="title",
                        present_count=10,
                        total_count=10,
                        observed_types=["String"],
                        constraint_required=True,
                    ),
                    "genre": PropertyProfile(
                        name="genre",
                        present_count=10,
                        total_count=10,
                        observed_types=["String"],  # enum stored as its scalar
                        constraint_required=True,
                        value_distribution=BoundedDistribution(
                            count=10,
                            histogram={"drama": 5, "action": 3, "romance": 2},
                            sample_complete=True,
                        ),
                    ),
                },
            ),
        },
    )

    result = compare_profile_to_definition(profile, model)
    codes = [
        (i.code, i.severity) for i in result.issues if i.entity_id == "Movie.genre"
    ]

    # The severe direction: observed 'romance' is not in the enum.
    assert ("UNDECLARED_PROPERTY_VALUE", Severity.WARNING) in codes
    # The benign direction: declared 'comedy' was never observed.
    assert ("UNOBSERVED_PROPERTY_VALUE", Severity.INFO) in codes
    # No spurious structural mismatch for an enum stored as a String.
    assert not any(c == "PROPERTY_TYPE_MISMATCH" for c, _ in codes)
    # UNDECLARED is the only error-or-warning-severity finding for genre values.
    assert {c for c, s in codes if s in (Severity.ERROR, Severity.WARNING)} == {
        "UNDECLARED_PROPERTY_VALUE"
    }


# ---------------------------------------------------------------------------
# Total count is diff-only — never a profile↔description finding (ADR-034 §6)
# ---------------------------------------------------------------------------


def test_total_count_never_produces_description_finding():
    """compare_profile_to_definition must never emit a count-delta finding.

    Profile node counts differ wildly from any notion the model could carry,
    yet no COUNT_* code may appear.
    """
    from orthograph.comparison.engine import compare_profile_to_definition

    profile = GraphProfile(
        source="test",
        node_type_profiles={
            "Person": NodeTypeProfile(
                label="Person",
                count=999_999,
                property_profiles={
                    "name": PropertyProfile(
                        name="name",
                        present_count=999_999,
                        total_count=999_999,
                        observed_types=["String"],
                    ),
                },
            ),
            "Movie": NodeTypeProfile(
                label="Movie",
                count=1,
                property_profiles={
                    "title": PropertyProfile(
                        name="title",
                        present_count=1,
                        total_count=1,
                        observed_types=["String"],
                    ),
                },
            ),
        },
        rel_type_profiles={
            "ACTED_IN": RelationshipTypeProfile(
                rel_type="ACTED_IN",
                count=42,
                source_labels={"Person"},
                target_labels={"Movie"},
                cardinality_stats=CardinalityStats(count=2, min=1, max=3, mean=2.0),
            ),
        },
    )
    result = compare_profile_to_definition(profile, _STD_MODEL)
    count_codes = [i.code for i in result.issues if "COUNT" in i.code]
    assert count_codes == [], f"count must be diff-only; got {count_codes}"


# ---------------------------------------------------------------------------
# standard_rules() — updated membership
# ---------------------------------------------------------------------------


def test_standard_rules_includes_e45_4_rules():
    keys = {r.key for r in standard_rules()}
    assert "property.constraint_presence" in keys
    assert "property.enum_value" in keys


# ===========================================================================
# E41.5 — CardinalityViolationRule: per-pair enforcement of conditional bounds
#
# Implements the cardinality rows of the ADR-034 §8 comparison matrix.  When
# the declared side is ConditionalCardinality and the observed profile carries
# ``partitioned_cardinality``, each declared rule's bound is enforced against
# the matching observed partition (full bound via spec.contains, both min and
# max — aligned with the in-memory per-node verdict, E41.5).  When the
# breakdown is absent, the E40.7 CARDINALITY_UNVERIFIABLE fallback is kept.
# ===========================================================================


def _partition(source_value: str | None, target_value: str | None) -> str:
    """Shorthand for the observed partition dict key (str(PartitionKey))."""
    return str(PartitionKey(source_value=source_value, target_value=target_value))


def _e415_ctx(rel_profile: RelationshipTypeProfile, **kwargs: Any) -> RuleContext:
    """Build a RuleContext over the conditional model + a given profile."""
    profile = GraphProfile(
        source="e415_test",
        node_type_profiles={
            "Operation": NodeTypeProfile(label="Operation", count=1),
            "Sample": NodeTypeProfile(label="Sample", count=2),
        },
        rel_type_profiles={"HAS_OUTPUT": rel_profile},
    )
    return RuleContext(
        left_graph=DefinitionView(_E407_MODEL),
        right_graph=ProfileView(profile),
        address="HAS_OUTPUT",
        left=_HasOutputConditional,
        right=rel_profile,
        **kwargs,
    )


def _e415_profile(
    partitioned_cardinality: dict[str, BoundedDistribution] | None,
) -> RelationshipTypeProfile:
    """A HAS_OUTPUT profile with the given source-side partitioned breakdown."""
    return RelationshipTypeProfile(
        rel_type="HAS_OUTPUT",
        count=2,
        source_labels={"Operation"},
        target_labels={"Sample"},
        cardinality_stats=CardinalityStats(count=1, min=1, max=2, mean=1.5),
        source_partitioned_cardinality=partitioned_cardinality,
    )


def test_cardinality_conditional_within_bounds_no_violation():
    """Conditional declared + matching partition within bounds → no violation."""
    rule = CardinalityViolationRule()
    # subsampling->subsampling declared 1..2; observed degree 2 is within bounds.
    rtp = _e415_profile(
        {
            _partition("subsampling", "subsampling"): BoundedDistribution(
                count=1, min=2, max=2, mean=2.0
            ),
        }
    )
    issues = list(rule(_e415_ctx(rtp)))
    assert [i.code for i in issues if i.code == "CARDINALITY_VIOLATION"] == []


def test_cardinality_conditional_partition_out_of_bounds_violation():
    """A partition out of bounds → CARDINALITY_VIOLATION (ERROR) naming the pair."""
    rule = CardinalityViolationRule()
    # subsampling->subsampling declared 1..2; observed max 3 exceeds the bound.
    rtp = _e415_profile(
        {
            _partition("subsampling", "subsampling"): BoundedDistribution(
                count=1, min=3, max=3, mean=3.0
            ),
        }
    )
    issues = [i for i in rule(_e415_ctx(rtp)) if i.code == "CARDINALITY_VIOLATION"]
    assert len(issues) == 1
    assert issues[0].severity == Severity.ERROR
    assert issues[0].entity_type == EntityType.RELATIONSHIP
    assert issues[0].entity_id == "HAS_OUTPUT"
    assert issues[0].context["source_value"] == "subsampling"
    assert issues[0].context["target_value"] == "subsampling"


def test_cardinality_conditional_absent_partition_min_violation():
    """A declared partition absent from the breakdown with min>0 → violation (0)."""
    rule = CardinalityViolationRule()
    # subsampling->subsampling declared 1..2 but never observed; degree 0 < min 1.
    rtp = _e415_profile(
        {
            _partition("nothing", "nothing"): BoundedDistribution(
                count=1, min=0, max=0, mean=0.0
            ),
        }
    )
    issues = [i for i in rule(_e415_ctx(rtp)) if i.code == "CARDINALITY_VIOLATION"]
    assert any(
        i.context.get("source_value") == "subsampling"
        and i.context.get("target_value") == "subsampling"
        for i in issues
    )


def test_cardinality_conditional_no_breakdown_unverifiable():
    """Profile without partitioned_cardinality → CARDINALITY_UNVERIFIABLE INFO."""
    rule = CardinalityViolationRule()
    rtp = _e415_profile(None)
    issues = list(rule(_e415_ctx(rtp)))
    assert len(issues) == 1
    assert issues[0].code == "CARDINALITY_UNVERIFIABLE"
    assert issues[0].severity == Severity.INFO


def test_cardinality_conditional_unmatched_kind_info():
    """An observed partition matching no declared rule → CARDINALITY_UNMATCHED_KIND."""
    rule = CardinalityViolationRule()
    # subsampling->subsampling (declared 1..2) satisfied; 'nothing' matches no rule
    # and the default 0..* admits degree 1, so no default-floor violation fires.
    rtp = _e415_profile(
        {
            _partition("subsampling", "subsampling"): BoundedDistribution(
                count=1, min=2, max=2, mean=2.0
            ),
            _partition("nothing", "nothing"): BoundedDistribution(
                count=1, min=1, max=1, mean=1.0
            ),
        }
    )
    issues = list(rule(_e415_ctx(rtp)))
    unmatched = [i for i in issues if i.code == "CARDINALITY_UNMATCHED_KIND"]
    assert len(unmatched) == 1
    assert unmatched[0].severity == Severity.INFO
    assert "CARDINALITY_VIOLATION" not in {i.code for i in issues}


def test_cardinality_conditional_unmatched_kind_default_floor_violation():
    """Unmatched-kind partition with min>0 default + zero degree → default-floor ERROR.

    Uses a conditional whose default is ``1..*`` so an unmatched node with zero
    observed degree violates the default (mirrors validation._default_floor_issue
    / E40.5).
    """

    class _HasOutputFloorDefault(RelationshipModel):
        __label__ = "HAS_OUTPUT_FLOOR"
        __source_label__ = "Operation"
        __target_label__ = "Sample"
        __source_cardinality__ = ConditionalCardinality(
            rules=(
                ConditionalRule(
                    source=PropMatch({"kind": "subsampling"}),
                    target=PropMatch({"kind": "subsampling"}),
                    spec=CardinalitySpec(min=1, max=2),
                ),
            ),
            default="1..*",
        )

    model = GraphDefinition(
        name="e415_floor",
        node_types=[_OperationNode, _SampleNode],
        relationship_types=[_HasOutputFloorDefault],
    )
    rule = CardinalityViolationRule()
    rtp = RelationshipTypeProfile(
        rel_type="HAS_OUTPUT_FLOOR",
        count=0,
        source_labels={"Operation"},
        target_labels={"Sample"},
        cardinality_stats=CardinalityStats(count=1, min=0, max=0, mean=0.0),
        source_partitioned_cardinality={
            _partition("nothing", "nothing"): BoundedDistribution(
                count=1, min=0, max=0, mean=0.0
            ),
        },
    )
    ctx = RuleContext(
        left_graph=DefinitionView(model),
        right_graph=ProfileView(
            GraphProfile(
                source="e415_floor", rel_type_profiles={"HAS_OUTPUT_FLOOR": rtp}
            )
        ),
        address="HAS_OUTPUT_FLOOR",
        left=_HasOutputFloorDefault,
        right=rtp,
    )
    issues = list(rule(ctx))
    codes = {i.code for i in issues}
    assert "CARDINALITY_UNMATCHED_KIND" in codes
    floor = [
        i
        for i in issues
        if i.code == "CARDINALITY_VIOLATION" and i.context.get("default") is True
    ]
    assert len(floor) == 1
    assert floor[0].severity == Severity.ERROR


def _floor_default_model(
    default: str,
) -> tuple[GraphDefinition, type[RelationshipModel]]:
    """Operation -[HAS_OUTPUT_FLOOR]-> Sample with a conditional source side.

    The single rule pins subsampling->subsampling = 1..2; the supplied default
    governs any source node whose kind matches no rule.
    """

    class _HasOutputFloor(RelationshipModel):
        __label__ = "HAS_OUTPUT_FLOOR"
        __source_label__ = "Operation"
        __target_label__ = "Sample"
        __source_cardinality__ = ConditionalCardinality(
            rules=(
                ConditionalRule(
                    source=PropMatch({"kind": "subsampling"}),
                    target=PropMatch({"kind": "subsampling"}),
                    spec=CardinalitySpec(min=1, max=2),
                ),
            ),
            default=default,
        )

    model = GraphDefinition(
        name="e415_floor_multi",
        node_types=[_OperationNode, _SampleNode],
        relationship_types=[_HasOutputFloor],
    )
    return model, _HasOutputFloor


def _floor_ctx(
    model: GraphDefinition,
    rt_class: type[RelationshipModel],
    partitioned: dict[str, BoundedDistribution],
) -> RuleContext:
    rtp = RelationshipTypeProfile(
        rel_type="HAS_OUTPUT_FLOOR",
        count=sum(int(d.max or 0) for d in partitioned.values()),
        source_labels={"Operation"},
        target_labels={"Sample"},
        cardinality_stats=CardinalityStats(count=1, min=0, max=2, mean=1.0),
        source_partitioned_cardinality=partitioned,
    )
    return RuleContext(
        left_graph=DefinitionView(model),
        right_graph=ProfileView(
            GraphProfile(
                source="e415_floor_multi", rel_type_profiles={"HAS_OUTPUT_FLOOR": rtp}
            )
        ),
        address="HAS_OUTPUT_FLOOR",
        left=rt_class,
        right=rtp,
    )


def test_cardinality_default_floor_uses_total_across_partitions_no_violation():
    """An unmatched value spanning two partitions is floored on its TOTAL degree.

    default = 2..*; an unmatched source value 'nothing' has one edge to a
    subsampling target and one to a nothing target → two partitions, each degree
    1, total 2 → satisfies 2..*.  Parity with the in-memory per-node floor, which
    checks the node's total side degree, not each partition independently
    (finding 1).  A single drift INFO is emitted and no default-floor ERROR.
    """
    model, rt_class = _floor_default_model("2..*")
    rule = CardinalityViolationRule()
    partitioned = {
        _partition("nothing", "subsampling"): BoundedDistribution(
            count=1, min=1, max=1, mean=1.0
        ),
        _partition("nothing", "nothing"): BoundedDistribution(
            count=1, min=1, max=1, mean=1.0
        ),
    }
    issues = list(rule(_floor_ctx(model, rt_class, partitioned)))
    unmatched = [i for i in issues if i.code == "CARDINALITY_UNMATCHED_KIND"]
    floor = [
        i
        for i in issues
        if i.code == "CARDINALITY_VIOLATION" and i.context.get("default") is True
    ]
    # One drift signal for the single unmatched value 'nothing'; no false floor.
    assert len(unmatched) == 1
    assert floor == []


def test_cardinality_default_floor_uses_total_across_partitions_violation():
    """The summed total below the floor → exactly one default-floor ERROR.

    default = 3..*; the same 'nothing' value spans two partitions totalling 2 <
    3 → one CARDINALITY_VIOLATION (not one per partition).
    """
    model, rt_class = _floor_default_model("3..*")
    rule = CardinalityViolationRule()
    partitioned = {
        _partition("nothing", "subsampling"): BoundedDistribution(
            count=1, min=1, max=1, mean=1.0
        ),
        _partition("nothing", "nothing"): BoundedDistribution(
            count=1, min=1, max=1, mean=1.0
        ),
    }
    issues = list(rule(_floor_ctx(model, rt_class, partitioned)))
    floor = [
        i
        for i in issues
        if i.code == "CARDINALITY_VIOLATION" and i.context.get("default") is True
    ]
    assert len(floor) == 1
    assert floor[0].severity == Severity.ERROR
    assert floor[0].context["observed_min"] == 2


def test_cardinality_constant_max_exceeded_violation():
    """Constant finite-max spec with observed aggregate max over the bound → ERROR.

    Aggregate path now checks the full bound (both min and max) via
    spec.contains() — aligned with the in-memory per-node verdict (E41.5).
    """

    class _BoundedRel(RelationshipModel):
        __label__ = "BOUNDED"
        __source_label__ = "Operation"
        __target_label__ = "Sample"
        __source_cardinality__ = "1..2"

    model = GraphDefinition(
        name="e415_bounded",
        node_types=[_OperationNode, _SampleNode],
        relationship_types=[_BoundedRel],
    )
    rule = CardinalityViolationRule()
    rtp = RelationshipTypeProfile(
        rel_type="BOUNDED",
        count=3,
        source_labels={"Operation"},
        target_labels={"Sample"},
        # min 1 is within 1..2, but max 3 exceeds it.
        cardinality_stats=CardinalityStats(count=2, min=1, max=3, mean=2.0),
    )
    ctx = RuleContext(
        left_graph=DefinitionView(model),
        right_graph=ProfileView(
            GraphProfile(source="e415_bounded", rel_type_profiles={"BOUNDED": rtp})
        ),
        address="BOUNDED",
        left=_BoundedRel,
        right=rtp,
    )
    issues = [i for i in rule(ctx) if i.code == "CARDINALITY_VIOLATION"]
    assert len(issues) == 1
    assert issues[0].severity == Severity.ERROR


# ===========================================================================
# both-endpoint conditional cardinality: enforce each side independently
# ===========================================================================


def _both_sides_model() -> tuple[GraphDefinition, type[RelationshipModel]]:
    """Operation -[MAKES]-> Sample, conditional on BOTH endpoints.

    Source side: (assembler, final) = 2..2.  Target side: (assembler, final) =
    1..1.  Both discriminate on ``kind`` per the absolute convention.
    """

    source_card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "assembler"}),
                target=PropMatch({"kind": "final"}),
                spec=CardinalitySpec(min=2, max=2),
            ),
        ),
        default="0..*",
    )
    target_card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "assembler"}),
                target=PropMatch({"kind": "final"}),
                spec=CardinalitySpec(min=1, max=1),
            ),
        ),
        default="0..*",
    )

    class _Makes(RelationshipModel):
        __label__ = "MAKES"
        __source_label__ = "Operation"
        __target_label__ = "Sample"
        __source_cardinality__ = source_card
        __target_cardinality__ = target_card

    model = GraphDefinition(
        name="e417_both",
        node_types=[_OperationNode, _SampleNode],
        relationship_types=[_Makes],
    )
    return model, _Makes


def _both_sides_ctx(
    model: GraphDefinition,
    rt_class: type[RelationshipModel],
    source_partitioned: dict[str, BoundedDistribution] | None,
    target_partitioned: dict[str, BoundedDistribution] | None,
) -> RuleContext:
    rtp = RelationshipTypeProfile(
        rel_type="MAKES",
        count=2,
        source_labels={"Operation"},
        target_labels={"Sample"},
        cardinality_stats=CardinalityStats(count=1, min=1, max=2, mean=1.5),
        source_partitioned_cardinality=source_partitioned,
        target_partitioned_cardinality=target_partitioned,
    )
    return RuleContext(
        left_graph=DefinitionView(model),
        right_graph=ProfileView(
            GraphProfile(source="e417_both", rel_type_profiles={"MAKES": rtp})
        ),
        address="MAKES",
        left=rt_class,
        right=rtp,
    )


def test_cardinality_both_sides_one_violating_yields_one_violation():
    """Both-sides conditional, source in bounds, target violating → one ERROR.

    E41.7: each conditional side is enforced independently; only the breaching
    side yields a violation.
    """
    model, rt_class = _both_sides_model()
    rule = CardinalityViolationRule()
    pair = _partition("assembler", "final")
    issues = list(
        rule(
            _both_sides_ctx(
                model,
                rt_class,
                # Source side within 2..2.
                source_partitioned={
                    pair: BoundedDistribution(count=1, min=2, max=2, mean=2.0)
                },
                # Target side declares 1..1 but observed 2 → violation.
                target_partitioned={
                    pair: BoundedDistribution(count=2, min=2, max=2, mean=2.0)
                },
            )
        )
    )
    violations = [i for i in issues if i.code == "CARDINALITY_VIOLATION"]
    assert len(violations) == 1
    assert violations[0].severity == Severity.ERROR
    # The violation names the target-side partition (the side that breached).
    assert violations[0].context["source_value"] == "assembler"
    assert violations[0].context["target_value"] == "final"


def test_cardinality_both_sides_both_in_bounds_no_violation():
    """Both-sides conditional, both sides within bounds → no violation (E41.7)."""
    model, rt_class = _both_sides_model()
    rule = CardinalityViolationRule()
    pair = _partition("assembler", "final")
    issues = list(
        rule(
            _both_sides_ctx(
                model,
                rt_class,
                source_partitioned={
                    pair: BoundedDistribution(count=1, min=2, max=2, mean=2.0)
                },
                target_partitioned={
                    pair: BoundedDistribution(count=2, min=1, max=1, mean=1.0)
                },
            )
        )
    )
    assert [i for i in issues if i.code == "CARDINALITY_VIOLATION"] == []


def test_cardinality_both_sides_target_absent_is_unverifiable_for_that_side():
    """A both-sides type with only the source breakdown present (E41.7).

    The source side is enforced (in bounds → silent); the target side has no
    breakdown → exactly one CARDINALITY_UNVERIFIABLE INFO for the target side,
    never a false verdict.  This is the regression guard for single-side profiles
    behaving as in E41.5.
    """
    model, rt_class = _both_sides_model()
    rule = CardinalityViolationRule()
    pair = _partition("assembler", "final")
    issues = list(
        rule(
            _both_sides_ctx(
                model,
                rt_class,
                source_partitioned={
                    pair: BoundedDistribution(count=1, min=2, max=2, mean=2.0)
                },
                target_partitioned=None,
            )
        )
    )
    unverifiable = [i for i in issues if i.code == "CARDINALITY_UNVERIFIABLE"]
    assert len(unverifiable) == 1
    assert unverifiable[0].severity == Severity.INFO
    assert "CARDINALITY_VIOLATION" not in {i.code for i in issues}
