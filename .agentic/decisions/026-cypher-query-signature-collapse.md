# CypherQuery Signature Collapse — `Params` + `Identifiers` Only, JSON-Schema Round-Trip Wire Format

**Status:** Accepted — 2026-06-18
**Epic:** E38 — CypherQuery Signature Collapse
**Produced by:** E38 T1–T9

---

## Context

`CypherQuery` (the simple / file-authored path) carried three overlapping ways to declare
"what parameters does this query take":

```python
query_args_required: list[str]                  # Noctis-derived authoring style
query_args_optional: list[str]                  # Noctis-derived authoring style
Params: type[BaseModel] | None                  # orthograph typed-contract style
```

This redundancy existed for historical reasons (Noctis-style file authoring) but created
three maintenance burdens:

1. **Drift detection:** `_check_spec_consistency` policed conflicts between the lists and
   a declared `Params` model. Inconsistency was only caught at validation time, not
   definition time.
2. **Two sources of truth:** `query_args_required` and `query_args_optional` had to be
   kept in sync with `Params` field defaults manually.
3. **File authoring limitation:** A Python class cannot be written to YAML, so the lists
   were the only way to author queries in YAML.

However, the equivalence was proven by the codebase:
- `_make_passthrough_params_model()` mechanically converted the two lists into a
  `create_model()` model with `(Any, ...)` for required and `(Any, None)` for optional.
- The typed path (`CypherReadQuery` / `CypherWriteQuery`) already declared only `Params` +
  `Identifiers`, required/optional via field defaults.

---

## Decision

### 1. Single typed source: `Params` (required) + `Identifiers` (optional)

Remove `query_args_required` and `query_args_optional` entirely. Collapse to:

```python
class CypherQuery(BaseModel):
    name: str = Field(..., alias="query_name")
    cypher_template: str                         # renamed from `cypher` (no alias)
    description: str | None = None
    Params: type[BaseModel]                      # REQUIRED; use NoParams for zero-arg
    Identifiers: type[BaseModel] | None = None
    identifiers: BaseModel | None = None         # bound instance (unchanged)
```

This makes the simple path a **strict subset** of the typed path (`CypherReadQuery` /
`CypherWriteQuery`), closing the architecture gap.

### 2. File authoring via JSON Schema wire format, not name lists

The requirement "queries must be writable to YAML" is preserved by round-tripping `Params`
and `Identifiers` through **JSON Schema** instead of plain string lists.

**Wire format (YAML/JSON):**

```yaml
- name: movies_by_year
  cypher_template: "MATCH (m:Movie {released: $released}) RETURN m.title"
  description: "Movies released in a given year"
  params_schema:
    title: MovieByYearParams
    type: object
    properties:
      released: {type: integer, title: Released}
      limit: {type: integer, title: Limit, default: 10}
    required: [released]
  identifiers_schema:                           # optional
    title: MovieIdentifiers
    type: object
    properties:
      label: {type: string, title: Label}
    required: [label]
```

**Round-trip implementation:**

- **Write (object → file):** `Params.model_json_schema()` via a Pydantic field serializer.
  Same for `Identifiers`.
- **Read (file → object):** `params_schema` dict → `model_from_json_schema()` →
  `create_model(...)` → passed as `Params=`. Same for `identifiers_schema` → `Identifiers=`.
- **Supported types:** Scalars only (`int`, `str`, `float`, `bool`). Nested objects,
  arrays, enums, and `$ref` raise `CypherQueryDefinitionError` (loud, never silent `Any`).
  Non-scalar queries must use the typed path (`CypherReadQuery` / `CypherWriteQuery`).

### 3. Field rename: `cypher` → `cypher_template` (no alias)

The `cypher` field name conflicted with the module path (`orthograph.cypher`). Rename to
`cypher_template` (matches the typed path naming) with **no alias** — the old field name is
not accepted.

Legacy support: `query_name` alias on `name` is kept for file loader compatibility; `cypher`
/ `query` aliases are removed.

### 4. Derive required/optional from `Params.model_fields` at runtime

The `list_arguments()` method now derives `required` and `optional` from
`Params.model_fields` (via `field.is_required()`) instead of from the removed lists.

### 5. Validation timing unchanged

The simple path (`CypherQuery`) still validates at `validate_query()` time (runtime /
call site), not class-definition time like the typed path. The `cypher_template` rename
does not change this contract — this is a deliberate design difference (file-authored
queries are not trusted until first use; typed queries are validated at definition site).

---

## Rationale

### Why collapse now?

1. **Internal consistency:** E36–E37 unified the typed and simple paths on shared
   `validate_cypher_spec` core. The signature difference was the last remaining gap.
2. **Removes maintenance burden:** No more `_check_spec_consistency` drift detection.
   Single source of truth (`Params` model).
3. **Enables better tooling:** A single typed source + JSON-Schema serialization enables
   IDE autocomplete, validation hooks, and catalogue introspection without string-key
   dispatch.
4. **No back-compat loss in practice:** The typed path (production use) was already
   orthogonal to `query_args_*`. File-authored queries are testing / onboarding tool;
   production code uses the typed path or the query catalogue.

### Why JSON Schema instead of keeping name lists?

1. **Symmetry with catalogue introspection:** `QueryCatalogue.describe()` already
   serializes `Params.model_json_schema()` for IDE discovery.
2. **Type preservation:** JSON Schema preserves field type, default, and required/optional
   semantics. Name lists do not.
3. **Standards alignment:** JSON Schema is a widely-understood, machine-readable contract;
   name lists are orthograph-specific.
4. **Extensibility:** Adding field constraints (min/max/regex) in the future is easier
   with JSON Schema than with name lists.

### Why scalars only in the simple path?

Complex types (nested objects, arrays) are rare in production Cypher queries. The typed
path (`CypherReadQuery` / `CypherWriteQuery`) is available for those cases. Restricting
the file-authored path to scalars simplifies the codec and error messages.

### Why no back-compat alias for `cypher`?

1. `orthograph.cypher` (module) vs `cypher` (field) is a naming collision.
2. The field is used mainly in tests and onboarding notebooks, not production code.
3. E36–E37 already introduced `cypher_template` on the typed path; consistency is better.

---

## Rejected Alternatives

1. **Keep `query_args_*` lists + add `Params` alongside:** Maintains drift and confusion.
   Rejected.
2. **Serialize `Params` directly to YAML as a Python class string:** Not feasible (YAML
   does not have a standard Python object representation).
3. **Use a custom schema format (not JSON Schema):** JSON Schema is already a standard;
   no benefit to inventing a new one.
4. **Provide a back-compat alias for `cypher`:** Adds a naming collision and masks the
   refactoring. Rejected.

---

## Testing & Validation

- **Schema codec round-trip:** `model_to_json_schema()` ↔ `model_from_json_schema()` with
  scalar-type coverage and unsupported-construct error handling (test_schema_codec.py).
- **File loader:** Reads `cypher_template` + `params_schema` and reconstructs typed models
  (test_query_catalogue_yaml.py).
- **Validator alignment:** Simple and typed paths produce identical results on the same
  query (test_query.py, `test_cypher_query_validate_parity_with_typed_query`).
- **Round-trip tests:** Python → YAML → Python produces equivalent `CypherQuery`
  (test_query.py, new tests in E38 T9).

---

## Consequences

### Immediate

- `CypherQuery` signature is now aligned with `CypherReadQuery` / `CypherWriteQuery`.
- File-authored queries use JSON-Schema `params_schema` and `identifiers_schema` keys
  (YAML / JSON format change).
- Zero references to `query_args_required`, `query_args_optional`, or `.cypher` attribute
  remain in `src/` or `tests/`.
- 1103 tests pass; 2 new round-trip tests added.

### Long-term

- Simpler mental model: one parameter representation across all three query types.
- Catalogue introspection becomes uniform: all queries (simple, typed, catalogue) expose
  `Params` + `Identifiers` + JSON-Schema serialization.
- Future: could add constraint validation (min/max/regex) via JSON-Schema extensions
  without API change.

---

## References

- **E36:** CypherQuery Naming Convergence + Class-Based Query Definitions (2026-06-17)
- **E37:** Simple Cypher Query — Shared Validation, Catalogue Parity, and Executor
  (2026-06-17)
- **ADR-027:** Simple-path shared validation, catalogue registration, opt-in identifiers,
  and executor reuse (2026-06-17)
