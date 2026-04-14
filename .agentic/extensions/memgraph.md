# Memgraph Extension

> Read `overview.md` first for the two-phase architecture.

## Files

| File | Content |
|------|---------|
| `inspector.py` | `MemgraphInspector(GraphInspector)` + `validate_database()` |
| `queries.py` | `MemgraphQueries` class with Memgraph-specific Cypher |

## MemgraphInspector

```python
inspector = MemgraphInspector(driver)
profile = inspector.inspect()
```

- Accepts a `neo4j.Driver` (Memgraph uses Bolt protocol, same driver)
- No multi-database support (Memgraph is single-database)
- Uses Memgraph's built-in `schema.*` procedures (no APOC equivalent needed)

## Key Differences from Neo4j

| Aspect | Neo4j | Memgraph |
|--------|-------|----------|
| Driver | `neo4j` Python driver | Same `neo4j` driver (Bolt protocol) |
| Database param | `database="neo4j"` supported | Not supported (single DB) |
| Property introspection | APOC or pure Cypher fallback | Built-in: `schema.node_type_properties()` |
| Constraint syntax | `SHOW CONSTRAINTS YIELD ...` | `SHOW CONSTRAINT INFO` |
| Observation counts | Available via APOC | Not provided (set to 1/0) |
| APOC detection | Needed | Not applicable |

## Memgraph Queries

```python
class MemgraphQueries:
    def node_properties(self) -> str:
        "CALL schema.node_type_properties() YIELD nodeType, nodeLabels, mandatory, propertyName, propertyTypes"
    def rel_properties(self) -> str:
        "CALL schema.rel_type_properties() YIELD relType, mandatory, propertyName, propertyTypes"
    def constraints(self) -> str:
        "SHOW CONSTRAINT INFO"
    def cardinality(self, label, rel_type) -> str:
        # Same pure Cypher as Neo4j fallback
```

## Result Validation

Memgraph uses the same `neo4j` driver, so `neo4j/result_adapter.py` works
directly with Memgraph query results. No separate result adapter needed.
