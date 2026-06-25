"""Unit tests for the symmetric diff rule family.

One focused test per rule — mirrors ``test_rules.py`` style.

Coverage:
- ``only_in_left`` and ``only_in_right`` for node label, rel type, property.
- ``PROPERTY_TYPE_CHANGED`` for both the ``TypeInfo`` (definition↔definition)
  and ``PropertyProfile`` (profile↔profile) shapes.
- ``ENDPOINTS_CHANGED`` fires **only** for the definition ``__directed__``-flag
  delta (it is silent for profiles; endpoint-label differences surface as
  ``REL_TYPE_ONLY_IN_LEFT``/``_RIGHT``).
- ``CARDINALITY_CHANGED`` for both profile and definition shapes.
- No-op guards: wrong address type, both-sides-present, both-sides-absent,
  mixed-shape for PropertyTypeChangedRule.
- ``diff_rules()`` factory returns the ten rules in spec order.
- Every emitted issue has ``Severity.INFO``.
"""

from typing import Any, Optional

from orthograph.comparison.diff_rules import (
    CardinalityChangedRule,
    CountChangedRule,
    EndpointsChangedRule,
    NodeLabelOnlyInLeftRule,
    NodeLabelOnlyInRightRule,
    PartitionedCardinalityChangedRule,
    PropertyOnlyInLeftRule,
    PropertyOnlyInRightRule,
    PropertyTypeChangedRule,
    RelTypeOnlyInLeftRule,
    RelTypeOnlyInRightRule,
    diff_rules,
)
from orthograph.comparison.rules import Rule, RuleContext
from orthograph.comparison.views import DefinitionView, ProfileView
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
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
    PartitionedCardinalityRow,
    PartitionKey,
    PropertyProfile,
    RelationshipTypeProfile,
)


# ---------------------------------------------------------------------------
# Minimal fixtures used throughout
# ---------------------------------------------------------------------------


class _PersonNode(NodeModel):
    __label__ = "Person"
    name: str
    age: Optional[int] = None


class _MovieNode(NodeModel):
    __label__ = "Movie"
    title: str


class _CityNode(NodeModel):
    __label__ = "City"
    name: str


class _DirectorNode(NodeModel):
    __label__ = "Director"
    name: str


class _FilmNode(NodeModel):
    __label__ = "Film"
    title: str


class _ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    role: str


class _ActedInAlt(RelationshipModel):
    """ACTED_IN with different endpoints (Director → Film)."""

    __label__ = "ACTED_IN"
    __source_label__ = "Director"
    __target_label__ = "Film"


class _ActedInUndirected(RelationshipModel):
    """ACTED_IN with the same endpoints as _ActedIn but undirected.

    Same identity triple (Person:ACTED_IN:Movie); only ``__directed__`` differs,
    so EndpointsChangedRule must surface it as a direction-flag delta.
    """

    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    __directed__ = False


class _LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "City"
    __source_cardinality__ = "1..1"


class _LivesInLoose(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "City"
    __source_cardinality__ = "0..*"


class _LivesInConditional(RelationshipModel):
    """LIVES_IN whose source cardinality is conditional (default ONE_OR_MORE)."""

    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "City"
    __source_cardinality__ = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "vip"}),
                target=PropMatch(),
                spec="0..1",
            ),
        ),
        default="1..*",
    )


# GD that includes all node types so referential integrity holds
_GD_LEFT = GraphDefinition(
    name="left",
    node_types=[_PersonNode, _MovieNode, _CityNode],
    relationship_types=[_ActedIn, _LivesIn],
)

_GD_RIGHT = GraphDefinition(
    name="right",
    node_types=[_PersonNode, _MovieNode],
    relationship_types=[_ActedIn],
)

# Definitions for endpoint-changed test (Director/Film nodes required)
_GD_ALT = GraphDefinition(
    name="alt",
    node_types=[_DirectorNode, _FilmNode],
    relationship_types=[_ActedInAlt],
)

# Definitions for cardinality-changed test
_GD_STRICT_CARD = GraphDefinition(
    name="strict",
    node_types=[_PersonNode, _CityNode],
    relationship_types=[_LivesIn],
)

_GD_LOOSE_CARD = GraphDefinition(
    name="loose",
    node_types=[_PersonNode, _CityNode],
    relationship_types=[_LivesInLoose],
)

_GP_EMPTY = GraphProfile(source="empty")

_GP_PERSON = GraphProfile(
    source="person_only",
    node_type_profiles={"Person": NodeTypeProfile(label="Person", count=5)},
)


def _def_view(gd: GraphDefinition) -> DefinitionView:
    return DefinitionView(gd)


def _prof_view(gp: GraphProfile) -> ProfileView:
    return ProfileView(gp)


def _ctx(
    left=None,
    right=None,
    address: str = "SomeLabel",
    extra: dict[str, Any] | None = None,
    *,
    left_gd: GraphDefinition = _GD_LEFT,
    right_gd: GraphDefinition = _GD_LEFT,
) -> RuleContext:
    """Build a RuleContext backed by DefinitionViews (convenient for most tests)."""
    return RuleContext(
        left_graph=_def_view(left_gd),
        right_graph=_def_view(right_gd),
        address=address,
        left=left,
        right=right,
        extra=extra or {},
    )


def _pctx(
    left=None,
    right=None,
    address: str = "SomeLabel",
    extra: dict[str, Any] | None = None,
    *,
    left_gp: GraphProfile = _GP_EMPTY,
    right_gp: GraphProfile = _GP_EMPTY,
) -> RuleContext:
    """Build a RuleContext backed by ProfileViews."""
    return RuleContext(
        left_graph=_prof_view(left_gp),
        right_graph=_prof_view(right_gp),
        address=address,
        left=left,
        right=right,
        extra=extra or {},
    )


_PROP_EXTRA_NODE = {
    "label": "Person",
    "prop_name": "name",
    "entity_type": EntityType.NODE,
}

_PROP_EXTRA_REL = {
    "label": "ACTED_IN",
    "prop_name": "role",
    "entity_type": EntityType.RELATIONSHIP,
}


# ---------------------------------------------------------------------------
# diff_rules() factory
# ---------------------------------------------------------------------------


def test_diff_rules_returns_eleven_rules():
    rules = diff_rules()
    assert len(rules) == 11


def test_diff_rules_order():
    """Verify keys in the spec-mandated order."""
    expected = [
        "diff.node_label.only_in_left",
        "diff.node_label.only_in_right",
        "diff.rel_type.only_in_left",
        "diff.rel_type.only_in_right",
        "diff.property.only_in_left",
        "diff.property.only_in_right",
        "diff.property.type_changed",
        "diff.rel.endpoints_changed",
        "diff.rel.cardinality_changed",
        "diff.rel.partitioned_cardinality_changed",
        "diff.count_changed",
    ]
    assert [r.key for r in diff_rules()] == expected


def test_diff_rules_all_satisfy_rule_protocol():
    for rule in diff_rules():
        assert isinstance(rule, Rule), f"{rule.key} does not satisfy Rule protocol"


# ---------------------------------------------------------------------------
# NodeLabelOnlyInLeftRule
# ---------------------------------------------------------------------------


def test_node_label_only_in_left_fires():
    rule = NodeLabelOnlyInLeftRule()
    # left = NodeTypeProfile present, right = None  (left-only node label)
    ntp = NodeTypeProfile(label="Person", count=3)
    ctx = _pctx(
        left=ntp, right=None, address="Person", extra={"address_type": "node_label"}
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "NODE_LABEL_ONLY_IN_LEFT"
    assert issue.severity == Severity.INFO
    assert issue.entity_type == EntityType.NODE
    assert issue.entity_id == "Person"


def test_node_label_only_in_left_noop_when_right_present():
    rule = NodeLabelOnlyInLeftRule()
    ntp = NodeTypeProfile(label="Person", count=3)
    ctx = _pctx(left=ntp, right=ntp, address="Person")
    assert list(rule(ctx)) == []


def test_node_label_only_in_left_noop_when_both_absent():
    rule = NodeLabelOnlyInLeftRule()
    ctx = _pctx(left=None, right=None, address="Ghost")
    assert list(rule(ctx)) == []


def test_node_label_only_in_left_noop_for_property_address():
    rule = NodeLabelOnlyInLeftRule()
    ntp = NodeTypeProfile(label="Person", count=3)
    ctx = _pctx(left=ntp, right=None, address="Person.name", extra=_PROP_EXTRA_NODE)
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# NodeLabelOnlyInRightRule
# ---------------------------------------------------------------------------


def test_node_label_only_in_right_fires():
    rule = NodeLabelOnlyInRightRule()
    ntp = NodeTypeProfile(label="City", count=1)
    ctx = _pctx(
        left=None, right=ntp, address="City", extra={"address_type": "node_label"}
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "NODE_LABEL_ONLY_IN_RIGHT"
    assert issues[0].severity == Severity.INFO
    assert issues[0].entity_type == EntityType.NODE


def test_node_label_only_in_right_noop_when_left_present():
    rule = NodeLabelOnlyInRightRule()
    ntp = NodeTypeProfile(label="City", count=1)
    ctx = _pctx(left=ntp, right=ntp, address="City")
    assert list(rule(ctx)) == []


def test_node_label_only_in_right_noop_for_property_address():
    rule = NodeLabelOnlyInRightRule()
    ntp = NodeTypeProfile(label="Person", count=3)
    ctx = _pctx(left=None, right=ntp, address="Person.name", extra=_PROP_EXTRA_NODE)
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# RelTypeOnlyInLeftRule
# ---------------------------------------------------------------------------


def test_rel_type_only_in_left_fires_profile():
    rule = RelTypeOnlyInLeftRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(
        left=rtp, right=None, address="ACTED_IN", extra={"address_type": "rel_type"}
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "REL_TYPE_ONLY_IN_LEFT"
    assert issues[0].severity == Severity.INFO
    assert issues[0].entity_type == EntityType.RELATIONSHIP


def test_rel_type_only_in_left_fires_definition():
    rule = RelTypeOnlyInLeftRule()
    ctx = _ctx(
        left=_ActedIn,
        right=None,
        address="ACTED_IN",
        extra={"address_type": "rel_type"},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "REL_TYPE_ONLY_IN_LEFT"


def test_rel_type_only_in_left_noop_when_right_present():
    rule = RelTypeOnlyInLeftRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(left=rtp, right=rtp, address="ACTED_IN")
    assert list(rule(ctx)) == []


def test_rel_type_only_in_left_noop_for_property_address():
    rule = RelTypeOnlyInLeftRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(left=rtp, right=None, address="ACTED_IN.role", extra=_PROP_EXTRA_REL)
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# RelTypeOnlyInRightRule
# ---------------------------------------------------------------------------


def test_rel_type_only_in_right_fires_profile():
    rule = RelTypeOnlyInRightRule()
    rtp = RelationshipTypeProfile(
        rel_type="DIRECTED", count=2, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(
        left=None, right=rtp, address="DIRECTED", extra={"address_type": "rel_type"}
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "REL_TYPE_ONLY_IN_RIGHT"
    assert issues[0].severity == Severity.INFO


def test_rel_type_only_in_right_fires_definition():
    rule = RelTypeOnlyInRightRule()
    ctx = _ctx(
        left=None,
        right=_ActedIn,
        address="ACTED_IN",
        extra={"address_type": "rel_type"},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "REL_TYPE_ONLY_IN_RIGHT"


def test_rel_type_only_in_right_noop_when_left_present():
    rule = RelTypeOnlyInRightRule()
    rtp = RelationshipTypeProfile(
        rel_type="DIRECTED", count=2, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(left=rtp, right=rtp, address="DIRECTED")
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# PropertyOnlyInLeftRule
# ---------------------------------------------------------------------------


def test_property_only_in_left_fires_type_info():
    rule = PropertyOnlyInLeftRule()
    ti = TypeInfo(python_type=str, is_required=True)
    ctx = _ctx(left=ti, right=None, address="Person.name", extra=_PROP_EXTRA_NODE)
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_ONLY_IN_LEFT"
    assert issues[0].severity == Severity.INFO
    assert issues[0].entity_type == EntityType.NODE
    assert issues[0].entity_id == "Person.name"


def test_property_only_in_left_fires_property_profile():
    rule = PropertyOnlyInLeftRule()
    pp = PropertyProfile(name="name", present_count=3, total_count=3)
    ctx = _pctx(left=pp, right=None, address="Person.name", extra=_PROP_EXTRA_NODE)
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_ONLY_IN_LEFT"


def test_property_only_in_left_noop_when_right_present():
    rule = PropertyOnlyInLeftRule()
    ti = TypeInfo(python_type=str, is_required=True)
    ctx = _ctx(left=ti, right=ti, address="Person.name", extra=_PROP_EXTRA_NODE)
    assert list(rule(ctx)) == []


def test_property_only_in_left_noop_no_prop_name():
    """Non-property address (no prop_name in extra) must be ignored."""
    rule = PropertyOnlyInLeftRule()
    ntp = NodeTypeProfile(label="Person", count=3)
    ctx = _pctx(left=ntp, right=None, address="Person")
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# PropertyOnlyInRightRule
# ---------------------------------------------------------------------------


def test_property_only_in_right_fires():
    rule = PropertyOnlyInRightRule()
    ti = TypeInfo(python_type=int, is_required=False)
    extra = {"label": "Person", "prop_name": "age", "entity_type": EntityType.NODE}
    ctx = _ctx(left=None, right=ti, address="Person.age", extra=extra)
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_ONLY_IN_RIGHT"
    assert issues[0].severity == Severity.INFO
    assert issues[0].entity_id == "Person.age"


def test_property_only_in_right_noop_when_left_present():
    rule = PropertyOnlyInRightRule()
    ti = TypeInfo(python_type=int, is_required=False)
    ctx = _ctx(left=ti, right=ti, address="Person.age", extra=_PROP_EXTRA_NODE)
    assert list(rule(ctx)) == []


def test_property_only_in_right_noop_no_prop_name():
    rule = PropertyOnlyInRightRule()
    ntp = NodeTypeProfile(label="Person", count=3)
    ctx = _pctx(left=None, right=ntp, address="Person")
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# PropertyTypeChangedRule — TypeInfo shape (definition ↔ definition)
# ---------------------------------------------------------------------------


def test_property_type_changed_fires_type_info():
    rule = PropertyTypeChangedRule()
    ti_left = TypeInfo(python_type=str, is_required=True)
    ti_right = TypeInfo(python_type=int, is_required=True)
    ctx = _ctx(
        left=ti_left, right=ti_right, address="Person.name", extra=_PROP_EXTRA_NODE
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_TYPE_CHANGED"
    assert issues[0].severity == Severity.INFO
    assert issues[0].context["left"] is str
    assert issues[0].context["right"] is int


def test_property_type_changed_noop_same_type_info():
    rule = PropertyTypeChangedRule()
    ti = TypeInfo(python_type=str, is_required=True)
    ctx = _ctx(left=ti, right=ti, address="Person.name", extra=_PROP_EXTRA_NODE)
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# PropertyTypeChangedRule — PropertyProfile shape (profile ↔ profile)
# ---------------------------------------------------------------------------


def test_property_type_changed_fires_property_profile():
    rule = PropertyTypeChangedRule()
    pp_left = PropertyProfile(
        name="score", present_count=10, total_count=10, observed_types=["Long"]
    )
    pp_right = PropertyProfile(
        name="score", present_count=10, total_count=10, observed_types=["String"]
    )
    extra = {"label": "Player", "prop_name": "score", "entity_type": EntityType.NODE}
    ctx = _pctx(left=pp_left, right=pp_right, address="Player.score", extra=extra)
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_TYPE_CHANGED"
    assert issues[0].severity == Severity.INFO


def test_property_type_changed_noop_same_property_profile():
    rule = PropertyTypeChangedRule()
    pp = PropertyProfile(
        name="name", present_count=3, total_count=3, observed_types=["String"]
    )
    ctx = _pctx(left=pp, right=pp, address="Person.name", extra=_PROP_EXTRA_NODE)
    assert list(rule(ctx)) == []


def test_property_type_changed_noop_mixed_shape():
    """TypeInfo vs PropertyProfile must not fire (wrong comparison family)."""
    rule = PropertyTypeChangedRule()
    ti = TypeInfo(python_type=str, is_required=True)
    pp = PropertyProfile(
        name="name", present_count=3, total_count=3, observed_types=["String"]
    )
    ctx = RuleContext(
        left_graph=_def_view(_GD_LEFT),
        right_graph=_prof_view(_GP_PERSON),
        address="Person.name",
        left=ti,
        right=pp,
        extra=_PROP_EXTRA_NODE,
    )
    assert list(rule(ctx)) == []


def test_property_type_changed_noop_empty_observed_types():
    """No issue when either side has empty observed_types."""
    rule = PropertyTypeChangedRule()
    pp_left = PropertyProfile(
        name="x", present_count=0, total_count=5, observed_types=[]
    )
    pp_right = PropertyProfile(
        name="x", present_count=5, total_count=5, observed_types=["String"]
    )
    extra = {"label": "X", "prop_name": "x", "entity_type": EntityType.NODE}
    ctx = _pctx(left=pp_left, right=pp_right, address="X.x", extra=extra)
    assert list(rule(ctx)) == []


def test_property_type_changed_noop_no_prop_name():
    rule = PropertyTypeChangedRule()
    ti = TypeInfo(python_type=str, is_required=True)
    ctx = _ctx(left=ti, right=ti, address="Person")
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# EndpointsChangedRule — profile ↔ profile
#
# A profile's source/target labels are part of relationship
# identity (the address), so an endpoint difference is a *different* address and
# surfaces via RelTypeOnlyInLeft/Right — never as ENDPOINTS_CHANGED.  The profile
# carries no direction field, so EndpointsChangedRule is always silent for
# profile ↔ profile.
# ---------------------------------------------------------------------------


def test_endpoints_changed_silent_for_profiles():
    """EndpointsChangedRule never fires for profile operands (endpoints are identity,
    no direction field)."""
    rule = EndpointsChangedRule()
    rtp_left = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, source_label="Person", target_label="Movie"
    )
    rtp_right = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=3, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(
        left=rtp_left,
        right=rtp_right,
        address="Person:ACTED_IN:Movie",
        extra={"address_type": "rel_type"},
    )
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# EndpointsChangedRule — definition ↔ definition
#
# Endpoint labels are identity; only the ``__directed__`` flag remains an
# attribute delta, so ENDPOINTS_CHANGED is trimmed to the direction signal.
# ---------------------------------------------------------------------------


def test_endpoints_changed_fires_directed_flag_definition():
    """Same triple, differing ``__directed__`` → ENDPOINTS_CHANGED (INFO)."""
    rule = EndpointsChangedRule()
    ctx = _ctx(
        left=_ActedIn,
        right=_ActedInUndirected,
        address="Person:ACTED_IN:Movie",
        extra={"address_type": "rel_type"},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "ENDPOINTS_CHANGED"
    assert issues[0].context["role"] == "directed"
    assert issues[0].severity == Severity.INFO


def test_endpoints_changed_silent_for_endpoint_label_difference_definition():
    """A source/target label difference is an identity (address) difference and is
    NOT reported by EndpointsChangedRule (presence rules handle it)."""
    rule = EndpointsChangedRule()
    ctx = _ctx(
        left=_ActedIn,
        right=_ActedInAlt,
        address="Person:ACTED_IN:Movie",
        extra={"address_type": "rel_type"},
    )
    assert list(rule(ctx)) == []


def test_endpoints_changed_noop_identical_definition():
    rule = EndpointsChangedRule()
    ctx = _ctx(
        left=_ActedIn,
        right=_ActedIn,
        address="Person:ACTED_IN:Movie",
        extra={"address_type": "rel_type"},
    )
    assert list(rule(ctx)) == []


def test_endpoints_changed_noop_when_left_absent():
    rule = EndpointsChangedRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(
        left=None,
        right=rtp,
        address="Person:ACTED_IN:Movie",
        extra={"address_type": "rel_type"},
    )
    assert list(rule(ctx)) == []


def test_endpoints_changed_noop_for_property_address():
    rule = EndpointsChangedRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(
        left=rtp, right=rtp, address="Person:ACTED_IN:Movie.role", extra=_PROP_EXTRA_REL
    )
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# CardinalityChangedRule — profile ↔ profile
# ---------------------------------------------------------------------------


def test_cardinality_changed_fires_profile():
    rule = CardinalityChangedRule()
    rtp_left = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=5,
        source_label="Person",
        target_label="Movie",
        cardinality_stats=CardinalityStats(count=5, min=1, max=3, mean=2.0),
    )
    rtp_right = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=5,
        source_label="Person",
        target_label="Movie",
        cardinality_stats=CardinalityStats(count=5, min=2, max=5, mean=3.0),
    )
    ctx = _pctx(
        left=rtp_left,
        right=rtp_right,
        address="ACTED_IN",
        extra={"address_type": "rel_type"},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "CARDINALITY_CHANGED"
    assert issues[0].severity == Severity.INFO


def test_cardinality_changed_noop_identical_stats():
    rule = CardinalityChangedRule()
    stats = CardinalityStats(count=5, min=1, max=3, mean=2.0)
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=5,
        source_label="Person",
        target_label="Movie",
        cardinality_stats=stats,
    )
    ctx = _pctx(
        left=rtp, right=rtp, address="ACTED_IN", extra={"address_type": "rel_type"}
    )
    assert list(rule(ctx)) == []


def test_cardinality_changed_noop_when_stats_none():
    rule = CardinalityChangedRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(
        left=rtp, right=rtp, address="ACTED_IN", extra={"address_type": "rel_type"}
    )
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# PartitionedCardinalityChangedRule — profile ↔ profile
# ---------------------------------------------------------------------------


def _rtp_with_partitions(
    source_rows: list[PartitionedCardinalityRow] | None = None,
    target_rows: list[PartitionedCardinalityRow] | None = None,
) -> RelationshipTypeProfile:
    return RelationshipTypeProfile(
        rel_type="IS_INPUT",
        count=2,
        source_label="Sample",
        target_label="Operation",
        cardinality_stats=CardinalityStats(count=1, min=1, max=2, mean=1.5),
        source_partitioned_cardinality=source_rows,
        target_partitioned_cardinality=target_rows,
    )


def test_partitioned_cardinality_changed_same_partition_differing_stats():
    """Same {"type": "combine"} partition, differing degree stats → one delta."""
    rule = PartitionedCardinalityChangedRule()
    key = PartitionKey(source={}, target={"type": "combine"})
    left = _rtp_with_partitions(
        target_rows=[
            PartitionedCardinalityRow(
                key=key, stats=BoundedDistribution(count=9, min=2, max=3)
            )
        ]
    )
    right = _rtp_with_partitions(
        target_rows=[
            PartitionedCardinalityRow(
                key=key, stats=BoundedDistribution(count=9, min=2, max=5)
            )
        ]
    )
    ctx = _pctx(
        left=left, right=right, address="IS_INPUT", extra={"address_type": "rel_type"}
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PARTITIONED_CARDINALITY_CHANGED"
    assert issues[0].severity == Severity.INFO
    assert issues[0].context["change"] == "stats"
    assert issues[0].context["left_max"] == 3
    assert issues[0].context["right_max"] == 5


def test_partitioned_cardinality_changed_distinct_property_names_not_matched():
    """{"type": "combine"} vs {"stage": "combine"} → distinct (added + removed).

    The name-blindness regression this epic fixes: a value-only key would collide
    these two as one matched (no-change) partition; with name-aware keys they are
    a removed left partition and an added right partition.
    """
    rule = PartitionedCardinalityChangedRule()
    left = _rtp_with_partitions(
        target_rows=[
            PartitionedCardinalityRow(
                key=PartitionKey(source={}, target={"type": "combine"}),
                stats=BoundedDistribution(count=9, min=2, max=3),
            )
        ]
    )
    right = _rtp_with_partitions(
        target_rows=[
            PartitionedCardinalityRow(
                key=PartitionKey(source={}, target={"stage": "combine"}),
                stats=BoundedDistribution(count=9, min=2, max=3),
            )
        ]
    )
    ctx = _pctx(
        left=left, right=right, address="IS_INPUT", extra={"address_type": "rel_type"}
    )
    issues = list(rule(ctx))
    changes = {i.context["change"] for i in issues}
    assert len(issues) == 2
    assert changes == {"left_only", "right_only"}
    assert all(i.code == "PARTITIONED_CARDINALITY_CHANGED" for i in issues)


def test_partitioned_cardinality_changed_partition_left_only():
    """A partition present on the left only → a left_only delta."""
    rule = PartitionedCardinalityChangedRule()
    left = _rtp_with_partitions(
        target_rows=[
            PartitionedCardinalityRow(
                key=PartitionKey(source={}, target={"type": "combine"}),
                stats=BoundedDistribution(count=9, min=2, max=3),
            )
        ]
    )
    right = _rtp_with_partitions(target_rows=None)
    ctx = _pctx(
        left=left, right=right, address="IS_INPUT", extra={"address_type": "rel_type"}
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].context["change"] == "left_only"
    assert issues[0].severity == Severity.INFO


def test_partitioned_cardinality_changed_noop_identical():
    """Identical breakdowns on both sides → no delta."""
    rule = PartitionedCardinalityChangedRule()
    key = PartitionKey(source={}, target={"type": "combine"})
    stats = BoundedDistribution(count=9, min=2, max=3)
    rtp = _rtp_with_partitions(
        target_rows=[PartitionedCardinalityRow(key=key, stats=stats)]
    )
    ctx = _pctx(
        left=rtp, right=rtp, address="IS_INPUT", extra={"address_type": "rel_type"}
    )
    assert list(rule(ctx)) == []


def test_partitioned_cardinality_changed_silent_for_definition_operands():
    """Definition operands carry no breakdown → the rule is silent."""
    rule = PartitionedCardinalityChangedRule()
    ctx = _ctx(
        left=_LivesIn,
        right=_LivesInLoose,
        address="LIVES_IN",
        extra={"address_type": "rel_type"},
    )
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# CardinalityChangedRule — definition ↔ definition
# ---------------------------------------------------------------------------


def test_cardinality_changed_fires_definition():
    rule = CardinalityChangedRule()
    # _LivesIn has "1..1"; _LivesInLoose has "0..*"
    ctx = _ctx(
        left=_LivesIn,
        right=_LivesInLoose,
        address="LIVES_IN",
        extra={"address_type": "rel_type"},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "CARDINALITY_CHANGED"
    assert issues[0].severity == Severity.INFO


def test_cardinality_changed_noop_identical_definition():
    rule = CardinalityChangedRule()
    ctx = _ctx(
        left=_LivesIn,
        right=_LivesIn,
        address="LIVES_IN",
        extra={"address_type": "rel_type"},
    )
    assert list(rule(ctx)) == []


def test_cardinality_changed_conditional_definition_does_not_crash():
    """a conditional source cardinality on one side must not raise
    AttributeError; the context omits min/max keys (conditional specs
    have no .min/.max attributes; representative_spec is not used for context)."""
    rule = CardinalityChangedRule()
    ctx = _ctx(
        left=_LivesIn,  # "1..1"
        right=_LivesInConditional,  # default ONE_OR_MORE (min=1, max=None)
        address="LIVES_IN",
        extra={"address_type": "rel_type"},
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "CARDINALITY_CHANGED"
    # when either side is conditional, context has no min/max keys.
    ctx_keys = set(issue.context or {})
    assert "left_min" not in ctx_keys
    assert "left_max" not in ctx_keys
    assert "right_min" not in ctx_keys
    assert "right_max" not in ctx_keys


def test_cardinality_changed_noop_for_property_address():
    rule = CardinalityChangedRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=5,
        source_label="Person",
        target_label="Movie",
        cardinality_stats=CardinalityStats(count=5, min=1, max=3, mean=2.0),
    )
    ctx = _pctx(left=rtp, right=rtp, address="ACTED_IN.role", extra=_PROP_EXTRA_REL)
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# All emitted issues are INFO — cross-cutting assertion
# ---------------------------------------------------------------------------


def test_all_emitted_issues_are_info():
    """Every diff rule can only emit Severity.INFO issues."""
    rules = diff_rules()

    def _collect_issues(ctx: RuleContext) -> list[ValidationIssue]:
        return [issue for rule in rules for issue in rule(ctx)]

    # Node label: left only
    ntp = NodeTypeProfile(label="Ghost", count=1)
    issues = _collect_issues(
        _pctx(
            left=ntp, right=None, address="Ghost", extra={"address_type": "node_label"}
        )
    )
    # Node label: right only
    issues += _collect_issues(
        _pctx(
            left=None, right=ntp, address="Ghost", extra={"address_type": "node_label"}
        )
    )
    # Rel type: left only (definition)
    issues += _collect_issues(
        _ctx(
            left=_ActedIn,
            right=None,
            address="ACTED_IN",
            extra={"address_type": "rel_type"},
        )
    )
    # Property: left only
    ti = TypeInfo(python_type=str, is_required=True)
    issues += _collect_issues(
        _ctx(left=ti, right=None, address="Person.name", extra=_PROP_EXTRA_NODE)
    )
    # Property type changed (TypeInfo)
    ti2 = TypeInfo(python_type=int, is_required=True)
    issues += _collect_issues(
        _ctx(left=ti, right=ti2, address="Person.name", extra=_PROP_EXTRA_NODE)
    )

    assert issues, "Expected at least some issues to be emitted in the INFO check"
    for issue in issues:
        assert issue.severity == Severity.INFO, (
            f"Rule emitted non-INFO issue: {issue.code} ({issue.severity})"
        )


# ---------------------------------------------------------------------------
# Bug/design regression tests (reported review issues)
# ---------------------------------------------------------------------------


def test_cardinality_changed_noop_asymmetric_stats_none_left():
    """CardinalityChangedRule is silent when the left profile lacks stats.

    A schema evolving from 'cardinality untracked' → 'cardinality tracked'
    produces no diff issue.  This is correct by design: the rule requires
    measured data on both sides to emit a meaningful diff.
    """
    rule = CardinalityChangedRule()
    rtp_no_stats = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, source_label="Person", target_label="Movie"
    )
    rtp_with_stats = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=5,
        source_label="Person",
        target_label="Movie",
        cardinality_stats=CardinalityStats(count=5, min=1, max=3, mean=2.0),
    )
    ctx = _pctx(
        left=rtp_no_stats,
        right=rtp_with_stats,
        address="ACTED_IN",
        extra={"address_type": "rel_type"},
    )
    assert list(rule(ctx)) == []


def test_cardinality_changed_noop_asymmetric_stats_none_right():
    """Same as above but the right profile lacks stats."""
    rule = CardinalityChangedRule()
    rtp_with_stats = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=5,
        source_label="Person",
        target_label="Movie",
        cardinality_stats=CardinalityStats(count=5, min=1, max=3, mean=2.0),
    )
    rtp_no_stats = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(
        left=rtp_with_stats,
        right=rtp_no_stats,
        address="ACTED_IN",
        extra={"address_type": "rel_type"},
    )
    assert list(rule(ctx)) == []


def test_property_type_changed_unknown_type_strings_differ():
    """PropertyTypeChangedRule fires when both sides have unknown type strings
    that are different from each other.

    When db_type_to_python cannot map a type string, the raw string is kept
    in the set.  Two different unmapped strings → PROPERTY_TYPE_CHANGED.
    """
    rule = PropertyTypeChangedRule()
    pp_left = PropertyProfile(
        name="geo",
        present_count=5,
        total_count=5,
        observed_types=["Point"],  # unknown → kept as "Point"
    )
    pp_right = PropertyProfile(
        name="geo",
        present_count=5,
        total_count=5,
        observed_types=["Geo3D"],  # unknown → kept as "Geo3D"
    )
    extra = {"label": "Place", "prop_name": "geo", "entity_type": EntityType.NODE}
    ctx = _pctx(left=pp_left, right=pp_right, address="Place.geo", extra=extra)
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_TYPE_CHANGED"
    assert issues[0].severity == Severity.INFO


def test_property_type_changed_same_unknown_type_string_noop():
    """PropertyTypeChangedRule is silent when both sides have the same
    unmapped type string."""
    rule = PropertyTypeChangedRule()
    pp = PropertyProfile(
        name="geo",
        present_count=5,
        total_count=5,
        observed_types=["Point"],
    )
    extra = {"label": "Place", "prop_name": "geo", "entity_type": EntityType.NODE}
    ctx = _pctx(left=pp, right=pp, address="Place.geo", extra=extra)
    assert list(rule(ctx)) == []


def test_node_label_rules_noop_for_rel_type_address_type():
    """NodeLabelOnlyInLeftRule and NodeLabelOnlyInRightRule must be silent
    when extra carries address_type='rel_type' (engine consistency guard).

    After the engine started stamping address_type, the diff rules also need
    to respect it to remain consistent with the standard rules.
    """
    left_rule = NodeLabelOnlyInLeftRule()
    right_rule = NodeLabelOnlyInRightRule()
    ntp = NodeTypeProfile(label="Person", count=3)

    # A rel-type-stamped context — the rules must not fire even though
    # left/right look like node profiles
    ctx_left_only = _pctx(
        left=ntp,
        right=None,
        address="Person",
        extra={"address_type": "rel_type"},
    )
    ctx_right_only = _pctx(
        left=None,
        right=ntp,
        address="Person",
        extra={"address_type": "rel_type"},
    )
    assert list(left_rule(ctx_left_only)) == []
    assert list(right_rule(ctx_right_only)) == []


def test_rel_type_rules_noop_for_node_label_address_type():
    """RelTypeOnlyInLeftRule and RelTypeOnlyInRightRule must be silent
    when extra carries address_type='node_label'."""
    left_rule = RelTypeOnlyInLeftRule()
    right_rule = RelTypeOnlyInRightRule()
    rtp = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, source_label="Person", target_label="Movie"
    )

    ctx_left_only = _pctx(
        left=rtp,
        right=None,
        address="ACTED_IN",
        extra={"address_type": "node_label"},
    )
    ctx_right_only = _pctx(
        left=None,
        right=rtp,
        address="ACTED_IN",
        extra={"address_type": "node_label"},
    )
    assert list(left_rule(ctx_left_only)) == []
    assert list(right_rule(ctx_right_only)) == []


# ---------------------------------------------------------------------------
# EndpointsChangedRule / CardinalityChangedRule — node-label address guard
# (regression for the `"prop_name" in extra` → `address_type != "rel_type"` fix)
# ---------------------------------------------------------------------------


def test_endpoints_changed_noop_for_node_label_address():
    """EndpointsChangedRule must be silent for node-label addresses.

    Before the fix the rule used ``"prop_name" in context.extra`` as its
    guard, which passed through node-label contexts (no prop_name, no
    address_type stamp).  After the fix the rule checks
    ``address_type != "rel_type"`` and must return immediately.
    """
    rule = EndpointsChangedRule()
    ntp = NodeTypeProfile(label="Person", count=3)
    ctx = _pctx(
        left=ntp,
        right=ntp,
        address="Person",
        extra={"address_type": "node_label"},
    )
    assert list(rule(ctx)) == []


def test_endpoints_changed_noop_for_node_label_address_left_only():
    """EndpointsChangedRule must be silent for a left-only node-label address."""
    rule = EndpointsChangedRule()
    ntp = NodeTypeProfile(label="Person", count=3)
    ctx = _pctx(
        left=ntp,
        right=None,
        address="Person",
        extra={"address_type": "node_label"},
    )
    assert list(rule(ctx)) == []


def test_cardinality_changed_noop_for_node_label_address():
    """CardinalityChangedRule must be silent for node-label addresses.

    Same guard regression as EndpointsChangedRule — the old
    ``"prop_name" in extra`` check allowed node-label contexts through;
    the new ``address_type != "rel_type"`` check must reject them.
    """
    rule = CardinalityChangedRule()
    ntp = NodeTypeProfile(label="Person", count=3)
    ctx = _pctx(
        left=ntp,
        right=ntp,
        address="Person",
        extra={"address_type": "node_label"},
    )
    assert list(rule(ctx)) == []


def test_cardinality_changed_noop_for_node_label_address_left_only():
    """CardinalityChangedRule must be silent for a left-only node-label address."""
    rule = CardinalityChangedRule()
    ntp = NodeTypeProfile(label="Person", count=3)
    ctx = _pctx(
        left=ntp,
        right=None,
        address="Person",
        extra={"address_type": "node_label"},
    )
    assert list(rule(ctx)) == []


# ---------------------------------------------------------------------------
# PropertyTypeChangedRule — None-safe fallback for db_type_to_python
# (regression for the `or t` → `is not None` fix)
# ---------------------------------------------------------------------------


def test_property_type_changed_noop_mapped_type_that_is_bool_falsy_would_not_occur():
    """Verify that the is-not-None guard is used rather than truthiness.

    ``db_type_to_python`` currently maps every known type to a non-None,
    non-falsy Python type (str, int, float, bool, list).  This test
    documents the invariant: for all known type strings the mapped value
    is truthy, so the old ``or t`` and the new ``is not None`` are
    equivalent today.  The test uses 'Boolean' (maps to ``bool``) on both
    sides to confirm no spurious PROPERTY_TYPE_CHANGED is emitted — if the
    old ``or t`` code had been replaced incorrectly, ``bool or 'Boolean'``
    would return ``bool`` (fine), but the explicit test makes the contract
    clear for future map additions.
    """
    rule = PropertyTypeChangedRule()
    pp_left = PropertyProfile(
        name="active",
        present_count=5,
        total_count=5,
        observed_types=["Boolean"],
    )
    pp_right = PropertyProfile(
        name="active",
        present_count=5,
        total_count=5,
        observed_types=["Bool"],  # different string, same mapped type (bool)
    )
    extra = {"label": "User", "prop_name": "active", "entity_type": EntityType.NODE}
    ctx = _pctx(left=pp_left, right=pp_right, address="User.active", extra=extra)
    # Both map to bool → sets are equal → no issue
    assert list(rule(ctx)) == []


def test_property_type_changed_unknown_type_same_as_known_mapped_noop():
    """An unmapped string kept as-is does not collide with a Python type object.

    If one side has an unknown type kept as ``'MyType'`` (a str) and the
    other side has a known type mapped to ``str`` (the type), these are
    *not* equal and PROPERTY_TYPE_CHANGED fires.  This confirms the raw
    string and the type object are distinct set members.
    """
    rule = PropertyTypeChangedRule()
    pp_left = PropertyProfile(
        name="val",
        present_count=5,
        total_count=5,
        observed_types=["String"],  # maps to str
    )
    pp_right = PropertyProfile(
        name="val",
        present_count=5,
        total_count=5,
        observed_types=["MyCustomType"],  # unknown → kept as "MyCustomType"
    )
    extra = {"label": "X", "prop_name": "val", "entity_type": EntityType.NODE}
    ctx = _pctx(left=pp_left, right=pp_right, address="X.val", extra=extra)
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "PROPERTY_TYPE_CHANGED"


# ===========================================================================
# CardinalityChangedRule: conditional definition ↔ definition
# ===========================================================================


class _KindedSourceNode(NodeModel):
    """Source node with a required 'kind' property for conditional cardinality tests."""

    __label__ = "KindedSource"
    kind: str


class _KindedTargetNode(NodeModel):
    """Target node for conditional cardinality tests."""

    __label__ = "KindedTarget"
    name: str


class _HasOutputConditionalA(RelationshipModel):
    """HAS_OUTPUT with conditional source cardinality — rule set A."""

    __label__ = "HAS_OUTPUT"
    __source_label__ = "KindedSource"
    __target_label__ = "KindedTarget"
    __source_cardinality__ = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "vip"}),
                target=PropMatch(),
                spec="0..1",
            ),
        ),
        default="1..*",
    )


class _HasOutputConditionalB(RelationshipModel):
    """HAS_OUTPUT with a different conditional source cardinality — rule set B."""

    __label__ = "HAS_OUTPUT"
    __source_label__ = "KindedSource"
    __target_label__ = "KindedTarget"
    __source_cardinality__ = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "admin"}),
                target=PropMatch(),
                spec="0..*",
            ),
        ),
        default="1..1",
    )


_GD_COND_A = GraphDefinition(
    name="cond_a",
    node_types=[_KindedSourceNode, _KindedTargetNode],
    relationship_types=[_HasOutputConditionalA],
)

_GD_COND_B = GraphDefinition(
    name="cond_b",
    node_types=[_KindedSourceNode, _KindedTargetNode],
    relationship_types=[_HasOutputConditionalB],
)

_GD_COND_SAME = GraphDefinition(
    name="cond_same",
    node_types=[_KindedSourceNode, _KindedTargetNode],
    relationship_types=[_HasOutputConditionalA],
)


def test_cardinality_changed_fires_for_differing_conditional_definitions():
    """Scope: CardinalityChangedRule emits CARDINALITY_CHANGED (INFO) when both
    sides have conditional source cardinality but with different rule sets."""
    rule = CardinalityChangedRule()
    ctx = _ctx(
        left=_HasOutputConditionalA,
        right=_HasOutputConditionalB,
        address="HAS_OUTPUT",
        extra={"address_type": "rel_type"},
        left_gd=_GD_COND_A,
        right_gd=_GD_COND_B,
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "CARDINALITY_CHANGED"
    assert issues[0].severity == Severity.INFO


def test_cardinality_changed_noop_for_identical_conditional_definitions():
    """Scope: CardinalityChangedRule is silent when both sides have identical
    conditional source cardinality (structural ==)."""
    rule = CardinalityChangedRule()
    ctx = _ctx(
        left=_HasOutputConditionalA,
        right=_HasOutputConditionalA,
        address="HAS_OUTPUT",
        extra={"address_type": "rel_type"},
        left_gd=_GD_COND_A,
        right_gd=_GD_COND_SAME,
    )
    assert list(rule(ctx)) == []


def test_cardinality_changed_conditional_context_has_no_min_max_keys():
    """Scope: CARDINALITY_CHANGED context dict for a conditional diff must not
    contain left_min, left_max, right_min, or right_max keys (those attributes
    do not exist on ConditionalCardinality)."""
    rule = CardinalityChangedRule()
    ctx = _ctx(
        left=_HasOutputConditionalA,
        right=_HasOutputConditionalB,
        address="HAS_OUTPUT",
        extra={"address_type": "rel_type"},
        left_gd=_GD_COND_A,
        right_gd=_GD_COND_B,
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    ctx_keys = set(issues[0].context or {})
    assert "left_min" not in ctx_keys
    assert "left_max" not in ctx_keys
    assert "right_min" not in ctx_keys
    assert "right_max" not in ctx_keys


# ===========================================================================
# total-count delta is diff-only
#
# Total count is excluded from profile↔description and participates *only* in
# profile↔profile as an INFO drift signal (COUNT_CHANGED).
# ===========================================================================


def test_count_changed_rule_satisfies_protocol():
    assert isinstance(CountChangedRule(), Rule)


def test_count_changed_fires_for_node_label_when_counts_differ():
    rule = CountChangedRule()
    left = NodeTypeProfile(label="Person", count=5)
    right = NodeTypeProfile(label="Person", count=8)
    ctx = _pctx(
        left=left, right=right, address="Person", extra={"address_type": "node_label"}
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "COUNT_CHANGED"
    assert issues[0].severity == Severity.INFO
    assert issues[0].entity_type == EntityType.NODE
    assert issues[0].entity_id == "Person"
    assert issues[0].context["left"] == 5
    assert issues[0].context["right"] == 8


def test_count_changed_fires_for_rel_type_when_counts_differ():
    rule = CountChangedRule()
    left = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=10, source_label="Person", target_label="Movie"
    )
    right = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=3, source_label="Person", target_label="Movie"
    )
    ctx = _pctx(
        left=left, right=right, address="ACTED_IN", extra={"address_type": "rel_type"}
    )
    issues = list(rule(ctx))
    assert len(issues) == 1
    assert issues[0].code == "COUNT_CHANGED"
    assert issues[0].severity == Severity.INFO
    assert issues[0].entity_type == EntityType.RELATIONSHIP


def test_count_changed_noop_when_counts_equal():
    rule = CountChangedRule()
    left = NodeTypeProfile(label="Person", count=5)
    right = NodeTypeProfile(label="Person", count=5)
    ctx = _pctx(
        left=left, right=right, address="Person", extra={"address_type": "node_label"}
    )
    assert list(rule(ctx)) == []


def test_count_changed_noop_when_one_side_absent():
    rule = CountChangedRule()
    left = NodeTypeProfile(label="Person", count=5)
    ctx = _pctx(
        left=left, right=None, address="Person", extra={"address_type": "node_label"}
    )
    assert list(rule(ctx)) == []


def test_count_changed_noop_for_definition_operands():
    """Definitions carry no observed count → rule does nothing for model classes."""
    rule = CountChangedRule()
    ctx = _ctx(
        left=_ActedIn,
        right=_ActedInAlt,
        address="ACTED_IN",
        extra={"address_type": "rel_type"},
        left_gd=_GD_LEFT,
        right_gd=_GD_ALT,
    )
    assert list(rule(ctx)) == []


def test_count_changed_noop_for_property_address():
    rule = CountChangedRule()
    left = PropertyProfile(name="name", present_count=3, total_count=3)
    right = PropertyProfile(name="name", present_count=4, total_count=4)
    ctx = _pctx(left=left, right=right, address="Person.name", extra=_PROP_EXTRA_NODE)
    assert list(rule(ctx)) == []
