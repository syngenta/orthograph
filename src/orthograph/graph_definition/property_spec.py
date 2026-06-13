"""Property specification types for graph model introspection."""

import types
import typing
from dataclasses import dataclass


@dataclass(frozen=True)
class TypeInfo:
    """Resolved type information for a single declared property annotation."""

    python_type: type
    """The declared Python type for this property."""
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
