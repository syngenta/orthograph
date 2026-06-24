"""Neo4j graph inspector (stateless; connection injected per call)."""

import warnings
from enum import Enum
from typing import Any

from orthograph.backends.neo4j.queries import (
    ApocNodePropertiesQuery,
    ApocNodeTypeCountsQuery,
    ApocNodeValueHistogramQuery,
    ApocRelPropertiesQuery,
    ApocRelTypeCountsQuery,
    ApocRelValueHistogramQuery,
    CypherNodePropertiesQuery,
    CypherNodeValueHistogramQuery,
    CypherRelPropertiesQuery,
    CypherRelValueHistogramQuery,
    DbSchemaNodeTypesQuery,
    DbSchemaRelTypesQuery,
    InspectNeo4jConstraintsQuery,
    InspectNodeLabelsQuery,
    InspectRelTypesQuery,
    NodeCountQuery,
    NodePresentCountQuery,
    NodePropertyRow,
    RelCountQuery,
    RelPresentCountQuery,
    TopNParams,
    TypeCountRow,
    ValueHistogramRow,
)
from orthograph.comparison.engine import compare_profile_to_definition
from orthograph.cypher.base_models import CypherReadQuery
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
)
from orthograph.graph_profile.queries.shared import (
    InspectCardinalityQuery,
    InspectEndpointLabelsQuery,
    InspectSourcePartitionedCardinalityQuery,
    InspectTargetPartitionedCardinalityQuery,
)


# Sentinel distinguishing "use_apoc not passed" from "use_apoc=None passed".
_UNSET = object()

# Type maps from the bulk db.schema.* queries: {label/rel_type: {property: types}}.
SchemaTypeMap = dict[str, dict[str, list[str]]]


class Neo4jInspectionStrategy(str, Enum):
    """Which query set the inspector uses to read property metadata.

    APOC
        ``apoc.meta.*`` — true counts + types in one procedure (requires APOC
        Core; the regression-guard default when available).
    SCHEMA
        Pure-Cypher scan (true counts) merged with built-in ``db.schema.*``
        (types).  Used when ``apoc.meta.*`` is absent but ``db.schema.*`` exists.
    CYPHER
        Pure-Cypher scan only — true counts, no ``observed_types``.  Last resort.
    """

    APOC = "apoc"
    SCHEMA = "schema"
    CYPHER = "cypher"


class Neo4jInspector(CypherInspector):
    """Inspects a Neo4j database and produces a GraphProfile.

    Stateless: the driver is passed to :meth:`inspect` per call, never stored.

    Parameters
    ----------
    strategy:
        Force a :class:`Neo4jInspectionStrategy`.  ``None`` (default) auto-detects
        at ``inspect()`` time in the order APOC → SCHEMA → CYPHER.
    use_apoc:
        **Deprecated** — use ``strategy`` instead.  ``True`` → ``APOC``,
        ``False`` → ``CYPHER``, ``None`` → auto-detect.  Emits a
        ``DeprecationWarning``.  If both are given, ``strategy`` wins.
    """

    def __init__(
        self,
        strategy: Neo4jInspectionStrategy | None = None,
        *,
        value_counts_top_n: int | None = None,
        use_apoc: bool | None = _UNSET,  # type: ignore[assignment]
    ) -> None:
        if use_apoc is not _UNSET:
            warnings.warn(
                "use_apoc is deprecated; pass strategy=Neo4jInspectionStrategy.*"
                " instead. True→APOC, False→CYPHER, None→auto-detect.",
                DeprecationWarning,
                stacklevel=2,
            )
            # strategy wins if both are given.
            if strategy is None:
                if use_apoc is True:
                    strategy = Neo4jInspectionStrategy.APOC
                elif use_apoc is False:
                    strategy = Neo4jInspectionStrategy.CYPHER
                # use_apoc is None → leave strategy None (auto-detect).
        self._strategy = strategy
        self._value_counts_top_n = value_counts_top_n

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def inspect(
        self,
        connection: Any,
        *,
        database: str | None = None,
        graph_definition: GraphDefinition | None = None,
    ) -> GraphProfile:
        """Inspect the Neo4j database and return a :class:`GraphProfile`.

        ``database`` is forwarded to ``driver.execute_query`` as ``database_``.

        When ``graph_definition`` is supplied, relationship types whose declared
        side is a :class:`~orthograph.graph_definition.models.ConditionalCardinality`
        additionally receive per-side partitioned cardinality breakdowns
        (``source_partitioned_cardinality`` / ``target_partitioned_cardinality``).
        Without a definition the breakdowns are left ``None`` (comparison
        then reports ``CARDINALITY_UNVERIFIABLE``).
        """
        execute_kwargs: dict[str, Any] = {"database_": database}
        strategy = self._resolve_strategy(connection, execute_kwargs)

        labels = {
            row.label
            for row in self._run_query(
                connection, InspectNodeLabelsQuery, **execute_kwargs
            )
        }
        rel_types = {
            row.relationship_type
            for row in self._run_query(
                connection, InspectRelTypesQuery, **execute_kwargs
            )
        }

        # SCHEMA fetches the db.schema.* type maps once (bulk), then merges them
        # into the per-label/rel-type pure-Cypher scan results.
        node_type_map: SchemaTypeMap = {}
        rel_type_map: SchemaTypeMap = {}
        if strategy is Neo4jInspectionStrategy.SCHEMA:
            node_type_map = self._fetch_node_type_map(connection, execute_kwargs)
            rel_type_map = self._fetch_rel_type_map(connection, execute_kwargs)

        # Type counts need the APOC runtime-type function (apoc.meta.cypher.type).
        # APOC strategy guarantees it; SCHEMA must gate at runtime — it is the
        # auto-detected fallback precisely when apoc.meta is absent, so we probe
        # once here.  When absent, type counts degrade to {} (ADR-035 §5), never
        # an apoc.meta.cypher.type call against a missing function.
        apoc_available = self._is_apoc_available(strategy, connection, execute_kwargs)

        # Constraints are read first so each PropertyProfile can be cross-
        # referenced against them.
        constraints = self._get_constraints(connection, execute_kwargs)

        node_profiles: dict[str, NodeTypeProfile] = {}
        for label in sorted(labels):
            node_profiles[label] = self._build_node_profile(
                connection,
                label,
                strategy,
                node_type_map,
                constraints,
                apoc_available,
                execute_kwargs,
            )

        rel_profiles: dict[str, RelationshipTypeProfile] = {}
        for rt in sorted(rel_types):
            rel_profiles[rt] = self._build_rel_profile(
                connection,
                rt,
                labels,
                strategy,
                rel_type_map,
                constraints,
                apoc_available,
                execute_kwargs,
                graph_definition=graph_definition,
            )

        return GraphProfile(
            source="neo4j",
            node_type_profiles=node_profiles,
            rel_type_profiles=rel_profiles,
            constraints=constraints,
        )

    # ------------------------------------------------------------------
    # Internal — strategy selection
    # ------------------------------------------------------------------

    def _resolve_strategy(
        self, connection: Any, execute_kwargs: dict[str, Any]
    ) -> Neo4jInspectionStrategy:
        """Resolve the strategy: explicit if set, else auto-detect."""
        if self._strategy is not None:
            return self._strategy
        return self._detect_strategy(connection, execute_kwargs)

    def _detect_strategy(
        self, connection: Any, execute_kwargs: dict[str, Any] | None = None
    ) -> Neo4jInspectionStrategy:
        """Auto-detect in order: APOC → SCHEMA → CYPHER."""
        kwargs = execute_kwargs or {}
        if self._procedure_present(connection, "apoc.meta", kwargs):
            return Neo4jInspectionStrategy.APOC
        if self._procedure_present(connection, "db.schema.nodeTypeProperties", kwargs):
            return Neo4jInspectionStrategy.SCHEMA
        return Neo4jInspectionStrategy.CYPHER

    def _procedure_present(
        self, connection: Any, prefix: str, execute_kwargs: dict[str, Any]
    ) -> bool:
        """Return True if a procedure whose name starts with ``prefix`` exists."""
        rows = self._run(
            connection,
            "SHOW PROCEDURES YIELD name"
            f" WHERE name STARTS WITH '{prefix}'"
            " RETURN count(name) AS cnt",
            **execute_kwargs,
        )
        return bool(rows and rows[0]["cnt"] > 0)

    def _is_apoc_available(
        self,
        strategy: Neo4jInspectionStrategy,
        connection: Any,
        execute_kwargs: dict[str, Any],
    ) -> bool:
        """Return True when the APOC runtime-type function is usable.

        Only relevant when a value scan will run (``value_counts_top_n`` set).
        The APOC strategy guarantees ``apoc.meta`` is present.  SCHEMA is the
        auto-detected fallback when ``apoc.meta`` is absent, so it must probe at
        runtime (ADR-035 §5) — an explicit ``strategy=SCHEMA`` on a server that
        *does* have APOC may still use the type function.  CYPHER never has it.
        """
        if not self._value_counts_top_n:
            return False
        if strategy is Neo4jInspectionStrategy.APOC:
            return True
        if strategy is Neo4jInspectionStrategy.SCHEMA:
            return self._procedure_present(connection, "apoc.meta", execute_kwargs)
        return False

    # ------------------------------------------------------------------
    # Internal — db.schema.* bulk type maps (SCHEMA strategy only)
    # ------------------------------------------------------------------

    def _fetch_node_type_map(
        self, connection: Any, execute_kwargs: dict[str, Any]
    ) -> SchemaTypeMap:
        """Index db.schema node-property types by (label, property_name)."""
        type_map: SchemaTypeMap = {}
        for row in self._run_query(
            connection, DbSchemaNodeTypesQuery, **execute_kwargs
        ):
            if row.property_name is None:
                continue
            type_map.setdefault(row.label, {})[row.property_name] = row.observed_types
        return type_map

    def _fetch_rel_type_map(
        self, connection: Any, execute_kwargs: dict[str, Any]
    ) -> SchemaTypeMap:
        """Index db.schema rel-property types by (rel_type, property_name)."""
        type_map: SchemaTypeMap = {}
        for row in self._run_query(connection, DbSchemaRelTypesQuery, **execute_kwargs):
            if row.property_name is None:
                continue
            type_map.setdefault(row.rel_type, {})[row.property_name] = (
                row.observed_types
            )
        return type_map

    # ------------------------------------------------------------------
    # Internal — profile builders
    # ------------------------------------------------------------------

    def _build_node_profile(
        self,
        connection: Any,
        label: str,
        strategy: Neo4jInspectionStrategy,
        node_type_map: SchemaTypeMap,
        constraints: list[ConstraintInfo],
        apoc_available: bool,
        execute_kwargs: dict[str, Any],
    ) -> NodeTypeProfile:
        query_cls = (
            ApocNodePropertiesQuery
            if strategy is Neo4jInspectionStrategy.APOC
            else CypherNodePropertiesQuery
        )
        rows: list[NodePropertyRow] = self._run_query(
            connection, query_cls, identifiers={"label": label}, **execute_kwargs
        )
        # Instance count comes from a dedicated count() — never from property
        # observations, which are zero for a label that has no properties.  On
        # the APOC strategy it is also the authoritative total_count denominator
        #  APOC's totalObservations can be unreliable.
        total_count = self._fetch_node_count(connection, label, execute_kwargs)
        is_apoc = strategy is Neo4jInspectionStrategy.APOC
        schema_types = node_type_map.get(label, {})
        props: dict[str, PropertyProfile] = {}
        for row in rows:
            if row.property_name is None:
                continue
            observed_types = (
                schema_types.get(row.property_name, [])
                if strategy is Neo4jInspectionStrategy.SCHEMA
                else row.property_types
            )
            type_counts, value_dist, present_count = self._fetch_node_value_scan(
                connection,
                label,
                row.property_name,
                row.property_observations,
                apoc_available,
                execute_kwargs,
            )
            # on the APOC strategy the no-scan present_count would
            # otherwise inherit APOC's sampled propertyObservations (which can
            # undercount).  When the value scan did not supply a present_count,
            # correct it with a real count() … IS NOT NULL.  total_count uses the
            # property-independent instance count (the completeness denominator).
            prop_present_count, prop_total_count = self._resolve_node_counts(
                connection,
                label,
                row.property_name,
                is_apoc,
                scan_ran=bool(self._value_counts_top_n) and apoc_available,
                scan_present_count=present_count,
                fallback_present_count=row.property_observations,
                apoc_total_observations=row.total_observations,
                instance_count=total_count,
                execute_kwargs=execute_kwargs,
            )
            props[row.property_name] = PropertyProfile(
                name=row.property_name,
                present_count=prop_present_count,
                total_count=prop_total_count,
                observed_types=observed_types,
                constraint_required=is_presence_constraint_for(
                    constraints, "NODE", label, row.property_name
                ),
                observed_type_counts=type_counts,
                value_distribution=value_dist,
            )
        return NodeTypeProfile(label=label, count=total_count, property_profiles=props)

    def _build_rel_profile(
        self,
        connection: Any,
        rel_type: str,
        labels: set[str],
        strategy: Neo4jInspectionStrategy,
        rel_type_map: SchemaTypeMap,
        constraints: list[ConstraintInfo],
        apoc_available: bool,
        execute_kwargs: dict[str, Any],
        *,
        graph_definition: GraphDefinition | None = None,
    ) -> RelationshipTypeProfile:
        query_cls = (
            ApocRelPropertiesQuery
            if strategy is Neo4jInspectionStrategy.APOC
            else CypherRelPropertiesQuery
        )
        rows: list[NodePropertyRow] = self._run_query(
            connection, query_cls, identifiers={"rel_type": rel_type}, **execute_kwargs
        )
        # Instance count from a dedicated count() — independent of properties and
        # the authoritative total_count denominator on the APOC strategy (ADR-036).
        total_count = self._fetch_rel_count(connection, rel_type, execute_kwargs)
        is_apoc = strategy is Neo4jInspectionStrategy.APOC
        schema_types = rel_type_map.get(rel_type, {})
        props: dict[str, PropertyProfile] = {}
        for row in rows:
            if row.property_name is None:
                continue
            observed_types = (
                schema_types.get(row.property_name, [])
                if strategy is Neo4jInspectionStrategy.SCHEMA
                else row.property_types
            )
            type_counts, value_dist, present_count = self._fetch_rel_value_scan(
                connection,
                rel_type,
                row.property_name,
                row.property_observations,
                apoc_available,
                execute_kwargs,
            )
            #  correct the APOC relationship-property undercount on the
            # no-scan path ( with a real count() … IS NOT
            # NULL, and use the property-independent instance count for total.
            prop_present_count, prop_total_count = self._resolve_rel_counts(
                connection,
                rel_type,
                row.property_name,
                is_apoc,
                scan_ran=bool(self._value_counts_top_n) and apoc_available,
                scan_present_count=present_count,
                fallback_present_count=row.property_observations,
                apoc_total_observations=row.total_observations,
                instance_count=total_count,
                execute_kwargs=execute_kwargs,
            )
            props[row.property_name] = PropertyProfile(
                name=row.property_name,
                present_count=prop_present_count,
                total_count=prop_total_count,
                observed_types=observed_types,
                constraint_required=is_presence_constraint_for(
                    constraints, "RELATIONSHIP", rel_type, row.property_name
                ),
                observed_type_counts=type_counts,
                value_distribution=value_dist,
            )

        base = RelationshipTypeProfile(
            rel_type=rel_type, count=total_count, property_profiles=props
        )
        enriched = self._enrich_with_endpoints_and_cardinality(
            connection,
            base,
            InspectEndpointLabelsQuery,
            InspectCardinalityQuery,
            fallback_labels=labels,
            **execute_kwargs,
        )

        # Partitioned cardinality — only for conditional relationship types when
        # a definition is provided.  Non-conditional and definition-less cases
        # leave both per-side fields None (comparison reports
        # CARDINALITY_UNVERIFIABLE).  A type conditional on both endpoints is
        # profiled on both sides.
        if graph_definition is not None:
            rel_model = graph_definition.get_relationship_type(rel_type)
            if rel_model is not None:
                for card_attr, side, side_query in (
                    (
                        "__source_cardinality__",
                        "source",
                        InspectSourcePartitionedCardinalityQuery,
                    ),
                    (
                        "__target_cardinality__",
                        "target",
                        InspectTargetPartitionedCardinalityQuery,
                    ),
                ):
                    card = getattr(rel_model, card_attr, None)
                    if isinstance(card, ConditionalCardinality):
                        discriminators = _extract_discriminators(card)
                        if discriminators is not None:
                            src_disc, tgt_disc = discriminators
                            enriched = self._enrich_with_partitioned_cardinality(
                                connection,
                                enriched,
                                side_query,
                                src_disc,
                                tgt_disc,
                                side,
                                **execute_kwargs,
                            )

        return enriched

    def _get_constraints(
        self, connection: Any, execute_kwargs: dict[str, Any]
    ) -> list[ConstraintInfo]:
        rows = self._run_query(
            connection, InspectNeo4jConstraintsQuery, **execute_kwargs
        )
        return list(rows)  # materialize() already returns ConstraintInfo instances

    # ------------------------------------------------------------------
    # Internal — authoritative instance counts (property-independent)
    # ------------------------------------------------------------------

    def _fetch_node_count(
        self, connection: Any, label: str, execute_kwargs: dict[str, Any]
    ) -> int:
        """Return the node count for ``label`` via a dedicated ``count()``.

        Independent of properties: a label with no properties still has a
        truthful instance count (the property scan would yield zero rows).
        """
        rows = self._run_query(
            connection, NodeCountQuery, identifiers={"label": label}, **execute_kwargs
        )
        return rows[0].count if rows else 0

    def _fetch_rel_count(
        self, connection: Any, rel_type: str, execute_kwargs: dict[str, Any]
    ) -> int:
        """Return the edge count for ``rel_type`` via a dedicated ``count()``.

        Independent of properties: a relationship type with no properties still
        has a truthful instance count.
        """
        rows = self._run_query(
            connection,
            RelCountQuery,
            identifiers={"rel_type": rel_type},
            **execute_kwargs,
        )
        return rows[0].count if rows else 0

    # ------------------------------------------------------------------
    # Internal — APOC no-scan count correction (ADR-036)
    # ------------------------------------------------------------------

    def _resolve_node_counts(
        self,
        connection: Any,
        label: str,
        property_name: str,
        is_apoc: bool,
        scan_ran: bool,
        scan_present_count: int,
        fallback_present_count: int,
        apoc_total_observations: int,
        instance_count: int,
        execute_kwargs: dict[str, Any],
    ) -> tuple[int, int]:
        """Resolve ``(present_count, total_count)`` for one node property.

        On the CYPHER / SCHEMA strategies the pure-Cypher property scan already
        yields truthful counts, so they are returned unchanged.

        On the APOC strategy (ADR-036) APOC's sampled ``propertyObservations`` /
        ``totalObservations`` can be unreliable.  When the value scan already ran
        (``value_counts_top_n`` set) it supplied an authoritative
        ``present_count`` which is used as-is; otherwise a dedicated
        ``count() … IS NOT NULL`` query measures the true non-null count.
        ``total_count`` becomes the property-independent instance count (the
        completeness denominator).
        """
        if not is_apoc:
            return fallback_present_count, apoc_total_observations
        present_count = (
            scan_present_count
            if scan_ran
            else self._fetch_node_present_count(
                connection, label, property_name, execute_kwargs
            )
        )
        return present_count, instance_count

    def _resolve_rel_counts(
        self,
        connection: Any,
        rel_type: str,
        property_name: str,
        is_apoc: bool,
        scan_ran: bool,
        scan_present_count: int,
        fallback_present_count: int,
        apoc_total_observations: int,
        instance_count: int,
        execute_kwargs: dict[str, Any],
    ) -> tuple[int, int]:
        """Resolve ``(present_count, total_count)`` for one relationship property.

        Mirrors :meth:`_resolve_node_counts`; on the APOC strategy this corrects
        the ``apoc.meta.relTypeProperties`` undercount (the 100-vs-172 finding).
        """
        if not is_apoc:
            return fallback_present_count, apoc_total_observations
        present_count = (
            scan_present_count
            if scan_ran
            else self._fetch_rel_present_count(
                connection, rel_type, property_name, execute_kwargs
            )
        )
        return present_count, instance_count

    def _fetch_node_present_count(
        self,
        connection: Any,
        label: str,
        property_name: str,
        execute_kwargs: dict[str, Any],
    ) -> int:
        """True non-null count for one node property via a dedicated ``count()``."""
        rows = self._run_query(
            connection,
            NodePresentCountQuery,
            identifiers={"label": label, "property_name": property_name},
            **execute_kwargs,
        )
        return rows[0].present_count if rows else 0

    def _fetch_rel_present_count(
        self,
        connection: Any,
        rel_type: str,
        property_name: str,
        execute_kwargs: dict[str, Any],
    ) -> int:
        """True non-null count for one relationship property via ``count()``."""
        rows = self._run_query(
            connection,
            RelPresentCountQuery,
            identifiers={"rel_type": rel_type, "property_name": property_name},
            **execute_kwargs,
        )
        return rows[0].present_count if rows else 0

    # ------------------------------------------------------------------
    # Internal — value scan helpers (E46.2, ADR-035)
    # ------------------------------------------------------------------

    def _fetch_node_value_scan(
        self,
        connection: Any,
        label: str,
        property_name: str,
        fallback_present_count: int,
        apoc_available: bool,
        execute_kwargs: dict[str, Any],
    ) -> tuple[dict[str, int], BoundedDistribution | None, int]:
        """Run the optional value scan for one node property.

        Returns ``(observed_type_counts, value_distribution, present_count)``.

        When the scan runs, ``present_count`` is the **authoritative** non-null
        count — the exact total of the per-type group counts from a real
        ``MATCH … WHERE … IS NOT NULL`` scan.  This supersedes APOC's
        ``propertyObservations`` (passed as ``fallback_present_count``), which
        can undercount.  When the scan is skipped (``value_counts_top_n`` unset
        or APOC unavailable) the fallback is returned unchanged with ``{}``/``None``.

        The type-count query needs ``apoc.meta.cypher.type`` and the APOC
        histogram needs ``apoc.convert.toJson`` (the list-safe value key), so the
        *full* value scan (type counts + list-keeping histogram) is an APOC
        feature.  When APOC is absent but
        ``value_counts_top_n`` is set, E46.6 still produces a **scalar-only**
        histogram via the pure-Cypher ``toStringOrNull`` fallback (lists dropped,
        type counts stay ``{}``); the histogram total reconciles only over the
        scalar population it scanned, so the dropped non-scalars fold into
        ``other_count`` against the pure-Cypher ``present_count``.
        """
        top_n = self._value_counts_top_n
        if not top_n:
            return {}, None, fallback_present_count

        identifiers = {"label": label, "property_name": property_name}

        if not apoc_available:
            # E46.6 fallback: no APOC → no type counts, but a scalar-only
            # histogram via toStringOrNull (list values become null and are
            # dropped, never crashing toString).  present_count stays the
            # pure-Cypher scan total (covers scalars *and* lists); the shortfall
            # folds into other_count.
            value_dist = self._run_fallback_histogram(
                connection,
                CypherNodeValueHistogramQuery,
                identifiers,
                fallback_present_count,
                top_n,
                execute_kwargs,
            )
            return {}, value_dist, fallback_present_count

        # Type counts — group by runtime type (apoc.meta.cypher.type).
        type_rows: list[TypeCountRow] = self._run_query(
            connection,
            ApocNodeTypeCountsQuery,
            identifiers=identifiers,
            **execute_kwargs,
        )
        type_counts = {r.type_name: r.type_count for r in type_rows}
        # Authoritative non-null count from the real scan (every non-null value
        # has exactly one runtime type, so the per-type totals partition it).
        scan_present_count = sum(type_counts.values())

        # Honest degradation: the type-count scan returned no rows but APOC
        # reported a positive observation count.  This means the runtime-type
        # aggregation could not classify the property's values (e.g.
        # apoc.meta.cypher.type yielded NULL and the GROUP BY dropped the rows).
        # Do NOT zero out present_count — that would silently understate a
        # property that has values.  Return the fallback with {} / None so the
        # property keeps its true presence while honestly reporting no counts
        # (ADR-035 §5: never invent, never silently regress presence).
        if not type_counts and fallback_present_count > 0:
            return {}, None, fallback_present_count

        # Histogram — group by JSON-coerced value (apoc.convert.toJson, list-safe).
        hist_query = ApocNodeValueHistogramQuery(identifiers=identifiers)
        cypher, params = hist_query.build(TopNParams(top_n=top_n))
        raw_rows = self._run(connection, cypher, parameters_=params, **execute_kwargs)
        hist_rows: list[ValueHistogramRow] = [
            hist_query.materialize(r) for r in raw_rows
        ]
        value_dist = _build_value_distribution(hist_rows, scan_present_count, top_n)
        return type_counts, value_dist, scan_present_count

    def _fetch_rel_value_scan(
        self,
        connection: Any,
        rel_type: str,
        property_name: str,
        fallback_present_count: int,
        apoc_available: bool,
        execute_kwargs: dict[str, Any],
    ) -> tuple[dict[str, int], BoundedDistribution | None, int]:
        """Run the optional value scan for one relationship property.

        Returns ``(observed_type_counts, value_distribution, present_count)``.
        Mirrors :meth:`_fetch_node_value_scan` — in particular the authoritative
        ``present_count`` from the real scan, which corrects APOC's
        ``apoc.meta.relTypeProperties`` undercount for relationship properties,
        and the E46.6 pure-Cypher scalar-histogram fallback when APOC is absent.
        """
        top_n = self._value_counts_top_n
        if not top_n:
            return {}, None, fallback_present_count

        identifiers = {"rel_type": rel_type, "property_name": property_name}

        if not apoc_available:
            # fallback: scalar-only histogram (toStringOrNull), no type
            # counts.  See _fetch_node_value_scan for the full rationale.
            value_dist = self._run_fallback_histogram(
                connection,
                CypherRelValueHistogramQuery,
                identifiers,
                fallback_present_count,
                top_n,
                execute_kwargs,
            )
            return {}, value_dist, fallback_present_count

        type_rows = self._run_query(
            connection,
            ApocRelTypeCountsQuery,
            identifiers=identifiers,
            **execute_kwargs,
        )
        type_counts = {r.type_name: r.type_count for r in type_rows}
        scan_present_count = sum(type_counts.values())

        # Honest degradation: scan classified nothing but APOC reported presence.
        # Keep the fallback presence; report no counts rather than zeroing
        # present_count (mirrors _fetch_node_value_scan; ADR-035 §5).
        if not type_counts and fallback_present_count > 0:
            return {}, None, fallback_present_count

        hist_query = ApocRelValueHistogramQuery(identifiers=identifiers)
        cypher, params = hist_query.build(TopNParams(top_n=top_n))
        raw_rows = self._run(connection, cypher, parameters_=params, **execute_kwargs)
        hist_rows = [hist_query.materialize(r) for r in raw_rows]
        value_dist = _build_value_distribution(hist_rows, scan_present_count, top_n)
        return type_counts, value_dist, scan_present_count

    def _run_fallback_histogram(
        self,
        connection: Any,
        histogram_query_cls: type[CypherReadQuery[TopNParams, ValueHistogramRow]],
        identifiers: dict[str, str],
        present_count: int,
        top_n: int,
        execute_kwargs: dict[str, Any],
    ) -> BoundedDistribution | None:
        """Run the E46.6 pure-Cypher scalar histogram for one property.

        Used on the no-APOC path (pure-CYPHER, or SCHEMA when the runtime APOC
        probe is negative).  The ``toStringOrNull`` query key drops list / map /
        non-stringifiable values, so the histogram covers **scalar** values only.
        ``present_count`` is the pure-Cypher property scan total (scalars *and*
        non-scalars); any shortfall — truncation or dropped non-scalars — folds
        into ``other_count``.  When the
        property has no scalar values the histogram is empty and the distribution
        is ``None`` (honest: a list-only property reports no histogram).
        """
        hist_query = histogram_query_cls(identifiers=identifiers)
        cypher, params = hist_query.build(TopNParams(top_n=top_n))
        raw_rows = self._run(connection, cypher, parameters_=params, **execute_kwargs)
        hist_rows: list[ValueHistogramRow] = [
            hist_query.materialize(r) for r in raw_rows
        ]
        return _build_value_distribution(hist_rows, present_count, top_n)


def validate_database(
    connection: Any,
    graph_definition: GraphDefinition,
    database: str | None = None,
) -> ValidationResult:
    """Validate a Neo4j database against a GraphDefinition."""
    profile = Neo4jInspector().inspect(
        connection, database=database, graph_definition=graph_definition
    )
    return compare_profile_to_definition(profile, graph_definition)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _build_value_distribution(
    hist_rows: list[ValueHistogramRow],
    present_count: int,
    top_n: int,
) -> BoundedDistribution | None:
    """Build a BoundedDistribution from value-histogram query rows.

    The DB query already applies ``LIMIT $top_n``; the inspector receives at most
    ``top_n`` rows.  If the sum of their counts equals ``present_count`` the
    histogram is complete (``sample_complete=True``); otherwise the remainder
    folds into ``other_count`` (ADR-035 §4).

    Completeness is inferred purely from count arithmetic: ``top_total >= present_count``.
    This is correct because every DB row has ``value_count >= 1`` (the GROUP BY
    only produces rows for values that actually exist).  If that invariant ever
    changes — e.g. zero-count rows are introduced, or the signal switches to a
    row-count threshold — the inference must be revisited.

    Returns ``None`` when there are no rows (property has no non-null values).
    """  # NOQA E501
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
