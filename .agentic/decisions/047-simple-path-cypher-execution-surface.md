# ADR-047: Simple-Path Cypher Execution Surface — `CypherQueryExecutor` and `run_cypher_*` Verbs

> **Status:** Accepted (decision recorded; implementation pending — E62)
> **Date:** 2026-06-29
> **Epic:** E62 (Simple-Path Cypher Execution Surface)
> **Depends on:** E39 (async executor — done; established `AsyncCypherExecutor` + caller-owned tx), E60/ADR-045 (query shape vocabulary), E37 (delivered the simple `CypherQuery` + sync `CypherExecutor` acceptance)
> **Relates to:** ADR-028 (caller-owned transactions — the new executors honour it unchanged), ADR-041 (root capability modules — `execution.py` is the public surface)

---

## Context

Orthograph has **two** Cypher query authoring paths (documented in
`src/orthograph/cypher/query.py`):

1. **Typed path** — `TypedCypherReadQueryModel[P, D]` / `TypedCypherWriteQueryModel[P, R]`.
   Subclass, declare an `Output` model, implement `materialize`/`interpret_result`.
   These **are** `ReadQueryModel[P, D]` / `WriteQueryModel[P, R]`, so the executors
   (`CypherExecutor`, `AsyncCypherExecutor`) and the public verbs
   (`run_read`/`run_write`/`run_read_async`/`run_write_async`) accept them with full
   static typing — `read()` returns `list[D]`, `write()` returns `R`.

2. **Simple path** — `CypherQuery`. A concrete, YAML-serialisable `BaseModel` you
   instantiate directly (no subclassing). It declares **no** `Output` model:
   `materialize()` returns `dict[str, Any]` and `interpret_result()` passes the raw
   `CypherWriteResultSummary` through. It does **not** split read from write.

### The defect

`D` in `ReadQueryModel[P, D]` is `TypeVar("D", bound=BaseModel)` — load-bearing:
`cypher/generator.py` calls `output_model.model_validate(...)` on `D`. `CypherQuery`'s
output is `dict[str, Any]`, which is not a `BaseModel`, so `CypherQuery` is **not** a
subtype of `ReadQueryModel[P, D]` for any `P, D`. It only satisfies the executor
contract by duck typing at runtime.

Consequence: **every** call site that passes a `CypherQuery` to `CypherExecutor`,
`AsyncCypherExecutor`, or the public `run_*` verbs requires `# type: ignore[arg-type]`.
This is already visible in the codebase:

- `tests/cypher/test_query_execution.py` — 4 per-line `# type: ignore[arg-type]`.
- `tests/cypher/test_query_e2e.py` — a **file-wide** `# mypy: disable-error-code="arg-type"`
  because every executor call in the file passes a `CypherQuery`.

A consuming application using the simple path (YAML-loaded queries, quick scripts) would
be forced to sprinkle `# type: ignore` on every execution call. That breaks the library's
contract: **well-typed, no band-aid, no exceptions — even for the simple path.**

### Rejected framings

- **The `type: ignore` is the honest path-crossing marker.** Rejected. It puts the cost on
  every consumer of a first-class, documented path. The simple path is meant to be the
  low-ceremony on-ramp; making it the type-unsafe path inverts that intent.
- **Relax `D`'s bound to unconstrained (`TypeVar("D")`).** Rejected. Breaks `generator.py`'s
  `output_model.model_validate(...)`; the bound is correct for the typed path.
- **`CypherQuery` inherits `ReadQueryModel[BaseModel, dict[str, Any]]`.** Rejected by the
  team: `CypherQuery` is deliberately simpler and makes **no** read/write distinction;
  forcing it into the read hierarchy (and a second time into the write hierarchy)
  contradicts its design and re-opens the `D` bound problem.
- **Methods on `CypherQuery` itself (`query.run_read(executor, params)`).** Rejected by the
  team: `CypherQuery` does not split read vs write, and we keep it a plain serialisable
  data class for YAML round-tripping — it should not carry execution-dispatch methods.

---

## Decisions

### Q1 — `CypherQuery` gets its own dedicated executor pair

Introduce `CypherQueryExecutor` (sync) and `AsyncCypherQueryExecutor` (async) in
`src/orthograph/cypher/query_execution.py`, typed **concretely on `CypherQuery`**. They are
**not** `Executor`/`AsyncExecutor` subclasses (those are the typed-path seam keyed on
`ReadQueryModel`/`WriteQueryModel`). They are a parallel, self-contained surface.

Rationale (rubric: readability, simplicity, low surprise, contract respect): the simple path
becomes well-typed end-to-end with zero casts, zero `type: ignore`, and zero generic-hierarchy
games. `CypherQuery` stays a plain serialisable `BaseModel`. The executor classes read as
exactly what they do.

After this change `CypherQuery` is **no longer passed to** `CypherExecutor`/`AsyncCypherExecutor`.
The duck-typed acceptance (the source of the gap) ends. This is correct: the two paths now have
two surfaces.

### Q2 — Two operations named by return shape, not transactional intent

`CypherQuery` makes no read/write distinction, so the two executor operations are named for
**what they return**, not for read/write intent:

| Operation | Returns | Cypher shape |
|---|---|---|
| `fetch(query, params)` | `list[dict[str, Any]]` | a query with a `RETURN` (rows) |
| `execute(query, params)` | `CypherWriteResultSummary` | a mutation (counters) |

`fetch`/`execute` is the **proposed default**; the final verb names are an **open question
for the E62.0 decision pass** (see Open Questions). Both operations honour the caller-owned
transaction contract (ADR-028): the executor opens the session via the factory, runs the
single built statement, and **never** commits or rolls back.

### Q3 — Reuse the existing I/O internals; no behaviour duplication

The new executors reuse the already-shared helpers in `query_execution.py`:
- `CypherExecutor._validate_cypher(cypher, query_id)` — the `@staticmethod` runtime parse guard.
- `_summary_from_counters(counters)` — the module-level summary builder.

`CypherQuery` already implements `params_schema`, `query_id`, `build(params)`,
`materialize(raw)`, and `interpret_result(raw)`. The new executors call these directly. No
new validation, parsing, or summary logic is written — the new classes are thin, typed
wrappers over the existing prologue + I/O tail.

### Q4 — Public verbs are Cypher-specific and do NOT go through the backend loader

The typed `run_read`/`run_write` verbs are backend-parameterised (`run_read("neo4j", ...)`)
and resolve the executor via `backends.loader.load_executor(name)`. `CypherQuery` carries
`backend = Backend.CYPHER` by construction — it is Cypher-only. Therefore the simple-path
public verbs **take no backend name** and construct the Cypher executor directly:

```python
def run_cypher_fetch(connection_factory, query: CypherQuery, params) -> list[dict[str, Any]]
def run_cypher_execute(connection_factory, query: CypherQuery, params) -> CypherWriteResultSummary
async def run_cypher_fetch_async(connection_factory, query, params) -> list[dict[str, Any]]
async def run_cypher_execute_async(connection_factory, query, params) -> CypherWriteResultSummary
```

These live in `src/orthograph/execution.py` beside the typed verbs and are re-exported in its
`__all__`. **No registry/loader wiring is added** — avoiding loader entries keeps the surface
minimal and matches the fact that there is no backend choice to make. (This Q4 stance is the
recommended resting state; if the E62.0 pass finds a concrete reason to route through the
loader, it must record the reversal here.)

### Q5 — Remove every simple-path `type: ignore`

Migrate all `CypherQuery` execution call sites to the new surface and delete:
- the 4 per-line `# type: ignore[arg-type]` in `tests/cypher/test_query_execution.py`,
- the file-wide `# mypy: disable-error-code="arg-type"` in `tests/cypher/test_query_e2e.py`,
- the transitional note in `cypher/query.py`'s docstring (replaced by a "use the executor /
  `run_cypher_*` verbs" note).

mypy must pass with **no** suppressions related to `CypherQuery` execution.

---

## Open Questions (resolve in the E62.0 decision pass before E62.1)

1. **Verb names.** `fetch`/`execute` (proposed) vs `rows`/`mutate` vs `read`/`write` (rejected —
   re-introduces read/write framing the simple path avoids) vs other. The public verb names
   (`run_cypher_*`) follow from the chosen method names.
2. **Method placement of `materialize`/`interpret_result`.** Keep them on `CypherQuery` (the
   new executor calls them — proposed, smallest change) **or** inline the identity-dict / pass-through
   logic into the executor and drop the methods from `CypherQuery`. Proposed: keep them; they are
   harmless and already tested.
3. **Loader wiring (Q4 confirmation).** Confirm the verbs construct the executor directly with no
   `BackendSpec` entry, or record a reason to wire it.

---

## E62.0 resolutions

Decided 2026-06-29 by an agent running the E62.0 decision pass with no human present;
all three Open Questions adopt the ADR-047 proposed defaults verbatim.

1. **Verb names — adopt the proposal.** Executor methods are `fetch` (returns
   `list[dict[str, Any]]`) and `execute` (returns `CypherWriteResultSummary`). Public verbs
   are `run_cypher_fetch`, `run_cypher_execute`, `run_cypher_fetch_async`,
   `run_cypher_execute_async`. The rejected `read`/`write` framing is not used.
2. **`materialize`/`interpret_result` placement — adopt the proposal.** Keep both methods on
   `CypherQuery`. The new executor's `fetch` calls `query.materialize(dict(rec))` per record;
   `execute` returns `_summary_from_counters(...)` directly (it does not call
   `interpret_result`, which is a pass-through).
3. **Loader wiring (Q4) — adopt the proposal.** No `BackendSpec`/loader entry is added. The
   `run_cypher_*` verbs construct `CypherQueryExecutor` / `AsyncCypherQueryExecutor` directly.
   `CypherQuery` is Cypher-only (`backend = Backend.CYPHER`), so there is no backend choice to
   route.

These match the proposed defaults exactly; no reversal recorded.

---

## Consequences

- The simple path is well-typed end-to-end; consumers write `executor.fetch(query, params)` /
  `run_cypher_fetch(factory, query, params)` and get `list[dict[str, Any]]` with no suppression.
- `CypherQuery` can no longer be passed to the typed `CypherExecutor`/`AsyncCypherExecutor`.
  This is the intended outcome; the duck-typed acceptance was the defect.
- Two small new classes + four public verbs. No change to the typed hierarchy, the `D` bound,
  `generator.py`, or `CypherQuery`'s serialisation. Blast radius is contained (see E62).
- ADR-028's caller-owned transaction contract is unchanged and now also stated by the new
  simple-path executors.

---

## References

- E62 epic file: `.agentic/planning/active_epics/E62_simple_path_cypher_execution.md`
- The defect's live evidence: `tests/cypher/test_query_execution.py` (4 ignores),
  `tests/cypher/test_query_e2e.py` (file-wide disable), `tests/cypher/test_query_async_e2e.py`
  (the two simple-path tests removed in E39.9, to be re-added on the new surface here).
- ADR-028 (caller-owned transactions), ADR-045 (query shape vocabulary), ADR-041 (root modules).
