"""Memgraph graph inspector (stateless; connection injected per call).

Counts and completeness — truthful, via dedicated property-independent
``count()`` queries (parity with Neo4j):

  * ``NodeTypeProfile.count`` / ``RelationshipTypeProfile.count`` come from
    ``MATCH (n:Label) RETURN count(n)`` / the edge equivalent — not from the
    schema procedures (which yield no observation counts).
  * ``PropertyProfile.total_count`` is that same true entity total, so
    ``completeness = present_count / total_count`` is meaningful.  When the
    value scan runs (``value_counts_top_n`` set), ``present_count`` is its exact
    non-null count and ``completeness`` is truthful.  Without a scan there is no
    *observed* completeness datum: the schema ``mandatory`` boolean is **not**
    used as a present==total proxy (presence requirements are carried by
    ``constraint_required``, sourced from real DB constraints), so
    ``present_count == total_count`` (completeness 1.0, no incompleteness claim).
    ``total_count`` is **never** derived from ``present_count`` — doing so would
    fabricate ``completeness == 1.0`` even when a scan observed fewer values, and
    suppress ``PROPERTY_INCOMPLETE`` ("never invent counts").

``cardinality_stats`` and ``source_label``/``target_label`` (per-shape scalar
endpoints) ARE populated (using the vendor-neutral shared Cypher).
"""

from typing import Any

from orthograph.backends.memgraph.queries import (
    MemgraphCardinalityQuery,
    MemgraphConstraintsQuery,
    MemgraphEndpointLabelsQuery,
    MemgraphNodeCountQuery,
    MemgraphNodePropertiesQuery,
    MemgraphNodeTypeCountsQuery,
    MemgraphNodeValueHistogramQuery,
    MemgraphRelCountQuery,
    MemgraphRelPropertiesQuery,
    MemgraphRelTypeCountsQuery,
    MemgraphRelValueHistogramQuery,
    MemgraphSourcePartitionedCardinalityQuery,
    MemgraphTargetPartitionedCardinalityQuery,
    MemgraphTopNParams,
    MemgraphTypeCountRow,
    MemgraphValueHistogramRow,
)
from orthograph.comparison.engine import compare_profile_to_definition
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import ConditionalCardinality
from orthograph.graph_profile.constraints import is_presence_constraint_for
from orthograph.graph_profile.inspection import CypherInspector, _extract_discriminators
from orthograph.graph_profile.models import (
    BoundedDistribution,
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
    RelTypeKey,
)


class MemgraphInspector(CypherInspector):
    """Inspects a Memgraph database and produces a :class:`GraphProfile`.

    Stateless: the driver is passed to :meth:`inspect` per call, never stored.

    Parameters
    ----------
    value_counts_top_n:
        When set, run an opt-in per-property value scan that
        populates ``observed_type_counts`` (via ``valueType``, exact) and a
        scalar ``value_distribution`` histogram (via ``toStringOrNull``, bounded
        to ``top_n``).  ``None`` / ``0`` runs no value-touching scan: both fields
        stay ``{}`` / ``None`` (byte-for-byte the previous behaviour).
    """

    def __init__(self, value_counts_top_n: int | None = None) -> None:
        self._value_counts_top_n = value_counts_top_n

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def inspect(
        self,
        connection: Any,
        *,
        graph_definition: GraphDefinition | None = None,
    ) -> GraphProfile:
        """Inspect the Memgraph database and return a :class:`GraphProfile`.

        When ``graph_definition`` is supplied, relationship types whose declared
        side is a :class:`~orthograph.graph_definition.models.ConditionalCardinality`
        additionally receive per-side partitioned cardinality breakdowns
        (``source_partitioned_cardinality`` / ``target_partitioned_cardinality``).
        Without a definition the breakdowns are left ``None`` (comparison
        then reports ``CARDINALITY_UNVERIFIABLE``).
        """
        constraints = self._get_constraints(connection)
        node_profiles = self._build_node_profiles(connection, constraints)
        rel_profiles = self._build_rel_profiles(
            connection, constraints, graph_definition=graph_definition
        )

        return GraphProfile(
            source="memgraph",
            node_type_profiles=node_profiles,
            rel_type_profiles=rel_profiles,
            constraints=constraints,
        )

    # ------------------------------------------------------------------
    # Internal — profile builders
    # ------------------------------------------------------------------

    def _build_node_profiles(
        self, connection: Any, constraints: list[ConstraintInfo]
    ) -> dict[str, NodeTypeProfile]:
        rows = self._run_query(connection, MemgraphNodePropertiesQuery)

        label_props: dict[str, list[Any]] = {}
        for row in rows:
            for lbl in row.node_labels:
                label_props.setdefault(lbl, [])

            if not row.property_name:
                raw_type = row.node_type
                lbl = raw_type.strip(":` ")
                label_props.setdefault(lbl, [])
                continue

            raw_type = row.node_type
            lbl = raw_type.strip(":` ")
            label_props.setdefault(lbl, []).append(row)

        profiles: dict[str, NodeTypeProfile] = {}
        for label, prop_rows in sorted(label_props.items()):
            # Truthful entity total via a property-independent count() — the only
            # honest denominator for completeness (never derive it from
            # present_count, which would fabricate completeness == 1.0).
            label_total = self._fetch_node_count(connection, label)
            props: dict[str, PropertyProfile] = {}
            for r in prop_rows:
                name = r.property_name
                # No-scan fallback: Memgraph's schema procedures yield only a
                # `mandatory` boolean, never observation counts.  `mandatory` is
                # deliberately NOT used as a present==total proxy (presence
                # requirements are carried by `constraint_required`, sourced from
                # real DB constraints.  Without a value scan there
                # is no observed completeness signal, so present_count == total
                # (completeness 1.0 — no *observed* incompleteness claimed).  The
                # value scan, when enabled, supersedes this with the exact
                # non-null count and a truthful completeness.
                type_counts, value_dist, present_count = self._fetch_node_value_scan(
                    connection,
                    label,
                    name,
                    fallback_present_count=label_total,
                )
                props[name] = PropertyProfile(
                    name=name,
                    present_count=present_count,
                    total_count=max(label_total, present_count),
                    observed_types=r.property_types,
                    constraint_required=is_presence_constraint_for(
                        constraints, "NODE", label, name
                    ),
                    observed_type_counts=type_counts,
                    value_distribution=value_dist,
                )
            profiles[label] = NodeTypeProfile(
                label=label, count=label_total, property_profiles=props
            )

        return profiles

    def _build_rel_profiles(
        self,
        connection: Any,
        constraints: list[ConstraintInfo],
        *,
        graph_definition: GraphDefinition | None = None,
    ) -> dict[str, RelationshipTypeProfile]:
        rows = self._run_query(connection, MemgraphRelPropertiesQuery)

        # Bulk property *types* keyed by the bare rel type: a
        # property key's stored type does not vary by endpoint pair, so the bulk
        # schema scan is the observed_types source for every shape.  Per-shape
        # counts come from the endpoint-filtered pattern scans below.
        type_rows: dict[str, list[Any]] = {}
        for row in rows:
            raw_type = row.rel_type
            rel_type = raw_type.strip(":` ")
            type_rows.setdefault(rel_type, []).append(row)

        profiles: dict[str, RelationshipTypeProfile] = {}
        for rel_type in sorted(type_rows):
            prop_rows = type_rows[rel_type]
            # Discover the distinct endpoint shapes of this bare rel type.
            pairs = self._discover_endpoint_pairs(
                connection, rel_type, MemgraphEndpointLabelsQuery
            )
            for source_label, target_label in pairs:
                profile = self._build_rel_profile_for_shape(
                    connection,
                    rel_type,
                    source_label,
                    target_label,
                    prop_rows,
                    constraints,
                    graph_definition=graph_definition,
                )
                key = str(
                    RelTypeKey(
                        source_label=source_label,
                        label=rel_type,
                        target_label=target_label,
                    )
                )
                profiles[key] = profile

        return profiles

    def _build_rel_profile_for_shape(
        self,
        connection: Any,
        rel_type: str,
        source_label: str,
        target_label: str,
        prop_rows: list[Any],
        constraints: list[ConstraintInfo],
        *,
        graph_definition: GraphDefinition | None = None,
    ) -> RelationshipTypeProfile:
        """Build one profile for the ``(source, rel, target)`` shape."""
        # Per-shape edge total via an endpoint-filtered count().
        rel_total = self._fetch_rel_count(
            connection, rel_type, source_label, target_label
        )
        props: dict[str, PropertyProfile] = {}
        for r in prop_rows:
            name = r.property_name
            if not name:
                continue
            type_counts, value_dist, present_count = self._fetch_rel_value_scan(
                connection,
                rel_type,
                source_label,
                target_label,
                name,
                fallback_present_count=rel_total,
            )
            props[name] = PropertyProfile(
                name=name,
                present_count=present_count,
                total_count=max(rel_total, present_count),
                observed_types=r.property_types,
                constraint_required=is_presence_constraint_for(
                    constraints, "RELATIONSHIP", rel_type, name
                ),
                observed_type_counts=type_counts,
                value_distribution=value_dist,
            )

        profile = RelationshipTypeProfile(
            rel_type=rel_type,
            count=rel_total,
            source_label=source_label,
            target_label=target_label,
            property_profiles=props,
            cardinality_stats=self._cardinality_for_shape(
                connection,
                rel_type,
                source_label,
                target_label,
                MemgraphCardinalityQuery,
            ),
        )

        # Partitioned cardinality — only for conditional relationship types when
        # a definition is provided.  Resolve the declared shape by identity triple.
        if graph_definition is not None:
            rel_model = graph_definition.get_relationship_type(
                source_label, rel_type, target_label
            )
            if rel_model is not None:
                for card_attr, side, side_query in (
                    (
                        "__source_cardinality__",
                        "source",
                        MemgraphSourcePartitionedCardinalityQuery,
                    ),
                    (
                        "__target_cardinality__",
                        "target",
                        MemgraphTargetPartitionedCardinalityQuery,
                    ),
                ):
                    card = getattr(rel_model, card_attr, None)
                    if isinstance(card, ConditionalCardinality):
                        discriminators = _extract_discriminators(card)
                        if discriminators is not None:
                            src_disc, tgt_disc = discriminators
                            profile = self._enrich_with_partitioned_cardinality(
                                connection,
                                profile,
                                side_query,
                                src_disc,
                                tgt_disc,
                                side,
                            )
        return profile

    def _get_constraints(self, connection: Any) -> list[ConstraintInfo]:
        rows = self._run_query(connection, MemgraphConstraintsQuery)
        return [
            ConstraintInfo(
                name=None,
                constraint_type=row.constraint_type,
                entity_type=row.entity_type,
                labels=[row.label] if row.label else [],
                properties=row.properties,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Internal — value scan helpers
    # ------------------------------------------------------------------

    def _fetch_node_count(self, connection: Any, label: str) -> int:
        """Return the node count for ``label`` via a property-independent count().

        Independent of properties: a label with no properties still has a
        truthful instance count (the schema scan supplies none).  This is the
        honest denominator for ``completeness`` — never derive a total from
        ``present_count``.
        """
        rows = self._run_query(
            connection, MemgraphNodeCountQuery, identifiers={"label": label}
        )
        return rows[0].count if rows else 0

    def _fetch_rel_count(
        self,
        connection: Any,
        rel_type: str,
        source_label: str,
        target_label: str,
    ) -> int:
        """Per-shape edge count via an endpoint-filtered count()."""
        rows = self._run_query(
            connection,
            MemgraphRelCountQuery,
            identifiers={
                "source_label": source_label,
                "rel_type": rel_type,
                "target_label": target_label,
            },
        )
        return rows[0].count if rows else 0

    def _fetch_node_value_scan(
        self,
        connection: Any,
        label: str,
        property_name: str,
        fallback_present_count: int,
    ) -> tuple[dict[str, int], BoundedDistribution | None, int]:
        """Run the optional value scan for one node property.

        Returns ``(observed_type_counts, value_distribution, present_count)``.
        When the scan runs, ``present_count`` is the **authoritative** non-null
        count (the exact sum of the per-type group counts), which supersedes the
        Memgraph mandatory heuristic.  When the scan is skipped
        (``value_counts_top_n`` unset) the fallback is returned unchanged with
        ``{}`` / ``None``.
        """
        if not self._value_counts_top_n:
            return {}, None, fallback_present_count

        identifiers = {"label": label, "property_name": property_name}
        type_rows: list[MemgraphTypeCountRow] = self._run_query(
            connection, MemgraphNodeTypeCountsQuery, identifiers=identifiers
        )
        return self._assemble_value_scan(
            connection,
            MemgraphNodeValueHistogramQuery,
            identifiers,
            type_rows,
            fallback_present_count,
        )

    def _fetch_rel_value_scan(
        self,
        connection: Any,
        rel_type: str,
        source_label: str,
        target_label: str,
        property_name: str,
        fallback_present_count: int,
    ) -> tuple[dict[str, int], BoundedDistribution | None, int]:
        """Run the optional per-shape value scan for one relationship property.

        Endpoint-filtered: the type-count / histogram scans target
        only edges of the ``(source_label, rel_type, target_label)`` shape.
        """
        if not self._value_counts_top_n:
            return {}, None, fallback_present_count

        identifiers = {
            "source_label": source_label,
            "rel_type": rel_type,
            "target_label": target_label,
            "property_name": property_name,
        }
        type_rows = self._run_query(
            connection, MemgraphRelTypeCountsQuery, identifiers=identifiers
        )
        return self._assemble_value_scan(
            connection,
            MemgraphRelValueHistogramQuery,
            identifiers,
            type_rows,
            fallback_present_count,
        )

    def _assemble_value_scan(
        self,
        connection: Any,
        histogram_query_cls: Any,
        identifiers: dict[str, str],
        type_rows: list[MemgraphTypeCountRow],
        fallback_present_count: int,
    ) -> tuple[dict[str, int], BoundedDistribution | None, int]:
        """Combine type counts + the scalar histogram into the scan result.

        The type-count total is the authoritative ``present_count`` (every
        non-null value has exactly one runtime type.  The scalar
        histogram (``toStringOrNull``, list values dropped) may total below it;
        the remainder reconciles into ``other_count``.
        """
        type_counts = {r.type_name: r.type_count for r in type_rows}
        scan_present_count = sum(type_counts.values())

        # Honest degradation: the type scan classified nothing but the heuristic
        # reported presence.  Keep the fallback presence; report no counts rather
        # than zeroing present_count (never silently regress presence).
        if not type_counts and fallback_present_count > 0:
            return {}, None, fallback_present_count

        top_n = self._value_counts_top_n
        assert top_n  # guarded by the callers' early return
        hist_query = histogram_query_cls(identifiers=identifiers)
        cypher, params = hist_query.build(MemgraphTopNParams(top_n=top_n))
        raw_rows = self._run(connection, cypher, parameters_=params)
        hist_rows: list[MemgraphValueHistogramRow] = [
            hist_query.materialize(r) for r in raw_rows
        ]
        value_dist = _build_value_distribution(hist_rows, scan_present_count, top_n)
        return type_counts, value_dist, scan_present_count


def validate_database(
    connection: Any,
    graph_definition: GraphDefinition,
) -> ValidationResult:
    """Validate a Memgraph database against a GraphDefinition."""
    profile = MemgraphInspector().inspect(connection, graph_definition=graph_definition)
    return compare_profile_to_definition(profile, graph_definition)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _build_value_distribution(
    hist_rows: list[MemgraphValueHistogramRow],
    present_count: int,
    top_n: int,
) -> BoundedDistribution | None:
    """Build a BoundedDistribution from scalar value-histogram rows.

    The DB query already applies ``LIMIT $top_n``.  Because the histogram covers
    **scalar values only** (``toStringOrNull`` drops lists/maps), its total can
    be below the authoritative ``present_count``; the shortfall — whether from
    truncation or from dropped non-scalar values — folds into ``other_count``.
    Returns ``None`` when there are no rows.

    Known cross-backend parity deviation (not identical
    output).  Memgraph's histogram key is ``toStringOrNull`` (scalars only),
    whereas Neo4j's APOC histogram key is ``apoc.convert.toJson`` (list/map
    values are kept *in* the histogram).  Consequence: a property mixing scalars
    and lists is reported ``sample_complete=False`` with the lists in
    ``other_count`` on Memgraph, but ``sample_complete=True`` on Neo4j for the
    same data.  ``observed_type_counts`` (the epic's primary deliverable) is
    exact and parity-correct on both backends; only the *value histogram*'s
    ``sample_complete``/``other_count`` differ.  Memgraph has no portable
    list-safe scalar+list value key, so this is honest degradation, not a bug.
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
