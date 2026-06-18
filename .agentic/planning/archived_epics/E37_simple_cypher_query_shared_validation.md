# Epic E37: Simple Cypher Query — Shared Validation, Catalogue Parity, and Executor

> **Priority:** Medium
> **Phase:** v0.1.0 — adoption readiness (MP/noctis on-ramp; closes the documented Phase-1 gap)
> **Blocked by:** E36 (`CypherQuery`/`CypherQueryData` naming landed)
> **Blocks:** MP migration Phase 1 (CI-time validation of YAML queries)
> **Type:** Refactor (extract shared validator) + small build (backend tag, register, executor reuse) + tests + docs
> **Rubric (every task judged against this):** simplicity over engineering · readability · robustness · validation capability

---

## Why This Epic Exists

`CypherQuery` (the simple/YAML path, `cypher/query.py`) and `CypherReadQuery` /
`CypherWriteQuery` (the typed path, `cypher/base_models.py`) validate Cypher through **two
different, non-aligned validators**:

- Simple path `CypherQuery.validate_query(def)` → `validate_cypher` only (**semantic / domain
  only**). It skips `$param`↔declared-arg alignment, `<<id>>`↔identifier alignment, and
  RETURN→Output.
- Typed path `validate_query_catalogue` → full four-axis (parse + param alignment +
  RETURN/Output + domain) + `QUERY_UNVERIFIABLE` classification.

Consequences visible in the shipped code today:

- A YAML-loaded `CypherQuery` is a plain `BaseModel`, has **no `backend`**, and **cannot
  register** in `QueryCatalogue` → it never reaches `validate_query_catalogue`. The MP
  "Phase 1 = YAML → catalogue validation" plan (review
  `2026-06-17-noctis-yaml-query-comparison.md` §5) does **not run** on the shipped simple class.
- A stale `$param` in a YAML query is caught only by the driver at runtime, never statically.

This epic makes the simple path **share one validation core** with the typed path (syntactic +
semantic), become **registerable + catalogue-validatable**, gain optional **params + identifiers
parity** with the typed path, and gain a **reused executor** — while staying a much lighter
implementation. It **reuses existing code**: (1) `bindings.py` placeholder extraction / alignment,
(2) `parser.py` + `validation.py` semantic and RETURN checks, (3) `query_execution.py`
`CypherExecutor`.

`CypherQueryBase` (the subclass authoring shell) is **out of scope** here — its fate is a separate
discussion after this epic.

---

## Decisions Already Made (do not re-litigate)

- **Validation convergence = extract a shared string-level core.** A single function validates a
  query *spec* (cypher string + declared param / identifier / arg names + optional Output) and is
  called by **both** paths. The typed path's catalogue-time checks are re-expressed in terms of it;
  the simple path calls the same function.
- **Simple path becomes a catalogue citizen.** `CypherQuery` gains `backend = Backend.CYPHER` and a
  registration route into `QueryCatalogue`, so `validate_query_catalogue` covers it.
- **Identifiers on the simple path = reuse, opt-in.** Add an optional `Identifiers` to `CypherQuery`
  reusing `bindings.render_with_identifiers` / `validate_identifier`, mirroring ADR-010, with an
  empty `NoIdentifiers`-equivalent default so existing simple queries are byte-for-byte unchanged.
- **Executor = reuse `CypherExecutor`.** The simple path adapts to the existing `ReadQuery` /
  `WriteQuery` shape so `CypherExecutor.read` / `write` runs unchanged; no second session / commit
  implementation is created.
- **`CypherQueryBase` untouched** in this epic.
- **No behaviour change to the typed path's public contract** — only internal re-expression on top
  of the shared core; all existing typed tests stay green.

---

## Existing Code to Reuse (the "use 1, 2, 3" mandate)

| Need | Reuse | Location |
|------|-------|----------|
| `$param` / `<<id>>` extraction | `extract_cypher_params`, `extract_cypher_identifiers` | `cypher/bindings.py` |
| Placeholder↔field alignment | `check_placeholder_alignment`, `_check_model_alignment` | `cypher/bindings.py` |
| Identifier splicing + safety | `render_with_identifiers`, `validate_identifier` | `cypher/bindings.py`, `cypher/identifiers.py` |
| Empty default models | `NoParams`, `NoIdentifiers` | `cypher/bindings.py` |
| Syntactic parse | `parse_cypher` | `cypher/parser.py` |
| Semantic / domain check | `validate_cypher`, `_check_labels/_rel_types/_properties/_endpoints` | `cypher/parser.py` |
| RETURN→Output alignment | `extract_return_columns`, `_check_return_output_alignment` | `cypher/parser.py`, `cypher/validation.py` |
| Identifier-injection INFO | `_check_identifier_injection` | `cypher/validation.py` |
| Result currency | `ValidationResult`, `ValidationIssue`, `Severity` | `diagnostics/` |
| Catalogue registry | `QueryCatalogue.register_*`, `queries()` | `query/catalogue.py` |
| Executor seam | `CypherExecutor`, `CypherWriteResultSummary` | `cypher/query_execution.py` |
| Backend tag | `Backend.CYPHER` | `query/base_models.py` |

---

## Tasks (execute in order; each ends green)

### E37.1 — Extract the shared syntactic validator `validate_cypher_spec`

> **Model: Sonnet.** Pulls a string-level core out of two existing validators and re-expresses the
> catalogue path in terms of it; requires judgement to keep typed-path behaviour byte-identical.

**Goal:** one function validates a query spec from primitives (no class, no instance required), so
both paths share it.

1. Add to `cypher/validation.py`:
   ```python
   def validate_cypher_spec(
       *,
       cypher: str,
       params_fields: set[str],
       query_name: str,
       identifier_fields: set[str] = frozenset(),
       graph_definition: GraphDefinition | None = None,
       output_model: type[BaseModel] | None = None,
   ) -> ValidationResult: ...
   ```
   It composes **only existing helpers**:
   - parse via `parse_cypher` → on failure emit `QUERY_PARSE_ERROR` (same code / severity as
     `validate_cypher` already does);
   - `$param` ↔ `params_fields` and `<<id>>` ↔ `identifier_fields` alignment by reusing
     `extract_cypher_params` / `extract_cypher_identifiers` + the `_check_model_alignment` logic;
   - semantic check via `validate_cypher` when `graph_definition is not None`;
   - RETURN→Output via `extract_return_columns` + `_check_return_output_alignment` when
     `output_model is not None`;
   - identifier-injection INFO via existing `_check_identifier_injection`.
2. Refactor `bindings._check_model_alignment` to accept a `set[str]` of declared field names
   instead of a `type[BaseModel]` (so both a model and a bare name-set can drive it). Update its one
   existing caller `check_placeholder_alignment` to pass `set(model.model_fields)`. Keep
   `check_placeholder_alignment`'s public signature and behaviour unchanged.
3. Re-express the per-query body of `validate_query_catalogue` (the typed branch) to call
   `validate_cypher_spec`, deriving `params_fields` from `Params.model_fields`, `identifier_fields`
   from `Identifiers.model_fields`, and `output_model` from `Output`. **No change to emitted codes
   or severities.**
4. Keep `validate_cypher` public and unchanged (it is the semantic half; `validate_cypher_spec`
   calls it).

**Verify:**
```
pwsh> python -m pytest tests/cypher -q
```
All existing cypher tests green (proves typed-path behaviour unchanged).

---

### E37.2 — Add `backend` tag and shared validation to `CypherQuery`

> **Model: Sonnet.** Adds a ClassVar and swaps `validate_query` onto the shared core; needs care
> that a `None` definition still yields syntactic-only checks.

**Goal:** `CypherQuery.validate_query(def)` runs the **same syntactic + semantic** checks as the
typed path.

1. In `cypher/query.py`, add `backend: ClassVar[Backend] = Backend.CYPHER` to `CypherQuery`
   (metadata only — matches the `Backend` docstring "NOT a dispatch switch"). Import `Backend` from
   `orthograph.query.base_models`.
2. Rewrite `CypherQuery.validate_query(definition)` to delegate to `validate_cypher_spec`:
   - `params_fields` = `set(self.Params.model_fields)` when `Params` is set, else
     `set(self.query_args_required) | set(self.query_args_optional)`;
   - `identifier_fields` = from `Identifiers` if E37.4 has landed, else `frozenset()`;
   - `graph_definition` = the argument (None → syntactic-only, preserving today's "pass None for
     syntax-only" contract);
   - `output_model` = None (simple path declares no Output — unchanged);
   - `query_name` = `self.name`.
   Result: a stale `$param` is now caught statically on the simple path (it was not before).
3. Keep `_validate_call_kwargs` (runtime call-arg check) unchanged.

**Verify:**
```
pwsh> python -m pytest tests/cypher/test_query.py -q
```
Green. (New assertions added in E37.5.)

---

### E37.3 — Make `CypherQuery` registerable in `QueryCatalogue`

> **Model: Sonnet.** Bridges a `BaseModel` value-object into a registry that expects `ReadQuery` /
> `WriteQuery`; needs a minimal, readable adapter — resist building a parallel registry.

**Goal:** a YAML/simple query reaches `validate_query_catalogue` — closing the MP Phase-1 gap.

1. Add `QueryCatalogue.register_cypher_query(q: CypherQuery) -> CypherQuery` that stores it in a
   third dict (`self._cypher_queries`) and rejects duplicate names via the existing
   `_reject_duplicate`. Include these in `queries()` so `validate_query_catalogue` iterates them.
2. Extend the loop in `validate_query_catalogue`: it already branches on
   `getattr(type(query), "cypher_template", None)`. Add a branch that recognises a `CypherQuery`
   instance (read `q.cypher`, `q.backend`, derive `params_fields` from `Params` or the arg-lists,
   `identifier_fields` from `Identifiers` if present) and calls `validate_cypher_spec`. Simple
   queries carry no typed-contract requirement.
3. Keep `register_read` / `register_write` and `describe()` untouched. **Do not** introduce
   string-key dispatch (E16 / ADR boundary): the catalogue stores objects; iteration is by object.

**Verify:**
```
pwsh> python -m pytest tests/cypher tests/io -q
```
New test: a YAML-loaded `CypherQuery` registered in a `QueryCatalogue`, then
`validate_query_catalogue(cat, definition)` returns the expected domain error for a renamed label
(the documented MP Phase-1 scenario).

---

### E37.4 — Add opt-in `Identifiers` to `CypherQuery`

> **Model: Sonnet.** Wires existing identifier rendering into the simple class with an empty
> default; small but must keep value-only queries unchanged.

**Goal:** safe dynamic labels on the simple path, reusing the ADR-010 mechanism — no f-string
injection.

1. Add `Identifiers: type[BaseModel] | None = Field(default=None)` to `CypherQuery` and accept an
   `identifiers` value bound at construction (mirror the typed bases' `__init__` shape, or accept it
   as a `build()` argument — choose the reading that keeps `build()`'s single-call shape simplest).
   Default `None` → behave exactly as today (render unchanged).
2. In `build()`, when identifiers are present, call
   `render_with_identifiers(self.cypher, identifiers_instance)` (existing function — already does
   `validate_identifier` + leftover-slot check) before returning `CypherQueryData`.
3. `validate_query` passes `identifier_fields` so `<<name>>` ↔ `Identifiers` alignment is checked,
   and identifier-injection emits the existing INFO code.

**Verify:**
```
pwsh> python -m pytest tests/cypher/test_query.py -q
```
New tests: (a) a value-only query renders byte-identical to before; (b) `<<label>>` with a valid
`Identifiers` field splices safely; (c) an unsafe identifier raises `CypherIdentifierError`;
(d) a `<<name>>` with no matching field raises at build.

---

### E37.5 — Tests for shared validation + simple path

> **Model: Sonnet.** New behavioural tests across the converged surface; needs understanding of
> which codes / severities each axis emits.

Append to `tests/cypher/test_query.py` and `tests/cypher/test_validate_query_catalogue.py` (pytest
functions, one-line docstrings, movie domain consistent with existing tests). Cover:

1. `validate_cypher_spec` syntactic-only (no definition) catches a stale `$param` → alignment ERROR.
2. `validate_cypher_spec` with a definition catches an unknown label → `QUERY_UNKNOWN_NODE_LABEL`
   (same code as the typed path).
3. `CypherQuery.validate_query(None)` is syntactic-only and catches a param-alignment problem
   (previously missed).
4. `CypherQuery.validate_query(definition)` produces identical domain codes to a typed query over
   the same cypher string (parity assertion).
5. A registered `CypherQuery` appears in `validate_query_catalogue` output alongside a typed query,
   in one merged `ValidationResult`.
6. Typed-path regression: an existing typed-query validation test still emits identical codes
   (proves the E37.1 re-expression is behaviour-preserving).

**Verify:**
```
pwsh> python -m pytest tests/cypher -q
```

---

### E37.6 — Executor for the simple path, reusing `CypherExecutor`

> **Model: Sonnet.** Adapts the simple query to the existing executor seam without duplicating
> session / commit; the design judgement is "reuse, don't fork."

**Goal:** the simple path executes through the **existing** `CypherExecutor`, not a new session
implementation.

1. Add a thin adapter (in `cypher/query.py` or `cypher/query_execution.py`, whichever reads cleaner)
   that lets a `CypherQuery` satisfy what `CypherExecutor.read` / `write` consume: `name`,
   `Params` (or a pass-through validator), `backend`, `build()` → `CypherQueryData`, and a
   materialiser.
2. Because the simple path declares no `Output` / `materialize`, provide a **default identity
   materialiser** (`lambda raw: dict(raw)`) so `read()` returns `list[dict]` — honest raw rows for
   the untyped on-ramp. For writes, reuse the counter pattern already in
   `generator._write_query.interpret_result` (default counter, e.g. `properties_set` or a
   caller-chosen counter on the adapter).
3. Reuse, do **not** rebuild: `CypherExecutor` unchanged; `CypherWriteResultSummary` unchanged;
   the `_driver_factory` / `begin_transaction` / rollback logic stays in `CypherExecutor`. The
   adapter is the only new code (~20 lines).

**Verify:**
```
pwsh> python -m pytest tests/cypher/test_query_execution.py -q
```
New test (using the existing `FakeGraphSession` double): a `CypherQuery` executed via the adapter +
`CypherExecutor` returns the expected rows; a write returns the expected counter. No live DB.

---

### E37.7 — Docs + ADR + planning index

> **Model: Sonnet.** Prose synthesis matching ADR house style + a runnable notebook section;
> explains the converged validation story.

1. Create ADR `.agentic/decisions/027-simple-cypher-query-shared-validation.md` recording: the
   shared `validate_cypher_spec` core; the simple-path `backend` + register decision; the
   executor-reuse decision; the opt-in identifiers decision; and the explicit non-goal
   (`CypherQueryBase` untouched, pending discussion).
2. Update `cypher/query.py` module docstring: the simple path now shares full syntactic + semantic
   validation with the typed path; the only difference is it declares no `Output` (raw-row results).
3. Extend notebook `04.06_cypher_query_definitions.ipynb` (created in E36.5) with a cell: load YAML →
   register in `QueryCatalogue` → `validate_query_catalogue(cat, definition)` showing a caught
   renamed-label; and a `CypherExecutor` round-trip on a `CypherQuery` via the adapter (test double,
   no DB).
4. Add E37 to `.agentic/planning/overview.md` with status and the `CypherQueryBase`-discussion
   follow-on note.

**Verify:**
```
pwsh> python -m pytest --nbval-lax notebooks/04.06_cypher_query_definitions.ipynb -q
```

---

## Success Criteria

- [ ] `validate_cypher_spec` exists; both `validate_query_catalogue` and
      `CypherQuery.validate_query` call it; all emitted codes / severities unchanged for the typed
      path.
- [ ] `CypherQuery` carries `backend = Backend.CYPHER` and is registerable in `QueryCatalogue`;
      `validate_query_catalogue` covers it.
- [ ] A YAML-loaded `CypherQuery` produces the same domain codes as a typed query over the same
      cypher string (parity test green).
- [ ] A stale `$param` on the simple path is caught statically (was not before).
- [ ] Simple path supports opt-in `<<name>>` identifiers via `render_with_identifiers`; value-only
      queries byte-unchanged.
- [ ] Simple path executes via the **existing** `CypherExecutor` (no duplicated session / commit
      logic).
- [ ] `tests/cypher`, `tests/io` green; notebook runs clean.
- [ ] ADR-027 written; overview updated.
- [ ] No string-key dispatch introduced; `CypherQueryBase` untouched.

---

## Out of Scope

- `CypherQueryBase` changes / removal (separate discussion after this epic).
- Renaming typed bases to `Typed*` (future epic).
- GQLAlchemy query bases.
- Collapsing the `Params` / arg-list duality (track separately — flagged in assessment as
  redundancy).
- Runtime RETURN↔`materialize` key-access guarantee (separate hardening item).
