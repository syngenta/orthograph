"""Vendor-neutral Cypher introspection queries.

Uses only plain ``MATCH``/``RETURN``; no APOC or vendor-specific procedures.
Runs identically on any Cypher backend.
"""

import warnings as _warnings
from typing import Any, cast

from pydantic import BaseModel

from orthograph.cypher.base_models import CypherReadQuery
from orthograph.cypher.bindings import (
    CypherQueryData,
    NoParams,
    render_with_identifiers,
)
from orthograph.cypher.identifiers import validate_identifier
from orthograph.graph_profile.models import (
    BareRelTypeIdentifiers,
    BoundedDistribution,
    CardinalityIdentifiers,
    CardinalityStats,
    EndpointLabelsRow,
    PartitionedCardinalityIdentifiers,
    PartitionedCardinalityRow,
    PartitionKey,
)


def coerce_types(raw_types: Any) -> list[str]:
    """Normalise a ``propertyTypes`` value to a list of strings."""
    if isinstance(raw_types, list):
        return raw_types
    return [raw_types] if raw_types else []


class _LabelRelEndpointIdentifiers(BaseModel):
    """The three static splice-once identifiers of a partitioned-cardinality query.

    Carries only ``label`` / ``rel_type`` / ``endpoint_label`` so
    ``render_with_identifiers`` validates each with its correct kind
    (``rel_type`` → relationship type; the rest → label).  The variable-width
    discriminator **property names** are validated and spliced separately (per
    column) inside ``build()`` — they are not ``<<...>>`` slots in the rendered
    template.
    """

    label: str
    rel_type: str  # kind = "relationship type"
    endpoint_label: str


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


def _discriminator_map(
    names: list[str], raw: Any, prefix: str
) -> dict[str, str | None]:
    """Rebuild one endpoint's ``{name: value}`` map from grouped columns.

    ``names`` is the (already validated, deterministically ordered) list of
    discriminator property names for the side; ``prefix`` is ``"sk"`` (source) or
    ``"tk"`` (target).  The i-th name maps to the grouped column ``f"{prefix}{i}"``
    in the raw row, stringified for parity with the NetworkX reference (``None``
    preserved as ``{name: None}`` — discriminator present, observed value null).

    An empty ``names`` list (a wildcard endpoint) yields ``{}`` and reads no
    column — mirroring ADR-032's absolute convention.
    """
    result: dict[str, str | None] = {}
    for index, name in enumerate(names):
        value = raw[f"{prefix}{index}"]
        result[name] = None if value is None else str(value)
    return result


def _materialize_partitioned_row(
    raw: Any, source_names: list[str], target_names: list[str]
) -> PartitionedCardinalityRow:
    """Map a grouped-cardinality raw row to a :class:`PartitionedCardinalityRow`.

    Shared by the source- and target-anchored queries, which differ only in their
    Cypher (which endpoint they anchor on / whose degree they count), not in row
    shape.  The discriminator **names** (``source_names`` / ``target_names``, each
    possibly empty for a wildcard endpoint) come from the identifiers the calling
    query was built with — they are never re-derived here — so the resulting
    name-carrying :class:`PartitionKey` is self-describing.  Each side may carry
    1..N properties (E54); the i-th name pairs with the ``sk{i}`` / ``tk{i}``
    column.  ``stats`` is a :class:`BoundedDistribution` directly (not the
    ``CardinalityStats`` marker): the per-side fields are typed on
    ``BoundedDistribution``, so a subclass value would lose its subtype on reload.
    """
    return PartitionedCardinalityRow(
        key=PartitionKey(
            source=_discriminator_map(source_names, raw, "sk"),
            target=_discriminator_map(target_names, raw, "tk"),
        ),
        stats=BoundedDistribution(
            count=raw["sample_size"],
            min=raw["min_degree"],
            max=raw["max_degree"],
            mean=float(raw["avg_degree"]),
        ),
    )


def _projection(names: list[str], node_var: str, col_prefix: str) -> str:
    """Build the ``WITH``-clause projection for one endpoint's discriminators.

    Each property name is validated through ``validate_identifier`` (property-key
    grammar) and spliced backtick-quoted, so an unsafe name is **rejected** before
    any Cypher is produced — never f-stringed unsafely.  Returns a comma-prefixed
    fragment (``", n.`p0` AS sk0, n.`p1` AS sk1"``) or ``""`` for an empty
    (wildcard) list, which projects no column at all.
    """
    parts: list[str] = []
    for index, name in enumerate(names):
        safe = validate_identifier(name, kind="property key")
        parts.append(f"{node_var}.`{safe}` AS {col_prefix}{index}")
    if not parts:
        return ""
    return ", " + ", ".join(parts)


def _return_columns(source_names: list[str], target_names: list[str]) -> str:
    """Build the ``RETURN``/``GROUP BY`` discriminator column list.

    The grouped ``sk{i}`` / ``tk{i}`` columns (every projected discriminator,
    none for a wildcard side) are carried through into ``RETURN`` so the
    aggregation groups by the full key.  Returns a comma-terminated fragment, or
    ``""`` when both sides are wildcards (which the caller never builds —
    :func:`_extract_discriminators` declines a fully-wildcard rule set).
    """
    cols = [f"sk{i}" for i in range(len(source_names))]
    cols += [f"tk{i}" for i in range(len(target_names))]
    if not cols:
        return ""
    return ", ".join(cols) + ", "


# Imperative build(): the grouped projection is variable-width (1..N
# discriminator columns per side), so the query shape genuinely changes at
# runtime and cannot be a static ``cypher_template``.  The UserWarning the base
# emits for imperative classes is suppressed here intentionally.
with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", UserWarning)

    class InspectSourcePartitionedCardinalityQuery(
        CypherReadQuery[NoParams, PartitionedCardinalityRow]
    ):
        """Per-pair cardinality for the **source side** (variable-width grouping).

        Anchors on the source ``<<label>>`` and counts each source node's
        **outgoing** degree of ``<<rel_type>>`` into a target carrying
        ``<<endpoint_label>>``, grouped by the absolute
        ``(source_discriminators, target_discriminators)`` property maps.  Each
        side carries 1..N property names (E54); an empty side is a wildcard that
        projects no grouped column (the generalisation of the former
        ``null AS sk`` collapse).  The ``<<endpoint_label>>`` filter restricts the
        breakdown to one endpoint shape.

        Every spliced identifier — the three label/rel-type identifiers **and**
        each discriminator property name — passes ``validate_identifier`` before
        substitution; an unsafe identifier is rejected, never injected.

        The symmetric counterpart is :class:`InspectTargetPartitionedCardinalityQuery`.
        """

        Params = NoParams
        Output = PartitionedCardinalityRow
        name = "inspect.partitioned_cardinality.source"
        Identifiers = PartitionedCardinalityIdentifiers

        def build(self, params: NoParams) -> CypherQueryData:
            ident = cast(PartitionedCardinalityIdentifiers, self._identifiers)
            src_proj = _projection(ident.source_discriminators, "n", "sk")
            tgt_proj = _projection(ident.target_discriminators, "m", "tk")
            return_cols = _return_columns(
                ident.source_discriminators, ident.target_discriminators
            )
            template = (
                "MATCH (n:`<<label>>`)"
                " OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->(m:`<<endpoint_label>>`)"
                f" WITH n{src_proj}{tgt_proj}, count(r) AS degree"
                f" RETURN {return_cols}min(degree) AS min_degree,"
                " max(degree) AS max_degree,"
                " avg(degree) AS avg_degree, count(n) AS sample_size"
            )
            # Only the three label/rel-type identifiers remain as <<...>> slots;
            # property names are already validated + spliced above.
            cypher = render_with_identifiers(
                template,
                _LabelRelEndpointIdentifiers(
                    label=ident.label,
                    rel_type=ident.rel_type,
                    endpoint_label=ident.endpoint_label,
                ),
            )
            return CypherQueryData(cypher, {})

        def materialize(self, raw: Any) -> PartitionedCardinalityRow:
            ident = cast(PartitionedCardinalityIdentifiers, self._identifiers)
            return _materialize_partitioned_row(
                raw, ident.source_discriminators, ident.target_discriminators
            )

    class InspectTargetPartitionedCardinalityQuery(
        CypherReadQuery[NoParams, PartitionedCardinalityRow]
    ):
        """Per-pair cardinality for the **target side** (variable-width grouping).

        Symmetric to :class:`InspectSourcePartitionedCardinalityQuery` but anchors
        on the target ``<<label>>`` and counts each target node's **incoming**
        degree of ``<<rel_type>>``, grouped by the same absolute discriminator
        maps.  This is the query a both-endpoint-conditional relationship needs for
        its target side; using the source query there would store source-outgoing
        degree under the target breakdown and diverge from the NetworkX/in-memory
        verdict.

        Identifier safety and the variable-width wildcard handling are identical
        to the source query; only the anchor (``MATCH (m:..)`` / ``count(m)``)
        differs.
        """

        Params = NoParams
        Output = PartitionedCardinalityRow
        name = "inspect.partitioned_cardinality.target"
        Identifiers = PartitionedCardinalityIdentifiers

        def build(self, params: NoParams) -> CypherQueryData:
            ident = cast(PartitionedCardinalityIdentifiers, self._identifiers)
            src_proj = _projection(ident.source_discriminators, "n", "sk")
            tgt_proj = _projection(ident.target_discriminators, "m", "tk")
            return_cols = _return_columns(
                ident.source_discriminators, ident.target_discriminators
            )
            template = (
                "MATCH (m:`<<label>>`)"
                " OPTIONAL MATCH (n:`<<endpoint_label>>`)-[r:`<<rel_type>>`]->(m)"
                f" WITH m{src_proj}{tgt_proj}, count(r) AS degree"
                f" RETURN {return_cols}min(degree) AS min_degree,"
                " max(degree) AS max_degree,"
                " avg(degree) AS avg_degree, count(m) AS sample_size"
            )
            cypher = render_with_identifiers(
                template,
                _LabelRelEndpointIdentifiers(
                    label=ident.label,
                    rel_type=ident.rel_type,
                    endpoint_label=ident.endpoint_label,
                ),
            )
            return CypherQueryData(cypher, {})

        def materialize(self, raw: Any) -> PartitionedCardinalityRow:
            ident = cast(PartitionedCardinalityIdentifiers, self._identifiers)
            return _materialize_partitioned_row(
                raw, ident.source_discriminators, ident.target_discriminators
            )
