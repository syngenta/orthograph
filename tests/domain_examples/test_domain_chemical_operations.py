"""Domain example: general both-endpoint conditional-cardinality partitioning
in a chemical-operations processing pipeline (ADR-032 / E43).

This is the domain-flavoured companion to
``tests/graph_definition/test_conditional_general_partitioning.py``: it exercises
the same partitioning logic, but grounded in a concrete ``Sample`` / ``Operation``
processing pipeline rather than the abstract movie domain used in the unit suite.

These tests author rules with explicit ``ConditionalRule`` / ``PropMatch`` (the
authoring surface after ``by_kind`` removal) and exercise the cases the
opposite-only partition axis could not enforce:

- a rule keyed on the *counted node's own* property when that node is the TARGET
  of the relationship (the ``Sample -[:IS_INPUT]-> Operation`` pilot direction);
- a rule fixing *two properties on one* endpoint;
- a rule fixing properties on *both* endpoints, subdividing by the full pair.
"""

from typing import Any

import pytest

from orthograph.diagnostics.result import GraphValidationError
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
    RelationshipModel,
)
from orthograph.graph_definition.validation import GraphValidator


def _spec(text: str) -> CardinalitySpec:
    return CardinalitySpec.parse(text)


# ---------------------------------------------------------------------------
# Target-side rule keyed on the counted node's OWN property
# ---------------------------------------------------------------------------


def _pipeline_input_model() -> type[RelationshipModel]:
    """IS_INPUT: Sample -> Operation, input count keyed on Operation.type.

    The counted node (Operation) is the TARGET; the rule discriminates on the
    Operation's own ``type`` via the rule's ``target`` predicate (target side =
    the iterated/counted node), and wildcards the Sample.
    """

    class Sample(NodeModel):
        __label__ = "Sample"
        __uid_field__ = "name"
        name: str
        role: str

    class Operation(NodeModel):
        __label__ = "Operation"
        __uid_field__ = "name"
        name: str
        type: str

    # On a __target_cardinality__, the counted node (Operation) is matched by the
    # rule's `target` PropMatch; the opposite endpoint (Sample) by `source`.
    inputs = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch(),
                target=PropMatch({"type": "chromatography"}),
                spec=_spec("1..1"),
            ),
            ConditionalRule(
                source=PropMatch(),
                target=PropMatch({"type": "combine"}),
                spec=_spec("2..*"),
            ),
        ),
        default=_spec("0..0"),
    )

    class IsInput(RelationshipModel):
        __label__ = "IS_INPUT"
        __source_label__ = "Sample"
        __target_label__ = "Operation"
        __source_cardinality__ = "0..*"
        __target_cardinality__ = inputs

    # Stash node types for the GraphDefinition builder.
    IsInput._test_nodes = [Sample, Operation]  # type: ignore[attr-defined]
    return IsInput


def test_target_side_own_property_chromatography_one_input_valid():
    """Scope: chromatography with exactly 1 input is VALID (target own-prop rule)."""
    rel = _pipeline_input_model()
    gd = GraphDefinition(
        name="Pipe",
        node_types=rel._test_nodes,  # type: ignore[attr-defined]
        relationship_types=[rel],
    )
    nodes: list[dict[str, Any]] = [
        {"__label__": "Sample", "name": "s1", "role": "sample"},
        {"__label__": "Operation", "name": "c1", "type": "chromatography"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "IS_INPUT", "__source_uid__": "s1", "__target_uid__": "c1"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert card_errors == [], [e.message for e in card_errors]


def test_target_side_own_property_combine_one_input_violates():
    """Scope: combine with 1 input violates 2..* (target-side own-prop rule)."""
    rel = _pipeline_input_model()
    gd = GraphDefinition(
        name="Pipe",
        node_types=rel._test_nodes,  # type: ignore[attr-defined]
        relationship_types=[rel],
    )
    nodes: list[dict[str, Any]] = [
        {"__label__": "Sample", "name": "s1", "role": "sample"},
        {"__label__": "Operation", "name": "m1", "type": "combine"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "IS_INPUT", "__source_uid__": "s1", "__target_uid__": "m1"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(card_errors) == 1, [e.message for e in card_errors]
    assert card_errors[0].context["expected_min"] == 2
    assert card_errors[0].context["actual"] == 1


# ---------------------------------------------------------------------------
# Two properties on one endpoint
# ---------------------------------------------------------------------------


def test_two_properties_on_source_endpoint_subdivides():
    """Scope: a rule fixing two source properties applies only to the full match."""

    class Producer(NodeModel):
        __label__ = "Producer"
        __uid_field__ = "uid"
        uid: str
        kind: str
        stage: str

    class Item(NodeModel):
        __label__ = "Item"
        __uid_field__ = "uid"
        uid: str

    # A producer of (kind=combine, stage=final) must emit exactly 1 output;
    # everything else falls to the permissive default.
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "combine", "stage": "final"}),
                target=PropMatch(),
                spec=_spec("1..1"),
            ),
        ),
        default=_spec("0..*"),
    )

    class Emits(RelationshipModel):
        __label__ = "EMITS"
        __source_label__ = "Producer"
        __target_label__ = "Item"
        __source_cardinality__ = card

    gd = GraphDefinition(
        name="TwoProp",
        node_types=[Producer, Item],
        relationship_types=[Emits],
    )

    # p1 matches both conditions and has 0 outputs -> violates 1..1.
    # p2 matches only stage (kind differs) -> default 0..* -> ok with 0.
    nodes: list[dict[str, Any]] = [
        {"__label__": "Producer", "uid": "p1", "kind": "combine", "stage": "final"},
        {"__label__": "Producer", "uid": "p2", "kind": "split", "stage": "final"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=[])
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert any("p1" in e.entity_id for e in card_errors)
    assert not any("p2" in e.entity_id for e in card_errors)


# ---------------------------------------------------------------------------
# Properties on BOTH endpoints — subdivide by the full pair
# ---------------------------------------------------------------------------


def test_both_endpoints_partition_by_pair():
    """Scope: a node's edges subdivide by (self props, other props) jointly.

    A 'combine' operation must have 2..* 'internal' inputs but 0..1 'subsample'
    inputs. The two partitions of one node are checked independently.
    """

    class Sample(NodeModel):
        __label__ = "Sample"
        __uid_field__ = "name"
        name: str
        role: str

    class Operation(NodeModel):
        __label__ = "Operation"
        __uid_field__ = "name"
        name: str
        type: str

    # On the source side, the counted node (Operation) is matched by `source`,
    # the opposite endpoint (Sample) by `target`.
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"type": "combine"}),
                target=PropMatch({"role": "internal"}),
                spec=_spec("2..*"),
            ),
            ConditionalRule(
                source=PropMatch({"type": "combine"}),
                target=PropMatch({"role": "subsample"}),
                spec=_spec("0..1"),
            ),
        ),
        default=_spec("0..*"),
    )

    class Consumes(RelationshipModel):
        __label__ = "CONSUMES"
        __source_label__ = "Operation"
        __target_label__ = "Sample"
        __source_cardinality__ = card

    gd = GraphDefinition(
        name="BothEnds",
        node_types=[Sample, Operation],
        relationship_types=[Consumes],
    )

    # op1: 2 internal (ok, 2..*) + 2 subsample (violates 0..1).
    nodes: list[dict[str, Any]] = [
        {"__label__": "Operation", "name": "op1", "type": "combine"},
        {"__label__": "Sample", "name": "i1", "role": "internal"},
        {"__label__": "Sample", "name": "i2", "role": "internal"},
        {"__label__": "Sample", "name": "u1", "role": "subsample"},
        {"__label__": "Sample", "name": "u2", "role": "subsample"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "CONSUMES", "__source_uid__": "op1", "__target_uid__": "i1"},
        {"__label__": "CONSUMES", "__source_uid__": "op1", "__target_uid__": "i2"},
        {"__label__": "CONSUMES", "__source_uid__": "op1", "__target_uid__": "u1"},
        {"__label__": "CONSUMES", "__source_uid__": "op1", "__target_uid__": "u2"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    # Exactly one violation: the subsample partition (count 2 vs 0..1).
    assert len(card_errors) == 1, [e.message for e in card_errors]
    assert card_errors[0].context["expected_max"] == 1
    assert card_errors[0].context["actual"] == 2


def test_both_endpoints_internal_partition_missing_violates_min():
    """Scope: a node missing the 'internal' partition entirely violates its 2..* min."""

    class Sample(NodeModel):
        __label__ = "Sample"
        __uid_field__ = "name"
        name: str
        role: str

    class Operation(NodeModel):
        __label__ = "Operation"
        __uid_field__ = "name"
        name: str
        type: str

    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"type": "combine"}),
                target=PropMatch({"role": "internal"}),
                spec=_spec("2..*"),
            ),
        ),
        default=_spec("0..*"),
    )

    class Consumes(RelationshipModel):
        __label__ = "CONSUMES"
        __source_label__ = "Operation"
        __target_label__ = "Sample"
        __source_cardinality__ = card

    gd = GraphDefinition(
        name="MissingPart",
        node_types=[Sample, Operation],
        relationship_types=[Consumes],
    )

    # op1 is a combine with one 'subsample' edge but ZERO 'internal' edges.
    # The declared (combine, internal) partition is missing -> counts as 0 ->
    # violates 2..*.
    nodes: list[dict[str, Any]] = [
        {"__label__": "Operation", "name": "op1", "type": "combine"},
        {"__label__": "Sample", "name": "u1", "role": "subsample"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "CONSUMES", "__source_uid__": "op1", "__target_uid__": "u1"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(card_errors) == 1, [e.message for e in card_errors]
    assert card_errors[0].context["expected_min"] == 2
    assert card_errors[0].context["actual"] == 0


# ---------------------------------------------------------------------------
# Definition-time guard: a key on neither endpoint is unenforceable (ADR-032 §4)
# ---------------------------------------------------------------------------


def test_unenforceable_rule_rejected_at_definition_time():
    """Scope: a rule discriminating on a property present on neither endpoint of
    the edge is rejected at GraphDefinition construction (no silent mis-validation).

    Under the absolute convention this is caught by the existing
    DiscriminatorPropertyExistsCheck (CARDINALITY_UNKNOWN_DISCRIMINATOR); this test
    locks that guarantee so the silent-pass hole cannot reopen.
    """

    class Sample(NodeModel):
        __label__ = "Sample"
        __uid_field__ = "uid"
        uid: str
        role: str

    class Operation(NodeModel):
        __label__ = "Operation"
        __uid_field__ = "uid"
        uid: str

    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"role": "x"}),
                target=PropMatch({"ghost": "y"}),  # 'ghost' is on neither endpoint
                spec=_spec("1..1"),
            ),
        ),
        default=_spec("0..*"),
    )

    class Feeds(RelationshipModel):
        __label__ = "FEEDS"
        __source_label__ = "Sample"
        __target_label__ = "Operation"
        __source_cardinality__ = card

    with pytest.raises(GraphValidationError) as exc:
        GraphDefinition(
            name="G", node_types=[Sample, Operation], relationship_types=[Feeds]
        )
    codes = {i.code for i in exc.value.issues}
    assert "CARDINALITY_UNKNOWN_DISCRIMINATOR" in codes


def test_target_side_own_property_rule_accepted_at_definition_time():
    """Scope: a target-side rule keyed on the counted (target) node's own property
    is ACCEPTED at definition time under the absolute convention — the previously
    silently-wrong case is now first-class."""
    rel = _pipeline_input_model()
    # Must not raise.
    GraphDefinition(
        name="Pipe",
        node_types=rel._test_nodes,  # type: ignore[attr-defined]
        relationship_types=[rel],
    )
