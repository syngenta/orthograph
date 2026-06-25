"""Graph inspector ABC and the shared Cypher inspector base."""

from abc import ABC, abstractmethod
from typing import Any

from orthograph.cypher.bindings import NoParams
from orthograph.graph_profile.models import (
    CardinalityStats,
    GraphProfile,
    PartitionedCardinalityRow,
    RelationshipTypeProfile,
)


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
