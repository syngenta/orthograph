# Epic E42: Unify Cardinality on UML Notation

> **Priority:** Medium
> **Phase:** v0.1.0 — pilot readiness (developer-experience / internal-quality)
> **Blocked by:** E40 (all tasks, including E40.6 YAML round-trip and E40.9 integration gate) — **do not start until E40 is fully done**
> **Blocks:** none
> **Type:** Refactor (collapse three cardinality-authoring forms into one value object) + notation parser/serializer + big-bang removal of `Cardinality.*` / `EXACTLY` + ADR amendment + test & doc migration
> **Decisions:** amends ADR-001 (naming), ADR-005 (cardinality semantics); relates ADR-029 (conditional), ADR-015 (declared/observed mirror), ADR-017 (topology). **Produces a new ADR (ADR-031) first — task E42.0.**
> **Rubric (every task judged against this):** strongly-typed · SOLID · readability over cleverness · small surgical diffs · break complex logic into named functions · docstrings carry only the essential · each task ends green with guardrails run

---

## Why This Epic Exists

Cardinality is authored three different ways today, all collapsing to the same
runtime value:

| Form | Example | Underlying |
|------|---------|------------|
| Named constant | `Cardinality.ONE_OR_MORE` | `CardinalitySpec(min=1, max=None)` |
| Raw spec | `CardinalitySpec(min=2, max=5)` | itself |
| Factory | `EXACTLY(3)` | `CardinalitySpec(min=3, max=3)` |

`CardinalitySpec` is **already** the single frozen value object (min/max, bound
validation, `.contains()`, `.resolve_for_pair()`, a UML-ish `__repr__`). The
fragmentation is only at the **authoring surface**, plus two divergent renderers
(`__repr__` emits `N` for unbounded; the visualizers emit `*`) and a third
serialized form (`{min, max}` dicts in YAML).

This epic makes `CardinalitySpec` the **one** value object with UML notation as a
first-class, round-tripping (de)serialization (`parse` ⇄ `notation`), accepts that
notation inline via Pydantic coercion, and **removes** the redundant
`Cardinality.*` constants and `EXACTLY`. One notation — `"1..*"` — is used in
class bodies, YAML, `__repr__`, and visualization.

The runtime model does not change: after construction everything is still a
`CardinalitySpec`. Every consumer (`validation.py`, `comparison/`, `visualization/`,
`graph_profile/`) reads `.min`/`.max`/`.contains()`/`representative_spec()`
**unchanged**. The blast radius is **wide but shallow**: ~3 production references,
~143 test references, ~59 doc references — almost all mechanical literal swaps,
funnelled through one new coercion seam.

---

## Decisions Already Made (locked in the design session — do not re-litigate; ADR-031 records them)

- **Value object = enriched `CardinalitySpec`.** No new class. The UML notation is
  a behaviour *of* `CardinalitySpec`, not a sibling type.
- **Parse seam = Pydantic `model_validator(mode="before")` on `CardinalitySpec`.**
  One hook covers raw construction, YAML parsing, and `ConditionalCardinality.by_kind`
  rule/`default` values.
- **Class-body authoring also coerced** in `RelationshipModel.__init_subclass__`
  (ClassVars bypass Pydantic, so a bare `__source_cardinality__ = "1..*"` needs an
  explicit coercion step there).
- **One notation everywhere — including YAML serialization.** YAML emits and reads
  `"1..*"` strings; the `{min, max}` dict form is still *accepted on read* for
  backward compatibility but is no longer emitted. (Conditional YAML round-trip
  from E40.6 stays as-is structurally; only the per-bound leaves become notation.)
- **`*` is the canonical unbounded symbol.** `__repr__` is fixed to use `*` (was `N`).
- **Grammar = strict `min..max`** (`max` may be `*`). No bare `"1"` / `"*"`
  shorthand in this epic (deferrable, non-breaking to add later).
- **Big-bang removal** of `Cardinality.*` and `EXACTLY` in this epic.

### Grammar (canonical, exact inverse of `notation`)

```
"<min>..<max>"   min = non-negative int;  max = non-negative int OR "*"
legal:   "0..0" "0..1" "1..1" "0..*" "1..*" "2..5" "3..3"
illegal: "1"  "*"  "..5"  "1.."  "*..5"  "1...5"  "5..2"  "-1..0"  "a..b"
```
Invariant: `CardinalitySpec.parse(spec.notation) == spec` for every spec.

---

## Existing Code to Touch

| Concern | File | Anchor (today) |
|---------|------|----------------|
| `CardinalitySpec` (value object) | `src/orthograph/graph_definition/models.py` | class @ `:203`; `__repr__` @ `:233`; bound validator @ `:211` |
| `Cardinality` namespace (DELETE) | `src/orthograph/graph_definition/models.py` | `:238`–`:264` |
| `EXACTLY` factory (DELETE) | `src/orthograph/graph_definition/models.py` | `:267`–`:269` |
| Field defaults | `src/orthograph/graph_definition/models.py` | `:512`–`:513`, `:519`–`:520` |
| Class-body coercion seam | `src/orthograph/graph_definition/models.py` | `__init_subclass__` @ `:526` |
| `by_kind` rule values | `src/orthograph/graph_definition/models.py` | `:416`–`:438` |
| New parse error type | `src/orthograph/graph_definition/exceptions.py` | new `CardinalityParseError` |
| YAML parse/serialize leaves | `src/orthograph/io/yaml.py` | `_parse_cardinality` @ `:183`; `_serialize_rel_type` @ `:251`–`:260` |
| Duplicate formatters (COLLAPSE) | `src/orthograph/visualization/text.py` `:9`–`:12`; `src/orthograph/visualization/mermaid.py` `:10`–`:13` | both → `.notation` |
| Public exports | `src/orthograph/graph_definition/__init__.py` (empty today), `api/` surface | — |
| ADRs to amend | `.agentic/decisions/001-*`, `005-*` (and references in `017-*`, `029-*`) | — |

---

## Tasks

> Tasks are ordered. **E42.0 → E42.1 → E42.2** are the load-bearing core and must be
> done in sequence by the indicated model. **E42.3 … E42.7** are largely independent
> mechanical follow-ups once the core seam exists and can be delegated in parallel.

---

### E42.0 — ADR-031: amend the cardinality-authoring decision

> **Model: Opus.** Reasoning-heavy: this reverses a published naming decision
> (ADR-001) and a recently-shipped E40 surface; the rationale and the rejected
> alternatives must be airtight before any code moves.

**Goal:** a new `.agentic/decisions/031-*.md` records: cardinality is authored as
UML notation parsed into `CardinalitySpec`; `Cardinality.*` constants and
`EXACTLY` are removed; `*` is canonical for unbounded; strict `min..max` grammar;
YAML switches to notation (dict accepted on read). It explicitly **supersedes the
cardinality-naming portions of ADR-001 and the constant/`EXACTLY` portions of
ADR-005**, and notes it reverses the *internal-only* `Cardinality.ZERO`/`EXACTLY`
introduced in E40 (which E40.9 deliberately did not publicly export, precisely to
enable this).

**Operation:**
1. Write ADR-031 (Status: Accepted; Category: core; Extends/Supersedes: ADR-001,
   ADR-005; Relates: ADR-029, ADR-015, ADR-017). Include: the locked decisions
   above, the grammar block, the round-trip invariant, the rejected alternatives
   (keep-constants-as-aliases; new-separate-value-object; keep-`{min,max}`-YAML;
   shorthand grammar) with one-line rationales.
2. Add cross-link rows in `.agentic/CONTEXT.md` Navigate table and amend the
   "supersedes" notes at the top of ADR-001 and ADR-005 (a one-line banner
   pointing to ADR-031; do not rewrite their bodies).

**Acceptance:** ADR-031 exists, is internally consistent, and ADR-001/005 carry a
supersession banner. No code changed in this task.

**Care / risks:** this is the gate — the design must be frozen here so E42.1+ are
purely mechanical. Do not introduce shorthand grammar (out of scope).

---

### E42.1 — Enrich `CardinalitySpec`: `parse`, `notation`, `mode="before"` coercion, fix `__repr__`

> **Model: Opus.** The one subtle, load-bearing change: a Pydantic `mode="before"`
> validator that must coerce strings without breaking dict/instance construction,
> frozen semantics, or the existing `_validate_bounds`. Get this wrong and every
> downstream task inherits the bug.

**Goal:** `CardinalitySpec` gains exact-inverse text (de)serialization and accepts
notation strings anywhere Pydantic validates it.

**Operation** — `src/orthograph/graph_definition/models.py` + `exceptions.py`:
1. Add `CardinalityParseError(ModelDefinitionError)` (or the closest existing base)
   to `graph_definition/exceptions.py` with a message template
   `"expected 'min..max', got {value!r}"`.
2. Add `@classmethod parse(cls, text: str) -> "CardinalitySpec"`: split on the
   first `..`; require exactly two non-empty parts; `min` must parse as a
   non-negative int; `max` is `None` if `== "*"` else a non-negative int; construct
   via `cls(min=…, max=…)` so `_validate_bounds` still runs. Any syntactic failure
   raises `CardinalityParseError`; semantic failures (`5..2`, negatives) keep coming
   from `_validate_bounds`.
3. Add `@property notation(self) -> str`: `f"{self.min}..{'*' if self.max is None else self.max}"`.
4. Add `model_validator(mode="before")`: if input is `str`, return
   `cls.parse(value)`'s field dict (or delegate cleanly); pass dicts/instances
   through untouched.
5. Change `__repr__` (`:233`–`:235`) to `f"CardinalitySpec({self.notation})"` so it
   uses `*`, not `N`.

**Tests (TDD — write first)** — new `tests/graph_definition/test_cardinality_notation.py`:
- every legal string parses to the expected `(min, max)`; round-trip
  `parse(spec.notation) == spec` for all five canonical specs + `2..5`/`3..3`.
- every illegal string raises `CardinalityParseError` (one assert per case from the
  grammar block).
- `CardinalitySpec.model_validate("1..*") == CardinalitySpec(min=1, max=None)`
  (the `mode="before"` seam).
- `repr(CardinalitySpec(min=1, max=None)) == "CardinalitySpec(1..*)"`.

**Care / risks:** keep `frozen=True` intact; `mode="before"` must not shadow the
existing `_validate_bounds` (mode="after"); do **not** change `min`/`max` field
types. Verify `ConditionalCardinality`/`ConditionalRule` (which embed
`CardinalitySpec`) still construct.

---

### E42.2 — Coerce authored class-body strings + `by_kind`; delete `Cardinality.*` and `EXACTLY`

> **Model: Sonnet.** Mechanical once E42.1 lands, but the `__init_subclass__`
> ClassVar coercion is the one place that needs care (Pydantic does not validate
> ClassVars).

**Goal:** `__source_cardinality__ = "1..*"` works in a `RelationshipModel` subclass;
`by_kind` accepts string rule/`default` values; the redundant constructors are gone.

**Operation** — `src/orthograph/graph_definition/models.py`:
1. In `RelationshipModel.__init_subclass__` (`:526`), after the existing required-var
   checks, coerce `__source_cardinality__` and `__target_cardinality__`: if the value
   is a `str`, replace it with `CardinalitySpec.parse(...)`; if it is a
   `CardinalitySpec`/`ConditionalCardinality`, leave it. Extract a small named helper
   `_coerce_cardinality(value) -> CardinalitySpec | ConditionalCardinality`.
 2. ~~In `ConditionalCardinality.by_kind`, coerce each rule `spec` and the
    `default`~~ **(N/A — `by_kind` was removed by E43/ADR-032; rule `spec`s now
    flow through the `CardinalitySpec` `mode="before"` coercion during explicit
    `ConditionalRule`/`ConditionalCardinality` construction).**
3. Replace the two field defaults (`:513`, `:520`) with `CardinalitySpec(min=0, max=None)`.
4. **Delete** `class Cardinality` (`:238`–`:264`) and `def EXACTLY` (`:267`–`:269`).
5. Update the field type annotation/docstrings (`:489`, `:493`, `:512`–`:524`) to
   describe notation authoring; remove references to the deleted constants.

**Tests (TDD — write/adjust):**
- new: a `RelationshipModel` subclass authored with `__source_cardinality__ = "1..*"`
  exposes a real `CardinalitySpec(min=1, max=None)`.
- new: `by_kind(rules={("a","b"): "1..2"}, default="0..*")` builds equal to the
  spec-valued form.
- the default (no override) is `CardinalitySpec(min=0, max=None)`.

**Care / risks:** this task makes `Cardinality`/`EXACTLY` import errors appear across
the suite — that is expected; E42.3 fixes the tests. Keep this task's own new tests
green and `mypy src/orthograph` green. Confirm nothing in `src/` still imports the
deleted names (grep `Cardinality\.` and `EXACTLY` under `src/` → only `CardinalitySpec` remains).

---

### E42.3 — Migrate all tests to notation; fix `is` → `==`

> **Model: Haiku.** High-volume, low-judgement literal substitution across ~18 files
> (~143 constant refs + 10 `EXACTLY`). Mechanical with a fixed mapping table.

**Goal:** the full test suite uses notation strings (or `CardinalitySpec(...)`) and
is green.

**Operation** — across `tests/`:
1. Substitute, per the mapping:
   `Cardinality.ZERO`→`"0..0"`, `Cardinality.ZERO_OR_ONE`→`"0..1"`,
   `Cardinality.ONE`→`"1..1"`, `Cardinality.ZERO_OR_MORE`→`"0..*"`,
   `Cardinality.ONE_OR_MORE`→`"1..*"`, `EXACTLY(n)`→`"n..n"`.
   Where a test asserts on a *constructed* `CardinalitySpec` (e.g. `.min`/`.max`),
   prefer `CardinalitySpec(min=…, max=…)` over a notation string for clarity.
2. **`is` → `==`**: parsed/notation specs are fresh instances. Find every
   `... is Cardinality.X` (e.g. `tests/graph_definition/test_cardinality_spec.py`
   `resolve_for_pair(...) is Cardinality.ONE` and siblings) and convert identity
   assertions to equality. Grep `is Cardinality` and `is CardinalitySpec` to be sure.
3. Remove the now-obsolete `EXACTLY` unit tests in `test_cardinality_spec.py`
   (or convert them to `CardinalitySpec(min=n,max=n)` / `parse("n..n")` cases).
4. Drop imports of the deleted `Cardinality` / `EXACTLY` from every test module.

**Files (ref counts from inventory):** `test_cardinality_spec.py` (44),
`test_validation.py` (23), `test_relationship_model.py` (16),
`test_graph_definition.py` (15), `test_types.py` (8), `tests/io/test_yaml.py` (7 —
but see E42.4), `tests/comparison/test_diff_rules.py` (7), `test_integration.py` (5),
`graph_definition/conftest.py` (5), `tests/fixtures/conftest.py` (2),
`tests/comparison/test_compare_peers.py` (2), `tests/visualization/test_mermaid.py` (2),
`tests/visualization/test_text.py` (2), `tests/comparison/test_rules.py` (1),
`tests/comparison/test_engine.py` (1), `tests/backends/gqlalchemy/test_result_adapter.py` (1),
`tests/backends/gqlalchemy/test_codegen.py` (1).

**Verify:** `python -m pytest -q` green; `grep` for `Cardinality\.` / `\bEXACTLY\b`
under `tests/` returns nothing (except `CardinalitySpec`).

**Care / risks:** do not change *intent* of any test — only the construction form.
The `is`→`==` cases are the only semantic edits; treat them carefully.

---

### E42.4 — YAML: emit notation, accept notation + legacy dict; collapse formatters

> **Model: Sonnet.** Two small format branches plus a backward-compat read path and
> golden-fixture updates; needs care that round-trip stays exact.

**Goal:** YAML serializes cardinality leaves as `"1..*"` strings and parses both the
new string form and the legacy `{min, max}` dict; the two duplicate visualization
formatters are replaced by `CardinalitySpec.notation`.

**Operation:**
1. `src/orthograph/io/yaml.py` `_parse_cardinality` (`:183`): accept `str`
   (→ `CardinalitySpec.parse`), `dict` (legacy `{min, max}` → unchanged), and `None`
   (→ `CardinalitySpec(min=0, max=None)`). Keep the conditional path from E40.6
   intact; only its per-bound leaves may now also be notation — confirm against the
   E40.6 grammar and keep both readable.
2. `_serialize_rel_type` (`:251`–`:260`): emit
   `spec["source_cardinality"] = representative_spec(...).notation` (string), same
   for target. (Conditional serialization from E40.6: emit each leaf bound as
   notation; keep the structural shape.)
3. `src/orthograph/visualization/text.py` (`:9`–`:12`) and
   `src/orthograph/visualization/mermaid.py` (`:10`–`:13`): delete the local
   `_format_cardinality`; use `representative_spec(...).notation` at the call sites
   (`text.py:37`–`38`, `mermaid.py:87`–`88`). Keep any conditional-rendering helper
   from E40.8 but route its per-bound leaves through `.notation`.

**Tests (TDD — adjust/add):** `tests/io/test_yaml.py` — update golden expectations to
the string form; add a regression test that a legacy `{min, max}` YAML still parses;
round-trip `model → serialize → parse` equal for flat and conditional.
`tests/visualization/test_text.py` / `test_mermaid.py` — outputs unchanged (they
already render `"0..1"`/`"1..*"`); assert the formatter dedup didn't change strings.

**Care / risks:** `check-yaml` pre-commit must pass. Round-trip equality is the
acceptance bar. Do not regress E40.6 conditional round-trip — run those tests.

---

### E42.5 — Public exports & API surface

> **Model: Sonnet.** Small, but must align with how the rest of the package
> re-exports types and not re-introduce a removed symbol.

**Goal:** `CardinalitySpec` (and `ConditionalCardinality`/`PropMatch`/`ConditionalRule`
per E40.9) are the public cardinality surface; nothing exports `Cardinality`/`EXACTLY`.

**Operation:**
1. Ensure `src/orthograph/graph_definition/__init__.py` (empty today) and any
   `orthograph` top-level / `api/` re-export surface expose `CardinalitySpec` and the
   conditional types — and **not** `Cardinality`/`EXACTLY`.
2. Grep the whole repo (`src/` + notebooks) for stray imports of the deleted names
   and remove them.

**Verify:** `python -c "import orthograph; ..."` smoke of the public path used by
notebooks/tests; `mypy src/orthograph` green.

**Care / risks:** if E40.9 already added the conditional exports, this task is mostly
a confirmation + a guard test asserting `Cardinality`/`EXACTLY` are not importable
from the public surface.

---

### E42.6 — Docs, ADR cross-links, notebook, overview hygiene

> **Model: Sonnet.** Prose + notebook cells + planning-index hygiene.

**Goal:** all documentation reflects notation authoring; no doc references the
deleted symbols as public API.

**Operation:**
1. Update the ~59 doc references (PRD/ADR/epic examples) that name `Cardinality.*`
   or `EXACTLY` as authoring forms to notation strings — **except** historical ADR
   bodies, which keep their banner from E42.0 rather than being rewritten.
   Priority files: ADR-001 (`:38`–`:43`), ADR-005, ADR-017 topology blurbs
   (`:82,133,135,276`), ADR-029 references; E40 epic example snippets.
2. Update the cardinality notebook
   (`notebooks/01.04_optionality_and_cardinality.ipynb`) to author with notation.
3. Add the **E42 row** to `.agentic/planning/overview.md` (Epics table + Dependency
   Graph "AFTER E40" + Active list + Epic Files list) — see E42.7 if not already done.

**Verify:** `python -m pytest --nbval-lax notebooks/01.04_optionality_and_cardinality.ipynb -q`.

**Care / risks:** keep notebook cells deterministic (no DB). Do not edit archived
epics.

---

### E42.7 — Integration gate: full suite + guardrails green

> **Model: Sonnet.** The closing gate; mostly running things and chasing the last
> red.

**Goal:** the repository is green end-to-end with the unified cardinality surface.

**Operation / verify:**
```
pwsh> python -m pytest -q
pwsh> python -m mypy src/orthograph
pwsh> pre-commit run --all-files
```
1. Confirm zero references to `Cardinality.` (other than `CardinalitySpec`) and
   `\bEXACTLY\b` anywhere in `src/` and `tests/`.
2. Confirm `parse(spec.notation) == spec` invariant test passes.
3. Confirm legacy `{min, max}` YAML still parses (back-compat regression).

**Care / risks:** this is the merge gate — everything green before close.

---

## Success Criteria

- [x] ADR-031 recorded; ADR-001 & ADR-005 carry supersession banners; CONTEXT.md cross-links it.
- [x] `CardinalitySpec.parse` ⇄ `.notation` round-trip exactly; `mode="before"` accepts notation strings; `__repr__` uses `*`.
- [x] `RelationshipModel` subclasses and `by_kind` accept notation strings; defaults are `CardinalitySpec(min=0, max=None)`.
- [x] `Cardinality.*` and `EXACTLY` are **deleted**; no import of them remains in `src/` or `tests/`; they are not publicly importable.
- [x] All tests migrated to notation/`CardinalitySpec(...)`; `is`→`==` identity assertions fixed; full suite green.
- [x] YAML emits notation, accepts notation **and** legacy `{min, max}`; flat + conditional round-trip exact.
- [x] Both visualization formatters collapsed into `CardinalitySpec.notation`; rendered strings unchanged.
- [x] Docs/notebook/overview updated; `mypy` + `pre-commit` green.

**Status: Done — 2026-06-19**
Note: E42.5 (public re-exports of `Cardinality`/`EXACTLY`) was skipped per design decision — the `__init__.py` remains empty; the removed names were never publicly exported so no guard test is needed.

---

## Out of Scope

- **UML shorthand** (`"1"`, `"*"`) — deferrable, non-breaking to add later.
- Merging declared `CardinalitySpec` with observed `CardinalityStats` (ADR-015 boundary stays).
- Any change to `ConditionalCardinality` resolution semantics (only its leaf-bound authoring/serialization touches notation).
- Re-opening the `{min, max}` YAML read path removal — it stays accepted-on-read for back-compat this phase.
