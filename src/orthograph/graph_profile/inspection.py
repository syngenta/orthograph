"""Graph inspector ABC and the shared Cypher inspector base."""

from abc import ABC, abstractmethod
from typing import Any

from orthograph.cypher.bindings import NoParams
from orthograph.graph_profile.models import (
    CardinalityStats,
    GraphProfile,
    RelationshipTypeProfile,
)


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
            if card_rows and card_rows[0].sample_size > 0:
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
