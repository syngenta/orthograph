# Extension Contract

The interface every inspection extension must satisfy.
For the rationale behind this architecture, see `decisions/003-extensions-two-phase-architecture.md`.

---

## GraphInspector ABC

```python
class GraphInspector(ABC):
    @abstractmethod
    def inspect(self) -> GraphProfile: ...
```

Implementations: `NetworkxInspector`, `Neo4jInspector`, `MemgraphInspector`.
Source: `src/orthograph/extensions/base.py`.

---

## GraphProfile Schema

Frozen Pydantic model. The shared currency between inspection and validation.

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

Source: `src/orthograph/extensions/models.py`.

---

## validate_profile()

Compares a `GraphProfile` against a `GraphDataModel`. Returns `ValidationResult`.

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

Source: `src/orthograph/extensions/validation.py`.

---

## GQLAlchemy Extension (different pattern)

The `gqlalchemy/` subpackage is an **interaction layer**, not an inspection layer.
It provides OGM capabilities and query builder integration with schema validation on all data paths.
Does not implement `GraphInspector`.

See `decisions/006-gqlalchemy-integration.md` for the design rationale.

---

## Adding a New Inspection Backend

1. Create `extensions/<backend>/inspector.py`
2. Implement `class MyBackendInspector(GraphInspector)`
3. Implement `inspect() -> GraphProfile` using the backend's API
4. Validation comes for free via `validate_profile(profile, model)`
