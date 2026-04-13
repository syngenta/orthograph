"""Shared data classes for database schema introspection."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PropertyInfo:
    """A property observed in the database."""

    name: str
    types: list[str]
    mandatory: bool
    observation_count: int
    total_count: int


@dataclass(frozen=True)
class ConstraintInfo:
    """A constraint in the database."""

    name: str | None
    constraint_type: str
    entity_type: str
    labels: list[str]
    properties: list[str]
    property_type: str | None = None


@dataclass(frozen=True)
class CardinalityStats:
    """Observed cardinality statistics for a relationship type."""

    min_degree: int
    max_degree: int
    avg_degree: float


@dataclass
class IntrospectedSchema:
    """Database schema as extracted from introspection queries."""

    node_labels: set[str] = field(default_factory=set)
    relationship_types: set[str] = field(default_factory=set)
    node_properties: dict[str, list[PropertyInfo]] = field(default_factory=dict)
    rel_properties: dict[str, list[PropertyInfo]] = field(default_factory=dict)
    constraints: list[ConstraintInfo] = field(default_factory=list)
    node_counts: dict[str, int] = field(default_factory=dict)
    cardinality_stats: dict[tuple[str, str, str], CardinalityStats] = field(
        default_factory=dict
    )
