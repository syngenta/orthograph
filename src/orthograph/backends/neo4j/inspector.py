"""Neo4j graph inspector (stateless; connection injected per call)."""

from typing import Any

from orthograph.backends.neo4j.queries import (
    ApocNodePropertiesQuery,
    ApocRelPropertiesQuery,
    CypherNodePropertiesQuery,
    CypherRelPropertiesQuery,
    InspectNeo4jConstraintsQuery,
    InspectNodeLabelsQuery,
    InspectRelTypesQuery,
    NodePropertyRow,
    build_apoc_catalogue,
    build_cypher_catalogue,
)
from orthograph.comparison.engine import compare
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
from orthograph.query.catalogue import QueryCatalogue


class Neo4jInspector(CypherInspector):
    """Inspects a Neo4j database and produces a GraphProfile.

    Stateless: the driver is passed to :meth:`inspect` per call, never stored.

    Parameters
    ----------
    use_apoc:
        ``True``  — use APOC procedures (must be installed).
        ``False`` — use the pure-Cypher fallback.
        ``None``  — auto-detect at ``inspect()`` time (default).
    """

    def __init__(self, use_apoc: bool | None = None) -> None:
        self._use_apoc = use_apoc

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def inspect(self, connection: Any, *, database: str | None = None) -> GraphProfile:
        """Inspect the Neo4j database and return a :class:`GraphProfile`.

        ``database`` is forwarded to ``driver.execute_query`` as ``database_``.
        """
        execute_kwargs: dict[str, Any] = {"database_": database}
        use_apoc, query_catalogue = self._resolve_catalogue(connection, execute_kwargs)

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

        node_profiles: dict[str, NodeTypeProfile] = {}
        for label in sorted(labels):
            node_profiles[label] = self._build_node_profile(
                connection, label, use_apoc, execute_kwargs
            )

        rel_profiles: dict[str, RelationshipTypeProfile] = {}
        for rt in sorted(rel_types):
            rel_profiles[rt] = self._build_rel_profile(
                connection, rt, labels, use_apoc, execute_kwargs
            )

        constraints = self._get_constraints(connection, execute_kwargs)

        return GraphProfile(
            source="neo4j",
            node_type_profiles=node_profiles,
            rel_type_profiles=rel_profiles,
            constraints=constraints,
        )

    # ------------------------------------------------------------------
    # Internal — catalogue selection
    # ------------------------------------------------------------------

    def _resolve_catalogue(
        self, connection: Any, execute_kwargs: dict[str, Any]
    ) -> tuple[bool, QueryCatalogue]:
        """Resolve APOC vs pure-Cypher and build the matching catalogue."""
        use_apoc = self._use_apoc
        if use_apoc is None:
            use_apoc = self._detect_apoc(connection, execute_kwargs)
        query_catalogue = (
            build_apoc_catalogue() if use_apoc else build_cypher_catalogue()
        )
        return use_apoc, query_catalogue

    def _detect_apoc(
        self, connection: Any, execute_kwargs: dict[str, Any] | None = None
    ) -> bool:
        """Return True if apoc.meta procedures are available."""
        rows = self._run(
            connection,
            "SHOW PROCEDURES YIELD name"
            " WHERE name STARTS WITH 'apoc.meta'"
            " RETURN count(name) AS cnt",
            **(execute_kwargs or {}),
        )
        return bool(rows and rows[0]["cnt"] > 0)

    # ------------------------------------------------------------------
    # Internal — profile builders
    # ------------------------------------------------------------------

    def _build_node_profile(
        self,
        connection: Any,
        label: str,
        use_apoc: bool,
        execute_kwargs: dict[str, Any],
    ) -> NodeTypeProfile:
        query_cls = ApocNodePropertiesQuery if use_apoc else CypherNodePropertiesQuery
        rows: list[NodePropertyRow] = self._run_query(
            connection, query_cls, identifiers={"label": label}, **execute_kwargs
        )
        props: dict[str, PropertyProfile] = {}
        total_count = 0
        for row in rows:
            props[row.property_name] = PropertyProfile(
                name=row.property_name,
                present_count=row.property_observations,
                total_count=row.total_observations,
                observed_types=row.property_types,
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
        use_apoc: bool,
        execute_kwargs: dict[str, Any],
    ) -> RelationshipTypeProfile:
        query_cls = ApocRelPropertiesQuery if use_apoc else CypherRelPropertiesQuery
        rows: list[NodePropertyRow] = self._run_query(
            connection, query_cls, identifiers={"rel_type": rel_type}, **execute_kwargs
        )
        props: dict[str, PropertyProfile] = {}
        total_count = 0
        for row in rows:
            props[row.property_name] = PropertyProfile(
                name=row.property_name,
                present_count=row.property_observations,
                total_count=row.total_observations,
                observed_types=row.property_types,
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
    return compare(profile, graph_definition)
