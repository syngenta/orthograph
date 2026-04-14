# Neo4j Extension

> Read `overview.md` first for the two-phase architecture.

## Files

| File | Content |
|------|---------|
| `inspector.py` | `Neo4jInspector(GraphInspector)` + `validate_database()` |
| `queries.py` | `QueryStrategy` protocol + `ApocQueryStrategy` + `CypherQueryStrategy` |
| `result_adapter.py` | `validate_result()`, `node_to_dict()`, `rel_to_dict()` |

## Neo4jInspector

```python
inspector = Neo4jInspector(driver, database="neo4j", strategy=None)
profile = inspector.inspect()
```

- Accepts a `neo4j.Driver` (typed as `Any` to avoid hard import)
- Auto-detects APOC availability via `SHOW PROCEDURES`
- Falls back to `CypherQueryStrategy` if APOC unavailable
- User can override: `Neo4jInspector(driver, strategy=ApocQueryStrategy())`
- Inspects: labels, rel types, properties (types + mandatory + counts), constraints

## QueryStrategy Protocol

```python
class QueryStrategy(Protocol):
    def node_labels(self) -> str: ...
    def rel_types(self) -> str: ...
    def node_properties(self, label: str) -> str: ...
    def rel_properties(self, rel_type: str) -> str: ...
    def cardinality(self, label: str, rel_type: str) -> str: ...
    def constraints(self) -> str: ...
```

Each method returns a Cypher query string. The inspector executes it.

| Strategy | When used | Data richness |
|----------|-----------|---------------|
| `ApocQueryStrategy` | APOC installed | Full: types, mandatory flag, observation counts |
| `CypherQueryStrategy` | No APOC | Limited: no property types, counts only |

## Result Adapter

Converts neo4j driver result objects to orthograph format:

```python
result = validate_result(records, model, result_model=None)
```

- `node_to_dict()`: extracts `__label__` from `node.labels`, properties from `node.items()`
- `rel_to_dict()`: extracts `__label__` from `rel.type`, resolves UIDs from endpoints
- Multi-label resolution: picks the label matching the model; falls back to first alphabetically
- UID resolution: uses `model.__uid_field__`; falls back to `node.element_id`
- Duck-typed: uses `hasattr` + `isinstance(labels, frozenset)` checks, no neo4j import needed

## Key Cypher Queries

### APOC path
- Labels: `CALL db.labels() YIELD label`
- Properties: `CALL apoc.meta.nodeTypeProperties({sample: -1}) ...`
- Constraints: `SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties, propertyType`

### Fallback path
- Properties: `MATCH (n:Label) UNWIND keys(n) AS key WITH key, count(*) AS present ...`
- Cardinality: `MATCH (n:Label) OPTIONAL MATCH (n)-[r:TYPE]->() WITH n, count(r) AS degree RETURN min(degree), max(degree), avg(degree), count(n)`
