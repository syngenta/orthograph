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

import json
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
    InspectSourcePartitionedCardinalityQuery,
    InspectTargetPartitionedCardinalityQuery,
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


# ---------------------------------------------------------------------------
# Value-scan currency and parameters (E46.1)
# ---------------------------------------------------------------------------


class TopNParams(BaseModel):
    """Value parameter for the bounded value-histogram queries.

    ``top_n`` is the histogram truncation cap (the ``value_counts_top_n`` opt-in).
    It is a driver ``$top_n`` parameter, never interpolated into the Cypher.
    """

    top_n: int


class TypeCountRow(BaseModel):
    """One ``{runtime-type-name: count}`` row from a type-count aggregation.

    Produced by grouping a property's non-null values by their runtime storage
    type (``apoc.meta.cypher.type``) and counting each group.  Exact and bounded:
    one row per distinct *type*, never per distinct value.

    ``type_name`` is normalised to the ``observed_types`` vocabulary (the
    ``coerce_types`` names: ``'Long'``, ``'String'``, …) — *not* the raw
    ``apoc.meta.cypher.type`` names (``'INTEGER'``, ``'STRING'``, …) — so the
    invariant ``set(observed_type_counts) ⊆ set(observed_types)``
    holds and ``db_type_to_python`` (which keys on the ``coerce_types``
    vocabulary) needs no change.
    """

    type_name: str
    type_count: int


class ValueHistogramRow(BaseModel):
    """One ``{value: count}`` row from a bounded value-histogram aggregation.

    The query groups on ``apoc.convert.toJson(value)`` (the list-safe value key),
    so the raw key is JSON-encoded: scalars come back quoted (``"Neo"``, ``1980``,
    ``true``) and lists as JSON arrays (``["Neo"]``).  The materialiser
    **unwraps a JSON-encoded string** back to its bare form (``"Neo"`` → ``Neo``)
    so string histogram keys read naturally and match the NetworkX reference's
    ``str(value)`` for scalar strings.  Non-string JSON (numbers,
    booleans, arrays) is kept verbatim — stable and unambiguous.

    The query orders by frequency and applies ``LIMIT $top_n``; the remainder
    (``other_count``) is reconciled by the inspector against ``present_count``
    (E46.2).
    """

    value: str
    value_count: int


def _unwrap_json_value(raw_value: Any) -> str:
    """Normalise an ``apoc.convert.toJson`` histogram key for the model.

    A JSON-encoded *string* (e.g. ``'"Neo"'``) is decoded back to its bare form
    (``'Neo'``) so string keys read naturally and match the NetworkX reference's
    ``str(value)``.  Any other JSON shape (number, boolean, array, object) — or a
    value that does not parse as JSON — is returned as ``str(raw_value)``
    unchanged (honest, never re-encoded).

    **Key-collision caveat**: a string property whose *literal DB value* is
    ``'"Neo"'`` (the 5-char sequence including the double-quotes) would produce
    the same histogram key as a property whose value is ``'Neo'``.  This can
    only occur in dirty data where string values embed surrounding double-quotes;
    the counts of both values would merge into one bucket.  The effect is
    limited to histogram-key fidelity; ``present_count`` and type counts are
    unaffected.
    """
    text = str(raw_value)
    try:
        decoded = json.loads(text)
    except (ValueError, TypeError):
        return text
    # Only a JSON *string* is unwrapped to its bare form; every other JSON shape
    # (number, boolean, array, object) returns ``text`` — the original
    # ``str(raw_value)`` — never ``str(decoded)``.  This keeps the key byte-stable
    # regardless of how json re-stringifies a number (e.g. ``1980`` vs ``1980.0``).
    # ``raw_value`` is always a ``str`` here (``apoc.convert.toJson`` returns a
    # JSON string from the driver), so ``text`` is the faithful original key.
    return decoded if isinstance(decoded, str) else text


# Maps the ``apoc.meta.cypher.type`` runtime-type vocabulary (upper-case, e.g.
# ``'INTEGER'``, ``'LIST OF FLOAT'``) onto the ``observed_types`` vocabulary
# produced by ``apoc.meta.nodeTypeProperties`` / ``db.schema.*`` (the
# ``coerce_types`` names, e.g. ``'Long'``, ``'DoubleArray'``).  The two APOC
# surfaces disagree on spelling; the type counts must reuse the
# ``observed_types`` vocabulary, so the type-count materialiser normalises here.
# An unrecognised runtime type passes through verbatim (honest, never invented) —
# e.g. a mixed-element list yields ``'LIST OF ANY'``, which is kept as-is.
#
# DEPRECATION (revisit when targeting Cypher 25): ``apoc.meta.cypher.type`` is
# deprecated in Cypher 25 in favour of the built-in ``valueType()``, whose
# vocabulary differs again (e.g. ``'INTEGER NOT NULL'``).  When the type-count
# queries move to ``valueType()`` they will need their own name map keyed on
# that vocabulary; this map stays paired with ``apoc.meta.cypher.type``.
_APOC_TYPE_NAME_MAP: dict[str, str] = {
    "INTEGER": "Long",
    "FLOAT": "Double",
    "STRING": "String",
    "BOOLEAN": "Boolean",
    "DATE": "Date",
    "DATE_TIME": "DateTime",
    "LOCAL_DATE_TIME": "LocalDateTime",
    "TIME": "Time",
    "LOCAL_TIME": "LocalTime",
    "DURATION": "Duration",
    "POINT": "Point",
    "LIST OF INTEGER": "LongArray",
    "LIST OF FLOAT": "DoubleArray",
    "LIST OF STRING": "StringArray",
    "LIST OF BOOLEAN": "BooleanArray",
}


def _normalise_apoc_type_name(raw_type: str) -> str:
    """Map an ``apoc.meta.cypher.type`` name to the ``observed_types`` vocabulary.

    Unrecognised names pass through unchanged so a backend never invents or
    silently drops a type it cannot map (honesty principle).
    """
    return _APOC_TYPE_NAME_MAP.get(raw_type, raw_type)


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

    class ApocRelTypesQuery(CypherReadQuery[NoParams, DbSchemaRelTypeRow]):
        """Bulk relationship-property **types** via ``apoc.meta.relTypeProperties``.

        Under ADR-037 §6a the per-shape relationship property *counts* come from
        the endpoint-filtered pattern scan (:class:`CypherRelPropertiesQuery`);
        APOC meta cannot be endpoint-filtered, so it is used here only as a bulk
        ``observed_types`` source keyed by the **bare** rel type (a property key's
        stored type does not vary by endpoint pair).  Mirrors
        :class:`DbSchemaRelTypesQuery`.

        Uses imperative ``build()`` because ``CALL apoc.meta.*`` is not standard
        Cypher.
        """

        Params = NoParams
        Output = DbSchemaRelTypeRow
        name = "neo4j.inspect.apoc.rel_types"
        Identifiers = NoIdentifiers
        _CYPHER = (
            "CALL apoc.meta.relTypeProperties({sample: -1})"
            " YIELD relType, propertyName, propertyTypes"
            " RETURN relType, propertyName, propertyTypes"
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
# Pure-Cypher fallback queries
# ---------------------------------------------------------------------------


class _NodePropertyScanIdentifiers(BaseModel):
    """Identifier group scoping a per-property query to one node label.

    Shared by the property-independent present-count query and the
    value-scan queries : both target one property of one node label.
    """

    label: str
    property_name: str  # property key (kind = "label" grammar)


class _RelPropertyScanIdentifiers(BaseModel):
    """Identifier group scoping a per-property query to one relationship *shape*.

    Shared by the present-count query and the value-scan queries.  Endpoint-aware:
    the scan is filtered to edges of ``rel_type`` whose endpoints carry
    ``source_label`` / ``target_label``, so per-shape statistics are un-blended.
    """

    source_label: str  # kind = "label"
    rel_type: str  # kind = "relationship type"
    target_label: str  # kind = "label"
    property_name: str  # property key (kind = "label" grammar)


class CountRow(BaseModel):
    """A single instance-count row for a node label or relationship type."""

    count: int


class PresentCountRow(BaseModel):
    """A single non-null-occurrence count for one property of a type.

    The authoritative ``present_count`` (numerator of ``completeness``): the
    true number of entities of a type whose given property is non-null, measured
    by a dedicated ``count() … WHERE … IS NOT NULL`` rather than APOC's sampled
    ``propertyObservations`` (which can undercount).
    """

    present_count: int


class NodeCountQuery(CypherReadQuery[NoParams, CountRow]):
    """Authoritative instance count for a node label (independent of properties).

    Property-derived counts are zero for a label/rel-type that has *no*
    properties (the property scan yields no rows), so the instance count must
    come from a dedicated ``count()`` that does not depend on any property.
    """

    Params = NoParams
    Output = CountRow
    name = "neo4j.inspect.node_count"
    Identifiers = NodeLabelIdentifiers
    cypher_template = "MATCH (n:`<<label>>`) RETURN count(n) AS count"

    def materialize(self, raw: Any) -> CountRow:
        return CountRow(count=raw["count"])


class RelCountQuery(CypherReadQuery[NoParams, CountRow]):
    """Authoritative instance count for one relationship *shape*.

    Endpoint-filtered: counts only edges of ``<<rel_type>>`` whose source carries
    ``<<source_label>>`` and target carries ``<<target_label>>``, so the count
    belongs to exactly one ``(source, rel, target)`` shape.
    """

    Params = NoParams
    Output = CountRow
    name = "neo4j.inspect.rel_count"
    Identifiers = RelTypeIdentifiers
    cypher_template = (
        "MATCH (:`<<source_label>>`)-[r:`<<rel_type>>`]->(:`<<target_label>>`)"
        " RETURN count(r) AS count"
    )

    def materialize(self, raw: Any) -> CountRow:
        return CountRow(count=raw["count"])


class NodePresentCountQuery(CypherReadQuery[NoParams, PresentCountRow]):
    """Authoritative non-null count for one node property.

    Supersedes APOC's sampled ``propertyObservations`` on the APOC no-scan path.
    Bounded: a single server-side ``count()`` over a null predicate — one scalar
    row, no value materialised to the client.  ``property_name`` is an identifier
    (label-grammar), never an interpolated value.
    """

    Params = NoParams
    Output = PresentCountRow
    name = "neo4j.inspect.node_present_count"
    Identifiers = _NodePropertyScanIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " WHERE n.`<<property_name>>` IS NOT NULL"
        " RETURN count(n) AS present_count"
    )

    def materialize(self, raw: Any) -> PresentCountRow:
        return PresentCountRow(present_count=raw["present_count"])


class RelPresentCountQuery(CypherReadQuery[NoParams, PresentCountRow]):
    """Authoritative non-null count for one relationship property.

    Supersedes APOC's sampled ``propertyObservations`` for relationship
    properties (the 100-vs-172 undercount).  Mirrors
    :class:`NodePresentCountQuery`.
    """

    Params = NoParams
    Output = PresentCountRow
    name = "neo4j.inspect.rel_present_count"
    Identifiers = _RelPropertyScanIdentifiers
    cypher_template = (
        "MATCH (:`<<source_label>>`)-[r:`<<rel_type>>`]->(:`<<target_label>>`)"
        " WHERE r.`<<property_name>>` IS NOT NULL"
        " RETURN count(r) AS present_count"
    )

    def materialize(self, raw: Any) -> PresentCountRow:
        return PresentCountRow(present_count=raw["present_count"])


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
    """Per-shape relationship property metadata via MATCH/UNWIND scan (no APOC).

    Endpoint-filtered: scans only edges of ``<<rel_type>>`` between
    ``<<source_label>>`` and ``<<target_label>>``, so ``present`` / ``total`` are
    per-shape.  ``propertyTypes`` is always ``[]`` (types come from the bulk
    ``db.schema`` map, keyed by bare rel type).
    """

    Params = NoParams
    Output = NodePropertyRow
    name = "neo4j.inspect.cypher.rel_properties"
    Identifiers = RelTypeIdentifiers
    cypher_template = (
        "MATCH (:`<<source_label>>`)-[r:`<<rel_type>>`]->(:`<<target_label>>`)"
        " WITH count(r) AS total"
        " MATCH (:`<<source_label>>`)-[r:`<<rel_type>>`]->(:`<<target_label>>`)"
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
# Value-scan queries (E46.1): one bounded scan per property exposes a
# {value: count} histogram (truncating) AND an exact {type-name: count} mapping.
# Both group server-side so the client never receives a per-value row set for
# the type aggregation.  Identifiers (label / rel_type / property_name) are
# spliced via <<placeholder>>; values are never interpolated.
# ---------------------------------------------------------------------------


class ApocNodeTypeCountsQuery(CypherReadQuery[NoParams, TypeCountRow]):
    """Exact per-type counts for a node property (group by runtime type).

    Groups the property's non-null values by ``apoc.meta.cypher.type(v)`` and
    counts each group, so the result has one row per distinct *type* — bounded
    and exact even on a UID / free-text column.
    """

    Params = NoParams
    Output = TypeCountRow
    name = "neo4j.inspect.apoc.node_type_counts"
    Identifiers = _NodePropertyScanIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " WHERE n.`<<property_name>>` IS NOT NULL"
        " WITH apoc.meta.cypher.type(n.`<<property_name>>`) AS type_name,"
        " count(*) AS type_count"
        " RETURN type_name, type_count"
    )

    def materialize(self, raw: Any) -> TypeCountRow:
        return TypeCountRow(
            type_name=_normalise_apoc_type_name(raw["type_name"]),
            type_count=raw["type_count"],
        )


class ApocRelTypeCountsQuery(CypherReadQuery[NoParams, TypeCountRow]):
    """Exact per-type counts for a relationship property (group by runtime type)."""

    Params = NoParams
    Output = TypeCountRow
    name = "neo4j.inspect.apoc.rel_type_counts"
    Identifiers = _RelPropertyScanIdentifiers
    cypher_template = (
        "MATCH (:`<<source_label>>`)-[r:`<<rel_type>>`]->(:`<<target_label>>`)"
        " WHERE r.`<<property_name>>` IS NOT NULL"
        " WITH apoc.meta.cypher.type(r.`<<property_name>>`) AS type_name,"
        " count(*) AS type_count"
        " RETURN type_name, type_count"
    )

    def materialize(self, raw: Any) -> TypeCountRow:
        return TypeCountRow(
            type_name=_normalise_apoc_type_name(raw["type_name"]),
            type_count=raw["type_count"],
        )


class ApocNodeValueHistogramQuery(CypherReadQuery[TopNParams, ValueHistogramRow]):
    """Bounded value histogram for a node property (group by value, LIMIT top_n).

    The only truncating part of the scan: groups by the JSON-coerced value,
    orders by frequency and keeps the top ``$top_n``.  Using
    ``apoc.convert.toJson(value)`` as the grouping key handles every Neo4j
    storage type uniformly — scalars *and* lists (``StringArray``, ``LongArray``,
    …) which plain ``toString()`` cannot stringify.  This makes the *list-keeping*
    histogram an APOC/SCHEMA feature (it shares the runtime-function requirement
    with the type-count query).  Pure-CYPHER cannot keep lists in the histogram,
    but this module  gives it a **scalar-only** fallback
    (:class:`CypherNodeValueHistogramQuery`, ``toStringOrNull``) so scalar
    properties still get a histogram there.

    Ties are broken on the JSON-encoded ``value`` key ASC for determinism.  This
    does **not** perfectly match the NetworkX reference's ``str(value)`` tie-break
    at the ``top_n`` truncation boundary: for *string* properties the JSON key has
    surrounding double-quotes (``'"Neo"'``), which shifts sort order relative to
    Python's ``str()`` (``'Neo'``); for array properties the JSON and Python repr
    formats differ entirely.  This divergence is a known limitation — cross-backend
    parity at the truncation boundary is verified in E46.3.  Using ``toString()``
    here would be wrong: it throws a ``TypeError`` on array/list properties.  The
    remainder is reconciled into ``other_count`` by the inspector (E46.2).
    """

    Params = TopNParams
    Output = ValueHistogramRow
    name = "neo4j.inspect.apoc.node_value_histogram"
    Identifiers = _NodePropertyScanIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " WHERE n.`<<property_name>>` IS NOT NULL"
        " WITH apoc.convert.toJson(n.`<<property_name>>`) AS value,"
        " count(*) AS value_count"
        " RETURN value, value_count"
        " ORDER BY value_count DESC, value ASC"
        " LIMIT $top_n"
    )

    def materialize(self, raw: Any) -> ValueHistogramRow:
        return ValueHistogramRow(
            value=_unwrap_json_value(raw["value"]),
            value_count=raw["value_count"],
        )


class ApocRelValueHistogramQuery(CypherReadQuery[TopNParams, ValueHistogramRow]):
    """Bounded value histogram for a relationship property (group by value).

    Uses ``apoc.convert.toJson(value)`` as the grouping key so all Neo4j storage
    types (including list properties) are handled uniformly — making this an
    APOC/SCHEMA feature.  Ties broken on the JSON-encoded key ASC for determinism;
    see :class:`ApocNodeValueHistogramQuery` for the known parity limitation vs.
    the NetworkX ``str(value)`` tie-break.
    """

    Params = TopNParams
    Output = ValueHistogramRow
    name = "neo4j.inspect.apoc.rel_value_histogram"
    Identifiers = _RelPropertyScanIdentifiers
    cypher_template = (
        "MATCH (:`<<source_label>>`)-[r:`<<rel_type>>`]->(:`<<target_label>>`)"
        " WHERE r.`<<property_name>>` IS NOT NULL"
        " WITH apoc.convert.toJson(r.`<<property_name>>`) AS value,"
        " count(*) AS value_count"
        " RETURN value, value_count"
        " ORDER BY value_count DESC, value ASC"
        " LIMIT $top_n"
    )

    def materialize(self, raw: Any) -> ValueHistogramRow:
        return ValueHistogramRow(
            value=_unwrap_json_value(raw["value"]),
            value_count=raw["value_count"],
        )


# ---------------------------------------------------------------------------
# Pure-Cypher scalar value-histogram fallback (E46.6).
# When APOC is absent the full value scan is skipped (no runtime-type function
# for type counts, no apoc.convert.toJson for a list-safe histogram key).  This
# fallback restores a *histogram* for scalar-typed properties using the built-in
# toStringOrNull(v): it returns null for list / map / non-stringifiable values
# (so they are dropped by the WHERE) instead of crashing the way plain
# toString(list) does (`Invalid input for function 'toString()': … StringArray`).
# Type counts stay {} on this path (no portable runtime-type function).  The
# histogram total reconciles only over the *scalar* population it scanned; the
# dropped non-scalars fold into other_count (the inspector reconciles against the
# pure-Cypher present_count — partial-population semantics).
# ---------------------------------------------------------------------------


class CypherNodeValueHistogramQuery(CypherReadQuery[TopNParams, ValueHistogramRow]):
    """Bounded scalar value histogram for a node property (no APOC).

    Groups on ``toStringOrNull(value)`` — the list-safe scalar key: a list / map /
    non-stringifiable value becomes ``null`` and is dropped by the ``WHERE`` (so
    only scalar values are histogrammed), ordered by frequency, ``LIMIT $top_n``.
    Unlike :class:`ApocNodeValueHistogramQuery` this keeps no list values *in* the
    histogram (no portable list-safe key without APOC); the dropped non-scalars
    fold into ``other_count`` via the inspector.
    """

    Params = TopNParams
    Output = ValueHistogramRow
    name = "neo4j.inspect.cypher.node_value_histogram"
    Identifiers = _NodePropertyScanIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " WITH toStringOrNull(n.`<<property_name>>`) AS value"
        " WHERE value IS NOT NULL"
        " WITH value, count(*) AS value_count"
        " RETURN value, value_count"
        " ORDER BY value_count DESC, value ASC"
        " LIMIT $top_n"
    )

    def materialize(self, raw: Any) -> ValueHistogramRow:
        return ValueHistogramRow(
            value=str(raw["value"]),
            value_count=raw["value_count"],
        )


class CypherRelValueHistogramQuery(CypherReadQuery[TopNParams, ValueHistogramRow]):
    """Bounded scalar value histogram for a relationship property (no APOC).

    Mirrors :class:`CypherNodeValueHistogramQuery` (``toStringOrNull`` key,
    scalars only, lists dropped, ``LIMIT $top_n``) for relationship properties.
    """

    Params = TopNParams
    Output = ValueHistogramRow
    name = "neo4j.inspect.cypher.rel_value_histogram"
    Identifiers = _RelPropertyScanIdentifiers
    cypher_template = (
        "MATCH (:`<<source_label>>`)-[r:`<<rel_type>>`]->(:`<<target_label>>`)"
        " WITH toStringOrNull(r.`<<property_name>>`) AS value"
        " WHERE value IS NOT NULL"
        " WITH value, count(*) AS value_count"
        " RETURN value, value_count"
        " ORDER BY value_count DESC, value ASC"
        " LIMIT $top_n"
    )

    def materialize(self, raw: Any) -> ValueHistogramRow:
        return ValueHistogramRow(
            value=str(raw["value"]),
            value_count=raw["value_count"],
        )


_PARTITIONED_PLACEHOLDER_IDENTIFIERS = {
    "label": "_",
    "rel_type": "_",
    "endpoint_label": "_",
    "source_discriminators": ["_"],
    "target_discriminators": ["_"],
}


def _register_partitioned_cardinality(catalogue: QueryCatalogue) -> None:
    """Register both per-side partitioned cardinality queries.

    Source and target are always registered together so every strategy catalogue
    (APOC / Cypher / SCHEMA) exposes the symmetric pair — a both-endpoint
    conditional relationship can be profiled on either side regardless of which
    inspection strategy is active.  Each query is variable-width: an endpoint's
    discriminator list may be empty (a wildcard side, no grouped column) or carry
    1..N property names (E54), so the former four one-sided ``wildcard_*`` query
    classes are subsumed and no longer registered.
    """
    catalogue.register_read(
        InspectSourcePartitionedCardinalityQuery(
            identifiers=_PARTITIONED_PLACEHOLDER_IDENTIFIERS
        )
    )
    catalogue.register_read(
        InspectTargetPartitionedCardinalityQuery(
            identifiers=_PARTITIONED_PLACEHOLDER_IDENTIFIERS
        )
    )


_VALUE_SCAN_PLACEHOLDER_NODE = {"label": "_", "property_name": "_"}
_VALUE_SCAN_PLACEHOLDER_REL = {
    "source_label": "_",
    "rel_type": "_",
    "target_label": "_",
    "property_name": "_",
}
_REL_SHAPE_PLACEHOLDER = {"source_label": "_", "rel_type": "_", "target_label": "_"}


def _register_present_counts(catalogue: QueryCatalogue) -> None:
    """Register the property-independent present-count queries.

    Registered in **all three** catalogues for parity and introspection (like
    ``NodeCountQuery`` / ``RelCountQuery``).  The inspector only *uses* them on
    the APOC strategy's no-scan path, where they supersede APOC's sampled
    ``propertyObservations``; the CYPHER / SCHEMA strategies already get a
    truthful count from their pure-Cypher property scan.
    """
    catalogue.register_read(
        NodePresentCountQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_NODE)
    )
    catalogue.register_read(
        RelPresentCountQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_REL)
    )


def _register_value_scan(catalogue: QueryCatalogue) -> None:
    """Register the full value-scan query set: type counts + value histograms.

    Both aggregations require the APOC runtime functions (``apoc.meta.cypher.type``
    for type counts, ``apoc.convert.toJson`` for the histogram's list-safe value
    key), so the value scan is registered only in strategies where APOC is
    available (APOC always; SCHEMA when APOC is present — the inspector gates at
    runtime).  Pure-CYPHER omits the whole value scan ⇒ ``observed_type_counts``
    stays ``{}`` and ``value_distribution`` stays ``None``.
    """
    catalogue.register_read(
        ApocNodeTypeCountsQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_NODE)
    )
    catalogue.register_read(
        ApocRelTypeCountsQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_REL)
    )
    catalogue.register_read(
        ApocNodeValueHistogramQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_NODE)
    )
    catalogue.register_read(
        ApocRelValueHistogramQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_REL)
    )


def _register_cypher_value_histogram(catalogue: QueryCatalogue) -> None:
    """Register the scalar-only pure-Cypher histogram fallback (E46.6).

    Used on strategies that may lack APOC (pure-CYPHER always; SCHEMA when the
    runtime APOC probe is negative).  Only the *histogram* is provided here —
    type counts need a runtime-type function APOC supplies, so ``{}`` stays
    honest on these strategies.  ``toStringOrNull`` keeps
    the histogram list-safe: list/map values become ``null`` and are dropped
    rather than crashing ``toString``.
    """
    catalogue.register_read(
        CypherNodeValueHistogramQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_NODE)
    )
    catalogue.register_read(
        CypherRelValueHistogramQuery(identifiers=_VALUE_SCAN_PLACEHOLDER_REL)
    )


def build_apoc_catalogue() -> QueryCatalogue:
    """Return an internal QueryCatalogue populated with APOC-strategy queries."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(InspectNodeLabelsQuery())
    query_catalogue.register_read(InspectRelTypesQuery())
    query_catalogue.register_read(NodeCountQuery(identifiers={"label": "_"}))
    query_catalogue.register_read(RelCountQuery(identifiers=_REL_SHAPE_PLACEHOLDER))
    query_catalogue.register_read(ApocNodePropertiesQuery(identifiers={"label": "_"}))
    # Per-shape relationship counts come from the endpoint-filtered pattern scan
    # APOC meta is the bulk bare-type *types* source only.
    query_catalogue.register_read(ApocRelTypesQuery())
    query_catalogue.register_read(
        CypherRelPropertiesQuery(identifiers=_REL_SHAPE_PLACEHOLDER)
    )
    query_catalogue.register_read(
        InspectCardinalityQuery(
            identifiers={"label": "_", "rel_type": "_", "target_label": "_"}
        )
    )
    query_catalogue.register_read(InspectNeo4jConstraintsQuery())
    query_catalogue.register_read(
        InspectEndpointLabelsQuery(identifiers={"rel_type": "_"})
    )
    _register_partitioned_cardinality(query_catalogue)
    _register_present_counts(query_catalogue)
    _register_value_scan(query_catalogue)
    return query_catalogue


def build_cypher_catalogue() -> QueryCatalogue:
    """Return an internal QueryCatalogue populated with pure-Cypher queries."""
    query_catalogue = QueryCatalogue()
    query_catalogue.register_read(InspectNodeLabelsQuery())
    query_catalogue.register_read(InspectRelTypesQuery())
    query_catalogue.register_read(NodeCountQuery(identifiers={"label": "_"}))
    query_catalogue.register_read(RelCountQuery(identifiers=_REL_SHAPE_PLACEHOLDER))
    query_catalogue.register_read(CypherNodePropertiesQuery(identifiers={"label": "_"}))
    query_catalogue.register_read(
        CypherRelPropertiesQuery(identifiers=_REL_SHAPE_PLACEHOLDER)
    )
    query_catalogue.register_read(
        InspectCardinalityQuery(
            identifiers={"label": "_", "rel_type": "_", "target_label": "_"}
        )
    )
    query_catalogue.register_read(InspectNeo4jConstraintsQuery())
    query_catalogue.register_read(
        InspectEndpointLabelsQuery(identifiers={"rel_type": "_"})
    )
    _register_partitioned_cardinality(query_catalogue)
    _register_present_counts(query_catalogue)
    _register_cypher_value_histogram(query_catalogue)
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
    query_catalogue.register_read(NodeCountQuery(identifiers={"label": "_"}))
    query_catalogue.register_read(RelCountQuery(identifiers=_REL_SHAPE_PLACEHOLDER))
    query_catalogue.register_read(CypherNodePropertiesQuery(identifiers={"label": "_"}))
    query_catalogue.register_read(
        CypherRelPropertiesQuery(identifiers=_REL_SHAPE_PLACEHOLDER)
    )
    query_catalogue.register_read(DbSchemaNodeTypesQuery())
    query_catalogue.register_read(DbSchemaRelTypesQuery())
    query_catalogue.register_read(
        InspectCardinalityQuery(
            identifiers={"label": "_", "rel_type": "_", "target_label": "_"}
        )
    )
    query_catalogue.register_read(InspectNeo4jConstraintsQuery())
    query_catalogue.register_read(
        InspectEndpointLabelsQuery(identifiers={"rel_type": "_"})
    )
    _register_partitioned_cardinality(query_catalogue)
    _register_present_counts(query_catalogue)
    _register_value_scan(query_catalogue)
    _register_cypher_value_histogram(query_catalogue)
    return query_catalogue
