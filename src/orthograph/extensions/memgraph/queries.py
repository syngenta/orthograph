"""Typed Cypher read queries for Memgraph schema introspection.

Each class is a ``CypherReadQuery`` subclass.  Dynamic identifiers (node
labels, relationship types) are carried through the
``Identifiers``/``<<placeholder>>`` mechanism from ADR-010.

Memgraph uses bulk schema procedures (``schema.node_type_properties()``,
``schema.rel_type_properties()``) that return all labels/types in a single
call, unlike Neo4j's per-label APOC path.  This structural difference is why
a single cross-backend ``QueryStrategy`` Protocol would have distorted one
backend (ADR-009, Considered Options).

Parity gaps vs. NetworkX / Neo4j — documented explicitly rather than silently
skipped:

  * ``NodeTypeProfile.count`` — always 0.  ``schema.node_type_properties()``
    yields no observation counts.
  * ``RelationshipTypeProfile.count`` — always 0, same reason.
  * ``PropertyProfile.present_count`` / ``.total_count`` — set to
    ``int(mandatory)`` / 1 (mandatory heuristic).  The Memgraph schema
    procedures yield a ``mandatory`` boolean, not observation counts.

``cardinality_stats`` and ``source_labels``/``target_labels`` ARE populated:
cardinality via ``InspectCardinalityQuery`` (shared with Neo4j — identical
Cypher), endpoint labels via ``InspectEndpointLabelsQuery`` (also shared).

``MemgraphQueries`` (the old untyped helper class) has been retired
(ADR-009 T7 decision: Option A).

Note on imperative style: ``MemgraphNodePropertiesQuery``,
``MemgraphRelPropertiesQuery``, and ``MemgraphConstraintsQuery`` use imperative
``build()`` because ``CALL schema.*`` and ``SHOW CONSTRAINT INFO`` are
Memgraph-specific commands that the graphglot dialect parser does not recognise
as standard Cypher.
"""

import warnings as _warnings
from typing import Any

from pydantic import BaseModel, Field

from orthograph.extensions.cypher.base_models import CypherReadQuery
from orthograph.extensions.cypher.bindings import CypherQuery, NoParams

# ---------------------------------------------------------------------------
# Re-export shared identifier + output models from neo4j.queries so Memgraph
# tests and callers can import from one place without circular imports.
# The shared typed query classes are also re-used directly.
# ---------------------------------------------------------------------------
from orthograph.extensions.neo4j.queries import (  # noqa: E402
    InspectCardinalityQuery,
    InspectEndpointLabelsQuery,
    _coerce_types,
)


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
    ):  # noqa: E501
        """Bulk node-property metadata via Memgraph's schema procedure.

        Returns one row per (nodeType, propertyName) pair across ALL node types.
        The inspector aggregates the rows by label.

        Uses imperative ``build()`` because ``CALL schema.*`` is Memgraph-specific
        and not recognised by the graphglot dialect parser.
        """

        Params = NoParams
        Output = MemgraphNodePropertyRow
        name = "memgraph.inspect.node_properties"
        _CYPHER = (
            "CALL schema.node_type_properties()"
            " YIELD nodeType, nodeLabels, mandatory, propertyName, propertyTypes"
        )

        def build(self, params: NoParams) -> CypherQuery:
            return self._CYPHER, {}

        def materialize(self, raw: Any) -> MemgraphNodePropertyRow:
            types = raw.get("propertyTypes", [])
            return MemgraphNodePropertyRow(
                node_type=raw["nodeType"],
                node_labels=raw.get("nodeLabels", []),
                mandatory=raw.get("mandatory", False),
                property_name=raw.get("propertyName"),
                property_types=_coerce_types(types),
            )

    class MemgraphRelPropertiesQuery(CypherReadQuery[NoParams, MemgraphRelPropertyRow]):
        """Bulk relationship-property metadata via Memgraph's schema procedure.

        Uses imperative ``build()`` because ``CALL schema.*`` is Memgraph-specific.
        """

        Params = NoParams
        Output = MemgraphRelPropertyRow
        name = "memgraph.inspect.rel_properties"
        _CYPHER = (
            "CALL schema.rel_type_properties()"
            " YIELD relType, mandatory, propertyName, propertyTypes"
        )

        def build(self, params: NoParams) -> CypherQuery:
            return self._CYPHER, {}

        def materialize(self, raw: Any) -> MemgraphRelPropertyRow:
            types = raw.get("propertyTypes", [])
            return MemgraphRelPropertyRow(
                rel_type=raw["relType"],
                mandatory=raw.get("mandatory", False),
                property_name=raw.get("propertyName"),
                property_types=_coerce_types(types),
            )

    class MemgraphConstraintsQuery(CypherReadQuery[NoParams, MemgraphConstraintRow]):
        """Return all constraints from Memgraph (``SHOW CONSTRAINT INFO``).

        Uses imperative ``build()`` because ``SHOW CONSTRAINT INFO`` is a
        Memgraph admin command not recognised by the graphglot dialect parser.
        """

        Params = NoParams
        Output = MemgraphConstraintRow
        name = "memgraph.inspect.constraints"
        _CYPHER = "SHOW CONSTRAINT INFO"

        def build(self, params: NoParams) -> CypherQuery:
            return self._CYPHER, {}

        def materialize(self, raw: Any) -> MemgraphConstraintRow:
            return MemgraphConstraintRow(
                constraint_type=raw.get("constraint type", ""),
                entity_type=raw.get("entity type", ""),
                label=raw.get("label"),
                properties=raw.get("properties", []),
            )


# ---------------------------------------------------------------------------
# Memgraph versions of the shared queries (same classes, different names)
# ---------------------------------------------------------------------------
# The cardinality and endpoint-label queries have identical Cypher text on both
# backends. We register them in the Memgraph catalogue under different names so
# ``describe()`` output is clearly scoped.


class MemgraphCardinalityQuery(InspectCardinalityQuery):
    """Cardinality query registered under the Memgraph catalogue name."""

    name = "memgraph.inspect.cardinality"


class MemgraphEndpointLabelsQuery(InspectEndpointLabelsQuery):
    """Endpoint-labels query registered under the Memgraph catalogue name."""

    name = "memgraph.inspect.endpoint_labels"


# ---------------------------------------------------------------------------
# Catalogue factory
# ---------------------------------------------------------------------------

from orthograph.catalogue.registry import QueryCatalogue  # noqa: E402


def build_memgraph_catalogue() -> QueryCatalogue:
    """Return an internal QueryCatalogue populated with Memgraph queries."""
    cat = QueryCatalogue()
    cat.register_read(MemgraphNodePropertiesQuery())
    cat.register_read(MemgraphRelPropertiesQuery())
    cat.register_read(MemgraphConstraintsQuery())
    cat.register_read(
        MemgraphCardinalityQuery(identifiers={"label": "_", "rel_type": "_"})
    )
    cat.register_read(MemgraphEndpointLabelsQuery(identifiers={"rel_type": "_"}))
    return cat
