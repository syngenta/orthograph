"""General both-endpoint conditional-cardinality partitioning.

These tests author rules with explicit ``ConditionalRule`` / ``PropMatch`` (the
authoring surface after ``by_kind`` removal) and exercise the cases the
opposite-only partition axis could not enforce:

- a rule keyed on the *counted node's own* property when that node is the TARGET
  of the relationship (the ``Person -[:DIRECTED]-> Film`` pilot direction);
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


def _filmography_director_model() -> type[RelationshipModel]:
    """DIRECTED: Person -> Film, director count keyed on Film.kind.

    The counted node (Film) is the TARGET; the rule discriminates on the
    Film's own ``kind`` via the rule's ``target`` predicate (target side =
    the iterated/counted node), and wildcards the Person.
    """

    class Person(NodeModel):
        __label__ = "Person"
        __uid_field__ = "name"
        name: str
        role: str

    class Film(NodeModel):
        __label__ = "Film"
        __uid_field__ = "name"
        name: str
        kind: str

    # On a __target_cardinality__, the counted node (Film) is matched by the
    # rule's `target` PropMatch; the opposite endpoint (Person) by `source`.
    directors = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch(),
                target=PropMatch({"kind": "documentary"}),
                spec=_spec("1..1"),
            ),
            ConditionalRule(
                source=PropMatch(),
                target=PropMatch({"kind": "anthology"}),
                spec=_spec("2..*"),
            ),
        ),
        default=_spec("0..0"),
    )

    class Directed(RelationshipModel):
        __label__ = "DIRECTED"
        __source_label__ = "Person"
        __target_label__ = "Film"
        __source_cardinality__ = "0..*"
        __target_cardinality__ = directors

    # Stash node types for the GraphDefinition builder.
    Directed._test_nodes = [Person, Film]  # type: ignore[attr-defined]
    return Directed


def test_target_side_own_property_documentary_one_director_valid():
    """Scope: a documentary with exactly 1 director is VALID (target own-prop rule)."""
    rel = _filmography_director_model()
    gd = GraphDefinition(
        name="Filmography",
        node_types=rel._test_nodes,  # type: ignore[attr-defined]
        relationship_types=[rel],
    )
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "p1", "role": "director"},
        {"__label__": "Film", "name": "d1", "kind": "documentary"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "DIRECTED", "__source_uid__": "p1", "__target_uid__": "d1"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert card_errors == [], [e.message for e in card_errors]


def test_target_side_own_property_anthology_one_director_violates():
    """Scope: an anthology with 1 director violates 2..* (target-side own-prop rule)."""
    rel = _filmography_director_model()
    gd = GraphDefinition(
        name="Filmography",
        node_types=rel._test_nodes,  # type: ignore[attr-defined]
        relationship_types=[rel],
    )
    nodes: list[dict[str, Any]] = [
        {"__label__": "Person", "name": "p1", "role": "director"},
        {"__label__": "Film", "name": "a1", "kind": "anthology"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "DIRECTED", "__source_uid__": "p1", "__target_uid__": "a1"},
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

    class Studio(NodeModel):
        __label__ = "Studio"
        __uid_field__ = "uid"
        uid: str
        kind: str
        stage: str

    class Film(NodeModel):
        __label__ = "Film"
        __uid_field__ = "uid"
        uid: str

    # A studio of (kind=major, stage=flagship) must release exactly 1 film;
    # everything else falls to the permissive default.
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "major", "stage": "flagship"}),
                target=PropMatch(),
                spec=_spec("1..1"),
            ),
        ),
        default=_spec("0..*"),
    )

    class Releases(RelationshipModel):
        __label__ = "RELEASES"
        __source_label__ = "Studio"
        __target_label__ = "Film"
        __source_cardinality__ = card

    gd = GraphDefinition(
        name="TwoProp",
        node_types=[Studio, Film],
        relationship_types=[Releases],
    )

    # s1 matches both conditions and has 0 releases -> violates 1..1.
    # s2 matches only stage (kind differs) -> default 0..* -> ok with 0.
    nodes: list[dict[str, Any]] = [
        {"__label__": "Studio", "uid": "s1", "kind": "major", "stage": "flagship"},
        {"__label__": "Studio", "uid": "s2", "kind": "indie", "stage": "flagship"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=[])
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert any("s1" in e.entity_id for e in card_errors)
    assert not any("s2" in e.entity_id for e in card_errors)


# ---------------------------------------------------------------------------
# Properties on BOTH endpoints — subdivide by the full pair
# ---------------------------------------------------------------------------


def test_both_endpoints_partition_by_pair():
    """Scope: a node's edges subdivide by (self props, other props) jointly.

    An 'anthology' film must have 2..* 'lead' cast members but 0..1 'cameo'
    cast members. The two partitions of one node are checked independently.
    """

    class Person(NodeModel):
        __label__ = "Person"
        __uid_field__ = "name"
        name: str
        role: str

    class Film(NodeModel):
        __label__ = "Film"
        __uid_field__ = "name"
        name: str
        kind: str

    # On the source side, the counted node (Film) is matched by `source`,
    # the opposite endpoint (Person) by `target`.
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "anthology"}),
                target=PropMatch({"role": "lead"}),
                spec=_spec("2..*"),
            ),
            ConditionalRule(
                source=PropMatch({"kind": "anthology"}),
                target=PropMatch({"role": "cameo"}),
                spec=_spec("0..1"),
            ),
        ),
        default=_spec("0..*"),
    )

    class Casts(RelationshipModel):
        __label__ = "CASTS"
        __source_label__ = "Film"
        __target_label__ = "Person"
        __source_cardinality__ = card

    gd = GraphDefinition(
        name="BothEnds",
        node_types=[Person, Film],
        relationship_types=[Casts],
    )

    # f1: 2 lead (ok, 2..*) + 2 cameo (violates 0..1).
    nodes: list[dict[str, Any]] = [
        {"__label__": "Film", "name": "f1", "kind": "anthology"},
        {"__label__": "Person", "name": "l1", "role": "lead"},
        {"__label__": "Person", "name": "l2", "role": "lead"},
        {"__label__": "Person", "name": "c1", "role": "cameo"},
        {"__label__": "Person", "name": "c2", "role": "cameo"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "CASTS", "__source_uid__": "f1", "__target_uid__": "l1"},
        {"__label__": "CASTS", "__source_uid__": "f1", "__target_uid__": "l2"},
        {"__label__": "CASTS", "__source_uid__": "f1", "__target_uid__": "c1"},
        {"__label__": "CASTS", "__source_uid__": "f1", "__target_uid__": "c2"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    # Exactly one violation: the cameo partition (count 2 vs 0..1).
    assert len(card_errors) == 1, [e.message for e in card_errors]
    assert card_errors[0].context["expected_max"] == 1
    assert card_errors[0].context["actual"] == 2


def test_both_endpoints_lead_partition_missing_violates_min():
    """Scope: a node missing the 'lead' partition entirely violates its 2..* min."""

    class Person(NodeModel):
        __label__ = "Person"
        __uid_field__ = "name"
        name: str
        role: str

    class Film(NodeModel):
        __label__ = "Film"
        __uid_field__ = "name"
        name: str
        kind: str

    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "anthology"}),
                target=PropMatch({"role": "lead"}),
                spec=_spec("2..*"),
            ),
        ),
        default=_spec("0..*"),
    )

    class Casts(RelationshipModel):
        __label__ = "CASTS"
        __source_label__ = "Film"
        __target_label__ = "Person"
        __source_cardinality__ = card

    gd = GraphDefinition(
        name="MissingPart",
        node_types=[Person, Film],
        relationship_types=[Casts],
    )

    # f1 is an anthology with one 'cameo' edge but ZERO 'lead' edges.
    # The declared (anthology, lead) partition is missing -> counts as 0 ->
    # violates 2..*.
    nodes: list[dict[str, Any]] = [
        {"__label__": "Film", "name": "f1", "kind": "anthology"},
        {"__label__": "Person", "name": "c1", "role": "cameo"},
    ]
    rels: list[dict[str, Any]] = [
        {"__label__": "CASTS", "__source_uid__": "f1", "__target_uid__": "c1"},
    ]
    result = GraphValidator(gd).validate(nodes=nodes, relationships=rels)
    card_errors = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(card_errors) == 1, [e.message for e in card_errors]
    assert card_errors[0].context["expected_min"] == 2
    assert card_errors[0].context["actual"] == 0


# ---------------------------------------------------------------------------
# Definition-time guard: a key on neither endpoint is unenforceable
# ---------------------------------------------------------------------------


def test_unenforceable_rule_rejected_at_definition_time():
    """Scope: a rule discriminating on a property present on neither endpoint of
    the edge is rejected at GraphDefinition construction (no silent mis-validation).

    Under the absolute convention this is caught by the existing
    DiscriminatorPropertyExistsCheck (CARDINALITY_UNKNOWN_DISCRIMINATOR); this test
    locks that guarantee so the silent-pass hole cannot reopen.
    """

    class Person(NodeModel):
        __label__ = "Person"
        __uid_field__ = "uid"
        uid: str
        role: str

    class Film(NodeModel):
        __label__ = "Film"
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

    class Directed(RelationshipModel):
        __label__ = "DIRECTED"
        __source_label__ = "Person"
        __target_label__ = "Film"
        __source_cardinality__ = card

    with pytest.raises(GraphValidationError) as exc:
        GraphDefinition(
            name="G", node_types=[Person, Film], relationship_types=[Directed]
        )
    codes = {i.code for i in exc.value.issues}
    assert "CARDINALITY_UNKNOWN_DISCRIMINATOR" in codes


def test_target_side_own_property_rule_accepted_at_definition_time():
    """Scope: a target-side rule keyed on the counted (target) node's own property
    is ACCEPTED at definition time under the absolute convention — the previously
    silently-wrong case is now first-class."""
    rel = _filmography_director_model()
    # Must not raise.
    GraphDefinition(
        name="Filmography",
        node_types=rel._test_nodes,  # type: ignore[attr-defined]
        relationship_types=[rel],
    )
