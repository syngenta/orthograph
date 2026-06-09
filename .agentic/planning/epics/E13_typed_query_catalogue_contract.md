# Epic E13: Typed Query Catalogue Contract

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Define the abstract, statically-typed `ReadQuery`/`WriteQuery`/`QueryCatalogue`/
> `Executor`/`ReadPort` contract that all backends (Cypher, GQLAlchemy, SQLAlchemy) implement,
> giving matterforge and mp-backend a single, navigable, IDE-friendly import point.
> **Blocked by:** None — can start immediately
> **Unblocks:** E14, E15, and the typed layer of E8/E11

---

## Context

The current E6 Cypher catalogue and E8 GQLAlchemy catalogue both use a **string-key dispatch**
model (`catalogue.execute("query_name", params, connection=conn)`). That model is correct for its
use case (named-string Cypher queries), but it cannot serve the typed contract needed by
matterforge: where `ReadQuery[P, D]` declares its `Params` *type* and its domain *output type*
statically, `go-to-definition` works on both, and the type checker flags a wrong materialise
return type.

E12 planned to extract a shared ABC *after* E6 + E8 exist. This epic instead defines the typed
contract *first* as a separate module (`catalogue/typed.py`), so that E14 (SQLAlchemy) and E15
(Cypher typed layer) plug in from day one, and E12 can later unify the string-key and typed
interfaces under one roof. **E13 does not replace E6 or E12 — it adds a typed layer alongside
them.**

**Reference implementation:** `query-catalog-spike/pocs/p01_query_catalogue/catalogue.py` and
the matterforge slice `pocs/p02_matterforge_slice/orthograph_ext/catalogue.py`. These are the
source of truth for the interface shape.

---

## Tasks

### E13.1: Define `ReadQuery[P, D]` and `WriteQuery[P, R]` base classes

**What:** Abstract generic base classes that enforce the typed, pure-build, per-record-materialise
contract. These live in `src/orthograph/catalogue/typed.py`.

**Actions:**
1. Create `src/orthograph/catalogue/typed.py`.
2. Define type variables: `P = TypeVar("P", bound=BaseModel)`, `D = TypeVar("D", bound=BaseModel)`,
   `R = TypeVar("R")`.
3. Define `ReadQuery(ABC, Generic[P, D])` with:
   ```python
   Params: ClassVar[type[P]]
   Output: ClassVar[type[D]]   # a NodeModel or projection BaseModel; direct type reference (no string)
   name: ClassVar[str]
   backend: ClassVar[Backend]  # descriptive tag only; see E13.3

   @abstractmethod
   def build(self, params: P) -> Any:
       """Pure, I/O-free construction of the backend construct (R1). No session."""

   @abstractmethod
   def materialize(self, raw: Any) -> D:
       """Pure per-record storage→domain mapping (R3). Returns the declared Output type."""
   ```
4. Define `WriteQuery(ABC, Generic[P, R])` with:
   ```python
   Params: ClassVar[type[P]]
   name: ClassVar[str]
   backend: ClassVar[Backend]

   @abstractmethod
   def build(self, params: P) -> Any:
       """Pure, I/O-free construction of the write construct (R1)."""

   @abstractmethod
   def interpret_result(self, raw: Any) -> R:
       """Pure mapping of the driver's write result into the declared result type."""
   ```
5. `__init_subclass__` validation: enforce that `Params`, `Output`/result, `name`, `backend` are
   set on each concrete class; raise `TypeError` with a clear message if not.
6. Write tests:
   - Subclass without `Params` raises `TypeError` at class definition time.
   - `build()` can be called with no executor/session; returns a non-None construct.
   - `materialize()` called with a fake row returns the declared `Output` type.

**Verification:** `from orthograph.catalogue.typed import ReadQuery, WriteQuery` works.
`mypy src/` passes.

---

### E13.2: Define `Executor` ABC and `QueryCatalogue`

**What:** The `Executor` ABC (per-backend session seam) and the `QueryCatalogue` registry
(register + introspect). Read and write are distinct methods on the executor; they are NOT a flag.

**Actions:**
1. In `typed.py`, define `Executor(ABC, Generic[P, D, R])` with:
   ```python
   @abstractmethod
   def read(self, query: ReadQuery[P, D], raw_params: Any) -> list[D]:
       """Opens connection, validates params (R4), calls build(), materialises. Commits NOTHING."""

   @abstractmethod
   def write(self, query: WriteQuery[P, R], raw_params: Any) -> R:
       """Opens connection, validates params, calls build(), commits. Returns interpret_result()."""
   ```
   **Constraint:** implementations MUST NOT store the connection as instance state — connections
   are passed via a factory (consistent with orthograph Constraint 13). Document this in the
   docstring with a code example of the session-factory pattern.

2. Define `QueryDescription` dataclass:
   ```python
   @dataclass
   class QueryDescription:
       name: str
       kind: Literal["read", "write"]
       backend: Backend
       params_schema: dict[str, Any]     # from Params.model_json_schema()
       output_schema: dict[str, Any] | None  # None for writes
   ```

3. Define `QueryCatalogue` dataclass with:
   - `register_read(query: ReadQuery[P, D]) -> ReadQuery[P, D]` — rejects duplicates.
   - `register_write(query: WriteQuery[P, R]) -> WriteQuery[P, R]` — rejects duplicates.
   - `describe() -> list[QueryDescription]` — derives Params + Output JSON Schema from the
     declared types. Spans all backends — the `backend` tag on each description identifies
     which store each query targets.
   - `names() -> list[str]`.

4. Write tests:
   - Register a read and a write; `describe()` returns both with correct `kind` and `backend`.
   - Duplicate name raises `ValueError`.
   - `output_schema` is `None` for writes, non-None for reads.
   - Two backends implementing the same logical read expose **identical** `output_schema`
     (this proves port-swappability at the schema level).

**Verification:** `from orthograph.catalogue.typed import QueryCatalogue, Executor` works.

---

### E13.3: Define `Backend` enum and `ReadPort`

**What:** The `Backend` descriptive tag (description-level only — NOT a behavioural switch) and
the `ReadPort` swappable-read abstraction (the seam that lets the read store be deferred).

**Actions:**
1. In `typed.py`, define:
   ```python
   class Backend(str, Enum):
       """Description-level tag on each registered query. NOT a runtime dispatch switch.
       Execution is always through a specific Executor subclass, never via this enum."""
       SQLALCHEMY = "sqlalchemy"
       CYPHER = "cypher"
       GQLALCHEMY = "gqlalchemy"
   ```

2. Define `ReadPort(ABC, Generic[P, D])`:
   ```python
   class ReadPort(ABC, Generic[P, D]):
       """A named read capability with a store-neutral signature.

       Consuming applications (e.g. FastAPI endpoints) depend on a ReadPort subclass,
       never on a specific ReadQuery or Executor. The composition root (application entry
       point) binds the port to a concrete query + executor, making the read store
       swappable at that single point without touching endpoints or repositories.

       Example:
           class SamplesByProtocol(ReadPort[SamplesByProtocolParams, Sample]):
               pass  # the port is the name; the composition root supplies the implementation

           # SQL binding:
           port = QueryBackedReadPort(SqlSamplesByProtocol(), sql_executor)
           # Graph binding (same port, different query+executor):
           port = QueryBackedReadPort(GraphSamplesByProtocol(), graph_executor)
       """
       @abstractmethod
       def fetch(self, params: P) -> list[D]: ...
   ```

3. Define `QueryBackedReadPort(ReadPort[P, D])` — the default adapter:
   ```python
   class QueryBackedReadPort(ReadPort[P, D]):
       def __init__(self, query: ReadQuery[P, D], executor: Executor) -> None: ...
       def fetch(self, params: P) -> list[D]:
           return self._executor.read(self._query, params)
   ```

4. Write tests:
   - Two `QueryBackedReadPort`s with different query+executor implementations but the same domain
     `Output` type both satisfy the same `ReadPort[P, D]` type annotation (static check).
   - `fetch()` delegates to the executor's `read()` method.
   - Swapping the port implementation changes the raw record source but NOT the returned domain
     type — verify with a test that asserts identical output from two different fake executors.

**Verification:** `from orthograph.catalogue.typed import ReadPort, QueryBackedReadPort` works.

---

### E13.4: Export via `orthograph.catalogue` public API

**What:** Make the typed contract importable via the catalogue package alongside the existing
string-key catalogue classes.

**Actions:**
1. Update `src/orthograph/catalogue/__init__.py` to export:
   `ReadQuery`, `WriteQuery`, `Executor`, `QueryCatalogue`, `QueryDescription`,
   `Backend`, `ReadPort`, `QueryBackedReadPort`.
2. Add docstring to `__init__.py` explaining the two-tier catalogue:
   - String-key tier (E6 `CypherQueryCatalogue`, E8 `GqlAlchemyQueryCatalogue`): named Cypher/ORM
     queries executed by name; suitable for YAML-configured, schema-validated named queries.
   - Typed tier (this epic): `ReadQuery[P,D]`/`WriteQuery[P,R]` with static output types,
     per-record materialise, and swappable `ReadPort`; suitable for typed domain-object-returning
     queries in matterforge/mp-backend.
3. No behavioural change to existing E6/E8 classes.

**Verification:** `from orthograph.catalogue import ReadQuery, WriteQuery, QueryCatalogue, ReadPort`
imports without errors. Existing `CypherQueryCatalogue` imports still work.

---

## Relationship to Other Epics

- **E6/E8** — string-key catalogues are unaffected; E13 adds a typed layer alongside them.
- **E12** — E12 planned to extract a shared ABC after E6+E8. Now that E13 defines the typed
  contract first, E12 should be revised: it can unify the string-key and typed tiers, or simply
  acknowledge E13 as the typed contract and limit E12 to the string-key tier. **Recommended:**
  update E12 scope to "extract/align the string-key ABC; typed contract is E13."
- **E14 (SQLAlchemy extension)** — blocked by this epic; `SqlReadQuery`/`SqlExecutor` subclass E13's ABCs.
- **E15 (Typed Cypher backend)** — blocked by this epic; `CypherReadQuery`/`CypherExecutor` extend E13.
- **matterforge** — will import `ReadQuery`, `WriteQuery`, `QueryCatalogue`, `ReadPort` from here
  once this epic lands (replacing the vendored `orthograph_ext/catalogue.py` in the PoC).
