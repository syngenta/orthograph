"""Neo4j graph inspector (stateless; connection injected per call)."""

import warnings
from enum import Enum
from typing import Any

from orthograph.backends.neo4j.queries import (
    ApocNodePropertiesQuery,
    ApocRelPropertiesQuery,
    CypherNodePropertiesQuery,
    CypherRelPropertiesQuery,
    DbSchemaNodeTypesQuery,
    DbSchemaRelTypesQuery,
    InspectNeo4jConstraintsQuery,
    InspectNodeLabelsQuery,
    InspectRelTypesQuery,
    NodePropertyRow,
)
from orthograph.comparison.engine import compare_profile_to_definition
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.inspection import CypherInspector
from orthograph.graph_profile.models import (
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)
from orthograph.graph_profile.queries.shared import (
    InspectCardinalityQuery,
    InspectEndpointLabelsQuery,
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

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def inspect(self, connection: Any, *, database: str | None = None) -> GraphProfile:
        """Inspect the Neo4j database and return a :class:`GraphProfile`.

        ``database`` is forwarded to ``driver.execute_query`` as ``database_``.
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

        node_profiles: dict[str, NodeTypeProfile] = {}
        for label in sorted(labels):
            node_profiles[label] = self._build_node_profile(
                connection, label, strategy, node_type_map, execute_kwargs
            )

        rel_profiles: dict[str, RelationshipTypeProfile] = {}
        for rt in sorted(rel_types):
            rel_profiles[rt] = self._build_rel_profile(
                connection, rt, labels, strategy, rel_type_map, execute_kwargs
            )

        constraints = self._get_constraints(connection, execute_kwargs)

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
        schema_types = node_type_map.get(label, {})
        props: dict[str, PropertyProfile] = {}
        total_count = 0
        for row in rows:
            if row.property_name is None:
                continue
            observed_types = (
                schema_types.get(row.property_name, [])
                if strategy is Neo4jInspectionStrategy.SCHEMA
                else row.property_types
            )
            props[row.property_name] = PropertyProfile(
                name=row.property_name,
                present_count=row.property_observations,
                total_count=row.total_observations,
                observed_types=observed_types,
                # TODO (ADR-015 B1): populate observed_type_counts once a query
                # returns per-type value counts (APOC currently returns only
                # distinct type names in propertyTypes, not per-type counts).
            )
            if row.total_observations > total_count:
                total_count = row.total_observations
        return NodeTypeProfile(label=label, count=total_count, property_profiles=props)

    def _build_rel_profile(
        self,
        connection: Any,
        rel_type: str,
        labels: set[str],
        strategy: Neo4jInspectionStrategy,
        rel_type_map: SchemaTypeMap,
        execute_kwargs: dict[str, Any],
    ) -> RelationshipTypeProfile:
        query_cls = (
            ApocRelPropertiesQuery
            if strategy is Neo4jInspectionStrategy.APOC
            else CypherRelPropertiesQuery
        )
        rows: list[NodePropertyRow] = self._run_query(
            connection, query_cls, identifiers={"rel_type": rel_type}, **execute_kwargs
        )
        schema_types = rel_type_map.get(rel_type, {})
        props: dict[str, PropertyProfile] = {}
        total_count = 0
        for row in rows:
            if row.property_name is None:
                continue
            observed_types = (
                schema_types.get(row.property_name, [])
                if strategy is Neo4jInspectionStrategy.SCHEMA
                else row.property_types
            )
            props[row.property_name] = PropertyProfile(
                name=row.property_name,
                present_count=row.property_observations,
                total_count=row.total_observations,
                observed_types=observed_types,
                # TODO (ADR-015 B1): populate observed_type_counts once a query
                # returns per-type value counts (APOC currently returns only
                # distinct type names in propertyTypes, not per-type counts).
            )
            if row.total_observations > total_count:
                total_count = row.total_observations

        base = RelationshipTypeProfile(
            rel_type=rel_type, count=total_count, property_profiles=props
        )
        return self._enrich_with_endpoints_and_cardinality(
            connection,
            base,
            InspectEndpointLabelsQuery,
            InspectCardinalityQuery,
            fallback_labels=labels,
            **execute_kwargs,
        )

    def _get_constraints(
        self, connection: Any, execute_kwargs: dict[str, Any]
    ) -> list[ConstraintInfo]:
        rows = self._run_query(
            connection, InspectNeo4jConstraintsQuery, **execute_kwargs
        )
        return list(rows)  # materialize() already returns ConstraintInfo instances


def validate_database(
    connection: Any,
    graph_definition: GraphDefinition,
    database: str | None = None,
) -> ValidationResult:
    """Validate a Neo4j database against a GraphDefinition."""
    profile = Neo4jInspector().inspect(connection, database=database)
    return compare_profile_to_definition(profile, graph_definition)
