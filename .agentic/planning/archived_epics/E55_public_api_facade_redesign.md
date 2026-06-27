# Epic E55: Public API Facade Redesign — Intent-Named Capability Surface

> **Priority:** High (this is the "new-API epic" that E48 is explicitly blocked
>   by; the current `api/` surface is ambiguous and hides shipped capabilities)
> **Phase:** v0.1.0 / pre-pilot
> **Type:** Facade restructure (additive new modules + **clean removal** of the
>   two redundant legacy modules); **no core-logic change** except one small
>   single-source accessor in `backends/loader.py` and a PRD/CONTEXT doc fix.
>   *(Revised 2026-06-26: the facade is fixed before any external dependency relies
>   on it, so `model.py`/`database.py` are removed outright — no deprecation shims;
>   internal consumers migrate in the same change.)*
> **Decisions:** ADR-016 (declared/observed naming and the deferred facade) ·
>   ADR-017 (package topology) · ADR-011 (capability seams — `api/` is vendor-free)
> **Rubric (every task judged against this):** one verb = one operand pair ·
>   avoid duplication · single source of truth · data traceability ·
>   adding code must not force edits in many places · strongly-typed ·
>   docstring + name + typed args readable by a human **and** an agent ·
>   `api/` stays vendor-free (architecture invariants 3 & 4 stay green) ·
>   no existing consumer breaks · each task ends green with guardrails run

---

## Why This Epic Exists

The current consumer facade (`api/model.py`, `api/database.py`,
`api/visualization.py`) is partial, ambiguous, and misleading:

1. **`validate` is overloaded three ways** across two modules — `model.validate`
   (in-memory data), `database.validate` (live DB vs definition),
   `model.validate_query` (a Cypher string). A reader/agent cannot infer the
   operand from the verb; only the argument shape disambiguates.
2. **Shipped comparisons are invisible.** The engine implements
   `compare_profiles` (staging↔prod, US 31) and `compare_definitions`
   (version↔version, US 30) — both fully implemented — yet neither is exposed in
   `api/`, and the PRD (line 343) wrongly calls them "planned, not yet
   implemented".
3. **"Definition creation + validation" has no home.** `validate_definition`
   (internal structural consistency, distinct from validating data) is not a
   facade verb.
4. **Query authoring/cataloguing is half-exposed.** `load_query_catalogue`
   returns a bare `list[CypherQuery]`, not an assembled `QueryCatalogue`;
   `QueryCatalogue`, the typed-query bases, `CypherGenerator` auto-CRUD,
   `NoParams`/`NoIdentifiers` are not surfaced — consumers must reach into
   `orthograph.query.*` / `orthograph.cypher.*` (the namespaces ADR-016 says to
   keep behind the facade).
5. **"Select backend" is a magic string** with no discovery (`available` /
   `can_inspect` / `can_execute`).

This epic restructures `api/` into **seven intent-named modules** — one
unambiguous verb per requested capability — and **removes** the old `model.py` /
`database.py` outright (clean break, no shims), migrating every internal consumer
to the new verbs in the same change.

---

## Decisions Already Made (locked with the requester — do not re-litigate)

- **Vocabulary = "description"** for the declared side (not "model"):
   `api.description`, `validate_description`, `compare.profile_to_description`
   — per ADR-016, the declared contract is the "description" layer (distinguishes it from
   `GraphDefinition` the class name). The engine function `compare_profile_to_definition`
   internally uses "definition" language; the facade exposes "description" to callers.
- **Restructure into new modules** and **remove `model.py` + `database.py`**
  (clean break — revised 2026-06-26: facade fixed before any external dependency
  relies on it; all internal/test consumers migrate in the same change).
- **Backend selection = Option B:** the backend name set lives **only** in
  `backends/loader._BACKENDS`. The loader grows derived accessors
  (`backend_names`, `capabilities`); the facade adds the
  availability/capability *join* (`available`/`is_available`/`can_inspect`/
  `can_execute`). `backend: str` typing (no hand-written enum — that would be a
  third copy of the name list and could drift). Adding a backend stays a **2-edit**
  change (one `BackendSpec`, one `dependencies` tuple).
- **Fix the PRD doc error** (compare_profiles/compare_definitions are implemented).

### Final facade topology

```
api/
├── __init__.py        # docstring-only (invariant 4); points at the 7 modules
├── description.py     # NEW  declared contract: author / load / save / validate
├── profile.py         # NEW  observed side: inspect -> GraphProfile
├── compare.py         # NEW  the 3 comparisons, one verb each
├── queries.py         # NEW  author / build / catalogue / validate / generate
├── execution.py       # NEW  run typed read/write queries
├── backends.py        # NEW  typed selection + capability discovery
└── visualization.py   # KEEP unchanged
# model.py / database.py  REMOVED (E55.8 — clean break, no shims)
```

---

## Hard Constraints Discovered in Current Code (must honour)

| Constraint | Source | Implication |
|------------|--------|-------------|
| **No re-exports in any `__init__.py`** | `tests/test_architecture.py` invariant 4 (only `importlib.metadata` in root) | `api/__init__.py` stays docstring-only; all re-exports go **in the submodules**. |
| **No top-level `orthograph.backends.*` import in `api/`** | invariant 3 | `profile`/`execution`/`backends` reach the loader via `from orthograph.backends import loader` (the ImportFrom `module` is `orthograph.backends`, which passes) — **never** `from orthograph.backends.loader import …`. |
| `backends/gqlalchemy/client.py` migrated to low-level API | grep | E55.8 **migrates** it to `loader` + `compare_profile_to_definition` directly (not via `api.database`); dependency direction correct (internal → core, never core → api). |
| `tests/cypher/test_query_e2e.py` migrated from `api.model.load_query_catalogue` | grep | E55.8 **migrates** it to `io.query_catalogue_yaml.load_query_catalogue_string` (still returns `list[CypherQuery]`). |
| `tests/domain_examples/…`, `notebooks/…` imported from removed modules | grep | E55.10 (deferred) will migrate `api.database.inspect` callers to `api.profile.inspect`; docs remain broken until then. |
| `tests/api/test_model.py`, `test_database.py` tested old modules | grep | E55.8 **deletes** these tests; new coverage lives in `test_description.py`, `test_profile.py`, etc. |

---

## Existing Code to Reuse / Touch

| Need | Reuse / Touch | Location |
|------|---------------|----------|
| Backend wiring (single source of names) | `_BACKENDS`, `BackendSpec`, `load_inspector`, `load_executor` | `backends/loader.py` |
| Availability probe | `is_available`, `MissingDependencyError` | `dependencies.py` |
| Declared side | `GraphDefinition` (+ `validate_structure`), `NodeModel`, `RelationshipModel`, cardinality models | `graph_definition/{graph_definition,models}.py` |
| In-memory data validation | `GraphValidator.validate` | `graph_definition/validation.py` |
| Observed side | `GraphProfile` | `graph_profile/models.py` |
| Inspector dispatch | `loader.load_inspector(name)().inspect(connection, **kw)` | current `api/database.py:27` |
| The three comparisons | `compare_profile_to_definition`, `compare_profiles`, `compare_definitions` | `comparison/engine.py` |
| Comparison rule type | `Rule` | `comparison/rules.py` |
| Query catalogue + typed bases | `QueryCatalogue`, `CypherReadQuery`, `CypherWriteQuery`, `CypherQuery`, `NoParams`, `NoIdentifiers` | `query/catalogue.py`, `cypher/{base_models,query,bindings}.py` |
| Auto-CRUD | `CypherGenerator` (`match_by_uid_query`/`merge_query`/`create_query`/`delete_by_uid_query`) | `cypher/generator.py` |
| Static query validation | `validate_cypher`, `validate_query_catalogue`, `validate_query_catalogue_against_profile` | `cypher/{parser,validation}.py` |
| YAML catalogue load | `load_query_catalogue_file` / `_string`, `list_catalogue_queries` | `io/query_catalogue_yaml.py` |
| Typed execution | `loader.load_executor(name)(factory).read/.write`, `ReadQuery`/`WriteQuery`/`P`/`R`/`D` | current `api/database.py:60`, `query/base_models.py` |
| Existing facade (the verbs to migrate, then remove) | `model.py`, `database.py` | `api/` |

---

## Per-Task Guardrails (apply to EVERY task unless stated)

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

`api/` must stay vendor-free — run `python -m pytest tests/test_architecture.py -q`
on any task that adds an `api/` module or import. E55.8 removes the legacy
`model.py`/`database.py` and must leave the suite green with every consumer
migrated to the new verbs.

---

## Tasks (execute in order; each ends green)

### E55.0 — Decisions confirmation note + PRD/CONTEXT doc fix

> **Model: Opus.** Decision-record + doc accuracy. Cheap in code, but it pins the
> naming ("definition"), the removal policy, and corrects a PRD statement every
> later task relies on; getting the vocabulary and the layering wording right here
> prevents churn across all seven modules.

**Goal:** the documented facade matches what this epic builds, and the PRD no
longer claims a shipped capability is unbuilt.

**Operation (docs only — no production code):**
1. Fix PRD `product_requirements_document.md` line ~343: change the
   version-to-version comparison from *"(planned, not yet implemented)"* to
   implemented, naming `api.compare.profiles` (profile↔profile, US 31) and
   `api.compare.definitions` (definition↔definition, US 30).
2. Update PRD line ~14 and `CONTEXT.md` line ~14 ("consumer-facing API surface")
   to describe the seven modules (the legacy `model`/`database` modules are
   **removed** by E55.8 — no shims).
3. Record the locked decisions (vocabulary = "definition"; Option-B backend
   discovery; clean-removal policy) inline in this epic's "Decisions Already Made"
   (already present) and add a short ADR **only if** a reviewer asks — default: no
   new ADR, reuse ADR-016/017.

**Done when:** PRD/CONTEXT read true against the planned surface; no code, no tests.

**Care / risks:** keep CONTEXT.md a routing table — link, do not duplicate prose.

---

### E55.1 — Single-source backend discovery accessors in the loader

> **Model: Opus.** Touches the one module that owns backend identity. Must derive
> from `_BACKENDS` (zero name duplication) and not break `load_inspector` /
> `load_executor`; the whole Option-B "2-edit to add a backend" property depends
> on this being obviously correct.

**Goal:** the loader exposes the backend name set and per-backend capabilities,
derived from the existing wiring table, so the facade adds only a *join*.

**Operation** — in `backends/loader.py`:
1. Add `@dataclass(frozen=True) BackendCapabilities` with `can_inspect: bool`,
   `can_execute: bool`.
2. Add `backend_names() -> list[str]` → `sorted(_BACKENDS)`.
3. Add `capabilities(name: str) -> BackendCapabilities` deriving
   `can_inspect = spec.inspector is not None`,
   `can_execute = spec.executor is not None`; raise `MissingDependencyError`
   (consistent message with `load_inspector`) on an unknown name.

**Tests (TDD — write first)** — `tests/backends/test_loader.py`:
- `backend_names()` returns the five wired names, sorted, no duplicates.
- `capabilities("networkx")` → inspect-only; `capabilities("cypher")` →
  execute-only; `capabilities("neo4j")` → both; `capabilities("gqlalchemy")` →
  neither.
- `capabilities("nope")` raises `MissingDependencyError`.

**Care / risks:** do not import any vendor package — read the table only. The
`deferred_executor_reason` backends (gqlalchemy) report `can_execute=False`
(intentionally; the message stays a `load_executor` concern).

---

### E55.2 — `api.backends` — typed selection + capability discovery

> **Model: Sonnet.** Thin join over E55.1 + `dependencies.is_available`; spec
> fully pinned. The only subtlety is honouring invariant 3 (reach the loader via
> the module import form).

**Goal:** a consumer/agent can discover which backends are installed and what each
can do, without magic-string guesswork.

**Operation** — new `api/backends.py`:
- `available() -> list[str]` → `[n for n in loader.backend_names() if dependencies.is_available(n)]`.
- `is_available(backend: str) -> bool` → delegate to `dependencies.is_available`.
- `can_inspect(backend: str) -> bool` / `can_execute(backend: str) -> bool` →
  `loader.capabilities(backend).can_inspect/.can_execute`.
- Import the loader as `from orthograph.backends import loader` (module form,
  invariant-3 safe). Docstring lists the verbs and points at `available()` as the
  source of legal `backend` strings (compensates for `str` typing).

**Tests (TDD — write first)** — `tests/api/test_backends.py`:
- `available()` is a subset of `loader.backend_names()` and contains only
  installed ones (mock `dependencies.is_available`).
- `can_inspect`/`can_execute` match the loader capabilities for each backend.
- unknown backend in `can_inspect`/`can_execute` raises `MissingDependencyError`;
  `is_available("nope")` returns `False`.

**Care / risks:** do not duplicate the name list here — derive everything from the
loader. Confirm `tests/test_architecture.py` stays green (no top-level backend
import).

---

### E55.3 — `api.description` — author / load / save / validate the declared contract

> **Model: Opus.** Public-API design surface and the split of the overloaded
> `validate` into `validate_definition` (structural consistency) vs
> `validate_data` (records vs contract). Naming here sets the tone for the whole
> facade and must read unambiguously to an agent.

**Goal:** one module owns the declared side: re-export the authoring primitives
and expose four unambiguous verbs.

**Operation** — new `api/description.py`:
- Re-export (module-level, NOT in `__init__`): `NodeModel`, `RelationshipModel`,
  `GraphDefinition`, `CardinalitySpec`, `ConditionalCardinality`,
  `ConditionalRule`, `PropMatch`.
- Add a `DescriptionFormat` enum (single source in `io/formats.py`) fixed on
  `YAML` for now; JSON to be added later without changing call sites. Re-export it.
- `load_from_file(path: str | Path, format: DescriptionFormat = DescriptionFormat.YAML) -> GraphDefinition`
  (wraps `io.yaml.load_yaml_file`).
- `save_to_file(definition: GraphDefinition, path: str | Path, format: DescriptionFormat = DescriptionFormat.YAML) -> None`
  (wraps `io.yaml.save_yaml_file`; param `definition`, accept positionally).
- `validate_definition(definition: GraphDefinition) -> ValidationResult` — wraps
  `GraphDefinition.validate_structure()` (internal consistency; US "definition
  creation + validation").
- `validate_data(definition, nodes, relationships=None) -> ValidationResult` —
  wraps `GraphValidator(definition).validate(...)` (the former `model.validate`).
- `__all__` listing every re-export and verb; rich docstrings (operand stated in
  the first line of each).

**Tests (TDD — write first)** — `tests/api/test_description.py`:
- `load_from_file`/`save_to_file` round-trip a YAML definition; `format` defaults
  to `DescriptionFormat.YAML`.
- `validate_definition` returns `is_valid` for a consistent definition and
  surfaces a structural issue (e.g. `ISOLATED_NODE`) for a suspect one (note:
  structural *errors* like undefined refs are rejected at construction time).
- `validate_data` accepts valid nodes/rels and flags an invalid record.
- the re-exported primitives are importable from `api.description`.

**Care / risks:** `validate_definition` vs `validate_data` must be impossible to
confuse — first docstring line names the operand. Do not import vendors.

---

### E55.4 — `api.profile` — inspect a backend into a `GraphProfile`

> **Model: Sonnet.** Mostly a move of the existing `database.inspect` body; spec
> pinned. Care: keep `**backend_kwargs` forwarding and the loader module-import
> form intact.

**Goal:** one verb produces the observed side.

**Operation** — new `api/profile.py`:
- Re-export `GraphProfile`.
- `inspect(backend: str, connection: Any, **backend_kwargs: Any) -> GraphProfile`
  — body identical to current `database.inspect` (`loader.load_inspector(name)().inspect(...)`),
  via `from orthograph.backends import loader`.

**Tests (TDD — write first)** — `tests/api/test_profile.py`:
- `inspect("networkx", nx_graph)` returns a `GraphProfile` (in-memory, no mock).
- `inspect("neo4j", driver)` dispatches to the neo4j inspector (mock the loader);
  `backend_kwargs` (e.g. `database=`) are forwarded.
- unknown backend raises `MissingDependencyError`.

**Care / risks:** keep stateless per-call semantics (Constraint 13); do not store
the connection.

---

### E55.5 — `api.compare` — the three comparisons, one verb each

> **Model: Opus.** Surfaces two currently-hidden shipped capabilities (US 30/31)
> and fixes the central ambiguity. The verb names (`profile_to_definition`,
> `profiles`, `definitions`) are the headline ergonomics of the whole epic.

**Goal:** every comparison the engine supports has exactly one English-reading
facade verb.

**Operation** — new `api/compare.py`:
- `profile_to_definition(profile: GraphProfile, definition: GraphDefinition, rules: Sequence[Rule] | None = None) -> ValidationResult`
  → `compare_profile_to_definition`.
- `profiles(left: GraphProfile, right: GraphProfile, rules: Sequence[Rule] | None = None) -> ValidationResult`
  → `compare_profiles` (US 31).
- `definitions(left: GraphDefinition, right: GraphDefinition, rules: Sequence[Rule] | None = None) -> ValidationResult`
  → `compare_definitions` (US 30).
- Re-export `Rule` for the `rules=` override.

**Tests (TDD — write first)** — `tests/api/test_compare.py`:
- `profile_to_definition` flags drift (missing label) and passes a matching pair.
- `profiles` returns INFO-only diff for two profiles differing in a label/count.
- `definitions` returns INFO-only diff for two definition versions differing in a
  property/cardinality.
- `rules=` override is honoured for each verb.

**Care / risks:** these delegate only — no comparison logic moves. Confirm the PRD
fix from E55.0 names these exact verbs.

---

### E55.6 — `api.queries` — author / build / catalogue / validate / generate

> **Model: Opus.** The widest surface: it must expose typed-query declaration,
> simple-query building, an **assembled** catalogue loader (today's facade returns
> a list — the ergonomics defect), auto-CRUD, and three validation verbs — all
> without leaking `orthograph.query.*` / `orthograph.cypher.*`. Design-heavy.

**Goal:** the whole query-governance capability is reachable from one facade
module; `load_catalogue` returns a ready-to-use `QueryCatalogue`.

**Operation** — new `api/queries.py`:
- Re-export: `QueryCatalogue`, `CypherQuery`, `CypherReadQuery`, `CypherWriteQuery`,
  `NoParams`, `NoIdentifiers`, and the exceptions `CypherQueryError`,
  `CypherCatalogueLoadError`.
- `new_catalogue() -> QueryCatalogue` → `QueryCatalogue()`.
- `load_catalogue(source: str | Path) -> QueryCatalogue` — load the YAML specs
  (reuse `load_query_catalogue_file`/`_string`) **and register each** into a fresh
  `QueryCatalogue` via `register_cypher_query`, returning the assembled catalogue.
- `simple_query(name, cypher_template, *, params=NoParams, identifiers=None, description=None) -> CypherQuery`
  — construct a `CypherQuery` (maps to its `Params`/`Identifiers` constructor).
- `generate_crud(definition: GraphDefinition) -> QueryCatalogue` — build a
  `CypherGenerator(definition)`, register get-by-uid/merge/create/delete typed
  queries for every node type with a UID, return the catalogue.
- `validate_query(query: str | CypherQuery, definition) -> ValidationResult` —
  string → `validate_cypher`; `CypherQuery` → its `validate_query(definition)`.
- `validate_catalogue(catalogue, definition) -> ValidationResult` →
  `validate_query_catalogue`.
- `validate_catalogue_against_profile(catalogue, profile, definition, rules=None) -> ValidationResult`
  → `validate_query_catalogue_against_profile`.

**Tests (TDD — write first)** — `tests/api/test_queries.py`:
- `load_catalogue` returns a `QueryCatalogue` whose `names()` matches the YAML
  entries (round-trip), and the assembled catalogue validates against a matching
  definition.
- `new_catalogue()` is empty; `register_read`/`register_cypher_query` work on it.
- `simple_query(...)` builds a usable `CypherQuery`; `validate_query` accepts both
  a string and a `CypherQuery`.
- `generate_crud(definition)` produces a non-empty catalogue with the expected
  query names for a node type with a UID; the catalogue validates against the
  definition.
- `validate_catalogue` and `validate_catalogue_against_profile` return the same
  results as the underlying functions for a known fixture.

**Care / risks:** `load_catalogue` is the behaviour change vs the old
`load_query_catalogue` (list → assembled catalogue) — the old name stays a list in
the shim (E55.8). Keep `generate_crud`'s contract documented (which ops, when a
type has no UID it is skipped). No vendor imports.

---

### E55.7 — `api.execution` — run typed read/write queries

> **Model: Sonnet.** Move of the existing `database.query`/`execute` bodies with a
> verb rename to `run_read`/`run_write`; spec pinned. Care: keep the
> `connection_factory` (not a driver) contract and the loader module-import form.

**Goal:** typed execution has direction-named verbs that state their result shape.

**Operation** — new `api/execution.py`:
- `run_read(backend: str, connection_factory: Callable[[], Any], read_query: ReadQuery[P, D], params: Any) -> list[D]`
  — body of current `database.query`.
- `run_write(backend: str, connection_factory: Callable[[], Any], write_query: WriteQuery[P, R], params: Any) -> R`
  — body of current `database.execute`.
- Re-export `ReadQuery`, `WriteQuery` (and `ReadPort`/`QueryBackedReadPort` if a
  test needs them — otherwise leave them in `query.base_models`).

**Tests (TDD — write first)** — `tests/api/test_execution.py`:
- `run_read` round-trips a typed `CypherReadQuery` via a `FakeGraphSession`
  factory and returns `list[Output]`.
- `run_write` returns the interpreted write result.
- unknown / execute-incapable backend (`networkx`) raises `MissingDependencyError`.

**Care / risks:** `connection_factory` is a callable returning a session context
manager (per the current contract) — do **not** confuse it with the `inspect`
driver argument. Orthograph opens/closes per call, stores nothing (Constraint 13).

---

### E55.8 — Clean break: remove `api.model` + `api.database` (no shims)

> **Model: Sonnet.** Decision revised (2026-06-26): the facade is fixed **before**
> any external dependency relies on it, so the two redundant modules are **removed
> outright** rather than kept as deprecation shims. All real internal consumers are
> migrated to the new intent-named verbs in the same change. Mechanical-but-careful:
> every old call site must move to the correct new module verb.

**Goal:** `api.model` and `api.database` no longer exist; every consumer imports the
intent-named modules directly; the suite stays green with no deprecation layer.

**Operation:**
1. Delete `api/model.py` and `api/database.py` (and their tests
   `tests/api/test_model.py`, `tests/api/test_database.py` — coverage now lives in
   `test_description`, `test_queries`, `test_profile`, `test_compare`,
   `test_execution`).
2. Migrate `backends/gqlalchemy/client.py` off the removed `api.database.validate`.
   A backend is **lower-level than `api/`**, so it must depend on the low-level
   constructs directly (never import `orthograph.api.*` — that would invert the
   dependency direction): call `loader.load_inspector(name=backend)().inspect(...)`
   then `comparison.engine.compare_profile_to_definition(...)` — exactly the body
   the old API wrapped.
3. Migrate the remaining `.py` consumers that pytest collects:
   - `tests/cypher/test_query_e2e.py` — the old `model.load_query_catalogue`
     returned a `list[CypherQuery]`; point it at
     `io.query_catalogue_yaml.load_query_catalogue_string` (the list loader),
     **not** the new assembled `queries.load_catalogue`.
   - `notebooks/shared/utils.py` / `dash_app.py` —
     `api.database.inspect` → `api.profile.inspect`.
   - `api/visualization.py` docstring example —
     `database.inspect` → `profile.inspect`.
4. Rewrite `api/__init__.py` docstring to list the seven modules. **No imports**
   in `__init__` (invariant 4). No mention of removed modules.

**Tests / verify:**
- `tests/api`, `tests/cypher/test_query_e2e.py`, `tests/test_architecture.py` green.
- full suite + mypy + pre-commit green.
- no remaining `api.model` / `api.database` import anywhere in `*.py`.

**Care / risks:** `tests/cypher/test_query_e2e.py` and the YAML callers expect a
**list**, so reuse the list loader (`load_query_catalogue_string`), not the
assembled `queries.load_catalogue`. Remaining `.ipynb` notebooks + README prose
references migrate in **E55.10** (documentation pass).


---

### E55.9 — Architecture-invariant + integration sweep

> **Model: Haiku.** Fully-specified verification + mechanical cross-reference
> updates; success is "every guardrail green and the new modules obey the
> invariants". No design judgement.

**Operation:**
1. Run `tests/test_architecture.py` and confirm all five invariants pass with the
   new `api/` modules present (esp. 3: no top-level backend import; 4: no
   `__init__` re-export).
2. Add the **E55 row** to `.agentic/planning/overview.md` (Epics table + the
   "AFTER the new-API epic (NOT YET CREATED)" note now resolves to E55 → unblock
   E48's wording; Epic Files list).
3. Confirm `.agentic/CONTEXT.md` line ~14 facade description matches (edited in
   E55.0); add a routing row for the seven-module surface if missing.
4. Run the full suite + mypy + pre-commit and confirm green.

**Tests / verify:**
```
pwsh> python -m pytest -q
pwsh> python -m pytest tests/test_architecture.py -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

**Care / risks:** purely mechanical/verification — if an architecture invariant
fails, **stop and escalate** to the owning task (E55.2/E55.4/E55.7 for backend
imports, E55.8 for `__init__`), do not weaken the invariant test.

---

### E55.10 — Demo/notebook ergonomics pass (consumer-facing)

> **Model: Haiku.** Documentation/example only — wire the new verbs into the
> existing notebook helpers/examples so a human can read the intended flow. No
> production-code logic, no assertion changes.

**Operation:**
1. The `.py` notebook helpers (`notebooks/shared/utils.py` / `dash_app.py`) and
   the `tests/cypher/test_query_e2e.py` import were already migrated in E55.8.
   Migrate the remaining **`.ipynb` notebooks**, `README.rst`, and the
   `notebooks/shared/profiles.py` prose note off `api.model` / `api.database` to
   the new modules (`profile.inspect`, `description.*`,
   `compare.profile_to_definition`, etc.). The legacy modules are **gone** — these
   references would otherwise break.
2. Add a short end-to-end example (in an existing example/notebook or a docstring)
   that exercises: `description.load_from_file` → `profile.inspect` →
   `compare.profile_to_definition` → `queries.load_catalogue` →
   `queries.validate_catalogue` → `execution.run_read` → `visualization.render_*`,
   and `backends.available()`.
3. Migrate any remaining `tests/domain_examples/…` imports to the new modules.

**Tests / verify:** the touched example/notebook helper imports resolve; full
suite stays green.

**Care / risks:** examples only — if updating an import surfaces a real behaviour
gap in a new module, **stop and escalate** to that module's task rather than
patching the example around it.

---

## Model Assignment Summary

| Task | Model | Why |
|------|-------|-----|
| E55.0 Decisions note + PRD/CONTEXT fix | **Opus** | pins vocabulary + corrects a PRD claim every task cites |
| E55.1 Loader discovery accessors | **Opus** | owns backend identity; single-source correctness |
| E55.2 `api.backends` | **Sonnet** | thin join, spec pinned; invariant-3 care |
| E55.3 `api.description` | **Opus** | public-API design; the `validate_definition`/`validate_data` split |
| E55.4 `api.profile` | **Sonnet** | move + forward kwargs; pinned |
| E55.5 `api.compare` | **Opus** | surfaces hidden capabilities; headline verb names |
| E55.6 `api.queries` | **Opus** | widest surface; assembled-catalogue design + CRUD |
| E55.7 `api.execution` | **Sonnet** | move + verb rename; factory-contract care |
| E55.8 Clean removal of `model`/`database` | **Sonnet** | mechanical consumer migration; clean-break risk |
| E55.9 Invariant + integration sweep | **Haiku** | fully-specified verification |
| E55.10 Demo/notebook ergonomics | **Haiku** | examples/docs only |

---

## Success Criteria

- [ ] PRD/CONTEXT describe the seven-module facade; the "planned, not implemented"
      claim for profile↔profile / definition↔definition is corrected (E55.0).
- [ ] `backends/loader.py` exposes `backend_names()` + `capabilities()` derived
      from `_BACKENDS` (no name duplication); adding a backend stays a 2-edit change.
- [ ] `api.backends` exposes `available`/`is_available`/`can_inspect`/`can_execute`
      with no hand-written name list.
- [ ] `api.description` splits `validate_definition` (structure) from `validate_data`
      (records) and re-exports the authoring primitives.
- [ ] `api.profile.inspect` and `api.execution.run_read`/`run_write` reproduce the
      current behaviour under intent-named verbs.
- [ ] `api.compare.{profile_to_definition,profiles,definitions}` expose all three
      shipped comparisons.
- [ ] `api.queries.load_catalogue` returns an **assembled** `QueryCatalogue`;
      `simple_query`, `generate_crud`, and the three validation verbs work; no
      `orthograph.query.*`/`orthograph.cypher.*` leak into consumer code.
- [ ] `api.model` and `api.database` are **removed**; every internal consumer
      (`gqlalchemy/client.py`, the notebook `.py` helpers, `test_query_e2e.py`) is
      migrated to the new verbs and the suite stays green — no deprecation layer.
- [ ] `tests/test_architecture.py` (all five invariants), full suite, mypy, and
      pre-commit are green; overview + CONTEXT updated; E48's blocker resolved.

---

## Out of Scope

- A hand-written `Backend` enum (Option A) — rejected: third copy of the name
  list, drift risk (decision locked to Option B).
- Deprecation shims for `model`/`database` — rejected (revised 2026-06-26): the
  facade is fixed before any external dependency relies on it, so the modules are
  removed outright and consumers migrate in E55.8.
- Configuration knobs (`severity_threshold`, inspector `value_counts_top_n` /
  Neo4j `strategy`) — that is **E48**, which this epic unblocks by reserving the
  config-ready entry-point seam; not built here.
- YAML catalogue authoring format decisions — that is E19 (scoping); `load_catalogue`
  reuses the existing loader as-is.
- Async facade verbs — E39 owns the async query runner; the facade stays sync this
  phase.
- Any change to comparison/validation/inspection **logic** — this epic is facade +
  one loader accessor + docs only.
