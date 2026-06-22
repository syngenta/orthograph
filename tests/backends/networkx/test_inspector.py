"""Tests for NetworkxInspector."""

from __future__ import annotations

import networkx as nx
import pytest

from orthograph.backends.networkx.inspector import NetworkxInspector
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
    RelationshipModel,
)
from orthograph.graph_profile.models import PartitionKey


def _make_graph() -> nx.MultiDiGraph[str]:
    """Helper to create a fresh empty MultiDiGraph."""
    return nx.MultiDiGraph()


def test_inspect_empty_graph():
    g = _make_graph()
    profile = NetworkxInspector().inspect(g)

    assert profile.source == "networkx"
    assert profile.node_type_profiles == {}
    assert profile.rel_type_profiles == {}


def test_inspect_nodes_only():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice", age=30)
    g.add_node("b", __label__="Movie", title="Inception", year=2010)

    profile = NetworkxInspector().inspect(g)

    assert "Person" in profile.node_type_profiles
    assert "Movie" in profile.node_type_profiles
    assert profile.rel_type_profiles == {}


def test_inspect_node_count():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice")
    g.add_node("b", __label__="Person", name="Bob")
    g.add_node("c", __label__="Person", name="Charlie")
    g.add_node("m1", __label__="Movie", title="X")

    profile = NetworkxInspector().inspect(g)

    assert profile.node_type_profiles["Person"].count == 3
    assert profile.node_type_profiles["Movie"].count == 1


def test_inspect_property_completeness():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice", age=30, email="a@b.com")
    g.add_node("b", __label__="Person", name="Bob", age=25)
    g.add_node("c", __label__="Person", name="Charlie")

    profile = NetworkxInspector().inspect(g)
    props = profile.node_type_profiles["Person"].property_profiles

    assert props["name"].present_count == 3
    assert props["name"].total_count == 3
    assert props["name"].completeness == 1.0

    assert props["age"].present_count == 2
    assert props["age"].total_count == 3

    assert props["email"].present_count == 1
    assert props["email"].total_count == 3
    assert props["email"].completeness == pytest.approx(1 / 3)


def test_inspect_property_types():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice", age=30)
    g.add_node("b", __label__="Person", name="Bob", age=25)

    profile = NetworkxInspector().inspect(g)
    props = profile.node_type_profiles["Person"].property_profiles

    assert "str" in props["name"].observed_types
    assert "int" in props["age"].observed_types


def test_inspect_explicit_null_not_present():
    """An explicit ``None`` value is not counted as present."""
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice", nickname="Al")
    g.add_node("b", __label__="Person", name="Bob", nickname=None)
    g.add_node("c", __label__="Person", name="Charlie", nickname=None)

    profile = NetworkxInspector().inspect(g)
    props = profile.node_type_profiles["Person"].property_profiles

    # nickname is set on all three but null on two → only one is present.
    assert props["nickname"].present_count == 1
    assert props["nickname"].total_count == 3
    # null values contribute no observed type.
    assert props["nickname"].observed_types == ["str"]


def test_inspect_constraint_required_is_none():
    """NetworkX has no DB constraints → constraint_required is None."""
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice")

    profile = NetworkxInspector().inspect(g)
    name = profile.node_type_profiles["Person"].property_profiles["name"]
    assert name.constraint_required is None


def test_inspect_relationships():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice")
    g.add_node("m1", __label__="Movie", title="X")
    g.add_node("m2", __label__="Movie", title="Y")
    g.add_edge("a", "m1", __label__="ACTED_IN", role="Lead")
    g.add_edge("a", "m2", __label__="ACTED_IN", role="Extra")
    g.add_edge("a", "m1", __label__="DIRECTED")

    profile = NetworkxInspector().inspect(g)

    assert "ACTED_IN" in profile.rel_type_profiles
    assert "DIRECTED" in profile.rel_type_profiles
    assert profile.rel_type_profiles["ACTED_IN"].count == 2
    assert profile.rel_type_profiles["DIRECTED"].count == 1


def test_inspect_rel_source_target_labels():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice")
    g.add_node("m1", __label__="Movie", title="X")
    g.add_edge("a", "m1", __label__="ACTED_IN", role="Lead")

    profile = NetworkxInspector().inspect(g)
    rel = profile.rel_type_profiles["ACTED_IN"]

    assert rel.source_labels == {"Person"}
    assert rel.target_labels == {"Movie"}


def test_inspect_cardinality_stats():
    g = _make_graph()
    g.add_node("a", __label__="Person", name="Alice")
    g.add_node("b", __label__="Person", name="Bob")
    g.add_node("m1", __label__="Movie", title="X")
    g.add_node("m2", __label__="Movie", title="Y")
    g.add_node("m3", __label__="Movie", title="Z")
    # Alice -> 3 movies, Bob -> 1 movie
    g.add_edge("a", "m1", __label__="ACTED_IN")
    g.add_edge("a", "m2", __label__="ACTED_IN")
    g.add_edge("a", "m3", __label__="ACTED_IN")
    g.add_edge("b", "m1", __label__="ACTED_IN")

    profile = NetworkxInspector().inspect(g)
    stats = profile.rel_type_profiles["ACTED_IN"].cardinality_stats

    assert stats is not None
    assert stats.min == 1
    assert stats.max == 3
    assert stats.mean == pytest.approx(2.0)
    assert stats.count == 2


def test_inspect_full_graph():
    g = _make_graph()
    # Nodes
    g.add_node("a", __label__="Person", name="Alice", age=30)
    g.add_node("b", __label__="Person", name="Bob", age=25)
    g.add_node("m1", __label__="Movie", title="Inception", year=2010)
    g.add_node("m2", __label__="Movie", title="Matrix", year=1999)
    g.add_node("c1", __label__="City", name="London")
    # Edges
    g.add_edge("a", "m1", __label__="ACTED_IN", role="Cobb")
    g.add_edge("a", "m2", __label__="ACTED_IN", role="Trinity")
    g.add_edge("b", "m1", __label__="ACTED_IN", role="Arthur")
    g.add_edge("a", "m1", __label__="DIRECTED")
    g.add_edge("a", "c1", __label__="LIVES_IN")

    profile = NetworkxInspector().inspect(g)

    # Node profiles
    assert set(profile.node_labels) == {"Person", "Movie", "City"}
    assert profile.node_type_profiles["Person"].count == 2
    assert profile.node_type_profiles["Movie"].count == 2
    assert profile.node_type_profiles["City"].count == 1

    # Relationship profiles
    assert set(profile.relationship_types) == {"ACTED_IN", "DIRECTED", "LIVES_IN"}
    assert profile.rel_type_profiles["ACTED_IN"].count == 3
    assert profile.rel_type_profiles["DIRECTED"].count == 1
    assert profile.rel_type_profiles["LIVES_IN"].count == 1

    # Property profile on relationships
    acted_in_props = profile.rel_type_profiles["ACTED_IN"].property_profiles
    assert "role" in acted_in_props
    assert acted_in_props["role"].present_count == 3

    # Cardinality
    acted_in_stats = profile.rel_type_profiles["ACTED_IN"].cardinality_stats
    assert acted_in_stats is not None
    assert acted_in_stats.min == 1  # Bob has 1
    assert acted_in_stats.max == 2  # Alice has 2


# --- value_distribution ---


def test_inspect_value_distribution_low_cardinality():
    """Low-cardinality property: full histogram, sample_complete=True."""
    g = _make_graph()
    g.add_node("a", __label__="Person", status="active")
    g.add_node("b", __label__="Person", status="inactive")
    g.add_node("c", __label__="Person", status="active")
    g.add_node("d", __label__="Person", status="active")

    profile = NetworkxInspector().inspect(g)
    dist = (
        profile.node_type_profiles["Person"]
        .property_profiles["status"]
        .value_distribution
    )

    assert dist is not None
    assert dist.sample_complete is True
    assert dist.histogram == {"active": 3, "inactive": 1}
    assert dist.count == 4
    assert dist.other_count == 0


def test_inspect_value_distribution_high_cardinality_truncated():
    """High-cardinality property (> top_n distinct) is truncated."""
    g = _make_graph()
    # 15 distinct values — exceeds the default top_n of 10
    for i in range(15):
        g.add_node(str(i), __label__="Item", uid=f"uid-{i:03d}")

    profile = NetworkxInspector().inspect(g)
    dist = (
        profile.node_type_profiles["Item"].property_profiles["uid"].value_distribution
    )

    assert dist is not None
    assert dist.sample_complete is False
    assert dist.limit == 10  # default VALUE_COUNTS_TOP_N
    assert len(dist.histogram) == 10  # type: ignore[arg-type]
    assert dist.other_count == 5  # 15 - 10 remaining


def test_inspect_value_distribution_top_n_none_disables():
    """top_n=None disables value_distribution entirely."""
    g = _make_graph()
    g.add_node("a", __label__="X", val=1)
    g.add_node("b", __label__="X", val=2)

    profile = NetworkxInspector(value_counts_top_n=None).inspect(g)
    props = profile.node_type_profiles["X"].property_profiles
    dist = props["val"].value_distribution

    assert dist is None


def test_inspect_value_distribution_top_n_zero_disables():
    """top_n=0 disables value_distribution."""
    g = _make_graph()
    g.add_node("a", __label__="X", val=1)

    profile = NetworkxInspector(value_counts_top_n=0).inspect(g)
    props = profile.node_type_profiles["X"].property_profiles
    dist = props["val"].value_distribution

    assert dist is None


def test_inspect_value_distribution_null_values_excluded():
    """Null values are excluded from the histogram."""
    g = _make_graph()
    g.add_node("a", __label__="X", colour="red")
    g.add_node("b", __label__="X", colour=None)
    g.add_node("c", __label__="X", colour="blue")

    profile = NetworkxInspector().inspect(g)
    dist = (
        profile.node_type_profiles["X"].property_profiles["colour"].value_distribution
    )

    assert dist is not None
    assert "red" in (dist.histogram or {})
    assert "blue" in (dist.histogram or {})
    assert None not in (dist.histogram or {})
    assert dist.count == 2  # only non-null


# --- partitioned_cardinality ---


def _operation_sample_model(
    source_cardinality: ConditionalCardinality | CardinalitySpec | str,
) -> GraphDefinition:
    """Build the ADR-029 Operation -[HAS_OUTPUT]-> Sample model.

    Both endpoints are discriminated by ``kind``; the HAS_OUTPUT source side
    carries the supplied cardinality (constant or conditional).
    """

    class Operation(NodeModel):
        __label__ = "Operation"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class Sample(NodeModel):
        __label__ = "Sample"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class HasOutput(RelationshipModel):
        __label__ = "HAS_OUTPUT"
        __source_label__ = "Operation"
        __target_label__ = "Sample"
        __source_cardinality__ = source_cardinality
        __target_cardinality__ = "0..*"

    return GraphDefinition(
        name="OperationSample",
        node_types=[Operation, Sample],
        relationship_types=[HasOutput],
    )


def _deciding_conditional() -> ConditionalCardinality:
    """The ADR-029 deciding scenario: subsampling→subsampling is 1..2."""
    return ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch({"kind": "subsampling"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
        ),
        default="0..*",
    )


def test_inspect_partitioned_cardinality_deciding_scenario():
    """The deciding scenario yields the two expected partitions with correct degrees.

    op1 (subsampling) -> 2 subsampling Samples (s1, s2) and 1 nothing Sample (s3),
    so the (subsampling, subsampling) partition has degree 2 and the
    (subsampling, nothing) partition has degree 1.
    """
    gd = _operation_sample_model(_deciding_conditional())
    g = _make_graph()
    g.add_node("op1", __label__="Operation", uid="op1", kind="subsampling")
    g.add_node("s1", __label__="Sample", uid="s1", kind="subsampling")
    g.add_node("s2", __label__="Sample", uid="s2", kind="subsampling")
    g.add_node("s3", __label__="Sample", uid="s3", kind="nothing")
    g.add_edge("op1", "s1", __label__="HAS_OUTPUT")
    g.add_edge("op1", "s2", __label__="HAS_OUTPUT")
    g.add_edge("op1", "s3", __label__="HAS_OUTPUT")

    profile = NetworkxInspector().inspect(g, graph_definition=gd)
    partitions = profile.rel_type_profiles["HAS_OUTPUT"].source_partitioned_cardinality

    assert partitions is not None
    sub_sub = str(PartitionKey(source_value="subsampling", target_value="subsampling"))
    sub_nothing = str(PartitionKey(source_value="subsampling", target_value="nothing"))
    assert set(partitions) == {sub_sub, sub_nothing}

    assert partitions[sub_sub].min == 2
    assert partitions[sub_sub].max == 2
    assert partitions[sub_sub].count == 1

    assert partitions[sub_nothing].min == 1
    assert partitions[sub_nothing].max == 1
    assert partitions[sub_nothing].count == 1


def test_inspect_partitioned_cardinality_constant_is_none():
    """A relationship with constant cardinality leaves partitioned_cardinality None."""
    gd = _operation_sample_model("0..*")
    g = _make_graph()
    g.add_node("op1", __label__="Operation", uid="op1", kind="subsampling")
    g.add_node("s1", __label__="Sample", uid="s1", kind="subsampling")
    g.add_edge("op1", "s1", __label__="HAS_OUTPUT")

    profile = NetworkxInspector().inspect(g, graph_definition=gd)
    rel = profile.rel_type_profiles["HAS_OUTPUT"]

    assert rel.source_partitioned_cardinality is None
    assert rel.target_partitioned_cardinality is None
    # The simple aggregate is still gathered.
    assert rel.cardinality_stats is not None


def test_inspect_partitioned_cardinality_without_definition_is_none():
    """Without a GraphDefinition the breakdown is not computed (graceful None)."""
    g = _make_graph()
    g.add_node("op1", __label__="Operation", uid="op1", kind="subsampling")
    g.add_node("s1", __label__="Sample", uid="s1", kind="subsampling")
    g.add_edge("op1", "s1", __label__="HAS_OUTPUT")

    profile = NetworkxInspector().inspect(g)

    rel = profile.rel_type_profiles["HAS_OUTPUT"]
    assert rel.source_partitioned_cardinality is None
    assert rel.target_partitioned_cardinality is None


def test_inspect_partitioned_cardinality_zero_output_partition_absent():
    """An Operation with no outputs of a declared pair leaves that partition absent.

    Only observed (src_kind, tgt_kind) pairs become partitions; the missing-partition
    convention (matching the in-memory ``observed.get(partition, 0)``) treats an
    unobserved declared pair as degree 0 at comparison time, so the inspector need
    not synthesise zero-degree partitions.
    """
    gd = _operation_sample_model(_deciding_conditional())
    g = _make_graph()
    # op1 only produces subsampling outputs -> no (subsampling, nothing) partition.
    g.add_node("op1", __label__="Operation", uid="op1", kind="subsampling")
    g.add_node("s1", __label__="Sample", uid="s1", kind="subsampling")
    g.add_node("s2", __label__="Sample", uid="s2", kind="subsampling")
    g.add_edge("op1", "s1", __label__="HAS_OUTPUT")
    g.add_edge("op1", "s2", __label__="HAS_OUTPUT")

    profile = NetworkxInspector().inspect(g, graph_definition=gd)
    partitions = profile.rel_type_profiles["HAS_OUTPUT"].source_partitioned_cardinality

    assert partitions is not None
    sub_sub = str(PartitionKey(source_value="subsampling", target_value="subsampling"))
    assert set(partitions) == {sub_sub}
    assert partitions[sub_sub].min == 2
    assert partitions[sub_sub].max == 2


def test_inspect_partitioned_cardinality_target_side():
    """A target-side conditional partitions a target's incoming edges by source kind.

    Symmetric to the source side: the partition key is still
    (source-label node kind, target-label node kind) per the absolute convention
    (ADR-032 §1a); the counted degree is the target node's incoming degree.
    """

    class Producer(NodeModel):
        __label__ = "Producer"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class Artifact(NodeModel):
        __label__ = "Artifact"
        __uid_field__ = "uid"
        uid: str
        kind: str

    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "assembler"}),
                target=PropMatch({"kind": "final"}),
                spec=CardinalitySpec(min=2, max=2),
            ),
        ),
        default="0..*",
    )

    class Produces(RelationshipModel):
        __label__ = "PRODUCES"
        __source_label__ = "Producer"
        __target_label__ = "Artifact"
        __target_cardinality__ = card

    gd = GraphDefinition(
        name="ProducerArtifact",
        node_types=[Producer, Artifact],
        relationship_types=[Produces],
    )
    g = _make_graph()
    g.add_node("p1", __label__="Producer", uid="p1", kind="assembler")
    g.add_node("p2", __label__="Producer", uid="p2", kind="assembler")
    g.add_node("a1", __label__="Artifact", uid="a1", kind="final")
    g.add_edge("p1", "a1", __label__="PRODUCES")
    g.add_edge("p2", "a1", __label__="PRODUCES")

    profile = NetworkxInspector().inspect(g, graph_definition=gd)
    rtp = profile.rel_type_profiles["PRODUCES"]
    partitions = rtp.target_partitioned_cardinality

    assert partitions is not None
    # A target-side-only conditional leaves the source-side breakdown None.
    assert rtp.source_partitioned_cardinality is None
    assembler_final = str(PartitionKey(source_value="assembler", target_value="final"))
    assert set(partitions) == {assembler_final}
    # a1 has 2 incoming edges from assembler producers.
    assert partitions[assembler_final].min == 2
    assert partitions[assembler_final].max == 2
    assert partitions[assembler_final].count == 1


def test_inspect_partitioned_cardinality_both_sides():
    """A relationship conditional on BOTH endpoints populates both breakdowns (E41.7).

    op1 (assembler) -[MAKES]-> a1 (final), a2 (final).  The source side counts
    op1's outgoing degree by (src_kind, tgt_kind); the target side counts each
    artifact's incoming degree by the same absolute pair.  Both breakdowns must
    be present and correct — the source-only first cut dropped the target side.
    """

    class Operation(NodeModel):
        __label__ = "Operation"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class Sample(NodeModel):
        __label__ = "Sample"
        __uid_field__ = "uid"
        uid: str
        kind: str

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

    class Makes(RelationshipModel):
        __label__ = "MAKES"
        __source_label__ = "Operation"
        __target_label__ = "Sample"
        __source_cardinality__ = source_card
        __target_cardinality__ = target_card

    gd = GraphDefinition(
        name="BothSides",
        node_types=[Operation, Sample],
        relationship_types=[Makes],
    )
    g = _make_graph()
    g.add_node("op1", __label__="Operation", uid="op1", kind="assembler")
    g.add_node("a1", __label__="Sample", uid="a1", kind="final")
    g.add_node("a2", __label__="Sample", uid="a2", kind="final")
    g.add_edge("op1", "a1", __label__="MAKES")
    g.add_edge("op1", "a2", __label__="MAKES")

    profile = NetworkxInspector().inspect(g, graph_definition=gd)
    rtp = profile.rel_type_profiles["MAKES"]
    pair = str(PartitionKey(source_value="assembler", target_value="final"))

    # Source side: op1 has outgoing degree 2 in the (assembler, final) partition.
    assert rtp.source_partitioned_cardinality is not None
    assert set(rtp.source_partitioned_cardinality) == {pair}
    assert rtp.source_partitioned_cardinality[pair].min == 2
    assert rtp.source_partitioned_cardinality[pair].max == 2
    assert rtp.source_partitioned_cardinality[pair].count == 1

    # Target side: a1 and a2 each have incoming degree 1 in the same partition.
    assert rtp.target_partitioned_cardinality is not None
    assert set(rtp.target_partitioned_cardinality) == {pair}
    assert rtp.target_partitioned_cardinality[pair].min == 1
    assert rtp.target_partitioned_cardinality[pair].max == 1
    assert rtp.target_partitioned_cardinality[pair].count == 2
