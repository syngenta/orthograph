"""Graph inspector ABC and the shared Cypher inspector base."""

from abc import ABC, abstractmethod
from typing import Any

from orthograph.cypher.bindings import NoParams
from orthograph.graph_profile.models import (
    BoundedDistribution,
    CardinalityStats,
    GraphProfile,
    PartitionedCardinalityRow,
    PartitionKey,
    RelationshipTypeProfile,
)


def _extract_discriminators(card: Any) -> tuple[str, str] | None:
    """Return ``(source_prop, target_prop)`` for a single-property discriminator.

    Reads the union of property names used as conditions across all rules on
    each endpoint.  Returns ``None`` when the discriminator is multi-property
    (unsupported in the E41 first cut) or when no conditions exist.

    Mirrors the single-``kind`` constraint of :func:`_discriminator_value` in
    the NetworkX reference inspector.
    """
    src_keys: set[str] = set()
    tgt_keys: set[str] = set()
    for rule in card.rules:
        src_keys.update(rule.source.conditions)
        tgt_keys.update(rule.target.conditions)
    if len(src_keys) != 1 or len(tgt_keys) != 1:
        return None
    return next(iter(src_keys)), next(iter(tgt_keys))


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

    def _enrich_with_endpoints_and_cardinality(
        self,
        connection: Any,
        profile: RelationshipTypeProfile,
        endpoint_query: Any,
        cardinality_query: Any,
        fallback_labels: set[str] | None = None,
        **execute_kwargs: Any,
    ) -> RelationshipTypeProfile:
        """Return a copy of ``profile`` with endpoint labels + cardinality filled.

        Endpoint labels are collected first; cardinality is then probed against
        the confirmed source labels (falling back to ``fallback_labels`` only if
        no source labels were found), using the first label that has at least one
        relationship.  This avoids the misleading min=0/max=0 produced by
        target-only labels.
        """
        rel_type = profile.rel_type

        source_labels: set[str] = set()
        target_labels: set[str] = set()
        endpoint_rows = self._run_query(
            connection,
            endpoint_query,
            identifiers={"rel_type": rel_type},
            **execute_kwargs,
        )
        for erow in endpoint_rows:
            source_labels.update(erow.source_labels)
            target_labels.update(erow.target_labels)

        card_stats: CardinalityStats | None = None
        candidates = (
            sorted(source_labels) if source_labels else sorted(fallback_labels or set())
        )
        for label in candidates:
            card_rows: list[CardinalityStats] = self._run_query(
                connection,
                cardinality_query,
                identifiers={"label": label, "rel_type": rel_type},
                **execute_kwargs,
            )
            if card_rows and card_rows[0].count > 0:
                card_stats = card_rows[0]
                break

        return RelationshipTypeProfile(
            rel_type=profile.rel_type,
            count=profile.count,
            property_profiles=profile.property_profiles,
            cardinality_stats=card_stats,
            source_labels=source_labels,
            target_labels=target_labels,
        )

    def _enrich_with_partitioned_cardinality(
        self,
        connection: Any,
        profile: RelationshipTypeProfile,
        partitioned_query: Any,
        source_discriminator: str,
        target_discriminator: str,
        side: str,
        **execute_kwargs: Any,
    ) -> RelationshipTypeProfile:
        """Return a copy of ``profile`` with one side's partitioned breakdown set.

        The query is anchored on the side's own label and counts that side's
        degree — ``side == "source"`` iterates ``profile.source_labels`` with the
        source-anchored (outgoing-degree) query; ``side == "target"`` iterates
        ``profile.target_labels`` with the target-anchored (incoming-degree) query.
        The caller supplies the matching ``partitioned_query`` class.  The result
        is assembled into ``dict[str, BoundedDistribution]`` keyed by
        ``str(PartitionKey)`` and attached to ``{side}_partitioned_cardinality``.
        Calling it once per conditional side lets a both-endpoint-conditional type
        carry both breakdowns without collision (E41.7).

        Zero-degree rows (emitted by ``OPTIONAL MATCH`` for anchor nodes that have
        no matching edge) are suppressed so the result matches the NetworkX
        reference, which only emits partitions for observed edges (ADR-009 /
        E41.4 parity note).

        When no labels are known for the side or the query returns only zero-degree
        rows, the targeted field is left ``None`` (honest).
        """
        rel_type = profile.rel_type
        candidates = sorted(
            profile.source_labels if side == "source" else profile.target_labels
        )

        partitioned: dict[str, BoundedDistribution] = {}
        for label in candidates:
            rows: list[PartitionedCardinalityRow] = self._run_query(
                connection,
                partitioned_query,
                identifiers={
                    "label": label,
                    "rel_type": rel_type,
                    "source_discriminator": source_discriminator,
                    "target_discriminator": target_discriminator,
                },
                **execute_kwargs,
            )
            for row in rows:
                # Suppress zero-degree rows from OPTIONAL MATCH (parity with
                # NetworkX, which only emits observed edges -- see E41.4 notes).
                # A zero-degree partition has all anchor nodes at 0 degree:
                # min == 0 and max == 0.  Absent partitions are handled at
                # comparison time by treating a missing key as degree 0.
                if row.stats.min == 0 and row.stats.max == 0:
                    continue
                key = str(
                    PartitionKey(
                        source_value=row.source_value,
                        target_value=row.target_value,
                    )
                )
                partitioned[key] = row.stats

        breakdown = partitioned if partitioned else None
        return profile.model_copy(
            update={
                f"{side}_partitioned_cardinality": breakdown,
            }
        )
