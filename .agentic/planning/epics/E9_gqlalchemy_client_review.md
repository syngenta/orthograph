# Epic E9: GQLAlchemy Client Review

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Align the GQLAlchemy extension with the validated composition pattern — Orthograph generates and validates, consuming projects persist
> **Blocked by:** None — can start immediately
> **Type:** HITL (requires review of downstream impact)
> **User stories:** 21

---

## Context

The grill session (2026-05-08) established that Orthograph's role with GQLAlchemy
is **validated composition**:
- Orthograph generates GQLAlchemy-compatible classes (codegen)
- Orthograph validates queries (query builder wrapper)
- Orthograph validates results (result adapter)
- **Consuming projects own the persistence call**

The current `GqlAlchemyClient` in `src/orthograph/extensions/gqlalchemy/client.py`
has `save_node()`, `save_relationship()`, and `execute()` methods that accept a
stored `db` connection and perform persistence. This couples validation lifecycle
to connection lifecycle and blurs the ownership boundary.

**Decision:** Remove or deprecate persistence methods. The extension should provide
codegen + validation + result adaptation only. A convenience facade can be added
later if pilot teams request it.

---

## Tasks

### E9.1: Audit Current GqlAlchemyClient Usage

Map all methods on `GqlAlchemyClient` and classify them:

- **Keep:** Methods that validate or generate (align with composition)
- **Remove/deprecate:** Methods that own persistence calls
- **Refactor:** Methods that mix validation with persistence (split them)

**Acceptance criteria:**
- [ ] Written analysis of each method with keep/remove/refactor classification
- [ ] Identification of any external consumers (notebooks, tests) that use `save_*` methods
- [ ] Migration path documented for each removed method

---

### E9.2: Remove Persistence Ownership from GqlAlchemyClient

Refactor the client to remove `save_node()`, `save_relationship()`, and any method that directly calls `db.save()` or `db.execute()` for persistence.

**Acceptance criteria:**
- [ ] `GqlAlchemyClient` no longer has `save_node()` or `save_relationship()` methods
- [ ] Connection (`db`) is no longer stored as instance state on the client
- [ ] Validation methods (`validate_node_data()`, `validate_relationship_data()`) remain and work independently
- [ ] Codegen functionality unchanged
- [ ] Result adapter functionality unchanged
- [ ] Tests updated — remove tests for deleted methods, add tests confirming no connection storage

---

### E9.3: Document Composition Pattern for Consuming Projects

Write clear documentation showing how consuming projects should use the extension:

```python
# Consuming project code:
from orthograph.extensions.gqlalchemy import generate_gqlalchemy_classes

gql_classes = generate_gqlalchemy_classes(my_model)
person = gql_classes.Person(name="Alice", born=1985)
person.save(db)  # GQLAlchemy's own method — consuming project owns this

# Validate results after query:
from orthograph.extensions.gqlalchemy import validate_gqa_result
result = db.execute_and_fetch("MATCH (p:Person) RETURN p")
validate_gqa_result(result, my_model)
```

**Acceptance criteria:**
- [ ] Docstrings on all remaining public methods explain the composition pattern
- [ ] Notebook `03.03` or `03.04` updated to show the new pattern
- [ ] Extension contract doc updated to reflect GQLAlchemy's revised role

---

## Downstream Impact

- **E4.1** (backend parameter) — still valid, but now applies to inspection methods only
- **E8** (GQLAlchemy Query Catalogue) — builds on the cleaned-up extension
- **E10** (Connection Audit) — this epic establishes the pattern E10 enforces
