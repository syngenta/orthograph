# Epic E18: Validation Correctness

> **Priority:** High
> **Origin:** Code review 2026-06-09 (review of current branch changes)
> **Goal:** Fix silent validation failures and API breakage identified in code review
> **Blocked by:** none
> **User stories:** 5

---

## Context

A code review of the current branch identified five issues that are unrelated to
the branch's intent and should be addressed independently. Three are correctness
bugs that cause validation checks to silently produce no output; one is a minor
warning-plumbing issue; one is a breaking public-API removal without a deprecation
path.

---

## Tasks

### E18.1: Populate `source_labels` / `target_labels` in `Neo4jInspector._build_rel_profile`

`_build_rel_profile` (`src/orthograph/extensions/neo4j/inspector.py:124-170`) returns
a `RelationshipTypeProfile` with both `source_labels` and `target_labels` as empty
sets. This causes `_check_rel_endpoints` (`validation.py:268,288`) to iterate over
nothing and never emit `INVALID_ENDPOINT` errors for any Neo4j-sourced profile.

The `NetworkxInspector` collects these correctly from graph edges (`inspector.py:84-92`).
A new query method must be added to both `ApocQueryStrategy` and `CypherQueryStrategy`
to retrieve start/end node labels for a given relationship type, and the results must
be stored in the profile.

**Acceptance criteria:**
- [ ] `_build_rel_profile` sets `source_labels` and `target_labels` from a live Neo4j query
- [ ] Both `ApocQueryStrategy` and `CypherQueryStrategy` expose the new method
- [ ] `INVALID_ENDPOINT` violations are emitted when a relationship connects unexpected node labels
- [ ] Existing validation tests continue to pass

---

### E18.2: Validate `max_degree` in cardinality check

`_check_cardinality` (`src/orthograph/extensions/validation.py:323`) only checks
`stats.min_degree` against `src_card`. `stats.max_degree` is never tested, so
upper-bound cardinality violations (e.g. `Cardinality.ONE` with observed `max_degree=5`)
are silently ignored.

The fix is to test both bounds:

```python
if not src_card.contains(stats.min_degree) or not src_card.contains(stats.max_degree):
```

**Acceptance criteria:**
- [ ] Cardinality violations are raised when `max_degree` exceeds the declared upper bound
- [ ] Existing cardinality tests continue to pass
- [ ] A test is added that triggers the violation via `max_degree` only

---

### E18.3: Fix `<br>` in Mermaid pipe labels

`model_to_mermaid` (`src/orthograph/visualization/mermaid.py:108-109`) joins edge
label parts with `"<br>"` and inserts them inside pipe labels (`-->|label|`). Mermaid
pipe labels do not support HTML tags; `<br>` is rendered as literal text and can break
parsing in some Mermaid versions. The docstring claims "All output uses Mermaid-safe
syntax", which is false for multi-part edge labels.

**Acceptance criteria:**
- [ ] Edge labels use a Mermaid-safe separator (e.g. space or `/`) instead of `<br>`
- [ ] Docstring is updated to accurately describe the output format
- [ ] Existing visualization tests pass

---

### E18.4: Fix `warnings.warn` `stacklevel` in `_validate_declarative_cypher`

`_validate_declarative_cypher` (`src/orthograph/extensions/cypher/base_models.py:106`)
calls `warnings.warn(..., stacklevel=2)`. The call chain at class definition time is:

```
user class definition
  → CypherReadQuery.__init_subclass__
    → _validate_declarative_cypher   ← warns here
```

`stacklevel=2` points to the `__init_subclass__` call site inside the framework, not
to the user's class definition. The correct value is `stacklevel=3`.

**Acceptance criteria:**
- [ ] `stacklevel` changed to `3`
- [ ] Warning points to the user's subclass definition in test output

---

### E18.5: Restore `validate_networkx_graph` with deprecation shim

`validate_networkx_graph` was removed from `src/orthograph/extensions/networkx/__init__.py`
without a deprecation period. Any downstream code importing
`from orthograph.extensions.networkx import validate_networkx_graph` will get an
`ImportError` on upgrade.

**Acceptance criteria:**
- [ ] `validate_networkx_graph` is re-exported from the networkx extension `__init__.py`
- [ ] The shim emits a `DeprecationWarning` directing callers to the new API
- [ ] A test verifies the warning is raised and the function still works
- [ ] The deprecation shim is removed no earlier than the next minor version bump
