"""Tests for orthograph.backends.neo4j.queries (E17 T7/T8).

All tests are pure — no database connections, no mocks.  They verify:
  * build() returns the expected Cypher string (identifier substitution works).
  * materialize(fake_row) returns the expected typed output model.
  * An injected label/rel_type raises CypherIdentifierError before any
    Cypher is produced.
  * The catalogue factories register the expected query names.

The vendor-neutral cardinality and endpoint-label query tests live in
``tests/profile/queries/test_shared.py`` (E25 S1).
"""

import pytest

from orthograph.backends.neo4j.queries import (
    ApocNodePropertiesQuery,
    ApocRelPropertiesQuery,
    CypherNodePropertiesQuery,
    CypherRelPropertiesQuery,
    DbSchemaNodeTypeRow,
    DbSchemaNodeTypesQuery,
    DbSchemaRelTypeRow,
    DbSchemaRelTypesQuery,
    InspectNeo4jConstraintsQuery,
    InspectNodeLabelsQuery,
    InspectRelTypesQuery,
    NodeLabelRow,
    NodePropertyRow,
    RelTypeLabelRow,
    build_apoc_catalogue,
    build_cypher_catalogue,
    build_schema_catalogue,
)
from orthograph.cypher.bindings import NoParams
from orthograph.cypher.exceptions import CypherIdentifierError
from orthograph.graph_profile.models import ConstraintInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_params() -> NoParams:
    return NoParams()


# ---------------------------------------------------------------------------
# InspectNodeLabelsQuery
# ---------------------------------------------------------------------------


def test_node_labels_build_returns_expected_cypher() -> None:
    q = InspectNodeLabelsQuery()
    cypher, params = q.build(_no_params())
    assert "CALL db.labels()" in cypher
    assert "RETURN label" in cypher
    assert params == {}


def test_node_labels_materialize() -> None:
    q = InspectNodeLabelsQuery()
    row = q.materialize({"label": "Person"})
    assert isinstance(row, NodeLabelRow)
    assert row.label == "Person"


# ---------------------------------------------------------------------------
# InspectRelTypesQuery
# ---------------------------------------------------------------------------


def test_rel_types_build_returns_expected_cypher() -> None:
    q = InspectRelTypesQuery()
    cypher, params = q.build(_no_params())
    assert "db.relationshipTypes()" in cypher
    assert "RETURN relationshipType" in cypher
    assert params == {}


def test_rel_types_materialize() -> None:
    q = InspectRelTypesQuery()
    row = q.materialize({"relationshipType": "ACTED_IN"})
    assert isinstance(row, RelTypeLabelRow)
    assert row.relationship_type == "ACTED_IN"


# ---------------------------------------------------------------------------
# InspectNeo4jConstraintsQuery
# ---------------------------------------------------------------------------


def test_constraints_build() -> None:
    q = InspectNeo4jConstraintsQuery()
    cypher, params = q.build(_no_params())
    assert "SHOW CONSTRAINTS" in cypher
    assert params == {}


def test_constraints_materialize() -> None:
    q = InspectNeo4jConstraintsQuery()
    row = q.materialize(
        {
            "name": "constraint_person_name",
            "type": "UNIQUENESS",
            "entityType": "NODE",
            "labelsOrTypes": ["Person"],
            "properties": ["name"],
            "propertyType": None,
        }
    )
    assert isinstance(row, ConstraintInfo)
    assert row.constraint_type == "UNIQUENESS"
    assert row.entity_type == "NODE"
    assert row.labels == ["Person"]
    assert row.properties == ["name"]
    assert row.property_type is None


# ---------------------------------------------------------------------------
# ApocNodePropertiesQuery
# ---------------------------------------------------------------------------


def test_apoc_node_properties_build_contains_label() -> None:
    q = ApocNodePropertiesQuery(identifiers={"label": "Person"})
    cypher, params = q.build(_no_params())
    assert "apoc.meta.nodeTypeProperties" in cypher
    assert "'Person'" in cypher
    assert params == {}


def test_apoc_node_properties_materialize() -> None:
    q = ApocNodePropertiesQuery(identifiers={"label": "Person"})
    row = q.materialize(
        {
            "propertyName": "name",
            "propertyTypes": ["String"],
            "mandatory": True,
            "propertyObservations": 100,
            "totalObservations": 100,
        }
    )
    assert isinstance(row, NodePropertyRow)
    assert row.property_name == "name"
    assert row.property_types == ["String"]
    assert row.mandatory is True
    assert row.property_observations == 100
    assert row.total_observations == 100


def test_apoc_node_properties_injected_label_raises() -> None:
    q = ApocNodePropertiesQuery(identifiers={"label": "Person) DETACH DELETE (n //"})
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


# ---------------------------------------------------------------------------
# ApocRelPropertiesQuery
# ---------------------------------------------------------------------------


def test_apoc_rel_properties_build_contains_rel_type() -> None:
    q = ApocRelPropertiesQuery(identifiers={"rel_type": "ACTED_IN"})
    cypher, params = q.build(_no_params())
    assert "apoc.meta.relTypeProperties" in cypher
    assert "ACTED_IN" in cypher
    assert params == {}


def test_apoc_rel_properties_injected_rel_type_raises() -> None:
    q = ApocRelPropertiesQuery(identifiers={"rel_type": "X} DELETE ALL //"})
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


def test_apoc_rel_properties_materialize() -> None:
    q = ApocRelPropertiesQuery(identifiers={"rel_type": "ACTED_IN"})
    row = q.materialize(
        {
            "propertyName": "role",
            "propertyTypes": ["String"],
            "mandatory": True,
            "propertyObservations": 200,
            "totalObservations": 200,
        }
    )
    assert row.property_name == "role"
    assert row.property_types == ["String"]
    assert row.mandatory is True


# ---------------------------------------------------------------------------
# CypherNodePropertiesQuery
# ---------------------------------------------------------------------------


def test_cypher_node_properties_build_contains_label() -> None:
    q = CypherNodePropertiesQuery(identifiers={"label": "Movie"})
    cypher, params = q.build(_no_params())
    assert "`Movie`" in cypher
    # Two occurrences (two-pass MATCH)
    assert cypher.count("`Movie`") == 2
    assert params == {}


def test_cypher_node_properties_materialize_empty_types() -> None:
    q = CypherNodePropertiesQuery(identifiers={"label": "Movie"})
    row = q.materialize(
        {
            "propertyName": "title",
            "propertyTypes": [],
            "mandatory": True,
            "propertyObservations": 50,
            "totalObservations": 50,
        }
    )
    assert row.property_name == "title"
    assert row.property_types == []


def test_cypher_node_properties_injected_label_raises() -> None:
    q = CypherNodePropertiesQuery(identifiers={"label": "1BadLabel"})
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


# ---------------------------------------------------------------------------
# CypherRelPropertiesQuery
# ---------------------------------------------------------------------------


def test_cypher_rel_properties_build_contains_rel_type() -> None:
    q = CypherRelPropertiesQuery(identifiers={"rel_type": "OWNS"})
    cypher, params = q.build(_no_params())
    assert "`OWNS`" in cypher
    assert cypher.count("`OWNS`") == 2
    assert params == {}


def test_cypher_rel_properties_injected_rel_type_raises() -> None:
    q = CypherRelPropertiesQuery(identifiers={"rel_type": "X`Y"})
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


# ---------------------------------------------------------------------------
# DbSchemaNodeTypesQuery
# ---------------------------------------------------------------------------


def test_db_schema_node_types_build_returns_expected_cypher() -> None:
    q = DbSchemaNodeTypesQuery()
    cypher, params = q.build(_no_params())
    assert "CALL db.schema.nodeTypeProperties()" in cypher
    assert "nodeType" in cypher
    assert "propertyTypes" in cypher
    # Bulk query — no interpolated identifier slots.
    assert "<<" not in cypher
    assert params == {}


def test_db_schema_node_types_materialize_strips_prefix() -> None:
    q = DbSchemaNodeTypesQuery()
    row = q.materialize(
        {
            "nodeType": ":`Sample`",
            "nodeLabels": ["Sample"],
            "propertyName": "name",
            "propertyTypes": ["String"],
            "mandatory": True,
        }
    )
    assert isinstance(row, DbSchemaNodeTypeRow)
    assert row.label == "Sample"
    assert row.property_name == "name"
    assert row.observed_types == ["String"]


def test_db_schema_node_types_materialize_none_property() -> None:
    """A node type with no properties yields propertyName/propertyTypes None."""
    q = DbSchemaNodeTypesQuery()
    row = q.materialize(
        {
            "nodeType": ":`Empty`",
            "nodeLabels": ["Empty"],
            "propertyName": None,
            "propertyTypes": None,
            "mandatory": False,
        }
    )
    assert row.label == "Empty"
    assert row.property_name is None
    assert row.observed_types == []


# ---------------------------------------------------------------------------
# DbSchemaRelTypesQuery
# ---------------------------------------------------------------------------


def test_db_schema_rel_types_build_returns_expected_cypher() -> None:
    q = DbSchemaRelTypesQuery()
    cypher, params = q.build(_no_params())
    assert "CALL db.schema.relTypeProperties()" in cypher
    assert "relType" in cypher
    assert "propertyTypes" in cypher
    assert "<<" not in cypher
    assert params == {}


def test_db_schema_rel_types_materialize_strips_prefix() -> None:
    q = DbSchemaRelTypesQuery()
    row = q.materialize(
        {
            "relType": ":`ACTED_IN`",
            "propertyName": "role",
            "propertyTypes": ["String"],
            "mandatory": False,
        }
    )
    assert isinstance(row, DbSchemaRelTypeRow)
    assert row.rel_type == "ACTED_IN"
    assert row.property_name == "role"
    assert row.observed_types == ["String"]


def test_db_schema_rel_types_materialize_none_property() -> None:
    """A rel type with no properties yields propertyName/propertyTypes None."""
    q = DbSchemaRelTypesQuery()
    row = q.materialize(
        {
            "relType": ":`HAS_SAMPLE`",
            "propertyName": None,
            "propertyTypes": None,
            "mandatory": False,
        }
    )
    assert row.rel_type == "HAS_SAMPLE"
    assert row.property_name is None
    assert row.observed_types == []


# ---------------------------------------------------------------------------
# Catalogue factories
# ---------------------------------------------------------------------------


def test_apoc_catalogue_registered_names() -> None:
    query_catalogue = build_apoc_catalogue()
    names = query_catalogue.names()
    assert "neo4j.inspect.node_labels" in names
    assert "neo4j.inspect.rel_types" in names
    assert "neo4j.inspect.apoc.node_properties" in names
    assert "neo4j.inspect.apoc.rel_properties" in names
    assert "inspect.cardinality" in names
    assert "neo4j.inspect.constraints" in names
    assert "inspect.endpoint_labels" in names
    assert len(names) == 7


def test_cypher_catalogue_registered_names() -> None:
    query_catalogue = build_cypher_catalogue()
    names = query_catalogue.names()
    assert "neo4j.inspect.cypher.node_properties" in names
    assert "neo4j.inspect.cypher.rel_properties" in names
    assert "inspect.endpoint_labels" in names
    assert len(names) == 7


def test_schema_catalogue_registered_names() -> None:
    query_catalogue = build_schema_catalogue()
    names = query_catalogue.names()
    # The pure-Cypher scan queries (for true counts)
    assert "neo4j.inspect.cypher.node_properties" in names
    assert "neo4j.inspect.cypher.rel_properties" in names
    # The db.schema.* type queries
    assert "neo4j.inspect.schema.node_types" in names
    assert "neo4j.inspect.schema.rel_types" in names
    # Shared neutral queries
    assert "neo4j.inspect.node_labels" in names
    assert "neo4j.inspect.rel_types" in names
    assert "inspect.cardinality" in names
    assert "neo4j.inspect.constraints" in names
    assert "inspect.endpoint_labels" in names
    assert len(names) == 9


def test_catalogue_all_reads_have_output_schema() -> None:
    """Every registered read must have an output_schema (non-None)."""
    for query_catalogue in (
        build_apoc_catalogue(),
        build_cypher_catalogue(),
        build_schema_catalogue(),
    ):
        for desc in query_catalogue.describe():
            if desc.kind == "read":
                assert desc.output_schema is not None, (
                    f"{desc.name} has no output_schema"
                )
