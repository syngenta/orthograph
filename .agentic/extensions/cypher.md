# Cypher Extension

> Read `overview.md` first for the two-phase architecture.

## Files

| File | Content |
|------|---------|
| `generator.py` | `CypherGenerator` -- query construction from model |
| `parser.py` | `parse_cypher()`, `validate_cypher()` -- query parsing and validation |

## CypherGenerator

Generates Cypher queries from a `GraphDataModel`:

```python
gen = CypherGenerator(model)
query, params = gen.merge_node({"__label__": "Person", "name": "Alice", "age": 30})
query, params = gen.create_relationship({...})
constraints = gen.generate_constraints()
match_query = gen.match_node(Person)
pattern_query = gen.match_relationship(ActedIn)
```

| Method | Returns |
|--------|---------|
| `merge_node(data)` | MERGE using uid_field, SET other props |
| `create_node(data)` | CREATE with all props |
| `create_relationship(data)` | MATCH endpoints, CREATE rel |
| `merge_relationship(data)` | MATCH endpoints, MERGE rel |
| `generate_constraints()` | Uniqueness constraints for all uid_fields |
| `match_node(node_type)` | MATCH (n:Label) RETURN n |
| `match_relationship(rel_type)` | MATCH (a:Src)-[r:TYPE]->(b:Tgt) RETURN a, r, b |

## Cypher Parser

Parses Cypher query strings and validates them against a model.
Uses graphglot (100% openCypher TCK conformant).

### Strategy Pattern

```python
class CypherParserStrategy(Protocol):
    def parse(self, query: str) -> CypherQueryInfo: ...

class GraphglotParser:
    """Default implementation using graphglot."""
```

User can provide a custom parser implementation.

### `parse_cypher()`

```python
info = parse_cypher("MATCH (n:Person)-[r:ACTED_IN]->(m:Movie) RETURN n")
# info.node_labels == {"Person", "Movie"}
# info.relationship_types == {"ACTED_IN"}
# info.variable_bindings == {"n": "Person", "m": "Movie", "r": "ACTED_IN"}
# info.query_intent == "read"
# info.patterns == [PatternInfo(source="Person", rel="ACTED_IN", target="Movie")]
```

### `validate_cypher()`

```python
result = validate_cypher(query, model)
```

4 validation codes:

| Code | Meaning |
|------|---------|
| `QUERY_UNKNOWN_NODE_LABEL` | Label in query not in model |
| `QUERY_UNKNOWN_REL_TYPE` | Rel type in query not in model |
| `QUERY_UNKNOWN_PROPERTY` | Property access on variable not in model |
| `QUERY_INVALID_ENDPOINT` | Pattern endpoints don't match model |

### External Dependency

`graphglot >= 0.9` -- pure Python, pip-installable.
Only pulled in when importing `orthograph.extensions.cypher.parser`.
The `CypherGenerator` has no external dependencies beyond core.
