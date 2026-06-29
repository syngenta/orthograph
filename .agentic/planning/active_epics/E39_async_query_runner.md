# Epic E39: Async Query Runner — `AsyncExecutor`, Universal Caller-Owned Transactions

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Status:** planned (independent of other active epics; tasks are sequenced internally)
> **Decision authority:** [ADR-028 — Async execution and universal caller-owned transactions](../../decisions/028-async-execution-and-caller-owned-transactions.md). Read ADR-028 before any task.
> **Relates to:** PRD Constraint 13 (Orthograph never owns a connection), PRD "Async driver support"
> (promoted from aspirational → supported for the query runner by ADR-028), ADR-021
> (`WriteResultSummary` protocol — refined, not reversed, by E39.1), and the planned MP-backend
> (`mp-backend`) consumer whose `app/db/transaction_context.py` owns the transaction boundary and
> yields a live `neo4j.AsyncTransaction | AsyncSession` to its repositories.
> **Carries the live Constraint-13 executor work** that the retired E10 (Connection Ownership Audit)
> never covered: E10's inspector subject was already delivered by E25/ADR-011 (D1, stateless
> `inspect(self, connection)`); the GQLAlchemy client is E9's; and the one genuine ownership breach —
> `CypherExecutor.write()` self-committing — is removed here in Wave 0 (E39.2). E10 was retired
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

## Reality Check (verified 2026-06-18, **re-targeted 2026-06-29** after E55/E56/E59/E60 landed)

> **Note (2026-06-29 re-target):** E60 (ADR-045) explicitly promised that task E60.5 would
> re-target this epic file. E60 was marked done (overview line 89) but E60.5 did not execute.
> This re-target corrects all stale references. Symbol changes: `ReadQuery`→`ReadQueryModel`,
> `WriteQuery`→`WriteQueryModel`, `CypherReadQuery`→`TypedCypherReadQueryModel`,
> `CypherWriteQuery`→`TypedCypherWriteQueryModel`, `query.Params`→`query.params_schema`,
> `query.name`→`query.query_id`. E55 (ADR-041) removed `api/database.py`; the public execution
> verbs now live in `src/orthograph/execution.py` as `run_read`/`run_write`. E56 (ADR-042)
> extracted a shared `_prepare_statement` prologue in `CypherExecutor`. E60 (ADR-045 Q4 Option A)
> deleted all adapters; `CypherQuery` is now directly executable with `build(params)`.
> The registry wiring (`BackendSpec`, `BACKENDS`, `ExecutorClass`) moved from `loader.py` into
> `src/orthograph/backends/registry.py`. ADR-028's three decisions are unchanged.

1. **`CypherExecutor` is the only `Executor` implementation.** Confirmed by grep: the only
   `class …(Executor)` is `CypherExecutor` in `src/orthograph/cypher/query_execution.py:60`.
2. **Transaction lifecycle appears in exactly one source file and three test functions.**
   `begin_transaction` / `commit` / `rollback` occur in `cypher/query_execution.py` (the sync
   `write()` body, lines ~134–148) and in test doubles/assertions in:
   - `tests/cypher/test_query_execution.py`: `test_write_commits_transaction` (line ~224),
     `test_cypher_query_write_commits_transaction` (line ~448).
   - `tests/surface/test_execution.py`: `test_run_write_returns_interpreted_result` (line ~186).
   No production code outside the library relies on the executor committing.
3. **The sync `write()` currently self-commits.** `cypher/query_execution.py` `write()` does
   `tx = session.begin_transaction()`, runs, `tx.commit()`, and on exception `tx.rollback()`. ADR-028
   removes this.
4. **`CypherWriteResultSummary.from_neo4j_result()` calls `result.consume()` synchronously**
   (`query_execution.py:50`). The async driver's `consume()` is a coroutine. E39.1 refactors this.
5. **`read()` does not commit and is correct as-is** — uses `_prepare_statement` prologue then
   `session.run()` with no explicit transaction (`query_execution.py:107–118`). Only the *async*
   read body is new; the sync read is untouched.
6. **No async anywhere in `src/`.** The only `await` tokens are in two docstring examples
   (`cypher/query.py:58`, `:220`). This is a greenfield addition, not a migration.
7. **Test stack is `pytest` + `pytest-mock`; no `pytest-asyncio`.** `pyproject.toml` `dev` deps
   (lines 99–114) and `[tool.pytest.ini_options]` (lines 142–149) have markers `slow`/`neo4j`/`memgraph`
   and `addopts = "-v --strict-markers --tb=short --nbval-lax"`. No `asyncio_mode`.
8. **The query-definition layer does NOT change.** `ReadQueryModel`/`WriteQueryModel`/
   `TypedCypherReadQueryModel`/`TypedCypherWriteQueryModel`, `CypherQuery`, `build()`,
   `materialize()`, `interpret_result()`, `CypherQueryData`, `params_schema`, `query_id`,
   `identifiers_schema` — all reused unchanged (ADR-028 Decision 2). `CypherQuery` is directly
   executable without adapters (ADR-045 Q4 Option A): `build(params)` shape is uniform.
9. **`_prepare_statement` prologue exists (E56).** `CypherExecutor._prepare_statement(query,
   raw_params)` does `params_schema.model_validate → build(params) → _validate_cypher`, returning
   `(cypher, qparams, query_identity)`. The async executor mirrors this logic rather than
   duplicating it (E39.5 uses `_validate_cypher` as a static method; the async read/write both
   re-implement the two-line prologue inline to keep the async path self-contained and colour-safe).
10. **Registry wiring is in `registry.py`, not `loader.py`.** `BackendSpec`, `BACKENDS`,
    `ExecutorClass` live in `src/orthograph/backends/registry.py`. `loader.py` imports from
    `registry.py` and exposes the public `load_*` API. E39.7 edits both files.
11. **Inspection is out of scope.** Do not touch `graph_profile/`, `backends/*/inspector.py`,
    `profile.inspect_*`.

---

## Scope

**In scope:**
- Remove transaction ownership from sync `CypherExecutor.write()` (caller-owned).
- Refactor `CypherWriteResultSummary` construction so `consume()` is called by the executor (E39.1),
  enabling reuse on the async path.
- New async contracts: `AsyncExecutor`, `AsyncReadPort`, `AsyncQueryBackedReadPort`.
- New `AsyncCypherExecutor` (caller-owned; never commits).
- Registry wiring: `async_executor` field on `BackendSpec` + `_async_cypher_executor` thunk.
- Loader: `load_async_executor`.
- Async API verbs: `run_read_async`, `run_write_async` in `src/orthograph/execution.py`.
- `pytest-asyncio` + `asyncio_mode = "auto"` + `async_neo4j_driver` fixture.
- E2E async tests (live Neo4j, `--neo4j` flag) proving asyncronicity: read materialises,
  write returns interpreted result, executor never commits.
- Notebook `06.03_async_query_runner.ipynb` showing `run_read_async`/`run_write_async` in an
  async FastAPI handler with an in-notebook fake async session and `httpx.AsyncClient`.

**Out of scope:**
- Async inspection / `validate` (deferred — ADR-028 Decision 3).
- A convenience auto-commit wrapper for standalone writes (deferred — YAGNI).
- Async unit test doubles (`AsyncFakeGraphSession`). Sync tests carry the bulk of behaviour
  coverage; async-specific coverage is e2e only.
- Any change to the query-definition layer or to `QueryCatalogue`.
- Consolidating the duplicated `FakeGraphSession` across test files.

---

## How to use this epic (execution protocol)

Tasks are **sequential within their wave**. Do not start E39.(n+1) until E39.(n) passes its
acceptance gate, unless the Task Map marks them parallel. Each task is **self-contained**: a
low-context agent completes it by reading **only** (a) that task's section and (b) the
**Shared Reference** at the bottom. Each task states its exact files, the change, a binary
acceptance gate, and the **model** it is sized for.

**Model sizing legend:**
- **Haiku** — fully mechanical; every edit is spelled out verbatim. No design judgement.
- **Sonnet** — scoped implementation; a concrete pattern exists to mirror (the sync code or the MP
  reference). Most tasks.
- **Opus** — cross-file behaviour-change reasoning with real blast-radius risk. Used sparingly.

---

## Task Map (dependency order)

```
WAVE 0 — settle the sync contract first (behaviour change; highest risk)
E39.1  Extract _summary_from_counters seam from from_neo4j_result       [Sonnet]  ← unblocks E39.2, E39.5
E39.2  Remove transaction ownership from sync write()                   [OPUS]    ← unblocks E39.3
E39.3  Update 3 sync commit-asserting tests to caller-owned             [Sonnet]  ← gates Wave 1

WAVE 1 — add the async path (purely additive; depends on Wave 0)
E39.4  Add async ABCs (AsyncExecutor / AsyncReadPort / AsyncQueryBackedReadPort)  [Sonnet]  ← unblocks E39.5
E39.5  Implement AsyncCypherExecutor                                    [Sonnet]  ← unblocks E39.7, E39.9
E39.6  Add pytest-asyncio + asyncio_mode + async_neo4j_driver fixture   [Sonnet]  ← unblocks E39.9
E39.7  Wire registry + loader: async_executor field + load_async_executor [Sonnet] ← unblocks E39.8
E39.8  Add async verbs run_read_async / run_write_async + re-exports     [Sonnet]  ← unblocks E39.9, E39.10
E39.9  Add e2e async tests (live Neo4j, --neo4j gated)                  [Sonnet]
E39.10 Add notebook 06.03_async_query_runner.ipynb                      [Sonnet]
E39.11 Update PRD + planning overview                                    [Haiku]
```

- **E39.1 → E39.2 → E39.3** strictly sequential (Wave 0). E39.3 must be green before Wave 1.
- **E39.4 → E39.5** sequential. **E39.6, E39.7** depend on E39.5/E39.3 and may run in parallel.
- **E39.8** depends on E39.7. **E39.9** depends on E39.6 + E39.8. **E39.10** depends on E39.8.
- **E39.11** last (docs).
- **E39.2 is the only Opus task** — it changes tested behaviour at the I/O seam and is the one
  place a wrong edit silently breaks transactional safety.

---

## Tasks

### E39.1 — Refactor `CypherWriteResultSummary` so the executor calls `consume()`

**Model:** Sonnet. **Type:** Code (source). **Wave 0.** No dependencies.

**Goal:** Make summary construction reusable by both sync and async executors by moving the
`result.consume()` call out of the summary classmethod and into the executor. ADR-028 Decision 3
(refines ADR-021, does not reverse it: summary stays structured and vendor-free).

**What to do (in `src/orthograph/cypher/query_execution.py`):**

1. Add a module-level helper (after the `CypherWriteResultSummary` dataclass, before
   `CypherExecutor`) that builds the summary from already-extracted counters:
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
2. Keep `CypherWriteResultSummary.from_neo4j_result` **for now** but reimplement its body to
   delegate: `return _summary_from_counters(result.consume().counters)`.
   (This keeps the sync executor and any existing callers/tests working; E39.2 will switch the
   sync executor to call `consume()` directly.)
3. Do **not** change the dataclass fields or the `WriteResultSummary` protocol. Do not touch async
   anything (no async in this task). Do not change `CypherExecutor`.
4. Run `python -m pytest -q tests/cypher/test_query_execution.py` — must stay green.

**Acceptance gate:**
- [ ] `_summary_from_counters(counters)` exists at module level and returns a `CypherWriteResultSummary`.
- [ ] `from_neo4j_result` now delegates to `_summary_from_counters` (no behaviour change).
- [ ] `python -m pytest -q tests/cypher/test_query_execution.py` passes unchanged.
- [ ] No async code added; no other file changed.

---

### E39.2 — Remove transaction ownership from sync `CypherExecutor.write()`

**Model:** OPUS. **Type:** Code (source — behaviour change). **Wave 0.** Depends on E39.1.

**Why Opus:** this changes tested behaviour at the single I/O seam. A wrong edit silently breaks
transactional safety (the exact failure mode ADR-028 exists to prevent). It requires reasoning about
what the caller's session/transaction object now guarantees and reconciling the docstrings, the
`read()`/`write()` asymmetry, and the rollback-on-error semantics in one coherent change.

**Goal:** After this task, `write()` runs the validated statement against the object the factory
yields and returns `interpret_result(summary)`. It does **not** call `begin_transaction()`,
`commit()`, or `rollback()`. The caller owns the transaction boundary (ADR-028 Decision 1).

**What to do (in `src/orthograph/cypher/query_execution.py`):**

1. Rewrite `CypherExecutor.write()` so it uses `_prepare_statement` (already present) for the
   prologue and then, inside `with self._driver_factory() as session:`, runs directly on the
   session (not on a transaction):
   ```python
   def write(self, query: WriteQueryModel[P, R], raw_params: Any) -> R:
       """Validate params → build → parse Cypher → run → interpret_result (no commit).

       The caller owns the transaction boundary (ADR-028). Pass a session whose
       context-manager exit auto-commits for standalone writes, or pass a live transaction
       and commit externally. Any rows projected by a RETURN clause are discarded — write
       results come from the mutation counters via interpret_result.
       """
       cypher, qparams, _ = self._prepare_statement(query, raw_params)
       with self._driver_factory() as session:
           result = session.run(cypher, **qparams)
           summary = _summary_from_counters(result.consume().counters)
       return query.interpret_result(summary)
   ```
   - **Remove** the `begin_transaction()` / `tx.run()` / `tx.commit()` / `tx.rollback()` /
     `try/except BaseException` block entirely. The executor performs no commit and no rollback.
2. `read()` is **unchanged**. Pre-I/O steps (`_prepare_statement`) are unchanged.
3. Update the module docstring at the top of the file. The current line 7 reads:
   `"``read()`` does not commit; ``write()`` commits."` — change it to:
   `"Neither ``read()`` nor ``write()`` commits or rolls back — the caller owns the transaction"`
   `"boundary (ADR-028). The factory yields the session or live transaction to run against."`
4. Run `python -m pytest -q tests/cypher/test_query_execution.py tests/surface/test_execution.py`.
   The **only** failures after this task must be exactly the three commit-assertion tests E39.3
   will fix (see the Reality Check §2 for their exact names). Confirm no other test newly fails.

**Acceptance gate:**
- [ ] `CypherExecutor.write()` contains no `begin_transaction`, `commit`, or `rollback` call.
- [ ] `write()` builds the summary via `_summary_from_counters(result.consume().counters)` and
      returns `query.interpret_result(summary)`.
- [ ] `read()` is unchanged; `_prepare_statement` is unchanged.
- [ ] Module docstring states the caller-owned-transaction contract (ADR-028).
- [ ] After this task, the **only** failing tests are exactly these three:
      `test_write_commits_transaction` and `test_cypher_query_write_commits_transaction`
      (in `tests/cypher/test_query_execution.py`) and `test_run_write_returns_interpreted_result`
      (in `tests/surface/test_execution.py`). No other test newly fails.

---

### E39.3 — Update sync commit-asserting tests for caller-owned behaviour

**Model:** Sonnet. **Type:** Code (tests). **Wave 0.** Depends on E39.2.

**Goal:** Bring the three commit-asserting tests in line with ADR-028: the executor must now be
shown to run the statement and **not** commit. The fakes keep their `committed`/`rolled_back` flags
so the tests can prove the executor leaves them `False`.

**What to do:**

1. **`tests/cypher/test_query_execution.py`:**
   - `test_write_commits_transaction` (≈ line 224): rename to
     `test_write_does_not_commit_caller_owns_tx`. Keep the run-call assertions (statement ran,
     params correct). Change `assert session.committed is True` to `assert session.committed is
     False` and keep `assert session.rolled_back is False`. Update the docstring to: "write()
     runs the statement but does NOT commit — the caller owns the transaction (ADR-028)."
   - `test_cypher_query_write_commits_transaction` (≈ line 448): same treatment — rename to
     `test_cypher_query_write_does_not_commit_caller_owns_tx`, assert `committed is False`,
     `rolled_back is False`, keep the run assertion.
   - The `FakeGraphSession`/`FakeTransaction` doubles may keep `begin_transaction`/`commit`/`rollback`
     for now (harmless; the executor no longer calls them).
2. **`tests/surface/test_execution.py`:**
   - `test_run_write_returns_interpreted_result` (≈ line 182): keep `assert result == 1`;
     change `assert session.committed is True` to `assert session.committed is False`; keep
     `assert session.rolled_back is False`. Update the inline comment to reference caller-owned tx.
3. Run `python -m pytest -q` (no flags). Entire suite must be green.

**Acceptance gate:**
- [ ] The three tests assert the executor did **not** commit (`committed is False`) and did not
      roll back, while still asserting the statement ran with the correct cypher/params.
- [ ] All test names accurately describe the new (caller-owned) behaviour.
- [ ] `python -m pytest -q` (no flags) passes with the same collected test count as before E39.3.
- [ ] No `src/` change in this task.

---

### E39.4 — Add the async contracts (`AsyncExecutor`, `AsyncReadPort`, `AsyncQueryBackedReadPort`)

**Model:** Sonnet. **Type:** Code (source — additive). **Wave 1.** Depends on E39.3 (Wave 0 green).

**Goal:** Add the async ABCs alongside the sync ones, mirroring their shape (ADR-028 Decision 2).
Purely additive — do not modify the existing `Executor`/`ReadPort`/`QueryBackedReadPort`.

**What to do (in `src/orthograph/query/base_models.py`):**

1. After the existing `Executor` ABC (≈ line 225), add:
   ```python
   class AsyncExecutor(ABC):
       """Async counterpart of Executor. Same contract, awaited.

       Like Executor, it NEVER commits or rolls back — the caller owns the transaction
       boundary (ADR-028). Implementations receive an async factory and open/close the
       async session (or accept a caller-supplied live async transaction) per call.
       """

       @abstractmethod
       async def read(self, query: ReadQueryModel[P, D], raw_params: Any) -> list[D]:
           """Validate params → build() (pure) → execute → materialize. No commit."""

       @abstractmethod
       async def write(self, query: WriteQueryModel[P, R], raw_params: Any) -> R:
           """Validate params → build() (pure) → execute → interpret_result. No commit."""
   ```
2. After `QueryBackedReadPort` (≈ line 255), add the async port pair, mirroring the sync ones:
   ```python
   class AsyncReadPort(ABC, Generic[P, D]):
       """Async named read capability. Async counterpart of ReadPort."""

       @abstractmethod
       async def fetch(self, params: P) -> list[D]: ...


   class AsyncQueryBackedReadPort(AsyncReadPort[P, D]):
       """An AsyncReadPort backed by a ReadQueryModel + AsyncExecutor pair."""

       def __init__(self, query: ReadQueryModel[P, D], executor: AsyncExecutor) -> None:
           self._query = query
           self._executor = executor

       async def fetch(self, params: P) -> list[D]:
           return await self._executor.read(self._query, params)
   ```
3. Reuse the existing `P`, `D`, `R` TypeVars and `ReadQueryModel`/`WriteQueryModel` — no new
   query types.
4. Import smoke: `python -c "from orthograph.query.base_models import AsyncExecutor, AsyncReadPort, AsyncQueryBackedReadPort"` must succeed.
5. Run `python -m pytest -q` — still green.

**Acceptance gate:**
- [ ] `AsyncExecutor`, `AsyncReadPort`, `AsyncQueryBackedReadPort` exist and import cleanly.
- [ ] Their docstrings state "no commit — caller owns the transaction (ADR-028)".
- [ ] The sync `Executor`/`ReadPort`/`QueryBackedReadPort` are unchanged.
- [ ] `python -m pytest -q` passes.

---

### E39.5 — Implement `AsyncCypherExecutor`

**Model:** Sonnet. **Type:** Code (source — additive). **Wave 1.** Depends on E39.4 and E39.1.

**Goal:** Add the concrete async executor, mirroring the (now caller-owned) sync `CypherExecutor`,
using the neo4j async driver idioms. It never commits or rolls back.

**Background — the async driver idioms** (from the MP backend, verified):
- `async with factory() as session:` — async context manager.
- `result = await session.run(cypher, **params)` — returns an async result.
- `records = [dict(rec) async for rec in result]` — iterate records.
- `(await result.consume()).counters` — get mutation counters.
- The factory yields an `AsyncSession` or a live `AsyncTransaction`; the executor never calls
  `commit()` or `rollback()`. Mirror MP's `app/repos/protocol_neo4j_repo.py`.

**What to do (in `src/orthograph/cypher/query_execution.py`):**

1. Add `from orthograph.query.base_models import AsyncExecutor` to the imports (add it after the
   existing `Executor` import in the `base_models` import block).
2. Add the class after `CypherExecutor`, before the end of file:
   ```python
   class AsyncCypherExecutor(AsyncExecutor):
       """Async Executor for graph databases. Caller owns the transaction (ADR-028).

       Accepts an async factory yielding an AsyncSession or a live AsyncTransaction
       (any object with ``async run()``); runs the statement and NEVER commits or rolls back.

       The factory pattern mirrors the sync CypherExecutor: pass a callable returning an
       async context manager, not a live session. Open/close happens per call.

       Example (neo4j async, auto-commit session)::

           AsyncCypherExecutor(lambda: driver.session())

       Example (caller-owned transaction, e.g. MP transaction_context)::

           AsyncCypherExecutor(lambda: live_async_tx)
       """

       def __init__(self, driver_factory: Callable[[], Any]) -> None:
           self._driver_factory = driver_factory

       async def read(self, query: ReadQueryModel[P, D], raw_params: Any) -> list[D]:
           """Validate params → build → parse Cypher → run → materialize (no commit)."""
           params = query.params_schema.model_validate(raw_params)
           cypher, qparams = query.build(params)
           CypherExecutor._validate_cypher(cypher, query.query_id)
           async with self._driver_factory() as session:
               result = await session.run(cypher, **qparams)
               records = [dict(rec) async for rec in result]
           # materialize() is called outside the async-with: it is pure and sync (ADR-028).
           return [query.materialize(rec) for rec in records]

       async def write(self, query: WriteQueryModel[P, R], raw_params: Any) -> R:
           """Validate params → build → parse Cypher → run → interpret_result (no commit)."""
           params = query.params_schema.model_validate(raw_params)
           cypher, qparams = query.build(params)
           CypherExecutor._validate_cypher(cypher, query.query_id)
           async with self._driver_factory() as session:
               result = await session.run(cypher, **qparams)
               summary = _summary_from_counters((await result.consume()).counters)
           return query.interpret_result(summary)
   ```
   Notes:
   - `_validate_cypher` is a `@staticmethod` on `CypherExecutor` — reuse it directly.
   - `_summary_from_counters` is the module-level helper added in E39.1 — reuse it.
   - `materialize()` is called **after** the `async with` block on a plain list — it stays sync
     and pure (ADR-028 Decision 2).
   - Accepts `CypherQuery` and `TypedCypherReadQueryModel`/`TypedCypherWriteQueryModel` directly
     (adapters deleted by E60/ADR-045 Q4); all expose `params_schema`, `query_id`, and
     `build(params)` uniformly.
   - No `begin_transaction`, no `commit`, no `rollback`.
3. Import smoke: `python -c "from orthograph.cypher.query_execution import AsyncCypherExecutor"` must succeed.
4. Run `python -m pytest -q` — still green (no async tests yet; E39.9 adds them).

**Acceptance gate:**
- [ ] `AsyncCypherExecutor(AsyncExecutor)` exists with `async def read` and `async def write`.
- [ ] It uses `async with` for the session, `await session.run`, `async for` to collect records,
      and `(await result.consume()).counters` via `_summary_from_counters`.
- [ ] It contains no `commit` / `rollback` / `begin_transaction`.
- [ ] `materialize()` is called outside the `async with` block (sync, on a collected list).
- [ ] Uses `query.params_schema` (not `query.Params`) and `query.query_id` (not `query.name`).
- [ ] Imports cleanly; `python -m pytest -q` passes.

---

### E39.6 — Add `pytest-asyncio`, `asyncio_mode`, and `async_neo4j_driver` fixture

**Model:** Sonnet. **Type:** Code (deps + fixture). **Wave 1.** Depends on E39.3. May run parallel with E39.4/E39.5.

**Goal:** Enable async test execution and provide a live async Neo4j driver fixture for the e2e
async tests in E39.9. No async test cases are added in this task.

**What to do:**

1. **`pyproject.toml`:**
   - In `[project.optional-dependencies]` `dev` list (line ~106), add
     `"pytest-asyncio>=0.23"` after the line `"pytest-mock>=3.0"`.
   - In `[tool.pytest.ini_options]` (line ~142), add `asyncio_mode = "auto"` as a new line after
     `addopts = ...`. Leave `addopts` and `markers` unchanged.
   - Install: `pip install -e ".[dev]"` (note for CI: the lockfile/CI also needs updating).

2. **`conftest.py`** (root project conftest — the file that registers `--neo4j`):
   Add the following two fixtures after the existing `neo4j_clean` fixture. The `--neo4j` guard,
   URI, user, and password options already exist; reuse the same `request.config.getoption` calls.
   ```python
   @pytest.fixture
   def async_neo4j_driver(request: pytest.FixtureRequest):
       """Yield a neo4j.AsyncGraphDatabase driver for async e2e tests.

       Requires the --neo4j flag. Automatically skipped otherwise.
       """
       import neo4j

       if not request.config.getoption("--neo4j", default=False):
           pytest.skip("needs --neo4j flag to run")

       uri = request.config.getoption("--neo4j-uri")
       user = request.config.getoption("--neo4j-user")
       password = request.config.getoption("--neo4j-password")
       driver = neo4j.AsyncGraphDatabase.driver(uri, auth=(user, password))
       yield driver
       import asyncio
       asyncio.get_event_loop().run_until_complete(driver.close())


   @pytest.fixture
   async def async_neo4j_clean(async_neo4j_driver):
       """Wipe the Neo4j DB before and after each async e2e test."""
       async with async_neo4j_driver.session() as session:
           await session.run("MATCH (n) DETACH DELETE n")
       yield
       async with async_neo4j_driver.session() as session:
           await session.run("MATCH (n) DETACH DELETE n")
   ```
   Note: with `asyncio_mode = "auto"`, the `async def async_neo4j_clean` fixture works without an
   explicit marker.

3. Run `python -m pytest -q` — still green (the new fixtures are discovered but not exercised yet).

**Acceptance gate:**
- [ ] `pytest-asyncio>=0.23` is in `dev` deps; `asyncio_mode = "auto"` is in `[tool.pytest.ini_options]`.
- [ ] `async_neo4j_driver` and `async_neo4j_clean` fixtures exist in the root `conftest.py`.
- [ ] `async_neo4j_driver` skips the test if `--neo4j` is not passed.
- [ ] `python -m pytest -q` passes; sync test count unchanged.

---

### E39.7 — Wire registry and loader: `async_executor` field + `load_async_executor`

**Model:** Sonnet. **Type:** Code (source — additive). **Wave 1.** Depends on E39.5.

**Goal:** Let the public API resolve an async executor by backend name, mirroring `load_executor`,
with the same dependency checks and actionable error messages.

**What to do:**

1. **`src/orthograph/backends/registry.py`:**
   - Add a deferred-import thunk after `_cypher_executor`:
     ```python
     def _async_cypher_executor() -> ExecutorClass:
         from orthograph.cypher.query_execution import AsyncCypherExecutor
         return AsyncCypherExecutor
     ```
     Note: `ExecutorClass` Protocol (`__call__(driver_factory) -> Executor`) fits structurally by
     duck typing — `AsyncCypherExecutor` is constructed with a single factory, same shape. Do not
     add an async-specific protocol (the construction shape is identical).
   - Add `async_executor: Callable[[], ExecutorClass] | None = None` field to `BackendSpec`
     (after the existing `executor` field). Since `BackendSpec` is a `frozen=True` dataclass, just
     add the field with a default of `None`.
   - In the `BACKENDS` dict, set `async_executor=_async_cypher_executor` for `"neo4j"`,
     `"memgraph"`, and `"cypher"`. Leave `"networkx"`, `"gqlalchemy"`, and `"ipython"` with
     `async_executor=None` (default).

2. **`src/orthograph/backends/loader.py`:**
   - Add `load_async_executor` to `__all__`.
   - Add the function after `load_executor`, mirroring it exactly but reading `spec.async_executor`:
     ```python
     def load_async_executor(name: str) -> ExecutorClass:
         """Return the AsyncExecutor class for ``name`` after verifying its dependencies.

         Raises
         ------
         MissingDependencyError
             If ``name`` is unknown, its dependencies are not installed, or async
             execution is not available for this backend.
         """
         spec = BACKENDS.get(name)
         if spec is not None and spec.deferred_executor_reason is not None:
             raise MissingDependencyError(spec.deferred_executor_reason)
         if spec is None or spec.async_executor is None:
             known = ", ".join(
                 sorted(
                     n
                     for n, s in BACKENDS.items()
                     if s.async_executor is not None or s.deferred_executor_reason is not None
                 )
             )
             raise MissingDependencyError(
                 f"Unknown execution backend {name!r}. Known backends: {known}."
             )
         require(name)
         return spec.async_executor()
     ```

3. **`tests/backends/test_loader.py`:**
   - Add parallel async-executor cases after the sync executor section:
     - `test_load_async_executor_neo4j_produces_async_executor_instance` — instantiate with
       `lambda: None`; assert `isinstance(result, AsyncCypherExecutor)` (import it).
     - `test_load_async_executor_neo4j_and_memgraph_share_async_cypher_executor` — both return
       the same class.
     - `test_load_async_executor_gqlalchemy_raises_missing_dependency_error` — same deferred msg.
     - `test_load_async_executor_unknown_raises_missing_dependency_error` — match
       `"Unknown execution backend"`.
     - `test_load_async_executor_networkx_raises_unknown_execution_backend` — networkx has no
       async executor.

4. Verify: `python -c "from orthograph.backends.loader import load_async_executor; print(load_async_executor('neo4j').__name__)"` prints `AsyncCypherExecutor`.
5. Run `python -m pytest -q tests/backends/test_loader.py` — all green.

**Acceptance gate:**
- [ ] `_async_cypher_executor` thunk and `BackendSpec.async_executor` field exist in `registry.py`.
- [ ] `neo4j`/`memgraph`/`cypher` map to the async executor; `networkx`/`gqlalchemy`/`ipython` do not.
- [ ] `load_async_executor("neo4j")` returns `AsyncCypherExecutor`; unknown names and `gqlalchemy`
      raise `MissingDependencyError` with the same messages as `load_executor`.
- [ ] Five new loader tests exist and pass.
- [ ] `python -m pytest -q` passes.

---

### E39.8 — Add async verbs `run_read_async` / `run_write_async` + re-exports

**Model:** Sonnet. **Type:** Code (source — additive). **Wave 1.** Depends on E39.7.

**Goal:** Expose the async path through the public execution module, mirroring the sync
`run_read`/`run_write`.

**What to do:**

1. **`src/orthograph/execution.py`:** after the sync `run_read` and `run_write` functions, add:
   ```python
   async def run_read_async(
       backend: str,
       connection_factory: Callable[[], Any],
       read_query: ReadQueryModel[P, D],
       params: Any,
   ) -> list[D]:
       """Async: execute a typed read query against ``backend``; return ``list[Output]``.

       The caller owns the transaction boundary (ADR-028); ``connection_factory``
       yields an async session or a live async transaction.
       """
       executor_cls = loader.load_async_executor(name=backend)
       return await executor_cls(connection_factory).read(query=read_query, raw_params=params)


   async def run_write_async(
       backend: str,
       connection_factory: Callable[[], Any],
       write_query: WriteQueryModel[P, R],
       params: Any,
   ) -> R:
       """Async: execute a typed write query against ``backend``; return the result.

       Does not commit — the caller owns the transaction boundary (ADR-028).
       """
       executor_cls = loader.load_async_executor(name=backend)
       return await executor_cls(connection_factory).write(
           query=write_query, raw_params=params
       )
   ```
2. Add `"run_read_async"` and `"run_write_async"` to `__all__`. Also add `AsyncExecutor`,
   `AsyncReadPort`, `AsyncQueryBackedReadPort` to the imports from `base_models` and to `__all__`
   so consumers can type their async ports without reaching into `orthograph.query.*`.
3. Update the module docstring to mention the two async verbs and the `AsyncExecutor`/`AsyncReadPort`
   re-exports alongside the sync ones.
4. **`tests/surface/test_execution.py`:** add async dispatch tests after the sync ones:
   - `test_run_read_async_unknown_backend_raises` — `run_read_async("nonsense", ...)` raises
     `MissingDependencyError("Unknown execution backend")`.
   - `test_run_write_async_unknown_backend_raises` — same for write.
   - `test_async_verbs_are_reexported` — assert `run_read_async` and `run_write_async` are
     importable from `orthograph.execution`.
   (Full happy-path async testing is in E39.9 against a live DB. These tests cover only the
   error path and re-exports, which require no async DB.)
5. Run `python -m pytest -q` — all green.

**Acceptance gate:**
- [ ] `run_read_async` and `run_write_async` exist in `execution.py` and `__all__`.
- [ ] Both load via `load_async_executor` and await the executor.
- [ ] `AsyncExecutor`, `AsyncReadPort`, `AsyncQueryBackedReadPort` are re-exported.
- [ ] The three new surface tests exist and pass.
- [ ] `python -m pytest -q` passes.

---

### E39.9 — Add e2e async tests (live Neo4j, `--neo4j` gated)

**Model:** Sonnet. **Type:** Code (tests — e2e). **Wave 1.** Depends on E39.6 + E39.8.

**Goal:** Prove the async executor's *asyncronicity* against a live database:
(1) `await`ed read materialises records, (2) `await`ed write returns the interpreted counter,
(3) the executor leaves the caller's transaction uncommitted (caller-owned tx contract).

**What to do:**

Create a new file `tests/cypher/test_query_async_e2e.py`. Mirror the structure of
`tests/cypher/test_query_e2e.py` (seed/clean pattern, `@pytest.mark.neo4j`, skip guard). The
domain models and seed helper can be copied from `test_query_e2e.py` (filmography domain).

```python
"""Async e2e tests for AsyncCypherExecutor against a live Neo4j DB.

Focus: prove asyncronicity only — that the async path awaits correctly and that
the executor never commits (caller owns the transaction boundary, ADR-028).
Bulk behaviour (param validation, bad Cypher, etc.) is already covered by the
sync unit tests in tests/cypher/test_query_execution.py.

Requires --neo4j flag:
    pytest --neo4j tests/cypher/test_query_async_e2e.py
"""

import pytest
from orthograph.cypher.query_execution import AsyncCypherExecutor
from orthograph.cypher.query import CypherQuery
from orthograph.cypher.bindings import NoIdentifiers
from orthograph.cypher.base_models import TypedCypherReadQueryModel, TypedCypherWriteQueryModel
from orthograph.query.write_result import WriteResultSummary
from pydantic import BaseModel
# ... (domain models same as test_query_e2e.py)
```

Add these three tests (use `async_neo4j_driver` and `async_neo4j_clean` fixtures from E39.6):

1. **`test_async_read_materialises_records`** — seed two movies; call
   `await executor.read(query, params)` via `AsyncCypherExecutor`; assert the returned list
   matches the seeded data. This proves `async for` record iteration works.

2. **`test_async_write_returns_interpreted_result`** — call `await executor.write(create_query,
   params)` via `AsyncCypherExecutor` (using `async_neo4j_clean`); assert result is the expected
   counter value (e.g., `nodes_created == 1`). This proves `(await result.consume()).counters`
   and `_summary_from_counters` works on the async path.

3. **`test_async_write_does_not_auto_commit`** — open an `AsyncTransaction` explicitly on the
   async driver; wrap it in a factory; call `await executor.write(create_query, params)`;
   then, **before calling `tx.commit()`**, run a read to assert the node is NOT yet visible to
   a separate session (phantom read). Then call `await tx.commit()` and assert it IS visible.
   This proves the caller-owned transaction contract: the executor ran the statement but did not
   commit; the caller's explicit `commit()` is what makes it durable.

Use `@pytest.mark.neo4j` on each test (or on the module) and use the `async_neo4j_clean` fixture
to ensure a clean DB before/after each test.

Run: `python -m pytest -q --neo4j tests/cypher/test_query_async_e2e.py` — all three pass.
Run: `python -m pytest -q` (no flags) — the new tests are collected but skipped cleanly.

**Acceptance gate:**
- [ ] `tests/cypher/test_query_async_e2e.py` exists with the three tests.
- [ ] Tests use `async_neo4j_driver`/`async_neo4j_clean` from the root conftest.
- [ ] Without `--neo4j`, tests are **skipped** (not failed) in the full suite run.
- [ ] With `--neo4j`, all three pass against a live Neo4j instance.
- [ ] `python -m pytest -q` (no DB) passes; no change in non-neo4j test count.

---

### E39.10 — Add notebook `06.03_async_query_runner.ipynb`

**Model:** Sonnet. **Type:** Documentation (notebook). **Wave 1.** Depends on E39.8.

**Goal:** Provide a runnable, CI-safe tutorial showing `run_read_async`/`run_write_async` inside
an async FastAPI handler. Mirrors the structure of `notebooks/06.01_fastapi_integration.ipynb`
(no live DB required; uses an in-notebook async fake session; runs via `httpx.AsyncClient`).

**What to do:**

1. Create `notebooks/06.03_async_query_runner.ipynb`. It must:
   - Open with a dependency check cell (skip gracefully if `fastapi` or `httpx` is absent — same
     pattern as 06.01).
   - Define a minimal domain model (reuse `Movie`/`ReleasedYearParams`/`TypedCypherReadQueryModel`
     from the notebook suite convention).
   - Define an `AsyncFakeSession` **in the notebook itself** (not imported from anywhere):
     a simple `async with` capable object whose `run()` returns a fake async-iterable result.
     This is a local teaching aid, not a test double — it exists solely in this notebook.
   - Define an async FastAPI route (`@app.get(...)` with `async def`) that calls
     `await run_read_async("neo4j", session_factory, query, params)` and returns typed JSON.
   - Test the route with `httpx.AsyncClient(app=app, base_url="http://test")` + `await client.get(...)`.
   - Include a cell demonstrating the caller-owned transaction story: create a factory that yields
     a fake async transaction and show that the query runs but "commits" only when the factory's
     `__aexit__` is called by the `async with` block inside the executor.
   - Add a clear docstring/prose explaining ADR-028 Decision 1 ("the executor never commits;
     you own the boundary") and the FastAPI integration pattern.

2. Register the notebook as a UI notebook (requires FastAPI + httpx, not in standard CI):
   In `notebooks/conftest.py`, add `"06.03_async_query_runner.ipynb"` to the `_UI_NOTEBOOKS` set.

3. Run the notebook manually to verify all cells execute without errors:
   `jupyter nbconvert --to notebook --execute notebooks/06.03_async_query_runner.ipynb`
   (requires `fastapi`, `httpx`, `pytest-asyncio` installed).

**Acceptance gate:**
- [ ] `notebooks/06.03_async_query_runner.ipynb` exists and all cells execute cleanly.
- [ ] It imports `run_read_async`/`run_write_async` from `orthograph.execution`.
- [ ] It uses an in-notebook `AsyncFakeSession` (no live DB).
- [ ] It demonstrates a caller-owned-transaction pattern with a fake async factory.
- [ ] `"06.03_async_query_runner.ipynb"` is in `_UI_NOTEBOOKS` in `notebooks/conftest.py`.
- [ ] `python -m pytest -q` (no flags, no `NOTEBOOKS_UI=1`) passes — notebook is skipped.

---

### E39.11 — Update PRD and planning overview

**Model:** Haiku. **Type:** Docs. **Wave 1.** Depends on E39.10.

**Goal:** Reflect that async is now supported for the query runner (inspection still deferred)
and that E39 is complete.

**What to do (verbatim edits):**

1. **`.agentic/knowledge/product_requirements_document.md`:**
   - Find the "Out of Scope" table row for "Async driver support". Change its rationale to:
     `"Query runner: SUPPORTED (async execution via AsyncExecutor / run_read_async /
     run_write_async under caller-owned transactions — ADR-028 / E39). Async inspection
     (inspect / validate) remains deferred until a concrete use case."`
   - In "Aspirational Direction", update the "Async execution" bullet to note the query-runner
     portion is now delivered (ADR-028 / E39); inspection remains aspirational.

2. **`.agentic/planning/overview.md`:**
   - Change E39's status cell from `planned (independent; ADR-028; ...)` to
     `**done** (YYYY-MM-DD; ADR-028; AsyncExecutor + run_read_async/run_write_async; caller-owned
     transactions; e2e async tests; notebook 06.03)` (insert the actual completion date).

3. No code changed. Run `python -m pytest -q` once to confirm still green after doc edits.

**Acceptance gate:**
- [ ] PRD "Out of Scope" + "Aspirational Direction" reflect query-runner async delivered,
      inspection deferred, citing ADR-028.
- [ ] `overview.md` E39 row status is `done` with the completion date.
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
  `WriteResultSummary` protocol; E39.1 refines (does not reverse) it.

### Relevant files (verified 2026-06-29)

| File | Role |
|---|---|
| `src/orthograph/cypher/query_execution.py` | Sync `CypherExecutor` (the I/O seam); `CypherWriteResultSummary`; `_prepare_statement` prologue. E39.1/E39.2 edit; E39.5 adds `AsyncCypherExecutor` here. |
| `src/orthograph/query/base_models.py` | `Executor`/`ReadQueryModel`/`WriteQueryModel`/`ReadPort`/`QueryBackedReadPort` ABCs + `P`/`D`/`R` TypeVars. E39.4 adds async ABCs here. |
| `src/orthograph/backends/registry.py` | `BackendSpec`, `BACKENDS`, `ExecutorClass` Protocol, deferred-import thunks. **E39.7 edits here** (adds `async_executor` field + `_async_cypher_executor` thunk). |
| `src/orthograph/backends/loader.py` | Public `load_inspector`/`load_executor` API; imports from `registry.py`. **E39.7 adds `load_async_executor` here**. |
| `src/orthograph/execution.py` | Public verbs `run_read`/`run_write`. **E39.8 adds `run_read_async`/`run_write_async`**. |
| `tests/cypher/test_query_execution.py` | Sync executor unit tests + `FakeGraphSession`/`FakeTransaction`/`FakeCounters`/`FakeSummary`/`FakeWriteResult`. E39.3 edits the two commit tests here. |
| `tests/surface/test_execution.py` | Surface dispatch tests. E39.3 edits `test_run_write_returns_interpreted_result`; E39.8 adds async error-path tests. |
| `tests/backends/test_loader.py` | Loader tests. E39.7 adds async executor cases. |
| `tests/cypher/test_query_async_e2e.py` | **New** (E39.9): async e2e tests, `--neo4j` gated. |
| `conftest.py` (root) | `--neo4j` fixture registration + `neo4j_driver`/`neo4j_clean`. E39.6 adds `async_neo4j_driver`/`async_neo4j_clean`. |
| `pyproject.toml` | `dev` deps + `[tool.pytest.ini_options]`. E39.6 adds `pytest-asyncio` + `asyncio_mode`. |
| `notebooks/06.03_async_query_runner.ipynb` | **New** (E39.10): async FastAPI example, in-notebook fake async session, no live DB. |
| `notebooks/conftest.py` | Notebook collection gating. E39.10 adds `06.03` to `_UI_NOTEBOOKS`. |
| `.agentic/knowledge/product_requirements_document.md` | E39.11 updates Out-of-Scope + Aspirational. |
| `.agentic/planning/overview.md` | E39.11 updates epic table row to done. |

### The caller-owned transaction contract (ADR-028 Decision 1 — the heart of this epic)

- The executor (sync AND async) **never** calls `begin_transaction` / `commit` / `rollback`.
- It runs the validated statement against whatever the factory yields and returns the
  materialised list (`read`) or `interpret_result(summary)` (`write`).
- The caller owns when the unit of work commits — exactly like MP's `transaction_context`, which
  opens the `AsyncTransaction`, yields it live to repos, and commits/rolls back both Postgres and
  Neo4j together.
- Reads were never committing; only `write()`'s self-commit is removed.

### The query surface post-E60 (all tasks must use these names)

- Abstract query bases: `ReadQueryModel`, `WriteQueryModel` (in `query/base_models.py`).
- Cypher typed bases: `TypedCypherReadQueryModel`, `TypedCypherWriteQueryModel` (in `cypher/base_models.py`).
- Simple instantiable Cypher path: `CypherQuery` (in `cypher/query.py`) — directly executable,
  no adapters (ADR-045 Q4 Option A). `build(params)` shape is uniform across all three paths.
- ClassVar names: `params_schema` (not `Params`), `query_id` (not `name`), `identifiers_schema`.
- The executor prologue: `query.params_schema.model_validate(raw_params)` → `query.build(params)`
  → `CypherExecutor._validate_cypher(cypher, query.query_id)`.

### The async idioms (verified against MP `app/repos/protocol_neo4j_repo.py` + `app/db/`)

- Session/transaction is an **async context manager**: `async with factory() as session:`.
- `result = await session.run(cypher, **params)`.
- Iterate records: `[dict(rec) async for rec in result]`. Single row: `await result.single()`.
- Counters (write): `(await result.consume()).counters` → `_summary_from_counters(...)`.
- Repos accept `AsyncTransaction | AsyncSession` and only call `run()`; they never commit.

### The colour rule (why parallel hierarchies — ADR-028 Decision 2)

`async def` is consumed only with `await`; sync callers cannot `await`; an async caller that calls
a blocking sync function freezes the event loop. Sync and async cannot be one method. Hence two
ABCs, two executors, two ports — the duplication is intentional and honest. The query-definition
layer (`build`/`materialize`/`interpret_result`/`CypherQueryData`) is colour-neutral and shared
unchanged.

### Verification commands

- Unit suite (no DB): `python -m pytest -q`
- Targeted: `python -m pytest -q tests/cypher/test_query_execution.py tests/surface/test_execution.py tests/backends/test_loader.py`
- Async e2e (live DB): `python -m pytest -q --neo4j tests/cypher/test_query_async_e2e.py`
- Import smoke checks are listed inside each task's acceptance gate.

### References
- ADR-028 (this epic's authority); ADR-021 (refined by E39.1); PRD Constraint 13.
- MP reference (read-only, do not modify): `D:\software_development\04_external\D4SP\MP\mp-backend\app\repos\protocol_neo4j_repo.py`, `app\db\transaction_context.py`, `app\db\async_neo4j_pool.py`.

---

## Changelog

- **2026-06-18** — Epic created from ADR-028. Codebase verified: `CypherExecutor` is the sole
  `Executor`; transaction lifecycle confined to one source file + three tests; no async in `src/`;
  test stack lacks `pytest-asyncio`. Scope fixed to the query runner (inspection deferred). Tasks
  originally numbered T1–T9. T2 = Opus (behaviour change at the I/O seam), T9 = Haiku (mechanical
  docs), rest = Sonnet.
- **2026-06-29** — Re-targeted after E55 (ADR-041), E56 (ADR-042), E59 (ADR-043), E60 (ADR-045)
  landed. ADR-045 Q4 promised E60.5 would perform this re-target; E60 was marked done but E60.5
  did not execute. Changes: tasks re-numbered E39.1–E39.11; `api/database.py` → `execution.py`;
  `run_read`/`run_write` verb names (E55); `ReadQueryModel`/`WriteQueryModel`/`TypedCypher*`
  names (E60 Q6); `params_schema`/`query_id` attribute names (E60 Q1–Q3); adapters deleted —
  `CypherQuery` directly executable (E60 Q4); registry wiring moved to `registry.py` (E56); two
  new tasks: E39.9 (e2e async tests, no fakes — async-only behaviour on live DB) and E39.10
  (notebook 06.03 — FastAPI async, in-notebook fake session); old T6 (AsyncFakeGraphSession unit
  tests) removed per pragmatic test strategy (sync unit tests carry the bulk).
