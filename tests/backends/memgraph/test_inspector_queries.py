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
    MemgraphEndpointLabelsQuery,
    MemgraphNodePropertiesQuery,
    MemgraphNodePropertyRow,
    MemgraphRelPropertiesQuery,
    MemgraphRelPropertyRow,
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
# MemgraphCardinalityQuery (subclass of shared InspectCardinalityQuery)
# ---------------------------------------------------------------------------


def test_mg_cardinality_build_splices_identifiers() -> None:
    q = MemgraphCardinalityQuery(
        identifiers={"label": "Person", "rel_type": "ACTED_IN"}
    )
    cypher, params = q.build(_no_params())
    assert "`Person`" in cypher
    assert "`ACTED_IN`" in cypher
    assert params == {}


def test_mg_cardinality_materialize() -> None:
    q = MemgraphCardinalityQuery(
        identifiers={"label": "Person", "rel_type": "ACTED_IN"}
    )
    row = q.materialize(
        {"min_degree": 1, "max_degree": 3, "avg_degree": 2.0, "sample_size": 50}
    )
    assert isinstance(row, CardinalityStats)
    assert row.count == 50


def test_mg_cardinality_injected_label_raises() -> None:
    q = MemgraphCardinalityQuery(
        identifiers={"label": "Person) DETACH DELETE (n", "rel_type": "X"}
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


def test_mg_cardinality_injected_rel_type_raises() -> None:
    q = MemgraphCardinalityQuery(identifiers={"label": "Person", "rel_type": "X`bad"})
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
    assert "memgraph.inspect.cardinality" in names
    assert "memgraph.inspect.endpoint_labels" in names
    assert "memgraph.inspect.partitioned_cardinality.source" in names
    assert "memgraph.inspect.partitioned_cardinality.target" in names
    assert len(names) == 7


def test_memgraph_catalogue_all_reads_have_output_schema() -> None:
    query_catalogue = build_memgraph_catalogue()
    for desc in query_catalogue.describe():
        if desc.kind == "read":
            assert desc.output_schema is not None, f"{desc.name} has no output_schema"
