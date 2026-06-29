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
    ApocNodeTypeCountsQuery,
    ApocNodeValueHistogramQuery,
    ApocRelTypeCountsQuery,
    ApocRelTypesQuery,
    ApocRelValueHistogramQuery,
    CypherNodePropertiesQuery,
    CypherNodeValueHistogramQuery,
    CypherRelPropertiesQuery,
    CypherRelValueHistogramQuery,
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
    TypeCountRow,
    ValueHistogramRow,
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
# ApocRelTypesQuery  (ADR-037 §6a: bulk bare-type source, replaces per-rel APOC)
# ---------------------------------------------------------------------------


def test_apoc_rel_types_build_calls_apoc_meta() -> None:
    """ApocRelTypesQuery is a bulk query — no identifier slots, calls apoc.meta."""
    q = ApocRelTypesQuery()
    cypher, params = q.build(_no_params())
    assert "apoc.meta.relTypeProperties" in cypher
    assert "relType" in cypher
    assert "propertyName" in cypher
    assert "propertyTypes" in cypher
    assert params == {}


def test_apoc_rel_types_materialize_with_property() -> None:
    """A row with a property name and types materialises as DbSchemaRelTypeRow."""
    q = ApocRelTypesQuery()
    row = q.materialize(
        {
            "relType": ":`ACTED_IN`",
            "propertyName": "role",
            "propertyTypes": ["String"],
        }
    )
    assert isinstance(row, DbSchemaRelTypeRow)
    assert row.rel_type == "ACTED_IN"  # backtick-quoted prefix stripped
    assert row.property_name == "role"
    assert row.observed_types == ["String"]


def test_apoc_rel_types_materialize_no_property() -> None:
    """A row with propertyName=None materialises with property_name=None."""
    q = ApocRelTypesQuery()
    row = q.materialize(
        {"relType": ":`HAS_OUTPUT`", "propertyName": None, "propertyTypes": None}
    )
    assert row.rel_type == "HAS_OUTPUT"
    assert row.property_name is None
    assert row.observed_types == []


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
    q = CypherRelPropertiesQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "OWNS",
            "target_label": "Movie",
        }
    )
    cypher, params = q.build(_no_params())
    assert "`OWNS`" in cypher
    assert cypher.count("`OWNS`") == 2
    assert "`Person`" in cypher
    assert "`Movie`" in cypher
    assert params == {}


def test_cypher_rel_properties_injected_rel_type_raises() -> None:
    q = CypherRelPropertiesQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "X`Y",
            "target_label": "Movie",
        }
    )
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


def test_cypher_rel_properties_injected_source_label_raises() -> None:
    q = CypherRelPropertiesQuery(
        identifiers={
            "source_label": "Person) DETACH DELETE (n //",
            "rel_type": "KNOWS",
            "target_label": "Person",
        }
    )
    with pytest.raises(CypherIdentifierError, match="label"):
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
# Value-scan: type-count queries
# Group by runtime type, count per group -> exact, bounded {type: count}.
# ---------------------------------------------------------------------------


def test_apoc_node_type_counts_build_groups_by_type_not_value() -> None:
    q = ApocNodeTypeCountsQuery(
        identifiers={"label": "Person", "property_name": "born"}
    )
    cypher, params = q.build(_no_params())
    # Scoped to the property of the label, splicing the identifiers safely.
    assert "`Person`" in cypher
    assert "`born`" in cypher
    # Groups by runtime type via the APOC type function, never by raw value.
    assert "apoc.meta.cypher.type" in cypher
    # The grouped value is the type name, not the value itself.
    assert "count(" in cypher
    # No driver value parameters and no value interpolation.
    assert params == {}


def test_apoc_node_type_counts_materialize() -> None:
    q = ApocNodeTypeCountsQuery(
        identifiers={"label": "Person", "property_name": "born"}
    )
    # apoc.meta.cypher.type yields the upper-case runtime vocabulary
    # ('INTEGER'); the materialiser normalises to the observed_types vocabulary
    # ('Long') so set(observed_type_counts) ⊆ set(observed_types) (ADR-035 §3).
    row = q.materialize({"type_name": "INTEGER", "type_count": 95})
    assert isinstance(row, TypeCountRow)
    assert row.type_name == "Long"
    assert row.type_count == 95


def test_apoc_node_type_counts_materialize_normalises_vocabulary() -> None:
    q = ApocNodeTypeCountsQuery(
        identifiers={"label": "Person", "property_name": "tags"}
    )
    assert q.materialize({"type_name": "STRING", "type_count": 3}).type_name == (
        "String"
    )
    assert q.materialize({"type_name": "FLOAT", "type_count": 1}).type_name == (
        "Double"
    )
    assert (
        q.materialize({"type_name": "LIST OF INTEGER", "type_count": 2}).type_name
        == "LongArray"
    )
    # An unrecognised runtime type passes through verbatim (never invented).
    assert q.materialize({"type_name": "EXOTIC", "type_count": 1}).type_name == "EXOTIC"
    # A mixed-element list yields 'LIST OF ANY' from apoc.meta.cypher.type; it is
    # not in the map, so it passes through unchanged (honest, never invented).
    assert (
        q.materialize({"type_name": "LIST OF ANY", "type_count": 1}).type_name
        == "LIST OF ANY"
    )


def test_apoc_node_type_counts_injected_label_raises() -> None:
    q = ApocNodeTypeCountsQuery(
        identifiers={"label": "P) DETACH DELETE (n //", "property_name": "born"}
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


def test_apoc_node_type_counts_injected_property_raises() -> None:
    q = ApocNodeTypeCountsQuery(
        identifiers={"label": "Person", "property_name": "x` // bad"}
    )
    with pytest.raises(CypherIdentifierError):
        q.build(_no_params())


def test_apoc_rel_type_counts_build_groups_by_type() -> None:
    q = ApocRelTypeCountsQuery(
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
    assert "apoc.meta.cypher.type" in cypher
    assert params == {}


def test_apoc_rel_type_counts_materialize() -> None:
    q = ApocRelTypeCountsQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "ACTED_IN",
            "target_label": "Movie",
            "property_name": "role",
        }
    )
    row = q.materialize({"type_name": "STRING", "type_count": 200})
    assert row.type_name == "String"
    assert row.type_count == 200


def test_apoc_rel_type_counts_injected_rel_type_raises() -> None:
    q = ApocRelTypeCountsQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "X} DELETE ALL //",
            "target_label": "Movie",
            "property_name": "role",
        }
    )
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


# ---------------------------------------------------------------------------
# Value-scan: value-histogram queries (E46.1)
# Group by value, ORDER BY frequency, LIMIT top_n -> the only truncating part.
# ---------------------------------------------------------------------------


def test_apoc_node_value_histogram_build_limits_by_param() -> None:
    q = ApocNodeValueHistogramQuery(
        identifiers={"label": "Person", "property_name": "born"}
    )
    cypher, params = q.build(q.params_schema(top_n=10))
    assert "`Person`" in cypher
    assert "`born`" in cypher
    # The histogram groups by value and truncates with a parameterised LIMIT.
    assert "LIMIT $top_n" in cypher
    # The value key is apoc.convert.toJson (list-safe — plain toString throws on
    # list/array properties); ties break on that JSON key ASC for determinism.
    # Note: this does not perfectly match NetworkX's str(value) tie-break for
    # string/array properties — parity at the truncation boundary is E46.3's concern.
    assert "apoc.convert.toJson(n.`born`)" in cypher
    assert "ORDER BY value_count DESC, value ASC" in cypher
    # top_n is a driver value parameter (never interpolated into the string).
    assert params == {"top_n": 10}
    assert "10" not in cypher


def test_apoc_node_value_histogram_materialize() -> None:
    q = ApocNodeValueHistogramQuery(
        identifiers={"label": "Person", "property_name": "born"}
    )
    row = q.materialize({"value": "1980", "value_count": 42})
    assert isinstance(row, ValueHistogramRow)
    assert row.value == "1980"
    assert row.value_count == 42


def test_apoc_node_value_histogram_materialize_coerces_value_to_str() -> None:
    q = ApocNodeValueHistogramQuery(
        identifiers={"label": "Person", "property_name": "born"}
    )
    # The histogram key currency is str(value) (parity with NetworkX).
    row = q.materialize({"value": 1980, "value_count": 42})
    assert row.value == "1980"


def test_apoc_node_value_histogram_unwraps_json_string() -> None:
    """A JSON-encoded string key from apoc.convert.toJson is unwrapped.

    apoc.convert.toJson('A Few Good Men') yields the quoted string
    '"A Few Good Men"'; the materialiser strips the JSON quotes so the histogram
    key reads naturally and matches NetworkX's str(value).
    """
    q = ApocNodeValueHistogramQuery(
        identifiers={"label": "Movie", "property_name": "title"}
    )
    row = q.materialize({"value": '"A Few Good Men"', "value_count": 1})
    assert row.value == "A Few Good Men"


def test_apoc_rel_value_histogram_keeps_json_array_verbatim() -> None:
    """A JSON array key (list-valued property) is kept as its JSON form."""
    q = ApocRelValueHistogramQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "ACTED_IN",
            "target_label": "Movie",
            "property_name": "roles",
        }
    )
    row = q.materialize({"value": '["Neo"]', "value_count": 3})
    assert row.value == '["Neo"]'


def test_apoc_node_value_histogram_injected_label_raises() -> None:
    q = ApocNodeValueHistogramQuery(
        identifiers={"label": "1Bad", "property_name": "born"}
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(q.params_schema(top_n=10))


def test_apoc_rel_value_histogram_build_limits_by_param() -> None:
    q = ApocRelValueHistogramQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "ACTED_IN",
            "target_label": "Movie",
            "property_name": "role",
        }
    )
    cypher, params = q.build(q.params_schema(top_n=5))
    assert "`ACTED_IN`" in cypher
    assert "`role`" in cypher
    assert "LIMIT $top_n" in cypher
    assert params == {"top_n": 5}


def test_apoc_rel_value_histogram_materialize() -> None:
    q = ApocRelValueHistogramQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "ACTED_IN",
            "target_label": "Movie",
            "property_name": "role",
        }
    )
    row = q.materialize({"value": "Neo", "value_count": 3})
    assert row.value == "Neo"
    assert row.value_count == 3


# ---------------------------------------------------------------------------
# Value-scan: pure-Cypher scalar histogram fallback
# No APOC: group on toStringOrNull(v) (list-safe — lists become null and are
# dropped), so scalar-typed properties still get a histogram; lists/maps are
# skipped rather than crashing (plain toString(list) throws).  No type counts.
# ---------------------------------------------------------------------------


def test_cypher_node_value_histogram_uses_to_string_or_null() -> None:
    q = CypherNodeValueHistogramQuery(
        identifiers={"label": "Person", "property_name": "born"}
    )
    cypher, params = q.build(q.params_schema(top_n=10))
    assert "`Person`" in cypher
    assert "`born`" in cypher
    # The scalar-safe value key: toStringOrNull returns null for list/map values,
    # which the WHERE then drops (never reaching a crashing toString(list)).
    assert "toStringOrNull(n.`born`)" in cypher
    # Lists are dropped, not crashed.
    assert "value IS NOT NULL" in cypher
    # The only truncating part — a parameterised LIMIT (never interpolated).
    assert "LIMIT $top_n" in cypher
    assert "ORDER BY value_count DESC, value ASC" in cypher
    assert params == {"top_n": 10}
    assert "10" not in cypher
    # No APOC functions on the pure-Cypher fallback.
    assert "apoc." not in cypher


def test_cypher_node_value_histogram_materialize() -> None:
    q = CypherNodeValueHistogramQuery(
        identifiers={"label": "Person", "property_name": "born"}
    )
    row = q.materialize({"value": "1980", "value_count": 42})
    assert isinstance(row, ValueHistogramRow)
    assert row.value == "1980"
    assert row.value_count == 42


def test_cypher_node_value_histogram_injected_label_raises() -> None:
    q = CypherNodeValueHistogramQuery(
        identifiers={"label": "1Bad", "property_name": "born"}
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(q.params_schema(top_n=10))


def test_cypher_rel_value_histogram_uses_to_string_or_null() -> None:
    q = CypherRelValueHistogramQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "ACTED_IN",
            "target_label": "Movie",
            "property_name": "role",
        }
    )
    cypher, params = q.build(q.params_schema(top_n=5))
    assert "`ACTED_IN`" in cypher
    assert "`role`" in cypher
    assert "toStringOrNull(r.`role`)" in cypher
    assert "value IS NOT NULL" in cypher
    assert "LIMIT $top_n" in cypher
    assert params == {"top_n": 5}
    assert "apoc." not in cypher


def test_cypher_rel_value_histogram_materialize() -> None:
    q = CypherRelValueHistogramQuery(
        identifiers={
            "source_label": "Person",
            "rel_type": "ACTED_IN",
            "target_label": "Movie",
            "property_name": "role",
        }
    )
    row = q.materialize({"value": "Neo", "value_count": 3})
    assert row.value == "Neo"
    assert row.value_count == 3


# ---------------------------------------------------------------------------
# Catalogue factories
# ---------------------------------------------------------------------------


def test_apoc_catalogue_registered_names() -> None:
    query_catalogue = build_apoc_catalogue()
    names = query_catalogue.names()
    assert "neo4j.inspect.node_labels" in names
    assert "neo4j.inspect.rel_types" in names
    # Authoritative instance-count queries (property-independent).
    assert "neo4j.inspect.node_count" in names
    assert "neo4j.inspect.rel_count" in names
    assert "neo4j.inspect.apoc.node_properties" in names
    # ADR-037 §6a: bulk rel-type-map source (was per-rel-type apoc.rel_properties).
    assert "neo4j.inspect.apoc.rel_types" in names
    # Per-shape rel-property counts via endpoint-filtered pattern scan.
    assert "neo4j.inspect.cypher.rel_properties" in names
    assert "inspect.cardinality" in names
    assert "neo4j.inspect.constraints" in names
    assert "inspect.endpoint_labels" in names
    assert "inspect.partitioned_cardinality.source" in names
    assert "inspect.partitioned_cardinality.target" in names
    # E46.1/E46.2 value scan: APOC type counts + APOC histograms (node + rel).
    assert "neo4j.inspect.apoc.node_type_counts" in names
    assert "neo4j.inspect.apoc.rel_type_counts" in names
    assert "neo4j.inspect.apoc.node_value_histogram" in names
    assert "neo4j.inspect.apoc.rel_value_histogram" in names
    # ADR-036: property-independent present-count queries (APOC count correction).
    assert "neo4j.inspect.node_present_count" in names
    assert "neo4j.inspect.rel_present_count" in names
    assert len(names) == 18


def test_cypher_catalogue_registered_names() -> None:
    query_catalogue = build_cypher_catalogue()
    names = query_catalogue.names()
    assert "neo4j.inspect.node_count" in names
    assert "neo4j.inspect.rel_count" in names
    assert "neo4j.inspect.cypher.node_properties" in names
    assert "neo4j.inspect.cypher.rel_properties" in names
    assert "inspect.endpoint_labels" in names
    assert "inspect.partitioned_cardinality.source" in names
    assert "inspect.partitioned_cardinality.target" in names
    # APOC-keyed value-scan queries are NOT
    # registered on pure-Cypher.  Type counts need apoc.meta.cypher.type and the
    # APOC histogram needs apoc.convert.toJson (keeps lists in the histogram).
    assert "neo4j.inspect.apoc.node_type_counts" not in names
    assert "neo4j.inspect.apoc.rel_type_counts" not in names
    assert "neo4j.inspect.apoc.node_value_histogram" not in names
    assert "neo4j.inspect.apoc.rel_value_histogram" not in names
    # a scalar-only pure-Cypher histogram fallback IS registered
    # (toStringOrNull drops lists, so scalar properties still get a histogram).
    # Type counts remain unavailable on pure-Cypher (no runtime-type function).
    assert "neo4j.inspect.cypher.node_value_histogram" in names
    assert "neo4j.inspect.cypher.rel_value_histogram" in names
    # ADR-036: present-count queries registered in every catalogue for parity
    # (used by the inspector only on the APOC strategy).
    assert "neo4j.inspect.node_present_count" in names
    assert "neo4j.inspect.rel_present_count" in names
    assert len(names) == 15


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
    assert "neo4j.inspect.node_count" in names
    assert "neo4j.inspect.rel_count" in names
    assert "inspect.cardinality" in names
    assert "neo4j.inspect.constraints" in names
    assert "inspect.endpoint_labels" in names
    assert "inspect.partitioned_cardinality.source" in names
    assert "inspect.partitioned_cardinality.target" in names
    # SCHEMA may use the APOC type function when APOC is present;
    # the inspector gates at runtime.  Histograms are value-only.
    assert "neo4j.inspect.apoc.node_type_counts" in names
    assert "neo4j.inspect.apoc.rel_type_counts" in names
    assert "neo4j.inspect.apoc.node_value_histogram" in names
    assert "neo4j.inspect.apoc.rel_value_histogram" in names
    # the scalar-only pure-Cypher histogram fallback is also registered so
    # a SCHEMA-without-APOC deployment still gets a histogram (the inspector picks
    # this path when the runtime APOC probe is negative).
    assert "neo4j.inspect.cypher.node_value_histogram" in names
    assert "neo4j.inspect.cypher.rel_value_histogram" in names
    # ADR-036: present-count queries registered for parity.
    assert "neo4j.inspect.node_present_count" in names
    assert "neo4j.inspect.rel_present_count" in names
    assert len(names) == 21


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
                    f"{desc.query_id} has no output_schema"
                )
