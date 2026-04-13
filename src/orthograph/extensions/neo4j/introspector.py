"""Neo4j database schema introspection and validation."""

from typing import Any

from orthograph.core.errors import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.extensions._shared import (
    ConstraintInfo,
    IntrospectedSchema,
    PropertyInfo,
    compare_schema,
)


class Neo4jSchemaIntrospector:
    """Introspects a Neo4j database to extract its schema."""

    def __init__(self, driver: Any, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    def _run(self, query: str) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results as list of dicts."""
        records, _, _ = self._driver.execute_query(query, database_=self._database)
        return [dict(record) for record in records]

    def has_apoc(self) -> bool:
        """Check if APOC procedures are available."""
        rows = self._run(
            "SHOW PROCEDURES YIELD name "
            "WHERE name STARTS WITH 'apoc.meta' "
            "RETURN count(name) AS cnt"
        )
        return bool(rows and rows[0]["cnt"] > 0)

    def introspect(self) -> IntrospectedSchema:
        """Orchestrate all introspection queries and return the schema."""
        labels = self._get_labels()
        rel_types = self._get_rel_types()
        constraints = self._get_constraints()

        if self.has_apoc():
            node_props = self._get_node_properties_apoc()
            rel_props = self._get_rel_properties_apoc()
        else:
            node_props = self._get_node_properties_fallback(labels)
            rel_props = {}

        return IntrospectedSchema(
            node_labels=labels,
            relationship_types=rel_types,
            node_properties=node_props,
            rel_properties=rel_props,
            constraints=constraints,
        )

    def _get_labels(self) -> set[str]:
        """Retrieve all node labels from the database."""
        rows = self._run("CALL db.labels() YIELD label RETURN label")
        return {row["label"] for row in rows}

    def _get_rel_types(self) -> set[str]:
        """Retrieve all relationship types from the database."""
        rows = self._run(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
        )
        return {row["relationshipType"] for row in rows}

    def _get_node_properties_apoc(self) -> dict[str, list[PropertyInfo]]:
        """Get node properties using APOC meta procedures."""
        rows = self._run("CALL apoc.meta.nodeTypeProperties({sample: -1})")
        result: dict[str, list[PropertyInfo]] = {}
        for row in rows:
            # nodeType looks like ":`Label`"
            raw_label = row["nodeType"]
            label = raw_label.strip(":` ")
            prop = PropertyInfo(
                name=row["propertyName"],
                types=row.get("propertyTypes", []),
                mandatory=row.get("mandatory", False),
                observation_count=row.get("propertyObservations", 0),
                total_count=row.get("totalObservations", 0),
            )
            result.setdefault(label, []).append(prop)
        return result

    def _get_rel_properties_apoc(self) -> dict[str, list[PropertyInfo]]:
        """Get relationship properties using APOC meta procedures."""
        rows = self._run("CALL apoc.meta.relTypeProperties({sample: -1})")
        result: dict[str, list[PropertyInfo]] = {}
        for row in rows:
            # relType looks like ":`REL_TYPE`"
            raw_type = row["relType"]
            rel_type = raw_type.strip(":` ")
            prop = PropertyInfo(
                name=row["propertyName"],
                types=row.get("propertyTypes", []),
                mandatory=row.get("mandatory", False),
                observation_count=row.get("propertyObservations", 0),
                total_count=row.get("totalObservations", 0),
            )
            result.setdefault(rel_type, []).append(prop)
        return result

    def _get_node_properties_fallback(
        self, labels: set[str]
    ) -> dict[str, list[PropertyInfo]]:
        """Get node properties using pure Cypher (no APOC)."""
        result: dict[str, list[PropertyInfo]] = {}
        for label in sorted(labels):
            rows = self._run(
                f"MATCH (n:`{label}`) "
                "UNWIND keys(n) AS key "
                "WITH key, count(*) AS cnt, count(n) AS total "
                "RETURN key, cnt, total, cnt = total AS mandatory"
            )
            if rows:
                result[label] = [
                    PropertyInfo(
                        name=row["key"],
                        types=[],
                        mandatory=row["mandatory"],
                        observation_count=row["cnt"],
                        total_count=row["total"],
                    )
                    for row in rows
                ]
        return result

    def _get_constraints(self) -> list[ConstraintInfo]:
        """Retrieve all constraints from the database."""
        rows = self._run(
            "SHOW CONSTRAINTS YIELD name, type, entityType, "
            "labelsOrTypes, properties, propertyType"
        )
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
    """Validate a Neo4j database schema against a GraphDataModel."""
    introspector = Neo4jSchemaIntrospector(driver, database)
    introspected = introspector.introspect()
    return compare_schema(introspected, model)
