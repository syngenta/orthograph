"""Inspection currency: vendor-free profile and query-support models."""

import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field


class BoundedDistribution(BaseModel):
    """A bounded statistical summary with an honest truncation signal (ADR-034 §3).

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

    A specialisation of :class:`BoundedDistribution` (ADR-034 §3): the degree
    moments map ``min``/``max``/``mean``/``count`` (gaining ``variance``).
    """


class PartitionKey(BaseModel):
    """Serialisable key for a (source-discriminator, target-discriminator) partition.

    ``None`` encodes the null/absent-edge partition (no edge of this type
    observed for that discriminator value).  ``__str__`` is deterministic and
    stable so that ``str(key)`` is a safe ``dict`` / JSON key.

    Encoding: ``"src=<value>|tgt=<value>"`` where ``None`` is the literal
    ``"null"`` (lower-case).  Values that already contain ``|`` or ``=`` are
    embedded verbatim; consumers must reconstruct via the model fields, not
    by parsing the string.
    """

    model_config = {"frozen": True}

    source_value: str | None
    target_value: str | None

    def __str__(self) -> str:
        src = "null" if self.source_value is None else self.source_value
        tgt = "null" if self.target_value is None else self.target_value
        return f"src={src}|tgt={tgt}"


class PropertyProfile(BaseModel):
    """Observed profile of a single property across all entities of one type."""

    model_config = {"frozen": True}

    name: str
    present_count: int = Field(
        description=(
            "Non-null occurrences of this property (ADR-034 §5): a value "
            "explicitly set to ``null`` is *not* present."
        ),
    )
    total_count: int
    constraint_required: bool | None = Field(
        default=None,
        description=(
            "Constraint-derived presence (ADR-034 §4): ``True`` when a DB "
            "presence/existence constraint covers this property, ``False`` when "
            "inspected with none found, ``None`` when constraint info is "
            "unavailable for this backend/strategy (ADR-033)."
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
            "Bounded value breakdown (ADR-034 §3/§4): ``histogram`` holds "
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
    """Observed profile of a single relationship type."""

    model_config = {"frozen": True}

    rel_type: str
    count: int
    source_labels: set[str] = Field(default_factory=set)
    target_labels: set[str] = Field(default_factory=set)
    property_profiles: dict[str, PropertyProfile] = Field(default_factory=dict)
    cardinality_stats: CardinalityStats | None = None
    source_partitioned_cardinality: dict[str, BoundedDistribution] | None = Field(
        default=None,
        description=(
            "Per-pair cardinality breakdown for the **source side** of a "
            "conditional relationship type (E41/ADR-034).  The counted degree is "
            "the source-label node's outgoing degree, grouped by the absolute "
            "``(source_discriminator, target_discriminator)`` partition.  Key = "
            "``str(PartitionKey)`` (``src=<v>|tgt=<v>``); value = "
            "``BoundedDistribution`` (the degree distribution of that partition).  "
            "Store ``BoundedDistribution`` instances directly: the field is *not* "
            "typed on the ``CardinalityStats`` marker subclass, so a "
            "``CardinalityStats`` value would be restored as its "
            "``BoundedDistribution`` base on reload and break round-trip equality.  "
            "``None`` when ``__source_cardinality__`` is not conditional or the "
            "inspector did not compute the breakdown."
        ),
    )
    target_partitioned_cardinality: dict[str, BoundedDistribution] | None = Field(
        default=None,
        description=(
            "Per-pair cardinality breakdown for the **target side** of a "
            "conditional relationship type (E41.7/ADR-032).  Symmetric to "
            "``source_partitioned_cardinality`` but the counted degree is the "
            "target-label node's incoming degree; the partition key still reads "
            "the source discriminator first and the target discriminator second "
            "(absolute convention, ADR-032 §1a).  Splitting the two sides into "
            "separate fields prevents a source-counted and a target-counted "
            "partition from colliding on the same ``str(PartitionKey)`` when a "
            "relationship type is conditional on **both** endpoints.  ``None`` "
            "when ``__target_cardinality__`` is not conditional or the inspector "
            "did not compute the breakdown."
        ),
    )


class GraphProfile(BaseModel):
    """Complete structural profile of a graph, produced by inspection."""

    model_config = {"frozen": True}

    source: str
    timestamp: datetime = Field(default_factory=datetime.now)
    node_type_profiles: dict[str, NodeTypeProfile] = Field(default_factory=dict)
    rel_type_profiles: dict[str, RelationshipTypeProfile] = Field(default_factory=dict)
    constraints: list[ConstraintInfo] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def node_labels(self) -> set[str]:
        return set(self.node_type_profiles.keys())

    @property
    def relationship_types(self) -> set[str]:
        return set(self.rel_type_profiles.keys())


# ---------------------------------------------------------------------------
# Vendor-neutral identifier groups for the shared Cypher queries
# ---------------------------------------------------------------------------


class NodeLabelIdentifiers(BaseModel):
    """Identifier group for queries that filter by a single node label."""

    label: str


class RelTypeIdentifiers(BaseModel):
    """Identifier group for queries that filter by a single relationship type."""

    rel_type: str  # name ends in _rel_type -> kind = "relationship type"


class CardinalityIdentifiers(BaseModel):
    """Identifier group for the cardinality query (label + rel_type)."""

    label: str
    rel_type: str  # kind = "relationship type"


class PartitionedCardinalityIdentifiers(BaseModel):
    """Identifier group for the grouped (per-pair) cardinality query (E41.3).

    ``source_discriminator`` and ``target_discriminator`` are **property names**
    (e.g. ``"kind"``); like every spliced identifier they pass through
    ``validate_identifier`` (ADR-008, validate-and-reject) — never f-stringed.
    """

    label: str
    rel_type: str  # kind = "relationship type"
    source_discriminator: str  # property name (kind = "label" grammar)
    target_discriminator: str  # property name (kind = "label" grammar)


# ---------------------------------------------------------------------------
# Vendor-neutral output / projection models for the shared Cypher queries
# ---------------------------------------------------------------------------


class EndpointLabelsRow(BaseModel):
    """Source and target label lists for a single relationship instance."""

    source_labels: list[str]
    target_labels: list[str]


class PartitionedCardinalityRow(BaseModel):
    """One per-pair row of the grouped cardinality query (E41.3).

    ``source_value`` / ``target_value`` are the source/target discriminator
    values for this partition; ``None`` encodes the null/absent-edge partition
    (the database returned ``null`` for that discriminator).  ``stats`` is a
    :class:`BoundedDistribution` (the degree distribution of this partition) —
    constructed as the base class directly, **not** the ``CardinalityStats``
    marker subclass, so that round-tripping ``partitioned_cardinality`` (which is
    typed on ``BoundedDistribution``) preserves the exact type (E41.1).
    """

    source_value: str | None
    target_value: str | None
    stats: BoundedDistribution
