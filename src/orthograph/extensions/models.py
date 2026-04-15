"""Shared data models for graph inspection profiles."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field


class PropertyProfile(BaseModel):
    """Profile of a single property across all entities of a type."""

    model_config = {"frozen": True}

    name: str
    present_count: int
    total_count: int
    observed_types: list[str] = Field(default_factory=list)

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
    def is_mandatory(self) -> bool:
        return self.total_count > 0 and self.present_count == self.total_count


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
    """Profile of a single node type (label)."""

    model_config = {"frozen": True}

    label: str
    count: int
    property_profiles: dict[str, PropertyProfile] = Field(default_factory=dict)


class RelationshipTypeProfile(BaseModel):
    """Profile of a single relationship type."""

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
