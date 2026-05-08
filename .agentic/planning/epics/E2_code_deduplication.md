# Epic E2: Code Deduplication & Internal Quality

> **Priority:** Medium
> **Origin:** Code review 2026-05-07 (section 6: Redundancy)
> **Goal:** Eliminate duplicated logic, improve maintainability, reduce future bug surface
> **Blocked by:** None — can start immediately

---

## Context

The codebase has several instances of duplicated logic that emerged naturally
during incremental development (each extension was built independently). Now
that the architecture is stable, these duplications should be consolidated.
The risk of not doing this: a bug fix in one location is forgotten in the
duplicate, or a refactor becomes unnecessarily complex because the same
logic exists in multiple places.

---

## Tasks

### E2.1: Extract Shared `PropertySpecMixin`

Eliminate the duplicated `get_property_specs()`, `get_required_property_names()`, and `get_all_property_names()` classmethods that exist identically on both `NodeModel` and `RelationshipModel`.

**Acceptance criteria:**
- [ ] Shared logic exists in exactly one place (mixin or base)
- [ ] Both model classes inherit/use the shared methods
- [ ] `extensions/validation.py` protocol still satisfied
- [ ] All existing tests pass unchanged

---

### E2.2: Extract Shared `pick_primary_label()` Utility

Consolidate the duplicated label-picking function from `neo4j/result_adapter.py` and `gqlalchemy/result_adapter.py` into `extensions/utils.py`.

**Acceptance criteria:**
- [ ] Single implementation in `extensions/utils.py`
- [ ] Both result adapters import from shared location
- [ ] New unit tests cover the shared function directly
- [ ] All existing tests pass unchanged

---

### E2.3: Extract Shared `CardinalitySpec.display()` Method

Add a `display()` method to `CardinalitySpec` replacing the duplicated `_format_cardinality()` helper in both visualization modules.

**Acceptance criteria:**
- [ ] `CardinalitySpec(min=0, max=1).display()` returns `"0..1"`
- [ ] `CardinalitySpec(min=1, max=None).display()` returns `"1..*"`
- [ ] Both visualization modules use the new method
- [ ] No local duplicates remain

---

### E2.4: Consolidate Neo4j QueryStrategy Shared Methods

Extract a `_BaseQueryStrategy` class for the 4 identical methods shared between `ApocQueryStrategy` and `CypherQueryStrategy`.

**Acceptance criteria:**
- [ ] Shared query logic exists in one base class
- [ ] Both strategies still satisfy the `QueryStrategy` protocol
- [ ] All existing tests pass unchanged
