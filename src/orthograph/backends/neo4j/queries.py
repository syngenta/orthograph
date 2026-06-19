"""Neo4j-specific typed Cypher read queries and catalogue factories.

Covers ``db.labels()``, ``db.relationshipTypes()``, ``SHOW CONSTRAINTS``,
APOC ``apoc.meta.*`` property queries, their pure-Cypher fallbacks, and the
built-in ``db.schema.*`` type queries.  Three catalogues are provided:
APOC-strategy, pure-Cypher, and SCHEMA (scan-counts + ``db.schema.*`` types).

``db.schema.*`` column shape (confirmed on Neo4j 5.12.0; available since 4.x):
  nodeTypeProperties: nodeType (str, e.g. ``:'`Label`'``), nodeLabels (list[str]),
    propertyName (str | None), propertyTypes (list[str] | None), mandatory (bool)
  relTypeProperties:  relType  (str, e.g. ``:'`REL_TYPE`'``),
    propertyName (str | None), propertyTypes (list[str] | None), mandatory (bool)
  Rows where a rel/node type has no properties yield ``propertyName=None`` and
  ``propertyTypes=None``; materialisers must guard both with ``.get()`` / ``or []``.
  No count columns exist (``propertyObservations``/``totalObservations`` are APOC-only).
"""

import warnings as _warnings
from typing import Any

from pydantic import BaseModel, Field

from orthograph.cypher.base_models import CypherReadQuery
from orthograph.cypher.bindings import (
    CypherQueryData,
    NoIdentifiers,
    NoParams,
    render_with_identifiers,
)
from orthograph.graph_profile.models import (
    ConstraintInfo,
    NodeLabelIdentifiers,
    RelTypeIdentifiers,
)
from orthograph.graph_profile.queries.shared import (
    InspectCardinalityQuery,
    InspectEndpointLabelsQuery,
    coerce_types,
)
from orthograph.query.catalogue import QueryCatalogue


# ---------------------------------------------------------------------------
# Neo4j-specific output / projection models
# ---------------------------------------------------------------------------


class NodeLabelRow(BaseModel):
    """A single node-label row from ``db.labels()``."""

    label: str


class RelTypeLabelRow(BaseModel):
    """A single relationship-type row from ``db.relationshipTypes()``."""

    relationship_type: str = Field(alias="relationshipType")

    model_config = {"populate_by_name": True}


class NodePropertyRow(BaseModel):
    """Per-property row returned by both APOC and pure-Cypher property queries.

    ``property_types`` is ``[]`` in the pure-Cypher fallback (the driver cannot
    introspect stored value types without APOC).  ``property_name`` is ``None``
    when APOC returns a row for a label/rel-type that has no properties at all
    (APOC emits one null-property sentinel row per empty type); callers must
    skip rows where ``property_name is None``.
    """

    property_name: str | None = Field(None, alias="propertyName")
    property_types: list[str] = Field(default_factory=list, alias="propertyTypes")
    mandatory: bool
    property_observations: int = Field(0, alias="propertyObservations")
    total_observations: int = Field(0, alias="totalObservations")

    model_config = {"populate_by_name": True}


class DbSchemaNodeTypeRow(BaseModel):
    """Per-property type row from ``db.schema.nodeTypeProperties()``.

    Carries types only — ``db.schema.*`` reports no observation counts.  The
    ``:`Label``` prefix on ``nodeType`` is stripped in ``materialize()`` so the
    inspector merge joins on a clean label.  ``property_name`` is ``None`` for a
    node type that has no properties.
    """

    label: str
    property_name: str | None = None
    observed_types: list[str] = Field(default_factory=list)


class DbSchemaRelTypeRow(BaseModel):
    """Per-property type row from ``db.schema.relTypeProperties()``.

    Carries types only.  The ``:`REL_TYPE``` prefix on ``relType`` is stripped
    in ``materialize()``.  ``property_name`` is ``None`` for a relationship type
    that has no properties.
    """

    rel_type: str
    property_name: str | None = None
    observed_types: list[str] = Field(default_factory=list)


class InspectNodeLabelsQuery(CypherReadQuery[NoParams, NodeLabelRow]):
    """Return all node labels present in the database."""

    Params = NoParams
    Output = NodeLabelRow
    name = "neo4j.inspect.node_labels"
    cypher_template = "CALL db.labels() YIELD label RETURN label"

    def materialize(self, raw: Any) -> NodeLabelRow:
        return NodeLabelRow(label=raw["label"])


class InspectRelTypesQuery(CypherReadQuery[NoParams, RelTypeLabelRow]):
    """Return all relationship types present in the database."""

    Params = NoParams
    Output = RelTypeLabelRow
    name = "neo4j.inspect.rel_types"
    cypher_template = (
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
    )

    def materialize(self, raw: Any) -> RelTypeLabelRow:
        return RelTypeLabelRow(relationship_type=raw["relationshipType"])


# InspectNeo4jConstraintsQuery uses imperative build() because
# ``SHOW CONSTRAINTS`` is a Neo4j admin command that the graphglot dialect
# parser does not recognise as standard Cypher.
with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", UserWarning)

    class InspectNeo4jConstraintsQuery(CypherReadQuery[NoParams, ConstraintInfo]):
        """Return all constraints via ``SHOW CONSTRAINTS``.

        Uses imperative ``build()`` because the command is not standard Cypher.
        """

        Params = NoParams
        Output = ConstraintInfo
        name = "neo4j.inspect.constraints"
        _CYPHER = (
            "SHOW CONSTRAINTS YIELD name, type, entityType,"
            " labelsOrTypes, properties, propertyType"
        )

        def build(self, params: NoParams) -> CypherQueryData:
            return CypherQueryData(self._CYPHER, {})

        def materialize(self, raw: Any) -> ConstraintInfo:
            return ConstraintInfo(
                name=raw.get("name"),
                constraint_type=raw["type"],
                entity_type=raw["entityType"],
                labels=raw.get("labelsOrTypes", []),
                properties=raw.get("properties", []),
                property_type=raw.get("propertyType"),
            )


# ---------------------------------------------------------------------------
# APOC-specific queries
# (imperative build() used because CALL apoc.meta.* ... WHERE is not
# valid standard Cypher and the graphglot parser rejects it)
# ---------------------------------------------------------------------------


with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", UserWarning)

    class ApocNodePropertiesQuery(CypherReadQuery[NoParams, NodePropertyRow]):
        """Node property metadata via ``apoc.meta.nodeTypeProperties``.

        Uses imperative ``build()`` because ``CALL apoc.meta.* ... WHERE`` is
        not standard Cypher.
        """

        Params = NoParams
        Output = NodePropertyRow
        name = "neo4j.inspect.apoc.node_properties"
        Identifiers = NodeLabelIdentifiers

        def build(self, params: NoParams) -> CypherQueryData:
            label = render_with_identifiers(
                "<<label>>",
                self._identifiers,  # validates identifier
            )
            cypher = (
                "CALL apoc.meta.nodeTypeProperties({sample: -1})"
                " YIELD nodeType, nodeLabels, propertyName, propertyTypes,"
                " mandatory, propertyObservations, totalObservations"
                f" WHERE '{label}' IN nodeLabels"
                " RETURN propertyName, propertyTypes, mandatory,"
                " propertyObservations, totalObservations"
            )
            return CypherQueryData(cypher, {})

        def materialize(self, raw: Any) -> NodePropertyRow:
            types = raw.get("propertyTypes", [])
            return NodePropertyRow(
                property_name=raw["propertyName"],
                property_types=coerce_types(types),
                mandatory=raw.get("mandatory", False),
                property_observations=raw.get("propertyObservations", 0),
                total_observations=raw.get("totalObservations", 0),
            )

    class ApocRelPropertiesQuery(CypherReadQuery[NoParams, NodePropertyRow]):
        """Relationship property metadata via ``apoc.meta.relTypeProperties``.

        Uses imperative ``build()`` because ``CALL apoc.meta.* ... WHERE`` is
        not standard Cypher.
        """

        Params = NoParams
        Output = NodePropertyRow
        name = "neo4j.inspect.apoc.rel_properties"
        Identifiers = RelTypeIdentifiers

        def build(self, params: NoParams) -> CypherQueryData:
            rel_type = render_with_identifiers(
                "<<rel_type>>",
                self._identifiers,  # validates identifier
            )
            cypher = (
                "CALL apoc.meta.relTypeProperties({sample: -1})"
                " YIELD relType, propertyName, propertyTypes,"
                " mandatory, propertyObservations, totalObservations"
                f" WHERE relType = ':`{rel_type}`'"
                " RETURN propertyName, propertyTypes, mandatory,"
                " propertyObservations, totalObservations"
            )
            return CypherQueryData(cypher, {})

        def materialize(self, raw: Any) -> NodePropertyRow:
            types = raw.get("propertyTypes", [])
            return NodePropertyRow(
                property_name=raw["propertyName"],
                property_types=coerce_types(types),
                mandatory=raw.get("mandatory", False),
                property_observations=raw.get("propertyObservations", 0),
                total_observations=raw.get("totalObservations", 0),
            )


# ---------------------------------------------------------------------------
# Pure-Cypher fallback queries
# ---------------------------------------------------------------------------


class CypherNodePropertiesQuery(CypherReadQuery[NoParams, NodePropertyRow]):
    """Node property metadata via a two-pass MATCH/UNWIND scan (no APOC).

    ``propertyTypes`` is always ``[]``.  ``totalObservations`` is the node count.
    """

    Params = NoParams
    Output = NodePropertyRow
    name = "neo4j.inspect.cypher.node_properties"
    Identifiers = NodeLabelIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " WITH count(n) AS total"
        " MATCH (n:`<<label>>`)"
        " UNWIND keys(n) AS key"
        " WITH key, count(*) AS present, total"
        " RETURN key AS propertyName, [] AS propertyTypes,"
        " present = total AS mandatory,"
        " present AS propertyObservations, total AS totalObservations"
    )

    def materialize(self, raw: Any) -> NodePropertyRow:
        return NodePropertyRow(
            property_name=raw["propertyName"],
            property_types=[],
            mandatory=raw.get("mandatory", False),
            property_observations=raw.get("propertyObservations", 0),
            total_observations=raw.get("totalObservations", 0),
        )


class CypherRelPropertiesQuery(CypherReadQuery[NoParams, NodePropertyRow]):
    """Relationship property metadata via MATCH/UNWIND scan (no APOC)."""

    Params = NoParams
    Output = NodePropertyRow
    name = "neo4j.inspect.cypher.rel_properties"
    Identifiers = RelTypeIdentifiers
    cypher_template = (
        "MATCH ()-[r:`<<rel_type>>`]->()"
        " WITH count(r) AS total"
        " MATCH ()-[r:`<<rel_type>>`]->()"
        " UNWIND keys(r) AS key"
        " WITH key, count(*) AS present, total"
        " RETURN key AS propertyName, [] AS propertyTypes,"
        " present = total AS mandatory,"
        " present AS propertyObservations, total AS totalObservations"
    )

    def materialize(self, raw: Any) -> NodePropertyRow:
        return NodePropertyRow(
            property_name=raw["propertyName"],
            property_types=[],
            mandatory=raw.get("mandatory", False),
            property_observations=raw.get("propertyObservations", 0),
            total_observations=raw.get("totalObservations", 0),
        )


# ---------------------------------------------------------------------------
# db.schema.* type queries (built-in; available since Neo4j 4.x)
# Bulk CALL with no interpolated identifiers (no new injection surface).
# Imperative build() because CALL db.schema.* is not standard Cypher and the
# graphglot parser rejects it.  Yields types only — no count columns exist;
# true counts come from the pure-Cypher scan in the SCHEMA strategy.
# ---------------------------------------------------------------------------


with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", UserWarning)

    class DbSchemaNodeTypesQuery(CypherReadQuery[NoParams, DbSchemaNodeTypeRow]):
        """Bulk node-property types via ``db.schema.nodeTypeProperties()``."""

        Params = NoParams
        Output = DbSchemaNodeTypeRow
        name = "neo4j.inspect.schema.node_types"
        Identifiers = NoIdentifiers
        _CYPHER = (
            "CALL db.schema.nodeTypeProperties()"
            " YIELD nodeType, nodeLabels, propertyName, propertyTypes, mandatory"
        )

        def build(self, params: NoParams) -> CypherQueryData:
            return CypherQueryData(self._CYPHER, {})

        def materialize(self, raw: Any) -> DbSchemaNodeTypeRow:
            return DbSchemaNodeTypeRow(
                label=raw["nodeType"].strip(":` "),
                property_name=raw.get("propertyName"),
                observed_types=coerce_types(raw.get("propertyTypes")),
            )

    class DbSchemaRelTypesQuery(CypherReadQuery[NoParams, DbSchemaRelTypeRow]):
        """Bulk relationship-property types via ``db.schema.relTypeProperties()``."""

        Params = NoParams
        Output = DbSchemaRelTypeRow
        name = "neo4j.inspect.schema.rel_types"
        Identifiers = NoIdentifiers
        _CYPHER = (
            "CALL db.schema.relTypeProperties()"
            " YIELD relType, propertyName, propertyTypes, mandatory"
        )

        def build(self, params: NoParams) -> CypherQueryData:
            return CypherQueryData(self._CYPHER, {})

        def materialize(self, raw: Any) -> DbSchemaRelTypeRow:
            return DbSchemaRelTypeRow(
                rel_type=raw["relType"].strip(":` "),
                property_name=raw.get("propertyName"),
                observed_types=coerce_types(raw.get("propertyTypes")),
            )


# ---------------------------------------------------------------------------
# Catalogue factories — each registers the shared neutral queries alongside
# the neo4j-specific ones.  The catalogue is the assembly point.
# ---------------------------------------------------------------------------


def build_apoc_catalogue() -> QueryCatalogue:
    """Return an internal QueryCatalogue populated with APOC-strategy queries."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(InspectNodeLabelsQuery())
    query_catalogue.register_read(InspectRelTypesQuery())
    query_catalogue.register_read(ApocNodePropertiesQuery(identifiers={"label": "_"}))
    query_catalogue.register_read(ApocRelPropertiesQuery(identifiers={"rel_type": "_"}))
    query_catalogue.register_read(
        InspectCardinalityQuery(identifiers={"label": "_", "rel_type": "_"})
    )
    query_catalogue.register_read(InspectNeo4jConstraintsQuery())
    query_catalogue.register_read(
        InspectEndpointLabelsQuery(identifiers={"rel_type": "_"})
    )
    return query_catalogue


def build_cypher_catalogue() -> QueryCatalogue:
    """Return an internal QueryCatalogue populated with pure-Cypher queries."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(InspectNodeLabelsQuery())
    query_catalogue.register_read(InspectRelTypesQuery())
    query_catalogue.register_read(CypherNodePropertiesQuery(identifiers={"label": "_"}))
    query_catalogue.register_read(
        CypherRelPropertiesQuery(identifiers={"rel_type": "_"})
    )
    query_catalogue.register_read(
        InspectCardinalityQuery(identifiers={"label": "_", "rel_type": "_"})
    )
    query_catalogue.register_read(InspectNeo4jConstraintsQuery())
    query_catalogue.register_read(
        InspectEndpointLabelsQuery(identifiers={"rel_type": "_"})
    )
    return query_catalogue


def build_schema_catalogue() -> QueryCatalogue:
    """Return a QueryCatalogue for the SCHEMA strategy.

    Combines the pure-Cypher property scan (for true completeness counts) with
    the ``db.schema.*`` type queries (for ``observed_types``).  The inspector
    merges the two halves per ``(label/rel_type, property_name)``.
    """
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(InspectNodeLabelsQuery())
    query_catalogue.register_read(InspectRelTypesQuery())
    query_catalogue.register_read(CypherNodePropertiesQuery(identifiers={"label": "_"}))
    query_catalogue.register_read(
        CypherRelPropertiesQuery(identifiers={"rel_type": "_"})
    )
    query_catalogue.register_read(DbSchemaNodeTypesQuery())
    query_catalogue.register_read(DbSchemaRelTypesQuery())
    query_catalogue.register_read(
        InspectCardinalityQuery(identifiers={"label": "_", "rel_type": "_"})
    )
    query_catalogue.register_read(InspectNeo4jConstraintsQuery())
    query_catalogue.register_read(
        InspectEndpointLabelsQuery(identifiers={"rel_type": "_"})
    )
    return query_catalogue
