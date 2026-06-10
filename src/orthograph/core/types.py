"""Core type definitions for orthograph: cardinality, enums, type introspection."""

import types
import typing
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, model_validator


class CardinalitySpec(BaseModel):
    """Defines min/max bounds for relationship cardinality."""

    model_config = {"frozen": True}

    min: int
    max: int | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "CardinalitySpec":
        if self.min < 0:
            raise ValueError(f"min must be >= 0, got {self.min}")
        if self.max is not None and self.max < self.min:
            raise ValueError(f"max ({self.max}) must be >= min ({self.min}) or None")
        return self

    def contains(self, count: int) -> bool:
        """Check if a count falls within the cardinality bounds."""
        if count < self.min:
            return False
        if self.max is not None and count > self.max:
            return False
        return True

    def __repr__(self) -> str:
        max_str = "N" if self.max is None else str(self.max)
        return f"CardinalitySpec({self.min}..{max_str})"


class Cardinality:
    """Named cardinality constants for relationship constraints.

    Cardinality constrains **how many instances** of a relationship type each
    individual node may have.  It does NOT control whether the relationship
    type exists in the schema -- that is a separate concern handled by
    ``__optional__`` on the ``RelationshipModel``.

    A cardinality of ``ZERO_OR_MORE`` (0..*) means "each node of the source
    (or target) type may have zero or more instances of this relationship".
    Zero is a valid count -- the node simply does not participate.  This is
    semantically distinct from ``ONE_OR_MORE`` (1..*), which requires every
    node to have at least one instance.

    This follows standard data-modelling conventions (UML multiplicity,
    ER crow's-foot notation, OWL cardinality restrictions).
    """

    ZERO_OR_ONE: typing.ClassVar[CardinalitySpec] = CardinalitySpec(min=0, max=1)
    """0..1 -- optional, at most one.  The node may or may not participate."""

    ONE: typing.ClassVar[CardinalitySpec] = CardinalitySpec(min=1, max=1)
    """1..1 -- exactly one.  Every node of this type must have one instance."""

    ZERO_OR_MORE: typing.ClassVar[CardinalitySpec] = CardinalitySpec(min=0, max=None)
    """0..* -- optional, unbounded.  The permissive default: no constraint is
    enforced.  A count of zero is valid (the node simply has no such
    relationship).  This does **not** mean the relationship type is absent
    from the schema; it means individual nodes are not required to use it."""

    ONE_OR_MORE: typing.ClassVar[CardinalitySpec] = CardinalitySpec(min=1, max=None)
    """1..* -- mandatory, unbounded.  Every node must have at least one
    instance of this relationship.  Use this when participation is required
    but there is no upper bound."""


class EntityType(Enum):
    """Discriminator for graph entities."""

    NODE = "node"
    RELATIONSHIP = "relationship"
    QUERY = "query"


class Severity(Enum):
    """Severity level for validation issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class TypeInfo:
    """Resolved type information for a property annotation."""

    python_type: type
    is_required: bool
    default: typing.Any = None


def resolve_type_info(annotation: typing.Any) -> TypeInfo:
    """Extract the concrete type and optionality from a type annotation.

    Handles: str, Optional[str], str | None, list[str], etc.
    """
    origin = typing.get_origin(annotation)

    # Handle Union types (Optional[X] is Union[X, None])
    if origin is typing.Union or origin is types.UnionType:
        args = typing.get_args(annotation)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            return TypeInfo(python_type=non_none_args[0], is_required=False)
        # Multi-type union without None: treat as required, pick first
        return TypeInfo(python_type=non_none_args[0], is_required=True)

    # Handle generic types like list[str], dict[str, int]
    if origin is not None:
        return TypeInfo(python_type=origin, is_required=True)

    # Plain types: str, int, etc.
    if isinstance(annotation, type):
        return TypeInfo(python_type=annotation, is_required=True)

    # Fallback
    return TypeInfo(python_type=type(annotation), is_required=True)
