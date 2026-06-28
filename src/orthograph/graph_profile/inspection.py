"""Graph inspector ABC and the shared Cypher inspector base."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Protocol

from orthograph.cypher.bindings import NoParams
from orthograph.graph_profile.models import (
    BoundedDistribution,
    CardinalityStats,
    GraphProfile,
    PartitionedCardinalityRow,
    RelationshipTypeProfile,
)


class _HistogramRow(Protocol):
    """Duck-type for histogram rows.

    Satisfied by both ``ValueHistogramRow`` and ``MemgraphValueHistogramRow``.
    """

    value: str
    value_count: int


def _extract_discriminators(card: Any) -> tuple[list[str], list[str]] | None:
    """Return ``(source_props, target_props)`` for the per-endpoint discriminators.

    Reads the union of property names used as conditions across all rules on
    each endpoint.  Each endpoint may carry **any number** of properties (E54
    lifts the former single-property cut):

    * one or many properties → the sorted list of property names for the side;
    * zero properties (a wildcard ``PropMatch()``) → the empty list, meaning the
      side has no grouping key and resolves to an empty-map partition endpoint
      (``{}``) — mirroring ADR-032's absolute convention and the
      ``PartitionKey(source={} | target={})`` representation.

    Returns ``None`` (declines) only for a fully-wildcard rule set (both
    endpoints empty), where there is nothing to partition on.

    Names are sorted so the projected grouped columns and the reconstructed
    :class:`PartitionKey` maps line up deterministically with the NetworkX
    reference (which sorts its discriminator keys), keeping rows comparable
    across backends.

    Mirrors :func:`_discriminator_keys` / :func:`_discriminator_map` in the
    NetworkX reference inspector, where a zero-key endpoint likewise maps to the
    empty-map partition endpoint.
    """
    src_keys: set[str] = set()
    tgt_keys: set[str] = set()
    for rule in card.rules:
        src_keys.update(rule.source.conditions)
        tgt_keys.update(rule.target.conditions)
    if not src_keys and not tgt_keys:
        return None
    return sorted(src_keys), sorted(tgt_keys)


class GraphInspector(ABC):
    """Inspects a graph source and produces a structural profile.

    Stateless: the source (driver / graph) is passed to ``inspect`` per call,
    never stored on the instance.
    """

    @abstractmethod
    def inspect(self, connection: Any) -> GraphProfile: ...


class CypherInspector(GraphInspector):
    """Shared base for Cypher-speaking inspectors.

    Provides the driver-I/O seam and typed-query execution helper.
    The driver is threaded through every call; none is stored.
    """

    def _run(
        self, connection: Any, cypher: str, **execute_kwargs: Any
    ) -> list[dict[str, Any]]:
        """Execute a raw Cypher string and return dict rows.

        ``execute_kwargs`` carries backend-specific driver options
        (e.g. ``database_=``).
        """
        records, _, _ = connection.execute_query(cypher, **execute_kwargs)
        return [dict(record) for record in records]

    def _run_query(
        self,
        connection: Any,
        query: Any,
        identifiers: dict[str, str] | None = None,
        **execute_kwargs: Any,
    ) -> list[Any]:
        """Build a typed query, render its Cypher, execute it, materialize rows."""
        instance = query(identifiers=identifiers or {})
        cypher, _ = instance.build(NoParams())
        rows = self._run(connection, cypher, **execute_kwargs)
        return [instance.materialize(row) for row in rows]

    def _discover_endpoint_pairs(
        self,
        connection: Any,
        rel_type: str,
        endpoint_query: Any,
        **execute_kwargs: Any,
    ) -> list[tuple[str, str]]:
        """Discover the distinct ``(source_label, target_label)`` pairs for a rel type.

        Drives the per-shape fan-out: the endpoint-discovery query
        returns each instance's source/target label *lists*; the cross product of
        every row's lists yields the scalar endpoint pairs that identify the
        distinct relationship shapes.  Returned sorted for deterministic output.

        **Assumption (currently unreachable):** Assumes endpoint nodes carry a single
        label each. If a node carries multiple labels, the cross-product yields a
        shape for each label combination, and downstream per-shape cardinality/count
        scans will count the same physical edge in multiple profiles — total counts
        will not sum to the true edge count. The declared side has no mechanism to
        declare multi-labeled nodes (``NodeModel.__label__`` is a single scalar in
        ``graph_definition/models.py``); backend result adapters collapse multi-label
        nodes to a primary label.
        """
        pairs: set[tuple[str, str]] = set()
        endpoint_rows = self._run_query(
            connection,
            endpoint_query,
            identifiers={"rel_type": rel_type},
            **execute_kwargs,
        )
        for erow in endpoint_rows:
            for src in erow.source_labels:
                for tgt in erow.target_labels:
                    pairs.add((src, tgt))
        return sorted(pairs)

    def _fetch_node_count(
        self, connection: Any, label: str, count_query: Any, **execute_kwargs: Any
    ) -> int:
        """Return the node count for ``label`` via a property-independent count().

        Independent of properties: a label with no properties still has a
        truthful instance count (the property scan would yield zero rows).
        ``count_query`` is the vendor-specific ``NodeCountQuery`` class.
        """
        rows = self._run_query(
            connection, count_query, identifiers={"label": label}, **execute_kwargs
        )
        return rows[0].count if rows else 0

    def _fetch_rel_count(
        self,
        connection: Any,
        rel_type: str,
        source_label: str,
        target_label: str,
        count_query: Any,
        **execute_kwargs: Any,
    ) -> int:
        """Per-shape edge count via an endpoint-filtered count().

        Counts only edges of ``rel_type`` between ``source_label`` and
        ``target_label``, so the count belongs to one relationship shape.
        ``count_query`` is the vendor-specific ``RelCountQuery`` class.
        """
        rows = self._run_query(
            connection,
            count_query,
            identifiers={
                "source_label": source_label,
                "rel_type": rel_type,
                "target_label": target_label,
            },
            **execute_kwargs,
        )
        return rows[0].count if rows else 0

    def _build_value_distribution(
        self,
        hist_rows: Sequence[_HistogramRow],
        present_count: int,
        top_n: int,
    ) -> BoundedDistribution | None:
        """Build a :class:`BoundedDistribution` from value-histogram query rows.

        The DB query already applies ``LIMIT $top_n``; the inspector receives at
        most ``top_n`` rows.  If the sum of their counts equals ``present_count``
        the histogram is complete (``sample_complete=True``); otherwise the
        remainder folds into ``other_count`` (honesty principle).

        Completeness is inferred purely from count arithmetic:
        ``top_total >= present_count``.  This is correct because every DB row has
        ``value_count >= 1`` (the GROUP BY only produces rows for values that
        actually exist).  If that invariant ever changes the inference must be
        revisited.

        Returns ``None`` when there are no rows (property has no non-null values).

        **Cross-backend parity note:** the histogram key differs by backend.
        Neo4j's APOC path groups on ``apoc.convert.toJson`` (list-safe: lists and
        maps are kept *in* the histogram).  Memgraph and Neo4j's no-APOC path
        group on ``toStringOrNull`` (scalars only: list/map values become ``null``
        and are dropped).  Consequently, on a property mixing scalars and lists,
        Memgraph reports ``sample_complete=False`` with lists in ``other_count``,
        while Neo4j/APOC may report ``sample_complete=True`` for the same data.
        This is honest degradation — the *arithmetic* here is identical on both
        backends; the deviation originates in the query-layer histogram key.
        """
        if not hist_rows or present_count == 0:
            return None

        histogram = {r.value: r.value_count for r in hist_rows}
        top_total = sum(histogram.values())
        sample_complete = top_total >= present_count

        if sample_complete:
            return BoundedDistribution(
                count=present_count,
                histogram=histogram,
                sample_complete=True,
            )
        return BoundedDistribution(
            count=present_count,
            histogram=histogram,
            sample_complete=False,
            limit=top_n,
            other_count=present_count - top_total,
        )

    def _cardinality_for_shape(
        self,
        connection: Any,
        rel_type: str,
        source_label: str,
        target_label: str,
        cardinality_query: Any,
        **execute_kwargs: Any,
    ) -> CardinalityStats | None:
        """Run the endpoint-filtered cardinality scan for one relationship shape.

        Anchored on ``source_label`` and filtered to a ``target_label`` endpoint,
        so the degree distribution belongs to exactly one ``(source, rel, target)``
        shape.  Returns ``None`` when the shape has no edges.
        """
        card_rows: list[CardinalityStats] = self._run_query(
            connection,
            cardinality_query,
            identifiers={
                "label": source_label,
                "rel_type": rel_type,
                "target_label": target_label,
            },
            **execute_kwargs,
        )
        if card_rows and card_rows[0].count > 0:
            return card_rows[0]
        return None

    def _enrich_with_partitioned_cardinality(
        self,
        connection: Any,
        profile: RelationshipTypeProfile,
        query: Any,
        source_discriminators: list[str],
        target_discriminators: list[str],
        side: str,
        **execute_kwargs: Any,
    ) -> RelationshipTypeProfile:
        """Return a copy of ``profile`` with one side's partitioned breakdown set.

        Endpoint-aware: the scan is anchored on the side's own scalar
        endpoint label (``profile.source_label`` for the source side,
        ``profile.target_label`` for the target side) and filtered to the *other*
        endpoint via ``endpoint_label``, so the breakdown belongs to exactly one
        relationship shape.  ``side == "source"`` counts each source node's
        outgoing degree; ``side == "target"`` counts each target node's incoming
        degree.  The result is assembled into a ``list[PartitionedCardinalityRow]``
        (each row's ``key`` a name-carrying :class:`PartitionKey`) and attached to
        ``{side}_partitioned_cardinality``.

        ``query`` is the variable-width source- or target-anchored query class.
        ``source_discriminators`` / ``target_discriminators`` are the (sorted)
        property-name lists for each endpoint (1..N per side); an **empty** list
        is a wildcard endpoint that projects no grouped column and reconstructs to
        the empty map ``{}`` — mirroring ADR-032's absolute convention and the
        NetworkX reference, never a read of a non-existent property.  Every
        property name is spliced through ``validate_identifier`` inside the
        query's ``build()`` — never f-stringed.

        Zero-degree rows (emitted by ``OPTIONAL MATCH`` for anchor nodes that have
        no matching edge) are suppressed so the result matches the NetworkX
        reference, which only emits partitions for observed edges.  When the query
        returns only zero-degree rows the targeted field is left ``None`` (honest).
        """
        rel_type = profile.rel_type
        if side == "source":
            anchor_label = profile.source_label
            endpoint_label = profile.target_label
        else:
            anchor_label = profile.target_label
            endpoint_label = profile.source_label

        identifiers: dict[str, Any] = {
            "label": anchor_label,
            "rel_type": rel_type,
            "endpoint_label": endpoint_label,
            "source_discriminators": source_discriminators,
            "target_discriminators": target_discriminators,
        }

        rows: list[PartitionedCardinalityRow] = self._run_query(
            connection,
            query,
            identifiers=identifiers,
            **execute_kwargs,
        )
        kept: list[PartitionedCardinalityRow] = []
        for row in rows:
            # Suppress zero-degree rows from OPTIONAL MATCH (parity with
            # NetworkX, which only emits observed edges).  Absent partitions are
            # handled at comparison time by treating a missing key as degree 0.
            if row.stats.min == 0 and row.stats.max == 0:
                continue
            kept.append(row)

        breakdown = kept if kept else None
        return profile.model_copy(
            update={
                f"{side}_partitioned_cardinality": breakdown,
            }
        )
