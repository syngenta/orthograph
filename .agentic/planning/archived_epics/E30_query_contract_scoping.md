# Epic E30: Query Contract Scoping — Pre-Public-API Design Session

> **Priority:** High (blocker for public release)
> **Origin:** Ergonomics assessment 2026-06-16 — SE review of typed query DX before code goes public
> **Goal:** Hold a single structured scoping session to resolve all entangled design questions about the typed query contract. Output is one or more ADRs + a follow-on implementation epic (E31).
> **Blocked by:** None — independent
> **Blocks:** E31 (implementation), notebook `05.01_openapi_ergonomics_assessment.ipynb`, and any public API stabilisation

---

## Why This Epic Exists

E16 delivered the typed query contract (`ReadQuery`/`WriteQuery`/`CypherExecutor`/
`QueryCatalogue`). It is well-engineered and builds on a solid foundation. However, the
contract was designed primarily from the *implementor's* perspective. A hands-on
ergonomics review (2026-06-16, simulating a third-party team writing their first queries
and wiring them to an OpenAPI endpoint) surfaced **nine entangled design questions** that
cannot be resolved independently without risking inconsistencies.

These questions are last-chance: once the library ships with external consumers, the
`ReadQuery`/`WriteQuery` surface becomes a breaking-change boundary.

**Scope of this epic:** Decision-only. No production code is written here. The deliverable
is a set of ADRs recording the decisions and rationale, plus a follow-on epic (E31) with
concrete, agent-executable implementation tasks for whatever was decided.

---

## Session Agenda & Design Questions

All nine questions are ordered by entanglement — questions that constrain each other's
answers are grouped together.

---

### Group A: Method naming and raw-result contract (Q1 + Q2)

These two questions are tightly coupled. Decide together.

---

#### Q1 — Should `WriteQuery.materialize()` be renamed to `interpret_result()`?

**Problem:**
`ReadQuery.materialize(raw: dict) → D` maps one result-set row to a typed domain object.
`WriteQuery.materialize(raw: Any) → R` receives the driver's raw transaction result (a
`neo4j.Result` / `tx.run()` return value with `.counters`, `.summary()`, etc.) and
returns an untyped `R`.

The name `materialize` implies "turn a row into a model instance". For writes, there is
no row — there is a mutation summary. The semantic mismatch is a first-contact friction
point: developers writing their first write query expect `raw` to be a dict (as on reads)
and get confused by the opaque driver object.

**Location:** `src/orthograph/query/base_models.py` (line 159) and
`src/orthograph/cypher/base_models.py` (line 203).

**Concrete symptom:**
The existing notebook `04.01_typed_cypher_queries.ipynb` section 3 prose says
"Implement `interpret_result()` instead of `materialize()`" — but the actual abstract
method is `materialize()`. The documentation and the code already disagree.

**Options:**

| Option | What changes | Risk |
|--------|-------------|------|
| A — Rename `materialize` → `interpret_result` on `WriteQuery`/`CypherWriteQuery` | ~6 source files + test files | Breaking; v0.1.0 — acceptable |
| B — Keep `materialize`; add `interpret_result` as a non-abstract alias on `WriteQuery` | Additive | Confusing — two names for one method |
| C — Keep `materialize`; fix the notebook prose to match the code | Notebook only | Leaves the naming mismatch in production code |

**Recommended for discussion:** Option A. The v0.1.0 window is the right moment.

**Affected files (Option A):**
- `src/orthograph/query/base_models.py` — `WriteQuery.materialize` (line 159)
- `src/orthograph/cypher/base_models.py` — `CypherWriteQuery.materialize` (line 203)
- `src/orthograph/cypher/query_execution.py` — call site `query.materialize(result)` (line 71)
- `tests/cypher/test_base_models.py` — `CreateMovieCypher.materialize` (line 95), `test_write_materialize` (line 173)
- `tests/query/test_base_models.py` — `ConcreteWrite.materialize` (line 207), `test_write_query_materialize` (line 254)
- `notebooks/04.01_typed_cypher_queries.ipynb` — section 3 prose + write query example cell

**Cross-links:** Directly affects Q2 (the docstring for the renamed method must document
what `raw` is).

---

#### Q2 — What is the documented contract for `raw` in `WriteQuery.interpret_result()`?

**Problem:**
`CypherExecutor.write()` calls `query.materialize(result)` (line 71 of
`src/orthograph/cypher/query_execution.py`) where `result` is the return value of
`tx.run(cypher, **params)`. For the neo4j Python driver this is a `neo4j.Result` object;
for a test double it could be anything.

This creates two problems:
1. **Undocumented contract:** There is no docstring or type annotation explaining what
   `raw` is. Developers see `def materialize(self, raw: Any) -> R` with no guidance.
2. **Untestable without a driver:** `ReadQuery.materialize(raw: dict)` is trivially
   unit-testable with a hand-built dict. `WriteQuery.materialize(raw)` requires either
   the real driver or a carefully crafted fake that mimics `neo4j.Result`.

**Options:**

| Option | What changes |
|--------|-------------|
| A — Document only: add a precise docstring explaining `raw` is the driver's result handle, with `.counters` / `.summary()` examples | Docstring only |
| B — Introduce a `WriteResultSummary` protocol (duck-typed) with the minimal surface (`counters`, `summary`) that both the real driver and a test double can satisfy | New protocol class in `cypher/` |
| C — Change `CypherExecutor.write()` to extract counters before calling `interpret_result`, passing a structured dict instead of the raw driver object | Executor change; may lose access to full result |

**Recommended for discussion:** Option B (protocol) or at minimum Option A. Option C
changes the executor's behaviour and could break callers who already introspect the full
result object.

**Affected files (Option B):**
- `src/orthograph/cypher/query_execution.py` — add protocol or update docstring
- `src/orthograph/cypher/base_models.py` — update `CypherWriteQuery.materialize` signature / docstring
- New file: `src/orthograph/cypher/result_protocol.py` (if Option B chosen)

**Cross-links:** Affects the OpenAPI wiring story (Q8), since a structured write result
enables a machine-readable write response schema.

---

### Group B: Write response schema and Output ClassVar (Q3)

---

#### Q3 — Should `WriteQuery` have an optional `Output` ClassVar?

**Problem:**
`WriteQuery[P, R]` uses `R` as an unbound TypeVar — write results (row counts, generated
IDs, status strings) are not always Pydantic `BaseModel` subclasses, so no `Output`
ClassVar is declared.

`QueryCatalogue.describe()` returns `output_schema=None` for all writes
(`src/orthograph/query/catalogue.py` line 119).

For an OpenAPI write endpoint (e.g. `POST /samples` that returns the created `Sample`),
the team building the endpoint must:
1. Define a separate response `BaseModel` (e.g. `SampleCreatedResponse`)
2. Keep it manually in sync with both the write query's `R` TypeVar and the domain
   `Sample` NodeModel

This is exactly the kind of schema drift orthograph is meant to prevent — but it is
unaddressed for write endpoints.

**Options:**

| Option | Pros | Cons |
|--------|------|------|
| A — Add `Output: ClassVar[type[BaseModel] \| None] = None` to `WriteQuery`; `describe()` emits the schema when set | Closes the gap; additive (no break) | Optional means it can be ignored; still allows inconsistency |
| B — Make `R` bounded: `R = TypeVar("R", bound=BaseModel)` | Forces Pydantic output on all writes | Breaks `WriteQuery[P, int]` (row count) — too restrictive |
| C — Leave as-is; document the gap; recommend using `ReadQuery` for writes that need to return domain data | No code change | Does not address the architectural gap |
| D — Introduce a `WriteQueryWithOutput[P, D, R]` subclass for writes that produce typed domain output | Clean separation | More class hierarchy; third parties must choose the right base |

**Recommended for discussion:** Option A or D. The session should decide if writes-that-
return-data are a first-class concept (D) or a decoration on the existing base (A).

**Affected files:**
- `src/orthograph/query/base_models.py` — `WriteQuery` class definition
- `src/orthograph/query/catalogue.py` — `QueryDescription.output_schema` and `describe()` (lines 109–120)
- `tests/query/test_base_models.py` — `test_write_query_has_no_output_attribute` (line 243) — this test would need updating

**Cross-links:** Affects Q8 (OpenAPI write endpoint wiring) and Q2 (if write result is
typed, the `interpret_result()` contract becomes clearer).

---

### Group C: Static query validation coverage (Q4)

---

#### Q4 — Should `validate_query_catalogue` check RETURN columns against `Output` fields?

**Problem:**
Definition-time validation and `validate_query_catalogue` check:
- Cypher syntax
- `$param` ↔ `Params` field 1:1 alignment
- `<<name>>` ↔ `Identifiers` field 1:1 alignment
- Node labels, relationship types, and property names against `GraphDefinition`

What they do **not** check:
- That the columns projected by `RETURN` actually match the keys that `materialize()`
  expects to find in `raw`

**Concrete failure mode:** A developer adds `released_year: int` to `Movie` (renaming
from `released`) and updates the `Output` model but forgets to update `RETURN`. The
query passes all definition-time validation and `validate_query_catalogue`, then raises
`KeyError: 'm.released_year'` at runtime on the first real call.

**Location for the fix:**
`src/orthograph/cypher/parser.py` — `GraphglotParser._extract_bindings()` produces
`variable_bindings`; the RETURN clause outputs are available via `lg.outputs` (used in
`_detect_intent`, line 162). An additional extraction pass could collect RETURN column
aliases and compare them to `Output.model_fields.keys()`.

**Complexity:**
Cypher RETURN can produce columns as:
- `m.title` → key `"m.title"` in the result dict
- `m.title AS title` → key `"title"`
- `{title: m.title, year: m.released}` → map literal
- `*` → all bound variables (unknowable statically)
- `count(m)`, `collect(m.title)` → aggregations with non-property-name keys

A full check is non-trivial and risks false positives. A partial check (simple
`m.prop` and `m.prop AS alias` patterns) covers ~90% of practical cases.

**Options:**

| Option | Scope | Severity |
|--------|-------|----------|
| A — Implement partial RETURN→Output column alignment as an INFO-level `QUERY_RETURN_OUTPUT_MISMATCH` issue | New logic in `parser.py` + tests | INFO (warning only — no false-positive ERRORs) |
| B — Implement as WARNING-level but only when `RETURN *` and aggregations are absent | More precise but complex | WARNING |
| C — Backlog only: document the gap, do not implement | Zero scope | — |

**Recommended for discussion:** Option A is the pragmatic starting point. INFO severity
avoids breaking valid but unusual Cypher patterns. Can be tightened to WARNING/ERROR
later with evidence.

**Affected files (Option A):**
- `src/orthograph/cypher/parser.py` — new `_extract_return_columns()` method on `GraphglotParser`; new `_check_return_output_alignment()` function in `validate_cypher()`
- `src/orthograph/cypher/base_models.py` — `_validate_declarative_cypher()` could run the check at definition time if `Output` is known
- `src/orthograph/cypher/validation.py` — `validate_query_catalogue()` passes `Output` to the check
- `tests/cypher/test_validate_query_catalogue.py` — new test cases for the mismatch issue

---

### Group D: Authoring ergonomics (Q5 + Q6)

---

#### Q5 — Is the double-declaration of generic type params and ClassVar acceptable?

**Problem:**
Every `CypherReadQuery` subclass must write the type twice:

```python
class MoviesByYear(CypherReadQuery[MoviesByYearParams, Movie]):  # generics
    Params = MoviesByYearParams                                    # class var (again)
    Output = Movie                                                 # class var (again)
```

The duplication exists because `__init_subclass__` (which runs definition-time checks)
cannot introspect generic type arguments — they are erased at runtime. The class vars are
the introspectable ground truth.

**Is this a problem?**
Yes, when team members coming from SQLModel, Pandera, or Django ORM expect a single
declaration. It is a minor but consistent friction point across every query a team writes.

**Options:**

| Option | Approach | Risk |
|--------|----------|------|
| A — Accept the pattern; add a clear comment in the base class explaining why | Docstring only | None |
| B — Use `typing.get_args(cls.__orig_bases__[0])` in `__init_subclass__` to auto-populate `Params` and `Output` from generic args if not explicitly declared | Eliminates duplication | Python version sensitivity; may behave differently with `from __future__ import annotations`; edge cases with multiple inheritance |
| C — Explore `__class_getitem__` to return a pre-configured class with Params/Output set | More controlled than B | Complex metaclass work |

**Note on Option B feasibility:**
`get_args` on `cls.__orig_bases__` is available in Python 3.9+. The library currently
targets 3.11+ (per `pyproject.toml`), so version sensitivity is low. The main risk is
with intermediate abstract classes (e.g. `class AbstractSampleRead(CypherReadQuery[SampleParams, Sample]): ...`)
where the generic args are available but the class is not yet concrete.

**Recommended for discussion:** Lean toward Option B with a guarded fallback — if
`Params`/`Output` are not explicitly declared, auto-populate from generics; if they are
declared, validate they match the generics (catches copy-paste errors where generics and
class vars disagree).

**Affected files (Option B):**
- `src/orthograph/query/base_models.py` — `ReadQuery.__init_subclass__` (line 111)
- `src/orthograph/cypher/base_models.py` — `CypherReadQuery.__init_subclass__` (line 142)
- `tests/query/test_base_models.py` — tests for auto-population behaviour
- All notebook examples — can drop the redundant `Params = ...` / `Output = ...` lines

---

#### Q6 — Should `NoParams` and `NoIdentifiers` import ceremony be reduced?

**Problem:**
A query with no params requires importing a sentinel type from an internal `bindings`
module:

```python
from orthograph.cypher.bindings import NoParams  # from an internal module

class NodeCount(CypherReadQuery[NoParams, CountResult]):
    Params = NoParams
    ...
```

This is unexpected for developers who just want a zero-parameter query. The `bindings`
module name gives no hint that `NoParams` lives there.

**Options:**

| Option | Change |
|--------|--------|
| A — Re-export `NoParams`/`NoIdentifiers` from `orthograph.cypher` package `__init__.py` | Import path shortcut only; no behaviour change |
| B — Make `Params` default to `NoParams` automatically when not declared (if Q5 Option B is adopted, this is a free side-effect) | Removes explicit import for the no-param case |
| C — Keep as-is; document in Getting Started | No change |

**Recommended for discussion:** Option A is a zero-risk improvement regardless of Q5
outcome. Option B eliminates the need entirely if Q5 Option B is adopted.

**Affected files (Option A):**
- `src/orthograph/cypher/__init__.py` — add `NoParams`, `NoIdentifiers` to `__all__` / re-export

---

### Group E: Pagination and bulk writes (Q7)

---

#### Q7 — What is the library's position on pagination and bulk writes?

**Problem:**
`CypherExecutor.read()` returns `list[D]` with no built-in limit, offset, or cursor.
`WriteQuery` executes one statement per call, with no first-class bulk-write pattern.

These are not gaps in the current implementation — they were never in scope. But before
going public, the library needs a **documented position** so that third-party teams don't
build incompatible patterns in the interim.

**Pagination options:**

| Option | Mechanism |
|--------|-----------|
| A — Convention only: recommend `$skip: int = 0` / `$limit: int = 100` fields on `Params` with `SKIP $skip LIMIT $limit` in the template | No library change; documented convention in Getting Started |
| B — Add a `PaginatedParams` mixin `BaseModel` with `skip`/`limit` fields that teams can compose into their own `Params` | Thin additive; no executor change |
| C — Add a `PaginatedReadQuery[P, D]` base with built-in skip/limit injection | New base class; changes executor contract |

**Bulk write options:**

| Option | Mechanism |
|--------|-----------|
| A — Convention only: use `$items: list[dict]` in `Params` and `UNWIND $items AS item CREATE (...)` | Documented pattern; no library change |
| B — Add a `BulkWriteQuery[P, R]` base | New base class |

**Recommended for discussion:** Option A for both in v0.1.0. A `PaginatedParams` mixin
(Pagination Option B) is a very low-cost additive that closes a specific ergonomic gap
without changing the executor. Decide whether it warrants inclusion pre-public.

---

### Group F: OpenAPI wiring (Q8 + Q9)

---

#### Q8 — What does a team need to wire `GraphDefinition` + typed queries to FastAPI?

**Problem:**
`QueryDescription.params_schema` (from `Params.model_json_schema()`) and
`QueryDescription.output_schema` (from `Output.model_json_schema()`) are the right
pieces for auto-generating OpenAPI endpoint schemas. However, a team building a FastAPI
endpoint today faces four gaps:

1. **Write endpoint response schema is missing** (`output_schema=None` — see Q3).
2. **No helper to get `Output` class from a `ReadQuery`** for use as
   `response_model=` in a FastAPI route decorator. The schema dict is available, but
   FastAPI's `response_model=` requires the class itself, not the dict.
3. **DI wiring pattern is undocumented.** `ReadPort[P, D].fetch(params)` maps perfectly
   to a FastAPI dependency (`Depends(lambda: port.fetch(params))`), but this pattern
   must be discovered independently.
4. **No pagination response envelope.** A `list[D]` return with no `total`, `page`, or
   `cursor` metadata is sufficient for many use cases but not all.

**The session should decide:**
- Whether orthograph should provide any FastAPI-aware helpers (thin, no hard dep on
  FastAPI) or leave this entirely to the consuming application.
- Whether `QueryDescription` should expose the `Output` class reference (not just the
  JSON schema dict) so consuming code can pass it to `response_model=`.
- Whether the library should ship a **recipe notebook** (05.01) demonstrating FastAPI
  wiring without providing integration code.

**Affected files:**
- `src/orthograph/query/catalogue.py` — `QueryDescription` dataclass; optionally add
  `output_class: type[BaseModel] | None` field
- New notebook: `notebooks/05.01_openapi_ergonomics_assessment.ipynb`

---

#### Q9 — Is the `<<identifier>>` syntax and `Identifiers` ClassVar discoverable enough?

**Problem:**
The `Identifiers`/`<<name>>` mechanism for label/rel-type injection is powerful but
has a discoverability gap:

1. `<<name>>` is not valid Cypher — it is orthograph-specific syntax. A developer
   reading a query template for the first time sees `MATCH (n:\`<<label>>\`)` with no
   signal that `<<label>>` is substituted before the query hits the driver.
2. `Identifiers = MyModel` is not mentioned in the `ReadQuery` base class docstring's
   "Subclasses MUST define" section (only `Params`, `Output`, `name`, `backend` are
   listed there).
3. The feature is currently documented only in `04.01_typed_cypher_queries.ipynb`
   section 6 and the `base_models.py` module docstring — not in the API reference or
   Getting Started guide.

**Options:**

| Option | Change |
|--------|--------|
| A — Improve docstrings in `CypherReadQuery`/`CypherWriteQuery` to call out `Identifiers` and `<<name>>` explicitly; update the "Optional class variables" section | Docstring only |
| B — Add a `QUERY_USES_IDENTIFIER_INJECTION` INFO issue to `validate_query_catalogue` output for any query that uses `<<name>>` | Adds a visible validation signal that draws attention to the feature |
| C — Change syntax from `<<name>>` to a more recognisable form (e.g. `{!name}`, a Jinja-like `{{ name }}`) | Breaking; affects all existing queries using identifiers |

**Recommended for discussion:** Option A is the minimum; Option B adds useful tooling
signal at zero ergonomic cost to the author. Option C is high-risk and should only be
considered if user research shows the `<<name>>` syntax is genuinely confusing in practice.

**Affected files (Option A+B):**
- `src/orthograph/cypher/base_models.py` — docstring updates
- `src/orthograph/cypher/validation.py` — `validate_query_catalogue()` — add INFO issue for identifier-injection queries

---

## Session Structure

This is designed as a focused decision session. Recommended format:

1. **Read this document** (10 min)
2. **Quick triage** — for each question, decide: resolve now / defer / delegate to ADR (10 min)
3. **Deep dive on Group A** (Q1+Q2 — naming + raw-result contract) — highest blast radius (20 min)
4. **Deep dive on Group B** (Q3 — write Output ClassVar) — second highest blast radius (15 min)
5. **Quick decisions on Groups C–F** (Q4–Q9) — most can be resolved with a single ADR note (20 min)
6. **Write ADRs** for all accepted decisions (30 min)
7. **Draft E31** — create the follow-on implementation epic with one task per accepted code change

Total estimated session time: ~90 minutes.

---

## Acceptance Criteria

- [x] Every question in this document has a resolution: `ACCEPTED`, `DEFERRED`, or `WONT-FIX`
- [x] Every `ACCEPTED` resolution has a corresponding ADR in `.agentic/decisions/`
- [x] ADRs record the rejected alternatives and their rationale (not just the chosen option)
- [x] A follow-on epic E31 is created with one concrete implementation task per accepted code change
- [x] E31 tasks are agent-executable: each task cites the exact files/lines to change, has acceptance criteria, and has a test pattern to follow
- [x] CONTEXT.md and the PRD are updated if any decision changes a documented boundary
- [x] This epic is moved to `archived_epics/` once all acceptance criteria are met

## Resolutions (2026-06-16)

| Q | Resolution | ADR |
|---|-----------|-----|
| Q1 — Rename `materialize` → `interpret_result` on `WriteQuery` | ACCEPTED | ADR-020 |
| Q2 — `WriteResultSummary` protocol in vendor-free `query/` layer | ACCEPTED | ADR-021 |
| Q3 — Optional `Output` ClassVar on `WriteQuery` (Option A) | ACCEPTED | — |
| Q4 — INFO-level RETURN→Output alignment check (Option A) | ACCEPTED | — |
| Q5 — Auto-populate `Params`/`Output` from generics; no explicit re-declaration | ACCEPTED | ADR-022 |
| Q6 — Re-export `NoParams`/`NoIdentifiers` from `orthograph.cypher` (Options A+B) | ACCEPTED | — |
| Q7 — `PaginatedParams` mixin; bulk writes convention-only, `BulkWriteQuery` deferred | ACCEPTED/DEFERRED | ADR-023 |
| Q8 — `output_class` on `QueryDescription`; FastAPI integration in notebooks only | ACCEPTED | ADR-024 |
| Q9 — Improve `Identifiers` docstrings + `QUERY_USES_IDENTIFIER_INJECTION` INFO issue (Options A+B) | ACCEPTED | — |

---

## Constraints and Non-Goals

- **No production code is written as part of E30** — this is decision-only.
- The session must not revisit decisions already captured in ADR-010 (declared
  Identifiers/Params split) or ADR-016 (typed query contract) unless a specific question
  in this document explicitly invalidates them.
- Async driver support is out of scope (see deferred items in `overview.md`).
- Rich nested/computed projections are out of scope.
- The goal is not to redesign the query system — it is to harden the current design's
  contract and close the identified ergonomic gaps before the public API boundary locks in.

---

## Related Files

| File | Relevance |
|------|-----------|
| `src/orthograph/query/base_models.py` | `ReadQuery`, `WriteQuery`, `Executor`, `ReadPort` — lines 92–205 |
| `src/orthograph/cypher/base_models.py` | `CypherReadQuery`, `CypherWriteQuery` — lines 113–204 |
| `src/orthograph/cypher/query_execution.py` | `CypherExecutor` — write result passthrough at line 71 |
| `src/orthograph/query/catalogue.py` | `QueryCatalogue`, `QueryDescription` — `output_schema` at line 119 |
| `src/orthograph/cypher/bindings.py` | `NoParams`, `NoIdentifiers`, `CypherQuery` |
| `src/orthograph/cypher/parser.py` | `validate_cypher`, `GraphglotParser` — `lg.outputs` at line 162 |
| `notebooks/04.01_typed_cypher_queries.ipynb` | Current typed query documentation — prose/code mismatch at section 3 |
| `.agentic/decisions/010-declared-identifier-parameters.md` | ADR for `Identifiers`/`<<name>>` mechanism |
| `.agentic/decisions/018-query-package-naming.md` | ADR for query package topology |
