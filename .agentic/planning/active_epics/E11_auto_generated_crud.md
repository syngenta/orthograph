# Epic E11: Auto-Generated CRUD Operations

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Derive standard CRUD and janitor queries automatically from a GraphDataModel, pre-populating catalogues
> **Blocked by:** E6 (Cypher catalogue must exist), E8 (GQLAlchemy catalogue must exist), E17 (CypherGenerator must be hardened and emit typed query objects)
> **User stories:** 9

---

## Context

Most graph applications need the same boilerplate operations for each node and
relationship type: get by UID, merge/upsert, create, delete, match by label.
Rather than requiring every consuming project to hand-write these, Orthograph
can auto-generate them from the schema.

This epic leverages the existing `CypherGenerator` (which already generates
individual statements) and wraps its output into catalogue entries. For
GQLAlchemy, it produces equivalent builder expressions.

---

## Tasks

### E11.1: Auto-Generate Cypher CRUD Catalogue

Given a `GraphDataModel`, produce a `CypherQueryCatalogue` pre-populated with standard operations per node/relationship type.

**Operations per node type:**
- `get_{label}_by_uid` — MATCH by UID field
- `merge_{label}` — MERGE with all properties
- `create_{label}` — CREATE with all properties
- `delete_{label}_by_uid` — DELETE by UID field
- `match_all_{label}` — MATCH all nodes of label
- `create_{label}_uniqueness_constraint` — constraint DDL

**Operations per relationship type:**
- `create_{rel_type}` — CREATE relationship between source/target by UID
- `merge_{rel_type}` — MERGE relationship
- `match_{rel_type}` — MATCH relationships of type

**Acceptance criteria:**
- [ ] `generate_cypher_crud_catalogue(model) -> CypherQueryCatalogue` returns populated catalogue
- [ ] Generated queries pass `validate_cypher()` against the model
- [ ] All generated queries have correct parameter declarations
- [ ] Tests validate generated Cypher correctness for a sample model

---

### E11.2: Auto-Generate GQLAlchemy CRUD Catalogue

Same operations expressed as GQLAlchemy builder expressions.

**Acceptance criteria:**
- [ ] `generate_gqlalchemy_crud_catalogue(model) -> GqlAlchemyQueryCatalogue` returns populated catalogue
- [ ] Generated queries are valid GQLAlchemy builder expressions
- [ ] Tests validate execution against mocked database client

---

### E11.3: Convenience Factory — Combined Catalogue

Provide a single factory that creates a catalogue with CRUD operations already registered, ready for the consuming project to add custom queries on top.

**Acceptance criteria:**
- [ ] `CypherQueryCatalogue.with_crud(model)` returns catalogue with CRUD pre-loaded
- [ ] `GqlAlchemyQueryCatalogue.with_crud(model)` same for GQLAlchemy
- [ ] Custom queries can be registered on top of auto-generated ones
- [ ] Notebook demonstrates: create with CRUD, then add custom queries
