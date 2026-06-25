"""Tests for orthograph.graph_profile.queries.shared (vendor-neutral Cypher queries).

Pure tests — no database, no mocks.  Verify build()/materialize() and that
injected identifiers are rejected before any Cypher is produced.  These queries
moved out of the neo4j backend because their Cypher is vendor-neutral.
"""

import pytest

from orthograph.cypher.bindings import NoParams
from orthograph.cypher.exceptions import CypherIdentifierError
from orthograph.graph_profile.models import (
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
    q = InspectCardinalityQuery(
        identifiers={"label": "Person", "rel_type": "ACTED_IN", "target_label": "Movie"}
    )
    cypher, params = q.build(_no_params())
    assert "`Person`" in cypher
    assert "`ACTED_IN`" in cypher
    assert "min_degree" in cypher
    assert params == {}


def test_cardinality_materialize() -> None:
    q = InspectCardinalityQuery(
        identifiers={"label": "Person", "rel_type": "ACTED_IN", "target_label": "Movie"}
    )
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
        identifiers={
            "label": "Person) DETACH DELETE (n //",
            "rel_type": "X",
            "target_label": "Movie",
        }
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


def test_cardinality_injected_rel_type_raises() -> None:
    q = InspectCardinalityQuery(
        identifiers={
            "label": "Person",
            "rel_type": "X} DELETE ALL //",
            "target_label": "Movie",
        }
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
# Partitioned cardinality queries (E54.2: variable-width per-side name lists)
#
# Each query carries two *lists* of discriminator property names (one per
# spliceable side).  A list of length k projects k grouped columns for that
# side; an empty list means that endpoint is a wildcard (no grouped column, no
# read of a non-existent property) and reconstructs to the empty map ``{}``.
# This subsumes the former 6-class source/target × {both, wildcard_source,
# wildcard_target} layout into the two source/target classes.
# ---------------------------------------------------------------------------


def _partitioned_query(
    source: list[str] | None = None,
    target: list[str] | None = None,
) -> InspectSourcePartitionedCardinalityQuery:
    return InspectSourcePartitionedCardinalityQuery(
        identifiers={
            "label": "Operation",
            "rel_type": "PRODUCES",
            "endpoint_label": "Sample",
            "source_discriminators": ["kind"] if source is None else source,
            "target_discriminators": ["kind"] if target is None else target,
        }
    )


def _target_partitioned_query(
    source: list[str] | None = None,
    target: list[str] | None = None,
) -> InspectTargetPartitionedCardinalityQuery:
    return InspectTargetPartitionedCardinalityQuery(
        identifiers={
            "label": "Sample",
            "rel_type": "PRODUCES",
            "endpoint_label": "Operation",
            "source_discriminators": ["kind"] if source is None else source,
            "target_discriminators": ["kind"] if target is None else target,
        }
    )


def test_partitioned_build_splices_single_property_each_side() -> None:
    cypher, params = _partitioned_query().build(_no_params())
    assert "`Operation`" in cypher
    assert "`PRODUCES`" in cypher
    # both discriminator property names spliced (one column per side)
    assert "n.`kind` AS sk0" in cypher
    assert "m.`kind` AS tk0" in cypher
    assert "min_degree" in cypher
    assert "max_degree" in cypher
    assert "sample_size" in cypher
    assert params == {}


def test_source_query_anchors_on_source_outgoing_degree() -> None:
    """The source query anchors ``MATCH (n:label)`` and counts ``count(n)``."""
    cypher, _ = _partitioned_query().build(_no_params())
    assert "MATCH (n:`Operation`)" in cypher
    assert "count(n) AS sample_size" in cypher
    assert "count(m)" not in cypher


def test_target_query_anchors_on_target_incoming_degree() -> None:
    """The target query anchors ``MATCH (m:label)`` and counts ``count(m)``.

    This is what distinguishes it from the source query: the target side must
    count the target node's incoming degree, not the source node's outgoing one.
    """
    cypher, _ = _target_partitioned_query().build(_no_params())
    assert "MATCH (m:`Sample`)" in cypher
    assert "count(m) AS sample_size" in cypher
    assert "count(n)" not in cypher
    # absolute discriminator convention is preserved (sk from n, tk from m)
    assert "n.`kind` AS sk0" in cypher
    assert "m.`kind` AS tk0" in cypher


# --- variable-width: multiple properties per side ---


def test_partitioned_build_projects_one_column_per_source_property() -> None:
    """Two source properties → two grouped sk columns spliced safely."""
    cypher, _ = _partitioned_query(source=["kind", "tier"]).build(_no_params())
    assert "n.`kind` AS sk0" in cypher
    assert "n.`tier` AS sk1" in cypher
    # the lone target property keeps its single tk column
    assert "m.`kind` AS tk0" in cypher


def test_partitioned_materialize_two_source_properties() -> None:
    """A two-source-property grouped row → a two-entry source map."""
    row = _partitioned_query(source=["kind", "tier"]).materialize(
        {
            "sk0": "heavy",
            "sk1": "1",
            "tk0": "Sample",
            "min_degree": 2,
            "max_degree": 2,
            "avg_degree": 2.0,
            "sample_size": 1,
        }
    )
    assert isinstance(row, PartitionedCardinalityRow)
    assert row.key.source == {"kind": "heavy", "tier": "1"}
    assert row.key.target == {"kind": "Sample"}
    assert row.stats.min == 2
    assert row.stats.count == 1


def test_partitioned_materialize_three_source_properties() -> None:
    """N-property path: three source columns reconstruct a three-entry map."""
    row = _partitioned_query(source=["a", "b", "c"], target=[]).materialize(
        {
            "sk0": "x",
            "sk1": "y",
            "sk2": "z",
            "min_degree": 1,
            "max_degree": 1,
            "avg_degree": 1.0,
            "sample_size": 5,
        }
    )
    assert row.key.source == {"a": "x", "b": "y", "c": "z"}
    assert row.key.target == {}


def test_partitioned_materialize_mixed_endpoints() -> None:
    """Two source properties + one target property → both maps populated."""
    row = _partitioned_query(source=["stage", "type"], target=["kind"]).materialize(
        {
            "sk0": "final",
            "sk1": "combine",
            "tk0": "output",
            "min_degree": 2,
            "max_degree": 2,
            "avg_degree": 2.0,
            "sample_size": 1,
        }
    )
    assert row.key.source == {"stage": "final", "type": "combine"}
    assert row.key.target == {"kind": "output"}


# --- wildcard side: empty property list → empty map, no grouped column ---


def test_partitioned_wildcard_source_projects_no_source_column() -> None:
    """An empty source list projects no sk column (the former WildcardSource)."""
    cypher, _ = _partitioned_query(source=[], target=["kind"]).build(_no_params())
    assert " AS sk0" not in cypher
    assert "n.`" not in cypher  # no source property read at all
    assert "m.`kind` AS tk0" in cypher


def test_partitioned_wildcard_source_materializes_empty_source_map() -> None:
    row = _partitioned_query(source=[], target=["kind"]).materialize(
        {
            "tk0": "Sample",
            "min_degree": 1,
            "max_degree": 1,
            "avg_degree": 1.0,
            "sample_size": 3,
        }
    )
    assert row.key.source == {}
    assert row.key.target == {"kind": "Sample"}


def test_partitioned_wildcard_target_projects_no_target_column() -> None:
    """An empty target list projects no tk column (the former WildcardTarget)."""
    cypher, _ = _partitioned_query(source=["kind"], target=[]).build(_no_params())
    assert "n.`kind` AS sk0" in cypher
    assert " AS tk0" not in cypher
    assert "m.`" not in cypher  # no target property read at all


def test_partitioned_wildcard_target_materializes_empty_target_map() -> None:
    row = _partitioned_query(source=["kind"], target=[]).materialize(
        {
            "sk0": "subsampling",
            "min_degree": 1,
            "max_degree": 1,
            "avg_degree": 1.0,
            "sample_size": 3,
        }
    )
    assert row.key.source == {"kind": "subsampling"}
    assert row.key.target == {}


# --- None value preservation ---


def test_partitioned_materialize_null_value_maps_to_none() -> None:
    """A null observed value is ``{name: None}`` — present key, null value."""
    row = _partitioned_query(source=["kind"], target=["kind"]).materialize(
        {
            "sk0": "subsampling",
            "tk0": None,
            "min_degree": 0,
            "max_degree": 0,
            "avg_degree": 0.0,
            "sample_size": 4,
        }
    )
    assert row.key.source == {"kind": "subsampling"}
    assert row.key.target == {"kind": None}


# --- injection safety (1-prop and N-prop paths) ---


def test_partitioned_injected_source_discriminator_raises() -> None:
    q = _partitioned_query(source=["kind` ) DETACH DELETE (n) //"], target=["kind"])
    with pytest.raises(CypherIdentifierError):
        q.build(_no_params())


def test_partitioned_injected_target_discriminator_raises() -> None:
    q = _partitioned_query(source=["kind"], target=["kind` ) DELETE m //"])
    with pytest.raises(CypherIdentifierError):
        q.build(_no_params())


def test_partitioned_injected_discriminator_in_n_prop_list_raises() -> None:
    """An unsafe name anywhere in a multi-property list is rejected, not spliced."""
    q = _partitioned_query(source=["kind", "tier`) DELETE n //", "ok"], target=[])
    with pytest.raises(CypherIdentifierError):
        q.build(_no_params())


def test_partitioned_injected_label_raises() -> None:
    q = InspectSourcePartitionedCardinalityQuery(
        identifiers={
            "label": "Operation) DETACH DELETE (n //",
            "rel_type": "PRODUCES",
            "endpoint_label": "Sample",
            "source_discriminators": ["kind"],
            "target_discriminators": ["kind"],
        }
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


def test_partitioned_injected_rel_type_raises() -> None:
    q = InspectSourcePartitionedCardinalityQuery(
        identifiers={
            "label": "Operation",
            "rel_type": "PRODUCES} DELETE ALL //",
            "endpoint_label": "Sample",
            "source_discriminators": ["kind"],
            "target_discriminators": ["kind"],
        }
    )
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


def test_target_partitioned_injected_discriminator_raises() -> None:
    """Identifier safety holds for the target query too."""
    q = _target_partitioned_query(source=["kind"], target=["kind` ) DELETE m //"])
    with pytest.raises(CypherIdentifierError):
        q.build(_no_params())
