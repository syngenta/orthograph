# Running Queries — Sync and Async Execution

Orthograph provides **two execution paths** — one for the typed path, one for
the simple path — each available in both synchronous and asynchronous flavours.
The right path to use depends on what kind of query object you have.

→ **Tutorials:**
  {doc}`../notebooks/03.03_cypher_query_usage` demonstrates the simple path.
  {doc}`../notebooks/03.04_typed_query_contracts` and
  {doc}`../notebooks/03.05_typed_query_result_shapes_and_materialization`
  demonstrate the typed path.
  {doc}`../notebooks/06.03_async_query_runner` (How-To) shows async execution
  in a realistic service context.

For a description of query kinds, see [Query management](query-management.md).

---

## The two paths and why they are separate

The typed path (`TypedCypherReadQueryModel`, `TypedCypherWriteQueryModel`)
declares an `Output` Pydantic model. The executor is generic over it:
`run_read(...)` returns `list[D]` where `D` is your output model. The type
checker can verify this end to end.

The simple path (`CypherQuery`) declares **no** output model — results are
`list[dict[str, Any]]`. `dict[str, Any]` is not a `BaseModel`, so `CypherQuery`
cannot be passed to the typed executors without breaking the generic bound.
Rather than pollute the typed surface with `# type: ignore`, the simple path
gets **dedicated executors** (`CypherQueryExecutor`, `AsyncCypherQueryExecutor`)
whose operations return the correct raw type directly.

See [ADR-047](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/047-simple-path-cypher-execution-surface.md)
for the full rationale.

---

## Simple-path execution

```python
from orthograph.execution import run_cypher_fetch, run_cypher_execute
from orthograph.execution import run_cypher_fetch_async, run_cypher_execute_async
```

| Verb | Returns | Use for |
|---|---|---|
| `run_cypher_fetch(connection_factory, query, params)` | `list[dict[str, Any]]` | Queries with a `RETURN` clause |
| `run_cypher_execute(connection_factory, query, params)` | `CypherWriteResultSummary` | Mutations (CREATE / SET / DELETE) |
| `run_cypher_fetch_async(...)` | `list[dict[str, Any]]` | Async fetch |
| `run_cypher_execute_async(...)` | `CypherWriteResultSummary` | Async mutation |

`connection_factory` is a callable that returns a Neo4j / Memgraph session (or
compatible object). Orthograph never owns a connection; the caller manages the
lifecycle.

---

## Typed-path execution

```python
from orthograph.execution import run_read, run_write
from orthograph.execution import run_read_async, run_write_async
```

| Verb | Returns | Use for |
|---|---|---|
| `run_read(backend, connection_factory, query, params)` | `list[D]` | Read queries — fully typed result |
| `run_write(backend, connection_factory, query, params)` | `R` | Write queries — typed result summary |
| `run_read_async(...)` | `list[D]` | Async read |
| `run_write_async(...)` | `R` | Async write |

`backend` is a string name (`"neo4j"`, `"networkx"`, …) that selects the
executor via `backends/loader.py`. `D` and `R` are inferred from the query's
type parameters.

---

## The executor objects

For both paths, a low-level executor object is also available if you need to
reuse a single executor across multiple calls:

**Simple path:**

```python
from orthograph.execution import CypherQueryExecutor, AsyncCypherQueryExecutor

executor = CypherQueryExecutor(connection_factory)
rows = executor.fetch(query, params)          # list[dict[str, Any]]
summary = executor.execute(query, params)     # CypherWriteResultSummary
```

**Typed path:**

```python
from orthograph.execution import CypherExecutor, AsyncCypherExecutor

executor = CypherExecutor(connection_factory)
results = executor.read(query, params)        # list[D]
summary = executor.write(query, params)       # R
```

---

## Caller-owned transactions

Orthograph does **not** manage transactions. Each `run_*` call opens a session
via `connection_factory`, executes a single statement, and returns. Commit,
rollback, and retry logic belong to the calling application.

This is a deliberate constraint (ADR-028): Orthograph is a governance layer, not
a connection manager. It works with any connection library that provides a
callable session factory.

---

## Choosing sync vs. async

Both paths offer identical functionality in sync and async flavours. Use the
async verbs (`run_*_async`, `AsyncCypherQueryExecutor`, `AsyncCypherExecutor`)
when integrating with an async framework such as FastAPI or when running multiple
queries concurrently. See {doc}`../notebooks/06.03_async_query_runner` for a
worked example.

---

## Implementation locations

| Concern | Module |
|---|---|
| Simple-path executors | `src/orthograph/cypher/query_execution.py` (`CypherQueryExecutor`, `AsyncCypherQueryExecutor`) |
| Typed-path executors | `src/orthograph/cypher/query_execution.py` (`CypherExecutor`, `AsyncCypherExecutor`) |
| Public verbs | `src/orthograph/execution.py` |
| Backend loader | `src/orthograph/backends/loader.py` |
| ADR-047 (simple-path surface) | `.agentic/decisions/047-simple-path-cypher-execution-surface.md` |
| ADR-028 (caller-owned transactions) | `.agentic/decisions/028-caller-owned-transactions.md` |
