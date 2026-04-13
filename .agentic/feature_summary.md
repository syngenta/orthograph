# Orthograph -- Feature Summary

> Pydantic-native graph data model definition and validation.
> Like Pandera for DataFrames, but for graph data structures.

**Version**: 0.1.0 (rebuild-implementation branch)
**Python**: >= 3.10
**Tests**: 205 passing, strict mypy, ruff, pre-commit enforced

---

## What This Library Does

Orthograph provides a declarative way to define the structure of graph data
(node types, relationship types, their properties, cardinality constraints)
and validate actual graph data against those definitions. It fills the gap
between Pydantic (document validation), Pandera (DataFrame validation), and
SQLModel (SQL schema + validation) -- but for **graph databases and graph
data structures**.

---

## Core Concepts

### GraphDataModel

The central container. Defines which node types and relationship types exist,
their properties, and their constraints. Validates its own structural
consistency on creation (no duplicates, no dangling references).

```python
from orthograph import GraphDataModel, NodeModel, RelationshipModel, Cardinality

class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    age: int
    email: str | None = None        # Optional property

class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    year: int

class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_type__ = Person
    __target_type__ = Movie
    __source_cardinality__ = Cardinality.ZERO_OR_MORE
    role: str                        # Required property on relationship

model = GraphDataModel(
    name="Filmography",
    node_types=[Person, Movie],
    relationship_types=[ActedIn],
)
```

### GraphValidator

Validates actual data (dicts or model instances) against a GraphDataModel.

```python
from orthograph import GraphValidator

validator = GraphValidator(model)
result = validator.validate(
    nodes=[
        {"__label__": "Person", "name": "Alice", "age": 30},
        {"__label__": "Movie", "title": "Inception", "year": 2010},
    ],
    relationships=[
        {"__label__": "ACTED_IN", "__source_uid__": "Alice",
         "__target_uid__": "Inception", "role": "Cobb"},
    ],
)
assert result.is_valid
```

---

## Feature Coverage by Area

### 1. Schema Definition (core)

| Feature | Status | Module |
|---------|--------|--------|
| Node types as Pydantic models (native Python types) | Done | `core.node_model` |
| Relationship types as Pydantic models | Done | `core.relationship_model` |
| Required vs optional properties (`Optional[T]`) | Done | `core.node_model`, `core.relationship_model` |
| UID field declaration (`__uid_field__`) | Done | `core.node_model` |
| Directed and undirected relationships (`__directed__`) | Done | `core.relationship_model` |
| Source/target node type constraints | Done | `core.relationship_model` |
| Named cardinality constants (ONE, ZERO_OR_MORE, etc.) | Done | `core.types.Cardinality` |
| Custom cardinality (min/max) | Done | `core.types.CardinalitySpec` |
| Source and target cardinality per relationship type | Done | `core.relationship_model` |
| Entity-level optionality (`__optional__`) | Done | `core.node_model`, `core.relationship_model` |
| GraphDataModel container with structural validation | Done | `core.graph_data_model` |
| Dynamic Enum generation for labels | Done | `core.graph_data_model` |
| Introspection (property specs, required/all names, outgoing/incoming rels) | Done | All model classes + `GraphDataModel` |

### 2. Data Validation (core)

| Feature | Status | Module |
|---------|--------|--------|
| Node label validation | Done | `core.validator` |
| Relationship label validation | Done | `core.validator` |
| Property type validation (Pydantic delegation) | Done | `core.validator` |
| Required property enforcement | Done | `core.validator` |
| Extra property rejection | Done | `core.validator` |
| Referential integrity (dangling references) | Done | `core.validator` |
| Endpoint type checking (correct source/target label) | Done | `core.validator` |
| Cardinality enforcement (outgoing and incoming) | Done | `core.validator` |
| Entity presence checks (required types must appear) | Done | `core.validator` |
| Covariant input types (`Sequence` not `list`) | Done | `core.validator` |
| Accept both dicts and model instances as input | Done | `core.validator` |
| Collect-all-errors mode (not fail-fast) | Done | `core.validator` |

### 3. Error Reporting

| Feature | Status | Module |
|---------|--------|--------|
| Structured `ValidationIssue` (code, severity, entity_type, entity_id, message, context) | Done | `core.errors` |
| `ValidationResult` with is_valid, errors, warnings, issues | Done | `core.errors` |
| `raise_on_errors()` raises `GraphValidationError` | Done | `core.errors` |
| `merge()` to combine results from multiple validation passes | Done | `core.errors` |
| 26 distinct validation codes across all validators | Done | See catalog below |

### 4. YAML Configuration (io)

| Feature | Status | Module |
|---------|--------|--------|
| Load GraphDataModel from YAML string | Done | `io.yaml` |
| Load GraphDataModel from YAML file | Done | `io.yaml` |
| Save GraphDataModel to YAML file | Done | `io.yaml` |
| Round-trip (Python -> YAML -> Python) | Done | `io.yaml` |
| Dynamic class generation from YAML specs | Done | `io.yaml` |
| Property types (str, int, float, bool, list, dict) | Done | `io.yaml` |
| Required/optional properties in YAML | Done | `io.yaml` |
| Cardinality in YAML (min/max) | Done | `io.yaml` |
| Entity-level optionality in YAML | Done | `io.yaml` |

### 5. Cypher Extension

| Feature | Status | Module |
|---------|--------|--------|
| MERGE node queries (UID-based upsert) | Done | `extensions.cypher.generator` |
| CREATE node queries | Done | `extensions.cypher.generator` |
| CREATE relationship queries | Done | `extensions.cypher.generator` |
| MERGE relationship queries | Done | `extensions.cypher.generator` |
| MATCH node queries | Done | `extensions.cypher.generator` |
| MATCH relationship pattern queries | Done | `extensions.cypher.generator` |
| Uniqueness constraint generation from UID fields | Done | `extensions.cypher.generator` |
| Parse Cypher query -> extract labels, rel types, properties | Done | `extensions.cypher.parser` |
| Validate Cypher query against a GraphDataModel | Done | `extensions.cypher.parser` |
| Detect query intent (read/write/read_write) | Done | `extensions.cypher.parser` |
| Extract variable bindings (variable -> label mapping) | Done | `extensions.cypher.parser` |
| Extract relationship patterns (source -> rel -> target) | Done | `extensions.cypher.parser` |
| Strategy pattern for parser backends | Done | `extensions.cypher.parser` |
| GraphglotParser (default, 100% openCypher TCK) | Done | `extensions.cypher.parser` |

**Cypher query validation checks:**
- Unknown node labels referenced in query
- Unknown relationship types referenced in query
- Unknown properties accessed on bound variables
- Invalid relationship endpoints (wrong source/target type)

### 6. Neo4j Extension

| Feature | Status | Module |
|---------|--------|--------|
| Schema introspection from live Neo4j database | Done | `extensions.neo4j.introspector` |
| APOC detection (automatic) | Done | `extensions.neo4j.introspector` |
| Rich property introspection via APOC (types, mandatory) | Done | `extensions.neo4j.introspector` |
| Pure Cypher fallback when APOC unavailable | Done | `extensions.neo4j.introspector` |
| Constraint introspection (`SHOW CONSTRAINTS`) | Done | `extensions.neo4j.introspector` |
| Compare introspected schema against GraphDataModel | Done | `extensions._shared.schema_compare` |
| `validate_database()` top-level function | Done | `extensions.neo4j.introspector` |
| Convert neo4j driver Node to orthograph dict | Done | `extensions.neo4j.result_adapter` |
| Convert neo4j driver Relationship to orthograph dict | Done | `extensions.neo4j.result_adapter` |
| Extract nodes/rels from driver Records | Done | `extensions.neo4j.result_adapter` |
| Validate query results against a GraphDataModel | Done | `extensions.neo4j.result_adapter` |
| Validate against a query-specific result model | Done | `extensions.neo4j.result_adapter` |
| Multi-label node resolution (pick matching label) | Done | `extensions.neo4j.result_adapter` |
| UID resolution from driver Node objects | Done | `extensions.neo4j.result_adapter` |
| Duck-typed detection of Node vs Relationship vs scalar | Done | `extensions.neo4j.result_adapter` |

### 7. Memgraph Extension

| Feature | Status | Module |
|---------|--------|--------|
| Schema introspection from live Memgraph database | Done | `extensions.memgraph.introspector` |
| Node properties via `schema.node_type_properties()` | Done | `extensions.memgraph.introspector` |
| Relationship properties via `schema.rel_type_properties()` | Done | `extensions.memgraph.introspector` |
| Constraint introspection (`SHOW CONSTRAINT INFO`) | Done | `extensions.memgraph.introspector` |
| Compare introspected schema against GraphDataModel | Done | `extensions._shared.schema_compare` |
| `validate_database()` top-level function | Done | `extensions.memgraph.introspector` |

**Note:** Memgraph uses the same `neo4j` Python driver (Bolt protocol). The
result adapter from `extensions.neo4j.result_adapter` works with Memgraph
driver results as well (same Node/Relationship types).

### 8. NetworkX Extension

| Feature | Status | Module |
|---------|--------|--------|
| Convert GraphDataModel to NetworkX MultiDiGraph (schema visualization) | Done | `extensions.networkx.adapter` |
| Validate a NetworkX graph against a GraphDataModel | Done | `extensions.networkx.adapter` |
| Map NetworkX node IDs to UID field values for referential integrity | Done | `extensions.networkx.adapter` |

### 9. Visualization

| Feature | Status | Module |
|---------|--------|--------|
| Generate Mermaid diagram from GraphDataModel | Done | `depiction` |
| Node properties shown in diagram | Done | `depiction` |
| Directed and undirected edge rendering | Done | `depiction` |

---

## Validation Code Catalog

Every validation issue has a unique code, severity, and source.

### Structural Validation (GraphDataModel creation)

| Code | Severity | Meaning |
|------|----------|---------|
| `DUPLICATE_NODE_LABEL` | ERROR | Two node types share the same label |
| `DUPLICATE_RELATIONSHIP_LABEL` | ERROR | Two relationship types share the same label |
| `UNDEFINED_NODE_TYPE` | ERROR | A relationship references a node type not in the model |
| `ISOLATED_NODE` | WARNING | A node type is not connected by any relationship |

### Data Validation (GraphValidator)

| Code | Severity | Meaning |
|------|----------|---------|
| `MISSING_LABEL` | ERROR | Node or relationship dict lacks `__label__` field |
| `UNKNOWN_NODE_LABEL` | ERROR | Node label not defined in the model |
| `UNKNOWN_RELATIONSHIP_LABEL` | ERROR | Relationship label not defined in the model |
| `EXTRA_PROPERTIES` | ERROR | Data contains properties not in the model |
| `PROPERTY_VALIDATION_ERROR` | ERROR | Pydantic validation failed (type mismatch, missing required) |
| `MISSING_ENDPOINT` | ERROR | Relationship missing `__source_uid__` or `__target_uid__` |
| `DANGLING_REFERENCE` | ERROR | Relationship references a node not in the data |
| `WRONG_ENDPOINT_TYPE` | ERROR | Relationship endpoint has wrong node label |
| `CARDINALITY_VIOLATION` | ERROR | Node has too few or too many relationships of a type |
| `MISSING_REQUIRED_TYPE` | ERROR | A non-optional entity type has no instances in the data |

### Database Schema Comparison

| Code | Severity | Meaning |
|------|----------|---------|
| `DB_MISSING_NODE_LABEL` | ERROR | Model defines a label that doesn't exist in DB |
| `DB_UNEXPECTED_NODE_LABEL` | WARNING | DB has a label not in the model |
| `DB_MISSING_REL_TYPE` | ERROR | Model defines a relationship type not in DB |
| `DB_UNEXPECTED_REL_TYPE` | WARNING | DB has a relationship type not in the model |
| `DB_MISSING_PROPERTY` | ERROR | Required property not found in DB |
| `DB_PROPERTY_TYPE_MISMATCH` | ERROR | DB property type doesn't match model |
| `DB_PROPERTY_OPTIONAL_MISMATCH` | WARNING | Model says required, DB says not always present |
| `DB_UNEXPECTED_PROPERTY` | INFO | DB has a property not in the model |

### Cypher Query Validation

| Code | Severity | Meaning |
|------|----------|---------|
| `QUERY_UNKNOWN_NODE_LABEL` | ERROR | Query references a node label not in the model |
| `QUERY_UNKNOWN_REL_TYPE` | ERROR | Query references a relationship type not in the model |
| `QUERY_UNKNOWN_PROPERTY` | ERROR | Query accesses a property not defined on the bound type |
| `QUERY_INVALID_ENDPOINT` | ERROR | Query pattern has wrong source/target for a relationship |

---

## Architecture

```
orthograph/
├── __init__.py               # Public API: core classes
├── core/
│   ├── types.py              # CardinalitySpec, Cardinality, EntityType, Severity, TypeInfo
│   ├── errors.py             # ValidationIssue, ValidationResult, GraphValidationError
│   ├── node_model.py         # NodeModel (Pydantic BaseModel subclass)
│   ├── relationship_model.py # RelationshipModel (Pydantic BaseModel subclass)
│   ├── graph_data_model.py   # GraphDataModel container
│   └── validator.py          # GraphValidator engine
├── io/
│   └── yaml.py               # YAML load/save with dynamic class generation
├── extensions/
│   ├── _shared/              # Shared DB types (no external deps)
│   │   ├── schema_types.py   # IntrospectedSchema, PropertyInfo, ConstraintInfo
│   │   └── schema_compare.py # compare_schema(), db_type_to_python()
│   ├── cypher/               # Cypher language (depends: graphglot)
│   │   ├── generator.py      # CypherGenerator (MERGE, CREATE, MATCH, constraints)
│   │   └── parser.py         # CypherParserStrategy, GraphglotParser, validate_cypher
│   ├── neo4j/                # Neo4j specific (depends: neo4j driver at runtime)
│   │   ├── introspector.py   # Neo4jSchemaIntrospector (APOC + fallback)
│   │   └── result_adapter.py # node_to_dict, validate_result
│   ├── memgraph/             # Memgraph specific (depends: neo4j driver at runtime)
│   │   └── introspector.py   # MemgraphSchemaIntrospector
│   └── networkx/             # NetworkX (depends: networkx)
│       └── adapter.py        # schema_to_networkx, validate_networkx_graph
└── depiction.py              # Mermaid diagram generation
```

### Dependency Isolation

Each extension subpackage can be imported independently:

| Import | Pulls in |
|--------|----------|
| `from orthograph import *` | pydantic only |
| `from orthograph.io.yaml import *` | pydantic + pyyaml |
| `from orthograph.extensions.cypher import *` | pydantic + graphglot |
| `from orthograph.extensions.neo4j import *` | pydantic only (neo4j driver passed at runtime) |
| `from orthograph.extensions.memgraph import *` | pydantic only (neo4j driver passed at runtime) |
| `from orthograph.extensions.networkx import *` | pydantic + networkx |
| `from orthograph.depiction import *` | pydantic only |

---

## Three Levels of Optionality

Orthograph distinguishes three orthogonal levels of optionality:

**Level 1 -- Property optionality**: A property on a node or relationship can
be required (`name: str`) or optional (`email: Optional[str] = None`).

**Level 2 -- Entity optionality**: A node or relationship type can be optional
(`__optional__ = True`, the default) or required (`__optional__ = False`).
When required, at least one instance must be present in validated data.

**Level 3 -- Cardinality**: How many relationships of a given type each node
can have. Expressed as `__source_cardinality__` and `__target_cardinality__`
on RelationshipModel. Named constants: `Cardinality.ONE`, `ZERO_OR_ONE`,
`ZERO_OR_MORE`, `ONE_OR_MORE`. Custom: `CardinalitySpec(min=2, max=5)`.

---

## Extension Points and Protocols

| Protocol | Module | Purpose |
|----------|--------|---------|
| `CypherParserStrategy` | `extensions.cypher.parser` | Pluggable Cypher parser backends |
| `NodeLike` | `extensions.neo4j.result_adapter` | Structural match for neo4j driver Node |
| `RelationshipLike` | `extensions.neo4j.result_adapter` | Structural match for neo4j driver Relationship |
| `RecordLike` | `extensions.neo4j.result_adapter` | Structural match for neo4j driver Record |

---

## What Is Not Yet Implemented

These are identified gaps for future development:

| Feature | Notes |
|---------|-------|
| Schema/Projection hierarchy | `GraphDataModel` is one flat concept. A formal `GraphSchema` (DB truth) -> `GraphProjection` (usage subset) with compatibility validation is deferred. |
| Multi-label node support | `NodeModel.__label__` is a single string. Neo4j nodes can have multiple labels. Current workaround: pick-the-matching-one. |
| Schema composition / inheritance | Cannot compose or extend schemas. No `include` or `extends` mechanism. |
| Custom validators / checks | No user-defined validation rules (like Pandera's `Check`). Only structural + type checks. |
| JSON I/O | Only YAML is supported. JSON loading/saving not implemented. |
| Property value constraints | No min/max/regex/enum constraints on property values (beyond Pydantic's own Field validators). |
| Cardinality statistics in DB comparison | `IntrospectedSchema.cardinality_stats` field exists but is not populated by either introspector. |
| RDF / SHACL extension | No RDF graph support or SHACL shape generation. |
| GQL / openGQL extension | No GQL support beyond Cypher. |
| Async neo4j driver support | Only sync `driver.execute_query()` is used. No async introspection. |
| CLI tool | No command-line interface for validation. |
| Schema migration / diffing | No tools to compare two GraphDataModel versions or generate migration scripts. |

---

## Notebooks

Six self-contained example notebooks:

| # | Notebook | Covers |
|---|----------|--------|
| 01 | Defining a Graph Data Model | NodeModel, RelationshipModel, GraphDataModel, structural validation, introspection |
| 02 | Validating Graph Data | GraphValidator, error handling, all error types, referential integrity |
| 03 | Optionality and Cardinality | Three levels of optionality, cardinality violations, relaxed query-result models |
| 04 | YAML Configuration | YAML format, load/save, round-trip, config-driven validation |
| 05 | Cypher Query Generation | CypherGenerator, MERGE/CREATE/MATCH, constraints, full DB population workflow |
| 06 | NetworkX and Visualization | schema_to_networkx, validate_networkx_graph, Mermaid diagrams |
