"""Generate GQLAlchemy Node/Relationship classes from an Orthograph model.

Translates Pydantic v2 model definitions to GQLAlchemy-compatible Pydantic v1
classes at runtime.  Generated classes are internal; consumers never use them directly.
"""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass, field
from typing import Any, Optional, get_type_hints

from orthograph.dependencies import require
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.graph_definition.property_spec import TypeInfo


require("gqlalchemy")

from gqlalchemy import Node as GqaNode  # noqa: E402
from gqlalchemy import Relationship as GqaRelationship  # noqa: E402


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GqlAlchemySchema:
    """Generated GQLAlchemy classes indexed by label/type."""

    node_classes: dict[str, type[GqaNode]] = field(default_factory=dict)
    rel_classes: dict[str, type[GqaRelationship]] = field(default_factory=dict)

    def get_node_class(self, label: str) -> type[GqaNode]:
        """Return the generated GQLAlchemy Node class for ``label``.

        Raises
        ------
        KeyError
            If ``label`` is not in the schema.
        """
        try:
            return self.node_classes[label]
        except KeyError:
            raise KeyError(
                f"Unknown node label '{label}'. "
                f"Available: {sorted(self.node_classes.keys())}"
            ) from None

    def get_rel_class(self, rel_type: str) -> type[GqaRelationship]:
        """Return the generated GQLAlchemy Relationship class for ``rel_type``.

        Raises
        ------
        KeyError
            If ``rel_type`` is not in the schema.
        """
        try:
            return self.rel_classes[rel_type]
        except KeyError:
            raise KeyError(
                f"Unknown relationship type '{rel_type}'. "
                f"Available: {sorted(self.rel_classes.keys())}"
            ) from None


def generate_gqlalchemy_classes(
    graph_definition: GraphDefinition,
) -> GqlAlchemySchema:
    """Generate GQLAlchemy Node/Relationship classes from ``graph_definition``."""
    node_classes: dict[str, type[GqaNode]] = {}
    for node_type in graph_definition.node_types:
        cls = _build_node_class(node_type)
        node_classes[node_type.__label__] = cls

    rel_classes: dict[str, type[GqaRelationship]] = {}
    for rel_type in graph_definition.relationship_types:
        cls = _build_rel_class(rel_type)
        rel_classes[rel_type.__label__] = cls

    return GqlAlchemySchema(
        node_classes=node_classes,
        rel_classes=rel_classes,
    )


# ---------------------------------------------------------------------------
# Internal: class builders
# ---------------------------------------------------------------------------


def _build_node_class(node_type: type[NodeModel]) -> type[GqaNode]:
    """Create a GQLAlchemy Node subclass from an Orthograph NodeModel."""
    label = node_type.__label__
    annotations, defaults = _extract_fields(node_type)
    class_name = f"_Gqa_{label}_Node"

    namespace: dict[str, Any] = {
        "__annotations__": annotations,
        **defaults,
    }

    # Use the label= kwarg to set GQLAlchemy's label via its metaclass
    cls = type(class_name, (GqaNode,), namespace)
    setattr(cls, "label", label)
    setattr(cls, "labels", {label})

    return cls


def _build_rel_class(
    rel_type: type[RelationshipModel],
) -> type[GqaRelationship]:
    """Create a GQLAlchemy Relationship subclass from an Orthograph model."""
    rel_label = rel_type.__label__
    annotations, defaults = _extract_fields(rel_type)
    class_name = f"_Gqa_{rel_label}_Rel"

    namespace: dict[str, Any] = {
        "__annotations__": annotations,
        **defaults,
    }

    cls = type(class_name, (GqaRelationship,), namespace)
    setattr(cls, "type", rel_label)

    return cls


# ---------------------------------------------------------------------------
# Internal: field extraction and type translation
# ---------------------------------------------------------------------------


def _extract_fields(
    model_cls: type[NodeModel] | type[RelationshipModel],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(annotations, defaults)`` suitable for a dynamic ``type()`` call."""
    specs = model_cls.get_property_specs()
    annotations: dict[str, Any] = {}
    defaults: dict[str, Any] = {}

    # Use get_type_hints for the raw annotations (preserves Optional etc.)
    raw_hints = get_type_hints(model_cls)

    for name, info in specs.items():
        # Translate the type for Pydantic v1 compatibility
        translated_type = _translate_type(info, raw_hints.get(name))
        annotations[name] = translated_type

        if not info.is_required:
            defaults[name] = info.default
        # Required fields: no default (Pydantic v1 treats missing default
        # as required via the Ellipsis sentinel)
        else:
            defaults[name] = ...

    return annotations, defaults


def _translate_type(info: TypeInfo, raw_annotation: Any) -> Any:
    """Translate a Pydantic v2 annotation to a Pydantic v1-compatible one.

    Generic types (``list[str]``, ``dict[str, Any]``) are simplified to their
    origin (``list``, ``dict``) for v1 compatibility.  ``Optional[T]`` and plain
    types pass through unchanged.
    """
    # If we have the raw annotation, use it directly for simple cases.
    # This preserves Optional[str] as-is.
    if raw_annotation is not None:
        origin = getattr(raw_annotation, "__origin__", None)

        # Optional[X] in Python is Union[X, None] -- preserve as-is
        if _is_optional(raw_annotation):
            return Optional[info.python_type]

        # Generic types like list[str] -> list (simplified for v1)
        if origin is not None:
            return origin

        # Plain types pass through
        return raw_annotation

    # Fallback: reconstruct from TypeInfo
    if not info.is_required:
        return Optional[info.python_type]
    return info.python_type


def _is_optional(annotation: Any) -> bool:
    """Check if an annotation is Optional[T] (i.e., Union[T, None])."""
    origin = getattr(annotation, "__origin__", None)

    if isinstance(annotation, types.UnionType):
        return type(None) in annotation.__args__

    if origin is typing.Union:
        return type(None) in annotation.__args__

    return False
