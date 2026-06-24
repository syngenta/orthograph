"""NetworkX graph inspector producing a GraphProfile (stateless)."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import networkx as nx

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    ConditionalCardinality,
    RelationshipModel,
)
from orthograph.graph_profile.inspection import GraphInspector
from orthograph.graph_profile.models import (
    BoundedDistribution,
    CardinalityStats,
    GraphProfile,
    NodeTypeProfile,
    PartitionKey,
    PropertyProfile,
    RelationshipTypeProfile,
    RelTypeKey,
)


logger = logging.getLogger(__name__)

# Default maximum distinct values kept in value_distribution.histogram.
# Set to None or 0 to disable value_distribution entirely.
VALUE_COUNTS_TOP_N: int = 10


class NetworkxInspector(GraphInspector):
    """Inspects a NetworkX MultiDiGraph and produces a structural profile.

    Stateless: the graph is passed to :meth:`inspect` per call, never stored.

    Parameters
    ----------
    value_counts_top_n:
        Maximum number of distinct values to retain in
        :attr:`~orthograph.graph_profile.models.PropertyProfile.value_distribution`.
        ``None`` or ``0`` disables the distribution entirely.  Defaults to
        :data:`VALUE_COUNTS_TOP_N`.
    """

    def __init__(self, value_counts_top_n: int | None = VALUE_COUNTS_TOP_N) -> None:
        self._value_counts_top_n = value_counts_top_n

    def inspect(
        self,
        connection: nx.MultiDiGraph[str],
        *,
        graph_definition: GraphDefinition | None = None,
    ) -> GraphProfile:
        """Inspect the graph and return a frozen :class:`GraphProfile`.

        When ``graph_definition`` is supplied, relationship types whose declared
        side is a :class:`ConditionalCardinality` additionally receive a per-pair
        breakdown grouped by the endpoints' discriminator values,
        in ``source_partitioned_cardinality`` and/or ``target_partitioned_cardinality`` —
        a type conditional on **both** endpoints carries both.  Without a definition
        the breakdowns are left ``None`` (comparison then reports
        ``CARDINALITY_UNVERIFIABLE``) — an additive keyword keeps existing
        single-argument callers working.
        """  # NOQA E501
        node_type_profiles = self._inspect_nodes(connection)
        rel_type_profiles = self._inspect_relationships(
            connection, node_type_profiles, graph_definition
        )
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
            prop_profiles = _compute_property_profiles(nodes, self._value_counts_top_n)
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
        graph_definition: GraphDefinition | None = None,
    ) -> dict[str, RelationshipTypeProfile]:
        """Group edges by the identity triple ``(source, label, target)``.

        Relationship identity is the endpoint triple, so two edges
        sharing a label but differing in either endpoint label form **distinct**
        profiles; their ``count`` / ``cardinality_stats`` / ``property_profiles``
        are never blended.  Each group is keyed by ``str(RelTypeKey)``.  An edge
        whose source or target node carries no ``__label__`` cannot form a valid
        identity triple and is skipped with a warning (mirroring the
        missing-edge-label skip).
        """
        groups: dict[RelTypeKey, list[dict[str, Any]]] = defaultdict(list)
        # Track outgoing degree per (triple, source_node)
        outgoing: dict[RelTypeKey, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        # Endpoint records per triple for the conditional per-pair breakdown:
        # (src_node, tgt_node, src_attrs, tgt_attrs).  Collected for every edge;
        # only consumed for relationship types with a conditional declared side.
        endpoints: dict[RelTypeKey, list[_EdgeEndpoints]] = defaultdict(list)

        for src, tgt, attrs in graph.edges(data=True):
            label = attrs.get("__label__")
            if label is None:
                logger.warning(
                    "Edge without __label__ attribute skipped: %s -> %s", src, tgt
                )
                continue

            # Resolve endpoint node labels — both are part of identity.
            src_attrs = graph.nodes.get(src, {})
            tgt_attrs = graph.nodes.get(tgt, {})
            src_label = src_attrs.get("__label__")
            tgt_label = tgt_attrs.get("__label__")
            if not src_label or not tgt_label:
                logger.warning(
                    "Edge %s -[%s]-> %s skipped: endpoint without __label__ "
                    "cannot form a relationship identity triple",
                    src,
                    label,
                    tgt,
                )
                continue

            key = RelTypeKey(
                source_label=src_label, label=label, target_label=tgt_label
            )
            groups[key].append(dict(attrs))
            outgoing[key][src] += 1
            endpoints[key].append(
                _EdgeEndpoints(src, tgt, dict(src_attrs), dict(tgt_attrs))
            )

        profiles: dict[str, RelationshipTypeProfile] = {}
        for key, edges in sorted(groups.items(), key=lambda kv: str(kv[0])):
            prop_profiles = _compute_property_profiles(edges, self._value_counts_top_n)
            cardinality = _compute_cardinality(outgoing.get(key, {}))
            source_partitioned, target_partitioned = _compute_partitioned_cardinality(
                key, endpoints.get(key, []), graph_definition
            )
            profiles[str(key)] = RelationshipTypeProfile(
                rel_type=key.label,
                count=len(edges),
                source_label=key.source_label,
                target_label=key.target_label,
                property_profiles=prop_profiles,
                cardinality_stats=cardinality,
                source_partitioned_cardinality=source_partitioned,
                target_partitioned_cardinality=target_partitioned,
            )
        return profiles


def _compute_property_profiles(
    entities: list[dict[str, Any]],
    value_counts_top_n: int | None,
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
        value_counts: Counter[str] = Counter()
        # observed_type_counts is gated on the same value-scan opt-in as the
        # histogram: a single knob, so when counts are populated
        # value_distribution is too and the reconciliation invariant
        # (sum(type_counts) == value_distribution.count == present_count) holds.
        type_counts: Counter[str] = Counter()
        for entity in entities:
            if key in entity and entity[key] is not None:
                # an explicit ``null`` is *not* present.
                present_count += 1
                type_name = type(entity[key]).__name__
                observed_types.add(type_name)
                if value_counts_top_n:
                    value_counts[str(entity[key])] += 1
                    # Type counts reuse the observed_types vocabulary
                    # (type(value).__name__) and are exact
                    # (grouped by type, never truncated ).
                    type_counts[type_name] += 1
        profiles[key] = PropertyProfile(
            name=key,
            present_count=present_count,
            total_count=total,
            observed_types=sorted(observed_types),
            observed_type_counts=dict(type_counts),
            value_distribution=_build_value_distribution(
                value_counts, present_count, value_counts_top_n
            ),
            # NetworkX carries no DB constraints -> constraint_required stays None.
        )
    return profiles


def _build_value_distribution(
    value_counts: Counter[str],
    present_count: int,
    top_n: int | None,
) -> BoundedDistribution | None:
    """Build a BoundedDistribution from value counts, or None when disabled."""
    if not top_n or present_count == 0:
        return None

    distinct = len(value_counts)
    if distinct <= top_n:
        return BoundedDistribution(
            count=present_count,
            histogram=dict(value_counts),
            sample_complete=True,
        )

    # Truncate to top-N by frequency, ties broken by key for determinism.
    # Counter.most_common alone breaks ties by insertion order, which is not
    # stable across runs/backends; sorting by (-count, key) makes the kept set
    # reproducible so profile comparisons don't drift.
    ranked = sorted(value_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top_histogram = dict(ranked[:top_n])
    top_total = sum(top_histogram.values())
    return BoundedDistribution(
        count=present_count,
        histogram=top_histogram,
        sample_complete=False,
        limit=top_n,
        other_count=present_count - top_total,
    )


def _compute_cardinality(degree_map: dict[str, int]) -> CardinalityStats | None:
    """Compute cardinality stats from a mapping of source_node -> degree."""
    if not degree_map:
        return None
    degrees = list(degree_map.values())
    mean = sum(degrees) / len(degrees)
    # Population variance (divide by N, not N-1): the degrees ARE the full
    # population for this (source-label, rel-type) pair, not a sample of it.
    # This is the reference estimator -- Neo4j/Memgraph must match it or
    # cross-backend variance comparisons will drift.
    variance = sum((d - mean) ** 2 for d in degrees) / len(degrees)
    return CardinalityStats(
        count=len(degrees),
        min=min(degrees),
        max=max(degrees),
        mean=mean,
        variance=variance,
    )


# ---------------------------------------------------------------------------
# Conditional per-pair cardinality — reference implementation
# ---------------------------------------------------------------------------
#
# This is the reference the Neo4j/Memgraph backends must match.  The
# partition key is the *absolute* (source-label-node discriminator, target-label-
# node discriminator) pair: regardless of which side carries the
# conditional cardinality, the key always reads the discriminator from the
# source-label node first and the target-label node second.  Only the *counted*
# node differs — the source node on a source-side rule, the target node on a
# target-side rule — which selects whose degree the partition's
# BoundedDistribution summarises.


@dataclass(frozen=True)
class _EdgeEndpoints:
    """One edge's endpoints and their attribute dicts, kept for partitioning."""

    src_node: str
    tgt_node: str
    src_attrs: dict[str, Any]
    tgt_attrs: dict[str, Any]


def _conditional_sides(
    rel_type: type[RelationshipModel],
) -> list[tuple[ConditionalCardinality, str]]:
    """Return ``(card, side)`` for **every** conditional, directed side.

    ``side`` is ``"source"`` or ``"target"`` and selects which endpoint's degree
    is counted.  A relationship type conditional on both endpoints yields two
    entries; a single-side type yields one; a constant or undirected type
    yields none.  Undirected relationships are skipped (mirrors the in-memory
    path, which only partitions directed sides — ``validation._partition_counts``).
    """
    if not rel_type.__directed__:
        return []
    sides: list[tuple[ConditionalCardinality, str]] = []
    src_card = rel_type.__source_cardinality__
    if isinstance(src_card, ConditionalCardinality):
        sides.append((src_card, "source"))
    tgt_card = rel_type.__target_cardinality__
    if isinstance(tgt_card, ConditionalCardinality):
        sides.append((tgt_card, "target"))
    return sides


def _discriminator_keys(matches: tuple[Any, ...]) -> frozenset[str]:
    """Union of property names every rule discriminates on for one endpoint."""
    keys: set[str] = set()
    for match in matches:
        keys.update(match.conditions)
    return frozenset(keys)


def _discriminator_value(attrs: dict[str, Any], keys: frozenset[str]) -> str | None:
    """Read the single discriminator value for *keys* from *attrs*, as a string.

    The single-``kind`` first cut discriminates on one property per
    endpoint; an endpoint with no discriminator, or a missing/``None`` value,
    maps to ``None`` (the null-partition component).  Multi-key endpoints are not
    supported in this first cut and also yield ``None`` (the guarded follow-on
    tracked in the epic Out-of-Scope handles them).
    """
    if len(keys) != 1:
        return None
    value = attrs.get(next(iter(keys)))
    return None if value is None else str(value)


def _partition_degrees(
    card: ConditionalCardinality,
    side: str,
    endpoints: list[_EdgeEndpoints],
) -> dict[PartitionKey, list[int]]:
    """Group per-counted-node degrees by the absolute (src_value, tgt_value) pair.

    For each edge the partition key reads the source-label node's discriminator
    and the target-label node's discriminator (absolute convention).  The counted
    node is the source node on the source side and the target node on the target
    side; its degree within each partition is the number of edges it has in that
    partition.  Returns ``{partition: [degree_per_counted_node, ...]}``.
    """
    src_keys = _discriminator_keys(tuple(r.source for r in card.rules))
    tgt_keys = _discriminator_keys(tuple(r.target for r in card.rules))

    # counts[partition][counted_node] = degree of that node in that partition
    counts: dict[PartitionKey, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for edge in endpoints:
        partition = PartitionKey(
            source_value=_discriminator_value(edge.src_attrs, src_keys),
            target_value=_discriminator_value(edge.tgt_attrs, tgt_keys),
        )
        counted_node = edge.src_node if side == "source" else edge.tgt_node
        counts[partition][counted_node] += 1

    return {
        partition: list(node_degrees.values())
        for partition, node_degrees in counts.items()
    }


def _stats_per_partition(
    degrees_by_partition: dict[PartitionKey, list[int]],
) -> dict[str, BoundedDistribution]:
    """Summarise each partition's per-node degrees into a BoundedDistribution.

    Constructs :class:`BoundedDistribution` directly (not the
    :class:`CardinalityStats` marker subclass): the profile field is typed on
    the base, so a subclass value would be restored as its base on reload and
     break round-trip equality.  Reuses the population-variance
    estimator of :func:`_compute_cardinality` so partition and aggregate stats
    stay consistent.
    """
    result: dict[str, BoundedDistribution] = {}
    for partition, degrees in degrees_by_partition.items():
        mean = sum(degrees) / len(degrees)
        variance = sum((d - mean) ** 2 for d in degrees) / len(degrees)
        result[str(partition)] = BoundedDistribution(
            count=len(degrees),
            min=min(degrees),
            max=max(degrees),
            mean=mean,
            variance=variance,
        )
    return result


def _compute_partitioned_cardinality(
    rel_key: RelTypeKey,
    endpoints: list[_EdgeEndpoints],
    graph_definition: GraphDefinition | None,
) -> tuple[
    dict[str, BoundedDistribution] | None, dict[str, BoundedDistribution] | None
]:
    """Return ``(source_breakdown, target_breakdown)`` for a conditional rel type.

    Each element is ``None`` (the common case) when its side is not conditional,
    no definition is injected, the relationship type is unknown, or there are no
    edges — so non-conditional profiling cost is unchanged.  A type conditional on
    **both** endpoints returns both breakdowns; the per-side fields keep
    source-counted and target-counted partitions from colliding.
    """
    if graph_definition is None:
        return None, None
    # Resolve the declared shape by its identity triple: the profile is
    # now grouped per endpoint pair, so the exact declared type is addressable.
    rel_type = graph_definition.get_relationship_type(
        rel_key.source_label, rel_key.label, rel_key.target_label
    )
    if rel_type is None:
        return None, None
    if not endpoints:
        return None, None

    source_breakdown: dict[str, BoundedDistribution] | None = None
    target_breakdown: dict[str, BoundedDistribution] | None = None
    for card, side in _conditional_sides(rel_type):
        breakdown = _stats_per_partition(_partition_degrees(card, side, endpoints))
        if side == "source":
            source_breakdown = breakdown
        else:
            target_breakdown = breakdown
    return source_breakdown, target_breakdown
