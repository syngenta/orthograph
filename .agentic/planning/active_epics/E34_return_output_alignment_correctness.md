# Epic E34: RETURN→Output Alignment Correctness & `materialize` Default

> **STATUS UPDATE (2026-06-16): T4 REVERTED — scope reduced.**
> T1 (RETURN-column classifier `ReturnColumn`/`ReturnKind` in `parser.py`) and
> T2 (tiered static RETURN→Output alignment check in `validation.py`) **stand and
> ship** — they deliver the PRD silent-mismatch guarantee without executing the
> query. **T3/T4 are reverted:** the auto-classifying default `materialize`
> (`_MaterializeKind`/`_classify_materialize`/`_cypher_materialize_default` and the
> `__init_subclass__` injection) was withdrawn for over-coupling runtime shaping to
> the static classifier and shipped broken (undefined `abstract_methods` →
> `NameError` at every `CypherReadQuery` subclass). `materialize` remains an
> **explicit, required one-line method**. ADR-025 amended accordingly. T5/T6
> (notebook re-write for the default) are N/A. The task text below is retained for
> historical context only.

> **Priority:** High
> **Origin:** Notebook ergonomics review session 2026-06-16 (analysis of
> `notebooks/04.05_cypher_result_shapes.ipynb`); follow-on to the E33 grilling.
> **Goal:** Make the RETURN→Output validation actually deliver the PRD's
> silent-mismatch guarantee (User Stories 11, 24; PRD §"silent-mismatch problem",
> axis "Output declaration & validation"), and decouple runtime DTO shaping
> (`materialize`) from the query↔graph-description validation so the two share
> one source of truth instead of being hand-synchronised in three places.
> **Blocked by:** nothing in code (E31 vocabulary already merged). Supersedes the
> Q1 portion of E33 (`row_mapper` is **rejected** here in favour of a declarative
> default `materialize` — see Task T4 and the ADR it produces).
> **Blocks:** Honest documentation of the result-shapes contract (notebook 04.05
> re-write); public API stabilisation for pilot consumers.

---

## Problem statement (verified against source 2026-06-16)

Three findings, all confirmed by reading the code — not inferred:

1. **`extract_return_columns` discards whole-node information it already has.**
   `GraphglotParser._extract_return_columns` (`src/orthograph/cypher/parser.py:185-230`)
   records a column only when the output has an `alias` **or** a connected
   `PropertyRef` (scalar). For a whole-node return (`RETURN m`) the connected
   lineage node is a `Binding` (carrying `name="m"`, `kind=BindingKind.NODE`,
   `label_expression=Movie`) — and the code **ignores the Binding branch
   entirely**. Result: `extract_return_columns("RETURN m") == set()` (empty set,
   **not** `None`). Only `RETURN *` (zero outputs) and aggregation return `None`.

2. **The alignment check is therefore vacuously wrong for the most common shape.**
   `_check_return_output_alignment` (`src/orthograph/cypher/validation.py:41-71`)
   computes `Output.model_fields.keys() - return_cols`. With `return_cols == set()`
   for `RETURN m`, it flags **every** `Output` field as "missing", emitting one
   `QUERY_RETURN_OUTPUT_MISMATCH` INFO per field. Notebook 04.05 rationalises this
   as "expected and intentional — `materialize` bridges the gap" and recommends
   silencing it with `AS` aliases. That is rationalising a bug: the check is
   **only correct for flat scalar projections** and is noise for whole-node /
   whole-rel / projection returns.

3. **Severity is INFO, so the PRD's promised ERROR never fires.** The PRD
   (User Story 24, §"silent-mismatch problem") promises that an `Output` field
   with no matching projected column is caught at build time. Today a genuine
   drift — a scalar projection `RETURN m.title AS title` whose `Output` still
   declares a required `released` field after the property was dropped — produces
   only an INFO and does not fail `is_valid`. The one check that targets the
   query↔DTO coupling is demoted to INFO and broken for whole-node returns.

**Root cause:** validation and runtime shaping (`materialize`) each hand-encode
the RETURN→Output mapping independently. Neither classifies RETURN columns by
*kind* (whole-node vs whole-rel vs scalar), even though graphglot exposes that
distinction at the exact point it is needed (confirmed: the `OutputField`'s
single upstream neighbour is either a `Binding` or a `PropertyRef`; see
`parser.py:66-84` for the existing `Binding` consumption in `_extract_bindings`).

---

## Strategy — three layers, two independent axes

The fix splits along an axis the current design conflates:

- **Axis 1 — static validation of the query against the graph description.**
  Does NOT call `materialize`. Compares the parsed RETURN *shape* to the `Output`
  *type*. Layers 1–2 below.
- **Axis 2 — runtime shaping of a record into a DTO (`materialize`).** Layer 3
  below. Independent of Axis 1 and lower priority.

Because both axes need the **same** RETURN-column classification, we build it
once (Task T1) and consume it from both the validator (T2) and the default
`materialize` (T4). A query that passes validation is then *guaranteed* to have a
working default `materialize` — the coupling becomes derived-and-checked from one
place rather than asserted by hand in three.

**Scope boundary (the honest "which shapes" decision):**
- Single node, multiple nodes, node+rel+node, flat scalar projection → fully
  validated and (Layer 3) auto-materialised. These ARE the product.
- Paths → remain `QUERY_UNVERIFIABLE` (INFO), with a documented
  `UNWIND nodes(path)` Cypher-unroll workaround. No typed `PathOutput` is built
  (already "Not planned for v0.1" in the 04.05 gaps table). This is not dropping
  a feature; it is placing paths in the bucket the PRD already designed
  (PRD §"Three-layer drift detection": `QUERY_UNVERIFIABLE` states *why*).

---

## Constraints from existing code (must respect)

- **`tests/test_architecture.py`** enforces: `cypher/` is a vendor-free layer and
  must not top-level-import `neo4j`/`networkx`/`gqlalchemy`. `graphglot` is
  explicitly allowed. New imports in `parser.py`/`validation.py` must come only
  from `graphglot.*`, stdlib, `pydantic`, or vendor-free `orthograph` layers
  (`graph_definition`, `diagnostics`, `query`). The resolved label needed for
  classification is reachable via `graphglot` Bindings and/or the already-passed
  `GraphDefinition` — **no vendor import required**.
- **No re-exports in `__init__.py`** (architecture test #4). Do not add new
  symbols to any `__init__.py`.
- **Tests are the specification (Constraint 12).** Every behavioural change ships
  with tests in the same task.
- **`RETURN *` and aggregation must still return `None` (skip).** Preserve the two
  existing skip cases exactly (`test_return_star_skips_alignment_check`,
  `test_aggregation_skips_alignment_check`).
- **Backward signature compatibility.** `extract_return_columns` is called from
  `validation.py:175`. If T1 changes its return type, update the single call site
  in the same task; do not leave two shapes in flight.
- **nbval compares stored notebook outputs.** Notebooks run via
  `pytest notebooks/ --nbval-lax`. Any change to the emitted issue set diverges
  the stored outputs of `notebooks/04.05_cypher_result_shapes.ipynb` and they
  must be re-executed and re-saved (Task T5).

---

## Tasks

Execute in order. T1→T2 are the high-value correctness fix (Axis 1). T3 is the
ADR gate for Axis 2. T4 is Axis 2 implementation (only if ADR accepts). T5 is the
notebook re-write/re-run. T6 is the final review pass.

> **Decision point for the implementing session:** T1+T2+T5+T6 are the *minimal
> honest fix* and can ship without T3/T4. T4 (default `materialize`) is the
> ergonomic improvement and is gated on the ADR in T3. If time-boxed, do
> T1,T2,T5,T6 and leave T3/T4 for a follow-up.

---

### T1 — Enrich `extract_return_columns` to classify RETURN columns by kind

**File:** `src/orthograph/cypher/parser.py`
(`GraphglotParser._extract_return_columns` lines 185-230; public
`extract_return_columns` lines 170-183; module-level wrapper lines 249-263).

**Change:** Stop collapsing whole-node/whole-rel outputs to nothing. Classify each
projected output column into one of:
- `scalar` — has an alias OR a connected `PropertyRef`; carries the column name.
- `whole_node` — connected to a `Binding` with `kind == BindingKind.NODE`;
  carries the bound variable name (e.g. `m`) and resolved label
  (`str(binding.label_expression)`, e.g. `Movie`).
- `whole_rel` — connected to a `Binding` with `kind == BindingKind.EDGE`; carries
  variable name and resolved rel-type.

**Return shape:** Introduce a small typed result so the validator can branch on
kind. Recommended: a frozen dataclass `ReturnColumn(name: str, kind: ReturnKind,
label: str | None)` and have `extract_return_columns` return
`list[ReturnColumn] | None` (`None` preserved for `RETURN *` and aggregation).
- Define `ReturnKind` as a `str` `Enum` (`SCALAR`, `WHOLE_NODE`, `WHOLE_REL`) and
  `ReturnColumn` in `parser.py` (vendor-free; no new top-level vendor import).
- If a less invasive change is preferred, the dataclass may instead live next to
  the validator — but `parser.py` is the natural home since classification needs
  graphglot internals. Implementer's call; document it in the docstring.

**Preserve exactly:**
- Empty `lg.outputs` (i.e. `RETURN *`) → `None`.
- Any `node.is_aggregated` → `None`.
- Aliased scalar/whole-node still uses the alias as `name` (so `RETURN m AS movie`
  → `ReturnColumn(name="movie", kind=WHOLE_NODE, label="Movie")`).

**Tests (add to `tests/cypher/test_parser.py`):**
- `RETURN m` → `[ReturnColumn("m", WHOLE_NODE, "Movie")]`.
- `RETURN p, r, m` → three columns: node `p`/Person, rel `r`/ACTED_IN, node
  `m`/Movie (use the project's existing test graph; mirror the labels used in
  `tests/cypher/test_validate_query_catalogue.py` fixtures).
- `RETURN m.title AS title, m.released AS released` → two `SCALAR` columns
  `title`, `released`.
- `RETURN m.title` (no alias) → `SCALAR` column `title`.
- `RETURN m AS movie` → `WHOLE_NODE` named `movie`, label `Movie`.
- `RETURN *` → `None`.
- `RETURN count(m) AS c` → `None`.
- A mixed `RETURN p, m.title AS t` → one `WHOLE_NODE` + one `SCALAR`.

**Acceptance criteria:**
- [ ] `extract_return_columns` returns the typed classification described above.
- [ ] `RETURN *` and aggregation still return `None` (the two existing skip
      tests, `test_return_star_skips_alignment_check` /
      `test_aggregation_skips_alignment_check`, updated to the new return shape
      but still asserting the skip).
- [ ] No new top-level vendor import in `parser.py` (re-run
      `pytest tests/test_architecture.py`).
- [ ] `pytest tests/cypher/test_parser.py` green.

---

### T2 — Make `_check_return_output_alignment` tiered and severity-correct

**File:** `src/orthograph/cypher/validation.py`
(`_check_return_output_alignment` lines 41-71; call site in
`validate_query_catalogue` lines 168-180).

**Change:** Replace the one-way `output_fields - return_cols` INFO emitter with a
tiered check that branches on the `Output` kind and the classified RETURN columns
from T1:

| Output kind & RETURN shape | Outcome |
|---|---|
| `Output` is a `NodeModel`/`RelationshipModel` AND there is exactly one matching whole-node/whole-rel column of the same label | **VALID — no issue.** (Properties are guaranteed by the graph description; this is the case currently spamming false INFOs.) |
| `Output` is a `NodeModel`/`RelationshipModel` but the single whole-node column's label does NOT match `Output.__label__` | **ERROR** (new code, e.g. `QUERY_RETURN_OUTPUT_LABEL_MISMATCH`) — wrong node type returned for the declared Output. |
| `Output` is a flat `BaseModel` (not a Node/Rel model) AND RETURN is scalar columns | For each **required** `Output` field with no matching scalar column alias → **ERROR** `QUERY_RETURN_OUTPUT_MISMATCH`. Optional `Output` fields with no column → INFO (or no issue — implementer decides, document in ADR/docstring). Extra columns not in `Output` → no issue (unchanged policy). |
| `Output` is a projection `BaseModel` whose fields are themselves Node/Rel models AND RETURN is whole-node/whole-rel columns | The variable-name↔field-name gap is **expected** — emit **no** mismatch noise. Optionally verify each whole-node column's label is consistent with the corresponding field model's `__label__` (INFO if it cannot be matched positionally). Keep this lenient; the projection case is the legitimate `materialize` seam. |

**Severity change is the headline:** a required scalar `Output` field with no
matching column moves **INFO → ERROR**. This is the PRD silent-mismatch guarantee.

**Notes for the implementer:**
- Determine "is a NodeModel/RelationshipModel" via `issubclass(Output, NodeModel)`
  / `issubclass(Output, RelationshipModel)` (both importable from
  `orthograph.graph_definition.models`, already vendor-free).
- "required vs optional field" → pydantic `model_fields[name].is_required()`.
- Add any new issue code(s) following the existing `ValidationIssue` construction
  pattern (`code`, `severity`, `entity_type=EntityType.QUERY`, `entity_id`,
  `message`). Keep `QUERY_RETURN_OUTPUT_MISMATCH` as the code name but allow it to
  carry ERROR severity for the required-scalar case; introduce a distinct code
  only if a reviewer prefers code-per-severity (decide in T3 ADR; default: reuse
  the code, vary severity).
- The `validate_query_catalogue` skip conditions (non-Cypher → unverifiable;
  imperative → unverifiable; identifier-injection → unverifiable+`continue`;
  write queries → no alignment) are **unchanged**. Only the read-query alignment
  branch (lines 172-180) changes.

**Tests (modify/add in `tests/cypher/test_validate_query_catalogue.py`):**
- **MODIFY `test_return_output_mismatch_emits_info_issue` (lines 270-289):** the
  fixture `MoviesByYearPartialReturn` (`RETURN m.title AS title`, Output has
  required `title`+`released`) now produces an **ERROR** for `released`, not INFO.
  Rename to `test_scalar_projection_missing_required_field_emits_error` and assert
  the ERROR + that `result.is_valid is False`.
- **KEEP `test_return_output_aligned_emits_no_mismatch_issue` (292-304):** aligned
  scalar projection → no issue (should still hold).
- **ADD `test_whole_node_return_against_nodemodel_emits_no_issue`:** a query with
  `RETURN m` and `Output = Movie` (NodeModel) → no `QUERY_RETURN_OUTPUT_MISMATCH`,
  `is_valid` True. (This is the case 04.05 currently spams.)
- **ADD `test_whole_node_return_wrong_label_emits_error`:** `RETURN m` where `m`
  is a `Movie` but `Output` is a `Person` NodeModel → ERROR.
- **ADD `test_projection_of_whole_nodes_emits_no_mismatch`:** `RETURN p, m` with a
  projection Output (`person: Person`, `movie: Movie`) → no mismatch noise.
- **KEEP** `test_return_star_skips_alignment_check`,
  `test_aggregation_skips_alignment_check`,
  `test_write_query_*_alignment_issue` — verify still pass against the new return
  shape.

**Tests to re-verify in `tests/api/test_model.py` (do NOT loosen intent):**
- `test_validate_query_catalogue_clean` (200-219): `FindPerson` uses whole-node
  `RETURN p`, `Output = Person`. Under the new rule this is the VALID/no-INFO
  case. Assert `is_valid` still True; tighten the assertion to also check **no
  `QUERY_RETURN_OUTPUT_MISMATCH` issues** appear (it should now be clean).
- `test_validate_query_catalogue_against_profile_all_clean` (281-304): same
  `RETURN p` pattern; same tightening.
- `tests/cypher/test_validate_query_catalogue_against_profile.py` (call sites
  ~114/126/140/155): inspect the templates registered there; if any use
  whole-node returns, re-verify the issue set.

**Acceptance criteria:**
- [ ] A scalar projection missing a **required** Output field is an **ERROR** and
      `is_valid` is False.
- [ ] A whole-node `RETURN m` against a matching NodeModel Output produces **no**
      `QUERY_RETURN_OUTPUT_MISMATCH` and `is_valid` is True.
- [ ] A whole-node return whose label contradicts the NodeModel Output is an ERROR.
- [ ] A projection of whole-node columns produces no mismatch noise.
- [ ] `RETURN *` / aggregation / imperative / non-Cypher / write skip behaviour
      unchanged.
- [ ] `pytest tests/cypher/test_validate_query_catalogue.py tests/api/test_model.py tests/cypher/test_validate_query_catalogue_against_profile.py`
      green.
- [ ] `pytest tests/test_architecture.py` green.

---

### T3 — ADR: reject `row_mapper`, adopt declarative default `materialize` (Axis 2 gate)

**Output:** `.agentic/decisions/025-read-query-row-mapper.md` (this is the ADR
target E33 reserved for Q1; E34 fulfils it).

**Decision to record:** E33's `row_mapper: ClassVar[Callable[[dict], D] | None]`
is **rejected** — by its own grilling question #1 it only renames the boilerplate,
keeps the mapping stringly-typed, and adds an ambiguous `row_mapper`-vs-override
precedence rule. Instead adopt a **concrete default `materialize`** on
`CypherReadQuery` that reuses the T1 RETURN-column classifier:
- whole-node/whole-rel single column + Node/Rel `Output` → `Output.model_validate(dict(column_value))`;
- all-scalar columns whose aliases ⊇ required `Output` fields → `Output.model_validate(raw)`;
- projection-of-Node/Rel `Output` → `materialize` stays **required** (the
  genuine divergent seam — keep abstract-by-fallback: default raises a clear
  `NotImplementedError` instructing the author to override).

This makes `materialize` an *override for the divergent case*, not mandatory
boilerplate, and ties it to the SAME classifier the validator uses — so a query
that validates is guaranteed to have a working default.

The ADR must also state:
- the precedence rule (explicit `materialize` override always wins; no ambiguity);
- whether the default lives on `ReadQuery` (backend-agnostic) or `CypherReadQuery`
  (Cypher-specific) — recommend `CypherReadQuery`, since classification needs the
  Cypher RETURN shape;
- the driver-object caveat: `dict(column_value)` must work for real neo4j
  `Node`/`Relationship` objects (mapping protocol) — record this as the runtime
  contract;
- cross-link from `notebooks/04.05` known-gaps table and update E33 status to
  "superseded by E34" in `overview.md`.

**Acceptance criteria:**
- [ ] ADR-025 written with the decision (reject `row_mapper`, adopt default
      `materialize`), the precedence rule, the layer placement, and the rejected
      alternative recorded.
- [ ] `overview.md` E33 row updated to note E34 supersedes its Q1.
- [ ] No production code in this task (decision only).

---

### T4 — Implement the default `materialize` (only if T3 ADR accepts)

**File:** `src/orthograph/cypher/base_models.py` (`CypherReadQuery`,
`materialize` abstract at line 194; `__init_subclass__` at 168-177;
`CypherExecutor.read` call site at `query_execution.py:101`).

**Change:** Provide a concrete default `materialize` on `CypherReadQuery`
implementing the three branches from the ADR, driven by the T1 classifier applied
to `type(self).cypher_template` (cache the classification at class-definition time
in `__init_subclass__`, AFTER `Output` is populated — ordering matters, see E33
constraint note). Imperative queries (no `cypher_template`) cannot be classified
statically → default `materialize` raises a clear `NotImplementedError` telling
the author to override (preserves today's behaviour for the path/imperative case).

**Tests (modify/add in `tests/cypher/test_query_execution.py` and
`tests/query/test_catalogue.py`):**
- ADD: a `CypherReadQuery` with `RETURN m` + `Output = Movie` and **no**
  `materialize` override → `executor.read(...)` returns `Movie` instances via the
  default. Use the existing `FakeGraphSession`/fake-record pattern from
  `test_query_execution.py`.
- ADD: a flat scalar projection with aliases matching a flat `Output` and no
  override → default maps via `Output.model_validate(raw)`.
- ADD: an imperative query (no template) with no override → default
  `materialize` raises `NotImplementedError` with a helpful message.
- KEEP: existing explicit-`materialize` queries
  (`MoviesByYearCypher.materialize`, etc.) still work (override wins).
- VERIFY: `tests/query/test_catalogue.py` (35,50) and
  `tests/query/test_pagination.py` (126,158) still pass (they declare explicit
  `materialize`).

**Acceptance criteria:**
- [ ] A 1:1 whole-node read query needs no `materialize` and round-trips through
      `executor.read`.
- [ ] Explicit `materialize` override still wins (precedence from ADR).
- [ ] Imperative/path queries without override fail loudly with a clear message.
- [ ] `pytest tests/cypher/ tests/query/` green.

---

### T5 — Re-write and re-run notebook `04.05_cypher_result_shapes.ipynb`

**File:** `notebooks/04.05_cypher_result_shapes.ipynb` (primary impact).
Secondary verify: `04.01_typed_cypher_queries.ipynb`,
`05.01_openapi_ergonomics_assessment.ipynb`,
`02.02_cypher_query_generation.ipynb`.

**Why:** nbval (`pytest notebooks/ --nbval-lax`) compares stored cell outputs.
The change diverges 04.05's stored outputs and invalidates several markdown
claims. The notebook currently *teaches the bug* and must be corrected.

**Markdown/claims to rewrite in 04.05:**
- Issue-code table (line ~1086): `QUERY_RETURN_OUTPUT_MISMATCH` is no longer a
  blanket INFO for whole-node returns — it is **ERROR for a required scalar field
  with no column**, and **not emitted** for whole-node-vs-NodeModel. Update the
  table.
- Cell `val0004` stored output (lines ~1160-1169): re-execute. The eight
  `QUERY_RETURN_OUTPUT_MISMATCH` INFOs for `all_movies`/`actor_movie_pairs`/
  `actor_movie_edges` should **disappear** (whole-node / projection cases now
  clean). Only the `shortest_actor_path` `QUERY_UNVERIFIABLE` INFO remains.
- Markdown `val0005` (lines ~1191-1214): delete the "expected and intentional —
  `materialize` bridges the naming gap / silence it with AS aliases" rationale.
  Replace with the correct model: whole-node returns against a NodeModel are VALID
  with no noise; scalar projections must match required Output fields or it is an
  ERROR.
- Validation summary table `val0013` (lines ~1491-1497): update the three
  whole-node rows from "VALID — INFO for ... gap" to "VALID — no INFO".
- Known-gaps table (lines ~1510-1511): update the "`materialize` is mandatory
  boilerplate" row to reference E34/ADR-025 and the default `materialize`
  (whatever T3 decided — if T4 shipped, mark resolved; if T4 deferred, note the
  decision and the v0.1 workaround).
- If T4 shipped: add a short cell demonstrating a whole-node query with **no**
  `materialize` override working via the default.

**Process:**
- Re-execute the notebook top-to-bottom and save with outputs
  (`jupyter nbconvert --to notebook --execute --inplace notebooks/04.05_cypher_result_shapes.ipynb`
  or run in Jupyter and save).
- Re-run `04.01`, `05.01`, `02.02` under nbval; fix any cell that now ERRORs.
  (Per inventory, `04.01`'s catalogue uses scalar projections that already match —
  expected to stay green; `02.02`'s validate cell has no stored output.)

**Acceptance criteria:**
- [ ] `pytest notebooks/ --nbval-lax` green (DB notebooks auto-excluded).
- [ ] 04.05 no longer teaches the silence-with-aliases workaround for whole-node
      returns; its narrative matches the new tiered behaviour.
- [ ] Stored outputs regenerated and committed.

---

### T6 — Full-suite review pass & impacted-test audit

**Why:** This change touches the validator that many catalogue/api/profile tests
lean on indirectly. Final sweep to catch anything the per-task runs missed.

**Steps:**
- Run the full suite: `pytest` (DB tests auto-skip).
- Run notebooks: `pytest notebooks/ --nbval-lax`.
- Run the architecture invariants explicitly: `pytest tests/test_architecture.py`.
- Grep the test tree for any remaining assertion that depends on the old
  behaviour (search for `QUERY_RETURN_OUTPUT_MISMATCH` and `extract_return_columns`
  across `tests/` and confirm each surviving assertion matches the new contract).
- Confirm `src/orthograph/api/model.py` re-exports
  (`validate_query_catalogue`, `validate_query_catalogue_against_profile`,
  `validate_cypher`) still behave (their wrappers are unchanged, but the
  underlying issue set changed).
- Confirm `backends/gqlalchemy/query_builder.py` `validate_cypher` usage is
  unaffected (it does not use the alignment path).

**Acceptance criteria:**
- [ ] `pytest` fully green (no DB).
- [ ] `pytest notebooks/ --nbval-lax` fully green.
- [ ] `pytest tests/test_architecture.py` green.
- [ ] No test in `tests/` still asserts the old whole-node-INFO behaviour.
- [ ] A short note appended to this epic recording the final issue-set diff
      (what moved INFO→ERROR, what INFO→none).

---

## Impacted-files index (for the implementing session)

**Source (change):**
- `src/orthograph/cypher/parser.py` — T1 (`extract_return_columns`,
  `_extract_return_columns`, new `ReturnColumn`/`ReturnKind`).
- `src/orthograph/cypher/validation.py` — T2 (`_check_return_output_alignment`,
  call site lines 168-180).
- `src/orthograph/cypher/base_models.py` — T4 (default `materialize`,
  `__init_subclass__` ordering).

**Tests (change / add / re-verify):**
- `tests/cypher/test_parser.py` — T1 (add classification tests).
- `tests/cypher/test_validate_query_catalogue.py` — T2 (MODIFY
  `test_return_output_mismatch_emits_info_issue` → ERROR; ADD whole-node /
  wrong-label / projection cases; KEEP skip + write cases).
- `tests/api/test_model.py` — T2 (re-verify + tighten `*_clean` cases at
  200-219 / 281-304).
- `tests/cypher/test_validate_query_catalogue_against_profile.py` — T2
  (inspect call-site templates 114/126/140/155).
- `tests/cypher/test_query_execution.py` — T4 (add default-`materialize` cases).
- `tests/query/test_catalogue.py`, `tests/query/test_pagination.py` — T4
  (re-verify explicit-`materialize` queries still pass).
- `tests/test_architecture.py` — T1/T2/T4 (no change expected; constraint guard).

**Notebooks (re-execute / re-save):**
- `notebooks/04.05_cypher_result_shapes.ipynb` — T5 (primary; rewrite narrative +
  regenerate outputs).
- `notebooks/04.01_typed_cypher_queries.ipynb`,
  `notebooks/05.01_openapi_ergonomics_assessment.ipynb`,
  `notebooks/02.02_cypher_query_generation.ipynb` — T5 (re-verify under nbval).

**Decisions:**
- `.agentic/decisions/025-read-query-row-mapper.md` — T3 (new ADR).
- `.agentic/planning/overview.md` — T3 (mark E33 Q1 superseded by E34; add E34 row).

**Commands:**
- Unit tests: `pytest`
- Notebooks: `pytest notebooks/ --nbval-lax`
- Architecture: `pytest tests/test_architecture.py`
- Regenerate a notebook:
  `jupyter nbconvert --to notebook --execute --inplace notebooks/04.05_cypher_result_shapes.ipynb`

---

## Success Criteria

- [ ] T1: `extract_return_columns` classifies whole-node/whole-rel/scalar columns;
      `RETURN *`/aggregation still skip.
- [ ] T2: tiered alignment check — required scalar mismatch is ERROR; whole-node
      vs NodeModel is clean; projection gap is silent; wrong-label is ERROR.
- [ ] T3: ADR-025 records the `row_mapper`-rejected / default-`materialize`
      decision (or explicitly defers Axis 2).
- [ ] T4 (if ADR accepts): default `materialize` removes 1:1 boilerplate; override
      precedence preserved; imperative fails loudly.
- [ ] T5: notebook 04.05 corrected and all notebooks green under nbval.
- [ ] T6: full suite + architecture + notebooks green; issue-set diff recorded.
- [ ] The PRD silent-mismatch guarantee (User Story 24) is actually enforced: a
      query that drops a required projected column fails `is_valid` at build time.
