# Simple-path shared validation, catalogue registration, opt-in identifiers, and executor reuse

**Status:** Accepted — 2026-06-17
**Epic:** E37
**Produced by:** E37.1–E37.6

---

## Context

`CypherQuery` (the simple / YAML path) and `CypherReadQuery` / `CypherWriteQuery` (the
typed path) previously validated Cypher through two **non-aligned** validators:

- Simple path `CypherQuery.validate_query(def)` → `validate_cypher` only (semantic /
  domain checks). It skipped `$param` ↔ declared-arg alignment, `<<id>>` ↔ identifier
  alignment, and RETURN→Output.
- Typed path `validate_query_catalogue` → full four-axis (parse + param alignment +
  RETURN/Output + domain) + `QUERY_UNVERIFIABLE` classification.

Additionally, `CypherQuery` was a plain `BaseModel` with no `backend` tag and no
registration route into `QueryCatalogue`. A YAML-loaded query therefore never reached
`validate_query_catalogue`. A stale `$param` was caught only by the driver at runtime.

---

## Decisions

### 1. Shared `validate_cypher_spec` core

A single function `validate_cypher_spec` (in `cypher/validation.py`) validates a query
spec from primitives — `cypher: str`, `params_fields: set[str]`,
`identifier_fields: set[str]`, `graph_definition`, `output_model` — no class or instance
required. It composes **only existing helpers**:

- `parse_cypher` → `QUERY_PARSE_ERROR` on failure
- `_check_model_alignment` → `QUERY_PARAM_ALIGNMENT_ERROR` for `$param` / `<<id>>`
  alignment mismatches
- `validate_cypher` (semantic) when `graph_definition is not None`
- `extract_return_columns` + `_check_return_output_alignment` when `output_model is not None`
- `_check_identifier_injection` INFO

Both `CypherQuery.validate_query` and the `validate_query_catalogue` typed branch now call
this function. The typed-path emitted codes and severities are **unchanged**.

`_check_model_alignment` was refactored to accept `declared: set[str]` (field names as a
set) instead of `type[BaseModel]`, so both a model and a bare name-set can drive it.
The public `check_placeholder_alignment` signature is unchanged.

### 2. `CypherQuery` backend tag

`CypherQuery` gains `backend: ClassVar[Backend] = Backend.CYPHER`. This is metadata only
(ADR-011: `backend` is NOT a dispatch switch).

### 3. `CypherQuery` as a catalogue citizen

`QueryCatalogue` gains `register_cypher_query(q: CypherQuery) -> CypherQuery`. Simple
queries are stored in a third dict `_cypher_queries` and included in `queries()`, so
`validate_query_catalogue` iterates them. Duplicate-name rejection reuses `_reject_duplicate`.
`describe()` exposes them as `kind="read"` with `params_schema` derived from `Params` or
the arg-lists, and `output_class=None` / `output_schema=None` (no Output on the simple path).

`validate_query_catalogue` branches on `isinstance(query, CypherQuery)` and calls
`validate_cypher_spec` directly. This closes the MP Phase-1 gap: YAML-loaded queries now
reach catalogue validation.

### 4. Opt-in `Identifiers` on `CypherQuery`

`CypherQuery` accepts an optional `Identifiers: type[BaseModel] | None` and a bound
`identifiers: BaseModel | None` instance. When both are present, `build()` calls
`render_with_identifiers(self.cypher, identifiers_instance)` (existing function — already
performs `validate_identifier` + leftover-slot check). Default `None` → behaviour is
byte-identical to before (existing value-only queries unchanged). The mechanism mirrors
ADR-010 (declared identifier parameters).

### 5. Executor reuse

The simple path executes via the **existing** `CypherExecutor`, not a new session
implementation. A thin `CypherQueryAdapter` (in `cypher/query_execution.py`) wraps a
`CypherQuery` instance and satisfies the `ReadQuery` / `WriteQuery` duck-type:

- `name`, `backend`, `build()` → `CypherQueryData` pass through unchanged.
- `materialize` defaults to `lambda raw: dict(raw)` → `read()` returns `list[dict]`
  (honest raw rows for the untyped on-ramp).
- `interpret_result` defaults to returning `properties_set` from the
  `CypherWriteResultSummary` — consistent with the existing counter pattern.

`CypherExecutor`, `CypherWriteResultSummary`, and the driver-session / commit logic are
**unchanged**.

---

## Non-goals (explicit)

- `CypherQueryBase` changes or removal — pending a separate discussion after E37.
- Renaming `CypherReadQuery` / `CypherWriteQuery` to `Typed*` — future epic.
- GQLAlchemy query bases — untouched.
- Collapsing the `Params` / arg-list duality — tracked separately.
- Runtime RETURN↔`materialize` key-access guarantee — separate hardening item.

---

## Consequences

- A stale `$param` in a YAML query is now caught **statically** at `validate_query_catalogue`
  time (or `CypherQuery.validate_query(None)`) rather than only at runtime by the driver.
- A YAML-loaded `CypherQuery` registered in a `QueryCatalogue` produces the same domain
  error codes as a typed query over the same Cypher string.
- The simple path is a first-class executor target without any duplicated session or commit
  logic.
- No new string-key dispatch is introduced; the catalogue stores and iterates objects.

---

## Cross-references

- ADR-010: declared identifier parameters — `orthograph.cypher.base_models.CypherReadQuery`
- ADR-011: capability seams + `Backend` as metadata-only tag
- ADR-017: package topology — `cypher/` is top-level; `query/` is vendor-free
- `validate_cypher_spec`: `src/orthograph/cypher/validation.py`
- `CypherQueryAdapter`: `src/orthograph/cypher/query_execution.py`
- `QueryCatalogue.register_cypher_query`: `src/orthograph/query/catalogue.py`
- E37 epic: `.agentic/planning/active_epics/E37_simple_cypher_query_shared_validation.md`
