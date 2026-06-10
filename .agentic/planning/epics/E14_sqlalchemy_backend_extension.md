# Epic E14: SQLAlchemy Backend Extension

> **Priority:** Low (was High)
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Add `extensions/sqlalchemy/` to orthograph: `SqlReadQuery`, `SqlWriteQuery`, and
> `SqlExecutor` that implement the E16 typed contract, giving any project a relational backend
> with the same introspection/port surface as graph backends.
> **Blocked by:** E16 (typed contract must exist first) — **E16 is already implemented**
> **Status note:** The matterforge PoC has verified that `SqlReadQuery`/`SqlWriteQuery`/
> `SqlExecutor` work correctly when implemented in matterforge itself (as
> `matterforge/persistence/sql/query_bases.py`) rather than in orthograph. This epic is
> therefore **not blocking matterforge Phase 2**. It becomes relevant only when a second project
> needs reusable SQLAlchemy query bases and it would be wasteful to reimplement them.
> **Decision:** implement when there is a second consumer, not before.

---

## Context

matterforge's primary store is Postgres. Without this extension, matterforge must vendor the
SQLAlchemy backend (as in the PoC's `orthograph_ext/sql.py`). Adding it to orthograph makes it
available to any consuming project and keeps the vendored copy as a reference only.

**Scope flag:** This grows orthograph a relational limb. orthograph Constraint 1 ("DB-agnostic
in core") is respected: all SQLAlchemy code lives in `extensions/sqlalchemy/`, never in `core/`.
Constraint 11 ("extensions are isolated") is respected: importing this extension does not pull in
neo4j, memgraph, or gqlalchemy. If the team decides relational is outside orthograph's mission,
this epic stays inside matterforge instead — in that case only E13 is upstreamed and this epic is
cancelled. **The placement decision should be confirmed before work begins.**

**Reference implementation:** `pocs/p02_matterforge_slice/orthograph_ext/sql.py` in the
matterforge-persistence PoC. That file is the design ground truth for this epic.

---

## Tasks

### E14.1: `SqlReadQuery` and `SqlWriteQuery` base classes

**What:** Backend-specific base classes that fix `build()` return type to a SQLAlchemy construct
and set `backend = Backend.SQLALCHEMY`. Concrete subclasses provide `build()` body + `materialize()`.

**Actions:**
1. Create `src/orthograph/extensions/sqlalchemy/__init__.py`.
2. Create `src/orthograph/extensions/sqlalchemy/queries.py`:
   ```python
   from sqlalchemy.sql import Executable
   from sqlalchemy.sql.selectable import Select
   from orthograph.catalogue.typed import Backend, ReadQuery, WriteQuery

   class SqlReadQuery(ReadQuery[P, D], Generic[P, D]):
       """build() returns a SQLAlchemy Select. materialize() maps a Row -> declared Output."""
       backend = Backend.SQLALCHEMY

       def build(self, params: P) -> Select: ...       # abstract — subclasses provide body
       def materialize(self, raw: Any) -> D: ...       # abstract — subclasses provide body

   class SqlWriteQuery(WriteQuery[P, R], Generic[P, R]):
       backend = Backend.SQLALCHEMY

       def build(self, params: P) -> Executable: ...   # abstract
       def interpret_result(self, raw: Any) -> R: ...  # abstract
   ```
3. Tests (no DB — R1 must hold):
   - `SqlReadQuery.build()` returns a `Select` object; `str(stmt)` contains expected SQL keywords.
   - The `Select` compiles without a connection: `stmt.compile()` succeeds.
   - `SqlReadQuery.materialize()` with a hand-built fake row tuple returns the declared `Output` type.

**Verification:** `from orthograph.extensions.sqlalchemy import SqlReadQuery, SqlWriteQuery` works.
`mypy src/` passes.

---

### E14.2: `SqlExecutor` — the relational session seam

**What:** Concrete `Executor` for SQLAlchemy. The **only** place a Session is opened.
Read and write are distinct methods with different transactional intent.

**Actions:**
1. Create `src/orthograph/extensions/sqlalchemy/executor.py`:
   ```python
   from sqlalchemy.orm import Session
   from orthograph.catalogue.typed import Executor, ReadQuery, WriteQuery

   class SqlExecutor(Executor):
       """The single I/O seam for the relational store.

       Connections are NEVER owned (orthograph Constraint 13). A session_factory
       callable is passed at construction time; the executor opens a session per
       call and closes it after. Example:
           executor = SqlExecutor(lambda: Session(engine))
       """
       def __init__(self, session_factory: Callable[[], Session]) -> None:
           self._session_factory = session_factory

       def read(self, query: ReadQuery[P, D], raw_params: Any) -> list[D]:
           params = query.Params.model_validate(raw_params)   # R4: validate before SQL
           stmt = query.build(params)                          # R1: pure, no session
           with self._session_factory() as session:            # only I/O seam
               rows = session.execute(stmt).all()
           return [query.materialize(row) for row in rows]     # R3: query owns mapping

       def write(self, query: WriteQuery[P, R], raw_params: Any) -> R:
           params = query.Params.model_validate(raw_params)    # R4
           stmt = query.build(params)
           with self._session_factory() as session:
               result = session.execute(stmt)
               session.commit()                                # writes commit; reads do NOT
           return query.interpret_result(result)
   ```
2. Tests (with real SQLite in-memory):
   - `read()` executes the query and materialises all rows into the declared `Output` type.
   - `write()` commits; subsequent `read()` reflects the change.
   - **`StaticPool` required** for in-memory SQLite so seed and query share one connection.
     Document this as a known gotcha: `create_engine("sqlite://", poolclass=StaticPool)`.
   - `read()` does NOT commit; `write()` does.
   - Bad params (`model_validate` raises) prevent any SQL from running.

**Verification:** `from orthograph.extensions.sqlalchemy import SqlExecutor` works.
Integration test: seed + read + write + re-read with real SQLite passes.

---

### E14.3: Package structure, optional dependency, isolation test

**What:** Wire up the extension as an independently installable optional dependency.

**Actions:**
1. Add `[sqlalchemy]` optional dependency group to `pyproject.toml`:
   ```toml
   [project.optional-dependencies]
   sqlalchemy = ["sqlalchemy>=2.0"]
   ```
2. Guard the import: wrap `from sqlalchemy ...` in a try/except that raises a clear
   `ImportError("Install orthograph[sqlalchemy] to use the SQLAlchemy backend.")`.
3. Isolation test: importing `orthograph.extensions.neo4j` in the same process as
   `orthograph.extensions.sqlalchemy` works without pulling in the other's dependencies.
4. Export from `orthograph.extensions.sqlalchemy.__init__`:
   `SqlReadQuery`, `SqlWriteQuery`, `SqlExecutor`.

**Verification:** `pip install orthograph` (without `[sqlalchemy]`) then
`import orthograph.extensions.sqlalchemy` raises `ImportError`. With `[sqlalchemy]` it succeeds.

---

## Relationship to Other Epics

- **E13** — this epic implements E13's `ReadQuery`/`WriteQuery`/`Executor` ABCs for SQLAlchemy.
- **E15** — parallel; the Cypher typed backend does the same for graph.
- **matterforge E7–E9** — import `SqlReadQuery`, `SqlWriteQuery`, `SqlExecutor` from here once
  this lands; remove the vendored `orthograph_ext/sql.py`.
