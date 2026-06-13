"""NetworkX graph inspector producing a GraphProfile (stateless)."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

import networkx as nx

from orthograph.graph_profile.inspection import GraphInspector
from orthograph.graph_profile.models import (
    CardinalityStats,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)


logger = logging.getLogger(__name__)


class NetworkxInspector(GraphInspector):
    """Inspects a NetworkX MultiDiGraph and produces a structural profile.

    Stateless: the graph is passed to :meth:`inspect` per call, never stored.
    """

    def inspect(self, connection: nx.MultiDiGraph[str]) -> GraphProfile:
        """Inspect the graph and return a frozen :class:`GraphProfile`."""
        node_type_profiles = self._inspect_nodes(connection)
        rel_type_profiles = self._inspect_relationships(connection, node_type_profiles)
        return GraphProfile(
            source="networkx",
            timestamp=datetime.now(),
            node_type_profiles=node_type_profiles,
            rel_type_profiles=rel_type_profiles,
        )

    def _inspect_nodes(self, graph: nx.MultiDiGraph[str]) -> dict[str, NodeTypeProfile]:
        """Group nodes by __label__ and compute property profiles."""
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for _, attrs in graph.nodes(data=True):
            label = attrs.get("__label__")
            if label is None:
                logger.warning("Node without __label__ attribute skipped: %s", attrs)
                continue
            groups[label].append(dict(attrs))

        profiles: dict[str, NodeTypeProfile] = {}
        for label, nodes in sorted(groups.items()):
            prop_profiles = _compute_property_profiles(nodes)
            profiles[label] = NodeTypeProfile(
                label=label,
                count=len(nodes),
                property_profiles=prop_profiles,
            )
        return profiles

    def _inspect_relationships(
        self,
        graph: nx.MultiDiGraph[str],
        node_profiles: dict[str, NodeTypeProfile],
    ) -> dict[str, RelationshipTypeProfile]:
        """Group edges by __label__ and compute property/cardinality profiles."""
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        source_labels: dict[str, set[str]] = defaultdict(set)
        target_labels: dict[str, set[str]] = defaultdict(set)
        # Track outgoing degree per (rel_type, source_node)
        outgoing: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for src, tgt, attrs in graph.edges(data=True):
            label = attrs.get("__label__")
            if label is None:
                logger.warning(
                    "Edge without __label__ attribute skipped: %s -> %s", src, tgt
                )
                continue

            groups[label].append(dict(attrs))

            # Resolve node labels from the graph
            src_attrs = graph.nodes.get(src, {})
            tgt_attrs = graph.nodes.get(tgt, {})
            src_label = src_attrs.get("__label__")
            tgt_label = tgt_attrs.get("__label__")
            if src_label:
                source_labels[label].add(src_label)
            if tgt_label:
                target_labels[label].add(tgt_label)

            outgoing[label][src] += 1

        profiles: dict[str, RelationshipTypeProfile] = {}
        for label, edges in sorted(groups.items()):
            prop_profiles = _compute_property_profiles(edges)
            cardinality = _compute_cardinality(outgoing.get(label, {}))
            profiles[label] = RelationshipTypeProfile(
                rel_type=label,
                count=len(edges),
                source_labels=source_labels.get(label, set()),
                target_labels=target_labels.get(label, set()),
                property_profiles=prop_profiles,
                cardinality_stats=cardinality,
            )
        return profiles


def _compute_property_profiles(
    entities: list[dict[str, Any]],
) -> dict[str, PropertyProfile]:
    """Compute property profiles from a list of entity attribute dicts."""
    total = len(entities)
    if total == 0:
        return {}

    # Collect all property keys (excluding __label__)
    all_keys: set[str] = set()
    for entity in entities:
        all_keys.update(k for k in entity if k != "__label__")

    profiles: dict[str, PropertyProfile] = {}
    for key in sorted(all_keys):
        present_count = 0
        observed_types: set[str] = set()
        for entity in entities:
            if key in entity:
                present_count += 1
                observed_types.add(type(entity[key]).__name__)
        profiles[key] = PropertyProfile(
            name=key,
            present_count=present_count,
            total_count=total,
            observed_types=sorted(observed_types),
        )
    return profiles


def _compute_cardinality(degree_map: dict[str, int]) -> CardinalityStats | None:
    """Compute cardinality stats from a mapping of source_node -> degree."""
    if not degree_map:
        return None
    degrees = list(degree_map.values())
    return CardinalityStats(
        min_degree=min(degrees),
        max_degree=max(degrees),
        avg_degree=sum(degrees) / len(degrees),
        sample_size=len(degrees),
    )
