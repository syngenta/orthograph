# Epic E16: Query Catalogue — Unified Interface, Cypher Query Model, and Typed Backends

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Supersedes:** E6 (Cypher Query Catalogue), E12 (Shared Interface Extraction), E13 (Typed
> Contract), E15 (Typed Cypher Backend). Those four epics are **retired**; their tasks are
> reformulated here in an order that resolves the tensions between them.
> **Blocked by:** None — can start immediately
> **Unblocks:** E8 (GQLAlchemy catalogue), E11 (CRUD auto-generation), E14 (SQLAlchemy backend),
> matterforge Phase 2 (E9, E10)

---

## Why This Consolidation Was Needed: The Four Tensions

Before the tasks, here are the concrete design conflicts that the retired epics left unresolved.
Any agent picking up a task from E6/E12/E13/E15 would have produced code that conflicts.

### Tension 1 — Two incompatible registration models both called "catalogue"

E6 defined a **string-key registry**: `catalogue.register("my_query", cypher_str, params_spec,
returns_spec)` / `catalogue.execute("my_query", params, connection=conn)`. The query is identified
at runtime by a string; the return type is untyped.

E13 defined a **typed-object registry**: `catalogue.register_read(MyQuery())` where `MyQuery` is
a Python class carrying `Output: type[Sample]`; the type checker knows the return is `list[Sample]`
at every call site.

These are **not two tiers** — they are fundamentally different patterns with different call sites,
different type safety properties, and different serialisability. Calling them "two tiers of one
catalogue" implied a shared call surface that does not exist.

**Resolution:** they are **two distinct catalogue types** serving two distinct use cases.
Each gets a clear definition and a clear decision rule for when to use it.

### Tension 2 — The Cypher query data model has two incompatible shapes

E6's `QueryDefinition` is a **data structure** (serialisable to YAML): `(name, cypher: str,
parameters: list[ParamSpec], returns: dict)`. It holds the query as a raw string.

E15's `CypherReadQuery` is a **Python class** with a `build()` method that returns
`(cypher: str, params_dict)` and a `materialize(record: dict) -> D` method. The query and the
materialisation logic are inseparable and cannot be serialised to YAML.

**Resolution:** the Cypher query data model must have a single canonical representation that
*both* authoring modes (YAML and class) produce or conform to — and the materialisation question
(who maps driver records to domain objects?) must be answered per mode.

### Tension 3 — YAML-loaded queries have no `materialize()`, typed queries have no YAML

A YAML-loaded query produces raw driver records. A typed `CypherReadQuery.materialize()` is
Python code. Neither bridged the gap.

**Resolution:** make the materialisation strategy explicit and pluggable:
- String-key catalogue path: materialisation is **optional and separate** — the consumer provides
  a `materializer: Callable[[record], DomainType]` at registration or at call time.
- Typed path: materialisation is **declared on the class** and always present.

### Tension 4 — E12's "extract the common ABC" targets a non-existent commonality

E12's proposed `QueryCatalogue(Protocol)` with `execute(name: str, ...)` describes the string-key
catalogue only. It cannot describe the typed catalogue (which has no `execute(name: str, ...)`).
Extracting a single ABC that covers both would produce a `Protocol` so broad it adds nothing.

**Resolution:** there is no single `QueryCatalogue` base class. The two catalogues share a
**naming convention** and a **`describe()` introspection surface** (both can enumerate their
queries as `QueryDescription` records with JSON Schema), but their registration and execution
surfaces are intentionally different. Document this clearly rather than abstracting it away.

---

## The Unified Cypher Query Data Model (design decision, resolved here)

A Cypher query in orthograph has exactly these fields, regardless of how it was authored:

```
CypherQueryDefinition
  name: str                       # unique within a catalogue
  cypher: str                     # the Cypher string (with $param placeholders)
  params: list[ParamSpec]         # name, type, required, default
  returns: ReturnSpec             # flat field map OR a NodeModel reference OR list of NodeModel
  description: str | None
  validated: bool                 # True after validate_cypher() was run at registration
```

`ReturnSpec` covers three cases:
- **Flat projection** — `{"total": int, "label": str}` — like E6 had
- **NodeModel reference** — `{"type": "node", "model": Protocol}` — new; enables auto-materialise
- **List of NodeModel** — `{"type": "node_list", "model": Sample}` — the common read case

**Authoring modes:**

| Mode | How it produces a `CypherQueryDefinition` |
|---|---|
| **YAML** | loaded via `load_catalogue_config(path)`, parsed into `CypherQueryDefinition` records |
| **Python class** (`CypherReadQuery` subclass) | `to_definition()` method synthesises a `CypherQueryDefinition` from the class's `build()` output (called with dummy params) and `Output` type |
| **Runtime registration** | `catalogue.register(name, cypher, params, returns)` constructs directly |

**Materialisation strategy per mode:**

| Case | Who materialises |
|---|---|
| String-key catalogue, flat projection returns | consumer provides `materializer=` callable, or gets raw record |
| String-key catalogue, NodeModel returns | auto-materialise: catalogue calls `NodeModel(**record_fields)` using the declared model |
| Typed catalogue (`CypherReadQuery` subclass) | the class's own `materialize(record)` method — always present, type-checked |

This is the decision E6 never made and E15 assumed without stating.

---

## Package Structure (outcome of this epic)

```
src/orthograph/catalogue/
  __init__.py          exports both catalogues + typed contract; explains the two-model split
  typed.py             ReadQuery/WriteQuery/Executor/QueryCatalogue/ReadPort (typed tier)
  models.py            CypherQueryDefinition, ParamSpec, ReturnSpec, QueryDescription
  loader.py            load_catalogue_config(path) -> list[CypherQueryDefinition]
  validation.py        validate_catalogue(definitions, model) -> ValidationResult
  cypher.py            StringKeyCypherCatalogue (replaces E6's CypherQueryCatalogue)
  base.py              shared describe() mixin (both catalogues expose describe())

src/orthograph/extensions/cypher/
  typed_queries.py     CypherReadQuery / CypherWriteQuery (typed tier — from E15)
  executor.py          CypherExecutor (typed tier — from E15)
  [generator.py        UNCHANGED — kept as-is]
  [parser.py           UNCHANGED — kept as-is]
```

---

## Tasks

### T1: Define the Cypher query data model (`catalogue/models.py`)

**What:** The canonical data structures for a Cypher query — the single representation that both
YAML-loaded and class-defined queries conform to. This resolves Tension 2 and 3.

**Actions:**
1. Create `src/orthograph/catalogue/models.py`:
   ```python
   from __future__ import annotations
   from dataclasses import dataclass, field
   from typing import Any, Literal

   from pydantic import BaseModel
   from orthograph.core.node_model import NodeModel

   @dataclass(frozen=True)
   class ParamSpec:
       name: str
       type: type        # int, str, float, bool — python primitive
       required: bool = True
       default: Any = None

   @dataclass(frozen=True)
   class FlatReturnSpec:
       """Returns a flat dict projection (not a domain node)."""
       kind: Literal["flat"] = "flat"
       fields: dict[str, type] = field(default_factory=dict)  # field_name -> python type

   @dataclass(frozen=True)
   class NodeReturnSpec:
       """Returns instances of a declared NodeModel. Enables auto-materialise."""
       kind: Literal["node"] = "node"
       model: type[NodeModel]
       many: bool = True   # True -> list[NodeModel]; False -> NodeModel | None

   ReturnSpec = FlatReturnSpec | NodeReturnSpec

   @dataclass
   class CypherQueryDefinition:
       name: str
       cypher: str
       params: list[ParamSpec] = field(default_factory=list)
       returns: ReturnSpec = field(default_factory=FlatReturnSpec)
       description: str | None = None
       validated: bool = False   # set True by validate_catalogue()
   ```

2. Tests:
   - `CypherQueryDefinition` with `NodeReturnSpec(model=Protocol)` stores the model by
     direct reference (not by string label — Tension 1/string-key resolution).
   - `FlatReturnSpec` and `NodeReturnSpec` are distinguishable by `kind` field (discriminated union
     pattern; avoids isinstance sprawl downstream).
   - A `CypherQueryDefinition` is serialisable to `dict` (for YAML round-trip tests in T2).

**Verification:** `from orthograph.catalogue.models import CypherQueryDefinition, NodeReturnSpec` works.

---

### T2: YAML loader (`catalogue/loader.py`)

**What:** Load a YAML catalogue file into a list of `CypherQueryDefinition` records. This is E6.1
reformulated against the new data model.

**Actions:**
1. Create `src/orthograph/catalogue/loader.py`.
2. Define the YAML schema (document in a module-level docstring):
   ```yaml
   # catalogue.yaml
   version: "1"
   queries:
     find_protocols_by_version:
       cypher: "MATCH (p:Protocol {version: $version}) RETURN p.protocol_id, p.name"
       description: "Find all protocols at a given version"
       params:
         - name: version
           type: str
           required: true
       returns:
         kind: flat
         fields:
           protocol_id: int
           name: str
     samples_for_protocol:
       cypher: "MATCH (p:Protocol {protocol_id: $pid})<-[:HAS_OPERATION]-(op)<-[:PRODUCES]-(s) RETURN s"
       params:
         - name: pid
           type: int
           required: true
       returns:
         kind: node
         model: Sample          # resolved against a model_map at load time
         many: true
   ```
3. Implement:
   ```python
   def load_catalogue(
       path: str | Path,
       model_map: dict[str, type[NodeModel]] | None = None,
   ) -> list[CypherQueryDefinition]:
       """Load a YAML catalogue. model_map resolves NodeModel labels in 'node' returns.
       If model_map is None, node returns are stored with the label string only and
       resolved lazily on first use."""
   ```
4. Tests:
   - Valid YAML with flat returns loads correctly.
   - Valid YAML with node returns resolves the model label against `model_map`.
   - Unknown model label in a node return raises `CatalogueLoadError` with the query name.
   - Invalid YAML raises `CatalogueLoadError`.
   - Missing required field raises `CatalogueLoadError`.

**Verification:** `from orthograph.catalogue.loader import load_catalogue` works.

---

### T3: Catalogue validation (`catalogue/validation.py`)

**What:** Validate `CypherQueryDefinition` records against a `GraphDataModel`. E6.2 reformulated.

**Actions:**
1. Create `src/orthograph/catalogue/validation.py`:
   ```python
   def validate_catalogue(
       definitions: list[CypherQueryDefinition],
       model: GraphDataModel,
   ) -> ValidationResult:
       """Validate every query definition against the schema.
       Reuses validate_cypher() from extensions/cypher/parser.py for structural checks.
       Additionally validates:
       - NodeReturnSpec.model label exists in the GraphDataModel
       - All param names referenced in $placeholders are declared in params list
       """
   ```
2. Tests:
   - Valid definitions against a matching model → empty result.
   - Query with unknown label → `ValidationIssue(severity=ERROR, entity_id=query_name)`.
   - Query with `$param` placeholder but no matching `ParamSpec` → `ValidationIssue`.
   - Multiple queries, multiple errors — all collected (no fail-fast).

**Verification:** `from orthograph.catalogue.validation import validate_catalogue` works.

---

### T4: `StringKeyCypherCatalogue` — the named-string registry (`catalogue/cypher.py`)

**What:** The E6.3 `CypherQueryCatalogue` reformulated to use `CypherQueryDefinition` internally.
Named string dispatch; optional auto-materialise for NodeModel returns; schema-validated at registration.

This is the **string-key tier**. Its `execute(name, params, connection=conn)` call surface is
unchanged from E6. The internal data model is now `CypherQueryDefinition` (from T1).

**Actions:**
1. Create `src/orthograph/catalogue/cypher.py`:
   ```python
   class StringKeyCypherCatalogue:
       """Named-string Cypher query registry.

       Use this when:
       - queries come from YAML configuration
       - you want schema validation at registration time
       - the call site does not need Python-level type checking on the return type

       For typed, domain-object-returning queries with IDE type safety, use
       CypherReadQuery (extensions/cypher/typed_queries.py) with a TypedQueryCatalogue.
       """
       def __init__(self, model: GraphDataModel, auto_validate: bool = True) -> None: ...

       @classmethod
       def from_yaml(
           cls, path: str | Path, model: GraphDataModel,
           model_map: dict[str, type[NodeModel]] | None = None,
       ) -> StringKeyCypherCatalogue:
           """Load, validate, and construct from a YAML file."""

       def register(
           self,
           definition: CypherQueryDefinition | None = None,
           *,
           name: str | None = None,
           cypher: str | None = None,
           params: list[ParamSpec] | None = None,
           returns: ReturnSpec | None = None,
       ) -> None:
           """Register from a CypherQueryDefinition OR from keyword args (runtime convenience).
           Validates against the GraphDataModel immediately."""

       def execute(
           self,
           name: str,
           params: dict,
           connection: Any,
           materializer: Callable[[dict], Any] | None = None,
       ) -> list[Any]:
           """Execute by name. Connection passed per-call (never stored).
           If returns is NodeReturnSpec and materializer is None: auto-materialise via NodeModel.
           If returns is FlatReturnSpec and materializer is None: return raw record dicts."""

       def describe(self) -> list[QueryDescription]:
           """Unified introspection — same surface as TypedQueryCatalogue."""

       def query_names(self) -> list[str]: ...
       def get_definition(self, name: str) -> CypherQueryDefinition: ...
   ```

2. Auto-materialise for NodeModel returns:
   ```python
   # inside execute(), when returns.kind == "node":
   def _auto_materialize(self, rec: dict, model: type[NodeModel]) -> NodeModel:
       # strips driver-specific key prefixes (e.g. "s." from RETURN s.field)
       # constructs model(**cleaned_fields)
       # raises CatalogueMaterializeError with field list if construction fails
   ```

3. Tests:
   - `from_yaml` loads flat-return query; `execute` returns list of raw dicts.
   - `from_yaml` loads node-return query; `execute` auto-materialises → `list[NodeModel]`.
   - `register` with bad Cypher (unknown label) raises `CatalogueValidationError`.
   - `execute` with unknown name raises `KeyError`.
   - `execute` with missing required param raises `ValueError` before any driver call.
   - `describe()` returns `QueryDescription` with `params_schema` and `output_schema`.
   - Connection is never stored; two `execute` calls can use different connections.

**Verification:** `from orthograph.catalogue import StringKeyCypherCatalogue` works.
Backward compatibility alias: `CypherQueryCatalogue = StringKeyCypherCatalogue` for existing code.

---

### T5: `TypedQueryCatalogue` and the typed contract (`catalogue/typed.py`)

**What:** E13's typed contract (ReadQuery/WriteQuery/Executor/QueryCatalogue/ReadPort), keeping
everything from E13 but renamed to `TypedQueryCatalogue` to avoid the name collision with
`StringKeyCypherCatalogue` and making the split explicit at the API level.

**Actions:**
1. Create `src/orthograph/catalogue/typed.py` as described in E13 (tasks E13.1–E13.3 are
   adopted verbatim). The class previously called `QueryCatalogue` becomes `TypedQueryCatalogue`:
   ```python
   class TypedQueryCatalogue:
       """Typed object registry for ReadQuery/WriteQuery instances.

       Use this when:
       - queries are Python classes declaring Output type statically
       - you want IDE go-to-definition and type-checker enforcement on the return type
       - queries may span multiple backends (SQL + Cypher) and you want uniform introspection

       For YAML-configured string-key queries, use StringKeyCypherCatalogue.
       """
   ```
2. `TypedQueryCatalogue.describe()` returns the same `QueryDescription` shape as
   `StringKeyCypherCatalogue.describe()`. This is the **one shared surface** between the two tiers.
3. Export aliases for backward compat with E13 tasks already written:
   `QueryCatalogue = TypedQueryCatalogue`.

Tests: adopt all tests from E13.1–E13.3 verbatim.

**Verification:** `from orthograph.catalogue.typed import ReadQuery, WriteQuery, TypedQueryCatalogue,
ReadPort, Executor` works.

---

### T6: `CypherReadQuery.to_definition()` — the bridge between typed and string-key

**What:** Every `CypherReadQuery` subclass can produce a `CypherQueryDefinition` from itself.
This resolves Tension 2/3: a typed class can participate in the string-key catalogue, or its
definition can be round-tripped to YAML for documentation.

**Actions:**
1. In `extensions/cypher/typed_queries.py`, add to `CypherReadQuery`:
   ```python
   def to_definition(self, dummy_params: dict | None = None) -> CypherQueryDefinition:
       """Synthesise a CypherQueryDefinition from this class.

       Calls build() with dummy_params (or auto-generated dummy values from Params schema)
       to extract the Cypher string. Derives params list from Params.model_json_schema().
       Derives returns from Output type (NodeReturnSpec if Output is a NodeModel,
       FlatReturnSpec otherwise).
       """
       params = dummy_params or _make_dummy_params(self.Params)
       cypher, _ = self.build(self.Params.model_validate(params))
       param_specs = _params_from_schema(self.Params.model_json_schema())
       return_spec = (
           NodeReturnSpec(model=self.Output)
           if issubclass(self.Output, NodeModel)
           else FlatReturnSpec(fields=_fields_from_schema(self.Output.model_json_schema()))
       )
       return CypherQueryDefinition(
           name=self.name,
           cypher=cypher,
           params=param_specs,
           returns=return_spec,
           description=self.__doc__,
       )
   ```

2. Tests:
   - `GraphSamplesByProtocol().to_definition()` returns a `CypherQueryDefinition` with
     `returns.kind == "node"` and `returns.model is Sample`.
   - The definition can be registered into a `StringKeyCypherCatalogue` and executed.
   - A query with `FlatReturnSpec` output produces `returns.kind == "flat"`.

**Why this matters:** it makes the two tiers interoperable. A matterforge `CypherReadQuery`
can be introspected as a `CypherQueryDefinition` by tooling (e.g. docs generators) that
only speaks the string-key model, without needing to know about the typed tier.

---

### T7: Typed Cypher backend (`extensions/cypher/typed_queries.py` + `executor.py`)

**What:** E15's tasks E15.1–E15.4 adopted verbatim, but in the context of E16's unified
data model. `CypherReadQuery` now additionally carries `to_definition()` from T6.

**Actions:** Implement E15.1 (`CypherReadQuery`/`CypherWriteQuery`), E15.2 (`CypherExecutor`),
E15.3 (integration proof test), E15.4 (notebook), exactly as specified in E15, plus the
`to_definition()` method from T6.

No changes to the E15 task content; just adding T6 to the class.

---

### T8: Shared `describe()` surface and `QueryDescription` (`catalogue/base.py`)

**What:** The one concrete thing both catalogues share: a `describe()` method returning a list of
`QueryDescription` records with uniform JSON Schema for params and output. This is the real answer
to what E12 was trying to extract.

**Actions:**
1. Create `src/orthograph/catalogue/base.py`:
   ```python
   @dataclass
   class QueryDescription:
       name: str
       kind: Literal["read", "write"]
       backend: Backend
       params_schema: dict      # JSON Schema of the Params type/spec
       output_schema: dict | None   # JSON Schema of the return type; None for writes

   class DescribableCatalogue(Protocol):
       """The one surface shared by both catalogue tiers.
       Both StringKeyCypherCatalogue and TypedQueryCatalogue satisfy this."""
       def describe(self) -> list[QueryDescription]: ...
       def query_names(self) -> list[str]: ...
   ```

2. Both `StringKeyCypherCatalogue` and `TypedQueryCatalogue` satisfy `DescribableCatalogue`.
3. Tests:
   - A function typed `(cat: DescribableCatalogue) -> list[str]` accepts both catalogue types
     (structural subtyping check).
   - `describe()` from both returns `QueryDescription` with identical schema for the same
     logical query (e.g. a `CypherReadQuery` registered in a `TypedQueryCatalogue` and its
     `to_definition()` registered in a `StringKeyCypherCatalogue` produce the same output schema).

**Verification:** `from orthograph.catalogue import DescribableCatalogue` works. This is what
E12 should have been.

---

### T9: Public API and `__init__.py` (`catalogue/__init__.py`)

**Actions:**
1. Update `src/orthograph/catalogue/__init__.py` to export:
   ```python
   # Typed tier
   from orthograph.catalogue.typed import (
       ReadQuery, WriteQuery, Executor, TypedQueryCatalogue, ReadPort, QueryBackedReadPort,
   )
   # String-key tier
   from orthograph.catalogue.cypher import StringKeyCypherCatalogue
   CypherQueryCatalogue = StringKeyCypherCatalogue  # backward-compat alias

   # Shared
   from orthograph.catalogue.base import DescribableCatalogue, QueryDescription
   from orthograph.catalogue.models import CypherQueryDefinition, ParamSpec, NodeReturnSpec, FlatReturnSpec

   # Convenience re-export
   from orthograph.catalogue.loader import load_catalogue
   from orthograph.catalogue.validation import validate_catalogue
   ```
2. Module docstring must contain the decision table:
   ```
   WHICH CATALOGUE TO USE:
   ┌─────────────────────────────────┬──────────────────────────────────────────┐
   │ StringKeyCypherCatalogue        │ TypedQueryCatalogue                      │
   ├─────────────────────────────────┼──────────────────────────────────────────┤
   │ Queries come from YAML          │ Queries are Python classes               │
   │ String-key dispatch at call     │ Type-checked return type at call site    │
   │ Schema-validated at registration│ Pure build(); no session needed          │
   │ Auto-materialise for NodeModel  │ Query owns its materialize()             │
   │ returns; raw dict for flat      │ Registered with typed register_read/write│
   │ Suitable for external config    │ Suitable for matterforge, mp-backend     │
   └─────────────────────────────────┴──────────────────────────────────────────┘
   Both expose describe() → list[QueryDescription] for uniform introspection.
   ```
3. Notebook `04.01_query_catalogue.ipynb`: shows StringKeyCypherCatalogue from YAML.
4. Notebook `04.02_typed_query_catalogue.ipynb`: shows TypedQueryCatalogue with CypherReadQuery.

---

### T10: E8 alignment (GQLAlchemy catalogue)

**What:** E8 was blocked by E6 and planned to share E6's registry interface. Now that the
interface is resolved in E16, E8 needs explicit alignment.

**Actions:**
1. E8 (`GqlAlchemyQueryCatalogue`) is a **third registration model** — Python-only builder
   expressions (no YAML, no string Cypher, no typed generics on the return). It is neither the
   string-key tier nor the typed tier.
2. Add `GqlAlchemyQueryCatalogue.describe() -> list[QueryDescription]` so it satisfies
   `DescribableCatalogue` (the one shared surface).
3. Update E8's "Blocked by" to "E16" (instead of E6).
4. No other changes to E8's task content.

---

### T11: E11 alignment (CRUD auto-generation)

**What:** E11 generates CRUD entries into `CypherQueryCatalogue` and `GqlAlchemyQueryCatalogue`.
With E16 in place, clarify which catalogue tier auto-CRUD targets.

**Actions:**
1. Auto-generated Cypher CRUD entries are produced as `CypherQueryDefinition` records
   (not as `CypherReadQuery` subclasses — they are data, not code). They register into
   `StringKeyCypherCatalogue`.
2. For `TypedQueryCatalogue` users who want CRUD, a factory function
   `crud_read_queries_for(node_type) -> list[CypherReadQuery]` generates typed instances
   (separate from the string-key path).
3. Update E11's `generate_cypher_crud_catalogue()` signature to return
   `StringKeyCypherCatalogue` (explicit).
4. No other changes to E11's task content.

---

## Task Execution Order

```
T1 (models.py)          ← no dependencies; do first
T8 (base.py)            ← depends on T1 (QueryDescription references models)
T2 (loader.py)          ← depends on T1
T3 (validation.py)      ← depends on T1; reuses existing cypher/parser.py
T4 (StringKeyCypher)    ← depends on T1, T2, T3, T8
T5 (TypedCatalogue)     ← depends on T8; independent of T1-T4
T6 (to_definition)      ← depends on T1 + T5
T7 (CypherReadQuery)    ← depends on T5 + T6
T9 (public API)         ← depends on T4, T5, T7, T8
T10 (E8 alignment)      ← depends on T8
T11 (E11 alignment)     ← depends on T4
```

Earliest parallelism:
- T1 → T2 and T8 in parallel
- T4 and T5 in parallel (after T1+T2+T3 / T8 respectively)
- T6 and T7 together after T5

---

## Relationship to Other Epics

- **E8 (GQLAlchemy)** — unblocked by this epic; uses T8's `DescribableCatalogue` to expose `describe()`.
- **E11 (CRUD)** — targets `StringKeyCypherCatalogue` (T11 alignment).
- **E14 (SQLAlchemy backend)** — implements `ReadQuery`/`WriteQuery` from T5; unchanged by E16.
- **matterforge E9** — imports `TypedQueryCatalogue`, `ReadQuery`, `CypherReadQuery` from T5/T7.
- **E6, E12, E13, E15** — **retired**; see header. Their tasks are wholly superseded by this epic.
