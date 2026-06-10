# Epic E16: Query Catalogue — Typed Contract, Cypher Backend, and Registry

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Supersedes:** E6 (Cypher Query Catalogue), E12 (Shared Interface Extraction), E13 (Typed
> Contract), E15 (Typed Cypher Backend). Those four epics are **retired**.
> **Blocked by:** None — can start immediately
> **Unblocks:** E8 (GQLAlchemy catalogue), E11 (CRUD auto-generation), E14 (SQLAlchemy backend),
> matterforge Phase 2 (E9, E10)
>
> **SCOPE NOTE:** This epic builds the **typed track only**, in strict implementation order:
> (1) Read/Write query generics + Executor → (2) Cypher concrete backend → (3) the catalogue.
> **YAML configuration is deliberately OUT of this epic's build scope** — it is an open
> architectural decision recorded at the bottom (see "OPEN DECISION: YAML"). We build the clean
> typed core first, then decide whether YAML earns its place or is dropped.

---

## Why This Consolidation Was Needed: The Tensions

The four retired epics left genuine, code-producing conflicts unresolved. Any agent implementing
them in their original form would produce files that conflict:

### Tension 1 — Two classes both named `QueryCatalogue`, with incompatible registration
- E13 defined `QueryCatalogue` with `register_read(MyQuery())` (typed object registry).
- E6 defined `CypherQueryCatalogue` with `register(name, cypher, ...)` / `execute("name", ...)`
  (string-key registry).
These are different patterns with different call sites and type-safety properties. They are NOT
two tiers of one thing.

### Tension 2 — Two incompatible Cypher query data models
- E6's `QueryDefinition` is a **data structure** (a string + a returns spec).
- E15's `CypherReadQuery` is a **Python class** with a `build()` method and a `materialize()`
  method. The materialisation logic is Python code that cannot be serialised.

### Tension 3 — E12's "extract a shared ABC" targets a non-existent commonality
E12's `execute(name: str, ...)` Protocol describes the string-key catalogue only; it cannot
describe the typed catalogue (which has no string-key dispatch).

### Resolution adopted by this epic
- There is **one typed catalogue** (`QueryCatalogue`) and **one typed query contract**
  (`ReadQuery`/`WriteQuery`). Built here, cleanly.

  > **Naming note (2026-06-10):** the registry class was implemented as `TypedQueryCatalogue`
  > and later renamed to **`QueryCatalogue`**. With the untyped string-key catalogue (retired E6)
  > gone, the "Typed" prefix disambiguated nothing. If a string-key/YAML variant is ever
  > introduced, the naming split will be decided at that point.
- The Cypher query is a **Python class** (`CypherReadQuery`) — the typed model wins for the core.
- The shared surface is `describe() → list[QueryDescription]`, defined up front (not "extracted
  later"). This is what E12 should have been.
- The string-key + YAML model from E6 is **not built in this epic**. Whether it returns at all is
  the open decision below.

---

## Implementation Order (build in this sequence)

```
STEP 1 — Typed query generics + Executor   (T1, T2)   no backend, no catalogue, no YAML
STEP 2 — Cypher concrete backend           (T3, T4)   first real backend; needs STEP 1
STEP 3 — QueryCatalogue + describe()   (T5, T6)   registry + introspection; needs STEP 1+2
STEP 4 — Public API + notebook             (T7)        wire-up; needs STEP 1-3
─────────────────────────────────────────────────────────────────────────────────────
THEN STOP. Decide YAML separately (see OPEN DECISION). Do not build YAML in this epic.
```

Package structure produced by STEPs 1–4:
```
src/orthograph/catalogue/
  __init__.py        exports the typed contract + catalogue (T7)
  typed.py           ReadQuery, WriteQuery, Executor, ReadPort, QueryBackedReadPort (T1, T2)
  registry.py        QueryCatalogue, QueryDescription, Backend (T5, T6)
src/orthograph/extensions/cypher/
  typed_queries.py   CypherReadQuery, CypherWriteQuery (T3)
  executor.py        CypherExecutor (T4)
  [generator.py, parser.py  UNCHANGED]
```

---

## STEP 1 — Typed query generics + Executor

### T1: `ReadQuery[P, D]` and `WriteQuery[P, R]` base classes

**What:** Abstract generic base classes enforcing the typed, pure-build, per-record-materialise
contract. No backend, no I/O. Lives in `src/orthograph/catalogue/typed.py`.

**Actions:**
1. Create `src/orthograph/catalogue/typed.py`.
2. Define type variables:
   ```python
   P = TypeVar("P", bound=BaseModel)   # Params — a Pydantic model (validated at boundary, R4)
   D = TypeVar("D", bound=BaseModel)   # Output — a NodeModel or projection BaseModel (R3)
   R = TypeVar("R")                    # Write result — rowcount, id, etc. (not a domain object)
   ```
3. Define `Backend` enum (descriptive tag only — NOT a dispatch switch):
   ```python
   class Backend(str, Enum):
       CYPHER = "cypher"
       SQLALCHEMY = "sqlalchemy"
       GQLALCHEMY = "gqlalchemy"
   ```
4. Define `ReadQuery(ABC, Generic[P, D])`:
   ```python
   class ReadQuery(ABC, Generic[P, D]):
       Params: ClassVar[type[BaseModel]]   # set by subclass; the P type
       Output: ClassVar[type[BaseModel]]   # set by subclass; the D type — DIRECT reference, no string
       name: ClassVar[str]
       backend: ClassVar[Backend]

       @abstractmethod
       def build(self, params: P) -> Any:
           """Pure, I/O-free construction of the backend construct (R1). MUST NOT touch a session."""

       @abstractmethod
       def materialize(self, raw: Any) -> D:
           """Pure per-record storage→domain mapping (R3). Returns the declared Output type."""
   ```
5. Define `WriteQuery(ABC, Generic[P, R])`:
   ```python
   class WriteQuery(ABC, Generic[P, R]):
       Params: ClassVar[type[BaseModel]]
       name: ClassVar[str]
       backend: ClassVar[Backend]

       @abstractmethod
       def build(self, params: P) -> Any:
           """Pure, I/O-free construction of the write construct (R1)."""

       @abstractmethod
       def interpret_result(self, raw: Any) -> R:
           """Pure mapping of the driver's write result into the declared result type."""
   ```
6. `__init_subclass__` on both: raise `TypeError` at class-definition time if `Params`/`name`/
   `backend` (and `Output` for reads) are unset. Skip the check for the abstract bases themselves.

**Tests:**
- A `ReadQuery` subclass missing `Params` raises `TypeError` at definition time.
- A concrete subclass's `build(params)` runs with no executor/session and returns non-None.
- `materialize(fake_raw)` returns an instance of the declared `Output` type.
- `WriteQuery` has no `Output` attribute requirement (only `Params`/`name`/`backend`).

**Verification:** `from orthograph.catalogue.typed import ReadQuery, WriteQuery, Backend` works.
`mypy src/` passes. No import of any backend library in `typed.py`.

---

### T2: `Executor` ABC + `ReadPort`

**What:** The `Executor` ABC (per-backend session seam; read ≠ write) and the `ReadPort`
swappable-read abstraction. Still no concrete backend.

**Actions:**
1. In `typed.py`, define `Executor(ABC)`:
   ```python
   class Executor(ABC):
       """The only place a connection/session is touched. read() and write() are DISTINCT
       methods (not a kind flag). Implementations MUST NOT store a connection as instance
       state — a factory is passed at construction (orthograph Constraint 13).

       Example:
           executor = SqlExecutor(lambda: Session(engine))   # factory, not a live session
       """
       @abstractmethod
       def read(self, query: ReadQuery[P, D], raw_params: Any) -> list[D]:
           """Validate params (R4) → build() (R1, pure) → open session → execute →
           materialize each record (R3). Commits NOTHING."""

       @abstractmethod
       def write(self, query: WriteQuery[P, R], raw_params: Any) -> R:
           """Validate params → build() → open session → execute → commit →
           interpret_result(). Commits (distinct transactional intent from read)."""
   ```
2. Define `ReadPort(ABC, Generic[P, D])` and `QueryBackedReadPort`:
   ```python
   class ReadPort(ABC, Generic[P, D]):
       """A named read capability with a store-neutral signature. Consuming code depends on a
       ReadPort subclass, never on a specific ReadQuery or Executor. The composition root binds
       the port to a concrete query + executor, making the read store swappable at ONE point
       without touching callers."""
       @abstractmethod
       def fetch(self, params: P) -> list[D]: ...

   class QueryBackedReadPort(ReadPort[P, D]):
       def __init__(self, query: ReadQuery[P, D], executor: Executor) -> None:
           self._query, self._executor = query, executor
       def fetch(self, params: P) -> list[D]:
           return self._executor.read(self._query, params)
   ```

**Tests:**
- `Executor` cannot be instantiated (abstract).
- Two `QueryBackedReadPort`s with different query+executor but the same `Output` type both satisfy
  the same `ReadPort[P, D]` annotation (static + runtime).
- `fetch()` delegates to `executor.read()`.

**Verification:** `from orthograph.catalogue.typed import Executor, ReadPort, QueryBackedReadPort`
works.

---

## STEP 2 — Cypher concrete backend

### T3: `CypherReadQuery` and `CypherWriteQuery`

**What:** The first concrete backend bases. `build()` returns `(cypher_str, params_dict)`;
`materialize()` maps a driver record dict to the declared `Output` NodeModel.

**Actions:**
1. Create `src/orthograph/extensions/cypher/typed_queries.py` (alongside `generator.py`,
   `parser.py` — does not replace them):
   ```python
   from orthograph.catalogue.typed import Backend, ReadQuery, WriteQuery

   class CypherReadQuery(ReadQuery[P, D], Generic[P, D]):
       """build() returns (cypher: str, params: dict).
       materialize() maps a graph record dict (keys like 's.sample_id') to Output NodeModel."""
       backend = Backend.CYPHER
       # subclasses implement build() and materialize()

   class CypherWriteQuery(WriteQuery[P, R], Generic[P, R]):
       backend = Backend.CYPHER
       # subclasses implement build() and interpret_result()
   ```
2. Tests (no driver — R1):
   - A concrete `CypherReadQuery.build()` returns a `(str, dict)` tuple; no driver needed.
   - `materialize()` with a hand-built fake record dict returns the declared `Output` NodeModel.
   - Two `CypherReadQuery`s with the same `Output` type have identical `Output.model_json_schema()`
     (port-swappability proof at the schema level).

**Verification:** `from orthograph.extensions.cypher import CypherReadQuery, CypherWriteQuery` works.

---

### T4: `CypherExecutor`

**What:** Concrete `Executor` for graph databases. The single graph-driver seam.

**Actions:**
1. Create `src/orthograph/extensions/cypher/executor.py`:
   ```python
   class CypherExecutor(Executor):
       """Single I/O seam for graph DBs. Accepts any driver whose session supports
       .run(cypher, **params) returning an iterable of records. Driver factory passed in
       (Constraint 13 — never owned).

       Example (neo4j): CypherExecutor(lambda: GraphDatabase.driver(URI).session())
       Example (test):  CypherExecutor(lambda: FakeGraphSession(records))
       """
       def __init__(self, driver_factory: Callable) -> None:
           self._driver_factory = driver_factory

       def read(self, query: CypherReadQuery[P, D], raw_params: Any) -> list[D]:
           params = query.Params.model_validate(raw_params)     # R4
           cypher, qparams = query.build(params)                # R1 — pure
           with self._driver_factory() as session:              # only I/O seam
               records = list(session.run(cypher, **qparams))
           return [query.materialize(dict(rec)) for rec in records]   # R3

       def write(self, query: CypherWriteQuery[P, R], raw_params: Any) -> R:
           params = query.Params.model_validate(raw_params)
           cypher, qparams = query.build(params)
           with self._driver_factory() as session:
               result = session.run(cypher, **qparams)
           return query.interpret_result(result)
   ```
2. Tests with a `FakeGraphSession` (test-internal; no live DB):
   - `read()` materialises fake records into the declared `Output` NodeModel instances.
   - Bad params raise (R4) before `run()` is called.
3. Live tests behind `--neo4j` / `--memgraph` flags.

**Verification:** `from orthograph.extensions.cypher import CypherExecutor` works.

---

## STEP 3 — Catalogue + introspection

### T5: `QueryCatalogue` + `QueryDescription`

**What:** The typed object registry. Registers `ReadQuery`/`WriteQuery` instances; introspects them.

**Actions:**
1. Create `src/orthograph/catalogue/registry.py`:
   ```python
   @dataclass
   class QueryDescription:
       name: str
       kind: Literal["read", "write"]
       backend: Backend
       params_schema: dict[str, Any]         # Params.model_json_schema()
       output_schema: dict[str, Any] | None  # Output.model_json_schema(); None for writes

   @dataclass
   class QueryCatalogue:
       """Typed object registry. Register ReadQuery/WriteQuery instances; introspect via describe().
       Queries reference their Output model by direct import — NO string-key model lookup."""
       _reads: dict[str, ReadQuery] = field(default_factory=dict)
       _writes: dict[str, WriteQuery] = field(default_factory=dict)

       def register_read(self, q: ReadQuery[P, D]) -> ReadQuery[P, D]:
           # reject duplicate name
       def register_write(self, q: WriteQuery[P, R]) -> WriteQuery[P, R]:
           # reject duplicate name
       def describe(self) -> list[QueryDescription]: ...
       def names(self) -> list[str]: ...
   ```
2. Tests:
   - Register a read and a write; `describe()` returns both with correct `kind`/`backend`.
   - Duplicate name raises `ValueError`.
   - `output_schema` is `None` for writes, non-None for reads.
   - Two backends implementing the same logical read expose identical `output_schema`.

**Verification:** `from orthograph.catalogue.registry import QueryCatalogue, QueryDescription`
works.

---

### T6: Integration proof — same port, different executors

**What:** The end-to-end proof of the swappable-read claim. (Full cross-backend test needs E14's
`SqlExecutor`; until then, prove it with two different fake Cypher executors / record shapes.)

**Actions:**
1. `tests/catalogue/test_port_swap.py`:
   ```python
   def test_same_port_different_record_shapes_identical_output():
       """A ReadPort returns identical domain objects regardless of the raw record shape."""
       q = SamplesByProtocolCypher()   # one CypherReadQuery
       ex_a = CypherExecutor(lambda: FakeGraphSession(RECORDS_SHAPE_A))
       ex_b = CypherExecutor(lambda: FakeGraphSession(RECORDS_SHAPE_B))  # same data, diff keys
       port_a = QueryBackedReadPort(q, ex_a)
       port_b = QueryBackedReadPort(q, ex_b)
       assert port_a.fetch(P(protocol_id=1)) == port_b.fetch(P(protocol_id=1))
   ```
2. When E14 lands, extend this to a true SQL-vs-Cypher swap test (cross-reference E14).

---

## STEP 4 — Public API

### T7: `catalogue/__init__.py` + notebook

**Actions:**
1. `src/orthograph/catalogue/__init__.py` exports:
   `ReadQuery`, `WriteQuery`, `Executor`, `ReadPort`, `QueryBackedReadPort`, `Backend`,
   `QueryCatalogue`, `QueryDescription`.
2. Module docstring: state plainly that this is the **typed query catalogue**; queries are Python
   classes; the return type is statically known; no string-key dispatch; no YAML (see the epic's
   OPEN DECISION).
3. Notebook `04.01_typed_query_catalogue.ipynb`: define a NodeModel → a CypherReadQuery → register
   in QueryCatalogue → describe() → run against a FakeGraphSession → swap behind a ReadPort.

**Verification:** `from orthograph.catalogue import ReadQuery, QueryCatalogue, ReadPort` works.

---

## OPEN DECISION: YAML — still open, scoping moved to dedicated epic

> **Status (2026-06-10):** This decision remains open. It was briefly marked closed as option A
> but that was premature — other projects in the organisation build parameterised Cypher queries
> from YAML files, so real consumers exist. The decision requires a dedicated scoping session
> with the team.
>
> **Action:** A dedicated epic (E19) has been created to scope the YAML query authoring question
> against the real consumer requirements. **Do not build any YAML support until E19 produces a
> decision and records it in an ADR.**

The retired E6 offered a **YAML-configured, string-key Cypher catalogue**
(`catalogue.execute("name", params, conn)`, queries loaded from a `.yaml` file). It is
deliberately **excluded** from STEPs 1–4. Resolve this AFTER the typed core exists and is felt.

### The conflict YAML creates with the typed architecture
1. **YAML cannot carry `materialize()`.** A YAML query is `(name, cypher, params, returns)` — a
   data structure. The typed contract's value is that `materialize()` is type-checked Python that
   produces a declared `Output`. A YAML query has no such method.
2. **Two registration models reappear.** A YAML/string-key catalogue is a *different class* with a
   *different call surface* (`execute("name", ...)` vs `executor.read(query, params)`). That is the
   exact Tension 1 we just resolved by choosing the typed model. Re-adding YAML re-opens it.
3. **Loss of static typing at the call site** — `execute("samples", ...)` returns untyped records;
   the type checker cannot know it is `list[Sample]`. This is the core property the typed track
   protects (and the reason the original brief rejected string-key lookups).

### The three options to choose between (later)
- **(A) Drop YAML entirely.** Queries are always Python classes. Simplest; preserves the typed
  architecture fully. Cost: no external/config-driven query authoring; ops/analysts must write
  Python. Pilot A (hardcoded Cypher, no schema) would adopt classes instead of YAML.
- **(B) YAML as a constrained, auto-materialising subset.** YAML may declare ONLY queries whose
  `returns` is a NodeModel; the catalogue auto-materialises via `NodeModel(**fields)` by
  convention. No custom `materialize()` allowed from YAML. Keeps YAML but boxes it so it cannot
  express the projection/transform queries the typed track handles. Two catalogue types coexist;
  both expose `describe()`.
- **(C) YAML as a code-generator, not a runtime model.** A YAML file *generates* `CypherReadQuery`
  Python classes (codegen at build time). Runtime stays 100% typed; YAML is just an authoring
  convenience that disappears after generation. No second runtime catalogue; preserves typing.
  Cost: a generation step and the round-trip questions that come with codegen.

### Decision criteria
Choose the option that (1) does not reintroduce string-key dispatch into application code,
(2) keeps `materialize()` type-checked, and (3) is justified by a real consumer who genuinely
needs config-driven queries. If no such consumer exists, prefer (A).

**Record the decision** in this section and in `idea_db/query-catalog-spike/docs/` before building
any YAML support.

---

## Relationship to Other Epics

- **E8 (GQLAlchemy)** — unblocked by this epic; its catalogue should also expose `describe()`
  (a `QueryDescription` surface) for uniform introspection.
- **E11 (CRUD)** — generates typed `CypherReadQuery`/`CypherWriteQuery` instances (Python classes),
  registered into a `QueryCatalogue`. (If YAML option C is later chosen, CRUD could also emit
  YAML — but not until the YAML decision is made.)
- **E14 (SQLAlchemy backend)** — implements `ReadQuery`/`WriteQuery`/`Executor` from STEP 1 for
  SQLAlchemy; completes the cross-backend port-swap proof in T6.
- **matterforge E9/E10** — import `ReadQuery`, `WriteQuery`, `QueryCatalogue`, `ReadPort`,
  `CypherReadQuery`, `CypherExecutor` from here once landed.
- **E6, E12, E13, E15** — retired; superseded by this epic.
