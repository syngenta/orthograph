"""Query helpers for Memgraph schema introspection."""


class MemgraphQueries:
    """Memgraph-specific Cypher queries for schema introspection."""

    def node_properties(self) -> str:
        return (
            "CALL schema.node_type_properties() "
            "YIELD nodeType, nodeLabels, mandatory, "
            "propertyName, propertyTypes"
        )

    def rel_properties(self) -> str:
        return (
            "CALL schema.rel_type_properties() "
            "YIELD relType, mandatory, propertyName, propertyTypes"
        )

    def constraints(self) -> str:
        return "SHOW CONSTRAINT INFO"

    def cardinality(self, label: str, rel_type: str) -> str:
        return (
            f"MATCH (n:`{label}`) "
            f"OPTIONAL MATCH (n)-[r:`{rel_type}`]->() "
            "WITH n, count(r) AS degree "
            "RETURN min(degree) AS min_degree, max(degree) AS max_degree, "
            "avg(degree) AS avg_degree, count(n) AS sample_size"
        )
