# Extensions -- Architecture Overview

> Read `../index.md` first for the package layout and core concepts.

## Two-Phase Architecture

Every extension follows the same pattern:

```
Phase 1: INSPECTION                     Phase 2: VALIDATION
GraphInspector.inspect()  ──>  GraphProfile  +  GraphDataModel  ──>  ValidationResult
```

**Phase 1** (inspection) produces a `GraphProfile` -- a backend-agnostic report.
**Phase 2** (validation) compares it against a `GraphDataModel`.
The validator never touches the backend.

## Key Abstractions

### `GraphInspector` (ABC, `extensions/base.py`)

```python
class GraphInspector(ABC):
    @abstractmethod
    def inspect(self) -> GraphProfile: ...
```

| Implementation | Backend | File |
|---------------|---------|------|
| `NetworkxInspector` | `nx.MultiDiGraph` | `extensions/networkx/inspector.py` |
| `Neo4jInspector` | Neo4j via driver | `extensions/neo4j/inspector.py` |
| `MemgraphInspector` | Memgraph via driver | `extensions/memgraph/inspector.py` |

### `GraphProfile` (Pydantic, `extensions/models.py`)

Frozen Pydantic model. Hierarchy:

```
GraphProfile
├── source: str                    # "networkx", "neo4j", "memgraph", "manual"
├── timestamp: datetime
├── node_type_profiles: dict[str, NodeTypeProfile]
│   └── label, count, property_profiles
│       └── PropertyProfile: name, present_count, total_count,
│           completeness (computed), observed_types, is_mandatory (computed)
├── rel_type_profiles: dict[str, RelationshipTypeProfile]
│   └── rel_type, count, source_labels, target_labels,
│       property_profiles, cardinality_stats
├── constraints: list[ConstraintInfo]
└── metadata: dict[str, Any]
```

### `validate_profile()` (`extensions/validation.py`)

10 validation codes:

| Code | Severity | Meaning |
|------|----------|---------|
| `MISSING_NODE_LABEL` | ERROR | Model type not in profile |
| `UNEXPECTED_NODE_LABEL` | WARNING | Profile label not in model |
| `MISSING_REL_TYPE` | ERROR | Model rel type not in profile |
| `UNEXPECTED_REL_TYPE` | WARNING | Profile rel type not in model |
| `MISSING_PROPERTY` | ERROR | Required property never observed |
| `UNEXPECTED_PROPERTY` | INFO | Profile property not in model |
| `PROPERTY_TYPE_MISMATCH` | ERROR | Observed type differs from model |
| `PROPERTY_INCOMPLETE` | WARNING | Required property < 100% complete |
| `INVALID_ENDPOINT` | ERROR | Observed source/target doesn't match model |
| `CARDINALITY_VIOLATION` | ERROR | Observed degree outside model bounds |

## Extension Subpackages

| Package | External dep | Purpose |
|---------|-------------|---------|
| `cypher/` | graphglot | Query generation (`CypherGenerator`) + query parsing/validation (`validate_cypher`) |
| `neo4j/` | neo4j driver (runtime) | DB inspection, query result validation |
| `memgraph/` | neo4j driver (runtime) | DB inspection |
| `networkx/` | networkx | In-memory graph inspection + conversion |
| `visualization/` | none | Mermaid diagram generation |

Each subpackage has its own `__init__.py` with re-exports.
Importing one subpackage does not pull in dependencies of others.

## Adding a New Backend

1. Create `extensions/mybackend/inspector.py`
2. Implement `class MyBackendInspector(GraphInspector)`
3. Implement `inspect() -> GraphProfile` using your backend's API
4. Validation comes for free via `validate_profile(profile, model)`
