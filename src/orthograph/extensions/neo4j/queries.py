"""Query strategies for Neo4j schema introspection."""

from typing import Protocol


class QueryStrategy(Protocol):
    """Protocol for Neo4j query generation strategies."""

    def node_labels(self) -> str: ...
    def rel_types(self) -> str: ...
    def node_properties(self, label: str) -> str: ...
    def rel_properties(self, rel_type: str) -> str: ...
    def cardinality(self, label: str, rel_type: str) -> str: ...
    def constraints(self) -> str: ...


class ApocQueryStrategy:
    """Uses APOC procedures for rich metadata."""

    def node_labels(self) -> str:
        return "CALL db.labels() YIELD label RETURN label"

    def rel_types(self) -> str:
        return (
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
        )

    def node_properties(self, label: str) -> str:
        return (
            "CALL apoc.meta.nodeTypeProperties({{sample: -1}}) "
            "YIELD nodeType, nodeLabels, propertyName, propertyTypes, "
            "mandatory, propertyObservations, totalObservations "
            "WHERE '{label}' IN nodeLabels "
            "RETURN propertyName, propertyTypes, mandatory, "
            "propertyObservations, totalObservations"
        ).format(label=label)

    def rel_properties(self, rel_type: str) -> str:
        return (
            "CALL apoc.meta.relTypeProperties({{sample: -1}}) "
            "YIELD relType, propertyName, propertyTypes, "
            "mandatory, propertyObservations, totalObservations "
            "WHERE relType = ':`{rel_type}`' "
            "RETURN propertyName, propertyTypes, mandatory, "
            "propertyObservations, totalObservations"
        ).format(rel_type=rel_type)

    def cardinality(self, label: str, rel_type: str) -> str:
        return (
            f"MATCH (n:`{label}`) "
            f"OPTIONAL MATCH (n)-[r:`{rel_type}`]->() "
            "WITH n, count(r) AS degree "
            "RETURN min(degree) AS min_degree, max(degree) AS max_degree, "
            "avg(degree) AS avg_degree, count(n) AS sample_size"
        )

    def constraints(self) -> str:
        return (
            "SHOW CONSTRAINTS YIELD name, type, entityType, "
            "labelsOrTypes, properties, propertyType"
        )


class CypherQueryStrategy:
    """Pure Cypher fallback when APOC is unavailable."""

    def node_labels(self) -> str:
        return "CALL db.labels() YIELD label RETURN label"

    def rel_types(self) -> str:
        return (
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
        )

    def node_properties(self, label: str) -> str:
        return (
            f"MATCH (n:`{label}`) "
            "WITH count(n) AS total "
            f"MATCH (n:`{label}`) "
            "UNWIND keys(n) AS key "
            "WITH key, count(*) AS present, total "
            "RETURN key AS propertyName, [] AS propertyTypes, "
            "present = total AS mandatory, "
            "present AS propertyObservations, total AS totalObservations"
        )

    def rel_properties(self, rel_type: str) -> str:
        return (
            f"MATCH ()-[r:`{rel_type}`]->() "
            "WITH count(r) AS total "
            f"MATCH ()-[r:`{rel_type}`]->() "
            "UNWIND keys(r) AS key "
            "WITH key, count(*) AS present, total "
            "RETURN key AS propertyName, [] AS propertyTypes, "
            "present = total AS mandatory, "
            "present AS propertyObservations, total AS totalObservations"
        )

    def cardinality(self, label: str, rel_type: str) -> str:
        return (
            f"MATCH (n:`{label}`) "
            f"OPTIONAL MATCH (n)-[r:`{rel_type}`]->() "
            "WITH n, count(r) AS degree "
            "RETURN min(degree) AS min_degree, max(degree) AS max_degree, "
            "avg(degree) AS avg_degree, count(n) AS sample_size"
        )

    def constraints(self) -> str:
        return (
            "SHOW CONSTRAINTS YIELD name, type, entityType, "
            "labelsOrTypes, properties, propertyType"
        )
