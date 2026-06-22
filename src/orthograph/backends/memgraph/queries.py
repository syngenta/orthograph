"""Memgraph-specific typed Cypher read queries and catalogue factory.

Uses bulk schema procedures (``schema.node_type_properties()``,
``schema.rel_type_properties()``) and ``SHOW CONSTRAINT INFO``.
"""

import warnings as _warnings
from typing import Any

from pydantic import BaseModel, Field

from orthograph.cypher.base_models import CypherReadQuery
from orthograph.cypher.bindings import CypherQueryData, NoParams
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


# ---------------------------------------------------------------------------
# Memgraph-specific typed query subclasses
# (imperative build() used where graphglot rejects Memgraph-specific syntax)
# ---------------------------------------------------------------------------


with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", UserWarning)

    class MemgraphNodePropertiesQuery(
        CypherReadQuery[NoParams, MemgraphNodePropertyRow]
    ):
        """Bulk node-property metadata via ``schema.node_type_properties()``.

        Uses imperative ``build()`` because the procedure is not standard Cypher.
        """

        Params = NoParams
        Output = MemgraphNodePropertyRow
        name = "memgraph.inspect.node_properties"
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

    class MemgraphRelPropertiesQuery(CypherReadQuery[NoParams, MemgraphRelPropertyRow]):
        """Bulk relationship-property metadata via ``schema.rel_type_properties()``.

        Uses imperative ``build()`` because the procedure is not standard Cypher.
        """

        Params = NoParams
        Output = MemgraphRelPropertyRow
        name = "memgraph.inspect.rel_properties"
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

    class MemgraphConstraintsQuery(CypherReadQuery[NoParams, MemgraphConstraintRow]):
        """Return all constraints via ``SHOW CONSTRAINT INFO``.

        Uses imperative ``build()`` because the command is not standard Cypher.
        """

        Params = NoParams
        Output = MemgraphConstraintRow
        name = "memgraph.inspect.constraints"
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


# ---------------------------------------------------------------------------
# Memgraph-scoped names for the shared neutral queries (identical Cypher).
# Registered under memgraph names so ``describe()`` output is clearly scoped.
# ---------------------------------------------------------------------------


class MemgraphCardinalityQuery(InspectCardinalityQuery):
    """Cardinality query under the Memgraph catalogue name."""

    name = "memgraph.inspect.cardinality"


class MemgraphEndpointLabelsQuery(InspectEndpointLabelsQuery):
    """Endpoint-labels query under the Memgraph catalogue name."""

    name = "memgraph.inspect.endpoint_labels"


class MemgraphSourcePartitionedCardinalityQuery(
    InspectSourcePartitionedCardinalityQuery
):
    """Source-side partitioned cardinality under the Memgraph catalogue name (E41.4)."""

    name = "memgraph.inspect.partitioned_cardinality.source"


class MemgraphTargetPartitionedCardinalityQuery(
    InspectTargetPartitionedCardinalityQuery
):
    """Target-side partitioned cardinality under the Memgraph catalogue name (E41.7)."""

    name = "memgraph.inspect.partitioned_cardinality.target"


# ---------------------------------------------------------------------------
# Catalogue factory
# ---------------------------------------------------------------------------


def build_memgraph_catalogue() -> QueryCatalogue:
    """Return an internal QueryCatalogue populated with Memgraph queries."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(MemgraphNodePropertiesQuery())
    query_catalogue.register_read(MemgraphRelPropertiesQuery())
    query_catalogue.register_read(MemgraphConstraintsQuery())
    query_catalogue.register_read(
        MemgraphCardinalityQuery(identifiers={"label": "_", "rel_type": "_"})
    )
    query_catalogue.register_read(
        MemgraphEndpointLabelsQuery(identifiers={"rel_type": "_"})
    )
    query_catalogue.register_read(
        MemgraphSourcePartitionedCardinalityQuery(
            identifiers={
                "label": "_",
                "rel_type": "_",
                "source_discriminator": "_",
                "target_discriminator": "_",
            }
        )
    )
    query_catalogue.register_read(
        MemgraphTargetPartitionedCardinalityQuery(
            identifiers={
                "label": "_",
                "rel_type": "_",
                "source_discriminator": "_",
                "target_discriminator": "_",
            }
        )
    )
    return query_catalogue
