"""Unit tests for the Rule abstraction and standard rule set (ADR-015 §4,
Phase C1 + C2).

C1 tests cover:
* RuleContext construction and field access.
* The Rule Protocol — isinstance check via runtime_checkable.
* A minimal concrete rule satisfies the Protocol and produces issues.
* A rule that yields no issues when the constraint is satisfied.
* RuleContext defaults (left/right None, extra empty dict).

C2 tests cover:
* Each standard rule emits the exact code + severity as its legacy _check_*
  counterpart (hard constraint — ADR-015).
* Satisfaction path: rule emits no issues when constraint is met.
* standard_rules() returns all ten rule instances in order.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from orthograph.comparison.rules import (
    CardinalityViolationRule,
    InvalidEndpointRule,
    MissingNodeLabelRule,
    MissingPropertyRule,
    MissingRelTypeRule,
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
    Cardinality,
    NodeModel,
    RelationshipModel,
)
from orthograph.graph_profile.models import (
    CardinalityStats,
    GraphProfile,
    NodeTypeProfile,
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
    __source_cardinality__ = Cardinality.ONE_OR_MORE


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
            cardinality_stats=CardinalityStats(
                min_degree=1, max_degree=3, avg_degree=1.5, sample_size=2
            ),
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
    # _ActedIn has source_cardinality ONE_OR_MORE (min=1); min_degree=0 violates
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=2,
        source_labels={"Person"},
        target_labels={"Movie"},
        cardinality_stats=CardinalityStats(
            min_degree=0, max_degree=3, avg_degree=1.5, sample_size=2
        ),
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
        cardinality_stats=CardinalityStats(
            min_degree=1, max_degree=3, avg_degree=2.0, sample_size=2
        ),
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


def test_standard_rules_returns_ten_rules():
    rules = standard_rules()
    assert len(rules) == 10


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

    # Total: 2 issues — 1 from standard rules, 1 from the injected Case-B rule
    assert len(result.issues) == 2, (
        f"Expected exactly 2 issues total; got {len(result.issues)}: "
        + str([(i.code, i.entity_id) for i in result.issues])
    )
