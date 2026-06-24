# Epic E4: Extension Robustness & Consistency

> **Priority:** Medium
> **Origin:** Code review 2026-05-07 (sections 5, 6: Simplicity, Redundancy)
> **Goal:** Improve reliability and consistency of extension modules
> **Blocked by:** E2 (shared utilities), E10 (connection patterns settled)
> **User stories:** 5

---

## Context

The extension modules were built incrementally (Neo4j first, then Memgraph,
then GQLAlchemy). Each was developed as a self-contained unit, which was
correct for initial velocity. Now that all exist, some inconsistencies
have emerged. This epic addresses them after E2 (shared utilities) and E10
(connection ownership) establish the patterns.

---

## Tasks

### E4.1: Add Explicit Backend Parameter to GqlAlchemyClient

Replace the fragile `type(self._db).__name__` string matching with an explicit `backend: Literal["neo4j", "memgraph"] | None` parameter.

**Acceptance criteria:**
- [ ] `GqlAlchemyClient(model=m, db=db, backend="memgraph")` uses Memgraph inspector
- [ ] Auto-detection still works when `backend=None`
- [ ] Explicit parameter takes precedence
- [ ] All existing tests pass

---

### E4.2: Align MemgraphQueries Documentation

Document the intentional divergence between `MemgraphQueries` and the Neo4j `QueryStrategy` protocol. The divergence is real (Memgraph returns all metadata in single calls, not per-label).

**Acceptance criteria:**
- [ ] Clear docstring on `MemgraphQueries` explains design choice
- [ ] Extension contract doc updated to note this divergence
- [ ] No behavioral changes
- [ ] All existing tests pass

---

## Removed (superseded)

- ~~E4.3 (old): Complete GQLAlchemy Load Operations (load_node/load_relationship)~~ — superseded by E9 (GQLAlchemy Client Review). Adding more persistence methods conflicts with the composition approach. Load operations belong in consuming projects or will be reconsidered after E9 establishes the new boundary.
