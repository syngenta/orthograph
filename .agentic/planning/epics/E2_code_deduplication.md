# Epic E2: Code Deduplication & Internal Quality

> **Priority:** Medium
> **Origin:** Code review 2026-05-07 (section 6: Redundancy)
> **Goal:** Eliminate duplicated logic, improve maintainability, reduce future bug surface
> **Estimated tasks:** 4

---

## Context

The codebase has several instances of duplicated logic that emerged naturally
during incremental development (each extension was built independently). Now
that the architecture is stable, these duplications should be consolidated.
The risk of not doing this: a bug fix in one location is forgotten in the
duplicate, or a refactor becomes unnecessarily complex because the same
logic exists in multiple places.

---

## Task E2.1: Extract Shared `EntityModel` Base (Property Spec Methods)

**Objective:** Eliminate the duplicated `get_property_specs()`, `get_required_property_names()`, and `get_all_property_names()` classmethods that exist identically on both `NodeModel` and `RelationshipModel`.

**Context:** Both `NodeModel` (`core/node_model.py:36-53`) and `RelationshipModel` (`core/relationship_model.py:56-72`) have three identical classmethods. These methods introspect Pydantic type hints and return property metadata. The duplication is ~30 lines of logic repeated verbatim.

**Implementation:**

1. Create a mixin class in `src/orthograph/core/types.py` (or a new `src/orthograph/core/base.py`):

```python
class PropertySpecMixin:
    """Mixin providing property introspection methods for graph entity models."""

    @classmethod
    def get_property_specs(cls) -> dict[str, TypeInfo]:
        """Return TypeInfo for each declared property field."""
        hints = get_type_hints(cls)
        result: dict[str, TypeInfo] = {}
        for name, annotation in hints.items():
            if name.startswith("_"):
                continue
            result[name] = resolve_type_info(annotation)
        return result

    @classmethod
    def get_required_property_names(cls) -> set[str]:
        """Return names of required (non-optional) properties."""
        specs = cls.get_property_specs()
        return {name for name, info in specs.items() if info.is_required}

    @classmethod
    def get_all_property_names(cls) -> set[str]:
        """Return names of all declared properties."""
        return set(cls.get_property_specs().keys())
```

2. Modify `NodeModel` and `RelationshipModel` to inherit from both `BaseModel` and `PropertySpecMixin`:

```python
class NodeModel(PropertySpecMixin, BaseModel):
    ...
```

3. Remove the duplicated method bodies from both classes.

4. Verify that the `_HasPropertySpecs` protocol in `extensions/validation.py` still matches (it should, since the method signatures are unchanged).

5. Run all 369 tests -- no behavioral change expected.

**Acceptance criteria:**
- `NodeModel.get_property_specs()` and `RelationshipModel.get_property_specs()` work identically to before
- The duplicated logic exists in exactly one place
- `extensions/validation.py`'s `_HasPropertySpecs` protocol still works
- All existing tests pass unchanged

---

## Task E2.2: Extract Shared `_pick_primary_label()` Utility

**Objective:** Consolidate the duplicated `_pick_primary_label()` function that exists in both `neo4j/result_adapter.py` and `gqlalchemy/result_adapter.py`.

**Context:** Both result adapters need to select a primary label from a multi-label node by matching against model labels. The logic is identical: prefer model-matching labels, alphabetical fallback. Having this in two places means a bug fix in one won't propagate to the other.

**Implementation:**

1. Create `src/orthograph/extensions/utils.py`:

```python
"""Shared utilities for extension subpackages."""

from orthograph.core.graph_data_model import GraphDataModel


def pick_primary_label(
    labels: frozenset[str] | set[str],
    model: GraphDataModel,
) -> str:
    """Select the primary label from a multi-label node.

    Prefers labels that match the model. Falls back to alphabetical
    sorting if no model match or multiple matches exist.
    """
    model_labels = model.node_labels
    matching = set(labels) & model_labels
    if len(matching) == 1:
        return next(iter(matching))
    if len(matching) > 1:
        return sorted(matching)[0]
    return sorted(labels)[0] if labels else "__unknown__"
```

2. Update `neo4j/result_adapter.py` to import and use `pick_primary_label` from `extensions/utils.py`. Remove the local `_pick_primary_label()` function.

3. Update `gqlalchemy/result_adapter.py` to import and use `pick_primary_label` from `extensions/utils.py`. Remove the local `_pick_primary_label()` function.

4. Add tests in `tests/extensions/test_utils.py`:
   - `test_pick_primary_label_single_match`
   - `test_pick_primary_label_multiple_matches_alphabetical`
   - `test_pick_primary_label_no_match_fallback`
   - `test_pick_primary_label_empty_labels`

5. Verify existing tests in `tests/extensions/neo4j/test_result_adapter.py` and `tests/extensions/gqlalchemy/test_result_adapter.py` still pass.

**Acceptance criteria:**
- `_pick_primary_label` exists in exactly one location
- Both result adapters use the shared version
- All existing tests pass unchanged
- New unit tests cover the shared function directly

---

## Task E2.3: Extract Shared `_format_cardinality()` Utility

**Objective:** Consolidate the duplicated `_format_cardinality()` helper used in both visualization renderers.

**Context:** `visualization/mermaid.py:9-12` and `visualization/text.py:9-12` contain identical functions that format a `CardinalitySpec` as a string like `"0..*"` or `"1..1"`. This is a natural method on `CardinalitySpec` itself.

**Implementation:**

Option A (preferred): Add a `display()` or `__str__` method to `CardinalitySpec`:

1. In `src/orthograph/core/types.py`, add to `CardinalitySpec`:

```python
def display(self) -> str:
    """Format as compact notation (e.g., '0..1', '1..*')."""
    max_str = "*" if self.max is None else str(self.max)
    return f"{self.min}..{max_str}"
```

2. Update `visualization/mermaid.py` and `visualization/text.py` to call `spec.display()` instead of the local `_format_cardinality(spec)`.

3. Remove both local `_format_cardinality()` functions.

4. Add test in `tests/core/test_types.py`:
   - `test_cardinality_spec_display_bounded`
   - `test_cardinality_spec_display_unbounded`

**Acceptance criteria:**
- `CardinalitySpec(min=0, max=1).display()` returns `"0..1"`
- `CardinalitySpec(min=1, max=None).display()` returns `"1..*"`
- Both visualization modules use the new method
- No local `_format_cardinality()` duplicates remain
- All existing tests pass

---

## Task E2.4: Consolidate Neo4j QueryStrategy Shared Methods

**Objective:** Eliminate the 4 identical method implementations shared between `ApocQueryStrategy` and `CypherQueryStrategy`.

**Context:** In `extensions/neo4j/queries.py`, both strategy classes have identical implementations for `node_labels()`, `rel_types()`, `cardinality()`, and `constraints()`. Only `node_properties()` and `rel_properties()` differ. This means a query change (e.g., for a new Neo4j version) must be applied twice.

**Implementation:**

1. In `src/orthograph/extensions/neo4j/queries.py`, introduce a base class:

```python
class _BaseQueryStrategy:
    """Shared queries that work for both APOC and pure-Cypher approaches."""

    def node_labels(self) -> str:
        return "CALL db.labels() YIELD label RETURN label"

    def rel_types(self) -> str:
        return "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"

    def cardinality(self, label: str, rel_type: str) -> str:
        return (
            f"MATCH (n:`{label}`) "
            f"OPTIONAL MATCH (n)-[r:`{rel_type}`]->() "
            "WITH n, count(r) AS degree "
            "RETURN min(degree) AS min_degree, max(degree) AS max_degree, "
            "avg(degree) AS avg_degree, count(n) AS sample_size"
        )

    def constraints(self) -> str:
        return (
            "SHOW CONSTRAINTS YIELD name, type, entityType, "
            "labelsOrTypes, properties, propertyType"
        )


class ApocQueryStrategy(_BaseQueryStrategy):
    """Uses APOC procedures for rich metadata."""

    def node_properties(self, label: str) -> str: ...
    def rel_properties(self, rel_type: str) -> str: ...


class CypherQueryStrategy(_BaseQueryStrategy):
    """Pure Cypher fallback when APOC is unavailable."""

    def node_properties(self, label: str) -> str: ...
    def rel_properties(self, rel_type: str) -> str: ...
```

2. Remove the duplicated method bodies from both concrete classes.

3. Ensure `QueryStrategy` protocol is still satisfied (structural typing -- the base class satisfies it by having all required methods).

4. Run existing tests in `tests/extensions/neo4j/` -- no behavioral change.

**Acceptance criteria:**
- Shared query logic exists in one place
- Both strategy classes still satisfy the `QueryStrategy` protocol
- All existing tests pass unchanged
