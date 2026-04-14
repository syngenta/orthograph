# Orthograph Extensions Plan: Database Validation, Query Parsing, Result Validation

## Context

This plan defines three validation mechanisms for graph database extensions:

1. **Database schema validation** -- introspect a live database (Neo4j/Memgraph) and validate it against a GraphDataModel
2. **Cypher query validation** -- parse a Cypher query string and check it against a GraphDataModel (offline, no DB needed)
3. **Query result validation** -- validate the output of a neo4j driver query against a GraphDataModel

All three share a common validation infrastructure with the existing NetworkX extension.

---

## Architecture: Shared Validation Core

Currently, `GraphValidator` is the validation engine. The NetworkX extension
converts nx graph data into the dict format that `GraphValidator.validate()`
accepts. The same pattern applies to all new extensions: each adapter converts
its source data into the common format, then delegates to `GraphValidator`.

```
                          ┌─────────────────────┐
                          │   GraphDataModel     │
                          │  (schema definition) │
                          └─────────┬───────────┘
                                    │
                          ┌─────────▼───────────┐
                          │   GraphValidator     │
                          │  (core engine)       │
                          └─────────┬───────────┘
                                    │
          ┌─────────────┬───────────┼────────────┬──────────────┐
          │             │           │            │              │
    ┌─────▼─────┐ ┌─────▼─────┐ ┌──▼───┐ ┌─────▼─────┐ ┌─────▼─────┐
    │ NetworkX  │ │  Neo4j    │ │Memgr.│ │  Cypher   │ │  Result   │
    │ Extension │ │ Extension │ │Ext.  │ │  Parser   │ │ Validator │
    └───────────┘ └───────────┘ └──────┘ └───────────┘ └───────────┘
```

### Refactoring needed

The current `GraphValidator` accepts data as `Sequence[dict[str, Any] | NodeModel]`.
The new extensions need to produce this format. Two approaches:

**Option A**: Each extension converts to dicts and calls `GraphValidator.validate()` (current pattern).
**Option B**: Extract validation checks into reusable functions that can be composed differently per extension.

**Decision**: Start with **Option A** (simpler, proven). Refactor to B later if needed.

### New package structure

```
orthograph/extensions/
├── __init__.py
├── cypher.py              # Existing: query generation
├── networkx.py            # Existing: nx graph validation
├── _neo4j_common.py       # Shared: Neo4j driver result conversion utilities
├── neo4j.py               # Neo4j database schema introspection + validation
├── memgraph.py            # Memgraph database schema introspection + validation
├── cypher_parser.py       # Cypher query string parsing and validation
└── result_validator.py    # Neo4j driver query result validation
```

`_neo4j_common.py` contains:
- `node_to_dict(neo4j.graph.Node) -> dict` -- converts driver Node to orthograph dict format
- `rel_to_dict(neo4j.graph.Relationship) -> dict` -- converts driver Relationship
- `records_to_graph_data(records) -> tuple[list[dict], list[dict]]` -- batch conversion

Both `neo4j.py` and `memgraph.py` depend on the `neo4j` Python driver package.
`cypher_parser.py` depends on `graphglot`.
These are optional dependencies (not required for core orthograph).

---

## Mechanism 1: Database Schema Validation

### Goal

Given a live Neo4j or Memgraph database connection and a `GraphDataModel`,
introspect the database schema and report deviations.

### What we introspect

| Aspect | Neo4j Query | Memgraph Query | APOC Needed |
|--------|------------|----------------|-------------|
| Node labels | `CALL db.labels()` | `CALL schema.node_type_properties()` | No |
| Relationship types | `CALL db.relationshipTypes()` | `CALL schema.rel_type_properties()` | No |
| Properties per label (with types + mandatory flag) | `CALL apoc.meta.nodeTypeProperties({sample:-1})` | `CALL schema.node_type_properties()` | Neo4j: Yes |
| Properties per rel type | `CALL apoc.meta.relTypeProperties({sample:-1})` | `CALL schema.rel_type_properties()` | Neo4j: Yes |
| Fallback: properties per label (no APOC) | `MATCH (n:Label) UNWIND keys(n) AS k WITH k, count(*) AS c ... RETURN ...` | Same | No |
| Constraints | `SHOW CONSTRAINTS YIELD *` | `SHOW CONSTRAINT INFO` | No |
| Indexes | `SHOW INDEXES YIELD *` | `SHOW INDEX INFO` | No |
| Counts per label | `MATCH (n:Label) RETURN count(n)` or `apoc.meta.stats()` | `SHOW SCHEMA INFO` | Neo4j: Optional |
| Cardinality stats | `MATCH (n:L) OPTIONAL MATCH (n)-[r:TYPE]->() WITH n, count(r) AS d RETURN min(d), max(d), avg(d)` | Same | No |

### Validation checks

Given a `GraphDataModel` and the introspected schema, report:

| Check | Code | Severity | Description |
|-------|------|----------|-------------|
| Missing node label | `DB_MISSING_NODE_LABEL` | ERROR | Model defines a node type that doesn't exist in DB |
| Unexpected node label | `DB_UNEXPECTED_NODE_LABEL` | WARNING | DB has a label not in the model |
| Missing relationship type | `DB_MISSING_REL_TYPE` | ERROR | Model defines a rel type not in DB |
| Unexpected relationship type | `DB_UNEXPECTED_REL_TYPE` | WARNING | DB has a rel type not in the model |
| Missing property | `DB_MISSING_PROPERTY` | ERROR | Model requires a property that no nodes of that label have |
| Property type mismatch | `DB_PROPERTY_TYPE_MISMATCH` | ERROR | DB property type differs from model |
| Property not always present | `DB_PROPERTY_OPTIONAL_MISMATCH` | WARNING | Model says required, but DB shows it's not on all nodes |
| Cardinality out of range | `DB_CARDINALITY_VIOLATION` | WARNING | Observed min/max degree doesn't match model cardinality |
| Missing constraint | `DB_MISSING_CONSTRAINT` | INFO | Model has uid_field but DB has no uniqueness constraint |
| Unexpected property | `DB_UNEXPECTED_PROPERTY` | INFO | DB has properties not in the model |

### Neo4j-specific design

```python
# orthograph/extensions/neo4j.py

class Neo4jSchemaIntrospector:
    """Extracts schema information from a live Neo4j database."""

    def __init__(self, driver: neo4j.Driver, database: str | None = None) -> None: ...

    def introspect(self) -> IntrospectedSchema: ...
    def has_apoc(self) -> bool: ...

class IntrospectedSchema:
    """Database schema as extracted from introspection queries.

    This is a data class, not a GraphDataModel -- it represents what IS
    in the database, not what SHOULD be.
    """
    node_labels: set[str]
    relationship_types: set[str]
    node_properties: dict[str, list[PropertyInfo]]  # label -> properties
    rel_properties: dict[str, list[PropertyInfo]]    # type -> properties
    constraints: list[ConstraintInfo]
    indexes: list[IndexInfo]
    node_counts: dict[str, int]
    cardinality_stats: dict[tuple[str, str, str], CardinalityStats]
    # (source_label, rel_type, direction) -> stats

class PropertyInfo:
    name: str
    types: list[str]       # observed types
    mandatory: bool        # present on all entities
    observation_count: int
    total_count: int

class ConstraintInfo:
    name: str | None
    constraint_type: str   # UNIQUENESS, EXISTENCE, TYPE, KEY
    entity_type: str       # NODE, RELATIONSHIP
    labels: list[str]
    properties: list[str]
    property_type: str | None

class CardinalityStats:
    min_degree: int
    max_degree: int
    avg_degree: float

def validate_database(
    driver: neo4j.Driver,
    model: GraphDataModel,
    database: str | None = None,
) -> ValidationResult:
    """Top-level function: introspect DB and validate against model."""
```

### Memgraph-specific design

```python
# orthograph/extensions/memgraph.py

class MemgraphSchemaIntrospector:
    """Extracts schema information from a live Memgraph database."""

    def __init__(self, driver: neo4j.Driver) -> None: ...

    def introspect(self) -> IntrospectedSchema: ...

def validate_database(
    driver: neo4j.Driver,
    model: GraphDataModel,
) -> ValidationResult:
    """Top-level function: introspect Memgraph and validate against model."""
```

Both return the same `IntrospectedSchema` type. The difference is in the
Cypher queries used to populate it.

### Key differences between Neo4j and Memgraph introspection

| Capability | Neo4j | Memgraph |
|-----------|-------|----------|
| Get labels | `CALL db.labels()` | `CALL schema.node_type_properties()` then extract unique labels |
| Get rel types | `CALL db.relationshipTypes()` | `CALL schema.rel_type_properties()` then extract unique types |
| Properties + types + mandatory | APOC: `apoc.meta.nodeTypeProperties()` | Built-in: `schema.node_type_properties()` |
| Fallback (no APOC) | Pure Cypher: `MATCH (n:L) UNWIND keys(n) ...` | Not needed (built-in works) |
| Constraints | `SHOW CONSTRAINTS YIELD *` | `SHOW CONSTRAINT INFO` |
| Cardinality stats | Pure Cypher queries | Same Cypher queries |
| APOC availability detection | `SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc'` | N/A |

### APOC fallback strategy (Neo4j only)

```
1. Check if APOC is available (SHOW PROCEDURES)
2. If yes: use apoc.meta.nodeTypeProperties(), apoc.meta.relTypeProperties()
3. If no: fall back to pure Cypher per-label property scanning:
   MATCH (n:Label)
   UNWIND keys(n) AS key
   WITH key, count(*) AS keyCount, count(n) AS total
   RETURN key, keyCount, total, keyCount = total AS mandatory
```

### IntrospectedSchema as shared type

`IntrospectedSchema` is defined in `_neo4j_common.py` so both Neo4j and Memgraph
introspectors produce the same output. A standalone comparison function then
compares `IntrospectedSchema` against `GraphDataModel`:

```python
# orthograph/extensions/_neo4j_common.py

def compare_schema(
    introspected: IntrospectedSchema,
    model: GraphDataModel,
) -> ValidationResult:
    """Compare an introspected database schema against a GraphDataModel."""
```

This keeps the comparison logic shared and tested once.

---

## Mechanism 2: Cypher Query Validation

### Goal

Given a Cypher query string and a `GraphDataModel`, parse the query and check
whether the node labels, relationship types, and property accesses are consistent
with the model. No database connection needed.

### Parser choice: strategy pattern with graphglot as default

The parser is implemented as a **strategy** (protocol/ABC). The default
implementation uses graphglot. This allows swapping to pycypher, regex,
or a future parser without changing the validation logic.

```python
class CypherParserStrategy(Protocol):
    def parse(self, query: str) -> CypherQueryInfo: ...

class GraphglotParser:
    """Default parser strategy using graphglot."""
    def parse(self, query: str) -> CypherQueryInfo: ...

class RegexParser:
    """Fallback parser using regex (~80% accuracy)."""
    def parse(self, query: str) -> CypherQueryInfo: ...
```

**graphglot** is the recommended parser. Rationale:
- Pure Python, `pip install graphglot`
- 100% openCypher TCK parse rate
- Built-in `LineageAnalyzer` extracts labels, rel types, property accesses
- Actively maintained (v0.9.2, April 2026)
- Apache 2.0 license

`pycypher` (ANTLR4-based) is the fallback if graphglot proves insufficient.

### What can be validated

| Check | Code | Description |
|-------|------|-------------|
| Unknown node label | `QUERY_UNKNOWN_NODE_LABEL` | Query uses `:Foo` but Foo not in model |
| Unknown rel type | `QUERY_UNKNOWN_REL_TYPE` | Query uses `[:BAR]` but BAR not in model |
| Unknown property | `QUERY_UNKNOWN_PROPERTY` | Query accesses `n.xyz` where n is bound to Person, but Person has no `xyz` |
| Invalid endpoint | `QUERY_INVALID_ENDPOINT` | Query has `(:Person)-[:LIVES_IN]->(:Movie)` but model says LIVES_IN connects Person->City |
| Write to wrong type | `QUERY_WRITE_TYPE_MISMATCH` | CREATE/MERGE creates a node/rel with properties inconsistent with model |
| Query intent | info | Is this a read (MATCH) or write (CREATE/MERGE/DELETE) query? |

### Design

```python
# orthograph/extensions/cypher_parser.py

class CypherQueryInfo:
    """Extracted structural information from a parsed Cypher query."""
    node_labels: set[str]
    relationship_types: set[str]
    property_accesses: dict[str, set[str]]  # variable -> {prop names}
    variable_bindings: dict[str, str | None]  # variable -> label (if known)
    query_intent: Literal["read", "write", "read_write", "schema"]
    raw_patterns: list[PatternInfo]

class PatternInfo:
    """A single graph pattern from the query."""
    source_label: str | None
    relationship_type: str | None
    target_label: str | None
    direction: Literal["outgoing", "incoming", "undirected"]

def parse_cypher(query: str) -> CypherQueryInfo:
    """Parse a Cypher query and extract structural information."""

def validate_cypher(
    query: str,
    model: GraphDataModel,
) -> ValidationResult:
    """Validate a Cypher query string against a GraphDataModel."""
```

### Implementation approach

```python
from graphglot.dialect import Dialect
from graphglot.lineage import LineageAnalyzer

def parse_cypher(query: str) -> CypherQueryInfo:
    neo4j_dialect = Dialect.get_or_raise("neo4j")
    ast = neo4j_dialect.parse(query)
    analyzer = LineageAnalyzer()
    lineage = analyzer.analyze(ast[0])
    # Extract labels, types, property accesses from lineage
    ...
```

### Limitations

- Static analysis only -- cannot resolve dynamic labels (e.g., from parameters)
- Variable-length paths `[*1..3]` -- intermediate node labels are unknown
- CALL {} subqueries -- lineage may not propagate perfectly
- UNWIND/WITH chains -- property provenance may be lost
- These are flagged as INFO-level "unable to determine" rather than false errors

### Open question

> Should `validate_cypher` also attempt to validate property value types
> (e.g., `WHERE n.age > "thirty"` -- comparing int to string)?
> This requires deeper analysis and is probably out of scope for v1.
> **Proposed answer**: No. Focus on structural checks (labels, types, properties exist). Type checking requires runtime knowledge of parameter values.

---

## Mechanism 3: Query Result Validation

### Goal

Given the output of a neo4j driver query (list of `neo4j.Record` containing
`Node`, `Relationship`, `Path` objects) and a `GraphDataModel`, validate that
the returned data conforms to the model.

Two modes:
1. **Validate against the general database model** -- check that returned nodes/rels
   are consistent with the full schema definition.
2. **Validate against a specific result model** -- define a more specific
   `GraphDataModel` for a particular query's expected output (which node types,
   which properties, which relationships should be returned).

### neo4j driver result structure (key facts)

- `neo4j.graph.Node`: has `.labels` (frozenset), `.element_id`, dict-like property access
- `neo4j.graph.Relationship`: has `.type` (str), `.start_node`, `.end_node`, dict-like properties
- `neo4j.graph.Path`: has `.nodes` (tuple), `.relationships` (tuple)
- `record.data()` is **lossy** -- discards labels and element_id. Must use raw objects.
- `result.graph()` returns a `neo4j.graph.Graph` with deduplicated `.nodes` and `.relationships`

### Conversion to orthograph format

```python
# orthograph/extensions/_neo4j_common.py

def node_to_dict(node: neo4j.graph.Node) -> dict[str, Any]:
    """Convert a neo4j Node to orthograph validation dict."""
    label = _pick_primary_label(node.labels)  # see below
    d = dict(node)  # all properties
    d["__label__"] = label
    return d

def rel_to_dict(rel: neo4j.graph.Relationship) -> dict[str, Any]:
    """Convert a neo4j Relationship to orthograph validation dict."""
    d = dict(rel)  # all properties
    d["__label__"] = rel.type
    # Use uid_field values if available, fall back to element_id
    d["__source_uid__"] = _resolve_uid(rel.start_node)
    d["__target_uid__"] = _resolve_uid(rel.end_node)
    return d
```

### Multi-label nodes

Neo4j nodes can have multiple labels (e.g., `Person:Employee`). Our
`NodeModel.__label__` is a single string. Resolution strategy:

1. If the node has exactly one label that matches a model label, use it
2. If the node has multiple labels matching model labels, pick the most
   specific one (user can configure priority)
3. If no labels match, report an error

```python
def _pick_primary_label(
    labels: frozenset[str],
    model: GraphDataModel,
) -> str | None:
    """Select the primary label from a multi-label node."""
    model_labels = model.node_labels
    matching = labels & model_labels
    if len(matching) == 1:
        return matching.pop()
    if len(matching) > 1:
        # Ambiguous -- return first alphabetically (or make configurable)
        return sorted(matching)[0]
    return None  # no matching label
```

### UID resolution

Relationships reference start/end nodes by UID. We need to resolve node UIDs
from the driver Node objects:

```python
def _resolve_uid(
    node: neo4j.graph.Node | None,
    model: GraphDataModel,
) -> str:
    """Extract the UID value from a node using the model's uid_field."""
    if node is None:
        return "__unknown__"
    label = _pick_primary_label(node.labels, model)
    if label:
        node_type = model.get_node_type(label)
        if node_type and node_type.__uid_field__:
            uid_val = node.get(node_type.__uid_field__)
            if uid_val is not None:
                return str(uid_val)
    return node.element_id  # fallback
```

### Design

```python
# orthograph/extensions/result_validator.py

def validate_result(
    records: Sequence[neo4j.Record],
    model: GraphDataModel,
    result_model: GraphDataModel | None = None,
) -> ValidationResult:
    """Validate neo4j driver query results against a GraphDataModel.

    Args:
        records: Query result records from the neo4j driver.
        model: The database-level GraphDataModel (what CAN exist).
        result_model: Optional specific model for this query's expected
            output (what SHOULD be in the result). If provided, validates
            against this instead of the general model.
    """

def validate_graph_result(
    graph: neo4j.graph.Graph,
    model: GraphDataModel,
    result_model: GraphDataModel | None = None,
) -> ValidationResult:
    """Validate a neo4j Graph object (from result.graph()) against a model."""
```

### Result-specific GraphDataModel

Users can define a specific model for a query's expected output:

```python
# Define what we expect from a "find actor filmography" query
class PersonResult(NodeModel):
    __label__ = "Person"
    __optional__ = False  # must appear in results
    name: str
    # age is NOT included -- this query doesn't return it

class MovieResult(NodeModel):
    __label__ = "Movie"
    __optional__ = False
    title: str
    year: int

class ActedInResult(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_type__ = PersonResult
    __target_type__ = MovieResult
    __optional__ = False
    role: str

filmography_result_model = GraphDataModel(
    name="FilmographyQueryResult",
    node_types=[PersonResult, MovieResult],
    relationship_types=[ActedInResult],
)

# Validate actual query results
result = validate_result(records, db_model, result_model=filmography_result_model)
```

---

## Dependencies

| Extension | Required Package | Optional | Notes |
|-----------|-----------------|----------|-------|
| neo4j.py | `neo4j` (Python driver) | Yes | Also used by memgraph.py |
| memgraph.py | `neo4j` (Python driver) | Yes | Memgraph uses Bolt protocol |
| cypher_parser.py | `graphglot` | Yes | Pure Python, pip install |
| result_validator.py | `neo4j` (Python driver) | Yes | Uses neo4j.graph types |
| _neo4j_common.py | `neo4j` (Python driver) | Yes | Shared conversion utilities |

All are optional extras. Core orthograph works without any of them.
Install with: `pip install orthograph[neo4j]`, `pip install orthograph[cypher]`

```toml
# pyproject.toml optional-dependencies (future)
[project.optional-dependencies]
neo4j = ["neo4j>=5.0"]
memgraph = ["neo4j>=5.0"]
cypher = ["graphglot>=0.9"]
all = ["neo4j>=5.0", "graphglot>=0.9"]
```

---

## Implementation Milestones

| # | Milestone | Content | Dependencies |
|---|-----------|---------|-------------|
| E1 | `_neo4j_common.py` | IntrospectedSchema, PropertyInfo, ConstraintInfo, CardinalityStats, node_to_dict, rel_to_dict, compare_schema | core |
| E2 | `neo4j.py` | Neo4jSchemaIntrospector, APOC detection + fallback, validate_database | E1, neo4j driver |
| E3 | `memgraph.py` | MemgraphSchemaIntrospector, validate_database | E1, neo4j driver |
| E4 | `cypher_parser.py` | CypherQueryInfo, parse_cypher, validate_cypher | graphglot |
| E5 | `result_validator.py` | validate_result, validate_graph_result, multi-label resolution, UID resolution | E1, neo4j driver |
| E6 | Tests for E1 (unit, no DB) | Mock-based tests for comparison logic and conversion functions | E1 |
| E7 | Tests for E4 (unit, no DB) | Parse various Cypher queries, validate against models | E4 |
| E8 | Integration tests for E2/E3 | Requires running Neo4j/Memgraph (mark as @pytest.mark.slow) | E2, E3 |
| E9 | Integration tests for E5 | Requires running Neo4j (or mock driver results) | E5 |

### Execution order

E1 -> E6 (test) -> E4 -> E7 (test) -> E5 -> E9 (test) -> E2 -> E3 -> E8 (test)

Rationale: E1 (shared core) and E4 (cypher parser) can be fully tested without
a database. E5 (result validator) can be tested with mock neo4j objects. E2/E3
(database introspection) require a running database for integration tests.

---

## Open Questions

1. **Multi-label nodes**: The current `NodeModel.__label__` is a single string.
   Neo4j nodes can have multiple labels. Should we support multi-label node
   types (e.g., `__labels__ = {"Person", "Employee"}`)? Or is
   "pick the matching one" sufficient?
   **Current proposal**: Pick-the-matching-one for v1. Multi-label support later.

2. **Property type mapping**: Neo4j reports types as strings like `"String"`,
   `"Long"`, `"Double"`. Memgraph reports `"String"`, `"Int"`, `"Float"`.
   We need a mapping from these to Python types for comparison with the model.
   **Current proposal**: Build a mapping dict in `_neo4j_common.py`:
   `{"String": str, "Long": int, "Integer": int, "Int": int, "Double": float, "Float": float, "Boolean": bool}`

3. **graphglot stability**: graphglot is pre-v1 (0.9.2). Should we vendor it
   or pin it tightly?
   **Current proposal**: Pin `>=0.9,<1.0` and test against specific version.
   Keep pycypher as documented fallback.

4. **Database connection management**: Should the introspector own the driver
   or accept a session/transaction? Should it use `driver.execute_query()` or
   `session.run()`?
   **Current proposal**: Accept a `neo4j.Driver` instance. Internally use
   `driver.execute_query()` for simplicity. User manages driver lifecycle.

5. **APOC requirement for Neo4j**: Rich property introspection (types, mandatory
   flag) requires APOC on Neo4j. The fallback (pure Cypher scanning) is slow
   on large databases. Should we warn users?
   **Current proposal**: Yes. If APOC is not available, issue INFO-level
   `APOC_NOT_AVAILABLE` message and use fallback queries. Document the
   performance implications.
