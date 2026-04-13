"""Memgraph database schema introspection and validation."""

from typing import Any

from orthograph.core.errors import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.extensions._shared import (
    ConstraintInfo,
    IntrospectedSchema,
    PropertyInfo,
    compare_schema,
)


class MemgraphSchemaIntrospector:
    """Introspects a Memgraph database to extract its schema."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    def _run(self, query: str) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results as list of dicts."""
        records, _, _ = self._driver.execute_query(query)
        return [dict(record) for record in records]

    def introspect(self) -> IntrospectedSchema:
        """Orchestrate all introspection queries and return the schema."""
        labels, node_props = self._get_node_properties()
        rel_types, rel_props = self._get_rel_properties()
        constraints = self._get_constraints()

        return IntrospectedSchema(
            node_labels=labels,
            relationship_types=rel_types,
            node_properties=node_props,
            rel_properties=rel_props,
            constraints=constraints,
        )

    def _get_node_properties(
        self,
    ) -> tuple[set[str], dict[str, list[PropertyInfo]]]:
        """Get node labels and properties from Memgraph schema."""
        rows = self._run(
            "CALL schema.node_type_properties() "
            "YIELD nodeType, nodeLabels, mandatory, "
            "propertyName, propertyTypes"
        )
        labels: set[str] = set()
        props: dict[str, list[PropertyInfo]] = {}
        for row in rows:
            # nodeLabels is a list like ["Person"]
            for label in row.get("nodeLabels", []):
                labels.add(label)
            property_name = row.get("propertyName")
            if not property_name:
                continue
            # nodeType looks like ":`Label`"
            raw_type = row["nodeType"]
            label = raw_type.strip(":` ")
            prop = PropertyInfo(
                name=property_name,
                types=row.get("propertyTypes", []),
                mandatory=row.get("mandatory", False),
                observation_count=0,
                total_count=0,
            )
            props.setdefault(label, []).append(prop)
        return labels, props

    def _get_rel_properties(
        self,
    ) -> tuple[set[str], dict[str, list[PropertyInfo]]]:
        """Get relationship types and properties from Memgraph schema."""
        rows = self._run(
            "CALL schema.rel_type_properties() "
            "YIELD relType, mandatory, propertyName, propertyTypes"
        )
        rel_types: set[str] = set()
        props: dict[str, list[PropertyInfo]] = {}
        for row in rows:
            # relType looks like ":`REL_TYPE`"
            raw_type = row["relType"]
            rel_type = raw_type.strip(":` ")
            rel_types.add(rel_type)
            property_name = row.get("propertyName")
            if not property_name:
                continue
            prop = PropertyInfo(
                name=property_name,
                types=row.get("propertyTypes", []),
                mandatory=row.get("mandatory", False),
                observation_count=0,
                total_count=0,
            )
            props.setdefault(rel_type, []).append(prop)
        return rel_types, props

    def _get_constraints(self) -> list[ConstraintInfo]:
        """Retrieve all constraints from Memgraph."""
        rows = self._run("SHOW CONSTRAINT INFO")
        return [
            ConstraintInfo(
                name=None,
                constraint_type=row.get("constraint type", ""),
                entity_type=row.get("entity type", ""),
                labels=[row["label"]] if "label" in row else [],
                properties=row.get("properties", []),
            )
            for row in rows
        ]


def validate_database(
    driver: Any,
    model: GraphDataModel,
) -> ValidationResult:
    """Validate a Memgraph database schema against a GraphDataModel."""
    introspector = MemgraphSchemaIntrospector(driver)
    introspected = introspector.introspect()
    return compare_schema(introspected, model)
