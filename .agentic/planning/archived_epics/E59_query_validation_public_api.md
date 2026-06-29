# Epic E59: Query Validation Public API — Two Phases × Two Input Grades

> **Priority:** Medium (pre-release surface freeze)
> **Phase:** post-v0.1.0 — public surface freeze before first external consumer
> **Type:** Public surface change. Decided by **ADR-043**.
> **Depends on:** E56 (distillation — done), E55 (public facade — done), ADR-043
> **Sequence vs E60:** **Land E59 first (suite green) before E60 starts.** Both edit `queries.py` + `cypher/validation.py` (same-file contention; see E60 §Q5). E59 is a pure surface+dispatch change with no attribute renames — smaller and self-contained — and E59.1's single `_extract_query_spec` dispatcher **satisfies E60.2's "merge the two extraction blocks in `cypher/validation.py`" bullet**, so E60 inherits it done. Running E60 first would force it to rename attributes E59 is about to re-route (more churn).
> **Blocks:** documentation authoring; first external release
> **Behaviour:** No change to *what* the validators detect (codes/severities/guards). Only the **shape and naming** of the public surface changes.

---

## Why This Epic Exists

The package gains external consumers this release, so the query validation surface
must be frozen and documentable. The current surface overloads two axes onto one
verb (`validate_query`):

- **Kind** — `str` / `CypherQuery` / typed `ReadQuery`|`WriteQuery` / (future) OGM.
- **Phase** — syntactic (parse + alignment) vs semantic (labels/props vs `GraphDefinition`),
  selected *implicitly* by whether a `GraphDefinition` is passed.

ADR-043 resolves this into an explicit **2 × 2 matrix**: phase (`check_*` / `validate*`)
× input grade (object / pieces). The full rationale and rejected alternatives live in
**`.agentic/decisions/043-query-validation-public-api-two-phases-two-input-grades.md`**.

---

## The Frozen Surface (target)

```python
# orthograph.queries

# OBJECT MODE — pass a whole query (polymorphic: str | CypherQuery | ReadQuery | WriteQuery)
check_syntax(query, *, parser=None)                              # syntax only — NO definition
validate(query, definition, *, parser=None)                     # syntax + semantics — definition REQUIRED
validate_catalogue(catalogue, definition, *, parser=None)
validate_catalogue_against_profile(catalogue, profile, definition, rules=None)

# PIECES MODE — pass raw cypher + declared field-name sets (advanced; already tested)
check_cypher_spec(*, cypher, params_fields, identifier_fields=None,
                  output_model=None, parser=None)                # syntax only — NO definition
validate_cypher_spec(*, cypher, params_fields, identifier_fields=None,
                     graph_definition, output_model=None, parser=None)  # definition REQUIRED
```

**Universal rule (lift into docs verbatim):**
> A `check_*` verb runs syntax only and never takes a `GraphDefinition`. A
> `validate*` verb runs syntax + semantics and always requires one. Holds in both
> object mode (whole query) and pieces mode (raw cypher + field sets).

- `params_fields` / `identifier_fields` are **`set[str]`** (declared names; name-level
  alignment only — no type check).
- `output_model` is optional (feature-presence, not a phase toggle).
- `parser=` is the keyword-only seam to swap the syntactic backend (graphglot today);
  a richer config object is deferred (ADR-043 §8).

**Made private** (dispatch stays clear + documented in code):
`_validate_cypher`, `_validate_cypher_query`, `_validate_typed_cypher_query`.

**Removed outright** (no shim — no external consumers): `validate_query`.

---

## Blast Radius (verified 2026-06-29)

**Breaking — `validate_query` removal:**
- `src/orthograph/queries.py` (def + `__all__` + docstring)
- `tests/surface/test_queries.py` (lines 165, 180)
- `tests/test_root_surface.py` (line 128)
- notebooks `03.02`, `03.03` (cells calling `validate_query`)
- `backends/gqlalchemy/query_builder.py` `ValidatedQueryBuilder.validate_query` is a
  **separate method** — NOT affected, do not touch.

**Rename — `validate_cypher` → private `_validate_cypher` (str→semantic primitive):**
- `src/orthograph/queries.py` (import + `__all__` + 2 refs)
- `src/orthograph/cypher/validation.py`, `cypher/generator.py`,
  `backends/gqlalchemy/query_builder.py` (internal callers — update imports)
- `tests/cypher/test_parser.py` (~30), `test_parser_advanced_patterns.py` (~22) —
  these test the primitive directly; update to the private name or via a new public verb.

**Privatize — `validate_cypher_query` / `validate_typed_cypher_query`:**
- callers in `queries.py`, `cypher/validation.py`; tests in `tests/cypher/test_query.py` (~13).

**Catalogue verbs — shape unchanged**, but internal `validate_query_catalogue*` keep working.
`tests/cypher/test_validate_query_catalogue*.py` (~43 combined) unaffected by signature.

**`validate_cypher_spec` — signature change** (`graph_definition` becomes required;
add sibling `check_cypher_spec`): `tests/cypher/test_query.py` (~lines 855–921) update
syntactic-only calls to `check_cypher_spec`.

No `examples/` directory. ~7 notebooks reference these symbols; only `03.02`/`03.03`
call the removed `validate_query` — the rest reference catalogue/primitive names.

---

## Tasks

#### E59.0 — ADR-043 — **done**
Decisions recorded in `.agentic/decisions/043-...md`. (This epic implements it.)

#### E59.1 — Internal dispatch core (no public change yet) — **Sonnet**
In `cypher/validation.py`: fold the two extraction sites (the `CypherQuery` reader in
`_validate_simple_cypher_query` and the typed `getattr`/`isinstance` block in
`validate_typed_cypher_query`) into **one** private dispatcher
`_extract_query_spec(query) -> (cypher, params_fields, identifier_fields, output_model)`
returning `QUERY_UNVERIFIABLE` markers for non-Cypher/imperative kinds. Add a clear
module docstring + inline comments documenting the dispatch table (string / CypherQuery /
typed / unverifiable) so the algorithm is doc-liftable. Keep the validation pipeline
(`validate_cypher_spec` engine) as the single shared core. **No public surface change in
this task; behaviour identical.** Run full suite — must stay green.
*Precondition: ADR-043.*

#### E59.2 — Split `validate_cypher_spec`; add `check_cypher_spec` — **Sonnet**
- Make `validate_cypher_spec`'s `graph_definition` **required** (drop `| None = None`).
- Add `check_cypher_spec(*, cypher, params_fields, identifier_fields=None, output_model=None, parser=None)`
  = the engine with no definition (internally the `graph_definition=None` seam).
- Thread `parser=` through both to the syntactic stage.
- Update `tests/cypher/test_query.py` syntactic-only `validate_cypher_spec(...)` calls to
  `check_cypher_spec(...)`.
*Precondition: E59.1.*

#### E59.3 — Object-mode verbs on the façade; privatize primitives — **Sonnet**
In `queries.py`:
- Add `check_syntax(query, *, parser=None)` and `validate(query, definition, *, parser=None)`,
  each delegating to the E59.1 dispatcher + engine.
- Add `check_cypher_spec` / `validate_cypher_spec` to `__all__`.
- Remove `validate_query` entirely. Remove `validate_cypher` from `__all__`.
- Rename the three primitives to `_validate_cypher` / `_validate_cypher_query` /
  `_validate_typed_cypher_query` in `cypher/validation.py` + `cypher/parser.py`; fix all
  internal imports (`generator.py`, `query_builder.py`, `validation.py`).
- Rewrite the module docstring to describe the 2×2 matrix + universal rule.
*Precondition: E59.2.*

#### E59.4 — Migrate tests + notebooks — **Haiku**
- `tests/surface/test_queries.py` + `tests/test_root_surface.py`: replace `validate_query`
  assertions/calls with `check_syntax` / `validate`; assert all six verbs importable & callable;
  cover each cell of the 2×2 (object check, object validate, pieces check, pieces validate).
- `tests/cypher/test_parser*.py`, `test_query.py`: update to private primitive names where they
  tested `validate_cypher` / `validate_cypher_query` / `validate_typed_cypher_query` directly
  (or re-point at the new public verbs where that is the intent).
- Notebooks `03.02`, `03.03` (and any other `validate_query` cell): migrate to the new verbs.
*Precondition: E59.3.*

#### E59.5 — mypy + full suite + surface gate — **Sonnet**
`python -m mypy src/orthograph` clean; `python -m pytest tests -q` green; confirm
`orthograph.queries.__all__` matches the ADR-043 frozen list exactly and no removed name
is importable.
*Precondition: E59.4.*

---

## Success Criteria

- [ ] `orthograph.queries.__all__` exposes exactly: `check_syntax`, `validate`,
      `validate_catalogue`, `validate_catalogue_against_profile`, `check_cypher_spec`,
      `validate_cypher_spec` (plus the authoring primitives already there).
- [ ] No public verb has an optional `GraphDefinition`. `check_*` takes none; `validate*`
      requires one (object **and** pieces mode).
- [ ] `validate_query` is gone — not importable, no shim.
- [ ] `validate_cypher` / `validate_cypher_query` / `validate_typed_cypher_query` are private;
      the kind-dispatch is a single documented function (`_extract_query_spec`).
- [ ] `params_fields` / `identifier_fields` remain `set[str]`; alignment behaviour unchanged.
- [ ] `parser=` keyword-only seam present on all six verbs.
- [ ] `python -m pytest tests -q` green; `python -m mypy src/orthograph` clean;
      `tests/surface/test_queries.py` covers all four object/pieces × phase cells.

---

## Out of Scope

- Any **behaviour** change to the validators (guards, codes, severities, the
  `QUERY_UNVERIFIABLE` contract).
- A syntactic **config object** beyond the `parser=` seam (ADR-043 §8 defers it).
- Type-aware param validation / `dict[str, type]` fields (ADR-043 §3 rejects it).
- `validate_catalogue` / `validate_catalogue_against_profile` shape (correct as-is).
- The OGM/GqlAlchemy `ValidatedQueryBuilder.validate_query` method (separate concern).
- E60 query-shape vocabulary alignment (`params_schema` vs `Params`) — separate epic;
  E59.1's single dispatcher makes E60 easier but does not depend on it.
