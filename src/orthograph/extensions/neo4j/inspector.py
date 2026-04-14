"""Neo4j graph inspector using the GraphProfile model."""

from typing import Any

from orthograph.core.errors import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.extensions.base import GraphInspector
from orthograph.extensions.models import (
    CardinalityStats,
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)
from orthograph.extensions.neo4j.queries import (
    ApocQueryStrategy,
    CypherQueryStrategy,
    QueryStrategy,
)
from orthograph.extensions.validation import validate_profile


class Neo4jInspector(GraphInspector):
    """Inspects a Neo4j database and produces a GraphProfile."""

    def __init__(
        self,
        driver: Any,
        database: str | None = None,
        strategy: QueryStrategy | None = None,
    ) -> None:
        self._driver = driver
        self._database = database
        self._strategy = strategy

    def inspect(self) -> GraphProfile:
        """Inspect the Neo4j database and return a complete GraphProfile."""
        strategy = self._strategy or self._detect_strategy()

        labels = self._get_labels(strategy)
        rel_types = self._get_rel_types(strategy)

        node_profiles: dict[str, NodeTypeProfile] = {}
        for label in sorted(labels):
            node_profiles[label] = self._build_node_profile(label, strategy)

        rel_profiles: dict[str, RelationshipTypeProfile] = {}
        for rt in sorted(rel_types):
            rel_profiles[rt] = self._build_rel_profile(
                rt,
                labels,
                strategy,
            )

        constraints = self._get_constraints(strategy)

        return GraphProfile(
            source="neo4j",
            node_type_profiles=node_profiles,
            rel_type_profiles=rel_profiles,
            constraints=constraints,
        )

    def _run(self, query: str) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results as list of dicts."""
        records, _, _ = self._driver.execute_query(
            query,
            database_=self._database,
        )
        return [dict(record) for record in records]

    def _detect_strategy(self) -> QueryStrategy:
        """Detect whether APOC is available and return the right strategy."""
        rows = self._run(
            "SHOW PROCEDURES YIELD name "
            "WHERE name STARTS WITH 'apoc.meta' "
            "RETURN count(name) AS cnt"
        )
        has_apoc = bool(rows and rows[0]["cnt"] > 0)
        if has_apoc:
            return ApocQueryStrategy()
        return CypherQueryStrategy()

    def _get_labels(self, strategy: QueryStrategy) -> set[str]:
        rows = self._run(strategy.node_labels())
        return {row["label"] for row in rows}

    def _get_rel_types(self, strategy: QueryStrategy) -> set[str]:
        rows = self._run(strategy.rel_types())
        return {row["relationshipType"] for row in rows}

    def _build_node_profile(
        self,
        label: str,
        strategy: QueryStrategy,
    ) -> NodeTypeProfile:
        rows = self._run(strategy.node_properties(label))
        props: dict[str, PropertyProfile] = {}
        total_count = 0
        for row in rows:
            name = row["propertyName"]
            obs = row.get("propertyObservations", 0)
            total = row.get("totalObservations", 0)
            types = row.get("propertyTypes", [])
            if isinstance(types, list):
                observed_types = types
            else:
                observed_types = [types] if types else []
            props[name] = PropertyProfile(
                name=name,
                present_count=obs,
                total_count=total,
                observed_types=observed_types,
            )
            if total > total_count:
                total_count = total
        return NodeTypeProfile(
            label=label,
            count=total_count,
            property_profiles=props,
        )

    def _build_rel_profile(
        self,
        rel_type: str,
        labels: set[str],
        strategy: QueryStrategy,
    ) -> RelationshipTypeProfile:
        rows = self._run(strategy.rel_properties(rel_type))
        props: dict[str, PropertyProfile] = {}
        total_count = 0
        for row in rows:
            name = row["propertyName"]
            obs = row.get("propertyObservations", 0)
            total = row.get("totalObservations", 0)
            types = row.get("propertyTypes", [])
            if isinstance(types, list):
                observed_types = types
            else:
                observed_types = [types] if types else []
            props[name] = PropertyProfile(
                name=name,
                present_count=obs,
                total_count=total,
                observed_types=observed_types,
            )
            if total > total_count:
                total_count = total

        # Collect cardinality for each source label
        card_stats: CardinalityStats | None = None
        for label in sorted(labels):
            card_rows = self._run(strategy.cardinality(label, rel_type))
            if card_rows and card_rows[0]["sample_size"] > 0:
                r = card_rows[0]
                card_stats = CardinalityStats(
                    min_degree=r["min_degree"],
                    max_degree=r["max_degree"],
                    avg_degree=float(r["avg_degree"]),
                    sample_size=r["sample_size"],
                )
                break  # use first label with data

        return RelationshipTypeProfile(
            rel_type=rel_type,
            count=total_count,
            property_profiles=props,
            cardinality_stats=card_stats,
        )

    def _get_constraints(
        self,
        strategy: QueryStrategy,
    ) -> list[ConstraintInfo]:
        rows = self._run(strategy.constraints())
        return [
            ConstraintInfo(
                name=row.get("name"),
                constraint_type=row["type"],
                entity_type=row["entityType"],
                labels=row.get("labelsOrTypes", []),
                properties=row.get("properties", []),
                property_type=row.get("propertyType"),
            )
            for row in rows
        ]


def validate_database(
    driver: Any,
    model: GraphDataModel,
    database: str | None = None,
) -> ValidationResult:
    """Validate a Neo4j database against a GraphDataModel."""
    inspector = Neo4jInspector(driver, database)
    profile = inspector.inspect()
    return validate_profile(profile, model)
