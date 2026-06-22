"""Cross-reference flat constraints onto individual properties (ADR-034 §4).

A :class:`~orthograph.graph_profile.models.GraphProfile` carries constraints in a
flat list.  Comparison needs to ask, per property, *"is this property's presence
guaranteed by a database constraint?"*.  This module answers that question in a
vendor-free way so every inspector links constraints onto ``PropertyProfile``
identically (ADR-009 parity).

Only constraints that *guarantee presence* count: existence/presence constraints
and key constraints (a key implies the keyed properties exist).  A uniqueness
constraint alone does **not** guarantee presence and is therefore excluded.
"""

from collections.abc import Iterable

from orthograph.graph_profile.models import ConstraintInfo


# Constraint-type strings (across Neo4j and Memgraph) that guarantee a property
# is present on every entity it covers.  Matched case-insensitively.
_PRESENCE_CONSTRAINT_TYPES: frozenset[str] = frozenset(
    {
        # Neo4j
        "NODE_PROPERTY_EXISTENCE",
        "RELATIONSHIP_PROPERTY_EXISTENCE",
        "NODE_KEY",
        "RELATIONSHIP_KEY",
        # Memgraph
        "EXISTS",
    }
)


def _guarantees_presence(constraint_type: str) -> bool:
    return constraint_type.upper() in _PRESENCE_CONSTRAINT_TYPES


def is_presence_constraint_for(
    constraints: Iterable[ConstraintInfo],
    entity_type: str,
    label: str,
    property_name: str,
) -> bool:
    """Return ``True`` if a presence-guaranteeing constraint covers the property.

    A constraint covers ``(label, property_name)`` when it guarantees presence
    (existence/key — see :data:`_PRESENCE_CONSTRAINT_TYPES`), targets the same
    entity kind, lists ``label`` among its labels, and lists ``property_name``
    among its properties.  Entity-type comparison is case-insensitive.
    """
    for constraint in constraints:
        if not _guarantees_presence(constraint.constraint_type):
            continue
        if constraint.entity_type.upper() != entity_type.upper():
            continue
        if label not in constraint.labels:
            continue
        if property_name in constraint.properties:
            return True
    return False
