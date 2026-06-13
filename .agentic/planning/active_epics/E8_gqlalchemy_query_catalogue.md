# Epic E8: GQLAlchemy Query Catalogue

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Provide a schema-validated, named-query registry for GQLAlchemy builder expressions (Python-only)
> **Blocked by:** E16 (typed query contract: `ReadQuery`/`WriteQuery`/`Executor`/`QueryCatalogue`),
> E17 T2.5 (the `Identifiers`/`Params` mechanism this epic implements in the builder dialect)
> **Relates to:** ADR-010 (declared identifier parameters — **this epic confirms the split in
> code**, closing the report's "confirm in code at E8" follow-on), ADR-009, ADR-006 (GQLAlchemy
> integration)
> **User stories:** 14, 16

---

## Context

The GQLAlchemy Query Catalogue parallels the typed Cypher catalogue (E16) but for GQLAlchemy
**builder expressions**. A GQLAlchemy query is Python code, e.g.
`match().node(labels="Person", variable="n").where(...).return_()` — there is **no Cypher string
template**, so the `<<placeholder>>` rendering from ADR-010 does not apply. Instead, this epic
realises the *declaration-level* `Identifiers`/`Params` split (validated backend-neutral in
`.agentic/reviews/2026-06-10-graphorm-adr-validation-report.md`) in the builder dialect:

- `Identifiers` (labels / relationship types) → **builder method arguments**
  (`node(labels=...)`, `.to(relationship_type=...)`), each validated via `validate_identifier`
  (from E17 T1) **before** the builder call.
- `Params` (values) → **value bindings** (`.where(prop == value)`).
- `build()` returns a **builder object** (legal under `query/base_models.py`'s `build() -> Any`), not a
  `(cypher, dict)` tuple.

Since builder patterns are Python (not serialisable strings), this catalogue is **Python-only** —
no YAML mode.

**Architectural principle:** Same as E16 — Orthograph provides the registry, the typed bases, and
validation; consuming projects provide queries, connections (passed per-call, never stored), and
orchestration.

**Existing surface to build on (read before starting):**
- `src/orthograph/query/base_models.py` — `ReadQuery[P, D]` / `WriteQuery[P, R]` / `Executor` /
  `QueryBackedReadPort` / `Backend.GQLALCHEMY` (already defined).
- `src/orthograph/query/catalogue.py` — `QueryCatalogue` + `describe()` (reuse pattern).
- `src/orthograph/extensions/gqlalchemy/query_builder.py` — `ValidatedQueryBuilder` +
  `_extract_cypher` (renders a builder to Cypher) + `_validate_cypher` (validates against model).
- `src/orthograph/extensions/gqlalchemy/codegen.py` — `generate_gqlalchemy_classes` /
  `GqlAlchemySchema` (label → generated Node class).
- `src/orthograph/extensions/gqlalchemy/result_adapter.py` — `validate_gqa_result` /
  `gqa_results_to_graph_data` (the GQLAlchemy analogue of `materialize()`).

---

## Tasks

### E8.1: GQLAlchemy typed query bases (`GqlAlchemyReadQuery` / `GqlAlchemyWriteQuery`)

**What:** The GraphORM analogue of `cypher/base_models.py` — abstract bases over the `typed.py`
contract that fix `backend = Backend.GQLALCHEMY` and realise the `Identifiers`/`Params` split via
builder calls. **This task confirms ADR-010's split in code.**

**Actions (new file `src/orthograph/backends/gqlalchemy/base_models.py`):**
1. `GqlAlchemyReadQuery(ReadQuery[P, D])` and `GqlAlchemyWriteQuery(WriteQuery[P, R])` with
   `backend = Backend.GQLALCHEMY` and an empty-default `Identifiers: ClassVar[type[BaseModel]] =
   NoIdentifiers` (the public empty model from `orthograph.cypher`, mirroring the
   Cypher base; the generic `typed.py` signature stays `[P, D]` — do NOT add a third generic
   param). A value-only query declares `Params = NoParams` (also public, reused from the Cypher
   layer); `Params` stays mandatory because it is the generic `P`.
2. `build(self, params: P) -> Any` is **abstract / author-implemented** here (unlike the Cypher
   declarative default): the author writes the builder expression. Document the convention that
   `build()` must call `validate_identifier(value, kind=...)` on every `Identifiers` field before
   passing it to a builder method (`node(labels=...)`, `.to(relationship_type=...)`), and pass
   `Params` values into `.where(...)` bindings.
3. Provide a small helper (e.g. `validated_label(idents.label)`) so authors get the identifier
   safety without re-importing — keep it thin, no magic.
4. `materialize()` stays abstract — implemented per query, typically delegating to
   `result_adapter` helpers.

**Acceptance criteria:**
- [ ] `from orthograph.backends.gqlalchemy import GqlAlchemyReadQuery, GqlAlchemyWriteQuery`
- [ ] A concrete subclass declaring `Identifiers = {label}` + `Params` + `Output` constructs and
      its `build()` returns a GQLAlchemy builder object (not a tuple).
- [ ] An injected label (`"x) DETACH DELETE (n"`) passed as an `Identifiers` value raises via
      `validate_identifier` before the builder is constructed.
- [ ] The `typed.py` generic base is unchanged (diff shows no edit); `build()` returning a builder
      passes through `Executor` without the executor assuming a tuple shape.
- [ ] Tests cover: value-only query (no `Identifiers`), label-only query, relationship query
      (label + rel-type) — the three sketches from the validation report.

---

### E8.2: `GqlAlchemyQueryCatalogue` — register / lookup / introspect

**What:** The registry, parallel to `QueryCatalogue` (E16), holding `GqlAlchemyReadQuery`/
`GqlAlchemyWriteQuery` instances and exposing `describe()` for uniform introspection.

**Actions (new file `src/orthograph/catalogue/gqlalchemy.py`):**
1. `GqlAlchemyQueryCatalogue(model=model)` — takes a `GraphDataModel`.
2. `register_read(query)` / `register_write(query)` (mirror `registry.py`), unique names across
   reads+writes, duplicate raises `ValueError`.
3. `names()` / `describe()` / `queries()` (reuse the `QueryDescription` dataclass from
   `registry.py`; `backend = GQLALCHEMY`; `params_schema` from `Params.model_json_schema()`;
   `output_schema` from `Output` for reads).
4. **Registration-time schema validation:** for each registered query, render a representative
   builder to Cypher via `query_builder._extract_cypher` and validate against the model via
   `_validate_cypher` (label references / property accesses consistent with the model). Surface
   inconsistencies as a structured error at registration.

**Acceptance criteria:**
- [ ] `GqlAlchemyQueryCatalogue(model=model)` constructs.
- [ ] `register_read` / `register_write` enforce unique names.
- [ ] `describe()` returns `QueryDescription`s with `backend == Backend.GQLALCHEMY`.
- [ ] Registration validates label/property references against the model and raises on unknowns.
- [ ] Tests cover registration, lookup, duplicate-name error, validation error.

---

### E8.3: GQLAlchemy `Executor` — per-call connection + result validation

**What:** The single I/O seam for GQLAlchemy, implementing `typed.py`'s `Executor` ABC. Connection
is **never stored** — a factory callable is passed at construction (PRD / E10 connection-ownership
rule).

**Actions (new file `src/orthograph/extensions/gqlalchemy/executor.py`):**
1. `GqlAlchemyExecutor(Executor)` constructed with a db-client factory callable.
2. `read(query, raw_params)`: validate `raw_params` → `query.build(params)` (pure, returns builder)
   → open client → `execute_and_fetch` → `materialize()` each row → return `list[D]`. Commits
   nothing.
3. `write(query, raw_params)`: validate → build → execute → commit → `interpret_result()`.
4. Optional `validate_results=True` path routes rows through `result_adapter.validate_gqa_result`.

**Acceptance criteria:**
- [ ] `read` / `write` are distinct methods (no kind flag).
- [ ] Connection is opened per-call from the factory and never held as instance state.
- [ ] `read` returns statically-typed `list[D]`; `write` returns `R`.
- [ ] Optional result validation against the model works.
- [ ] Tests with a mocked GQLAlchemy database client (no live DB).

---

### E8.4: Package structure and public API

**Actions:**
1. `from orthograph.catalogue import GqlAlchemyQueryCatalogue` works.
2. Catalogue lives in `src/orthograph/catalogue/gqlalchemy.py`; bases in
   `src/orthograph/extensions/gqlalchemy/base_models.py`; executor in
   `.../gqlalchemy/executor.py`.
3. Optional dependency: importable only when the `gqlalchemy` extra is installed (guard mirrors
   `codegen.py`'s import-guard pattern).

**Acceptance criteria:**
- [ ] Public imports resolve with the extra installed; a clear `ImportError` without it.
- [ ] `mypy src/` clean; `ruff check` clean.

---

### E8.5: Notebook demonstrating registration and execution

**Actions:**
1. A notebook mirroring `notebooks/04.01_typed_cypher_queries.ipynb` but for GQLAlchemy: define a
   model, write 2–3 `GqlAlchemyReadQuery` subclasses (value-only, label identifier, relationship),
   register them, `describe()`, and execute via `GqlAlchemyExecutor` against a mocked or live
   client.

**Acceptance criteria:**
- [ ] Notebook runs end-to-end (mock acceptable; live Memgraph if available).
- [ ] Demonstrates the `Identifiers`/`Params` split visibly (a label-parametric query alongside a
      value-only one).

---

## Relationship to Other Epics

- **E16** provides the typed contract (`ReadQuery`/`WriteQuery`/`Executor`/`QueryCatalogue`) this
  epic implements for the builder dialect.
- **E17 T2.5** establishes the `Identifiers`/`Params` mechanism in the Cypher dialect; this epic is
  the GraphORM counterpart and **confirms ADR-010's backend-neutrality in code**.
- **E11** populates this catalogue with auto-generated operations.
- **E12** (retired → E16) — the shared ABC already lives in `typed.py`.
- **E9** must be complete to establish the composition boundary this catalogue respects.
