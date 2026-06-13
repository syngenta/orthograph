"""Neo4j-specific typed Cypher read queries and catalogue factories.

Covers ``db.labels()``, ``db.relationshipTypes()``, ``SHOW CONSTRAINTS``,
APOC ``apoc.meta.*`` property queries, and their pure-Cypher fallbacks.
Two catalogues are provided: APOC-strategy and pure-Cypher.
"""

import warnings as _warnings
from typing import Any

from pydantic import BaseModel, Field

from orthograph.cypher.base_models import CypherReadQuery
from orthograph.cypher.bindings import (
    CypherQuery,
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
    introspect stored value types without APOC).
    """

    property_name: str = Field(alias="propertyName")
    property_types: list[str] = Field(default_factory=list, alias="propertyTypes")
    mandatory: bool
    property_observations: int = Field(0, alias="propertyObservations")
    total_observations: int = Field(0, alias="totalObservations")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Neo4j label / rel-type discovery queries
# ---------------------------------------------------------------------------


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

        def build(self, params: NoParams) -> CypherQuery:
            return self._CYPHER, {}

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

        def build(self, params: NoParams) -> CypherQuery:
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
            return cypher, {}

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

        def build(self, params: NoParams) -> CypherQuery:
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
            return cypher, {}

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
