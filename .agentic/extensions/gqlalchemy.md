# GQLAlchemy Extension -- Integration Plan

> Read `overview.md` first for the two-phase architecture.
> Read `../decisions.md` entry "2026-04-17: GQLAlchemy Integration" for the rationale.

## Goal

Add GQLAlchemy as an **optional extension** of Orthograph, providing:

1. **OGM capabilities** (save/load/merge graph objects) powered by GQLAlchemy
2. **Query builder** (fluent Cypher construction + execution) powered by GQLAlchemy
3. **Schema-validated I/O** -- all reads and writes pass through Orthograph validation

Users define models once in Orthograph (`NodeModel` / `RelationshipModel`).
GQLAlchemy classes are auto-generated behind the scenes. Users never import
GQLAlchemy directly -- they interact through the Orthograph extension API.

## Scope

### In scope (this extension)

| Capability | Description |
|---|---|
| Model codegen | Auto-generate GQLAlchemy `Node`/`Relationship` classes from Orthograph `NodeModel`/`RelationshipModel` |
| Validated client | Wrapper around GQLAlchemy's `Memgraph`/`Neo4j` that adds pre-save and post-load validation |
| Query builder bridge | Execute GQLAlchemy query builder chains with optional Cypher validation |
| Result adapter | Convert GQLAlchemy query results to Orthograph-validatable dicts |
| Database validation | Full database profiling via existing Orthograph inspectors (reuse, not rewrite) |

### Out of scope (deferred or not planned)

| Item | Reason |
|---|---|
| Modifying GQLAlchemy source code | GQLAlchemy is an external dependency; only Orthograph is modified |
| Index/constraint auto-creation | Deferred; users can use GQLAlchemy directly or Orthograph's `CypherGenerator.generate_constraints()` |
| Kafka/Pulsar stream management | GQLAlchemy-specific infrastructure; not a schema concern |
| Instance management (Docker/binary) | GQLAlchemy-specific; not a schema concern |
| On-disk storage | GQLAlchemy-specific |
| Data import (CSV/Parquet/Arrow) | GQLAlchemy-specific ETL; may be considered later |
| DGL/PyG graph translation | GQLAlchemy-specific ML integration |
| Cardinality enforcement on write | Deferred -- decision to be made later (requires extra DB queries) |

## Architecture

### New files

```
src/orthograph/extensions/gqlalchemy/
├── __init__.py           # Public API re-exports
├── codegen.py            # generate_gqlalchemy_classes() -- model translation
├── client.py             # GqlAlchemyClient -- validated wrapper
├── query_builder.py      # ValidatedQueryBuilder -- query validation bridge
└── result_adapter.py     # Convert GQLAlchemy objects to validation dicts
```

### Test files

```
tests/extensions/gqlalchemy/
├── __init__.py
├── conftest.py           # Shared fixtures (model, mock db)
├── test_codegen.py       # Class generation, property mapping, round-trip
├── test_client.py        # Validated save/load, rejection on bad data
├── test_query_builder.py # Query validation, execution
└── test_result_adapter.py # Result conversion
```

### How it fits into the existing architecture

```
                         ORTHOGRAPH CORE
                    ┌─────────────────────┐
                    │  NodeModel          │
                    │  RelationshipModel  │
                    │  GraphDataModel     │
                    │  GraphValidator     │
                    └────────┬────────────┘
                             │ defines schema
                    ┌────────┴────────────┐
                    │  extensions/         │
                    │  gqlalchemy/         │
                    │                     │
                    │  ┌───────────────┐  │
                    │  │  codegen.py   │  │  Orthograph models ──► GQLAlchemy classes
                    │  └───────┬───────┘  │
                    │          │           │
                    │  ┌───────┴───────┐  │
                    │  │  client.py    │  │  Validate ──► GQLAlchemy save/load ──► Validate
                    │  └───────┬───────┘  │
                    │          │           │
                    │  ┌───────┴───────┐  │
                    │  │query_builder  │  │  GQLAlchemy QB ──► Cypher ──► Validate ──► Execute
                    │  └───────┬───────┘  │
                    │          │           │
                    │  ┌───────┴───────┐  │
                    │  │result_adapter │  │  GQLAlchemy results ──► Orthograph dicts ──► Validate
                    │  └───────────────┘  │
                    └─────────────────────┘
                             │
                    ┌────────┴────────────┐
                    │  GQLAlchemy (ext.)  │  External dependency, unmodified
                    │  Memgraph / Neo4j   │
                    └─────────────────────┘
```

## Module Details

### 1. `codegen.py` -- Model Code Generation

**Purpose:** Translate Orthograph model definitions into GQLAlchemy-compatible
`Node` and `Relationship` subclasses at runtime.

**Key function:**

```python
def generate_gqlalchemy_classes(
    model: GraphDataModel,
) -> GqlAlchemySchema:
    """
    Given an Orthograph GraphDataModel, dynamically create GQLAlchemy
    Node and Relationship subclasses for every node type and
    relationship type in the model.

    Returns a GqlAlchemySchema holding the generated classes.
    """
```

**`GqlAlchemySchema` data class:**

```python
@dataclass
class GqlAlchemySchema:
    node_classes: dict[str, type[GqaNode]]       # keyed by __label__
    rel_classes: dict[str, type[GqaRelationship]] # keyed by __label__

    def get_node_class(self, label: str) -> type[GqaNode]: ...
    def get_rel_class(self, rel_type: str) -> type[GqaRelationship]: ...
```

**Translation rules:**

| Orthograph concept | GQLAlchemy equivalent |
|---|---|
| `NodeModel.__label__` | `class Foo(Node, label="Foo")` |
| `RelationshipModel.__label__` | `class Bar(Relationship, type="BAR")` |
| `__uid_field__ = "name"` | `name: str = Field(unique=True)` (*) |
| Required property `name: str` | `name: str` |
| Optional property `born: Optional[int] = None` | `born: Optional[int] = None` |
| `__source_type__`, `__target_type__` | Not representable -- enforced by Orthograph |
| `__source_cardinality__`, `__target_cardinality__` | Not representable -- enforced by Orthograph |
| `__directed__` | Not representable -- enforced by Orthograph |
| `__optional__` | Not representable -- enforced by Orthograph |

(*) `unique=True` without `db=` avoids triggering index/constraint creation
at class definition time. The `Field(unique=True)` is metadata-only; constraint
creation is explicitly out of scope for this phase.

**Pydantic v1/v2 challenge:**

GQLAlchemy's `Node` and `Relationship` inherit from `pydantic.v1.BaseModel`.
Orthograph's models use Pydantic v2. These cannot share a class hierarchy.
The codegen creates **entirely new classes** using `type()` that inherit from
GQLAlchemy's base classes and declare fields using Pydantic v1 annotations.

Type translation from v2 to v1 annotations:

| Pydantic v2 (Orthograph) | Pydantic v1 (GQLAlchemy) |
|---|---|
| `str` | `str` |
| `int` | `int` |
| `float` | `float` |
| `bool` | `bool` |
| `Optional[str]` | `Optional[str]` |
| `list[str]` | `list` (simplified) |
| `dict[str, Any]` | `dict` (simplified) |

Simple types pass through. Complex generic types are simplified since GQLAlchemy
stores them as-is in Cypher (lists/dicts become native Cypher lists/maps).

### 2. `client.py` -- Validated Client

**Purpose:** Thin wrapper around GQLAlchemy's `DatabaseClient` (either `Memgraph`
or `Neo4j`) that adds Orthograph schema validation on all data paths.

```python
class GqlAlchemyClient:
    def __init__(
        self,
        model: GraphDataModel,
        db: Any,  # GQLAlchemy Memgraph or Neo4j instance
    ):
        self._model = model
        self._db = db
        self._schema = generate_gqlalchemy_classes(model)
        self._validator = GraphValidator()
```

**Methods:**

| Method | Validation | GQLAlchemy call |
|---|---|---|
| `save_node(data, node_type)` | Pre-save: validate data dict against `NodeModel` | `gqa_node.save(db)` |
| `save_relationship(data, rel_type, start_node_id, end_node_id)` | Pre-save: validate data + endpoint types | `gqa_rel.save(db)` |
| `load_node(node_type, **properties)` | Post-load: validate returned data | `gqa_node.load(db)` |
| `load_relationship(rel_type, start_id, end_id)` | Post-load: validate returned data | `gqa_rel.load(db)` |
| `execute(query, params)` | None (raw passthrough) | `db.execute_and_fetch(query)` |
| `execute_validated(query_or_builder, params)` | Pre-exec: validate Cypher; Post-exec: validate results (opt-in) | `db.execute_and_fetch(query)` |
| `validate_database()` | Full profile validation | Uses existing inspectors |

**Validation flow for `save_node`:**

```
User dict ──► Orthograph GraphValidator.validate_nodes([dict], model)
           │
           ├── FAIL: raise ValidationError with structured issues
           │
           └── PASS: instantiate GQLAlchemy Node class ──► node.save(db)
                                                          │
                                                          └── return saved node data as dict
```

**Validation flow for `execute_validated`:**

```
Query builder / Cypher string
    │
    ├── Extract Cypher string (str(builder) or raw string)
    │
    ├── orthograph.extensions.cypher.validate_cypher(cypher, model)
    │   ├── FAIL: raise/return ValidationResult with issues
    │   └── PASS: continue
    │
    ├── db.execute_and_fetch(cypher)
    │
    ├── (opt-in) Convert results ──► validate against model
    │
    └── return results
```

### 3. `query_builder.py` -- Query Validation Bridge

**Purpose:** Enable using GQLAlchemy's fluent query builder with Orthograph
schema validation.

**Key class:**

```python
class ValidatedQueryBuilder:
    def __init__(self, model: GraphDataModel, db: Any):
        self._model = model
        self._db = db

    def execute_validated(
        self,
        builder: Any,
        validate_results: bool = False,
    ) -> list[dict[str, Any]]:
        """
        1. Extract Cypher from builder via str()
        2. Validate Cypher against model (labels, types, properties)
        3. Execute the query
        4. If validate_results=True, validate output against model
        5. Return results
        """

    def validate_query(self, builder: Any) -> ValidationResult:
        """
        Validate the query without executing it.
        Useful for static analysis / CI checks.
        """
```

**Design decision: wrapping, not replacing.**

The query builder is NOT re-implemented. Users construct queries using
GQLAlchemy's native API (`match()`, `create()`, `merge()`, etc.) and
pass the builder object to `execute_validated()`. The bridge adds validation
on top, not a new query language.

```python
from gqlalchemy import match
from orthograph.extensions.gqlalchemy import ValidatedQueryBuilder

vqb = ValidatedQueryBuilder(model=model, db=db)

# Use GQLAlchemy's native query builder
builder = (
    match()
    .node(labels="Person", variable="p")
    .to(relationship_type="ACTED_IN")
    .node(labels="Movie", variable="m")
    .return_()
)

# Execute with schema validation
results = vqb.execute_validated(builder, validate_results=True)
```

### 4. `result_adapter.py` -- Result Conversion

**Purpose:** Convert GQLAlchemy query result objects into Orthograph validation
dicts, mirroring `extensions/neo4j/result_adapter.py`.

**Key functions:**

```python
def gqa_node_to_dict(
    node: Any,  # GQLAlchemy Node instance
    model: GraphDataModel,
) -> dict[str, Any]:
    """Convert a GQLAlchemy Node to an Orthograph validation dict."""

def gqa_relationship_to_dict(
    rel: Any,  # GQLAlchemy Relationship instance
    model: GraphDataModel,
) -> dict[str, Any]:
    """Convert a GQLAlchemy Relationship to an Orthograph validation dict."""

def gqa_results_to_graph_data(
    results: list[dict[str, Any]],
    model: GraphDataModel,
) -> tuple[list[dict], list[dict]]:
    """Extract all nodes and relationships from GQLAlchemy result dicts."""

def validate_gqa_result(
    results: list[dict[str, Any]],
    model: GraphDataModel,
) -> ValidationResult:
    """Validate GQLAlchemy query results against the schema."""
```

**Conversion logic:**

GQLAlchemy returns results as dicts where values can be `Node` or `Relationship`
instances (if they were registered via `_subtypes_`). The adapter:

1. Iterates result dicts
2. Identifies `Node` instances (via `isinstance` or duck-typing on `_labels`)
3. Identifies `Relationship` instances (via `isinstance` or duck-typing on `_type`)
4. Extracts `__label__` from node labels (matching against model, like neo4j adapter)
5. Extracts properties (excluding `_`-prefixed internal attrs)
6. Returns flat dicts suitable for `GraphValidator.validate_nodes/validate_relationships`

## Pydantic v1/v2 Coexistence

### The problem

Orthograph: `pydantic >= 2.0` (v2 `BaseModel`)
GQLAlchemy: `from pydantic.v1 import BaseModel` (v1 compat shim)

Since Pydantic v2 ships the v1 module as `pydantic.v1`, both can coexist in
the same Python process. However:

- A class **cannot** inherit from both v1 and v2 `BaseModel`
- `Field()` from v1 and v2 are different objects
- Validators (v1 `@validator` vs v2 `@field_validator`) are incompatible

### The solution

The two model hierarchies are **completely separate**. No shared inheritance.
The codegen creates GQLAlchemy classes that live entirely in v1-land. Orthograph
classes live entirely in v2-land. The bridge layer converts between them using
plain dicts:

```
Orthograph (Pydantic v2)                    GQLAlchemy (Pydantic v1)
     │                                           │
     │  user-facing models                       │  internal transport classes
     │                                           │
     ▼                                           ▼
NodeModel.model_validate(data)    codegen    Node(**data)
     │                          ──────────►      │
     │  dict                                     │  dict
     └──────────────► plain dict ◄───────────────┘
                     (bridge layer)
```

### Testing the coexistence

A dedicated test must verify:

- `import orthograph` and `import gqlalchemy` both succeed
- Orthograph models and GQLAlchemy models can coexist in the same module
- `pydantic.VERSION` starts with `"2."` while `pydantic.v1.VERSION` exists
- Generated GQLAlchemy classes instantiate and validate correctly

## Deferred Decisions

| # | Decision | Status | Notes |
|---|----------|--------|-------|
| D1 | Cardinality enforcement on write | Deferred | Requires querying DB for current relationship count before save. Performance cost. Can be added later as `enforce_cardinality=True` on `GqlAlchemyClient`. |
| D2 | Result validation default | Decided: opt-in | `validate_results=False` by default on `execute_validated()`. Users enable with `validate_results=True`. Performance reason. |
| D3 | Index/constraint auto-creation | Deferred | Users can call `CypherGenerator.generate_constraints()` manually or use GQLAlchemy's `Field(unique=True, db=db)` directly. |
| D4 | Undirected relationship handling in OGM | Open | GQLAlchemy always creates directed relationships. For `__directed__=False`, the client could create both directions or use directionless MATCH. To be designed when needed. |
| D5 | Multi-label node support | Open | GQLAlchemy supports multi-label nodes (`labels=`). Orthograph currently has single `__label__`. Syncing these is future work. |

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pydantic v1/v2 runtime conflict | Low | High | Both shipped in same package since Pydantic 2.0. Test explicitly in CI. Pin `pydantic >= 2.0`. |
| GQLAlchemy's `Extra.allow` allows undeclared properties | Medium | Medium | Orthograph validates BEFORE save, catching extra properties. GQLAlchemy's permissiveness is never user-facing. |
| GQLAlchemy API breaking changes | Medium | Medium | Pin `gqlalchemy >= 1.6, < 2.0`. Wrap all imports behind extension boundary. |
| `type()` dynamic class generation fragile | Low | Medium | Comprehensive codegen tests with property round-trips. |
| Performance overhead from double validation | Low | Low | Pre-save validation is cheap (Pydantic). Post-load validation is opt-in. |
| GQLAlchemy requires `pymgclient` (C extension) on some platforms | Medium | Medium | Document in installation instructions. `pymgclient` is only needed for Memgraph; Neo4j path uses `neo4j` driver. |

## Implementation Phases

### Phase 1: Model codegen + unit tests

| # | Task | Description | Status |
|---|------|-------------|--------|
| G1 | `GqlAlchemySchema` data class | Container for generated classes | done |
| G2 | `generate_gqlalchemy_classes()` | Core codegen function | done |
| G3 | Node class generation | Property mapping, label, uid field | done |
| G4 | Relationship class generation | Property mapping, type | done |
| G5 | Type translation (v2 -> v1) | Handle Optional, list, dict, primitives | done |
| G6 | Codegen tests | Round-trip: Orthograph model -> GQLAlchemy class -> instantiate -> validate | done |
| G7 | Pydantic coexistence test | Verify v1/v2 both work in same process | done |

### Phase 2: Result adapter + unit tests

| # | Task | Description | Status |
|---|------|-------------|--------|
| G8 | `gqa_node_to_dict()` | Node instance -> validation dict | done |
| G9 | `gqa_relationship_to_dict()` | Relationship instance -> validation dict | done |
| G10 | `gqa_results_to_graph_data()` | Extract nodes/rels from result dicts | done |
| G11 | `validate_gqa_result()` | Full result validation | done |
| G12 | Result adapter tests | Mock GQLAlchemy objects, test conversion | done |

### Phase 3: Validated client + unit tests

| # | Task | Description | Status |
|---|------|-------------|--------|
| G13 | `GqlAlchemyClient.__init__` | Wire model, db, codegen, validator | done |
| G14 | `save_node()` with validation | Pre-validate, instantiate, save | done |
| G15 | `save_relationship()` with validation | Pre-validate, endpoint check, save | done |
| G16 | `load_node()` with validation | Load, convert, validate | pending |
| G17 | `load_relationship()` with validation | Load, convert, validate | pending |
| G18 | `execute()` raw passthrough | No validation, just proxy | done |
| G19 | `validate_database()` | Delegate to existing inspectors | done |
| G20 | Client tests | Mock GQLAlchemy db, test validation paths | done |

### Phase 4: Query builder bridge + unit tests

| # | Task | Description | Status |
|---|------|-------------|--------|
| G21 | `ValidatedQueryBuilder` class | Wrap GQLAlchemy query builder | done |
| G22 | `execute_validated()` | Extract Cypher, validate, execute | done |
| G23 | `validate_query()` | Static validation without execution | done |
| G24 | Query builder tests | Mock db, test validation + execution | done |

### Phase 5: Packaging, docs, notebook

| # | Task | Description | Status |
|---|------|-------------|--------|
| G25 | `__init__.py` public API | Re-exports | done |
| G26 | `pyproject.toml` optional dep | `gqlalchemy = ["gqlalchemy >= 1.6"]` | done |
| G27 | Notebook 09 | End-to-end GQLAlchemy integration walkthrough (design) | done |
| G28 | Update `.agentic/` docs | index, overview, progress, roadmap | done |

## Public API Summary

```python
from orthograph.extensions.gqlalchemy import (
    # Codegen
    generate_gqlalchemy_classes,
    GqlAlchemySchema,

    # Client
    GqlAlchemyClient,

    # Query builder
    ValidatedQueryBuilder,

    # Result adapter
    gqa_node_to_dict,
    gqa_relationship_to_dict,
    gqa_results_to_graph_data,
    validate_gqa_result,
)
```

## Dependencies

| Package | Version | Required for |
|---------|---------|-------------|
| `gqlalchemy` | >= 1.6 | All features in this extension |
| `pydantic` | >= 2.0 | Already a core dependency |
| `pymgclient` | (transitive) | Memgraph connections only |
| `neo4j` | >= 5.0 | Neo4j connections only |

The extension is **optional**. Importing `orthograph` without GQLAlchemy installed
works fine. Importing `orthograph.extensions.gqlalchemy` without GQLAlchemy raises
a clear `ImportError` with installation instructions.
