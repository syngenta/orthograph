# Async query execution and universal caller-owned transactions

The typed query runner (`api.database.query` / `execute`, backed by `CypherExecutor`) is
synchronous: every I/O path opens a session and blocks until the database answers. A planned
consumer — the MP backend (`mp-backend`) — is built entirely on the neo4j **async** driver
(`AsyncGraphDatabase`, `AsyncSession`, `AsyncTransaction`) and runs inside FastAPI request
handlers, where a blocking call would freeze the event loop and stall every concurrent request.
This is the "concrete backend and use case" the PRD named as the trigger for promoting async
out of the aspirational section (PRD "Out of Scope", "Aspirational Direction").

This ADR records three coupled decisions made while scoping that work: (1) **universal
caller-owned transactions** for both sync and async writes; (2) **parallel `Executor` /
`AsyncExecutor` hierarchies** rather than overloads or a merged protocol; (3) the **scope**
(query runner only — inspection stays sync) and a small refinement to ADR-021.

## Decision 1 — Orthograph never owns the transaction boundary (sync and async alike)

The executor will **not** open, commit, or roll back transactions. It runs the validated query
against the session or transaction object the caller's factory yields, and returns the
materialised/interpreted result. Commit and rollback are the caller's responsibility.

This **changes existing sync behaviour**: today `CypherExecutor.write()` calls
`session.begin_transaction()`, then `tx.commit()` (or `tx.rollback()` on error) internally. That
self-committing behaviour is removed. After this ADR, both sync and async `write()` follow one
rule: *run the statement; the caller decides when the unit of work commits.*

Why this is correct and not merely convenient for MP:

- **It honours Constraint 13, which the old code violated.** PRD Constraint 13 states "Connections
  are never owned… Orthograph never stores, pools, or manages connection lifecycle as instance
  state." A transaction boundary *is* connection lifecycle. A library executing a single statement
  cannot know the true extent of the caller's unit of work, so it must not decide when that work
  commits. The self-committing `write()` was an unnoticed breach of Orthograph's own stated
  principle; no consumer had exercised it until MP.
- **It prevents silent partial commits across stores.** MP coordinates PostgreSQL + Neo4j in one
  unit of work (`app/db/transaction_context.py`): it opens both transactions, yields the live
  `AsyncTransaction` to its repos, and commits/rolls back both together. If Orthograph committed
  the Neo4j half internally, a later PostgreSQL failure would roll back Postgres while Neo4j stayed
  committed — permanent, silent cross-store drift with no error raised. Caller-owned commit makes
  this failure mode impossible by construction.
- **One mental model.** "Orthograph never commits; you own the boundary" applies everywhere —
  sync, async, every future backend. This is the most learnable rule for contributors and for
  agents navigating `.agentic/`.

Accepted cost: a caller doing a one-off standalone write must now manage a transaction (or pass a
session whose context-manager exit commits) rather than relying on the executor to commit. For MP
this is irrelevant (it always owns the boundary). A thin convenience wrapper for the standalone
single-statement case is deliberately **not** built now (YAGNI); it may be added later if a real
consumer needs it.

`read()` is unaffected in substance — reads never committed. Its single-statement,
no-explicit-transaction behaviour stands (it remains the documented contract that a read needing
multi-statement isolation is not representable and is out of scope).

## Decision 2 — Parallel `Executor` and `AsyncExecutor` hierarchies

Async and sync are different "colours" of code: an `async def` can only be consumed with `await`,
and a sync caller cannot `await`. The two cannot be transparently unified — a single method that
"works both ways" is not expressible without one path silently blocking the event loop. Given
that, we add a **separate** `AsyncExecutor` ABC alongside the existing `Executor`, with a separate
concrete `AsyncCypherExecutor`, and a separate `AsyncReadPort` / `AsyncQueryBackedReadPort`. The
sync types are untouched (apart from Decision 1's behaviour change and docstrings).

### Considered options

- **One `Executor` ABC with overloaded sync/async methods** — rejected. The colour rule means a
  class cannot honestly offer both `def read` and `async def read`; the return types differ
  (`list[D]` vs a coroutine), type checkers reject or mis-infer it, and the "looks unified but
  isn't" shape invites a caller to forget `await` and silently block.
- **Convert `Executor` to a `Protocol` satisfied by both** — rejected. A protocol implies
  substitutability, but a sync executor is **not** substitutable for an async one: callers await
  one and not the other. The abstraction would lie.
- **Parallel hierarchies (chosen)** — the mild duplication between sync and async `read`/`write`
  bodies (identical except for `await` and `async with`) is honest: it makes the two execution
  models *visibly* different, which is exactly what readers and type checkers need. It is purely
  additive to the existing ABC-based design (`Executor` is already an ABC with a `QueryBackedReadPort`
  partner), so it cannot break the sync path.

The **query-definition layer does not change.** `ReadQuery` / `WriteQuery` / `CypherReadQuery` /
`CypherWriteQuery`, `build()`, `materialize()`, `interpret_result()`, `Params`, `cypher_template`,
`Identifiers`, and `CypherQueryData` are all execution-context-neutral and are reused unchanged by
both executors. The query owns validation and construction; the executor owns all execution. The
`backend` tag (`Backend.CYPHER`) denotes **dialect only** and must never encode sync-vs-async — the
composition root chooses the executor based on whether the runtime is sync or async, and the same
query class serves both.

`materialize()` and `interpret_result()` are contractually **pure and I/O-free** (already stated in
their docstrings). On the async path this is load-bearing: a blocking call hidden inside one of them
would freeze the event loop. The async executor collects records into a plain list before calling
`materialize()` per record, so the methods themselves stay synchronous and unaware of async.

## Decision 3 — Scope: query runner only; refine ADR-021's consume() seam

**In scope:** async execution of typed read/write queries — `AsyncExecutor`, `AsyncCypherExecutor`,
`AsyncReadPort`, `AsyncQueryBackedReadPort`, async loader wiring, and async `query`/`execute` API
verbs.

**Out of scope (deferred):** async **inspection** (`inspect` / `validate`, `CypherInspector`, the
neo4j/memgraph inspectors). MP's adoption is write/read-path-driven via repositories; live profiling
inside async request handlers is not a stated need. Inspection remains synchronous and untouched.
This roughly halves the work and keeps the change focused on the seam MP actually uses.

**ADR-021 refinement.** ADR-021 placed counter extraction in the executor via
`CypherWriteResultSummary.from_neo4j_result(result)`, which calls `result.consume()`
**synchronously**. The async driver's `consume()` is a coroutine, so this classmethod cannot be
shared across sync and async. We refine — not reverse — ADR-021: the executor calls `consume()`
(sync: `result.consume()`; async: `await result.consume()`) and constructs the **structured**
`CypherWriteResultSummary` from the resulting counters via a small shared helper. ADR-021's intent
is preserved (vendor-free, structured — not a bare dict — and testable without a live driver); only
*where* `consume()` is awaited moves. This also realises the Dependency-Inversion improvement
ADR-021 hinted at: the summary dataclass no longer needs to know the neo4j `Result` type.

## Consequences

- Existing sync write tests that assert the executor committed (`test_write_commits_transaction`,
  `test_cypher_query_write_adapter_commits_transaction`, and the `execute` dispatch test) change to
  assert the executor ran the statement and did **not** commit. This is a deliberate, controlled
  behaviour change covered by those tests.
- A new dev dependency (`pytest-asyncio`) and async test doubles (`AsyncFakeGraphSession`) are
  introduced; the sync suite is otherwise unaffected.
- The PRD's "async driver support" item moves from aspirational to supported **for the query
  runner**, with inspection explicitly still deferred.
- Implemented by Epic E39.
