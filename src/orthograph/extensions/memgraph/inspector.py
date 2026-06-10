"""Memgraph graph inspector using the GraphProfile model."""

from typing import Any

from orthograph.core.exceptions import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.extensions.base import GraphInspector
from orthograph.extensions.memgraph.queries import MemgraphQueries
from orthograph.extensions.models import (
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)
from orthograph.extensions.validation import validate_profile


class MemgraphInspector(GraphInspector):
    """Inspects a Memgraph database and produces a GraphProfile."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver
        self._queries = MemgraphQueries()

    def inspect(self) -> GraphProfile:
        """Inspect the Memgraph database and return a complete GraphProfile."""
        node_profiles = self._build_node_profiles()
        rel_profiles = self._build_rel_profiles()
        constraints = self._get_constraints()

        return GraphProfile(
            source="memgraph",
            node_type_profiles=node_profiles,
            rel_type_profiles=rel_profiles,
            constraints=constraints,
        )

    def _run(self, query: str) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results as list of dicts."""
        records, _, _ = self._driver.execute_query(query)
        return [dict(record) for record in records]

    def _build_node_profiles(self) -> dict[str, NodeTypeProfile]:
        rows = self._run(self._queries.node_properties())

        # Collect labels and per-label properties
        label_props: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            for label in row.get("nodeLabels", []):
                label_props.setdefault(label, [])

            property_name = row.get("propertyName")
            if not property_name:
                continue

            raw_type = row["nodeType"]
            label = raw_type.strip(":` ")
            label_props.setdefault(label, []).append(row)

        profiles: dict[str, NodeTypeProfile] = {}
        for label, rows_for_label in sorted(label_props.items()):
            props: dict[str, PropertyProfile] = {}
            for r in rows_for_label:
                name = r["propertyName"]
                types = r.get("propertyTypes", [])
                mandatory = r.get("mandatory", False)
                # Memgraph doesn't provide observation counts
                props[name] = PropertyProfile(
                    name=name,
                    present_count=1 if mandatory else 0,
                    total_count=1,
                    observed_types=types if isinstance(types, list) else [types],
                )
            profiles[label] = NodeTypeProfile(
                label=label,
                count=0,
                property_profiles=props,
            )

        return profiles

    def _build_rel_profiles(self) -> dict[str, RelationshipTypeProfile]:
        rows = self._run(self._queries.rel_properties())

        type_rows: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            raw_type = row["relType"]
            rel_type = raw_type.strip(":` ")
            type_rows.setdefault(rel_type, []).append(row)

        profiles: dict[str, RelationshipTypeProfile] = {}
        for rel_type, rows_for_type in sorted(type_rows.items()):
            props: dict[str, PropertyProfile] = {}
            for r in rows_for_type:
                name = r.get("propertyName")
                if not name:
                    continue
                types = r.get("propertyTypes", [])
                mandatory = r.get("mandatory", False)
                props[name] = PropertyProfile(
                    name=name,
                    present_count=1 if mandatory else 0,
                    total_count=1,
                    observed_types=types if isinstance(types, list) else [types],
                )
            profiles[rel_type] = RelationshipTypeProfile(
                rel_type=rel_type,
                count=0,
                property_profiles=props,
            )

        return profiles

    def _get_constraints(self) -> list[ConstraintInfo]:
        rows = self._run(self._queries.constraints())
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
    """Validate a Memgraph database against a GraphDataModel."""
    inspector = MemgraphInspector(driver)
    profile = inspector.inspect()
    return validate_profile(profile, model)
