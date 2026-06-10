"""Typed Cypher read queries for Neo4j schema introspection.

Each class is a ``CypherReadQuery`` subclass whose ``build()`` returns a
validated, identifier-safe Cypher string plus an (always empty) params dict.
Dynamic identifiers (node labels, relationship types) are carried through the
``Identifiers``/``<<placeholder>>`` mechanism from ADR-010 so that
``validate_identifier`` gates every per-call value before it reaches the
driver.

Two query sets are provided:
  * **APOC** — uses ``apoc.meta`` procedures for richer metadata (observation
    counts, type lists).  Selected when ``apoc.meta.*`` procedures are present.
  * **Pure Cypher** — fallback when APOC is unavailable.  Produces the same
    ``NodePropertyRow`` shape but with ``propertyTypes = []`` and
    ``totalObservations`` derived from a two-pass MATCH/count scan.

Four queries are shared between the two sets (same Cypher text):
  * ``InspectNodeLabelsQuery``
  * ``InspectRelTypesQuery``
  * ``InspectCardinalityQuery``
  * ``InspectNeo4jConstraintsQuery``

Two queries differ between sets:
  * ``ApocNodePropertiesQuery``  vs  ``CypherNodePropertiesQuery``
  * ``ApocRelPropertiesQuery``   vs  ``CypherRelPropertiesQuery``

One query is new (E18.1 endpoint-labels fix):
  * ``InspectEndpointLabelsQuery`` — shared with Memgraph (identical Cypher).

``QueryStrategy``, ``ApocQueryStrategy``, and ``CypherQueryStrategy`` have been
retired (ADR-009 T7 decision: Option A — direct typed subclasses).  The
APOC / pure-Cypher split is now expressed as two catalogues (or two named query
sets) selected at inspector construction time.
"""

import warnings as _warnings
from typing import Any

from pydantic import BaseModel, Field

from orthograph.extensions.cypher.base_models import CypherReadQuery
from orthograph.extensions.cypher.bindings import (
    CypherQuery,
    NoParams,
    render_with_identifiers,
)


# ---------------------------------------------------------------------------
# Shared identifier models
# ---------------------------------------------------------------------------


class NodeLabelIdentifiers(BaseModel):
    """Identifier group for queries that filter by a single node label."""

    label: str


class RelTypeIdentifiers(BaseModel):
    """Identifier group for queries that filter by a single relationship type."""

    rel_type: str  # name ends in _rel_type → kind = "relationship type"


class CardinalityIdentifiers(BaseModel):
    """Identifier group for the cardinality query (label + rel_type)."""

    label: str
    rel_type: str  # kind = "relationship type"


# ---------------------------------------------------------------------------
# Shared output / projection models
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

    ``property_types`` is ``[]`` in the pure-Cypher fallback (the driver
    cannot introspect stored value types without APOC).
    """

    property_name: str = Field(alias="propertyName")
    property_types: list[str] = Field(default_factory=list, alias="propertyTypes")
    mandatory: bool
    property_observations: int = Field(0, alias="propertyObservations")
    total_observations: int = Field(0, alias="totalObservations")

    model_config = {"populate_by_name": True}


class EndpointLabelsRow(BaseModel):
    """Source and target label lists for a single relationship instance."""

    source_labels: list[str]
    target_labels: list[str]


def _coerce_types(raw_types: Any) -> list[str]:
    """Normalise a propertyTypes value to a list of strings."""
    if isinstance(raw_types, list):
        return raw_types
    return [raw_types] if raw_types else []


# ConstraintInfo is used directly as Output for the constraints query;
# no intermediate projection needed.
from orthograph.extensions.models import CardinalityStats, ConstraintInfo  # noqa: E402


# ---------------------------------------------------------------------------
# Shared queries (same Cypher for APOC and pure-Cypher paths)
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


class InspectCardinalityQuery(CypherReadQuery[NoParams, CardinalityStats]):
    """Cardinality statistics for one (label, rel_type) pair.

    Shared between APOC, pure-Cypher, and Memgraph — the Cypher is identical
    across all three backends.
    """

    Params = NoParams
    Output = CardinalityStats
    name = "neo4j.inspect.cardinality"
    Identifiers = CardinalityIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->()"
        " WITH n, count(r) AS degree"
        " RETURN min(degree) AS min_degree, max(degree) AS max_degree,"
        " avg(degree) AS avg_degree, count(n) AS sample_size"
    )

    def materialize(self, raw: Any) -> CardinalityStats:
        return CardinalityStats(
            min_degree=raw["min_degree"],
            max_degree=raw["max_degree"],
            avg_degree=float(raw["avg_degree"]),
            sample_size=raw["sample_size"],
        )


# InspectNeo4jConstraintsQuery uses imperative build() because
# ``SHOW CONSTRAINTS`` is a Neo4j admin command that the graphglot dialect
# parser does not recognise as standard Cypher.  Imperative style is the
# documented escape hatch for query shapes the parser cannot validate.
with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", UserWarning)

    class InspectNeo4jConstraintsQuery(CypherReadQuery[NoParams, ConstraintInfo]):
        """Return all constraints from Neo4j (``SHOW CONSTRAINTS``).

        Uses imperative ``build()`` because ``SHOW CONSTRAINTS`` is a Neo4j
        admin command not recognised by the graphglot dialect parser.
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


class InspectEndpointLabelsQuery(CypherReadQuery[NoParams, EndpointLabelsRow]):
    """Collect the distinct source and target label lists for a relationship type.

    Returns one row per relationship instance; the inspector unions the label
    sets across all rows to populate ``RelationshipTypeProfile.source_labels``
    and ``.target_labels``.

    Shared between Neo4j and Memgraph — the Cypher text is identical.
    """

    Params = NoParams
    Output = EndpointLabelsRow
    name = "neo4j.inspect.endpoint_labels"
    Identifiers = RelTypeIdentifiers
    cypher_template = (
        "MATCH (src)-[r:`<<rel_type>>`]->(tgt)"
        " RETURN DISTINCT labels(src) AS source_labels, labels(tgt) AS target_labels"
    )

    def materialize(self, raw: Any) -> EndpointLabelsRow:
        return EndpointLabelsRow(
            source_labels=list(raw["source_labels"]),
            target_labels=list(raw["target_labels"]),
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

        The label is validated via ``validate_identifier`` before being embedded
        inside the APOC WHERE clause as a string-literal filter
        (``WHERE '<label>' IN nodeLabels``).

        Uses imperative ``build()`` because ``CALL apoc.meta.* ... WHERE``
        is not valid standard Cypher and the graphglot parser rejects it.
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
                property_types=_coerce_types(types),
                mandatory=raw.get("mandatory", False),
                property_observations=raw.get("propertyObservations", 0),
                total_observations=raw.get("totalObservations", 0),
            )

    class ApocRelPropertiesQuery(CypherReadQuery[NoParams, NodePropertyRow]):
        """Relationship property metadata via ``apoc.meta.relTypeProperties``.

        Uses imperative ``build()`` because ``CALL apoc.meta.* ... WHERE``
        is not valid standard Cypher and the graphglot parser rejects it.
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
                property_types=_coerce_types(types),
                mandatory=raw.get("mandatory", False),
                property_observations=raw.get("propertyObservations", 0),
                total_observations=raw.get("totalObservations", 0),
            )


# ---------------------------------------------------------------------------
# Pure-Cypher fallback queries
# ---------------------------------------------------------------------------


class CypherNodePropertiesQuery(CypherReadQuery[NoParams, NodePropertyRow]):
    """Node property metadata via a two-pass MATCH/UNWIND scan (no APOC).

    ``propertyTypes`` is always ``[]`` — the pure-Cypher path cannot introspect
    stored value types without APOC.  ``totalObservations`` is the node count.
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
# Catalogue factories
# ---------------------------------------------------------------------------

from orthograph.catalogue.registry import QueryCatalogue  # noqa: E402


def build_apoc_catalogue() -> QueryCatalogue:
    """Return an internal QueryCatalogue populated with APOC-strategy queries."""
    cat = QueryCatalogue()
    cat.register_read(InspectNodeLabelsQuery())
    cat.register_read(InspectRelTypesQuery())
    cat.register_read(ApocNodePropertiesQuery(identifiers={"label": "_"}))
    cat.register_read(ApocRelPropertiesQuery(identifiers={"rel_type": "_"}))
    cat.register_read(
        InspectCardinalityQuery(identifiers={"label": "_", "rel_type": "_"})
    )
    cat.register_read(InspectNeo4jConstraintsQuery())
    cat.register_read(InspectEndpointLabelsQuery(identifiers={"rel_type": "_"}))
    return cat


def build_cypher_catalogue() -> QueryCatalogue:
    """Return an internal QueryCatalogue populated with pure-Cypher queries."""
    cat = QueryCatalogue()
    cat.register_read(InspectNodeLabelsQuery())
    cat.register_read(InspectRelTypesQuery())
    cat.register_read(CypherNodePropertiesQuery(identifiers={"label": "_"}))
    cat.register_read(CypherRelPropertiesQuery(identifiers={"rel_type": "_"}))
    cat.register_read(
        InspectCardinalityQuery(identifiers={"label": "_", "rel_type": "_"})
    )
    cat.register_read(InspectNeo4jConstraintsQuery())
    cat.register_read(InspectEndpointLabelsQuery(identifiers={"rel_type": "_"}))
    return cat
