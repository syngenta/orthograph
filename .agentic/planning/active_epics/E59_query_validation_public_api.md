# Epic E59: Query Validation Public API — Split and Expose the Three Validation Paths

> **Priority:** Low
> **Phase:** post-v0.1.0 — API ergonomics / public surface
> **Type:** Interface design + public surface change. Requires an ADR before any code.
> **Depends on:** E56 (distillation — done), E55 (public facade — done)
> **Blocks:** nothing currently

---

## Why This Epic Exists

The current public entry point for single-query validation is:

```python
# orthograph/queries.py
def validate_query(query: str | CypherQuery, definition: GraphDefinition) -> ValidationResult:
    if isinstance(query, CypherQuery):
        return _cypher_validation.validate_cypher_query(query, definition)
    return validate_cypher(query=query, graph_definition=definition)
```

This overloads two different things onto one name:

1. **Raw Cypher string** → syntax + domain check via `validate_cypher` (no param/identifier/output alignment).
2. **`CypherQuery` instance** → full spec validation via `validate_cypher_query` (parse + param alignment + identifier alignment + domain + injection INFO).

A **third path** exists internally but is not exposed:

3. **Typed `ReadQuery` / `WriteQuery` instance** → `validate_typed_cypher_query` (backend guard + template guard + injection guard + param/identifier/output alignment via `validate_cypher_spec`).

The overloaded `validate_query` hides the distinction. Consumers who have a typed query and want to validate it in isolation — without registering a catalogue — have no public verb. The third path has been prepared for exposure: `validate_typed_cypher_query` is already named without a leading underscore (E56 prep, 2026-06-28).

---

## Open Questions (decide before coding)

These are the questions an ADR must answer before any public surface change:

### Q1 — Split or overload?

**Option A — three distinct verbs** (recommended for clarity):
```python
validate_cypher(query: str, definition)          # raw string path (already public)
validate_cypher_query(query: CypherQuery, definition)   # CypherQuery path
validate_typed_cypher_query(query: ReadQuery | WriteQuery, definition)  # typed path
```
`validate_query` is either deprecated (with a shim) or removed.

**Option B — single overload, three accepted types**:
```python
validate_query(query: str | CypherQuery | ReadQuery | WriteQuery, definition)
```
Keeps one name; hides the distinct contracts; `isinstance` dispatch inside.

**Option C — keep `validate_query` for the two existing paths, add `validate_typed_query` alongside**:
No removal; just adds the missing third verb. Minimal breakage.

### Q2 — What does `validate_typed_cypher_query` accept?

Currently `validate_typed_cypher_query(query, graph_definition)` takes an *instance* and introspects its class for `Params`/`Identifiers`/`Output`. This is correct. The public signature should match — no argument shape change needed.

The non-Cypher-backend and imperative-template guards currently live inside the function and return `QUERY_UNVERIFIABLE`. For a public verb these are valid returns (not exceptions). Confirm that contract is right for callers who call this directly (vs. through `validate_catalogue`).

### Q3 — `definition: GraphDefinition | None`?

`validate_cypher_query` already accepts `None` for syntactic-only checks. Should `validate_typed_cypher_query` support the same? Currently it requires a `GraphDefinition` (the typed path always validates against the model). Decision: keep required, or align with `CypherQuery` path?

### Q4 — Public module location

All three verbs currently live in `orthograph.cypher.validation` (internal) and are re-exported via `orthograph.queries`. After this epic, `validate_typed_cypher_query` needs to be added to `queries.__all__` and the module docstring updated to describe all three paths.

### Q5 — `validate_query` deprecation path

If Q1 resolves to Option A, `validate_query` is the old overloaded name. Decision: hard remove (breaking), soft deprecation with a shim + warning, or keep as an alias indefinitely?

---

## What Was Done in E56 to Prepare

- `_validate_typed_query` renamed to `validate_typed_cypher_query` (underscore dropped, 2026-06-28). It is now importable and has a stable public-grade name.
- `validate_cypher_query` (was `validate_query`) is the named internal function for the `CypherQuery` path.
- The internal call structure is: `validate_query_catalogue` → `isinstance` dispatch → `validate_cypher_query` or `validate_typed_cypher_query` directly. No indirection layer.

No public `__all__` change was made. `validate_query` in `queries.py` still delegates to `validate_cypher_query` internally.

---

## Proposed Tasks (after ADR)

#### E59.0 — ADR: decide Q1–Q5 — **Opus**
Record the decisions: which verbs are public, whether `validate_query` is kept/deprecated/removed, the `None`-definition question for the typed path, and the module location. No code.

#### E59.1 — Expose `validate_typed_cypher_query` on the public facade — **Sonnet**
Add to `queries.__all__`, add a wrapper function in `queries.py` with a user-facing docstring, add to the module docstring. Run surface tests + mypy.
*Precondition: E59.0 (ADR resolves Q2/Q3/Q4).*

#### E59.2 — Split or deprecate `validate_query` per ADR decision — **Sonnet**
If Option A: add `validate_cypher_query` to `__all__`; add or update `validate_query` shim with `DeprecationWarning`; update `test_root_surface.py` to assert both names callable. If Option C: no removal, just add the new verb.
*Precondition: E59.0.*

#### E59.3 — Update surface tests + notebooks — **Haiku**
`tests/surface/test_queries.py` + `tests/test_root_surface.py` + notebook cells that import `validate_query`. Update imports, add test coverage for the new verb.

---

## Success Criteria

- [ ] ADR records the decision on all five open questions.
- [ ] `orthograph.queries.validate_typed_cypher_query` is callable and documented.
- [ ] A newcomer reading `orthograph.queries` sees distinct verbs for distinct contracts — no hidden `isinstance` dispatch in the public surface.
- [ ] If `validate_query` is deprecated: a `DeprecationWarning` fires on import/call; existing consumers are not silently broken.
- [ ] `python -m pytest tests -q` green; `python -m mypy src/orthograph` clean; `tests/surface/test_queries.py` covers all three public validation paths.

---

## Out of Scope

- Changing `validate_cypher_spec` (internal primitive — not for direct public consumption).
- Changing `validate_catalogue` or `validate_catalogue_against_profile` (catalogue-level verbs are correct as-is).
- Any behaviour change to the three validation paths (guards, issues emitted, codes/severities).
