# Epic E8: GQLAlchemy Query Catalogue

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Provide a schema-validated, named-query registry for GQLAlchemy builder expressions (Python-only)
> **Blocked by:** E6 (shares registry interface design)
> **User stories:** 14, 16

---

## Context

The GQLAlchemy Query Catalogue parallels the Cypher Query Catalogue (E6) but
for GQLAlchemy builder expressions. Since builder patterns are Python code (not
serialisable strings), this catalogue is **Python-only** — no YAML mode.

Consuming projects register named GQLAlchemy queries at runtime with declared
parameter types and expected result types. Orthograph validates query output
against the schema at registration and validates results at execution.

**Architectural principle:** Same as E6 — Orthograph provides the registry and
validation; consuming projects provide queries, connections (passed per-call),
and orchestration.

---

## Tasks

### E8.1: Define GQLAlchemy Query Registry Interface

Design the `GqlAlchemyQueryCatalogue` class with register/lookup/execute pattern.

**Acceptance criteria:**
- [ ] `GqlAlchemyQueryCatalogue(model=model)` — takes a GraphDataModel
- [ ] `catalogue.register(name, query_factory, parameters, returns)` — query_factory is a callable that accepts params and returns a query builder expression
- [ ] `catalogue.query_names()` and `catalogue.get_definition(name)` for introspection
- [ ] Schema validation at registration: validate that query output (label references, property accesses) is consistent with model
- [ ] Tests cover registration, lookup, validation errors

---

### E8.2: Result Type Validation at Execution

Add execution path with per-call connection and result validation.

**Acceptance criteria:**
- [ ] `catalogue.execute(name, params, connection=conn)` runs the registered query
- [ ] `catalogue.execute(name, params, connection=conn, validate_results=True)` validates result against declared output types
- [ ] Connection is never stored — passed per-call only
- [ ] Result types: flat `field: type` map for projections, or model reference for full nodes
- [ ] Tests with mocked GQLAlchemy database client

---

### E8.3: Package Structure and Public API

Expose the GQLAlchemy catalogue cleanly.

**Acceptance criteria:**
- [ ] `from orthograph.catalogue import GqlAlchemyQueryCatalogue` works
- [ ] Lives in `src/orthograph/catalogue/gqlalchemy.py`
- [ ] Optional dependency: only importable when `gqlalchemy` extra installed
- [ ] Notebook demonstrates registration and execution pattern

---

## Relationship to Other Epics

- **E6** provides the registry interface pattern this epic follows
- **E11** populates this catalogue with auto-generated operations
- **E12** extracts the shared ABC after both E6 and E8 are complete
- **E9** must be complete to establish the composition boundary that this catalogue respects
