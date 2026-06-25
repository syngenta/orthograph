"""Tests for orthograph.backends.memgraph.queries (E17 T7/T8).

All tests are pure — no database connections, no mocks.  They verify:
  * build() returns the expected Cypher string.
  * materialize(fake_row) returns the expected typed output model.
  * An injected rel_type raises CypherIdentifierError before any Cypher is
    produced.
  * The catalogue factory registers the expected query names.
"""

import pytest

from orthograph.backends.memgraph.queries import (
    MemgraphCardinalityQuery,
    MemgraphConstraintRow,
    MemgraphConstraintsQuery,
    MemgraphCountRow,
    MemgraphEndpointLabelsQuery,
    MemgraphNodeCountQuery,
    MemgraphNodePropertiesQuery,
    MemgraphNodePropertyRow,
    MemgraphNodeTypeCountsQuery,
    MemgraphNodeValueHistogramQuery,
    MemgraphRelCountQuery,
    MemgraphRelPropertiesQuery,
    MemgraphRelPropertyRow,
    MemgraphRelTypeCountsQuery,
    MemgraphRelValueHistogramQuery,
    MemgraphTopNParams,
    MemgraphTypeCountRow,
    MemgraphValueHistogramRow,
    build_memgraph_catalogue,
)
from orthograph.cypher.bindings import NoParams
from orthograph.cypher.exceptions import CypherIdentifierError
from orthograph.graph_profile.models import CardinalityStats, EndpointLabelsRow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_params() -> NoParams:
    return NoParams()


# ---------------------------------------------------------------------------
# MemgraphNodePropertiesQuery
# ---------------------------------------------------------------------------


def test_mg_node_properties_build() -> None:
    q = MemgraphNodePropertiesQuery()
    cypher, params = q.build(_no_params())
    assert "schema.node_type_properties()" in cypher
    assert "nodeType" in cypher
    assert params == {}


def test_mg_node_properties_materialize() -> None:
    q = MemgraphNodePropertiesQuery()
    row = q.materialize(
        {
            "nodeType": ":`Person`",
            "nodeLabels": ["Person"],
            "mandatory": True,
            "propertyName": "name",
            "propertyTypes": ["String"],
        }
    )
    assert isinstance(row, MemgraphNodePropertyRow)
    assert row.node_type == ":`Person`"
    assert row.node_labels == ["Person"]
    assert row.mandatory is True
    assert row.property_name == "name"
    assert row.property_types == ["String"]


def test_mg_node_properties_materialize_no_property() -> None:
    """Rows with no propertyName (label-only sentinels) are handled."""
    q = MemgraphNodePropertiesQuery()
    row = q.materialize(
        {
            "nodeType": ":`Empty`",
            "nodeLabels": ["Empty"],
            "mandatory": False,
            "propertyName": None,
            "propertyTypes": [],
        }
    )
    assert row.property_name is None


# ---------------------------------------------------------------------------
# MemgraphRelPropertiesQuery
# ---------------------------------------------------------------------------


def test_mg_rel_properties_build() -> None:
    q = MemgraphRelPropertiesQuery()
    cypher, params = q.build(_no_params())
    assert "schema.rel_type_properties()" in cypher
    assert "relType" in cypher
    assert params == {}


def test_mg_rel_properties_materialize() -> None:
    q = MemgraphRelPropertiesQuery()
    row = q.materialize(
        {
            "relType": ":`ACTED_IN`",
            "mandatory": True,
            "propertyName": "role",
            "propertyTypes": ["String"],
        }
    )
    assert isinstance(row, MemgraphRelPropertyRow)
    assert row.rel_type == ":`ACTED_IN`"
    assert row.mandatory is True
    assert row.property_name == "role"


# ---------------------------------------------------------------------------
# MemgraphConstraintsQuery
# ---------------------------------------------------------------------------


def test_mg_constraints_build() -> None:
    q = MemgraphConstraintsQuery()
    cypher, params = q.build(_no_params())
    assert "SHOW CONSTRAINT INFO" in cypher
    assert params == {}


def test_mg_constraints_materialize() -> None:
    q = MemgraphConstraintsQuery()
    row = q.materialize(
        {
            "constraint type": "UNIQUE",
            "entity type": "NODE",
            "label": "Person",
            "properties": ["name"],
        }
    )
    assert isinstance(row, MemgraphConstraintRow)
    assert row.constraint_type == "UNIQUE"
    assert row.entity_type == "NODE"
    assert row.label == "Person"
    assert row.properties == ["name"]


# ---------------------------------------------------------------------------
# MemgraphNodeCountQuery / MemgraphRelCountQuery (E46.3 — true completeness
# denominator; property-independent count())
# ---------------------------------------------------------------------------


def test_mg_node_count_build_splices_label() -> None:
    q = MemgraphNodeCountQuery(identifiers={"label": "Person"})
    cypher, params = q.build(_no_params())
    assert "`Person`" in cypher
    assert "count(n) AS count" in cypher
    assert params == {}


def test_mg_node_count_materialize() -> None:
    q = MemgraphNodeCountQuery(identifiers={"label": "Person"})
    row = q.materialize({"count": 172})
    assert isinstance(row, MemgraphCountRow)
    assert row.count == 172


def test_mg_node_count_injected_label_raises() -> None:
    q = MemgraphNodeCountQuery(identifiers={"label": "Person) DETACH DELETE (n"})
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


def test_mg_rel_count_build_splices_rel_type() -> None:
    q = MemgraphRelCountQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "ACTED_IN",
            "target_label": "Movie",
        }
    )
    cypher, params = q.build(_no_params())
    assert "`ACTED_IN`" in cypher
    assert "`Person`" in cypher
    assert "`Movie`" in cypher
    assert "count(r) AS count" in cypher
    assert params == {}


def test_mg_rel_count_materialize() -> None:
    q = MemgraphRelCountQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "ACTED_IN",
            "target_label": "Movie",
        }
    )
    row = q.materialize({"count": 49})
    assert isinstance(row, MemgraphCountRow)
    assert row.count == 49


def test_mg_rel_count_injected_rel_type_raises() -> None:
    q = MemgraphRelCountQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "X`bad",
            "target_label": "Movie",
        }
    )
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


# ---------------------------------------------------------------------------
# MemgraphCardinalityQuery (subclass of shared InspectCardinalityQuery)
# ---------------------------------------------------------------------------


def test_mg_cardinality_build_splices_identifiers() -> None:
    q = MemgraphCardinalityQuery(
        identifiers={"label": "Person", "rel_type": "ACTED_IN", "target_label": "Movie"}
    )
    cypher, params = q.build(_no_params())
    assert "`Person`" in cypher
    assert "`ACTED_IN`" in cypher
    assert "`Movie`" in cypher
    assert params == {}


def test_mg_cardinality_materialize() -> None:
    q = MemgraphCardinalityQuery(
        identifiers={"label": "Person", "rel_type": "ACTED_IN", "target_label": "Movie"}
    )
    row = q.materialize(
        {"min_degree": 1, "max_degree": 3, "avg_degree": 2.0, "sample_size": 50}
    )
    assert isinstance(row, CardinalityStats)
    assert row.count == 50


def test_mg_cardinality_injected_label_raises() -> None:
    q = MemgraphCardinalityQuery(
        identifiers={
            "label": "Person) DETACH DELETE (n",
            "rel_type": "X",
            "target_label": "Movie",
        }
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


def test_mg_cardinality_injected_rel_type_raises() -> None:
    q = MemgraphCardinalityQuery(
        identifiers={"label": "Person", "rel_type": "X`bad", "target_label": "Movie"}
    )
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


# ---------------------------------------------------------------------------
# MemgraphEndpointLabelsQuery
# ---------------------------------------------------------------------------


def test_mg_endpoint_labels_build_splices_rel_type() -> None:
    q = MemgraphEndpointLabelsQuery(identifiers={"rel_type": "OWNS"})
    cypher, params = q.build(_no_params())
    assert "`OWNS`" in cypher
    assert "source_labels" in cypher
    assert "target_labels" in cypher
    assert params == {}


def test_mg_endpoint_labels_materialize() -> None:
    q = MemgraphEndpointLabelsQuery(identifiers={"rel_type": "OWNS"})
    row = q.materialize({"source_labels": ["User"], "target_labels": ["Device"]})
    assert isinstance(row, EndpointLabelsRow)
    assert row.source_labels == ["User"]
    assert row.target_labels == ["Device"]


def test_mg_endpoint_labels_injected_rel_type_raises() -> None:
    q = MemgraphEndpointLabelsQuery(identifiers={"rel_type": "X) DETACH DELETE //"})
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


# ---------------------------------------------------------------------------
# Catalogue factory
# ---------------------------------------------------------------------------


def test_memgraph_catalogue_registered_names() -> None:
    query_catalogue = build_memgraph_catalogue()
    names = query_catalogue.names()
    assert "memgraph.inspect.node_properties" in names
    assert "memgraph.inspect.rel_properties" in names
    assert "memgraph.inspect.constraints" in names
    assert "memgraph.inspect.node_count" in names
    assert "memgraph.inspect.rel_count" in names
    assert "memgraph.inspect.cardinality" in names
    assert "memgraph.inspect.endpoint_labels" in names
    assert "memgraph.inspect.partitioned_cardinality.source" in names
    assert "memgraph.inspect.partitioned_cardinality.target" in names
    # E49 T2: one-sided (wildcard) partitioned-cardinality variants.
    assert "memgraph.inspect.partitioned_cardinality.source.wildcard_source" in names
    assert "memgraph.inspect.partitioned_cardinality.source.wildcard_target" in names
    assert "memgraph.inspect.partitioned_cardinality.target.wildcard_source" in names
    assert "memgraph.inspect.partitioned_cardinality.target.wildcard_target" in names
    assert "memgraph.inspect.node_type_counts" in names
    assert "memgraph.inspect.rel_type_counts" in names
    assert "memgraph.inspect.node_value_histogram" in names
    assert "memgraph.inspect.rel_value_histogram" in names
    assert len(names) == 17


def test_memgraph_catalogue_all_reads_have_output_schema() -> None:
    query_catalogue = build_memgraph_catalogue()
    for desc in query_catalogue.describe():
        if desc.kind == "read":
            assert desc.output_schema is not None, f"{desc.name} has no output_schema"


# ---------------------------------------------------------------------------
# Value-scan queries (E46.3, ADR-035) — type counts + scalar histogram
# ---------------------------------------------------------------------------


def test_mg_node_type_counts_build_groups_by_type_not_value() -> None:
    """Type-count query groups on valueType() (by type, never by value)."""
    q = MemgraphNodeTypeCountsQuery(
        identifiers={"label": "Reading", "property_name": "value"}
    )
    cypher, params = q.build(_no_params())
    assert "`Reading`" in cypher
    assert "`value`" in cypher
    assert "valueType(" in cypher
    assert "IS NOT NULL" in cypher
    # Bounded: groups by type, no value interpolation, no LIMIT needed.
    assert "$" not in cypher  # no value parameters
    assert params == {}


def test_mg_node_type_counts_materialize_normalises_vocabulary() -> None:
    """valueType() names map onto the schema observed_types vocabulary."""
    q = MemgraphNodeTypeCountsQuery(
        identifiers={"label": "Reading", "property_name": "value"}
    )
    row = q.materialize({"type_name": "INTEGER", "type_count": 95})
    assert isinstance(row, MemgraphTypeCountRow)
    assert row.type_name == "Int"
    assert row.type_count == 95


def test_mg_node_type_counts_materialize_unknown_type_passes_through() -> None:
    """Unrecognised valueType() names pass through verbatim (never invent)."""
    q = MemgraphNodeTypeCountsQuery(identifiers={"label": "X", "property_name": "p"})
    row = q.materialize({"type_name": "SOMETHING_NEW", "type_count": 1})
    assert row.type_name == "SOMETHING_NEW"


def test_mg_rel_type_counts_build() -> None:
    q = MemgraphRelTypeCountsQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "ACTED_IN",
            "target_label": "Movie",
            "property_name": "role",
        }
    )
    cypher, params = q.build(_no_params())
    assert "`ACTED_IN`" in cypher
    assert "`role`" in cypher
    assert "valueType(" in cypher
    assert params == {}


def test_mg_node_value_histogram_build_is_scalar_safe_and_bounded() -> None:
    """Histogram groups on toStringOrNull() (list-safe) and applies LIMIT $top_n."""
    q = MemgraphNodeValueHistogramQuery(
        identifiers={"label": "Reading", "property_name": "value"}
    )
    cypher, params = q.build(MemgraphTopNParams(top_n=10))
    assert "`Reading`" in cypher
    assert "`value`" in cypher
    # toStringOrNull is the list-safe key (lists -> null -> dropped).
    assert "toStringOrNull(" in cypher
    assert "LIMIT $top_n" in cypher
    assert params == {"top_n": 10}


def test_mg_node_value_histogram_materialize() -> None:
    q = MemgraphNodeValueHistogramQuery(
        identifiers={"label": "Reading", "property_name": "value"}
    )
    row = q.materialize({"value": "active", "value_count": 3})
    assert isinstance(row, MemgraphValueHistogramRow)
    assert row.value == "active"
    assert row.value_count == 3


def test_mg_rel_value_histogram_build() -> None:
    q = MemgraphRelValueHistogramQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "ACTED_IN",
            "target_label": "Movie",
            "property_name": "role",
        }
    )
    cypher, params = q.build(MemgraphTopNParams(top_n=5))
    assert "`ACTED_IN`" in cypher
    assert "toStringOrNull(" in cypher
    assert "LIMIT $top_n" in cypher
    assert params == {"top_n": 5}


def test_mg_type_counts_injected_label_raises() -> None:
    q = MemgraphNodeTypeCountsQuery(
        identifiers={"label": "Reading`) DETACH DELETE (n", "property_name": "value"}
    )
    with pytest.raises(CypherIdentifierError):
        q.build(_no_params())
