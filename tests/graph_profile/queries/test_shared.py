"""Tests for orthograph.graph_profile.queries.shared (vendor-neutral Cypher queries).

Pure tests — no database, no mocks.  Verify build()/materialize() and that
injected identifiers are rejected before any Cypher is produced.  These queries
moved out of the neo4j backend (E25 S1) because their Cypher is vendor-neutral.
"""

import pytest

from orthograph.cypher.bindings import NoParams
from orthograph.cypher.exceptions import CypherIdentifierError
from orthograph.graph_profile.models import (
    BoundedDistribution,
    CardinalityStats,
    EndpointLabelsRow,
    PartitionedCardinalityRow,
)
from orthograph.graph_profile.queries.shared import (
    InspectCardinalityQuery,
    InspectEndpointLabelsQuery,
    InspectSourcePartitionedCardinalityQuery,
    InspectTargetPartitionedCardinalityQuery,
)


def _no_params() -> NoParams:
    return NoParams()


# ---------------------------------------------------------------------------
# InspectCardinalityQuery
# ---------------------------------------------------------------------------


def test_cardinality_build_splices_label_and_rel_type() -> None:
    q = InspectCardinalityQuery(identifiers={"label": "Person", "rel_type": "ACTED_IN"})
    cypher, params = q.build(_no_params())
    assert "`Person`" in cypher
    assert "`ACTED_IN`" in cypher
    assert "min_degree" in cypher
    assert params == {}


def test_cardinality_materialize() -> None:
    q = InspectCardinalityQuery(identifiers={"label": "Person", "rel_type": "ACTED_IN"})
    row = q.materialize(
        {"min_degree": 0, "max_degree": 5, "avg_degree": 2.5, "sample_size": 100}
    )
    assert isinstance(row, CardinalityStats)
    assert row.min == 0
    assert row.max == 5
    assert row.mean == 2.5
    assert row.count == 100


def test_cardinality_injected_label_raises() -> None:
    q = InspectCardinalityQuery(
        identifiers={"label": "Person) DETACH DELETE (n //", "rel_type": "X"}
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


def test_cardinality_injected_rel_type_raises() -> None:
    q = InspectCardinalityQuery(
        identifiers={"label": "Person", "rel_type": "X} DELETE ALL //"}
    )
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


# ---------------------------------------------------------------------------
# InspectEndpointLabelsQuery
# ---------------------------------------------------------------------------


def test_endpoint_labels_build_splices_rel_type() -> None:
    q = InspectEndpointLabelsQuery(identifiers={"rel_type": "ACTED_IN"})
    cypher, params = q.build(_no_params())
    assert "`ACTED_IN`" in cypher
    assert "source_labels" in cypher
    assert "target_labels" in cypher
    assert params == {}


def test_endpoint_labels_materialize() -> None:
    q = InspectEndpointLabelsQuery(identifiers={"rel_type": "ACTED_IN"})
    row = q.materialize({"source_labels": ["Person"], "target_labels": ["Movie"]})
    assert isinstance(row, EndpointLabelsRow)
    assert row.source_labels == ["Person"]
    assert row.target_labels == ["Movie"]


def test_endpoint_labels_injected_rel_type_raises() -> None:
    q = InspectEndpointLabelsQuery(identifiers={"rel_type": "X} DETACH DELETE (n //"})
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


# ---------------------------------------------------------------------------
# Partitioned cardinality queries (E41.3 source / E41.7 target)
# ---------------------------------------------------------------------------


def _partitioned_query() -> InspectSourcePartitionedCardinalityQuery:
    return InspectSourcePartitionedCardinalityQuery(
        identifiers={
            "label": "Operation",
            "rel_type": "PRODUCES",
            "source_discriminator": "kind",
            "target_discriminator": "kind",
        }
    )


def _target_partitioned_query() -> InspectTargetPartitionedCardinalityQuery:
    return InspectTargetPartitionedCardinalityQuery(
        identifiers={
            "label": "Sample",
            "rel_type": "PRODUCES",
            "source_discriminator": "kind",
            "target_discriminator": "kind",
        }
    )


def test_partitioned_build_splices_all_four_identifiers() -> None:
    cypher, params = _partitioned_query().build(_no_params())
    assert "`Operation`" in cypher
    assert "`PRODUCES`" in cypher
    # both discriminator property names spliced
    assert "n.`kind`" in cypher
    assert "m.`kind`" in cypher
    # grouped aggregation columns present
    assert "sk" in cypher
    assert "tk" in cypher
    assert "min_degree" in cypher
    assert "max_degree" in cypher
    assert "sample_size" in cypher
    assert params == {}


def test_partitioned_template_contains_all_four_slots() -> None:
    template = InspectSourcePartitionedCardinalityQuery.cypher_template
    assert "<<label>>" in template
    assert "<<rel_type>>" in template
    assert "<<source_discriminator>>" in template
    assert "<<target_discriminator>>" in template


def test_source_query_anchors_on_source_outgoing_degree() -> None:
    """The source query anchors ``MATCH (n:label)`` and counts ``count(n)``."""
    cypher, _ = _partitioned_query().build(_no_params())
    assert "MATCH (n:`Operation`)" in cypher
    assert "count(n) AS sample_size" in cypher
    assert "count(m)" not in cypher


def test_target_query_anchors_on_target_incoming_degree() -> None:
    """The target query anchors ``MATCH (m:label)`` and counts ``count(m)`` (E41.7).

    This is what distinguishes it from the source query: the target side must
    count the target node's incoming degree, not the source node's outgoing one.
    """
    cypher, _ = _target_partitioned_query().build(_no_params())
    assert "MATCH (m:`Sample`)" in cypher
    assert "count(m) AS sample_size" in cypher
    assert "count(n)" not in cypher
    # absolute discriminator convention is preserved (sk from n, tk from m)
    assert "n.`kind` AS sk" in cypher
    assert "m.`kind` AS tk" in cypher


def test_partitioned_template_contains_all_four_slots_target() -> None:
    template = InspectTargetPartitionedCardinalityQuery.cypher_template
    assert "<<label>>" in template
    assert "<<rel_type>>" in template
    assert "<<source_discriminator>>" in template
    assert "<<target_discriminator>>" in template


def test_partitioned_materialize_maps_row() -> None:
    row = _partitioned_query().materialize(
        {
            "sk": "subsampling",
            "tk": "Sample",
            "min_degree": 1,
            "max_degree": 3,
            "avg_degree": 2.0,
            "sample_size": 10,
        }
    )
    assert isinstance(row, PartitionedCardinalityRow)
    assert row.source_value == "subsampling"
    assert row.target_value == "Sample"
    assert isinstance(row.stats, BoundedDistribution)
    # constructed as BoundedDistribution directly, not the CardinalityStats marker
    assert type(row.stats) is BoundedDistribution
    assert row.stats.min == 1
    assert row.stats.max == 3
    assert row.stats.mean == 2.0
    assert row.stats.count == 10


def test_target_partitioned_materialize_maps_row() -> None:
    """The target query shares the source query's row mapping."""
    row = _target_partitioned_query().materialize(
        {
            "sk": "assembler",
            "tk": "final",
            "min_degree": 1,
            "max_degree": 1,
            "avg_degree": 1.0,
            "sample_size": 2,
        }
    )
    assert isinstance(row, PartitionedCardinalityRow)
    assert row.source_value == "assembler"
    assert row.target_value == "final"
    assert type(row.stats) is BoundedDistribution
    assert row.stats.count == 2


def test_partitioned_materialize_null_target_maps_to_none() -> None:
    row = _partitioned_query().materialize(
        {
            "sk": "subsampling",
            "tk": None,
            "min_degree": 0,
            "max_degree": 0,
            "avg_degree": 0.0,
            "sample_size": 4,
        }
    )
    assert row.source_value == "subsampling"
    assert row.target_value is None  # null partition, not the string "null"


def test_partitioned_materialize_null_source_maps_to_none() -> None:
    row = _partitioned_query().materialize(
        {
            "sk": None,
            "tk": "Sample",
            "min_degree": 0,
            "max_degree": 1,
            "avg_degree": 0.5,
            "sample_size": 2,
        }
    )
    assert row.source_value is None
    assert row.target_value == "Sample"


def test_partitioned_injected_source_discriminator_raises() -> None:
    q = InspectSourcePartitionedCardinalityQuery(
        identifiers={
            "label": "Operation",
            "rel_type": "PRODUCES",
            "source_discriminator": "kind` ) DETACH DELETE (n) //",
            "target_discriminator": "kind",
        }
    )
    with pytest.raises(CypherIdentifierError):
        q.build(_no_params())


def test_partitioned_injected_target_discriminator_raises() -> None:
    q = InspectSourcePartitionedCardinalityQuery(
        identifiers={
            "label": "Operation",
            "rel_type": "PRODUCES",
            "source_discriminator": "kind",
            "target_discriminator": "kind` ) DELETE m //",
        }
    )
    with pytest.raises(CypherIdentifierError):
        q.build(_no_params())


def test_partitioned_injected_label_raises() -> None:
    q = InspectSourcePartitionedCardinalityQuery(
        identifiers={
            "label": "Operation) DETACH DELETE (n //",
            "rel_type": "PRODUCES",
            "source_discriminator": "kind",
            "target_discriminator": "kind",
        }
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


def test_partitioned_injected_rel_type_raises() -> None:
    q = InspectSourcePartitionedCardinalityQuery(
        identifiers={
            "label": "Operation",
            "rel_type": "PRODUCES} DELETE ALL //",
            "source_discriminator": "kind",
            "target_discriminator": "kind",
        }
    )
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


def test_target_partitioned_injected_discriminator_raises() -> None:
    """Identifier safety holds for the target query too (E41.7 parity)."""
    q = InspectTargetPartitionedCardinalityQuery(
        identifiers={
            "label": "Sample",
            "rel_type": "PRODUCES",
            "source_discriminator": "kind",
            "target_discriminator": "kind` ) DELETE m //",
        }
    )
    with pytest.raises(CypherIdentifierError):
        q.build(_no_params())
