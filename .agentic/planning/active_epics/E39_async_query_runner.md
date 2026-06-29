# Epic E39: Async Query Runner — `AsyncExecutor`, Universal Caller-Owned Transactions

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Status:** planned (independent of other active epics; tasks are sequenced internally)
> **Decision authority:** [ADR-028 — Async execution and universal caller-owned transactions](../../decisions/028-async-execution-and-caller-owned-transactions.md). Read ADR-028 before any task.
> **Relates to:** PRD Constraint 13 (Orthograph never owns a connection), PRD "Async driver support"
> (promoted from aspirational → supported for the query runner by ADR-028), ADR-021
> (`WriteResultSummary` protocol — refined, not reversed, by T1), and the planned MP-backend
> (`mp-backend`) consumer whose `app/db/transaction_context.py` owns the transaction boundary and
> yields a live `neo4j.AsyncTransaction | AsyncSession` to its repositories.
> **Carries the live Constraint-13 executor work** that the retired E10 (Connection Ownership Audit)
> never covered: E10's inspector subject was already delivered by E25/ADR-011 (D1, stateless
> `inspect(self, connection)`); the GQLAlchemy client is E9's; and the one genuine ownership breach —
> `CypherExecutor.write()` self-committing — is removed here in Wave 0 (T2). E10 was retired
> (2026-06-24) with no tasks migrated, because doing so would re-open work E25 settled.

---

## Why this epic exists

The typed query runner is synchronous. The planned consumer (MP backend) is async throughout and
runs inside FastAPI handlers, where a blocking DB call freezes the event loop. ADR-028 promotes
async from aspirational to supported **for the query runner only** (inspection stays sync) and, as
a prerequisite, removes transaction ownership from the executor so the caller owns commit/rollback
(matching MP and finally honouring Constraint 13).

This epic implements exactly ADR-028. It does **two** things, in order:

1. **Realign the existing sync write path to caller-owned transactions** (behaviour change,
   highest-risk — done first so the async path is built on the settled contract).
2. **Add the parallel async path** (`AsyncExecutor`, `AsyncCypherExecutor`, async ports, loader
   wiring, async API verbs) — purely additive.

---

## Reality Check (verified against the codebase before writing this epic — trust these over memory)

1. **`CypherExecutor` is the only `Executor` implementation.** Confirmed by grep: the only
   `class …(Executor)` is `CypherExecutor` in `src/orthograph/cypher/query_execution.py:55`.
2. **Transaction lifecycle appears in exactly one source file and three test functions.**
   `begin_transaction` / `commit` / `rollback` occur in `cypher/query_execution.py` (the sync
   `write()` body, lines ~116–131) and in test doubles/assertions in
   `tests/cypher/test_query_execution.py` and `tests/api/test_database.py`. No production code
   outside the library relies on the executor committing.
3. **The sync `write()` currently self-commits.** `cypher/query_execution.py` `write()` does
   `tx = session.begin_transaction()`, runs, `tx.commit()`, and on exception `tx.rollback()`. ADR-028
   removes this.
4. **`CypherWriteResultSummary.from_neo4j_result()` calls `result.consume()` synchronously**
   (`query_execution.py:46`). The async driver's `consume()` is a coroutine. T1 refactors this.
5. **`read()` does not commit and is correct as-is** — single statement, no explicit transaction
   (`query_execution.py:86–99`). Only the *async* read body is new; the sync read is untouched.
6. **No async anywhere in `src/`.** The only `await` tokens are in two docstring examples
   (`cypher/query.py:58`, `:220`). This is a greenfield addition, not a migration.
7. **Test stack is `pytest` + `pytest-mock`; no `pytest-asyncio`.** `pyproject.toml` `dev` deps
   (lines 84–86) and `[tool.pytest.ini_options]` (lines 121–128) have markers `slow`/`neo4j`/`memgraph`
   and `addopts = "-v --strict-markers --tb=short --nbval-lax"`. No `asyncio_mode`.
8. **The query-definition layer does NOT change.** `ReadQuery`/`WriteQuery`/`CypherReadQuery`/
   `CypherWriteQuery`, `build()`, `materialize()`, `interpret_result()`, `CypherQueryData`,
   identifiers — all reused unchanged (ADR-028 Decision 2).
9. **`FakeGraphSession` is duplicated** in `tests/cypher/test_query_execution.py` (lines 106–144) and
   `tests/api/test_database.py` (lines 193–221), with `FakeTransaction`/`FakeCounters`/`FakeSummary`/
   `FakeWriteResult`. T6 adds async fakes; consolidation is **out of scope** here (keep diffs narrow).
10. **Inspection is out of scope.** Do not touch `graph_profile/`, `backends/*/inspector.py`,
    `api.database.inspect` / `validate`.

---

## Scope

**In scope:**
- Remove transaction ownership from sync `CypherExecutor.write()` (caller-owned).
- Refactor `CypherWriteResultSummary` construction so `consume()` is called by the executor (T1),
  enabling reuse on the async path.
- New async contracts: `AsyncExecutor`, `AsyncReadPort`, `AsyncQueryBackedReadPort`.
- New `AsyncCypherExecutor` (caller-owned; never commits).
- Loader wiring: `load_async_executor`.
- Async API verbs: `query_async`, `execute_async`.
- `pytest-asyncio` + `asyncio_mode`, async test doubles, async tests, and updates to the sync
  write tests for the new caller-owned behaviour.

**Out of scope:**
- Async inspection / `validate` (deferred — ADR-028 Decision 3).
- A convenience auto-commit wrapper for standalone writes (deferred — YAGNI).
- Consolidating the duplicated `FakeGraphSession` (keep diffs minimal).
- Any change to the query-definition layer or to `QueryCatalogue`.

---

## How to use this epic (execution protocol)

Tasks are **sequential within their wave**. Do not start T(n+1) until T(n) passes its acceptance
gate, unless the Task Map marks them parallel. Each task is **self-contained**: a low-context agent
completes it by reading **only** (a) that task's section and (b) the **Shared Reference** at the
bottom. Each task states its exact files, the change, a binary acceptance gate, and the **model**
it is sized for.

**Model sizing legend:**
- **Haiku** — fully mechanical; every edit is spelled out verbatim. No design judgement.
- **Sonnet** — scoped implementation; a concrete pattern exists to mirror (the sync code or the MP
  reference). Most tasks.
- **Opus** — cross-file behaviour-change reasoning with real blast-radius risk. Used sparingly.

---

## Task Map (dependency order)

```
WAVE 0 — settle the sync contract first (behaviour change; highest risk)
T1  Refactor CypherWriteResultSummary consume() seam          [Sonnet]  ← unblocks T2, T5
T2  Remove transaction ownership from sync write()            [OPUS]    ← unblocks T3
T3  Update sync write tests for caller-owned behaviour        [Sonnet]  ← gates Wave 1

WAVE 1 — add the async path (purely additive; depends on Wave 0)
T4  Add async ABCs (AsyncExecutor / AsyncReadPort / port)     [Sonnet]  ← unblocks T5
T5  Implement AsyncCypherExecutor                             [Sonnet]  ← unblocks T6,T7,T8
T6  Add pytest-asyncio + AsyncFakeGraphSession + executor tests [Sonnet]
T7  Wire loader: load_async_executor                          [Sonnet]  ← unblocks T8
T8  Add async API verbs query_async / execute_async + tests   [Sonnet]
T9  Update PRD + planning overview                            [Haiku]
```

- **T1 → T2 → T3** strictly sequential (Wave 0). T3 must be green before Wave 1.
- **T4 → T5** sequential. **T6, T7** depend on T5 and may run in parallel. **T8** depends on T7.
- **T9** last (docs).
- **T2 is the only Opus task** — it changes tested behaviour across the executor and is the one
  place a wrong edit silently breaks transactional safety.

---

## Tasks

### T1 — Refactor `CypherWriteResultSummary` so the executor calls `consume()`

**Model:** Sonnet. **Type:** Code (source). **Wave 0.** No dependencies.

**Goal:** Make summary construction reusable by both sync and async executors by moving the
`result.consume()` call out of the summary classmethod and into the executor. ADR-028 Decision 3
(refines ADR-021, does not reverse it: summary stays structured and vendor-free).

**What to do (in `src/orthograph/cypher/query_execution.py`):**

1. Add a module-level helper that builds the summary from already-extracted counters:
   ```python
   def _summary_from_counters(counters: Any) -> "CypherWriteResultSummary":
       """Build a CypherWriteResultSummary from a neo4j SummaryCounters-shaped object.

       The caller (sync or async executor) is responsible for having already consumed
       the driver result; this helper only reads the five mutation counters.
       """
       return CypherWriteResultSummary(
           nodes_created=counters.nodes_created,
           nodes_deleted=counters.nodes_deleted,
           relationships_created=counters.relationships_created,
           relationships_deleted=counters.relationships_deleted,
           properties_set=counters.properties_set,
       )
   ```
2. Keep `CypherWriteResultSummary.from_neo4j_result` **for now** but reimplement its body to delegate:
   `return _summary_from_counters(result.consume().counters)`. (This keeps the sync executor and any
   existing callers/tests working; T2 will switch the sync executor to call `consume()` itself.)
3. Do **not** change the dataclass fields or the `WriteResultSummary` protocol. Do not touch async
   anything (no async in this task).
4. Run `python -m pytest -q tests/cypher/test_query_execution.py` — must stay green.

**Acceptance gate:**
- [ ] `_summary_from_counters(counters)` exists and returns a `CypherWriteResultSummary`.
- [ ] `from_neo4j_result` now delegates to `_summary_from_counters` (no behaviour change).
- [ ] `python -m pytest -q tests/cypher/test_query_execution.py` passes unchanged.
- [ ] No async code added; no other file changed.

---

### T2 — Remove transaction ownership from sync `CypherExecutor.write()`

**Model:** OPUS. **Type:** Code (source — behaviour change). **Wave 0.** Depends on T1.

**Why Opus:** this changes tested behaviour at the single I/O seam. A wrong edit silently breaks
transactional safety (the exact failure mode ADR-028 exists to prevent). It requires reasoning about
what the caller's session/transaction object now guarantees and reconciling the docstrings, the
`read()`/`write()` asymmetry, and the rollback-on-error semantics in one coherent change.

**Goal:** After this task, `write()` runs the validated statement against the object the factory
yields and returns `interpret_result(summary)`. It does **not** call `begin_transaction()`,
`commit()`, or `rollback()`. The caller owns the transaction boundary (ADR-028 Decision 1).

**What to do (in `src/orthograph/cypher/query_execution.py`):**

1. Rewrite `CypherExecutor.write()` so that, inside `with self._driver_factory() as session:`, it:
   - runs the statement directly on `session`: `result = session.run(cypher, **qparams)`;
   - builds the summary by calling `consume()` itself and using the T1 helper:
     `summary = _summary_from_counters(result.consume().counters)`;
   - returns `query.interpret_result(summary)`.
   - **Remove** the `begin_transaction()` / `tx.run()` / `tx.commit()` / `tx.rollback()` /
     `try/except BaseException` block. The executor performs no commit and no rollback.
2. Keep all pre-I/O steps identical: `Params.model_validate`, `query.build(params)`,
   `_validate_cypher(cypher, query.name)`. Reads (`read()`) are **unchanged**.
3. Update the module docstring (top of file, line ~7) from
   `"read() does not commit; write() commits."` to:
   `"Neither read() nor write() commits or rolls back — the caller owns the transaction boundary
   (ADR-028). The factory yields the session or live transaction to run against."`
   Update the `write()` method docstring similarly (remove the "→ commit" language; state that the
   caller commits and that rows from `RETURN` are still discarded — write results come from the
   counters via `interpret_result`).
4. Note the consequence for callers: passing `driver.session` (a session context manager whose exit
   commits in neo4j auto-commit mode) still persists a single statement; passing a transaction
   context means the caller commits. Do not add any convenience wrapper (out of scope).
5. Run `python -m pytest -q tests/cypher/test_query_execution.py tests/api/test_database.py`.
   Tests asserting the executor committed will now FAIL — that is expected; T3 updates them. Confirm
   the **only** failures are the commit-assertion tests listed in T3 (no unexpected breakage).

**Acceptance gate:**
- [ ] `CypherExecutor.write()` contains no `begin_transaction`, `commit`, or `rollback` call.
- [ ] `write()` builds the summary via `_summary_from_counters(result.consume().counters)` and
      returns `interpret_result(summary)`.
- [ ] `read()` is unchanged; pre-I/O validation/build/parse steps are unchanged.
- [ ] Module + method docstrings state the caller-owned-transaction contract (ADR-028).
- [ ] After this task, the only failing tests are exactly the three commit-assertion tests T3 will
      fix (`test_write_commits_transaction`, `test_cypher_query_write_adapter_commits_transaction`,
      and the `execute` commit assertions in `test_database.py`). No other test newly fails.

---

### T3 — Update sync write tests for caller-owned behaviour

**Model:** Sonnet. **Type:** Code (tests). **Wave 0.** Depends on T2.

**Goal:** Bring the three commit-asserting tests in line with ADR-028: the executor must now be shown
to run the statement and **not** commit. The fakes keep their `committed`/`rolled_back` flags so the
tests can prove the executor leaves them `False`.

**What to do:**

1. `tests/cypher/test_query_execution.py`:
   - `test_write_commits_transaction` (≈ line 220): rename to `test_write_does_not_commit_caller_owns_tx`.
     Keep the run-call assertions (statement ran, params correct). Change `assert session.committed is True`
     to `assert session.committed is False` and keep `assert session.rolled_back is False`. Update the
     docstring to "write() runs the statement but does NOT commit — the caller owns the transaction
     (ADR-028)."
   - `test_cypher_query_write_adapter_commits_transaction` (≈ line 461): same treatment — rename to
     `…_does_not_commit`, assert `committed is False`, `rolled_back is False`, keep the run assertion.
   - The `FakeGraphSession`/`FakeTransaction` doubles may keep `begin_transaction`/`commit`/`rollback`
     for now (harmless; the executor no longer calls them). Do not delete them — `test_database.py`
     copies are separate and other tests may construct them.
2. `tests/api/test_database.py`:
   - `test_execute_dispatches_to_cypher_executor` (≈ line 247): keep `assert result == 1`; change
     `assert session.committed is True` to `assert session.committed is False`; keep
     `assert session.rolled_back is False`. Update any inline comment to reference caller-owned tx.
3. Run `python -m pytest -q` (no flags). Entire suite must be green.

**Acceptance gate:**
- [ ] The three tests assert the executor did **not** commit (`committed is False`) and did not roll
      back, while still asserting the statement ran with the correct cypher/params.
- [ ] `python -m pytest -q` (no flags) passes with the same collected test count as before T3.
- [ ] No `src/` change in this task.

---

### T4 — Add the async contracts (`AsyncExecutor`, `AsyncReadPort`, `AsyncQueryBackedReadPort`)

**Model:** Sonnet. **Type:** Code (source — additive). **Wave 1.** Depends on T3 (Wave 0 green).

**Goal:** Add the async ABCs alongside the sync ones, mirroring their shape (ADR-028 Decision 2).
Purely additive — do not modify the existing `Executor`/`ReadPort`/`QueryBackedReadPort` except
docstrings already updated in T2.

**What to do (in `src/orthograph/query/base_models.py`):**

1. After the existing `Executor` ABC, add:
   ```python
   class AsyncExecutor(ABC):
       """Async counterpart of Executor. Same contract, awaited.

       Like Executor, it NEVER commits or rolls back — the caller owns the transaction
       boundary (ADR-028). Implementations receive an async factory and open/close the
       session (or use a caller-supplied live transaction) per call.
       """

       @abstractmethod
       async def read(self, query: ReadQuery[P, D], raw_params: Any) -> list[D]:
           """Validate params → build() (pure) → execute → materialize. No commit."""

       @abstractmethod
       async def write(self, query: WriteQuery[P, R], raw_params: Any) -> R:
           """Validate params → build() (pure) → execute → interpret_result. No commit."""
   ```
2. After `QueryBackedReadPort`, add the async port pair, mirroring the sync ones:
   ```python
   class AsyncReadPort(ABC, Generic[P, D]):
       """Async named read capability. Async counterpart of ReadPort."""

       @abstractmethod
       async def fetch(self, params: P) -> list[D]: ...


   class AsyncQueryBackedReadPort(AsyncReadPort[P, D]):
       """An AsyncReadPort backed by a ReadQuery + AsyncExecutor pair."""

       def __init__(self, query: ReadQuery[P, D], executor: AsyncExecutor) -> None:
           self._query = query
           self._executor = executor

       async def fetch(self, params: P) -> list[D]:
           return await self._executor.read(self._query, params)
   ```
3. Reuse the existing `P`, `D`, `R` TypeVars and `ReadQuery`/`WriteQuery` — no new query types.
4. `python -c "from orthograph.query.base_models import AsyncExecutor, AsyncReadPort, AsyncQueryBackedReadPort"`
   must succeed. Run `python -m pytest -q` — still green.

**Acceptance gate:**
- [ ] `AsyncExecutor`, `AsyncReadPort`, `AsyncQueryBackedReadPort` exist and import cleanly.
- [ ] Their docstrings state "no commit — caller owns the transaction (ADR-028)".
- [ ] The sync `Executor`/`ReadPort`/`QueryBackedReadPort` are unchanged (apart from T2 docstrings).
- [ ] `python -m pytest -q` passes.

---

### T5 — Implement `AsyncCypherExecutor`

**Model:** Sonnet. **Type:** Code (source — additive). **Wave 1.** Depends on T4 and T1.

**Goal:** Add the concrete async executor, mirroring the (now caller-owned) sync `CypherExecutor`,
using the neo4j async driver idioms. It never commits or rolls back.

**Reference for the async idioms (from the MP backend, verified):** `await session.run(cypher, **params)`
returns an async result; records are read with `async for` or `await result.single()`; counters via
`await result.consume()`; the session/transaction is an **async** context manager (`async with`).
MP's repos accept `AsyncTransaction | AsyncSession` and only call `run()` — they never commit (the
service's `transaction_context` does). Mirror that.

**What to do (in `src/orthograph/cypher/query_execution.py`):**

1. Add `from typing import AsyncContextManager` (or `from contextlib import AbstractAsyncContextManager`)
   as needed; import `AsyncExecutor` from `query.base_models`.
2. Add the class, mirroring `CypherExecutor` but async, factory typed as
   `Callable[[], Any]` (the yielded object is an `AsyncSession` or live `AsyncTransaction` — any
   object exposing async `run`/`consume`; keep `Any` to stay vendor-free, matching how the sync
   executor types its factory):
   ```python
   class AsyncCypherExecutor(AsyncExecutor):
       """Async Executor for graph databases. Caller owns the transaction (ADR-028).

       Accepts an async factory yielding an async session or a live AsyncTransaction
       (anything with `async run()`); it runs the statement and NEVER commits/rolls back.

       Example (neo4j async, auto-commit read/write via a session):
           AsyncCypherExecutor(lambda: driver.session())
       Example (caller-owned transaction, e.g. MP transaction_context):
           AsyncCypherExecutor(lambda: live_async_tx)   # factory returns the live tx
       """

       def __init__(self, driver_factory: Callable[[], Any]) -> None:
           self._driver_factory = driver_factory

       async def read(self, query: ReadQuery[P, D], raw_params: Any) -> list[D]:
           params = cast(P, query.Params.model_validate(raw_params))
           cypher, qparams = query.build(params)
           CypherExecutor._validate_cypher(cypher, query.name)  # reuse the pure check
           async with self._driver_factory() as session:
               result = await session.run(cypher, **qparams)
               records = [dict(rec) async for rec in result]
           return [query.materialize(rec) for rec in records]

       async def write(self, query: WriteQuery[P, R], raw_params: Any) -> R:
           params = cast(P, query.Params.model_validate(raw_params))
           cypher, qparams = query.build(params)
           CypherExecutor._validate_cypher(cypher, query.name)
           async with self._driver_factory() as session:
               result = await session.run(cypher, **qparams)
               summary = _summary_from_counters((await result.consume()).counters)
           return query.interpret_result(summary)
   ```
   Notes: `materialize()` is called **after** the `async with` block on a plain list — it stays sync
   and pure (ADR-028). No `begin_transaction`, no `commit`, no `rollback`.
3. The async executor accepts `CypherQuery` and typed queries directly (adapters removed by E60);
   all expose `params_schema`/`query_id` and `build(params)` uniformly.
4. `python -c "from orthograph.cypher.query_execution import AsyncCypherExecutor"` must succeed.
   Run `python -m pytest -q` — still green (no async tests yet; T6 adds them).

**Acceptance gate:**
- [ ] `AsyncCypherExecutor(AsyncExecutor)` exists with `async def read` and `async def write`.
- [ ] It uses `async with` for the session, `await session.run`, `async for` to collect records,
      and `await result.consume()` for counters via `_summary_from_counters`.
- [ ] It contains no `commit` / `rollback` / `begin_transaction`.
- [ ] `materialize()` is called outside the `async with` block (sync, on a collected list).
- [ ] Imports cleanly; `python -m pytest -q` passes.

---

### T6 — Add `pytest-asyncio`, `AsyncFakeGraphSession`, and async executor tests

**Model:** Sonnet. **Type:** Code (deps + tests). **Wave 1.** Depends on T5. May run parallel with T7.

**Goal:** Enable async testing and prove `AsyncCypherExecutor` reads, writes, validates params before
running, and never commits.

**What to do:**

1. `pyproject.toml`:
   - Add `"pytest-asyncio>=0.23"` to the `dev` dependency list (next to `pytest-mock`).
   - In `[tool.pytest.ini_options]`, add `asyncio_mode = "auto"` (so `async def test_*` run without a
     per-test marker). Leave `addopts` and `markers` unchanged.
   - Install: `pip install -e ".[dev]"` (or note that CI will).
2. In `tests/cypher/test_query_execution.py`, add an **async** fake near the existing sync fakes (do
   NOT remove the sync ones; do NOT consolidate — out of scope):
   ```python
   class AsyncFakeResult:
       def __init__(self, records, counters=None):
           self._records = records or []
           self._counters = counters
       def __aiter__(self):
           async def gen():
               for r in self._records:
                   yield r
           return gen()
       async def consume(self):
           @dataclass
           class _S:
               counters: Any
           return _S(counters=self._counters)

   class AsyncFakeGraphSession:
       """Async stand-in: async context manager + `async run()`. Records calls.
       NEVER auto-commits (the caller owns the tx); exposes `committed` defaulting False
       so tests can assert the executor never set it."""
       def __init__(self, records=None, counters=None):
           self._records = records or []
           self._counters = counters
           self.run_calls: list[tuple[str, dict[str, Any]]] = []
           self.committed = False
       async def __aenter__(self): return self
       async def __aexit__(self, *exc): return None
       async def run(self, cypher: str, **params: Any):
           self.run_calls.append((cypher, params))
           return AsyncFakeResult(self._records, self._counters)
   ```
   (Reuse the existing `FakeCounters` dataclass for `counters=FakeCounters(nodes_created=1)`.)
3. Add async tests mirroring the sync ones (with `asyncio_mode=auto`, just write `async def`):
   - `test_async_read_materialises_records` — read returns declared `Movie` instances from records
     (reuse `MoviesByYearCypher`, `Movie`, `ReleasedYearParams` already defined in the file).
   - `test_async_read_passes_built_cypher_and_params` — asserts the run-call cypher/params.
   - `test_async_read_bad_params_raise_before_run` — invalid params raise; `run_calls == []`.
   - `test_async_write_returns_interpreted_result` — write returns `interpret_result` of the counters
     (reuse `CreateMovieCypher`); assert `result == 1`.
   - `test_async_write_does_not_commit_caller_owns_tx` — `session.committed is False` after write.
4. Run `python -m pytest -q` — all green, including the new async tests.

**Acceptance gate:**
- [ ] `pytest-asyncio` is in `dev` deps and `asyncio_mode = "auto"` is set.
- [ ] `AsyncFakeGraphSession` (async CM + `async run`) and `AsyncFakeResult` exist in the cypher test
      file; the existing sync fakes are untouched.
- [ ] The five async executor tests above exist and pass.
- [ ] `python -m pytest -q` passes; sync test count unchanged from after T3.

---

### T7 — Wire the loader: `load_async_executor`

**Model:** Sonnet. **Type:** Code (source — additive). **Wave 1.** Depends on T5. May run parallel with T6.

**Goal:** Let the public API resolve an async executor by backend name, mirroring `load_executor`,
with the same dependency checks and the same actionable error messages.

**What to do (in `src/orthograph/backends/loader.py`):**

1. Add a deferred-import thunk mirroring `_cypher_executor`:
   ```python
   def _async_cypher_executor() -> ExecutorClass:
       from orthograph.cypher.query_execution import AsyncCypherExecutor
       return AsyncCypherExecutor
   ```
   (The `ExecutorClass` Protocol — `__call__(driver_factory) -> Executor` — fits structurally; the
   async executor is also constructed with a single factory. Keep the same Protocol; do not add an
   async-specific protocol — the construction shape is identical.)
2. Add an `async_executor: Callable[[], ExecutorClass] | None = None` field to `BackendSpec` (default
   `None`).
3. In `_BACKENDS`, set `async_executor=_async_cypher_executor` for `"neo4j"`, `"memgraph"`, and
   `"cypher"`. Leave `"networkx"` and `"gqlalchemy"` with `async_executor=None`. Keep
   `gqlalchemy`'s `deferred_executor_reason` as-is.
4. Add `load_async_executor(name)` mirroring `load_executor` exactly, but reading `spec.async_executor`:
   - same `deferred_executor_reason` handling for gqlalchemy;
   - same "Unknown execution backend …" message when the name is unknown or `async_executor is None`;
   - same `require(name)` dependency check before returning.
5. Verify:
   ```
   python -c "from orthograph.backends.loader import load_async_executor; print(load_async_executor('neo4j').__name__)"
   ```
   prints `AsyncCypherExecutor`. Run `python -m pytest -q tests/backends/test_loader.py` — and if it
   has sync-executor cases, add parallel async-executor cases (unknown backend raises; gqlalchemy
   raises the deferred message; networkx has no async executor).

**Acceptance gate:**
- [ ] `_async_cypher_executor` thunk and `BackendSpec.async_executor` field exist.
- [ ] `neo4j`/`memgraph`/`cypher` map to the async executor; `networkx`/`gqlalchemy` do not.
- [ ] `load_async_executor("neo4j")` returns `AsyncCypherExecutor`; unknown names and `gqlalchemy`
      raise `MissingDependencyError` with the same messages as `load_executor`.
- [ ] `python -m pytest -q` passes (incl. any added loader tests).

---

### T8 — Add async API verbs `query_async` / `execute_async` + tests

**Model:** Sonnet. **Type:** Code (source + tests — additive). **Wave 1.** Depends on T7 (and T6 fakes).

**Goal:** Expose the async path through the public API, mirroring the sync `query`/`execute`.

**What to do:**

1. In `src/orthograph/api/database.py`, after the sync `query` and `execute`, add:
   ```python
   async def query_async(
       backend: str,
       connection_factory: Callable[[], Any],
       read_query: ReadQuery[P, D],
       params: Any,
   ) -> list[D]:
       """Async: execute a typed read query against ``backend``; return ``list[Output]``.

       The caller owns the transaction boundary (ADR-028); ``connection_factory`` yields
       an async session or a live async transaction.
       """
       executor_cls = loader.load_async_executor(name=backend)
       return await executor_cls(connection_factory).read(query=read_query, raw_params=params)

   async def execute_async(
       backend: str,
       connection_factory: Callable[[], Any],
       write_query: WriteQuery[P, R],
       params: Any,
   ) -> R:
       """Async: execute a typed write query against ``backend``; return the result.

       Does not commit — the caller owns the transaction boundary (ADR-028).
       """
       executor_cls = loader.load_async_executor(name=backend)
       return await executor_cls(connection_factory).write(query=write_query, raw_params=params)
   ```
   Update the module docstring's verb list to mention `query_async` / `execute_async` as the async
   counterparts (one line each).
2. In `tests/api/test_database.py`, add async tests mirroring the sync dispatch tests, using the
   `AsyncFakeGraphSession` from T6 (import it, or define a local async fake if cross-file import is
   awkward — a local copy is acceptable here since the sync fakes are already duplicated in this file):
   - `test_query_async_dispatches_to_async_cypher_executor` — returns materialised `Movie`s.
   - `test_execute_async_dispatches_to_async_cypher_executor` — returns `1`; `session.committed is False`.
   - `test_query_async_unknown_backend_raises` — `query_async("nonsense", …)` raises
     `MissingDependencyError` ("Unknown execution backend").
   - `test_query_async_gqlalchemy_raises` — raises the deferred `ValidatedQueryBuilder` message.
3. Run `python -m pytest -q` — all green.

**Acceptance gate:**
- [ ] `query_async` and `execute_async` exist with the signatures above and load via
      `load_async_executor`.
- [ ] `execute_async` does not commit (proven by `committed is False` in the test).
- [ ] The four async API tests exist and pass; error-path messages match the sync verbs'.
- [ ] `python -m pytest -q` passes.

---

### T9 — Update PRD and planning overview

**Model:** Haiku. **Type:** Docs. **Wave 1.** Depends on T8.

**Goal:** Reflect that async is now supported for the query runner (inspection still deferred) and
that E39 is complete.

**What to do (verbatim edits):**

1. `.agentic/knowledge/product_requirements_document.md`:
   - In the "Out of Scope" table, change the "Async driver support" row's rationale to:
     `"Query runner: SUPPORTED (async execution via AsyncExecutor / query_async / execute_async under
     caller-owned transactions — ADR-028). Async inspection (inspect/validate) remains deferred until
     a concrete use case."`
   - In "Aspirational Direction", update the "Async execution" bullet to note the query-runner portion
     is now delivered (ADR-028 / E39); inspection remains aspirational.
2. `.agentic/planning/overview.md`:
   - Add a row to the Epics table:
     `| E39 | Async Query Runner — AsyncExecutor & Caller-Owned Transactions | High | <status> |`
   - In the "Deferred (not this phase)" table, update the "Async driver support" row to
     `"Query runner delivered (E39 / ADR-028); async inspection deferred."`
   - Add `E39` to the active epic-files list:
     `- [E39 — Async Query Runner](active_epics/E39_async_query_runner.md)`
3. No code changed. Run `python -m pytest -q` once to confirm still green after doc edits.

**Acceptance gate:**
- [ ] PRD "Out of Scope" + "Aspirational Direction" reflect query-runner async delivered, inspection
      deferred, citing ADR-028.
- [ ] `overview.md` has the E39 row, the updated Deferred row, and the active epic-file link.
- [ ] `python -m pytest -q` passes.

---

## Shared Reference

> Point any agent executing a single task at **this section + their task section only**.

### Decision authority
- **[ADR-028](../../decisions/028-async-execution-and-caller-owned-transactions.md)** — the binding
  decisions: (1) caller-owned transactions (sync + async); (2) parallel `Executor`/`AsyncExecutor`
  hierarchies (not overloads/merged protocol); (3) scope = query runner only, ADR-021 consume()
  refinement.
- **[ADR-021](../../decisions/021-write-result-summary-protocol-vendor-free-layer.md)** — the
  `WriteResultSummary` protocol; T1 refines (does not reverse) it.

### Relevant files (verified paths)

| File | Role |
|---|---|
| `src/orthograph/cypher/query_execution.py` | Sync `CypherExecutor` (the I/O seam); `CypherWriteResultSummary`. T1/T2 edit; T5 adds `AsyncCypherExecutor` here. |
| `src/orthograph/query/base_models.py` | `Executor`/`ReadQuery`/`WriteQuery`/`ReadPort`/`QueryBackedReadPort` ABCs + `P`/`D`/`R` TypeVars. T4 adds async ABCs here. |
| `src/orthograph/backends/loader.py` | `BackendSpec`, `_BACKENDS`, `load_executor`, `ExecutorClass` Protocol. T7 adds `load_async_executor`. |
| `src/orthograph/api/database.py` | Public verbs `inspect`/`validate`/`query`/`execute`. T8 adds `query_async`/`execute_async`. |
| `tests/cypher/test_query_execution.py` | Sync executor tests + `FakeGraphSession`/`FakeTransaction`/`FakeCounters`/`FakeSummary`/`FakeWriteResult`. T3 edits commit tests; T6 adds async fakes + tests. |
| `tests/api/test_database.py` | API dispatch tests + a second copy of the fakes. T3 edits the execute commit test; T8 adds async API tests. |
| `tests/backends/test_loader.py` | Loader tests. T7 adds async cases if sync cases exist. |
| `pyproject.toml` | `dev` deps + `[tool.pytest.ini_options]`. T6 adds `pytest-asyncio` + `asyncio_mode`. |
| `.agentic/knowledge/product_requirements_document.md` | T9 updates Out-of-Scope + Aspirational. |
| `.agentic/planning/overview.md` | T9 updates epic table + Deferred. |

### The caller-owned transaction contract (ADR-028 Decision 1 — the heart of this epic)

- The executor (sync AND async) **never** calls `begin_transaction` / `commit` / `rollback`.
- It runs the validated statement against whatever the factory yields and returns the
  materialised list (`read`) or `interpret_result(summary)` (`write`).
- The caller owns when the unit of work commits — exactly like MP's `transaction_context`, which
  opens the `AsyncTransaction`, yields it live to repos, and commits/rolls back both Postgres and
  Neo4j together.
- Reads were never committing; only `write()`'s self-commit is removed.

### The async idioms (verified against MP `app/repos/protocol_neo4j_repo.py` + `app/db/`)

- Session/transaction is an **async context manager**: `async with factory() as session:`.
- `result = await session.run(cypher, **params)`.
- Iterate records: `[dict(rec) async for rec in result]`. Single row: `await result.single()`.
- Counters (write): `(await result.consume()).counters` → `_summary_from_counters(...)`.
- Repos accept `AsyncTransaction | AsyncSession` and only call `run()`; they never commit.

### The colour rule (why parallel hierarchies — ADR-028 Decision 2)

`async def` is consumed only with `await`; sync callers cannot `await`; an async caller that calls a
blocking sync function freezes the event loop. Sync and async cannot be one method. Hence two ABCs,
two executors, two ports — the duplication is intentional and honest. The query-definition layer
(`build`/`materialize`/`interpret_result`/`CypherQueryData`) is colour-neutral and shared unchanged.

### Verification commands

- Unit suite (no DB): `python -m pytest -q`
- Targeted: `python -m pytest -q tests/cypher/test_query_execution.py tests/api/test_database.py tests/backends/test_loader.py`
- Import smoke checks are listed inside each task's gate.

### References
- ADR-028 (this epic's authority); ADR-021 (refined by T1); PRD Constraint 13.
- MP reference (read-only, do not modify): `D:\software_development\04_external\D4SP\MP\mp-backend\app\repos\protocol_neo4j_repo.py`, `app\db\transaction_context.py`, `app\db\async_neo4j_pool.py`.

---

## Changelog

- **2026-06-18** — Epic created from ADR-028. Codebase verified: `CypherExecutor` is the sole
  `Executor`; transaction lifecycle confined to one source file + three tests; no async in `src/`;
  test stack lacks `pytest-asyncio`. Scope fixed to the query runner (inspection deferred). Tasks
  sized: T2 = Opus (behaviour change at the I/O seam), T9 = Haiku (mechanical docs), rest = Sonnet.
