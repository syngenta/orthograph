"""Inspection currency: vendor-free profile and query-support models."""

import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field

from orthograph.graph_definition.identity import RelTypeKey


__all__ = [
    "RelTypeKey",  # re-exported for the observed side
    "BoundedDistribution",
    "CardinalityStats",
    "PartitionKey",
    "PropertyProfile",
    "ConstraintInfo",
    "NodeTypeProfile",
    "RelationshipTypeProfile",
    "GraphProfile",
    "NodeLabelIdentifiers",
    "RelTypeIdentifiers",
    "BareRelTypeIdentifiers",
    "CardinalityIdentifiers",
    "PartitionedCardinalityIdentifiers",
    "EndpointLabelsRow",
    "PartitionedCardinalityRow",
]


class BoundedDistribution(BaseModel):
    """A bounded statistical summary with an honest truncation signal.

    Reused for both property-value distributions and cardinality-degree
    distributions.  ``count`` is the only required field; every moment is
    ``None``-tolerant so a backend may supply as little as ``min``/``max``.
    """

    model_config = {"frozen": True}

    # first moments -- first-class
    count: int = Field(description="Observations summarised by this distribution.")
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    variance: float | None = Field(
        default=None,
        description="``std`` is derivable; ``None`` when the backend can't supply it.",
    )

    # higher moments -- optional, populated only when a backend returns them
    skewness: float | None = None
    kurtosis: float | None = None

    # optional full breakdown (placeholder; populated only when feasible)
    histogram: dict[str, int] | None = Field(
        default=None,
        description="Observed value/degree -> count.  ``None`` when not available.",
    )

    # truncation honesty
    sample_complete: bool = Field(
        default=True,
        description="``False`` when the histogram hit ``limit`` (top-N kept).",
    )
    limit: int | None = Field(
        default=None, description="Configured cap, when one was applied."
    )
    other_count: int = Field(
        default=0, description="Observations beyond the limit (the remainder)."
    )

    @computed_field
    @property
    def std(self) -> float | None:
        """Standard deviation derived from ``variance``; ``None`` when absent."""
        if self.variance is None:
            return None
        return math.sqrt(self.variance)


class CardinalityStats(BoundedDistribution):
    """Observed cardinality statistics for a relationship type.

    A specialisation of :class:`BoundedDistribution`: the degree
    moments map ``min``/``max``/``mean``/``count`` (gaining ``variance``).
    """


class PartitionKey(BaseModel):
    """Name-aware key for a (source-discriminator, target-discriminator) partition.

    Each endpoint carries a ``{property_name: value}`` map, so the partition is
    **self-describing**: ``target={"type": "combine"}`` is interpretable with no
    ``GraphDefinition``.  The maps mirror a ``ConditionalRule``'s
    ``source.conditions`` / ``target.conditions`` ``PropMatch`` maps, so comparison
    matches map-against-map with no name re-derivation.

    - ``{}`` means **that endpoint carries no discriminator** (the wildcard /
      source-label-node case, ADR-032's absolute convention).
    - ``{"type": None}`` means **the discriminator property is present but its
      observed value is null** — distinct from ``{}``.

    Hashable (usable as a ``dict`` key / ``set`` member) despite carrying ``dict``
    fields: :meth:`__hash__` hashes the sorted map items, consistent with the
    field-wise equality of a frozen model.

    ``__str__`` is **display-only** (used by ``visualization/text.py``); it is a
    deterministic, sorted-key form and is **never** a serialisation/dict key.
    Nothing parses it back — there is no ``parse`` method (ADR-039 §2).
    """

    model_config = {"frozen": True}

    source: dict[str, str | None]
    target: dict[str, str | None]

    def __hash__(self) -> int:
        return hash(
            (tuple(sorted(self.source.items())), tuple(sorted(self.target.items())))
        )

    def __str__(self) -> str:
        def _fmt(m: dict[str, str | None]) -> str:
            inner = ", ".join(f"{k}={m[k]}" for k in sorted(m))
            return "{" + inner + "}"

        return f"source={_fmt(self.source)} target={_fmt(self.target)}"


class PartitionedCardinalityRow(BaseModel):
    """One per-pair row of an observed partitioned-cardinality breakdown.

    ``key`` is the name-carrying :class:`PartitionKey` for this partition (the
    self-describing ``{property_name: value}`` maps per endpoint).  ``stats`` is a
    :class:`BoundedDistribution` (the degree distribution of this partition) —
    typed on the base class directly, **not** the ``CardinalityStats`` marker
    subclass, so that round-tripping a list of these rows preserves equality (a
    ``CardinalityStats`` value would be restored as its ``BoundedDistribution``
    base on reload, ADR-039 §3).
    """

    model_config = {"frozen": True}

    key: PartitionKey
    stats: BoundedDistribution


class PropertyProfile(BaseModel):
    """Observed profile of a single property across all entities of one type."""

    model_config = {"frozen": True}

    name: str
    present_count: int = Field(
        description=(
            "Non-null occurrences of this property: a value "
            "explicitly set to ``null`` is *not* present."
        ),
    )
    total_count: int
    constraint_required: bool | None = Field(
        default=None,
        description=(
            "Constraint-derived presence: ``True`` when a DB "
            "presence/existence constraint covers this property, ``False`` when "
            "inspected with none found, ``None`` when constraint info is "
            "unavailable for this backend/strategy."
        ),
    )
    observed_types: list[str] = Field(
        default_factory=list,
        description=(
            "Database-reported type-name strings (e.g. ``'String'``, ``'Long'``)."
        ),
    )
    observed_type_counts: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Mapping of type-name string → observed value count "
            "(e.g. ``{'String': 98, 'Long': 2}``).  Empty when the backend "
            "only yields distinct type names without counts."
        ),
    )
    distinct_count: int | None = Field(
        default=None,
        description="Number of distinct values observed.  ``None`` when not populated.",
    )
    value_distribution: BoundedDistribution | None = Field(
        default=None,
        description=(
            "Bounded value breakdown: ``histogram`` holds "
            "``str(value) → count``; ``sample_complete=False`` when the "
            "distinct-value count exceeded ``limit`` (top-N kept, remainder "
            "in ``other_count``).  ``None`` when the backend does not supply "
            "per-value counts."
        ),
    )

    @computed_field
    @property
    def missing_count(self) -> int:
        return self.total_count - self.present_count

    @computed_field
    @property
    def completeness(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.present_count / self.total_count


class ConstraintInfo(BaseModel):
    """A database constraint."""

    model_config = {"frozen": True}

    name: str | None
    constraint_type: str
    entity_type: str
    labels: list[str]
    properties: list[str]
    property_type: str | None = None


class NodeTypeProfile(BaseModel):
    """Observed profile of a single node label."""

    model_config = {"frozen": True}

    label: str
    count: int
    property_profiles: dict[str, PropertyProfile] = Field(default_factory=dict)


class RelationshipTypeProfile(BaseModel):
    """Observed profile of a single relationship type.

    A relationship type is identified by the triple
    ``(source_label, label, target_label)``, so a profile describes exactly one
    such shape: the endpoints are **scalar**, not blended ``set`` fields.
    ``rel_type`` retains the bare label for display and grouping.
    """

    model_config = {"frozen": True}

    rel_type: str
    count: int
    source_label: str = Field(
        description="The single source node label of this relationship shape."
    )
    target_label: str = Field(
        description="The single target node label of this relationship shape."
    )
    property_profiles: dict[str, PropertyProfile] = Field(default_factory=dict)
    cardinality_stats: CardinalityStats | None = None
    source_partitioned_cardinality: list[PartitionedCardinalityRow] | None = Field(
        default=None,
        description=(
            "Per-pair cardinality breakdown for the **source side** of a "
            "conditional relationship type, as a list of "
            "``PartitionedCardinalityRow`` (``{key, stats}``).  The counted degree "
            "is the source-label node's outgoing degree, grouped by the absolute "
            "``(source_discriminator, target_discriminator)`` partition.  Each "
            "row's ``key`` is a name-carrying :class:`PartitionKey` "
            "(``{property_name: value}`` maps per endpoint), so the partition is "
            "self-describing; ``stats`` is the degree ``BoundedDistribution`` for "
            "that partition.  Store ``BoundedDistribution`` instances directly: the "
            "field is *not* typed on the ``CardinalityStats`` marker subclass, so a "
            "``CardinalityStats`` value would be restored as its "
            "``BoundedDistribution`` base on reload and break round-trip equality.  "
            "``None`` when ``__source_cardinality__`` is not conditional or the "
            "inspector did not compute the breakdown."
        ),
    )
    target_partitioned_cardinality: list[PartitionedCardinalityRow] | None = Field(
        default=None,
        description=(
            "Per-pair cardinality breakdown for the **target side** of a "
            "conditional relationship type, as a list of "
            "``PartitionedCardinalityRow``.  Symmetric to "
            "``source_partitioned_cardinality`` but the counted degree is the "
            "target-label node's incoming degree.  Splitting the two sides into "
            "separate fields prevents a source-counted and a target-counted "
            "partition (which may carry the same :class:`PartitionKey`) from "
            "colliding when a relationship type is conditional on **both** "
            "endpoints.  ``None`` when ``__target_cardinality__`` is not "
            "conditional or the inspector did not compute the breakdown."
        ),
    )


class GraphProfile(BaseModel):
    """Complete structural profile of a graph, produced by inspection."""

    model_config = {"frozen": True}

    source: str
    timestamp: datetime = Field(default_factory=datetime.now)
    node_type_profiles: dict[str, NodeTypeProfile] = Field(default_factory=dict)
    rel_type_profiles: dict[str, RelationshipTypeProfile] = Field(
        default_factory=dict,
        description=(
            "Relationship-type profiles keyed by ``str(RelTypeKey)`` "
            "(``source:LABEL:target``) — relationship identity is the endpoint "
            "triple, so same-label/different-endpoint shapes are "
            "distinct entries."
        ),
    )
    constraints: list[ConstraintInfo] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def node_labels(self) -> set[str]:
        return set(self.node_type_profiles.keys())

    @property
    def relationship_types(self) -> set[str]:
        """The set of ``RelTypeKey`` strings (identity triples) profiled.

        Keys, not bare labels: a label may appear under several endpoint shapes.
        Consumers recover the parts via :meth:`RelTypeKey.parse`.
        """
        return set(self.rel_type_profiles.keys())


# ---------------------------------------------------------------------------
# Vendor-neutral identifier groups for the shared Cypher queries
# ---------------------------------------------------------------------------


class NodeLabelIdentifiers(BaseModel):
    """Identifier group for queries that filter by a single node label."""

    label: str


class RelTypeIdentifiers(BaseModel):
    """Identifier group for queries that filter one relationship *shape*.

    A relationship type is identified by its endpoint triple, so the
    per-shape relationship queries filter on both endpoint labels in addition to
    the bare relationship type.  ``source_label`` / ``target_label`` are spliced
    through ``validate_identifier`` (label grammar) like every other identifier.
    """

    source_label: str  # kind = "label"
    rel_type: str  # name ends in _rel_type -> kind = "relationship type"
    target_label: str  # kind = "label"


class BareRelTypeIdentifiers(BaseModel):
    """Identifier group for queries scoped to a bare relationship type only.

    Used by endpoint-pair **discovery** (``InspectEndpointLabelsQuery``), which
    must match every ``(src)-[:REL]->(tgt)`` instance *before* the endpoint pairs
    are known.  The per-shape scans then use :class:`RelTypeIdentifiers`.
    """

    rel_type: str  # kind = "relationship type"


class CardinalityIdentifiers(BaseModel):
    """Identifier group for the per-shape cardinality query.

    Endpoint-aware: the cardinality scan is anchored on the source
    ``label`` and filtered to edges whose target carries ``target_label``, so the
    degree distribution belongs to exactly one ``(source, rel, target)`` shape.
    """

    label: str
    rel_type: str  # kind = "relationship type"
    target_label: str  # kind = "label"


class PartitionedCardinalityIdentifiers(BaseModel):
    """Identifier group for the grouped (per-pair) cardinality query.

    ``source_discriminators`` / ``target_discriminators`` are **lists** of
    property names (e.g. ``["kind", "tier"]``) — one per endpoint, of any width
    (E54: a multi-property ``PropMatch`` discriminates on N properties).  Each
    name is spliced via the ``<<...>>`` mechanism through ``validate_identifier``
    (validate-and-reject) — never f-stringed or string-joined into the template.

    An **empty** list means that endpoint is a wildcard: it projects no grouped
    column (no read of a non-existent property) and reconstructs to the empty
    map ``{}`` (ADR-032's absolute convention).  This subsumes the former
    separate ``WildcardPartitionedCardinalityIdentifiers`` group.

    Endpoint-aware: ``endpoint_label`` filters the *other* endpoint of
    the relationship to the discovered shape (the anchored side is ``label``), so
    the breakdown belongs to one ``(source, rel, target)`` shape rather than a
    bare label blended across endpoint pairs.
    """

    label: str
    rel_type: str  # kind = "relationship type"
    endpoint_label: str  # the non-anchored endpoint label (kind = "label")
    source_discriminators: list[str]  # source property names (may be empty)
    target_discriminators: list[str]  # target property names (may be empty)


# ---------------------------------------------------------------------------
# Vendor-neutral output / projection models for the shared Cypher queries
# ---------------------------------------------------------------------------


class EndpointLabelsRow(BaseModel):
    """Source and target label lists for a single relationship instance."""

    source_labels: list[str]
    target_labels: list[str]
