"""Memgraph-specific typed Cypher read queries and catalogue factory.

Uses bulk schema procedures (``schema.node_type_properties()``,
``schema.rel_type_properties()``) and ``SHOW CONSTRAINT INFO``.
"""

import warnings as _warnings
from typing import Any

from pydantic import BaseModel, Field

from orthograph.cypher.base_models import TypedCypherReadQueryModel
from orthograph.cypher.bindings import (
    CypherQueryData,
    NoParams,
    render_with_identifiers,
)
from orthograph.graph_profile.queries.shared import (
    InspectCardinalityQuery,
    InspectEndpointLabelsQuery,
    InspectSourcePartitionedCardinalityQuery,
    InspectTargetPartitionedCardinalityQuery,
    coerce_types,
)
from orthograph.query.catalogue import QueryCatalogue


# ---------------------------------------------------------------------------
# Memgraph-specific output / projection models
# ---------------------------------------------------------------------------


class MemgraphNodePropertyRow(BaseModel):
    """Per-property row from ``schema.node_type_properties()``."""

    node_type: str = Field(alias="nodeType")
    node_labels: list[str] = Field(default_factory=list, alias="nodeLabels")
    mandatory: bool = False
    property_name: str | None = Field(None, alias="propertyName")
    property_types: list[str] = Field(default_factory=list, alias="propertyTypes")

    model_config = {"populate_by_name": True}


class MemgraphRelPropertyRow(BaseModel):
    """Per-property row from ``schema.rel_type_properties()``."""

    rel_type: str = Field(alias="relType")
    mandatory: bool = False
    property_name: str | None = Field(None, alias="propertyName")
    property_types: list[str] = Field(default_factory=list, alias="propertyTypes")

    model_config = {"populate_by_name": True}


class MemgraphConstraintRow(BaseModel):
    """A single constraint row from ``SHOW CONSTRAINT INFO``."""

    constraint_type: str = Field(alias="constraint type")
    entity_type: str = Field(alias="entity type")
    label: str | None = None
    properties: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class MemgraphCountRow(BaseModel):
    """A single property-independent instance-count row for a label / rel type."""

    count: int


# ---------------------------------------------------------------------------
# Value-scan currency and parameters
# ---------------------------------------------------------------------------


class MemgraphTopNParams(BaseModel):
    """Value parameter for the bounded value-histogram queries.

    ``top_n`` is the histogram truncation cap (the ``value_counts_top_n`` opt-in).
    It is a driver ``$top_n`` parameter, never interpolated into the Cypher.
    """

    top_n: int


# Maps Memgraph's ``valueType()`` runtime-type vocabulary (upper-case, e.g.
# ``'INTEGER'``, ``'LIST'``) onto the ``observed_types`` vocabulary returned by
# ``schema.node_type_properties()`` (the BI-connector names ``'Int'``,
# ``'String'``, ``'List[Any]'``, …).  ADR-035 §3 requires type counts to reuse
# the ``observed_types`` vocabulary so ``db_type_to_python`` needs no change and
# the invariant ``set(observed_type_counts) ⊆ set(observed_types)`` holds.
# An unrecognised runtime type passes through verbatim (honest, never invented —
# ADR-035 §5), mirroring the Neo4j ``_normalise_apoc_type_name`` policy.
_VALUE_TYPE_NAME_MAP: dict[str, str] = {
    "INTEGER": "Int",
    "FLOAT": "Float",
    "STRING": "String",
    "BOOLEAN": "Boolean",
    "LIST": "List[Any]",
    "MAP": "Map[Any]",
    "DATE": "Date",
    "LOCAL_TIME": "LocalTime",
    "LOCAL_DATE_TIME": "LocalDateTime",
    "ZONED_DATE_TIME": "DateTime",
    "DURATION": "Duration",
    "POINT_2D": "Point",
    "POINT_3D": "Point",
}


def _normalise_value_type_name(raw_type: str) -> str:
    """Map a ``valueType()`` name to the ``observed_types`` vocabulary.

    Unrecognised names pass through unchanged so Memgraph never invents or
    silently drops a type it cannot map (honesty principle).
    """
    return _VALUE_TYPE_NAME_MAP.get(raw_type, raw_type)


class MemgraphTypeCountRow(BaseModel):
    """One ``{runtime-type-name: count}`` row from a type-count aggregation.

    Produced by grouping a property's non-null values by their runtime type
    (``valueType``) and counting each group.  Exact and bounded: one row per
    distinct *type*, never per distinct value .  ``type_name`` is
    normalised to the ``observed_types`` vocabulary.
    """

    type_name: str
    type_count: int


class MemgraphValueHistogramRow(BaseModel):
    """One ``{value: count}`` row from a bounded scalar value histogram.

    The query groups on ``toStringOrNull(value)`` (the list-safe scalar key:
    list / map / non-stringifiable values become ``null`` and are dropped), so
    the histogram covers scalar-typed values only.  The query orders by
    frequency and applies ``LIMIT $top_n``; the remainder (``other_count``) is
    reconciled by the inspector against the authoritative ``present_count``.
    """

    value: str
    value_count: int


# ---------------------------------------------------------------------------
# Memgraph-specific typed query subclasses
# (imperative build() used where graphglot rejects Memgraph-specific syntax)
# ---------------------------------------------------------------------------


with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", UserWarning)

    class MemgraphNodePropertiesQuery(
        TypedCypherReadQueryModel[NoParams, MemgraphNodePropertyRow]
    ):
        """Bulk node-property metadata via ``schema.node_type_properties()``.

        Uses imperative ``build()`` because the procedure is not standard Cypher.
        """

        params_schema = NoParams
        Output = MemgraphNodePropertyRow
        query_id = "memgraph.inspect.node_properties"
        _CYPHER = (
            "CALL schema.node_type_properties()"
            " YIELD nodeType, nodeLabels, mandatory, propertyName, propertyTypes"
        )

        def build(self, params: NoParams) -> CypherQueryData:
            return CypherQueryData(self._CYPHER, {})

        def materialize(self, raw: Any) -> MemgraphNodePropertyRow:
            types = raw.get("propertyTypes", [])
            return MemgraphNodePropertyRow(
                node_type=raw["nodeType"],
                node_labels=raw.get("nodeLabels", []),
                mandatory=raw.get("mandatory", False),
                property_name=raw.get("propertyName"),
                property_types=coerce_types(types),
            )

    class MemgraphRelPropertiesQuery(
        TypedCypherReadQueryModel[NoParams, MemgraphRelPropertyRow]
    ):
        """Bulk relationship-property metadata via ``schema.rel_type_properties()``.

        Uses imperative ``build()`` because the procedure is not standard Cypher.
        """

        params_schema = NoParams
        Output = MemgraphRelPropertyRow
        query_id = "memgraph.inspect.rel_properties"
        _CYPHER = (
            "CALL schema.rel_type_properties()"
            " YIELD relType, mandatory, propertyName, propertyTypes"
        )

        def build(self, params: NoParams) -> CypherQueryData:
            return CypherQueryData(self._CYPHER, {})

        def materialize(self, raw: Any) -> MemgraphRelPropertyRow:
            types = raw.get("propertyTypes", [])
            return MemgraphRelPropertyRow(
                rel_type=raw["relType"],
                mandatory=raw.get("mandatory", False),
                property_name=raw.get("propertyName"),
                property_types=coerce_types(types),
            )

    class MemgraphConstraintsQuery(
        TypedCypherReadQueryModel[NoParams, MemgraphConstraintRow]
    ):
        """Return all constraints via ``SHOW CONSTRAINT INFO``.

        Uses imperative ``build()`` because the command is not standard Cypher.
        """

        params_schema = NoParams
        Output = MemgraphConstraintRow
        query_id = "memgraph.inspect.constraints"
        _CYPHER = "SHOW CONSTRAINT INFO"

        def build(self, params: NoParams) -> CypherQueryData:
            return CypherQueryData(self._CYPHER, {})

        def materialize(self, raw: Any) -> MemgraphConstraintRow:
            return MemgraphConstraintRow(
                constraint_type=raw.get("constraint type", ""),
                entity_type=raw.get("entity type", ""),
                label=raw.get("label"),
                properties=raw.get("properties", []),
            )


class _MemgraphNodeLabelIdentifiers(BaseModel):
    """Identifier group scoping a count query to one node label."""

    label: str


class _MemgraphRelTypeIdentifiers(BaseModel):
    """Identifier group scoping a count query to one relationship *shape*."""

    source_label: str  # kind = "label"
    rel_type: str  # kind = "relationship type"
    target_label: str  # kind = "label"


with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", UserWarning)

    class MemgraphNodeCountQuery(TypedCypherReadQueryModel[NoParams, MemgraphCountRow]):
        """Authoritative instance count for a node label (property-independent).

        ``schema.node_type_properties()`` yields no observation counts, so the
        node/property presence totals cannot be derived from the schema scan.
        A dedicated ``count()`` supplies the truthful entity total, which is the
        only honest denominator for ``PropertyProfile.completeness`` (and the
        ``NodeTypeProfile.count``) — never derive a total from ``present_count``
        (that fabricates ``completeness == 1.0``; "never invent").
        """

        params_schema = NoParams
        Output = MemgraphCountRow
        query_id = "memgraph.inspect.node_count"
        identifiers_schema = _MemgraphNodeLabelIdentifiers

        def build(self, params: NoParams) -> CypherQueryData:
            cypher = render_with_identifiers(
                "MATCH (n:`<<label>>`) RETURN count(n) AS count",
                self._identifiers,
            )
            return CypherQueryData(cypher, {})

        def materialize(self, raw: Any) -> MemgraphCountRow:
            return MemgraphCountRow(count=raw["count"])

    class MemgraphRelCountQuery(TypedCypherReadQueryModel[NoParams, MemgraphCountRow]):
        """Authoritative instance count for a
        relationship type (property-independent)."""

        params_schema = NoParams
        Output = MemgraphCountRow
        query_id = "memgraph.inspect.rel_count"
        identifiers_schema = _MemgraphRelTypeIdentifiers

        def build(self, params: NoParams) -> CypherQueryData:
            cypher = render_with_identifiers(
                "MATCH (:`<<source_label>>`)-[r:`<<rel_type>>`]->(:`<<target_label>>`)"
                " RETURN count(r) AS count",
                self._identifiers,
            )
            return CypherQueryData(cypher, {})

        def materialize(self, raw: Any) -> MemgraphCountRow:
            return MemgraphCountRow(count=raw["count"])


# ---------------------------------------------------------------------------
# Value-scan queries: one bounded scan per property exposes an
# exact {type-name: count} mapping (via valueType, group by type) AND a bounded
# scalar {value: count} histogram (via toStringOrNull, group by value, LIMIT).
# Both functions are built-in (no MAGE), so the value scan is always available
# on Memgraph.  Identifiers (label / rel_type / property_name) are spliced via
# <<placeholder>>; values are never interpolated.  Imperative build()
# because valueType()/toStringOrNull() in a grouping WITH are not parsed by the
# graphglot dialect validator.
# ---------------------------------------------------------------------------


class _MemgraphNodePropertyScanIdentifiers(BaseModel):
    """Identifier group scoping a value scan to one property of one node label."""

    label: str
    property_name: str  # property key (kind = "label" grammar)


class _MemgraphRelPropertyScanIdentifiers(BaseModel):
    """Identifier group scoping a value scan to one property of one rel shape."""

    source_label: str  # kind = "label"
    rel_type: str  # kind = "relationship type"
    target_label: str  # kind = "label"
    property_name: str  # property key (kind = "label" grammar)


with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", UserWarning)

    class MemgraphNodeTypeCountsQuery(
        TypedCypherReadQueryModel[NoParams, MemgraphTypeCountRow]
    ):
        """Exact per-type counts for a node property (group by ``valueType``).

        Groups the property's non-null values by ``valueType(v)`` and counts each
        group, so the result has one row per distinct *type* — bounded and exact
        even on a UID / free-text column.
        """

        params_schema = NoParams
        Output = MemgraphTypeCountRow
        query_id = "memgraph.inspect.node_type_counts"
        identifiers_schema = _MemgraphNodePropertyScanIdentifiers

        def build(self, params: NoParams) -> CypherQueryData:
            cypher = render_with_identifiers(
                "MATCH (n:`<<label>>`)"
                " WHERE n.`<<property_name>>` IS NOT NULL"
                " WITH valueType(n.`<<property_name>>`) AS type_name,"
                " count(*) AS type_count"
                " RETURN type_name, type_count",
                self._identifiers,
            )
            return CypherQueryData(cypher, {})

        def materialize(self, raw: Any) -> MemgraphTypeCountRow:
            return MemgraphTypeCountRow(
                type_name=_normalise_value_type_name(raw["type_name"]),
                type_count=raw["type_count"],
            )

    class MemgraphRelTypeCountsQuery(
        TypedCypherReadQueryModel[NoParams, MemgraphTypeCountRow]
    ):
        """Exact per-type counts for a relationship property (group by type)."""

        params_schema = NoParams
        Output = MemgraphTypeCountRow
        query_id = "memgraph.inspect.rel_type_counts"
        identifiers_schema = _MemgraphRelPropertyScanIdentifiers

        def build(self, params: NoParams) -> CypherQueryData:
            cypher = render_with_identifiers(
                "MATCH (:`<<source_label>>`)-[r:`<<rel_type>>`]->(:`<<target_label>>`)"
                " WHERE r.`<<property_name>>` IS NOT NULL"
                " WITH valueType(r.`<<property_name>>`) AS type_name,"
                " count(*) AS type_count"
                " RETURN type_name, type_count",
                self._identifiers,
            )
            return CypherQueryData(cypher, {})

        def materialize(self, raw: Any) -> MemgraphTypeCountRow:
            return MemgraphTypeCountRow(
                type_name=_normalise_value_type_name(raw["type_name"]),
                type_count=raw["type_count"],
            )

    class MemgraphNodeValueHistogramQuery(
        TypedCypherReadQueryModel[MemgraphTopNParams, MemgraphValueHistogramRow]
    ):
        """Bounded scalar value histogram for a node property.

        Groups on ``toStringOrNull(value)`` — the list-safe scalar key: a list /
        map / non-stringifiable value becomes ``null`` and is dropped (so only
        scalar values are histogrammed), ordered by frequency, ``LIMIT $top_n``.
        The remainder is reconciled into ``other_count`` by the inspector against
        the authoritative type-count total.
        """

        params_schema = MemgraphTopNParams
        Output = MemgraphValueHistogramRow
        query_id = "memgraph.inspect.node_value_histogram"
        identifiers_schema = _MemgraphNodePropertyScanIdentifiers

        def build(self, params: MemgraphTopNParams) -> CypherQueryData:
            cypher = render_with_identifiers(
                "MATCH (n:`<<label>>`)"
                " WITH toStringOrNull(n.`<<property_name>>`) AS value"
                " WHERE value IS NOT NULL"
                " WITH value, count(*) AS value_count"
                " RETURN value, value_count"
                " ORDER BY value_count DESC, value ASC"
                " LIMIT $top_n",
                self._identifiers,
            )
            return CypherQueryData(cypher, {"top_n": params.top_n})

        def materialize(self, raw: Any) -> MemgraphValueHistogramRow:
            return MemgraphValueHistogramRow(
                value=raw["value"],
                value_count=raw["value_count"],
            )

    class MemgraphRelValueHistogramQuery(
        TypedCypherReadQueryModel[MemgraphTopNParams, MemgraphValueHistogramRow]
    ):
        """Bounded scalar value histogram for a relationship property.

        Mirrors :class:`MemgraphNodeValueHistogramQuery` (``toStringOrNull`` key,
        scalars only, ``LIMIT $top_n``) for relationship properties.
        """

        params_schema = MemgraphTopNParams
        Output = MemgraphValueHistogramRow
        query_id = "memgraph.inspect.rel_value_histogram"
        identifiers_schema = _MemgraphRelPropertyScanIdentifiers

        def build(self, params: MemgraphTopNParams) -> CypherQueryData:
            cypher = render_with_identifiers(
                "MATCH (:`<<source_label>>`)-[r:`<<rel_type>>`]->(:`<<target_label>>`)"
                " WITH toStringOrNull(r.`<<property_name>>`) AS value"
                " WHERE value IS NOT NULL"
                " WITH value, count(*) AS value_count"
                " RETURN value, value_count"
                " ORDER BY value_count DESC, value ASC"
                " LIMIT $top_n",
                self._identifiers,
            )
            return CypherQueryData(cypher, {"top_n": params.top_n})

        def materialize(self, raw: Any) -> MemgraphValueHistogramRow:
            return MemgraphValueHistogramRow(
                value=raw["value"],
                value_count=raw["value_count"],
            )


# ---------------------------------------------------------------------------
# Memgraph-scoped names for the shared neutral queries (identical Cypher).
# Registered under memgraph names so ``describe()`` output is clearly scoped.
# ---------------------------------------------------------------------------


class MemgraphCardinalityQuery(InspectCardinalityQuery):
    """Cardinality query under the Memgraph catalogue name."""

    query_id = "memgraph.inspect.cardinality"


class MemgraphEndpointLabelsQuery(InspectEndpointLabelsQuery):
    """Endpoint-labels query under the Memgraph catalogue name."""

    query_id = "memgraph.inspect.endpoint_labels"


# The partitioned-cardinality queries use imperative build() (variable-width
# grouping), so subclassing them re-triggers the base's imperative-style
# UserWarning at class definition; suppress it intentionally (same pattern the
# parent classes use in graph_profile/queries/shared.py).
with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", UserWarning)

    class MemgraphSourcePartitionedCardinalityQuery(
        InspectSourcePartitionedCardinalityQuery
    ):
        """Source-side partitioned cardinality under the Memgraph catalogue name."""

        query_id = "memgraph.inspect.partitioned_cardinality.source"

    class MemgraphTargetPartitionedCardinalityQuery(
        InspectTargetPartitionedCardinalityQuery
    ):
        """Target-side partitioned cardinality under the Memgraph catalogue name."""

        query_id = "memgraph.inspect.partitioned_cardinality.target"


# ---------------------------------------------------------------------------
# Catalogue factory
# ---------------------------------------------------------------------------


_VALUE_SCAN_PLACEHOLDER_NODE = {"label": "_", "property_name": "_"}
_VALUE_SCAN_PLACEHOLDER_REL = {
    "source_label": "_",
    "rel_type": "_",
    "target_label": "_",
    "property_name": "_",
}
_REL_SHAPE_PLACEHOLDER = {"source_label": "_", "rel_type": "_", "target_label": "_"}
_PARTITIONED_PLACEHOLDER = {
    "label": "_",
    "rel_type": "_",
    "endpoint_label": "_",
    "source_discriminators": ["_"],
    "target_discriminators": ["_"],
}


def build_memgraph_catalogue() -> QueryCatalogue:
    """Return an internal QueryCatalogue populated with Memgraph queries."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(MemgraphNodePropertiesQuery())
    query_catalogue.register_read(MemgraphRelPropertiesQuery())
    query_catalogue.register_read(MemgraphConstraintsQuery())
    query_catalogue.register_read(MemgraphNodeCountQuery(identifiers={"label": "_"}))
    query_catalogue.register_read(
        MemgraphRelCountQuery(identifiers=_REL_SHAPE_PLACEHOLDER)
    )
    query_catalogue.register_read(
        MemgraphCardinalityQuery(
            identifiers={"label": "_", "rel_type": "_", "target_label": "_"}
        )
    )
    query_catalogue.register_read(
        MemgraphEndpointLabelsQuery(identifiers={"rel_type": "_"})
    )
    query_catalogue.register_read(
        MemgraphSourcePartitionedCardinalityQuery(identifiers=_PARTITIONED_PLACEHOLDER)
    )
    query_catalogue.register_read(
        MemgraphTargetPartitionedCardinalityQuery(identifiers=_PARTITIONED_PLACEHOLDER)
    )
    # Value scan: type counts (valueType) + scalar histogram
    # (toStringOrNull).  Both functions are built-in, so the scan is always
    # registered; the inspector gates it on value_counts_top_n.
    query_catalogue.register_read(
        MemgraphNodeTypeCountsQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_NODE)
    )
    query_catalogue.register_read(
        MemgraphRelTypeCountsQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_REL)
    )
    query_catalogue.register_read(
        MemgraphNodeValueHistogramQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_NODE)
    )
    query_catalogue.register_read(
        MemgraphRelValueHistogramQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_REL)
    )
    return query_catalogue
