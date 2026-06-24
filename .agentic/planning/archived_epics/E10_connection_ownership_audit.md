# Epic E10: Connection Ownership Audit

> **Status:** **RETIRED (2026-06-24)** — superseded; do **not** pick up work from this epic.
> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Enforce PRD constraint #13 — connections are never owned by Orthograph
> **Blocked by:** E9 (GQLAlchemy client review establishes the pattern)
> **User stories:** 21

---

## Why this epic is retired (read before reviving any task)

E10's entire subject — auditing extension classes that store a connection as instance
state (`self._driver`/`self._db`/`self._graph`) and refactoring them to accept the
connection per-call — has already been delivered or reassigned. Retiring it prevents an
agent from re-opening settled work and regressing the current code:

- **Inspectors (E10.1 / E10.2 / E10.3) — delivered by E25 / ADR-011 (done 2026-06-11).**
  E25 explicitly closed discrepancy **D1** ("inspectors store `self._driver`/`self._graph`")
  by making the inspector ABC `inspect(self, connection)` (connection per-call) and the
  three inspectors stateless. Verified in the current code: `graph_profile/inspection.py`
  (`def inspect(self, connection)`), and `backends/{neo4j,memgraph,networkx}/inspector.py`
  (`__init__` stores only config knobs — `strategy`, `value_counts_top_n` — never a
  connection). `tests/test_architecture.py` enforces the structural invariants. E10.3's
  lifecycle intent is satisfied by that test layer.

- **The one remaining live Constraint-13 breach is owned by E39 / ADR-028, not E10.**
  E10 never covered the executor. The genuine ownership breach — `CypherExecutor.write()`
  self-committing (`begin_transaction` / `commit` / `rollback`) — is removed by E39 Wave 0
  (caller-owned transactions). ADR-028 §Decision 1 frames it as "honours Constraint 13,
  which the old code violated." No E10 task migrates here: E39 already covers it, and
  bringing the inspector-audit tasks across would re-open work E25 settled.

- **`ValidatedQueryBuilder` / `GqlAlchemyClient` connection storage is E9's subject.**
  The `GqlAlchemyClient.self._db` + `save_*`/`execute` cleanup is owned by **E9
  (GQLAlchemy Client Review)**, which remains active. E10 was merely "blocked by E9 to
  enforce the pattern E9 establishes"; with the inspector pattern now structurally
  enforced by E25, there is nothing left for E10 to enforce separately.

**Net:** no tasks worth migrating; superseded by **E25** (inspectors) + **E39/ADR-028**
(executor transaction ownership) + **E9** (GQLAlchemy client). See ADR-011 (E25 discrepancy
register, D1) and ADR-028 (Decision 1).

---

## Context

PRD Constraint #13 states: "Database drivers and sessions are passed in by the
caller. Orthograph never stores, pools, or manages connection lifecycle as
instance state."

After E9 establishes the composition pattern for GQLAlchemy, this epic audits
ALL extensions to ensure the same principle holds everywhere. Any extension that
stores a connection as `self._db`, `self._driver`, or similar instance state
must be refactored to accept connections per-call.

---

## Tasks

### E10.1: Audit All Extension Classes for Connection Storage

Inspect every class in `extensions/` that interacts with a database:
- `Neo4jInspector` — takes `driver` in `__init__`
- `MemgraphInspector` — takes `driver` in `__init__`
- `GqlAlchemyClient` — (refactored in E9)
- `ValidatedQueryBuilder` — takes `db` in `__init__`

Classify each:
- Does it store the connection as instance state?
- Is the connection used only in a single method call?
- Can it be refactored to accept connection per-call?

**Acceptance criteria:**
- [ ] Written audit of every extension class with connection interaction
- [ ] Each classified as: compliant / needs refactoring / acceptable exception (with rationale)

---

### E10.2: Refactor Inspectors to Accept Connection Per-Call

If inspectors store connections as instance state, refactor to pass per-call.

**Note:** There is a design tension here — inspectors are naturally "bound to a target" (you inspect *this* database). The acceptable pattern may be: connection passed at construction as a configuration parameter (not lifecycle-managed) OR passed to `inspect()` directly. The key constraint is that Orthograph never *pools*, *closes*, or *manages* the connection.

**Acceptance criteria:**
- [ ] Decision documented: which pattern inspectors follow (construction param vs per-call)
- [ ] If refactored: all inspector tests updated
- [ ] Connection is never closed/released by Orthograph code
- [ ] Extension contract doc updated with connection handling guidelines

---

### E10.3: Add Connection Ownership Tests

Write tests that verify no extension class manages connection lifecycle.

**Acceptance criteria:**
- [ ] Test: after `inspector.inspect()` completes, connection is not closed
- [ ] Test: `ValidatedQueryBuilder` does not store connection between calls (if refactored)
- [ ] Test: no extension class has `close()`, `disconnect()`, or `__del__` methods that touch connections
