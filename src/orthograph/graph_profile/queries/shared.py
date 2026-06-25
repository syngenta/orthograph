"""Vendor-neutral Cypher introspection queries.

Uses only plain ``MATCH``/``RETURN``; no APOC or vendor-specific procedures.
Runs identically on any Cypher backend.
"""

from typing import Any, cast

from orthograph.cypher.base_models import CypherReadQuery
from orthograph.cypher.bindings import NoParams
from orthograph.graph_profile.models import (
    BareRelTypeIdentifiers,
    BoundedDistribution,
    CardinalityIdentifiers,
    CardinalityStats,
    EndpointLabelsRow,
    PartitionedCardinalityIdentifiers,
    PartitionedCardinalityRow,
    PartitionKey,
    WildcardPartitionedCardinalityIdentifiers,
)


def coerce_types(raw_types: Any) -> list[str]:
    """Normalise a ``propertyTypes`` value to a list of strings."""
    if isinstance(raw_types, list):
        return raw_types
    return [raw_types] if raw_types else []


class InspectCardinalityQuery(CypherReadQuery[NoParams, CardinalityStats]):
    """Cardinality statistics for one ``(source, rel_type, target)`` shape.

    Endpoint-aware: anchors on the source ``<<label>>`` and counts each
    source node's outgoing degree of ``<<rel_type>>`` **into a target carrying
    ``<<target_label>>``**, so the degree distribution belongs to exactly one
    relationship shape rather than a bare label blended across endpoint pairs.
    """

    Params = NoParams
    Output = CardinalityStats
    name = "inspect.cardinality"
    Identifiers = CardinalityIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->(m:`<<target_label>>`)"
        " WITH n, count(r) AS degree"
        " RETURN min(degree) AS min_degree, max(degree) AS max_degree,"
        " avg(degree) AS avg_degree, count(n) AS sample_size"
    )

    def materialize(self, raw: Any) -> CardinalityStats:
        return CardinalityStats(
            count=raw["sample_size"],
            min=raw["min_degree"],
            max=raw["max_degree"],
            mean=float(raw["avg_degree"]),
        )


class InspectEndpointLabelsQuery(CypherReadQuery[NoParams, EndpointLabelsRow]):
    """Discover the distinct ``(source_labels, target_labels)`` pairs for a rel type.

    Matches every instance of the bare ``<<rel_type>>`` and returns the distinct
    endpoint-label-list pairs. The inspector then fans the per-shape count /
    property / cardinality scans out over each discovered
    ``(source_label, target_label)`` pair.
    """

    Params = NoParams
    Output = EndpointLabelsRow
    name = "inspect.endpoint_labels"
    Identifiers = BareRelTypeIdentifiers
    cypher_template = (
        "MATCH (src)-[r:`<<rel_type>>`]->(tgt)"
        " RETURN DISTINCT labels(src) AS source_labels, labels(tgt) AS target_labels"
    )

    def materialize(self, raw: Any) -> EndpointLabelsRow:
        return EndpointLabelsRow(
            source_labels=list(raw["source_labels"]),
            target_labels=list(raw["target_labels"]),
        )


def _discriminator_endpoint(name: str | None, value: Any) -> dict[str, str | None]:
    """Build one endpoint's ``{name: value}`` map for a :class:`PartitionKey`.

    A wildcard endpoint (``name is None``) carries no discriminator → ``{}``.
    Otherwise the grouped ``sk``/``tk`` value is stringified for parity with the
    NetworkX reference (``None`` preserved as ``{name: None}`` — discriminator
    present, observed value null).
    """
    if name is None:
        return {}
    return {name: None if value is None else str(value)}


def _materialize_partitioned_row(
    raw: Any, source_name: str | None, target_name: str | None
) -> PartitionedCardinalityRow:
    """Map a grouped-cardinality raw row to a :class:`PartitionedCardinalityRow`.

    Shared by the source- and target-anchored queries, which differ only in their
    Cypher (which endpoint they anchor on / whose degree they count), not in row
    shape.  The discriminator **names** (``source_name`` / ``target_name``, each
    ``None`` for a wildcard endpoint) come from the identifiers the calling query
    was built with — they are never re-derived here — so the resulting
    name-carrying :class:`PartitionKey` is self-describing.  ``stats`` is a
    :class:`BoundedDistribution` directly (not the ``CardinalityStats`` marker):
    the per-side fields are typed on ``BoundedDistribution``, so a subclass value
    would lose its subtype on reload.
    """
    return PartitionedCardinalityRow(
        key=PartitionKey(
            source=_discriminator_endpoint(source_name, raw["sk"]),
            target=_discriminator_endpoint(target_name, raw["tk"]),
        ),
        stats=BoundedDistribution(
            count=raw["sample_size"],
            min=raw["min_degree"],
            max=raw["max_degree"],
            mean=float(raw["avg_degree"]),
        ),
    )


class InspectSourcePartitionedCardinalityQuery(
    CypherReadQuery[NoParams, PartitionedCardinalityRow]
):
    """Per-pair cardinality for the **source side**.

    Anchors on the source ``<<label>>`` and counts each source node's **outgoing**
    degree of ``<<rel_type>>`` into a target carrying ``<<endpoint_label>>``,
    grouped by the absolute ``(source_discriminator, target_discriminator)`` pair.
    The ``<<endpoint_label>>`` filter restricts the breakdown to one endpoint
    shape. Source nodes with no such edge produce a ``(sk, null)``
    zero-degree partition (suppressed by the inspector for parity with NetworkX).

    All five identifiers (``label``, ``rel_type``, ``endpoint_label``, and the two
    **property-name** discriminators) are spliced via the ``<<...>>`` mechanism,
    which validates each through ``validate_identifier`` before substitution — an
    unsafe identifier is rejected, never injected.  This both-present variant is
    used when each endpoint carries a discriminator; the **one-sided** case (one
    endpoint a wildcard) uses
    :class:`InspectSourcePartitionedCardinalityWildcardSourceQuery` /
    :class:`InspectSourcePartitionedCardinalityWildcardTargetQuery`, which render
    the wildcard side as a constant ``null`` rather than a read of a non-existent
    property.

    The symmetric counterpart is :class:`InspectTargetPartitionedCardinalityQuery`.
    """

    Params = NoParams
    Output = PartitionedCardinalityRow
    name = "inspect.partitioned_cardinality.source"
    Identifiers = PartitionedCardinalityIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->(m:`<<endpoint_label>>`)"
        " WITH n, n.`<<source_discriminator>>` AS sk,"
        " m.`<<target_discriminator>>` AS tk, count(r) AS degree"
        " RETURN sk, tk, min(degree) AS min_degree, max(degree) AS max_degree,"
        " avg(degree) AS avg_degree, count(n) AS sample_size"
    )

    def materialize(self, raw: Any) -> PartitionedCardinalityRow:
        ident = cast(PartitionedCardinalityIdentifiers, self._identifiers)
        return _materialize_partitioned_row(
            raw, ident.source_discriminator, ident.target_discriminator
        )


class InspectSourcePartitionedCardinalityWildcardSourceQuery(
    CypherReadQuery[NoParams, PartitionedCardinalityRow]
):
    """Source side, **source** endpoint a wildcard: ``sk`` is constant ``null``.

    Identical to :class:`InspectSourcePartitionedCardinalityQuery` except the
    source discriminator is the literal ``null`` (no grouping key on that side),
    so only ``<<target_discriminator>>`` is spliced.  Used when a one-sided
    discriminator keys only the target endpoint.
    """

    Params = NoParams
    Output = PartitionedCardinalityRow
    name = "inspect.partitioned_cardinality.source.wildcard_source"
    Identifiers = WildcardPartitionedCardinalityIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->(m:`<<endpoint_label>>`)"
        " WITH n, null AS sk,"
        " m.`<<discriminator>>` AS tk, count(r) AS degree"
        " RETURN sk, tk, min(degree) AS min_degree, max(degree) AS max_degree,"
        " avg(degree) AS avg_degree, count(n) AS sample_size"
    )

    def materialize(self, raw: Any) -> PartitionedCardinalityRow:
        ident = cast(WildcardPartitionedCardinalityIdentifiers, self._identifiers)
        return _materialize_partitioned_row(raw, None, ident.discriminator)


class InspectSourcePartitionedCardinalityWildcardTargetQuery(
    CypherReadQuery[NoParams, PartitionedCardinalityRow]
):
    """Source side, **target** endpoint a wildcard: ``tk`` is constant ``null``.

    The natural shape for ``HAS_OUTPUT`` profiled on its source side: the counted
    (source) ``Operation`` endpoint carries the discriminator, the target
    ``Sample`` endpoint is a wildcard.  Only ``<<discriminator>>`` (the source
    property) is spliced.
    """

    Params = NoParams
    Output = PartitionedCardinalityRow
    name = "inspect.partitioned_cardinality.source.wildcard_target"
    Identifiers = WildcardPartitionedCardinalityIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->(m:`<<endpoint_label>>`)"
        " WITH n, n.`<<discriminator>>` AS sk,"
        " null AS tk, count(r) AS degree"
        " RETURN sk, tk, min(degree) AS min_degree, max(degree) AS max_degree,"
        " avg(degree) AS avg_degree, count(n) AS sample_size"
    )

    def materialize(self, raw: Any) -> PartitionedCardinalityRow:
        ident = cast(WildcardPartitionedCardinalityIdentifiers, self._identifiers)
        return _materialize_partitioned_row(raw, ident.discriminator, None)


class InspectTargetPartitionedCardinalityQuery(
    CypherReadQuery[NoParams, PartitionedCardinalityRow]
):
    """Per-pair cardinality for the **target side**.

    Symmetric to :class:`InspectSourcePartitionedCardinalityQuery` but anchors on
    the target ``<<label>>`` and counts each target node's **incoming** degree of
    ``<<rel_type>>``, grouped by the same absolute discriminator pair.  Target nodes
    with no such edge produce a ``(null, tk)`` zero-degree partition.

    This is the query a both-endpoint-conditional relationship needs for its target
    side; using the source query there would store source-outgoing degree under the
    target breakdown and diverge from the NetworkX/in-memory verdict.

    Identifier safety and zero-degree suppression are identical to the source
    query; only the anchor (``MATCH (m:..)`` / ``count(m)``) differs.  The
    **one-sided** case uses the ``WildcardSource`` / ``WildcardTarget`` variants.
    """

    Params = NoParams
    Output = PartitionedCardinalityRow
    name = "inspect.partitioned_cardinality.target"
    Identifiers = PartitionedCardinalityIdentifiers
    cypher_template = (
        "MATCH (m:`<<label>>`)"
        " OPTIONAL MATCH (n:`<<endpoint_label>>`)-[r:`<<rel_type>>`]->(m)"
        " WITH m, n.`<<source_discriminator>>` AS sk,"
        " m.`<<target_discriminator>>` AS tk, count(r) AS degree"
        " RETURN sk, tk, min(degree) AS min_degree, max(degree) AS max_degree,"
        " avg(degree) AS avg_degree, count(m) AS sample_size"
    )

    def materialize(self, raw: Any) -> PartitionedCardinalityRow:
        ident = cast(PartitionedCardinalityIdentifiers, self._identifiers)
        return _materialize_partitioned_row(
            raw, ident.source_discriminator, ident.target_discriminator
        )


class InspectTargetPartitionedCardinalityWildcardSourceQuery(
    CypherReadQuery[NoParams, PartitionedCardinalityRow]
):
    """Target side, **source** endpoint a wildcard: ``sk`` is constant ``null``.

    The natural shape for ``IS_INPUT`` profiled on its target side: the counted
    (target) ``Operation`` endpoint carries the discriminator, the source
    ``Sample`` endpoint is a wildcard.  Only ``<<discriminator>>`` (the target
    property) is spliced.
    """

    Params = NoParams
    Output = PartitionedCardinalityRow
    name = "inspect.partitioned_cardinality.target.wildcard_source"
    Identifiers = WildcardPartitionedCardinalityIdentifiers
    cypher_template = (
        "MATCH (m:`<<label>>`)"
        " OPTIONAL MATCH (n:`<<endpoint_label>>`)-[r:`<<rel_type>>`]->(m)"
        " WITH m, null AS sk,"
        " m.`<<discriminator>>` AS tk, count(r) AS degree"
        " RETURN sk, tk, min(degree) AS min_degree, max(degree) AS max_degree,"
        " avg(degree) AS avg_degree, count(m) AS sample_size"
    )

    def materialize(self, raw: Any) -> PartitionedCardinalityRow:
        ident = cast(WildcardPartitionedCardinalityIdentifiers, self._identifiers)
        return _materialize_partitioned_row(raw, None, ident.discriminator)


class InspectTargetPartitionedCardinalityWildcardTargetQuery(
    CypherReadQuery[NoParams, PartitionedCardinalityRow]
):
    """Target side, **target** endpoint a wildcard: ``tk`` is constant ``null``.

    The counted target endpoint is the wildcard and the source endpoint carries
    the discriminator.  Only ``<<discriminator>>`` (the source property) is
    spliced.
    """

    Params = NoParams
    Output = PartitionedCardinalityRow
    name = "inspect.partitioned_cardinality.target.wildcard_target"
    Identifiers = WildcardPartitionedCardinalityIdentifiers
    cypher_template = (
        "MATCH (m:`<<label>>`)"
        " OPTIONAL MATCH (n:`<<endpoint_label>>`)-[r:`<<rel_type>>`]->(m)"
        " WITH m, n.`<<discriminator>>` AS sk,"
        " null AS tk, count(r) AS degree"
        " RETURN sk, tk, min(degree) AS min_degree, max(degree) AS max_degree,"
        " avg(degree) AS avg_degree, count(m) AS sample_size"
    )

    def materialize(self, raw: Any) -> PartitionedCardinalityRow:
        ident = cast(WildcardPartitionedCardinalityIdentifiers, self._identifiers)
        return _materialize_partitioned_row(raw, ident.discriminator, None)
