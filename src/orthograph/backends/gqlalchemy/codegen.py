"""Generate GQLAlchemy Node/Relationship classes from an Orthograph model.

Translates Pydantic v2 model definitions to GQLAlchemy-compatible classes at
runtime.  Generated classes are internal; consumers never use them directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, get_type_hints

from orthograph.dependencies import require
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel


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
# Internal: field extraction
# ---------------------------------------------------------------------------


def _extract_fields(
    model_cls: type[NodeModel] | type[RelationshipModel],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(annotations, defaults)`` suitable for a dynamic ``type()`` call.

    Annotations are taken verbatim from ``get_type_hints`` so that generic types
    (``list[str]``, ``dict[str, Any]``, ``Optional[str]``) are preserved as-is.
    Pydantic v2 handles all of these natively.

    Defaults follow the standard Pydantic convention: ``...`` (Ellipsis) for
    required fields, the literal default value for optional ones.
    """
    specs = model_cls.get_property_specs()
    annotations: dict[str, Any] = {}
    defaults: dict[str, Any] = {}

    raw_hints = get_type_hints(model_cls)

    for name, info in specs.items():
        annotations[name] = raw_hints.get(name, info.python_type)
        defaults[name] = ... if info.is_required else info.default

    return annotations, defaults
