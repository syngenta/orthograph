# Epic E31: Query Contract Ergonomics — Implementation

> **Priority:** High (blocker for public release)
> **Origin:** E30 decision session 2026-06-16
> **Goal:** Implement all decisions from E30. Each task is independently executable.
> **Blocked by:** E30 (complete)
> **Blocks:** Public API stabilisation, notebook `05.01_openapi_ergonomics_assessment.ipynb`

---

## Task Index

| ID | Title | Group | ADR |
|----|-------|-------|-----|
| T1 | Rename `materialize` → `interpret_result` on `WriteQuery`/`CypherWriteQuery` | A | ADR-020 |
| T2 | Introduce `WriteResultSummary` protocol in `orthograph.query` | A | ADR-021 |
| T3 | Add optional `Output` ClassVar to `WriteQuery`; update `QueryCatalogue.describe()` | B | — |
| T4 | Add `output_class` field to `QueryDescription` | B | — |
| T5 | Add INFO-level RETURN→Output column alignment check to `validate_query_catalogue` | C | — |
| T6 | Auto-populate `Params`/`Output` from generic args in `__init_subclass__` | D | ADR-022 |
| T7 | Re-export `NoParams`/`NoIdentifiers` from `orthograph.cypher.__init__` | D | — |
| T8 | Add `PaginatedParams` mixin to `orthograph.query` | E | — |
| T9 | Improve `Identifiers`/`<<name>>` docstrings in `CypherReadQuery`/`CypherWriteQuery` | F | — |
| T10 | Add `QUERY_USES_IDENTIFIER_INJECTION` INFO issue to `validate_query_catalogue` | F | — |
| T11 | Create notebook `05.01_openapi_ergonomics_assessment.ipynb` | F | ADR-024 |
| T12 | Update notebook `04.01` to remove redundant `Params =`/`Output =` lines and align prose with `interpret_result` | A/D | — |
| T13 | Document bulk-write convention and deferred `BulkWriteQuery` in Getting Started | E | ADR-023 |

---

## Tasks

---

### T1 — Rename `materialize` → `interpret_result` on `WriteQuery`/`CypherWriteQuery`

**Decision:** ADR-020
**Scope:** 6 source files + test files

**Files to change:**

| File | Line(s) | Change |
|------|---------|--------|
| `src/orthograph/query/base_models.py` | ~159 | Rename abstract method `WriteQuery.materialize` → `interpret_result`; update docstring to say "interprets a mutation summary, not a row" |
| `src/orthograph/cypher/base_models.py` | ~203 | Rename abstract method `CypherWriteQuery.materialize` → `interpret_result` |
| `src/orthograph/cypher/query_execution.py` | ~71 | Update call site: `query.materialize(result)` → `query.interpret_result(result)` |
| `tests/cypher/test_base_models.py` | ~95, ~173 | Rename `CreateMovieCypher.materialize` → `interpret_result`; rename `test_write_materialize` → `test_write_interpret_result` |
| `tests/query/test_base_models.py` | ~207, ~254 | Rename `ConcreteWrite.materialize` → `interpret_result`; rename `test_write_query_materialize` → `test_write_query_interpret_result` |
| `notebooks/04.01_typed_cypher_queries.ipynb` | section 3 | Update prose + write query example cell (covered by T12) |

**Acceptance criteria:**
- `grep -r "def materialize" src/` returns only `ReadQuery.materialize` and `CypherReadQuery.materialize` — no write-side hits.
- All existing tests pass.
- New test: `test_write_interpret_result_is_abstract` — confirm `WriteQuery` raises `TypeError` if `interpret_result` is not implemented.

---

### T2 — Introduce `WriteResultSummary` protocol in `orthograph.query`

**Decision:** ADR-021
**Scope:** 1 new file + 2 modified files

**Status:** ✅ Complete

⚠️ **Note on acceptance criterion:** The epic's acceptance criterion `from orthograph.query import WriteResultSummary` conflicts with the project's architecture invariant (`test_no_reexports_in_init_files`). The protocol is importable from `orthograph.query.write_result` instead. See T7 blocker for resolution path.

**New file:** `src/orthograph/query/write_result.py`

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class WriteResultSummary(Protocol):
    """Vendor-free contract for the result of a write operation.

    Both the real neo4j driver result (via CypherWriteResultSummary) and
    test doubles must satisfy this protocol.
    """
    @property
    def nodes_created(self) -> int: ...
    @property
    def nodes_deleted(self) -> int: ...
    @property
    def relationships_created(self) -> int: ...
    @property
    def relationships_deleted(self) -> int: ...
    @property
    def properties_set(self) -> int: ...
```

**Modified files:**

| File | Change |
|------|--------|
| `src/orthograph/query/base_models.py` | Update `WriteQuery.interpret_result` docstring to reference `WriteResultSummary`; do NOT change the `raw: Any` signature — the protocol is a documentation/type-hint aid, not a hard constraint at the abstract layer |
| `src/orthograph/cypher/query_execution.py` | Add `CypherWriteResultSummary` dataclass that wraps `neo4j.Result.counters` and satisfies `WriteResultSummary`; pass it instead of the raw result to `query.interpret_result()` |

**Acceptance criteria:**
- `isinstance(CypherWriteResultSummary(...), WriteResultSummary)` passes (`runtime_checkable`).
- Existing write query tests pass with the wrapped summary.
- New test: `test_write_result_summary_protocol_satisfied_by_cypher_impl` — confirm `CypherWriteResultSummary` satisfies `WriteResultSummary`.
- New test: `test_write_result_summary_satisfied_by_simple_dataclass` — confirm a plain dataclass with the right fields satisfies the protocol (unit-testability guarantee).

---

### T3 — Add optional `Output` ClassVar to `WriteQuery`; update `QueryCatalogue.describe()`

**Scope:** 3 files

| File | Line(s) | Change |
|------|---------|--------|
| `src/orthograph/query/base_models.py` | `WriteQuery` class | Add `Output: ClassVar[type[BaseModel] \| None] = None`; update `__init_subclass__` to skip `Output` from the required-attrs enforcement (it remains optional) |
| `src/orthograph/query/catalogue.py` | ~119 | Change `output_schema=None` to `output_schema=q.Output.model_json_schema() if q.Output is not None else None` |
| `tests/query/test_base_models.py` | ~243 | Update `test_write_query_has_no_output_attribute` — the attribute now exists but defaults to `None`; rename and update the assertion accordingly |

**Acceptance criteria:**
- A `WriteQuery` subclass with `Output = SomeModel` has `describe()` emit its JSON schema.
- A `WriteQuery` subclass without `Output` still has `output_schema=None` in `describe()`.
- All existing tests pass.

---

### T4 — Add `output_class` field to `QueryDescription`

**Scope:** 1 file

| File | Line(s) | Change |
|------|---------|--------|
| `src/orthograph/query/catalogue.py` | `QueryDescription` dataclass, `describe()` | Add `output_class: type[BaseModel] \| None` field; populate from `q.Output` for reads and writes that declare it |

**Acceptance criteria:**
- `QueryDescription.output_class` is the actual class (not the JSON schema dict) for queries with `Output` set.
- `QueryDescription.output_class` is `None` for writes without `Output`.
- Existing `output_schema` field is unchanged.

---

### T5 — Add INFO-level RETURN→Output column alignment check

**Scope:** `src/orthograph/cypher/parser.py` + `src/orthograph/cypher/validation.py` + tests

**What to implement:**
- New method `GraphglotParser._extract_return_columns(lg) -> set[str]` — extracts simple `m.prop` and `m.prop AS alias` patterns from the RETURN clause. Returns the set of projected column names. Returns `None` (skip check) if `RETURN *` or any aggregation function is detected.
- New function `_check_return_output_alignment(return_cols, output_model) -> list[Issue]` in `validation.py` — compares extracted columns against `Output.model_fields.keys()`; emits `QUERY_RETURN_OUTPUT_MISMATCH` INFO issues for mismatches.
- Wire into `validate_query_catalogue` — run the check for all `ReadQuery` instances that have both a `cypher_template` and an `Output` model.

**Issue code to add:** `QUERY_RETURN_OUTPUT_MISMATCH` (INFO severity)

**Acceptance criteria:**
- A query with `RETURN m.title AS title` and `Output` fields `{title, released}` emits one `QUERY_RETURN_OUTPUT_MISMATCH` INFO issue for `released`.
- A query with `RETURN *` emits no issue (skip).
- A query with `count(m)` aggregation emits no issue (skip).
- All existing `validate_query_catalogue` tests pass.

---

### T6 — Auto-populate `Params`/`Output` from generic args in `__init_subclass__`

**Decision:** ADR-022
**Scope:** `src/orthograph/query/base_models.py` + `src/orthograph/cypher/base_models.py` + all test fixtures

**What to implement in `ReadQuery.__init_subclass__`:**
```python
# After super().__init_subclass__():
# 1. If class is abstract, return early (existing guard).
# 2. Try to extract (P, D) from cls.__orig_bases__ using typing.get_args.
# 3. If extracted and Params not in cls.__dict__, set cls.Params = P.
# 4. If extracted and Output not in cls.__dict__, set cls.Output = D.
# 5. If extracted and Params IS in cls.__dict__ and cls.Params != P, raise TypeError.
# 6. If extracted and Output IS in cls.__dict__ and cls.Output != D, raise TypeError.
# 7. Proceed to _enforce_query_contract as before.
```

Apply the same logic to `WriteQuery.__init_subclass__` for `Params` only.
Apply the same logic to `CypherReadQuery.__init_subclass__` and `CypherWriteQuery.__init_subclass__`.

**Files to change:**
- `src/orthograph/query/base_models.py` — `ReadQuery.__init_subclass__`, `WriteQuery.__init_subclass__`
- `src/orthograph/cypher/base_models.py` — `CypherReadQuery.__init_subclass__`, `CypherWriteQuery.__init_subclass__`
- `tests/query/test_base_models.py` — add tests for auto-population; remove redundant `Params =`/`Output =` from existing test fixtures
- `tests/cypher/test_base_models.py` — same
- All other test files with query fixtures — remove redundant `Params =`/`Output =` lines

**Acceptance criteria:**
- A subclass with only `CypherReadQuery[MoviesByYearParams, Movie]` in the signature (no ClassVar assignments) has `cls.Params is MoviesByYearParams` and `cls.Output is Movie` at class-definition time.
- A subclass that explicitly declares `Params = WrongType` while inheriting `CypherReadQuery[RightType, Movie]` raises `TypeError` at class-definition time.
- `MemgraphCardinalityQuery(InspectCardinalityQuery)` (inherits ClassVars, no generic re-declaration) continues to work.
- All existing tests pass after removing redundant ClassVar assignments.

---

### T7 — Import `NoParams`/`NoIdentifiers` directly from `orthograph.cypher.bindings`

**Status:** ✅ DECISION: Keep architecture invariant; import directly from submodules

The project enforces an invariant (`test_architecture.py::test_no_reexports_in_init_files`) that forbids **all** `import` or `from … import` statements in any `__init__.py` under `src/orthograph/` (except the top-level `__init__.py`'s single allowed `import importlib.metadata`).

**Decision:** Keep the invariant. Do not re-export from `orthograph.cypher.__init__`. Users will import directly:
```python
# Instead of: from orthograph.cypher import NoParams
from orthograph.cypher.bindings import NoParams, NoIdentifiers
```

**Rationale:** The invariant ensures clean package boundaries and makes implicit dependencies explicit. If better ergonomics are needed in the future, re-exports will be added **only at the API level** (`src/orthograph/api/`) after further architectural review.

**Update documentation** to reflect this import path in:
- Class docstrings for `NoParams` and `NoIdentifiers` in `src/orthograph/cypher/bindings.py`
- Any Getting Started or usage guides that reference these types

---

### T8 — Add `PaginatedParams` mixin to `orthograph.query`

**Scope:** 1 new file + 1 modified file

**New file:** `src/orthograph/query/pagination.py`

```python
from pydantic import BaseModel, Field

class PaginatedParams(BaseModel):
    """Mixin for read query params that support skip/limit pagination.

    Compose into a Params model:
        class MoviesByYearParams(PaginatedParams):
            released: int
    """
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)
```

**Modified file:** `src/orthograph/query/pagination.py` — No re-export from `__init__.py` per T7 decision. Users will import directly:
```python
from orthograph.query.pagination import PaginatedParams
```

**Acceptance criteria:**
- A `Params` model that inherits `PaginatedParams` passes `__init_subclass__` enforcement.
- `PaginatedParams` fields appear in `params_schema` from `QueryCatalogue.describe()`.
- New test: `test_paginated_params_composes_into_query_params`.

---

### T9 — Improve `Identifiers`/`<<name>>` docstrings

**Scope:** `src/orthograph/cypher/base_models.py`

**What to add to `CypherReadQuery` and `CypherWriteQuery` docstrings:**
- An explicit "Optional class variables" section listing `Identifiers` alongside `cypher_template`.
- A sentence explaining that `<<name>>` placeholders in the template are substituted with safe, validated identifier values before execution — they are not Cypher syntax.
- A minimal example showing `Identifiers` usage.

**Acceptance criteria:**
- `help(CypherReadQuery)` output mentions `Identifiers` and `<<name>>` in the class docstring.

---

### T10 — Add `QUERY_USES_IDENTIFIER_INJECTION` INFO issue to `validate_query_catalogue`

**Scope:** `src/orthograph/cypher/validation.py` + tests

**What to implement:**
- For each query in the catalogue with a `cypher_template` containing at least one `<<name>>` placeholder, emit one `QUERY_USES_IDENTIFIER_INJECTION` INFO issue.
- Issue message: `"Query '{name}' uses identifier injection (<<...>> placeholders). Ensure Identifiers model is declared and all slots are filled at construction time."`

**Acceptance criteria:**
- `validate_query_catalogue` on a catalogue containing `InspectCardinalityQuery` (which uses `<<label>>`) emits at least one `QUERY_USES_IDENTIFIER_INJECTION` INFO issue.
- Queries without `<<...>>` placeholders emit no such issue.

---

### T11 — Create notebook `05.01_openapi_ergonomics_assessment.ipynb`

**Decision:** ADR-024
**Scope:** New notebook

**Sections to cover (illustrative cells — no live server required):**

1. **Setup** — imports, a toy `GraphDefinition` with one `NodeModel`, one `ReadQuery`, one `WriteQuery` with `Output`.
2. **GET endpoint** — wiring `ReadQuery` to a FastAPI route with `response_model=query.Output`; show how `QueryDescription.output_class` provides the class reference.
3. **POST endpoint** — wiring `WriteQuery` with `Output` to a `POST` route; show `output_class` usage.
4. **DI pattern** — `ReadPort.fetch` as a `Depends()` dependency; show the lambda and typed annotation pattern.
5. **Pagination** — composing `PaginatedParams` into a request model; show `skip`/`limit` in the route signature.
6. **Limitations and future work** — no pagination response envelope in v0.1.0; `BulkWriteQuery` deferred; runnable vertical slice deferred to a future notebook.

**Acceptance criteria:**
- Notebook renders without errors in `nbconvert --execute` dry-run (cells are illustrative but must be syntactically valid Python).
- All four wiring patterns are present.
- A "Future work" section explicitly references deferred items.

---

### T12 — Update notebook `04.01` to align with E31 changes

**Scope:** `notebooks/04.01_typed_cypher_queries.ipynb`

**Changes:**
- Section 3 prose: replace all references to `interpret_result()` that are inconsistent with the renamed method (or were inconsistent with `materialize`) — ensure prose and code cells agree on `interpret_result`.
- All query example cells: remove redundant `Params = ...` / `Output = ...` ClassVar lines (after T6 lands).
- Write query example cell: update to use `interpret_result` and show the `WriteResultSummary` protocol.

**Acceptance criteria:**
- `grep "materialize" notebooks/04.01*` returns zero hits in code cells.
- No code cell in the notebook contains a standalone `Params = ...` or `Output = ...` ClassVar assignment.

---

### T13 — Document bulk-write convention and deferred `BulkWriteQuery`

**Decision:** ADR-023
**Scope:** Getting Started guide or notebook `04.01` section

**What to write:**
- "`WriteQuery` executes a single Cypher statement per call. There is no built-in bulk-write pattern in v0.1.0."
- The documented convention: declare `items: list[dict]` on `Params` and use `UNWIND $items AS item` in the template.
- Explicit note: "A `BulkWriteQuery` base class is planned for a future release. Until then, teams using the UNWIND convention are responsible for their own transaction semantics."

**Acceptance criteria:**
- The documented convention is present in at least one notebook or Getting Started guide section.
- The deferred `BulkWriteQuery` is mentioned by name with a forward reference.

---

## Execution Order

Tasks with no dependencies can run in parallel. Suggested order:

1. **T1** (rename) — unblocks T2, T12
2. **T2** (protocol) — depends on T1
3. **T6** (auto-populate) — unblocks T12; can run in parallel with T1
4. **T3, T4** (WriteQuery Output + QueryDescription) — can run in parallel with T1/T6
5. **T7, T8, T9, T10, T13** — independent; run in parallel after T6
6. **T5** (RETURN alignment check) — independent
7. **T11** (notebook 05.01) — depends on T3, T4, T8 being complete
8. **T12** (update notebook 04.01) — depends on T1, T6

---

## Acceptance Criteria for E31

- [x] T2 complete: `from orthograph.query.write_result import WriteResultSummary` works
- [x] T7 decision made: Keep invariant, users import from `orthograph.cypher.bindings` directly
- [x] T8 decision made: No re-export from `orthograph.query.__init__`; users import from `orthograph.query.pagination` directly
- [ ] All remaining tasks (T1, T3–T6, T9–T13) completed with passing tests
- [ ] `grep -r "def materialize" src/` returns only read-side hits
- [ ] `WriteResultSummary` protocol is testable without a live driver
- [ ] `QueryDescription` has both `output_schema` and `output_class` fields
- [ ] `validate_query_catalogue` emits `QUERY_RETURN_OUTPUT_MISMATCH` and `QUERY_USES_IDENTIFIER_INJECTION` INFO issues where appropriate
- [ ] Notebooks `04.01` and `05.01` render without errors
- [ ] No redundant `Params =` / `Output =` ClassVar assignments remain in `src/` or `notebooks/`
- [ ] Documentation (docstrings, getting started guides) reflects import paths: `orthograph.cypher.bindings`, `orthograph.query.pagination`, `orthograph.query.write_result`
