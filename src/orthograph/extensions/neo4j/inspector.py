"""Neo4j graph inspector using the GraphProfile model.

``QueryStrategy``, ``ApocQueryStrategy``, and ``CypherQueryStrategy`` have been
retired (ADR-009 / E17 T8).  APOC vs. pure-Cypher is now expressed as two sets
of typed ``CypherReadQuery`` subclasses selected at construction via the
``use_apoc`` parameter.

BREAKING CHANGE (E17 T8): the ``strategy: QueryStrategy | None`` constructor
parameter is removed.  Use ``use_apoc=True`` (APOC, default), ``use_apoc=False``
(pure Cypher), or ``use_apoc=None`` (auto-detect, default behaviour).
"""

from typing import Any

from orthograph.catalogue.registry import QueryCatalogue
from orthograph.core.exceptions import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.extensions.base import GraphInspector
from orthograph.extensions.cypher.bindings import NoParams
from orthograph.extensions.models import (
    CardinalityStats,
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)
from orthograph.extensions.neo4j.queries import (
    ApocNodePropertiesQuery,
    ApocRelPropertiesQuery,
    CypherNodePropertiesQuery,
    CypherRelPropertiesQuery,
    InspectCardinalityQuery,
    InspectEndpointLabelsQuery,
    InspectNeo4jConstraintsQuery,
    InspectNodeLabelsQuery,
    InspectRelTypesQuery,
    NodePropertyRow,
    build_apoc_catalogue,
    build_cypher_catalogue,
)
from orthograph.extensions.validation import validate_profile


class Neo4jInspector(GraphInspector):
    """Inspects a Neo4j database and produces a GraphProfile.

    Parameters
    ----------
    driver:
        A Neo4j driver instance (``neo4j.GraphDatabase.driver(...)``).
    database:
        Optional database name passed to ``driver.execute_query``.
    use_apoc:
        ``True``  — use APOC procedures (must be installed).
        ``False`` — use pure-Cypher fallback.
        ``None``  — auto-detect at first ``inspect()`` call (default).
    """

    def __init__(
        self,
        driver: Any,
        database: str | None = None,
        use_apoc: bool | None = None,
    ) -> None:
        self._driver = driver
        self._database = database
        self._use_apoc = use_apoc
        self._catalogue: QueryCatalogue | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def inspect(self) -> GraphProfile:
        """Inspect the Neo4j database and return a complete GraphProfile."""
        self._ensure_catalogue()

        labels = self._get_labels()
        rel_types = self._get_rel_types()

        node_profiles: dict[str, NodeTypeProfile] = {}
        for label in sorted(labels):
            node_profiles[label] = self._build_node_profile(label)

        rel_profiles: dict[str, RelationshipTypeProfile] = {}
        for rt in sorted(rel_types):
            rel_profiles[rt] = self._build_rel_profile(rt, labels)

        constraints = self._get_constraints()

        return GraphProfile(
            source="neo4j",
            node_type_profiles=node_profiles,
            rel_type_profiles=rel_profiles,
            constraints=constraints,
        )

    # ------------------------------------------------------------------
    # Internal — catalogue lifecycle
    # ------------------------------------------------------------------

    def _ensure_catalogue(self) -> None:
        """Build the internal catalogue if not already built."""
        if self._catalogue is not None:
            return
        if self._use_apoc is None:
            self._use_apoc = self._detect_apoc()
        self._catalogue = (
            build_apoc_catalogue() if self._use_apoc else build_cypher_catalogue()
        )

    def _detect_apoc(self) -> bool:
        """Return True if apoc.meta procedures are available."""
        rows = self._run(
            "SHOW PROCEDURES YIELD name"
            " WHERE name STARTS WITH 'apoc.meta'"
            " RETURN count(name) AS cnt"
        )
        return bool(rows and rows[0]["cnt"] > 0)

    # ------------------------------------------------------------------
    # Internal — query execution helpers
    # ------------------------------------------------------------------

    def _run(self, query: str) -> list[dict[str, Any]]:
        """Execute a raw Cypher string and return results as list of dicts.

        This is the single driver I/O seam.  All typed query execution routes
        through ``_run_query`` which calls this method.
        """
        records, _, _ = self._driver.execute_query(
            query,
            database_=self._database,
        )
        return [dict(record) for record in records]

    def _run_query(
        self, query: Any, identifiers: dict[str, str] | None = None
    ) -> list[Any]:
        """Build a typed query instance, render its Cypher, and execute it.

        Parameters
        ----------
        query:
            A ``CypherReadQuery`` *class* (not instance).  A fresh instance is
            created per call with the supplied ``identifiers``.
        identifiers:
            Identifier values to bind (e.g. ``{"label": "Person"}``).  ``None``
            is equivalent to ``{}`` (no identifiers).
        """
        instance = query(identifiers=identifiers or {})
        cypher, _ = instance.build(NoParams())
        rows = self._run(cypher)
        return [instance.materialize(row) for row in rows]

    # ------------------------------------------------------------------
    # Internal — profile builders
    # ------------------------------------------------------------------

    def _get_labels(self) -> set[str]:
        assert self._catalogue is not None
        rows = self._run_query(InspectNodeLabelsQuery)
        return {row.label for row in rows}

    def _get_rel_types(self) -> set[str]:
        assert self._catalogue is not None
        rows = self._run_query(InspectRelTypesQuery)
        return {row.relationship_type for row in rows}

    def _build_node_profile(self, label: str) -> NodeTypeProfile:
        assert self._use_apoc is not None
        query_cls = (
            ApocNodePropertiesQuery if self._use_apoc else CypherNodePropertiesQuery
        )
        rows: list[NodePropertyRow] = self._run_query(
            query_cls, identifiers={"label": label}
        )
        props: dict[str, PropertyProfile] = {}
        total_count = 0
        for row in rows:
            props[row.property_name] = PropertyProfile(
                name=row.property_name,
                present_count=row.property_observations,
                total_count=row.total_observations,
                observed_types=row.property_types,
            )
            if row.total_observations > total_count:
                total_count = row.total_observations
        return NodeTypeProfile(label=label, count=total_count, property_profiles=props)

    def _build_rel_profile(
        self,
        rel_type: str,
        labels: set[str],
    ) -> RelationshipTypeProfile:
        assert self._use_apoc is not None
        query_cls = (
            ApocRelPropertiesQuery if self._use_apoc else CypherRelPropertiesQuery
        )
        rows: list[NodePropertyRow] = self._run_query(
            query_cls, identifiers={"rel_type": rel_type}
        )
        props: dict[str, PropertyProfile] = {}
        total_count = 0
        for row in rows:
            props[row.property_name] = PropertyProfile(
                name=row.property_name,
                present_count=row.property_observations,
                total_count=row.total_observations,
                observed_types=row.property_types,
            )
            if row.total_observations > total_count:
                total_count = row.total_observations

        # Endpoint labels (E18.1) — must run BEFORE cardinality so we know
        # which labels are sources and can skip target-only labels.
        source_labels: set[str] = set()
        target_labels: set[str] = set()
        endpoint_rows = self._run_query(
            InspectEndpointLabelsQuery, identifiers={"rel_type": rel_type}
        )
        for erow in endpoint_rows:
            source_labels.update(erow.source_labels)
            target_labels.update(erow.target_labels)

        # Cardinality — iterate confirmed source labels only (not all node
        # labels); use the first label that has at least one relationship.
        # Falling back to all labels would give degree=0 for target-only labels
        # and produce a misleading min=0/max=0 result.
        card_stats: CardinalityStats | None = None
        candidates = sorted(source_labels) if source_labels else sorted(labels)
        for label in candidates:
            card_rows: list[CardinalityStats] = self._run_query(
                InspectCardinalityQuery,
                identifiers={"label": label, "rel_type": rel_type},
            )
            if card_rows and card_rows[0].sample_size > 0:
                card_stats = card_rows[0]
                break

        return RelationshipTypeProfile(
            rel_type=rel_type,
            count=total_count,
            property_profiles=props,
            cardinality_stats=card_stats,
            source_labels=source_labels,
            target_labels=target_labels,
        )

    def _get_constraints(self) -> list[ConstraintInfo]:
        rows = self._run_query(InspectNeo4jConstraintsQuery)
        return list(rows)  # materialize() already returns ConstraintInfo instances


def validate_database(
    driver: Any,
    model: GraphDataModel,
    database: str | None = None,
) -> ValidationResult:
    """Validate a Neo4j database against a GraphDataModel."""
    inspector = Neo4jInspector(driver, database)
    profile = inspector.inspect()
    return validate_profile(profile, model)
