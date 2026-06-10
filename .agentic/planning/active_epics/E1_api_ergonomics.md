# Epic E1: API Ergonomics & Developer Experience

> **Priority:** High
> **Origin:** Code review 2026-05-07 (section 7: API Ergonomics)
> **Goal:** Reduce friction in the most common user workflows without breaking existing API
> **Blocked by:** None — can start immediately
> **User stories:** 3, 4, 20

---

## Context

The current API is functional and well-typed, but users face unnecessary
ceremony in the most common workflows: validating a single node requires
wrapping in a list, discovering profile validation requires knowing about
a free function in a subpackage. These friction points accumulate and make
the library feel heavier than it needs to be.

---

## Tasks

### E1.1: Add Singular Validation Methods

Add `validate_node()` and `validate_relationship()` convenience methods to `GraphValidator` that accept a single item and return a `ValidationResult`.

**Acceptance criteria:**
- [ ] `validator.validate_node({"__label__": "Person", "name": "Alice"})` returns valid result
- [ ] Existing plural methods unchanged
- [ ] Tests cover valid/invalid dicts and model instances

---

### E1.2: Add `GraphDataModel.validate()` Convenience Method

Thin delegation method on `GraphDataModel` that creates a `GraphValidator` internally for one-off validation without manual construction.

**Acceptance criteria:**
- [ ] `model.validate(nodes=[...], relationships=[...])` returns same result as `GraphValidator(model).validate(...)`
- [ ] Docstring states this is a convenience wrapper
- [ ] Tests confirm equivalence

---

### E1.3: Add `model.validate_profile()` Delegation

Make profile validation discoverable from the `GraphDataModel` object by adding a delegation to `extensions.validation.validate_profile()`.

**Acceptance criteria:**
- [ ] `model.validate_profile(profile)` returns same result as `validate_profile(profile, model)`
- [ ] No circular import issues
- [ ] Tests confirm equivalence

---

### E1.4: Improve Relationship Data Input (Tuple Format)

Accept relationship data as `(source_uid, target_uid, label, props)` tuples in addition to the dict format.

**Acceptance criteria:**
- [ ] `validator.validate(nodes, [("alice", "inception", "ACTED_IN", {"role": "Cobb"})])` works
- [ ] Dict format unchanged and still works
- [ ] Type annotations correct for both formats
- [ ] Tests cover tuple, dict, and mixed input

---

## Removed (superseded)

- ~~E1.3 (old): Support `__label__` in Dict for `GqlAlchemyClient.save_node()`~~ — superseded by E9 (GQLAlchemy Client Review). The `save_*` methods are being reconsidered under the composition approach.
