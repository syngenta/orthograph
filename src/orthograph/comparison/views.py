"""GraphView Protocol and adapters for the comparison engine.

A :class:`GraphView` projects one comparison operand onto the shared address
space (node labels, relationship types, property dicts).  The engine walks two
views without knowing whether each side is a definition or a profile.

Two concrete adapters are provided:

- :class:`DefinitionView` — wraps a
  :class:`~orthograph.graph_definition.graph_definition.GraphDefinition`.
- :class:`ProfileView` — wraps a
  :class:`~orthograph.graph_profile.models.GraphProfile`.
"""

from typing import Any, Protocol, runtime_checkable

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.identity import RelTypeKey
from orthograph.graph_definition.property_spec import TypeInfo
from orthograph.graph_profile.models import GraphProfile


class _HasPropertySpecs(Protocol):
    """Protocol for model types that expose ``get_property_specs()``."""

    @classmethod
    def get_property_specs(cls) -> dict[str, TypeInfo]: ...


@runtime_checkable
class GraphView(Protocol):
    """A read-only projection of one comparison operand
    onto the shared address space."""

    def node_labels(self) -> set[str]: ...

    def relationship_types(self) -> set[str]:
        """The set of relationship-type identity keys (``str(RelTypeKey)``).

        The relationship address space is keyed by the
        ``(source, label, target)`` identity triple, not the bare label.
        """
        ...

    def node_at(self, label: str) -> Any | None:
        """Side-object for a node-label address
        (e.g. a NodeModel subclass or NodeTypeProfile)."""
        ...

    def relationship_at(self, rel_key: str) -> Any | None:
        """Side-object for a rel-type address keyed by ``str(RelTypeKey)``
        (e.g. a RelationshipModel subclass or RelationshipTypeProfile)."""
        ...

    def node_properties(self, label: str) -> dict[str, Any]:
        """Mapping of prop_name → side-object for
        all properties of the given node label."""
        ...

    def relationship_properties(self, rel_key: str) -> dict[str, Any]:
        """Mapping of prop_name → side-object for all properties of the rel
        type identified by ``str(RelTypeKey)``."""
        ...


class DefinitionView:
    """Projects a :class:`~orthograph.graph_definition.graph_definition.GraphDefinition`
    onto the :class:`GraphView` address space."""

    def __init__(self, graph_definition: GraphDefinition) -> None:
        self._gd = graph_definition

    def node_labels(self) -> set[str]:
        return self._gd.node_labels

    def relationship_types(self) -> set[str]:
        return self._gd.relationship_keys

    def node_at(self, label: str) -> Any | None:
        return self._gd.get_node_type(label)

    def relationship_at(self, rel_key: str) -> Any | None:
        key = RelTypeKey.parse(rel_key)
        return self._gd.get_relationship_type(
            key.source_label, key.label, key.target_label
        )

    def node_properties(self, label: str) -> dict[str, Any]:
        model_type = self._gd.get_node_type(label)
        if model_type is None:
            return {}
        return model_type.get_property_specs()

    def relationship_properties(self, rel_key: str) -> dict[str, Any]:
        key = RelTypeKey.parse(rel_key)
        model_type = self._gd.get_relationship_type(
            key.source_label, key.label, key.target_label
        )
        if model_type is None:
            return {}
        return model_type.get_property_specs()


class ProfileView:
    """Projects a :class:`~orthograph.graph_profile.models.GraphProfile`
    onto the :class:`GraphView` address space."""

    def __init__(self, profile: GraphProfile) -> None:
        self._profile = profile

    def node_labels(self) -> set[str]:
        return self._profile.node_labels

    def relationship_types(self) -> set[str]:
        return self._profile.relationship_types

    def node_at(self, label: str) -> Any | None:
        return self._profile.node_type_profiles.get(label)

    def relationship_at(self, rel_key: str) -> Any | None:
        return self._profile.rel_type_profiles.get(rel_key)

    def node_properties(self, label: str) -> dict[str, Any]:
        node_profile = self._profile.node_type_profiles.get(label)
        if node_profile is None:
            return {}
        return node_profile.property_profiles

    def relationship_properties(self, rel_key: str) -> dict[str, Any]:
        rel_profile = self._profile.rel_type_profiles.get(rel_key)
        if rel_profile is None:
            return {}
        return rel_profile.property_profiles
