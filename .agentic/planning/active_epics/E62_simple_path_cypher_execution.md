# Epic E62: Simple-Path Cypher Execution Surface — `CypherQueryExecutor`, `run_cypher_*` Verbs, Zero `type: ignore`

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Status:** planned (independent; opened from the E39.9 review, 2026-06-29)
> **Decision authority:** [ADR-047 — Simple-path Cypher execution surface](../../decisions/047-simple-path-cypher-execution-surface.md). Read ADR-047 before any task.
> **Relates to:** ADR-028 (caller-owned transactions — the new executors honour it unchanged),
> ADR-045 (query shape vocabulary: `params_schema`/`query_id`), ADR-041 (root capability
> modules — `execution.py` is the public surface), E37 (delivered `CypherQuery` + sync
> `CypherExecutor` acceptance), E39 (delivered `AsyncCypherExecutor`).

---

## Why this epic exists

Orthograph has two Cypher query authoring paths:

1. **Typed path** — `TypedCypherReadQueryModel[P, D]` / `TypedCypherWriteQueryModel[P, R]`.
   These **are** `ReadQueryModel[P, D]` / `WriteQueryModel[P, R]`, so the executors and the
   public `run_read`/`run_write` verbs accept them with full static typing.
2. **Simple path** — `CypherQuery`: a concrete, YAML-serialisable `BaseModel` you instantiate
   directly. It declares **no** `Output` model (`materialize()` → `dict[str, Any]`,
   `interpret_result()` passes the raw `CypherWriteResultSummary` through) and makes **no**
   read/write distinction.

**The defect.** `D` in `ReadQueryModel[P, D]` is `TypeVar("D", bound=BaseModel)` — load-bearing
(`cypher/generator.py` calls `output_model.model_validate(...)`). `CypherQuery`'s output is
`dict[str, Any]`, not a `BaseModel`, so `CypherQuery` is **not** a subtype of
`ReadQueryModel[P, D]`. It only satisfies the executor at runtime by duck typing. Therefore
**every** call passing a `CypherQuery` to `CypherExecutor` / `AsyncCypherExecutor` / the public
`run_*` verbs requires `# type: ignore[arg-type]`. A consuming application on the simple path
would have to sprinkle `# type: ignore` on every execution call — breaking the library's
contract (well-typed, no band-aid).

**The fix (ADR-047).** Give `CypherQuery` its own dedicated, concretely-typed executor pair
(`CypherQueryExecutor` / `AsyncCypherQueryExecutor`) with two operations named by return shape
(`fetch` → `list[dict[str, Any]]`, `execute` → `CypherWriteResultSummary`), plus public
`run_cypher_*` verbs. This removes every simple-path `type: ignore`. `CypherQuery` stops being
passed to the typed executors (the duck-typed acceptance was the defect).

---

## Reality Check (verified 2026-06-29)

1. **`CypherQuery` lives in `src/orthograph/cypher/query.py`** (`class CypherQuery(BaseModel)`,
   line ~139). It exposes `params_schema: type[BaseModel]`, `query_id: str`,
   `identifiers_schema: type[BaseModel] | None`, `build(params) -> CypherQueryData`,
   `materialize(raw: dict) -> dict[str, Any]`, `interpret_result(raw) -> Any`,
   and `backend: ClassVar[Backend] = Backend.CYPHER`.
2. **The I/O internals to reuse are already in `src/orthograph/cypher/query_execution.py`:**
   - `CypherExecutor._validate_cypher(cypher: str, query_name: str) -> None` — a `@staticmethod`
     that parses the Cypher and raises `CypherSyntaxError` on failure.
   - `_summary_from_counters(counters: Any) -> CypherWriteResultSummary` — module-level helper.
   - `CypherWriteResultSummary` — module-level dataclass.
3. **The sync `CypherExecutor.read/write` and async `AsyncCypherExecutor.read/write`** show the
   exact prologue + I/O pattern to mirror. Sync read: `with self._driver_factory() as session:
   records = list(session.run(cypher, **qparams))`. Async read: `async with
   self._driver_factory() as session: result = await session.run(...); records = [dict(rec)
   async for rec in result]`. Write tail: `_summary_from_counters(result.consume().counters)`
   (sync) / `_summary_from_counters((await result.consume()).counters)` (async).
4. **`CypherQuery.build(params)` takes a model instance**, so the prologue is:
   `params = query.params_schema.model_validate(raw_params)` → `cypher, qparams =
   query.build(params)` → `CypherExecutor._validate_cypher(cypher, query.query_id)`.
   (The `CypherQuery.materialize` is `dict(raw)` identity; `fetch` can call it or build the
   dict directly — see E62.0 Q2.)
5. **Public verbs live in `src/orthograph/execution.py`.** It imports `CypherExecutor`,
   `CypherWriteResultSummary` from `query_execution.py` and defines
   `run_read`/`run_write`/`run_read_async`/`run_write_async`, all routed through
   `backends.loader.load_executor(name)` / `load_async_executor(name)`. The typed verbs are
   **backend-parameterised** (`run_read("neo4j", factory, query, params)`).
6. **`CypherQuery` is Cypher-only** (`backend = Backend.CYPHER`). Per ADR-047 Q4, the simple-path
   verbs take **no** backend name and construct the Cypher executor directly — **no** loader/registry
   wiring is added.
7. **The `type: ignore` debt to remove (ADR-047 Q5):**
   - `tests/cypher/test_query_execution.py` — **4** per-line `# type: ignore[arg-type]` at lines
     ~372, ~402, ~437, ~468 (tests `test_cypher_query_read_returns_raw_rows`,
     `test_cypher_query_read_with_typed_params_model`, `test_cypher_query_write_returns_full_summary`,
     `test_cypher_query_write_does_not_commit_caller_owns_tx`).
   - `tests/cypher/test_query_e2e.py` — a **file-wide** `# mypy: disable-error-code="arg-type"`
     near line 25, because every executor call in the file passes a `CypherQuery`.
   - `src/orthograph/cypher/query.py` — a transitional docstring note (added 2026-06-29) that
     references E62/ADR-047 and the `# type: ignore` boundary.
8. **Test stack:** `pytest` + `pytest-mock` + `pytest-asyncio` (`asyncio_mode = "auto"`).
   Live-DB tests are `@pytest.mark.neo4j`, gated by `--neo4j`. Fixtures `neo4j_driver`/`neo4j_clean`
   (sync) and `async_neo4j_driver`/`async_neo4j_clean` (async) are in the root `conftest.py`.
   The simple-path async tests that E39.9 removed are to be re-added here on the new surface.
9. **`FakeGraphSession`/`FakeWriteResult`/`FakeSummary`/`FakeCounters`** test doubles already
   exist in `tests/cypher/test_query_execution.py` and are reused.

---

## Scope

**In scope:**
- `CypherQueryExecutor` (sync) + `AsyncCypherQueryExecutor` (async) in `query_execution.py`,
  typed concretely on `CypherQuery`, with `fetch`/`execute` operations (final names per E62.0).
- Public `run_cypher_fetch` / `run_cypher_execute` (+ async) verbs in `execution.py`, taking a
  connection factory + `CypherQuery` (no backend name).
- Migrate every `CypherQuery` execution call site to the new surface.
- Delete all simple-path `type: ignore` and the file-wide mypy disable.
- Re-add the two simple-path async e2e tests on the new surface (removed by E39.9).
- Update `cypher/query.py` docstring + PRD/overview/CONTEXT.

**Out of scope:**
- Any change to the typed path (`ReadQueryModel`/`WriteQueryModel`, `CypherExecutor`,
  `AsyncCypherExecutor`, the `D` bound, `generator.py`).
- Backend-loader/registry wiring for the simple path (ADR-047 Q4 — not needed).
- `CypherQuery` serialisation, validation, or catalogue behaviour.
- Removing `CypherQuery.materialize`/`interpret_result` (decided in E62.0 Q2; default = keep).

---

## How to use this epic (execution protocol)

Tasks are **sequential within their wave**. A low-context agent completes each task by reading
**only** (a) that task's section and (b) the **Shared Reference** at the bottom. Each task states
its exact files, the change, a binary acceptance gate, and the **model** it is sized for.

**Model sizing legend:**
- **Haiku** — fully mechanical; every edit spelled out verbatim.
- **Sonnet** — scoped implementation; a concrete pattern exists to mirror (the existing sync/async
  `CypherExecutor`).
- **Opus** — cross-file behaviour reasoning with real blast-radius risk. (None in this epic.)

---

## Task Map (dependency order)

```
WAVE 0 — decide the open questions (no code)
E62.0  Decision pass: verb names, materialize placement, loader confirmation   [Sonnet]  ← unblocks all

WAVE 1 — build the surface (additive)
E62.1  Add CypherQueryExecutor (sync) + AsyncCypherQueryExecutor (async)        [Sonnet]  ← unblocks E62.2, E62.4, E62.5
E62.2  Add run_cypher_* public verbs in execution.py + __all__                  [Sonnet]  ← unblocks E62.3, E62.6

WAVE 2 — migrate off the typed executors, kill the type: ignore
E62.3  Migrate tests/cypher/test_query_execution.py CypherQuery calls (4 ignores) [Sonnet] ← depends E62.1
E62.4  Migrate tests/cypher/test_query_e2e.py + remove file-wide mypy disable     [Sonnet] ← depends E62.1
E62.5  Re-add 2 simple-path async e2e tests on the new surface                    [Sonnet] ← depends E62.1
E62.6  Add surface unit tests for run_cypher_* verbs                              [Sonnet] ← depends E62.2

WAVE 3 — docs
E62.7  Update cypher/query.py docstring + PRD + overview + CONTEXT               [Haiku]   ← depends E62.1–E62.6
```

- **E62.0** first (decides names used by every later task). If executed by an agent rather than a
  human, default to the ADR-047 proposals: `fetch`/`execute`, keep `materialize`/`interpret_result`,
  no loader wiring.
- **E62.1 → E62.2** sequential. **E62.3, E62.4, E62.5** depend on E62.1 and may run in parallel.
  **E62.6** depends on E62.2. **E62.7** last.

---

## Tasks

### E62.0 — Decision pass: confirm verb names, `materialize` placement, loader stance

**Model:** Sonnet. **Type:** Decision (no code). **Wave 0.** No dependencies.

**Goal:** Resolve ADR-047's three Open Questions so every later task uses fixed names. If a human
runs the session, record their choices; if an agent runs it, adopt the ADR-047 proposals and note
that in ADR-047.

**What to decide (and the proposed defaults):**
1. **Operation/verb names.** Proposed: methods `fetch` (returns `list[dict[str, Any]]`) and
   `execute` (returns `CypherWriteResultSummary`); public verbs `run_cypher_fetch`,
   `run_cypher_execute`, `run_cypher_fetch_async`, `run_cypher_execute_async`. Rejected
   alternative: `read`/`write` (re-introduces the read/write framing the simple path avoids).
2. **`materialize`/`interpret_result` placement.** Proposed: **keep** them on `CypherQuery`; the
   new executor calls `query.materialize(dict(rec))` for `fetch` and returns
   `_summary_from_counters(...)` directly for `execute` (it does not need `interpret_result`,
   which is a pass-through). Alternative: inline `dict(rec)` in the executor and stop calling the
   `CypherQuery` methods — only choose this if it reads more clearly to the session.
3. **Loader wiring (ADR-047 Q4).** Proposed: **no** `BackendSpec`/loader entry; the verbs
   construct `CypherQueryExecutor` / `AsyncCypherQueryExecutor` directly. Confirm or record a
   reason to wire it.

**What to do:** Append a short "E62.0 resolutions" subsection to ADR-047 stating the three chosen
values verbatim. If they match the proposals, say so explicitly.

**Acceptance gate:**
- [ ] ADR-047 has an "E62.0 resolutions" subsection naming: the two method names, the two×two
      public verb names, the `materialize` placement choice, and the loader stance.
- [ ] No source/test code changed in this task.

---

### E62.1 — Add `CypherQueryExecutor` (sync) and `AsyncCypherQueryExecutor` (async)

**Model:** Sonnet. **Type:** Code (source — additive). **Wave 1.** Depends on E62.0.

**Goal:** Add two concrete executors typed on `CypherQuery`, reusing the existing prologue + I/O
internals, honouring the caller-owned transaction contract (ADR-028 — never commit/rollback).

**What to do (in `src/orthograph/cypher/query_execution.py`, after `AsyncCypherExecutor`):**

Use the names resolved in E62.0 (defaults shown: `fetch`/`execute`). Add a `CypherQuery` import
under `TYPE_CHECKING` to avoid any import cycle (`query_execution.py` is imported by
`execution.py`; `query.py` imports only from `bindings`, `schema_codec`, `base_models` — so a
`TYPE_CHECKING` import of `CypherQuery` here is safe and cycle-free):

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from orthograph.cypher.query import CypherQuery
```

Then add the two classes:

```python
class CypherQueryExecutor:
    """Executor for the simple-path CypherQuery. Caller owns the transaction (ADR-028).

    CypherQuery declares no Output model and makes no read/write distinction, so this
    executor exposes two operations named by return shape:
      - fetch()   -> list[dict[str, Any]]   (a RETURN query)
      - execute() -> CypherWriteResultSummary (a mutation)

    It never commits or rolls back; the factory yields the session or a live transaction.
    """

    def __init__(self, driver_factory: Callable[[], Any]) -> None:
        self._driver_factory = driver_factory

    def fetch(self, query: "CypherQuery", raw_params: Any) -> list[dict[str, Any]]:
        params = query.params_schema.model_validate(raw_params)
        cypher, qparams = query.build(params)
        CypherExecutor._validate_cypher(cypher, query.query_id)
        with self._driver_factory() as session:
            records = list(session.run(cypher, **qparams))
            return [query.materialize(dict(rec)) for rec in records]

    def execute(self, query: "CypherQuery", raw_params: Any) -> CypherWriteResultSummary:
        params = query.params_schema.model_validate(raw_params)
        cypher, qparams = query.build(params)
        CypherExecutor._validate_cypher(cypher, query.query_id)
        with self._driver_factory() as session:
            result = session.run(cypher, **qparams)
            return _summary_from_counters(result.consume().counters)


class AsyncCypherQueryExecutor:
    """Async executor for the simple-path CypherQuery. Caller owns the transaction (ADR-028)."""

    def __init__(self, driver_factory: Callable[[], Any]) -> None:
        self._driver_factory = driver_factory

    async def fetch(self, query: "CypherQuery", raw_params: Any) -> list[dict[str, Any]]:
        params = query.params_schema.model_validate(raw_params)
        cypher, qparams = query.build(params)
        CypherExecutor._validate_cypher(cypher, query.query_id)
        async with self._driver_factory() as session:
            result = await session.run(cypher, **qparams)
            records = [dict(rec) async for rec in result]
        return [query.materialize(rec) for rec in records]

    async def execute(self, query: "CypherQuery", raw_params: Any) -> CypherWriteResultSummary:
        params = query.params_schema.model_validate(raw_params)
        cypher, qparams = query.build(params)
        CypherExecutor._validate_cypher(cypher, query.query_id)
        async with self._driver_factory() as session:
            result = await session.run(cypher, **qparams)
            return _summary_from_counters((await result.consume()).counters)
```

Notes:
- `materialize()` is called **after** the `async with` block in the async `fetch` (it is pure/sync).
- `query.build(params)` returns a `CypherQueryData` NamedTuple unpacking as `cypher, qparams`.
- Reuse `CypherExecutor._validate_cypher` (a `@staticmethod`) and `_summary_from_counters`
  (module-level) — do not duplicate parsing or summary logic.
- These classes are **not** `Executor`/`AsyncExecutor` subclasses. No ABC, no generics.
- If E62.0 chose to inline `dict(rec)` instead of `query.materialize(...)`, apply that variant.

Import smoke: `python -c "from orthograph.cypher.query_execution import CypherQueryExecutor, AsyncCypherQueryExecutor"`.

**Acceptance gate:**
- [ ] `CypherQueryExecutor` and `AsyncCypherQueryExecutor` exist with `fetch`/`execute`
      (or the E62.0 names) typed concretely: `fetch -> list[dict[str, Any]]`,
      `execute -> CypherWriteResultSummary`.
- [ ] Both reuse `CypherExecutor._validate_cypher` and `_summary_from_counters`; no commit/rollback.
- [ ] `TYPE_CHECKING` import of `CypherQuery`; no runtime import cycle.
- [ ] `python -m mypy src/` is clean. `python -m pytest -q` passes (no new tests yet).

---

### E62.2 — Add public `run_cypher_*` verbs in `execution.py`

**Model:** Sonnet. **Type:** Code (source — additive). **Wave 1.** Depends on E62.1.

**Goal:** Expose the simple-path executors through the public execution module, mirroring the typed
`run_read`/`run_write` shape but **without** a backend name (CypherQuery is Cypher-only — ADR-047 Q4).

**What to do (in `src/orthograph/execution.py`):**

1. Import the new executors and `CypherQuery`:
   ```python
   from orthograph.cypher.query_execution import (
       AsyncCypherQueryExecutor,
       CypherExecutor,
       CypherQueryExecutor,
       CypherWriteResultSummary,
   )
   from orthograph.cypher.query import CypherQuery
   ```
2. Add the four verbs (use E62.0 names; defaults shown), after the typed verbs:
   ```python
   def run_cypher_fetch(
       connection_factory: Callable[[], Any],
       query: CypherQuery,
       params: Any,
   ) -> list[dict[str, Any]]:
       """Execute a simple-path CypherQuery RETURN; return raw ``list[dict]`` rows.

       CypherQuery is Cypher-only, so no backend name is taken. ``connection_factory``
       yields a session or live transaction; the caller owns the transaction (ADR-028).
       """
       return CypherQueryExecutor(connection_factory).fetch(query, params)


   def run_cypher_execute(
       connection_factory: Callable[[], Any],
       query: CypherQuery,
       params: Any,
   ) -> CypherWriteResultSummary:
       """Execute a simple-path CypherQuery mutation; return the write summary.

       Does not commit — the caller owns the transaction boundary (ADR-028).
       """
       return CypherQueryExecutor(connection_factory).execute(query, params)


   async def run_cypher_fetch_async(
       connection_factory: Callable[[], Any],
       query: CypherQuery,
       params: Any,
   ) -> list[dict[str, Any]]:
       """Async: execute a simple-path CypherQuery RETURN; return raw ``list[dict]`` rows."""
       return await AsyncCypherQueryExecutor(connection_factory).fetch(query, params)


   async def run_cypher_execute_async(
       connection_factory: Callable[[], Any],
       query: CypherQuery,
       params: Any,
   ) -> CypherWriteResultSummary:
       """Async: execute a simple-path CypherQuery mutation; return the write summary."""
       return await AsyncCypherQueryExecutor(connection_factory).execute(query, params)
   ```
3. Add `"run_cypher_fetch"`, `"run_cypher_execute"`, `"run_cypher_fetch_async"`,
   `"run_cypher_execute_async"` to `__all__`. Optionally re-export `CypherQueryExecutor`/
   `AsyncCypherQueryExecutor` too (add to `__all__` if so).
4. Update the module docstring to list the four simple-path verbs alongside the typed ones,
   noting they take a connection factory + CypherQuery (no backend name).

Verify: `python -c "from orthograph.execution import run_cypher_fetch, run_cypher_execute, run_cypher_fetch_async, run_cypher_execute_async"`.

**Acceptance gate:**
- [ ] The four `run_cypher_*` verbs exist in `execution.py` and `__all__`, typed concretely
      (`-> list[dict[str, Any]]` / `-> CypherWriteResultSummary`), taking no backend name.
- [ ] The module docstring describes the simple-path verbs.
- [ ] `python -m mypy src/` clean; `python -m pytest -q` passes.

---

### E62.3 — Migrate `tests/cypher/test_query_execution.py` CypherQuery calls (remove 4 ignores)

**Model:** Sonnet. **Type:** Code (tests). **Wave 2.** Depends on E62.1.

**Goal:** Switch the four `CypherQuery` executor calls from `CypherExecutor` to
`CypherQueryExecutor` and delete the four `# type: ignore[arg-type]`.

**What to do (in `tests/cypher/test_query_execution.py`):**

These four tests construct a `CypherQuery` and a `FakeGraphSession`, then call
`CypherExecutor(...).read/write(query, ...)  # type: ignore[arg-type]`. Replace with
`CypherQueryExecutor(...).fetch/execute(...)` (E62.0 names) and remove the ignore:

1. `test_cypher_query_read_returns_raw_rows` (≈ line 370–372):
   `executor = CypherExecutor(lambda: session)` → `executor = CypherQueryExecutor(lambda: session)`;
   `result: list[dict[str, Any]] = executor.read(query, {"released": 1999})  # type: ignore[arg-type]`
   → `result: list[dict[str, Any]] = executor.fetch(query, {"released": 1999})`. Keep all assertions.
2. `test_cypher_query_read_with_typed_params_model` (≈ line 400–402): same — `CypherQueryExecutor`,
   `.fetch(query, {"released": 2010})`, drop the ignore.
3. `test_cypher_query_write_returns_full_summary` (≈ line 435–437): `CypherQueryExecutor`,
   `result: CypherWriteResultSummary = executor.execute(query, {"title": "Dune"})` (drop ignore).
   Keep the `_FakeSessionWithCounters` double and all counter assertions.
4. `test_cypher_query_write_does_not_commit_caller_owns_tx` (≈ line 466–468): `CypherQueryExecutor`,
   `_: Any = executor.execute(query, {"title": "Arrival"})` (drop ignore). Keep the
   `committed is False` / `rolled_back is False` assertions.

Add `CypherQueryExecutor` to the imports from `orthograph.cypher.query_execution` at the top of the
file (it currently imports `CypherExecutor`, `CypherWriteResultSummary`, the fakes).

**Acceptance gate:**
- [ ] The four tests use `CypherQueryExecutor` with `.fetch`/`.execute` (E62.0 names).
- [ ] All four `# type: ignore[arg-type]` are gone; no new ignore added.
- [ ] All assertions unchanged and passing: `python -m pytest -q tests/cypher/test_query_execution.py`.
- [ ] `python -m mypy tests/cypher/test_query_execution.py` clean.

---

### E62.4 — Migrate `tests/cypher/test_query_e2e.py` and remove the file-wide mypy disable

**Model:** Sonnet. **Type:** Code (tests — e2e). **Wave 2.** Depends on E62.1.

**Goal:** Switch every `CypherQuery` executor call in the live-DB e2e file from `CypherExecutor`
to `CypherQueryExecutor`, then delete the file-wide `# mypy: disable-error-code="arg-type"`.

**What to do (in `tests/cypher/test_query_e2e.py`):**

1. The helper `_make_executor(driver)` returns `CypherExecutor(driver.session)`. Change it to
   return `CypherQueryExecutor(driver.session)` (import `CypherQueryExecutor` from
   `orthograph.cypher.query_execution`).
2. Every `executor.read(query, ...)` call (≈ lines 131, 153, 181, 205, 233) → `executor.fetch(query, ...)`.
   Every `executor.write(query, ...)` call (≈ lines 264, 301, 335) → `executor.execute(query, ...)`.
   (E62.0 names.) Keep the `list[dict[str, Any]]` / `CypherWriteResultSummary` annotations and all
   assertions unchanged.
3. **Remove** the file-wide `# mypy: disable-error-code="arg-type"` comment near line 25 (and any
   now-redundant per-line ignores, if present).
4. These are `@pytest.mark.neo4j` tests. Verify both with and without the flag:
   - `python -m pytest -q tests/cypher/test_query_e2e.py` → all skipped cleanly (no `--neo4j`).
   - `python -m pytest -q --neo4j --neo4j-password <pw> tests/cypher/test_query_e2e.py` → all pass.

**Acceptance gate:**
- [ ] `_make_executor` returns `CypherQueryExecutor`; all calls use `.fetch`/`.execute`.
- [ ] The file-wide `# mypy: disable-error-code="arg-type"` is removed; no per-line ignore replaces it.
- [ ] `python -m mypy tests/cypher/test_query_e2e.py` clean.
- [ ] Without `--neo4j`: tests skip. With `--neo4j`: tests pass. Same collected count as before.

---

### E62.5 — Re-add the two simple-path async e2e tests on the new surface

**Model:** Sonnet. **Type:** Code (tests — e2e). **Wave 2.** Depends on E62.1.

**Goal:** Restore the async simple-path coverage that E39.9 removed, now using
`AsyncCypherQueryExecutor` (no `type: ignore`). These prove the async simple-path `fetch`/`execute`
work against a live DB and honour the caller-owned tx.

**What to do:** Add a new file `tests/cypher/test_query_async_simple_e2e.py` (keep it separate from
`test_query_async_e2e.py`, which is typed-path only). Mirror the structure of
`tests/cypher/test_query_async_e2e.py` (the `--neo4j` gate, `async_neo4j_driver`/`async_neo4j_clean`
fixtures, the `_seed` helper, `@pytest.mark.neo4j`).

Define module-level `CypherQuery` constants (Cypher-only simple path):
```python
from orthograph.cypher.bindings import NoIdentifiers
from orthograph.cypher.query import CypherQuery
from orthograph.cypher.query_execution import AsyncCypherQueryExecutor, CypherWriteResultSummary
from pydantic import BaseModel

class NoParams(BaseModel): ...
class CreateMovieParams(BaseModel):
    title: str
    released: int

FIND_ALL = CypherQuery(
    query_id="async_simple_find_all_movies",
    cypher_template="MATCH (m:Movie) RETURN m.title AS title, m.released AS released ORDER BY m.title",
    params_schema=NoParams, identifiers_schema=NoIdentifiers,
)
CREATE = CypherQuery(
    query_id="async_simple_create_movie",
    cypher_template="CREATE (m:Movie {title: $title, released: $released})",
    params_schema=CreateMovieParams, identifiers_schema=NoIdentifiers,
)
```

Add two `@pytest.mark.neo4j` async tests (use `async_neo4j_driver`/`async_neo4j_clean`):

1. `test_async_simple_fetch_returns_raw_dicts` — `_seed` two movies; `executor =
   AsyncCypherQueryExecutor(async_neo4j_driver.session)`; `results: list[dict[str, Any]] = await
   executor.fetch(FIND_ALL, {})`; assert `{r["title"] for r in results} == {"The Matrix", "Speed"}`
   and `all(isinstance(r, dict) for r in results)`. **No `type: ignore`.**

2. `test_async_simple_execute_returns_summary` — `result: CypherWriteResultSummary = await
   executor.execute(CREATE, {"title": "Inception", "released": 2010})`; assert
   `isinstance(result, CypherWriteResultSummary)` and `result.nodes_created == 1`. **No `type: ignore`.**

Run: `python -m pytest -q --neo4j --neo4j-password <pw> tests/cypher/test_query_async_simple_e2e.py`
→ both pass. `python -m pytest -q tests/cypher/test_query_async_simple_e2e.py` → both skip cleanly.

**Acceptance gate:**
- [ ] `tests/cypher/test_query_async_simple_e2e.py` exists with the two tests, using
      `AsyncCypherQueryExecutor.fetch`/`.execute`.
- [ ] **No `# type: ignore`** anywhere in the file; `python -m mypy tests/cypher/test_query_async_simple_e2e.py` clean.
- [ ] Without `--neo4j`: skipped. With `--neo4j`: both pass.

---

### E62.6 — Add surface unit tests for `run_cypher_*` verbs

**Model:** Sonnet. **Type:** Code (tests). **Wave 2.** Depends on E62.2.

**Goal:** Cover the four public verbs without a live DB, mirroring the existing
`test_run_read_round_trips_typed_query` pattern in `tests/surface/test_execution.py` (which uses a
`FakeGraphSession`).

**What to do (in `tests/surface/test_execution.py`):**

Add tests after the typed-verb tests. Build a `CypherQuery` (simple path) + a `FakeGraphSession`
(reuse the same fake pattern the file already uses for typed verbs; import from
`tests/cypher/test_query_execution.py` or define a minimal local fake):

1. `test_run_cypher_fetch_returns_raw_rows` — `run_cypher_fetch(lambda: session, query, params)`
   returns the seeded `list[dict]`; assert the rows and that the statement ran with correct params.
2. `test_run_cypher_execute_returns_summary` — `run_cypher_execute(lambda: session, query, params)`
   returns a `CypherWriteResultSummary` with the expected counters.
3. `test_run_cypher_async_verbs_are_reexported` — assert `run_cypher_fetch_async` and
   `run_cypher_execute_async` are importable from `orthograph.execution`.

Import the verbs from `orthograph.execution`. **No `type: ignore`** — the verbs are typed on
`CypherQuery`.

**Acceptance gate:**
- [ ] Three new surface tests exist and pass: `python -m pytest -q tests/surface/test_execution.py`.
- [ ] No `# type: ignore` in the new tests; `python -m mypy tests/surface/test_execution.py` clean.

---

### E62.7 — Update docstring + PRD + overview + CONTEXT

**Model:** Haiku. **Type:** Docs. **Wave 3.** Depends on E62.1–E62.6.

**Goal:** Reflect that the simple path now has a dedicated, well-typed execution surface and E62 is
complete.

**What to do (verbatim edits):**

1. **`src/orthograph/cypher/query.py`** — replace the transitional "Type-checker boundary
   (transitional)" docstring bullet (added 2026-06-29, which references the `# type: ignore`) with:
   `"* **Execution surface.** Run a CypherQuery via "
   ":class:`~orthograph.cypher.query_execution.CypherQueryExecutor` (or "
   ":class:`~orthograph.cypher.query_execution.AsyncCypherQueryExecutor`), using ``fetch()`` "
   "for RETURN queries (``list[dict[str, Any]]``) and ``execute()`` for mutations "
   "(``CypherWriteResultSummary``); or the public ``run_cypher_fetch`` / ``run_cypher_execute`` "
   "verbs in ``orthograph.execution``. These are typed concretely on ``CypherQuery`` — no "
   "``# type: ignore`` is needed. The simple path is NOT passed to the typed ``CypherExecutor`` "
   "(use the typed path for that). The caller owns the transaction (ADR-028)."`
   (Use the E62.0 verb names if different from `fetch`/`execute`.)

2. **`.agentic/knowledge/product_requirements_document.md`** — if it mentions the simple-path
   execution, note that `CypherQuery` now executes via `CypherQueryExecutor` / `run_cypher_*` with
   full static typing (ADR-047 / E62). If there is no such mention, add a one-line note under the
   query-runner section. (If unsure, skip — this is a non-binding nicety.)

3. **`.agentic/planning/overview.md`** — change E62's status cell to
   `**done** (YYYY-MM-DD; ADR-047; CypherQueryExecutor/AsyncCypherQueryExecutor + run_cypher_* verbs;
   removed all simple-path type: ignore + the file-wide mypy disable; async simple-path e2e restored)`
   (insert the actual completion date).

4. **`.agentic/CONTEXT.md`** — the ADR-047 routing row already exists (added when the ADR was
   written). Verify it points to the right file; no change needed unless missing.

5. Run `python -m pytest -q` and `python -m mypy src/ tests/` once after doc edits — both clean.

**Acceptance gate:**
- [ ] `cypher/query.py` docstring describes the `CypherQueryExecutor` / `run_cypher_*` surface; the
      `# type: ignore` boundary note is gone.
- [ ] `overview.md` E62 row status is `done` with the completion date.
- [ ] `python -m pytest -q` passes; `python -m mypy src/ tests/` clean.

---

## Shared Reference

> Point any agent executing a single task at **this section + their task section only**.

### Decision authority
- **[ADR-047](../../decisions/047-simple-path-cypher-execution-surface.md)** — the binding
  decisions: (Q1) dedicated `CypherQueryExecutor`/`AsyncCypherQueryExecutor`; (Q2) `fetch`/`execute`
  named by return shape; (Q3) reuse `_validate_cypher` + `_summary_from_counters`; (Q4)
  Cypher-specific verbs, no loader; (Q5) remove all simple-path `type: ignore`.
- **[ADR-028](../../decisions/028-async-execution-and-caller-owned-transactions.md)** — the
  caller-owned transaction contract the new executors honour (never commit/rollback).

### Relevant files (verified 2026-06-29)

| File | Role |
|---|---|
| `src/orthograph/cypher/query_execution.py` | Has `CypherExecutor`, `AsyncCypherExecutor`, `CypherWriteResultSummary`, `_summary_from_counters`, `CypherExecutor._validate_cypher` (staticmethod). **E62.1 adds the two new executors here.** |
| `src/orthograph/cypher/query.py` | `CypherQuery(BaseModel)` — `params_schema`, `query_id`, `build(params)`, `materialize`, `interpret_result`, `backend=CYPHER`. **E62.7 edits the docstring.** |
| `src/orthograph/execution.py` | Public verbs `run_read`/`run_write`/`run_read_async`/`run_write_async`. **E62.2 adds `run_cypher_*` here.** |
| `tests/cypher/test_query_execution.py` | Sync executor unit tests + `FakeGraphSession`/`FakeWriteResult`/`FakeSummary`/`FakeCounters`. **E62.3 migrates 4 CypherQuery calls (removes 4 ignores).** |
| `tests/cypher/test_query_e2e.py` | Live-DB e2e; `_make_executor` + 8 CypherQuery calls; file-wide `# mypy: disable-error-code="arg-type"`. **E62.4 migrates + removes the disable.** |
| `tests/cypher/test_query_async_simple_e2e.py` | **New** (E62.5): async simple-path e2e on `AsyncCypherQueryExecutor`. |
| `tests/surface/test_execution.py` | Surface dispatch tests. **E62.6 adds `run_cypher_*` tests.** |
| `.agentic/decisions/047-...md` | E62.0 appends resolutions; E62.7 verifies. |
| `.agentic/planning/overview.md` | E62.7 updates the E62 row to done. |

### The simple-path contract (the heart of this epic)
- `CypherQuery` declares **no** Output model and makes **no** read/write distinction.
- It executes via `CypherQueryExecutor` / `AsyncCypherQueryExecutor` with two operations named for
  return shape: `fetch -> list[dict[str, Any]]`, `execute -> CypherWriteResultSummary`.
- These executors are **not** `Executor`/`AsyncExecutor` subclasses, take no generics, and are
  typed concretely on `CypherQuery` — so consumers need **no** `# type: ignore`.
- `CypherQuery` is **no longer** passed to the typed `CypherExecutor`/`AsyncCypherExecutor`.
- Caller owns the transaction (ADR-028): open the session via the factory, run the single built
  statement, never commit or roll back.

### The prologue every operation shares
```python
params = query.params_schema.model_validate(raw_params)
cypher, qparams = query.build(params)          # CypherQueryData unpacks as (cypher, params)
CypherExecutor._validate_cypher(cypher, query.query_id)   # reuse the staticmethod
```
Then sync I/O: `with self._driver_factory() as session: ...`; async I/O:
`async with self._driver_factory() as session: ... await session.run(...)`.
Write tail: `_summary_from_counters(result.consume().counters)` (sync) /
`_summary_from_counters((await result.consume()).counters)` (async).

### Verification commands
- mypy: `python -m mypy src/` and `python -m mypy tests/`
- Unit suite (no DB): `python -m pytest -q`
- Sync e2e (live DB): `python -m pytest -q --neo4j --neo4j-password <pw> tests/cypher/test_query_e2e.py`
- Async simple e2e (live DB): `python -m pytest -q --neo4j --neo4j-password <pw> tests/cypher/test_query_async_simple_e2e.py`
- The key success signal for the whole epic: **zero `# type: ignore[arg-type]` and zero
  `# mypy: disable-error-code` related to CypherQuery execution**, with mypy green.

### References
- ADR-047 (this epic's authority), ADR-028 (caller-owned tx), ADR-045 (query vocabulary),
  ADR-041 (root modules). E37 (simple CypherQuery + sync executor), E39 (async executor).

---

## Changelog

- **2026-06-29** — Epic created from the E39.9 review. The simple-path `CypherQuery` cannot be a
  subtype of `ReadQueryModel[P, D]` (its output is `dict`, `D` is `bound=BaseModel` and load-bearing
  in `generator.py`), forcing `# type: ignore[arg-type]` on every simple-path execution call — a
  contract violation for a consuming application. ADR-047 decides a dedicated, concretely-typed
  `CypherQueryExecutor`/`AsyncCypherQueryExecutor` pair with `fetch`/`execute` verbs + public
  `run_cypher_*` verbs, removing all simple-path suppressions. Tasks E62.0 (decision) through E62.7
  (docs); all Sonnet except E62.7 (Haiku). No Opus (no behaviour-change at the typed seam).
