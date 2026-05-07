# Epic E1: API Ergonomics & Developer Experience

> **Priority:** High
> **Origin:** Code review 2026-05-07 (section 7: API Ergonomics)
> **Goal:** Reduce friction in the most common user workflows without breaking existing API
> **Estimated tasks:** 5

---

## Context

The current API is functional and well-typed, but users face unnecessary
ceremony in the most common workflows: validating a single node requires
wrapping in a list, saving a node via GQLAlchemy requires passing the label
separately from the dict (contradicting the convention used everywhere else),
and discovering profile validation requires knowing about a free function in
a subpackage. These friction points accumulate and make the library feel
heavier than it needs to be.

---

## Task E1.1: Add Singular Validation Methods

**Objective:** Add `validate_node()` and `validate_relationship()` convenience methods to `GraphValidator` that accept a single item (dict or model instance) and return a `ValidationResult`.

**Context:** Currently `validate_nodes()` and `validate_relationships()` only accept `Sequence[...]`. The most common use case in notebooks and application code is validating a single entity before saving. Users must write `validator.validate_nodes([node_dict])` -- the list wrapping is pure boilerplate.

**Implementation:**

1. In `src/orthograph/core/validator.py`, add two new public methods:

```python
def validate_node(
    self,
    node: dict[str, Any] | NodeModel,
) -> ValidationResult:
    """Validate a single node against the model."""
    return self.validate_nodes([node])

def validate_relationship(
    self,
    relationship: dict[str, Any] | RelationshipModel,
) -> ValidationResult:
    """Validate a single relationship against the model."""
    return self.validate_relationships([relationship])
```

2. Add these to the `__all__` exports if applicable (they're methods, so this is just about documentation).

3. Add tests in `tests/core/test_validator.py`:
   - `test_validate_node_valid_dict`
   - `test_validate_node_invalid_dict`
   - `test_validate_node_model_instance`
   - `test_validate_relationship_valid_dict`
   - `test_validate_relationship_invalid_dict`

4. Update notebook 01.02 to show the singular form alongside the plural.

**Acceptance criteria:**
- `validator.validate_node({"__label__": "Person", "name": "Alice", "age": 30})` returns a valid `ValidationResult`
- Existing plural methods unchanged
- All existing tests pass
- New tests pass

---

## Task E1.2: Add `GraphDataModel.validate()` Convenience Method

**Objective:** Add a thin delegation method on `GraphDataModel` so users can validate data without manually constructing a `GraphValidator`.

**Context:** The common workflow in every notebook is: `model = GraphDataModel(...)` then `validator = GraphValidator(model)` then `validator.validate(...)`. For simple cases, the intermediate `GraphValidator` instantiation is unnecessary ceremony. A convenience method directly on the model reduces the common path to two steps.

**Implementation:**

1. In `src/orthograph/core/graph_data_model.py`, add:

```python
def validate(
    self,
    nodes: Sequence[dict[str, Any] | NodeModel],
    relationships: Sequence[dict[str, Any] | RelationshipModel] | None = None,
) -> ValidationResult:
    """Validate graph data against this model.

    Convenience method that creates a GraphValidator internally.
    For repeated validation, prefer constructing a GraphValidator directly.
    """
    from orthograph.core.validator import GraphValidator
    return GraphValidator(self).validate(nodes, relationships)
```

2. Add to imports in `src/orthograph/__init__.py` if needed (it's a method on an already-exported class, so no import changes needed).

3. Add tests in `tests/core/test_graph_data_model.py`:
   - `test_model_validate_convenience_valid`
   - `test_model_validate_convenience_invalid`
   - `test_model_validate_convenience_no_relationships`

4. Add a note in notebook 01.02 showing both approaches.

**Acceptance criteria:**
- `model.validate(nodes=[...], relationships=[...])` returns same result as `GraphValidator(model).validate(...)`
- Docstring clearly states this is a convenience wrapper
- All existing tests pass

---

## Task E1.3: Support `__label__` in Dict for `GqlAlchemyClient.save_node()`

**Objective:** Allow `save_node()` to infer the node type from `__label__` in the data dict, matching the convention used everywhere else in the library.

**Context:** Currently `save_node(data, node_type="Person")` requires passing the label separately, while everywhere else in orthograph the label is inside the dict as `__label__`. This inconsistency forces users to remember two conventions. The fix: support both -- if `node_type` is provided it takes precedence; if not, look for `__label__` in the dict.

**Implementation:**

1. In `src/orthograph/extensions/gqlalchemy/client.py`, modify `save_node()`:

```python
def save_node(
    self,
    data: dict[str, Any],
    node_type: str | None = None,
) -> Any:
    # Resolve node_type from parameter or dict
    resolved_type = node_type or data.get("__label__")
    if resolved_type is None:
        raise ValueError(
            "node_type must be provided either as parameter or as '__label__' in data"
        )
    # Strip __label__ from data before passing to GQLAlchemy
    clean_data = {k: v for k, v in data.items() if k != "__label__"}
    # ... rest of validation and save logic uses resolved_type and clean_data
```

2. Apply the same pattern to `save_relationship()` for `rel_type`.

3. Add tests in `tests/extensions/gqlalchemy/test_client.py`:
   - `test_save_node_label_from_dict`
   - `test_save_node_label_from_parameter_overrides_dict`
   - `test_save_node_no_label_raises`
   - `test_save_relationship_label_from_dict`

4. Update notebook 03.04 to show both styles.

**Acceptance criteria:**
- `client.save_node({"__label__": "Person", "name": "Alice", "born": 1985})` works
- `client.save_node({"name": "Alice", "born": 1985}, node_type="Person")` still works
- Parameter takes precedence over dict key when both present
- Missing both raises `ValueError` with clear message
- All existing tests pass

---

## Task E1.4: Add `model.validate_profile()` Delegation

**Objective:** Make profile validation discoverable from the `GraphDataModel` object by adding a thin delegation method.

**Context:** `validate_profile()` lives in `extensions/validation.py` as a free function. A user holding a `GraphDataModel` instance has no way to discover that profile validation exists without reading documentation. Adding a method on the model improves discoverability while keeping the implementation in extensions.

**Implementation:**

1. In `src/orthograph/core/graph_data_model.py`, add:

```python
def validate_profile(self, profile: "GraphProfile") -> "ValidationResult":
    """Validate a GraphProfile against this model.

    Delegates to orthograph.extensions.validation.validate_profile().
    Requires the extensions package.
    """
    from orthograph.extensions.validation import validate_profile
    return validate_profile(profile, self)
```

2. Use a string annotation for `GraphProfile` to avoid circular imports (or use `TYPE_CHECKING`).

3. Add test in `tests/core/test_graph_data_model.py`:
   - `test_validate_profile_delegation`

4. Update notebook 03.01 to show the method-based approach alongside the function-based one.

**Acceptance criteria:**
- `model.validate_profile(profile)` returns same result as `validate_profile(profile, model)`
- No circular import issues
- All existing tests pass

---

## Task E1.5: Improve Relationship Data Input (Alternative Formats)

**Objective:** Accept relationship data as `(source_uid, target_uid, label, props)` tuples in addition to the current dict format with magic keys.

**Context:** The dict format with `__source_uid__`, `__target_uid__`, `__label__` is the primary ergonomic friction point in the API. Every relationship dict requires 3 magic keys that feel like an interchange format leaked into the user API. Supporting tuples as an alternative input reduces boilerplate without breaking existing code.

**Implementation:**

1. In `src/orthograph/core/validator.py`, modify the type signature and `_to_rel_dict` to accept tuples:

```python
RelInput = dict[str, Any] | RelationshipModel | tuple[str, str, str, dict[str, Any]]

@staticmethod
def _to_rel_dict(rel: RelInput) -> dict[str, Any]:
    if isinstance(rel, tuple):
        src_uid, tgt_uid, label, props = rel
        return {"__source_uid__": src_uid, "__target_uid__": tgt_uid, "__label__": label, **props}
    # ... existing logic
```

2. Update the type annotation on `validate()` and `validate_relationships()`.

3. Add tests:
   - `test_validate_relationship_tuple_format`
   - `test_validate_mixed_formats`

4. Update notebook 01.02 to show the tuple format as an alternative.

5. Update `CypherGenerator` to accept tuples for `create_relationship()` / `merge_relationship()` as well.

**Acceptance criteria:**
- `validator.validate(nodes, [("alice", "inception", "ACTED_IN", {"role": "Cobb"})])` works identically to the dict format
- Dict format unchanged and still works
- Type annotations are correct for both formats
- All existing tests pass
