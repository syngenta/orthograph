"""Inspection currency: vendor-free profile and query-support models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field


class PropertyProfile(BaseModel):
    """Observed profile of a single property across all entities of one type."""

    model_config = {"frozen": True}

    name: str
    present_count: int
    total_count: int
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

    @computed_field
    @property
    def is_required(self) -> bool:
        """``True`` when present on every observed entity
        (``present_count == total_count > 0``)."""
        return 0 < self.total_count == self.present_count


class CardinalityStats(BaseModel):
    """Observed cardinality statistics for a relationship type."""

    model_config = {"frozen": True}

    min_degree: int
    max_degree: int
    avg_degree: float
    sample_size: int


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


# ---------------------------------------------------------------------------
# Vendor-neutral output / projection models for the shared Cypher queries
# ---------------------------------------------------------------------------


class EndpointLabelsRow(BaseModel):
    """Source and target label lists for a single relationship instance."""

    source_labels: list[str]
    target_labels: list[str]
