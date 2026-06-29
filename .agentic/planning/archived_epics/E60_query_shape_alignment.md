# Epic E60: Query Shape Alignment — One Vocabulary Across Typed / Cypher / ORM Paths

> **Priority:** Medium
> **Phase:** post-v0.1.0 — architecture / decoupling
> **Status:** ADR ratified (E60.0 done). Implementation E60.1–E60.5 ready.
> **Decision authority:** [ADR-045](../../decisions/045-query-shape-alignment-rename-strategy.md). Read ADR-045 before any task.
> **Depends on:** E56 (W4 isolated the divergence into `CypherExecutor._query_shape`),
>   E59 (**DONE** — query-validation public API; the `_extract_query_spec` dispatcher exists).
> **Blocks:** E39 (Async Query Runner). **E39 must NOT start until E60 is complete** —
>   E60 deletes the adapters E39 T5 currently references and renames the attributes its
>   code snippets read. E60.5 updates the E39 epic text so E39 starts clean.
> **Origin:** E56 Workstream W4 re-analysis (2026-06-28).

---

## Why This Epic Exists (one paragraph)

Two query authoring shapes describe the **same concepts** under **different attribute
names** (`Params`/`Identifiers`/`name` on the typed path; `params_schema`/
`identifiers_schema`/`query_id` on the simple `CypherQuery` path). The divergence is
accidental. It forces a reconciliation step (`getattr ... or ...`, three comprehensions,
two extraction blocks, two adapters) at every generic consumer. This epic aligns the
**typed path onto the Cypher names**, deletes the reconciliation, and unifies `build()`
so all paths share one construction shape and one build shape — **without** merging the
types into a union or hierarchy. ADR-045 records every decision and the verified facts
behind them.

---

## The End State (what "done" looks like)

| Concept | Before | After (all paths) |
|---|---|---|
| params model | `Params` (typed) / `params_schema` (simple) | `params_schema` |
| identifiers model | `Identifiers` (typed) / `identifiers_schema` (simple) | `identifiers_schema` |
| identity | `name` (typed) / `query_id` (simple) | `query_id` |
| cypher text | `cypher_template` (both) | `cypher_template` (unchanged) |
| construction | typed: `Q(identifiers=...)`; simple: identifiers at build-time | both: `Q(identifiers=...)` |
| build | typed: `build(params)`; simple: `build(**kwargs)` | both: `build(params)` |
| `QueryDescription` identity | `.name` | `.query_id` |
| reconciliation | `_query_shape`, 3 comprehensions, 2 extraction blocks, 2 adapters | **all deleted** |

YAML wire format: **byte-for-byte unchanged** (already `query_id`/`params_schema`,
schema-only, no identifier values).

---

## Verified Facts (trust these over memory — gathered 2026-06-29, see ADR-045)

1. **Blast radius:** 35 classes declare `Params`, 31 declare `Identifiers`, 39 declare
   `name`. Files: `query/base_models.py`, `cypher/base_models.py`,
   `graph_profile/queries/shared.py`, `backends/neo4j/queries.py`,
   `backends/memgraph/queries.py`, `backends/gqlalchemy/base_models.py`,
   `cypher/generator.py` (dynamic `type()` synthesis).
2. **`ReadQuery`/`WriteQuery` have NO `__init__`** — only `__init_subclass__`
   (`base_models.py:147-161/193-203`) which auto-populates ClassVars and enforces the
   contract. `CypherReadQuery.__init__` (`cypher/base_models.py:163-166`) binds
   `self._identifiers` at construction.
3. **Typed `build(self, params: P)` reads `self._identifiers`** (`cypher/base_models.py:191`);
   the executor calls `query.build(params)` (`query_execution.py:115`) — identifiers
   are NEVER passed to `build()`.
4. **The adapters never pass `identifiers=`** (`query_execution.py:186-192/221-227`);
   the simple execution path is already de facto `NoIdentifiers`-only.
5. **`CypherQuery` stores only the SCHEMA classes** (`params_schema`,
   `identifiers_schema`) as Pydantic fields; identifier *values* are NEVER stored on
   the instance and NEVER serialized (`query.py:35-37,170-204`). YAML is schema-only;
   there is no `CypherQuery` save path.
6. **E59 landed:** `cypher/validation.py` has one `_extract_query_spec` dispatcher; the
   "merge two extraction blocks" work is already done — E60 only renames the attribute
   that dispatcher reads.
7. **`describe()` has three comprehensions** (`catalogue.py:136-170`); reads/writes use
   `q.name`/`q.Params`, simple uses `q.query_id`/`q.params_schema`. They differ in
   `kind`/`output` per dict — the collapse keeps that per-source logic but reads ONE
   identity/params vocabulary.

---

## Execution Protocol (how a low-context agent runs a task)

Tasks are **sequential**. Do not start T(n+1) until T(n)'s acceptance gate is green.
Each task is **self-contained**: an agent completes it by reading **only** (a) its own
task section, (b) the **Shared Reference** at the bottom, and (c) ADR-045 if the task
says so. Each task names its files, the change, a binary acceptance gate, and the
**model** it is sized for.

**Model sizing legend:**
- **Haiku** — fully mechanical; every edit is spelled out or is a verbatim find/replace.
  No design judgement.
- **Sonnet** — scoped implementation mirroring an existing pattern.
- **Opus** — cross-file behaviour reasoning with real blast-radius risk.

**STOP markers:** where a task hands off from Opus/Sonnet judgement to a mechanical
tail, the task ends at a **`### STOP — hand to Haiku`** line. The user runs the
remaining mechanical sub-steps with a Haiku agent (or continues manually). This keeps
expensive reasoning tokens off the bulk find/replace work.

---

## Task Map (dependency order)

```
E60.1  Rename typed ClassVars + QueryDescription identity        [OPUS → STOP → Haiku]
E60.2  Collapse the reconciliation sites (_query_shape, describe) [Sonnet]
E60.3  Option A: CypherQuery binds identifiers at construction,
       unify build(params), delete adapters                      [OPUS → STOP → Sonnet]
E60.4  Update tests + notebooks for new build/construction shape  [Haiku]
E60.5  Update ADR-045 status, E39 epic text, overview, docstrings [Haiku]
E60.6  Rename base CLASSES to ...QueryModel (subclass-me signal)  [Sonnet → STOP → Haiku]
```

- **E60.1 → E60.2 → E60.3 → E60.4 → E60.5 → E60.6** strictly sequential.
- **E60.1** and **E60.3** are the Opus judgement tasks; each STOPs before its
  mechanical tail so Haiku finishes.
- **E60.6** is a pure symbol-rename (no behaviour change), kept LAST and separate from
  the attribute rename (E60.1) so the two ~300-site renames never share a commit.
- After E60.5, **E39 is unblocked.** E60.6 may run before or after E39 starts, but is
  cheapest now (before E39/ORM add more subclasses). The ADR addendum records this.

---

## Tasks

### E60.0 — ADR: decide Q1–Q5 + count blast radius — **Opus** ✓ DONE

ADR-045 written and amended (Option A for Q4; full `QueryDescription` rename for Q2).
Blast radius counted (see Verified Facts). Decisions:
- Q1 hard rename, no aliases.
- Q2 full rename incl. `QueryDescription.name` → `query_id`, root API, notebooks, tests.
- Q3 `_auto_populate_classvar`/`_enforce_query_contract` string literals updated.
- Q4 **Option A**: `CypherQuery` binds identifiers at construction (`PrivateAttr`),
  `build(self, params)`, adapters deleted, `**kwargs` removed.
- Q5 E59 gates E60.1 (E59 is done).

---

### E60.1 — Rename the typed-base ClassVars + `QueryDescription` identity

**Model:** **OPUS** for the base-class + auto-population edits and the `cypher/generator.py`
dynamic-synthesis edit; **STOP** then Haiku for the mechanical subclass-body find/replace.
**Type:** Code (source + tests). **Depends on:** E60.0. (E59 already done.)

**Goal:** Rename, across the whole codebase, in one commit:
- `Params` → `params_schema` (ClassVar on the typed bases + 35 subclass bodies)
- `Identifiers` → `identifiers_schema` (ClassVar default + 31 subclass bodies)
- `name` → `query_id` (ClassVar on the typed bases + 39 subclass bodies + 9 consumer sites)
- `QueryDescription.name` → `QueryDescription.query_id` (field + every reader)

The simple `CypherQuery` path already uses the target names — it is NOT renamed.

**OPUS sub-steps (judgement — do these first, by hand):**

1. `src/orthograph/query/base_models.py`:
   - `ReadQuery`: rename the ClassVar declarations `Params` → `params_schema`,
     `name` → `query_id`. In `__init_subclass__`:
     `_auto_populate_classvar(cls, "Params", ...)` → `"params_schema"`;
     `_enforce_query_contract(..., model_attrs=("Params","Output"), other_attrs=("name","backend"))`
     → `model_attrs=("params_schema","Output"), other_attrs=("query_id","backend")`.
   - `WriteQuery`: same rename of `Params`/`name`; same `__init_subclass__` updates
     (`model_attrs=("params_schema",)`, `other_attrs=("query_id","backend")`).
2. `src/orthograph/cypher/base_models.py`:
   - `CypherReadQuery` / `CypherWriteQuery`: auto-populate target `"Params"` →
     `"params_schema"`; class default `Identifiers: ClassVar[...] = NoIdentifiers` →
     `identifiers_schema: ClassVar[...] = NoIdentifiers`. Update `_validate_declarative_cypher`
     and any conflict-detection error message strings to name the new attrs.
   - `__init__` still binds `self._identifiers` — but it must now read
     `type(self).identifiers_schema` (was `.Identifiers`). Keep the private attr name
     `self._identifiers` (internal, not part of the vocabulary).
3. `src/orthograph/backends/gqlalchemy/base_models.py`:
   - `GqlAlchemyReadQuery`/`GqlAlchemyWriteQuery`: `Identifiers = NoIdentifiers` →
     `identifiers_schema = NoIdentifiers`.
4. `src/orthograph/cypher/generator.py` (dynamic synthesis): the dict passed to
   `type(name, bases, dict)` must use `"params_schema"`/`"query_id"` (and
   `"identifiers_schema"` if set) as keys. Find every `"Params"`/`"name"`/`"Identifiers"`
   string key in the synthesis dict and rename. **This is the one place a blind
   find/replace fails** (the keys are string literals, not attribute accesses).
5. `src/orthograph/query/catalogue.py`:
   - `QueryDescription`: field `name: str` → `query_id: str`.
   - `register_read`/`register_write`: `query.name` → `query.query_id`.
   - `describe()` comprehensions: reads/writes `q.name`→`q.query_id`,
     `q.Params`→`q.params_schema`; the simple comprehension already uses
     `q.query_id`/`q.params_schema`. Every `QueryDescription(name=...)` →
     `QueryDescription(query_id=...)`.
   - `names()`: `d.name` → `d.query_id`. `get()`: `desc.name` → `desc.query_id`.
6. `src/orthograph/cypher/validation.py`: the `_extract_query_spec` dispatcher and
   `validate_*` readers — `query.name`→`query.query_id`, `query.Params`→`query.params_schema`,
   `query.Identifiers`→`query.identifiers_schema`. (One dispatcher post-E59.)
7. `src/orthograph/cypher/query_execution.py`: in `_query_shape` (not yet deleted —
   E60.2 deletes it), the typed fallback reads `query.Params`/`query.name` → rename to
   `query.params_schema`/`query.query_id`. (E60.2 then removes the method entirely.)
8. Run `python -m mypy src/orthograph` — it will flag EVERY remaining `.Params`/
   `.Identifiers`/`.name` ClassVar access in subclasses as the rename's worklist.

### STOP — hand to Haiku

**Haiku sub-steps (mechanical — verbatim find/replace within these files only):**

In each of `src/orthograph/graph_profile/queries/shared.py`,
`src/orthograph/backends/neo4j/queries.py`,
`src/orthograph/backends/memgraph/queries.py`, replace, **only inside class bodies of
`CypherReadQuery`/`CypherWriteQuery` subclasses**, the ClassVar assignments:
- `    Params = ` → `    params_schema = `
- `    Identifiers = ` → `    identifiers_schema = `
- `    name = ` → `    query_id = `
- in imperative `def build(self, params: NoParams)` bodies, leave signatures as-is
  (param NAME `params` is fine; it is the ClassVar that renamed).

Then run mypy + the suite. Fix any remaining `.Params`/`.name`/`.Identifiers`
attribute access that mypy reports until clean.

**Acceptance gate:**
- [ ] `grep -rn "\.Params\b\|\.Identifiers\b\|ClassVar.*\bname\b" src/orthograph` shows
      no typed-query ClassVar named `Params`/`Identifiers`/`name` (the simple-path
      `params_schema`/`identifiers_schema`/`query_id` and unrelated `name` locals are fine).
- [ ] `QueryDescription` has `query_id`, not `name`; all readers updated.
- [ ] `python -m mypy src/orthograph` clean.
- [ ] `python -m pytest -q` green (test edits for renamed attrs allowed here if any
      test reads `.Params`/`.name` directly; notebook updates are E60.4).

---

### E60.2 — Collapse the reconciliation sites

**Model:** **Sonnet.** **Type:** Code (source). **Depends on:** E60.1 (suite green).

**Goal:** Now that all paths share names, delete the bridging.

**What to do:**
1. `src/orthograph/cypher/query_execution.py`:
   - Delete `CypherExecutor._query_shape` entirely.
   - In `_prepare_statement`, replace the `params_model, query_identity = self._query_shape(query)`
     call with direct reads: `params_model = query.params_schema` and
     `query_identity = query.query_id`. (Both attrs now exist on every query type.)
2. `src/orthograph/query/catalogue.py` — `describe()`: collapse the three comprehensions
   into ONE loop over `self.queries()` (reads, then writes, then simple — preserve
   order). Read `q.query_id` and `q.params_schema` uniformly. **Keep** the per-kind
   `kind`/`output_schema`/`output_class` logic: reads/writes have an `Output` (read →
   schema; write → schema-or-None); simple `CypherQuery` has `kind="read"`,
   `output_schema=None`, `output_class=None`. Do NOT lose the write/simple distinctions —
   only the identity+params reads are unified. (A small `isinstance`/source-tag helper
   is acceptable here; it is per-KIND output shaping, not name reconciliation.)
3. `cypher/validation.py`: E59's `_extract_query_spec` is already unified; E60.1 already
   renamed the attribute it reads. Confirm no `getattr(..., "Params", ...)` /
   `... or query.name` reconciliation remains; delete any that does.

**Acceptance gate:**
- [ ] `_query_shape` no longer exists; `_prepare_statement` reads `query.params_schema`
      and `query.query_id` directly.
- [ ] `describe()` is one comprehension/loop over `queries()`; no `getattr` fallback.
- [ ] No `getattr(query, "params_schema", None) or query.Params` or `... or query.name`
      anywhere: `grep -rn "or query.Params\|or query.name\|_query_shape" src/orthograph`
      returns nothing.
- [ ] `python -m mypy src/orthograph` clean; `python -m pytest -q` green.

---

### E60.3 — Option A: `CypherQuery` binds identifiers at construction; unify `build(params)`; delete adapters

**Model:** **OPUS** for the `CypherQuery` construction/build redesign and the executor
call-site change; **STOP** then Sonnet for the adapter deletion + test-double cleanup.
**Type:** Code (source). **Depends on:** E60.2. **Read ADR-045 §Q4 before starting.**

**Why Opus:** this changes a public `build()` contract and adds construction-time
binding to a Pydantic `BaseModel` without touching its serialization surface. The
serialization hazard (a stray field leaking into `model_dump`/YAML) is the trap.

**OPUS sub-steps:**

1. `src/orthograph/cypher/query.py` — `CypherQuery`:
   - Add a **`PrivateAttr`** for bound identifier values:
     `_identifiers: BaseModel = PrivateAttr()` (import `PrivateAttr` from `pydantic`).
     This is NOT a Pydantic field — it does not appear in `model_dump`/JSON-Schema, so
     the YAML wire format is unchanged.
   - Accept identifier values at construction. Pydantic v2 pattern: add
     ```python
     def model_post_init(self, __context: Any) -> None:
         schema = self.identifiers_schema or NoIdentifiers
         self._identifiers = schema.model_validate(self.__pydantic_extra__... )
     ```
     BUT identifier values cannot ride on a `BaseModel`'s normal fields without becoming
     a field. **Cleanest approach:** keep `__init__` Pydantic-managed and accept the raw
     identifier values via a dedicated keyword that is excluded from the model. Two
     acceptable implementations — pick the one that keeps `model_dump` unchanged and
     passes the round-trip test:
     - (a) Override `__init__(self, *, identifiers=None, **data)`: pop `identifiers`,
       call `super().__init__(**data)`, then in body bind
       `self._identifiers = (self.identifiers_schema or NoIdentifiers).model_validate(identifiers or {})`.
     - (b) Keep the existing field-based init and bind in `model_post_init` from a
       transient, reading identifiers passed via `model_config`/context.
     Prefer (a) — it mirrors `CypherReadQuery.__init__` most closely and is explicit.
   - Change `build` to: `def build(self, params: BaseModel) -> CypherQueryData:` —
     remove `**kwargs` and the `identifiers` parameter. Body:
     `rendered = render_with_identifiers(self.cypher_template, self._identifiers)`;
     `return CypherQueryData(rendered, params.model_dump(exclude_unset=True))`.
     Remove `_validate_call_kwargs` (no kwargs anymore) or repurpose it to validate
     `params` is an instance of `self.params_schema`.
   - Update `CypherQuery`'s class docstring: identifiers are now bound at construction
     (symmetric with the typed path); `build` takes a `params` model.
2. `src/orthograph/cypher/query_execution.py` — `CypherExecutor._prepare_statement`
   already calls `query.build(params)` after E60.2; confirm it now works for
   `CypherQuery` directly (no adapter).
3. **YAML round-trip guard:** add/confirm a test that loads a `CypherQuery` from YAML,
   `model_dump(by_alias=True)`s it, and asserts the output dict has exactly the five
   fields (`query_id`, `cypher_template`, `description`, `params_schema`,
   `identifiers_schema`) and NO `identifiers`/`_identifiers` key. This is the gate that
   proves the `PrivateAttr` did not leak.

### STOP — hand to Sonnet

**Sonnet sub-steps (delete the now-dead adapters + fix their direct users):**

4. `src/orthograph/cypher/query_execution.py`: delete `CypherQueryReadAdapter` and
   `CypherQueryWriteAdapter` entirely. Remove their names from `__all__` / re-exports
   (check `execution.py` and `cypher/__init__.py`).
5. Update every direct adapter instantiation in tests to pass the `CypherQuery`
   directly to the executor and bind identifiers (if any) at construction:
   - `tests/cypher/test_query_execution.py` lines ~368, 400, 440, 472 — replace
     `adapter = CypherQueryReadAdapter(query); executor.read(adapter, {...})` with
     `executor.read(query, MyParams(**{...}))` (construct the params model).
   - `tests/cypher/test_query_e2e.py` lines ~131, 154, 183, 207, 237, 269, 307, 342 —
     same pattern (these are `@pytest.mark.neo4j`; run only if neo4j is available, but
     they must still import/collect cleanly).
6. Update the root API surface (`execution.py`) if it re-exported the adapters.

**Acceptance gate:**
- [ ] `CypherQuery.build` signature is `build(self, params: BaseModel)` — no `**kwargs`,
      no `identifiers` param.
- [ ] `CypherQuery` binds `self._identifiers` at construction via a `PrivateAttr`;
      `model_dump(by_alias=True)` yields exactly the five existing fields (round-trip
      test green) — **YAML wire format unchanged.**
- [ ] `CypherQueryReadAdapter`/`CypherQueryWriteAdapter` deleted; no import of them
      anywhere: `grep -rn "CypherQuery.*Adapter" src tests` returns nothing.
- [ ] Executor runs `CypherQuery` instances directly via `query.build(params)`.
- [ ] `python -m mypy src/orthograph` clean; `python -m pytest -q` green (neo4j-marked
      tests at least collect; run them if a DB is available).

---

### E60.4 — Update notebooks for the new build/construction shape

**Model:** **Haiku.** **Type:** Docs/notebooks (+ any stray test). **Depends on:** E60.3.

**Goal:** Bring every direct `CypherQuery` consumer onto the new shape.

**What to do (mechanical, find each occurrence):**
1. In notebooks under `notebooks/` (esp. `03.03_cypher_query_usage.ipynb`) replace:
   - `query.build(field=value, ...)` → construct the params model first:
     `query.build(MyParams(field=value, ...))` (use the query's declared
     `params_schema` class).
   - `query.build(identifiers=Foo(...), field=value)` → move identifiers to
     construction: `CypherQuery(..., identifiers_schema=Foo, identifiers=Foo(...))`
     then `query.build(MyParams(field=value))`.
2. Re-run affected notebooks (`--nbval-lax` is in `addopts`) so they execute clean.
3. Fix any test still calling `query.build(**kwargs)` that E60.3 did not cover.

**Acceptance gate:**
- [ ] No `.build(` call in `notebooks/` or `tests/` passes bare keyword params or an
      `identifiers=` argument: `grep -rn "\.build([a-z_]*=" notebooks tests` reviewed,
      all use a single params-model positional arg.
- [ ] `python -m pytest -q` green (incl. notebook execution).

---

### E60.5 — Update ADR status, E39 epic text, overview, module docstrings

**Model:** **Haiku.** **Type:** Docs. **Depends on:** E60.4.

**Goal:** Close the loop and unblock E39 cleanly.

**What to do (verbatim edits):**
1. `.agentic/decisions/045-query-shape-alignment-rename-strategy.md`: set Status to
   `Accepted — implemented (E60, <date>)`.
2. `.agentic/planning/active_epics/E39_async_query_runner.md` — update the stale
   references so E39 starts against the aligned codebase:
   - T5 code snippet: `query.Params.model_validate(...)` → `query.params_schema.model_validate(...)`;
     `CypherExecutor._validate_cypher(cypher, query.name)` → `..., query.query_id)`.
   - Remove the sentence "The existing `CypherQueryReadAdapter`/`CypherQueryWriteAdapter`
     are reused unchanged …" — the adapters no longer exist. Replace with: "The async
     executor accepts `CypherQuery` and typed queries directly (adapters removed by E60);
     all expose `params_schema`/`query_id` and `build(params)`."
   - Shared Reference table row for `query_execution.py`: drop "adapters" mention.
   - Reality-Check item 8 still holds (query-definition layer reused) — leave it, but
     note the attribute names are now `params_schema`/`query_id`.
3. `.agentic/planning/overview.md`: mark E60 status; confirm E39 lists E60 as a
   predecessor.
4. Module docstrings: `src/orthograph/queries.py` and `src/orthograph/execution.py` —
   one sentence each stating all query paths share `params_schema`/`identifiers_schema`/
   `query_id`/`cypher_template` and `build(params)`.

**Acceptance gate:**
- [ ] ADR-045 Status updated.
- [ ] E39 epic text references no adapters and uses `params_schema`/`query_id`.
- [ ] `overview.md` reflects E60 done and E39 → depends-on-E60.
- [ ] `python -m pytest -q` green after doc edits.

---

### E60.6 — Rename base CLASSES to `…QueryModel` (signal "subclass me, don't instantiate")

**Model:** **Sonnet** for the rename decision points (the 4 class defs, the `__all__`
exports, the generic-base references in `__init_subclass__`/`_extract_generic_args`);
**STOP** then Haiku for the bulk symbol find/replace across subclasses, tests, notebooks.
**Type:** Code (source + tests + notebooks) — **pure symbol rename, zero behaviour change.**
**Depends on:** E60.5 (the whole attribute-rename epic must be green first — never share
a commit with E60.1).

**Why this task exists (and why LAST + separate):** the abstract bases are *models to
subclass*, not classes to instantiate — unlike `CypherQuery`, which IS instantiated.
The `…Model` suffix makes that contract self-evident (mirrors Pydantic's `BaseModel`).
This is a ~326-occurrence symbol rename; keeping it out of E60.1 keeps each commit
reviewable and bisectable. It is cheapest now, before E39 and the ORM path add more
subclasses.

**The rename (NOTE the backend-agnostic vs Cypher distinction — do NOT prefix the
agnostic bases with "Cypher"):**

| Current | New | Lives in | Rationale |
|---|---|---|---|
| `ReadQuery` | `ReadQueryModel` | `query/base_models.py` | backend-AGNOSTIC base (gqlalchemy subclasses it too) — NOT Cypher-specific |
| `WriteQuery` | `WriteQueryModel` | `query/base_models.py` | same |
| `CypherReadQuery` | `TypedCypherReadQueryModel` | `cypher/base_models.py` | Cypher-specific typed base |
| `CypherWriteQuery` | `TypedCypherWriteQueryModel` | `cypher/base_models.py` | Cypher-specific typed base |

> **Do NOT rename `CypherQuery`** — it is the instantiable simple-path class; keeping it
> without the `Model` suffix is the whole point of the distinction.
> `GqlAlchemyReadQuery`/`GqlAlchemyWriteQuery` MAY optionally also gain the `Model`
> suffix for consistency (`GqlAlchemyReadQueryModel`) — Sonnet decides; if unsure, leave
> them and note it. They are abstract too, so the suffix is defensible.

**SONNET sub-steps (judgement — the rename anchors):**
1. `src/orthograph/query/base_models.py`: rename the two `class ReadQuery(...)` /
   `class WriteQuery(...)` definitions and the `_extract_generic_args(cls, ReadQuery)` /
   `(cls, WriteQuery)` references inside `__init_subclass__` (the generic base passed to
   the extractor MUST match the renamed class). Update `__all__`.
2. `src/orthograph/cypher/base_models.py`: rename `class CypherReadQuery(ReadQuery[...])`
   → `class TypedCypherReadQueryModel(ReadQueryModel[...])` and the write equivalent;
   update the `_extract_generic_args(cls, CypherReadQuery)` references and `__all__`.
3. Check re-export surfaces: `src/orthograph/queries.py`, `src/orthograph/execution.py`,
   `src/orthograph/cypher/__init__.py`, `src/orthograph/query/__init__.py` — update any
   `from ... import ReadQuery as ...` / `__all__` entries.
4. Decide the gqlalchemy-suffix question (sub-step note above) and record it in the gate.

### STOP — hand to Haiku

**HAIKU sub-steps (verbatim whole-word symbol replace, ORDER MATTERS — do the longest
names first to avoid partial collisions):**
1. `CypherReadQuery` → `TypedCypherReadQueryModel` (whole word) across `src`, `tests`,
   `notebooks`.
2. `CypherWriteQuery` → `TypedCypherWriteQueryModel` (whole word) across all three.
3. `ReadQuery` → `ReadQueryModel` (whole word) — **only after** steps 1–2, so the
   `Cypher*` names are already gone and won't be double-touched. Exclude any match that
   is already part of `TypedCypherReadQueryModel`/`GqlAlchemyReadQuery` (whole-word
   boundary handles this; verify `GqlAlchemyReadQuery` was intentionally left or also
   renamed per Sonnet's decision).
4. `WriteQuery` → `WriteQueryModel` (whole word), same caveat.
5. Run `python -m mypy src/orthograph` and `python -m pytest -q` (incl. notebooks).
   Fix any stragglers mypy reports.

**Acceptance gate:**
- [ ] The four bases are renamed: `ReadQueryModel`, `WriteQueryModel`,
      `TypedCypherReadQueryModel`, `TypedCypherWriteQueryModel`.
- [ ] `CypherQuery` is UNCHANGED (still no `Model` suffix).
- [ ] gqlalchemy-base decision recorded (renamed-for-consistency OR left, with a one-line
      reason).
- [ ] No dangling old names: `grep -rwn "ReadQuery\b\|WriteQuery\b\|CypherReadQuery\b\|CypherWriteQuery\b" src tests notebooks`
      returns nothing (whole-word; the new `…Model` names and `CypherQuery` are fine).
- [ ] `python -m mypy src/orthograph` clean; `python -m pytest -q` green.
- [ ] **Zero behaviour change** — only symbols renamed; no logic, no signatures touched.

---

## Success Criteria (epic-level)

- [ ] All three query paths expose `params_schema` / `identifiers_schema` / `query_id`;
      `cypher_template` already shared.
- [ ] One construction shape (`Q(identifiers=...)`) and one build shape (`build(params)`)
      across typed and simple paths; `**kwargs` gone from the build surface.
- [ ] No generic consumer reconciles names: `_query_shape` deleted, `describe()` one
      loop, validation one dispatcher, adapters deleted.
- [ ] The three query *types* remain distinct — no union, no shared hierarchy.
- [ ] YAML wire format byte-for-byte unchanged (round-trip test green).
- [ ] Base classes renamed to `…QueryModel` (E60.6): `ReadQueryModel`, `WriteQueryModel`,
      `TypedCypherReadQueryModel`, `TypedCypherWriteQueryModel`; `CypherQuery` unchanged.
- [ ] `python -m pytest -q` (incl. notebooks) green; `python -m mypy src/orthograph`
      clean; `tests/test_architecture.py` green.
- [ ] E39 epic text updated; E39 unblocked.

---

## Out of Scope

- Unifying `ReadQuery`/`WriteQuery`/`CypherQuery` into one type/union (rejected — paths
  stay parallel).
- The validation public-API split (E59 — done).
- Changing the YAML wire format (must stay identical — gated by E60.3 round-trip test).
- Async execution (E39 — starts AFTER this epic).
- Any `ValidationIssue` code/severity/message change.

---

## Shared Reference

> Point any single-task agent at **this section + their task section + ADR-045 (if told)**.

### Decision authority
- **[ADR-045](../../decisions/045-query-shape-alignment-rename-strategy.md)** — rename
  direction, hard-rename policy, Option A (construction-time identifier binding via
  `PrivateAttr`), adapter deletion, E39 sequencing, the verified facts.

### Relevant files (verified paths)

| File | Role |
|---|---|
| `src/orthograph/query/base_models.py` | `ReadQuery`/`WriteQuery` ClassVars + `__init_subclass__` auto-population. E60.1; class rename → `ReadQueryModel`/`WriteQueryModel` E60.6. |
| `src/orthograph/cypher/base_models.py` | `CypherReadQuery`/`CypherWriteQuery`, `__init__` (`self._identifiers`), `build(params)`. E60.1; class rename → `TypedCypher…QueryModel` E60.6. |
| `src/orthograph/cypher/query.py` | `CypherQuery` (Pydantic model, fields, serializers, `build`). E60.3 adds construction-time identifier binding + `build(params)`. |
| `src/orthograph/cypher/query_execution.py` | `CypherExecutor`, `_prepare_statement`, `_query_shape` (delete E60.2), adapters (delete E60.3). |
| `src/orthograph/query/catalogue.py` | `QueryDescription`, `register_*`, `describe()` (3 comprehensions). E60.1 rename + E60.2 collapse. |
| `src/orthograph/cypher/validation.py` | `_extract_query_spec` dispatcher (E59). E60.1 renames attrs it reads. |
| `src/orthograph/cypher/generator.py` | Dynamic `type()` synthesis — string-literal dict keys. E60.1 (Opus sub-step 4). |
| `src/orthograph/backends/neo4j/queries.py` | 19 typed subclasses. E60.1 Haiku tail. |
| `src/orthograph/backends/memgraph/queries.py` | 13 typed subclasses. E60.1 Haiku tail. |
| `src/orthograph/graph_profile/queries/shared.py` | 4 typed subclasses. E60.1 Haiku tail. |
| `src/orthograph/backends/gqlalchemy/base_models.py` | 2 abstract bases (`identifiers_schema`). E60.1 Opus sub-step 3. |
| `src/orthograph/io/query_catalogue_yaml.py` | YAML loader — already uses `query_id`/`params_schema`. Unchanged; round-trip gate in E60.3. |
| `tests/cypher/test_query_execution.py` | Adapter unit tests. E60.3 rewrites to direct executor calls. |
| `tests/cypher/test_query_e2e.py` | Adapter e2e tests (`@pytest.mark.neo4j`). E60.3 rewrites. |
| `notebooks/03.03_cypher_query_usage.ipynb` | Direct `build(**kwargs)` usage. E60.4. |

### The one-vocabulary contract (what every path exposes after E60)
- `params_schema: type[BaseModel]` (the params model class)
- `identifiers_schema: type[BaseModel] | None` (the identifiers model class)
- `query_id: str` (identity)
- `cypher_template: str`
- `build(self, params: BaseModel) -> CypherQueryData` (identifiers bound at construction)

### Verification commands
- `python -m mypy src/orthograph`
- `python -m pytest -q`
- `python -m pytest -q tests/test_architecture.py`
- Reconciliation-gone check: `grep -rn "_query_shape\|or query.Params\|or query.name\|CypherQuery.*Adapter" src tests` → empty.

---

## Changelog

- **2026-06-29** — Epic created from E56 W4. ADR-045 ratified (E60.0). Second decision
  pass: Q1 confirmed hard-rename + fix consumers; Q2 widened to rename
  `QueryDescription.name`; Q4 chose **Option A** (construction-time identifier binding,
  adapters deleted, `**kwargs` removed) after verifying the executor never passes
  identifiers and YAML stores schema-only. A false premise in the first ADR draft
  ("template rendered at construction") was corrected. Tasks sized with Opus/Sonnet
  judgement heads and Haiku/Sonnet mechanical tails behind STOP markers. E39 sequenced
  strictly after E60.
- **2026-06-29** — Added Q6 / E60.6: rename the abstract bases to `…QueryModel`
  (`ReadQueryModel`, `WriteQueryModel`, `TypedCypherReadQueryModel`,
  `TypedCypherWriteQueryModel`) to signal "subclass me". Corrected the proposed name —
  `ReadQuery`/`WriteQuery` are backend-agnostic (gqlalchemy subclasses them) so they get
  `ReadQueryModel`, NOT a `Cypher` prefix. `CypherQuery` stays unsuffixed (instantiable).
  Kept as a dedicated last, behaviour-free, separate-commit task (~326 occurrences) so it
  never collides with the E60.1 attribute rename.
