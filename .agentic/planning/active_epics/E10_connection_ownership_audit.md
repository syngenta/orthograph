# Epic E10: Connection Ownership Audit

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Enforce PRD constraint #13 — connections are never owned by Orthograph
> **Blocked by:** E9 (GQLAlchemy client review establishes the pattern)
> **User stories:** 21

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
