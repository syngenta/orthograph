# Epic E52: GQLAlchemy Backend — Complete Delivery & Bug Sweep

> **Priority:** High (consolidation; out of *current* execution scope but the
> single authoritative home for all GQLAlchemy work)
> **Phase:** v0.1.0 — Pilot Readiness (Pilot B path)
> **Status:** planned — **not started**
> **Consolidates / supersedes:** E8 (GQLAlchemy Query Catalogue), E9 (GQLAlchemy
> Client Review). Both are retired into this epic so GQLAlchemy is delivered and
> hardened as **one coherent unit** rather than discovered piecemeal "too late".
> **Blocked by:** E16 (typed query contract — done) for the catalogue/executor
> tasks; the client + codegen tasks are independent and can start immediately.
> **Decisions:** ADR-006 (GQLAlchemy integration as optional backend),
> ADR-010 (declared `Identifiers`/`Params` split — this epic confirms it in the
> builder dialect), ADR-009 (inspector/query alignment), ADR-011 (capability
> seams + backend isolation), PRD Constraint 13 (connections never owned),
> PRD Constraint 3 (not an ORM — validated composition only).
> **User stories:** 14, 15, 16, 21.
> **Origin:** 2026-06-25 MatProt profiling session. While confirming the library
> had **no** reserved-name (`type`) collision on the *inspect/profile/compare*
> path, a real `type`-name collision **was** found on the GQLAlchemy **codegen**
> path (`codegen.py:127`). GQLAlchemy is out of the immediate execution window,
> so this latent bug would only surface when a pilot finally exercises codegen —
> exactly the "rediscover too late" failure mode. This epic captures it now and
> packages it with the remaining GQLAlchemy delivery so the backend ships
> complete and correct in one pass.

---

## Why one epic

GQLAlchemy work is currently split across E8 (forward delivery: catalogue +
executor) and E9 (cleanup: remove persistence ownership), with a newly-found
codegen bug homeless. Delivering them separately means:

- the backend is never "done" at a single, reviewable checkpoint;
- a consuming pilot adopts a half-built surface (bases exist, no catalogue/executor);
- latent bugs (the `type` clobber) sit undiscovered until a pilot trips them.

Consolidating gives **one** acceptance bar: *"GQLAlchemy is feature-complete,
composition-correct (Constraint 13), bug-swept, and demonstrated end-to-end."*

---

## Current state of `src/orthograph/backends/gqlalchemy/` (read before starting)

| File | State | Notes |
|------|-------|-------|
| `base_models.py` | **built** | `GqlAlchemyReadQuery` / `GqlAlchemyWriteQuery` with `Identifiers`/`Params` split + `validated_label`. (Was E8.1 — done.) |
| `codegen.py` | built, **has bug** | `generate_gqlalchemy_classes` / `GqlAlchemySchema`. `_build_rel_class` clobbers a user property named `type` (see W1). |
| `query_builder.py` | built | `ValidatedQueryBuilder`, `_extract_cypher`, `_validate_cypher`. |
| `result_adapter.py` | built | `validate_gqa_result`, `gqa_results_to_graph_data`. |
| `client.py` | built, **violates Constraint 13** | `GqlAlchemyClient` stores `db` and owns `save_node`/`save_relationship`/`execute` persistence. (E9 target.) |
| `catalogue/gqlalchemy.py` | **missing** | `GqlAlchemyQueryCatalogue` — not built (was E8.2). |
| `executor.py` | **missing** | `GqlAlchemyExecutor` — not built (was E8.3). |

Tests exist for base_models, client, codegen, query_builder, result_adapter
under `tests/backends/gqlalchemy/`.

---

## Workstreams & Tasks

The epic has three workstreams: **D**elivery (forward features), **C**leanup
(composition correctness), **W** bug sweep (latent defects).

### Workstream D — Delivery (forward features, from E8)

> Carries E8.2–E8.5 verbatim in intent. E8.1 (`base_models.py`) is already done;
> verify it against the acceptance criteria below rather than rebuild it.

#### D1 — `GqlAlchemyQueryCatalogue` (was E8.2)
Registry parallel to `QueryCatalogue` (E16), holding `GqlAlchemyReadQuery`/
`GqlAlchemyWriteQuery` instances, exposing `describe()` for uniform introspection,
and validating label/property references against the model at registration
(render representative builder → `_extract_cypher` → `_validate_cypher`).

**Acceptance:**
- [ ] `from orthograph.catalogue import GqlAlchemyQueryCatalogue` constructs with a `GraphDefinition`.
- [ ] `register_read`/`register_write` enforce unique names across reads+writes.
- [ ] `describe()` returns `QueryDescription`s with `backend == Backend.GQLALCHEMY`.
- [ ] Registration validates references against the model and raises on unknown label/property.
- [ ] Tests: registration, lookup, duplicate-name error, validation error.

#### D2 — `GqlAlchemyExecutor` (was E8.3)
Single I/O seam implementing `query/base_models.py`'s `Executor` ABC. Connection
is **never stored** — a db-client factory callable is passed at construction
(Constraint 13). `read` → validate params → `build` → open client →
`execute_and_fetch` → `materialize` each row → `list[D]` (commits nothing).
`write` → validate → build → execute → commit → `interpret_result`. Optional
`validate_results=True` routes rows through `result_adapter.validate_gqa_result`.

**Acceptance:**
- [ ] `read`/`write` are distinct methods (no kind flag).
- [ ] Connection opened per-call from the factory; never held as instance state.
- [ ] `read` returns statically-typed `list[D]`; `write` returns `R`.
- [ ] Optional result validation works.
- [ ] Tests with a mocked GQLAlchemy client (no live DB).

#### D3 — Package structure & public API (was E8.4)
`from orthograph.catalogue import GqlAlchemyQueryCatalogue`; executor under
`backends/gqlalchemy/executor.py`; importable only with the `gqlalchemy` extra
(guard mirrors `codegen.py`).

**Acceptance:**
- [ ] Public imports resolve with the extra; clear `ImportError` without it.
- [ ] `mypy src/` clean; `ruff check` clean; `tests/test_architecture.py` passes (no backend cross-imports).

#### D4 — Notebook end-to-end (was E8.5)
Notebook mirroring `notebooks/04.01_typed_cypher_queries.ipynb`: define a model,
write 2–3 `GqlAlchemyReadQuery` subclasses (value-only, label identifier,
relationship), register, `describe()`, execute via `GqlAlchemyExecutor`.

**Acceptance:**
- [ ] Runs end-to-end (mock acceptable; live Memgraph if available).
- [ ] Shows the `Identifiers`/`Params` split (a label-parametric query alongside a value-only one).

### Workstream C — Cleanup / composition correctness (from E9)

> **HITL:** changes the public client surface; review downstream consumers
> (notebooks, tests) before removing methods.

#### C1 — Audit `GqlAlchemyClient` (was E9.1)
Classify every method keep / remove / refactor against the validated-composition
pattern (Orthograph validates + generates; the consuming project persists).

**Acceptance:**
- [ ] Written per-method classification.
- [ ] External consumers of `save_*` identified (notebooks, tests).
- [ ] Migration path documented for each removed method.

#### C2 — Remove persistence ownership (was E9.2)
Remove `save_node()`, `save_relationship()`, and any method calling `db.save_*`/
`db.execute()` for persistence. Stop storing `db` as instance state. Keep
validation + codegen + result-adaptation surfaces.

**Acceptance:**
- [ ] No `save_node`/`save_relationship`; `db` not stored as instance state (Constraint 13).
- [ ] Validation methods remain and work independently of any connection.
- [ ] Codegen and result-adapter functionality unchanged.
- [ ] Tests updated: deleted-method tests removed; a test asserts no connection storage.

#### C3 — Document the composition pattern (was E9.3)
Docstrings + notebook (`03.03`/`03.04`) showing: generate classes → instantiate →
`node.save(db)` (GQLAlchemy's own call, owned by the consumer) → validate results
with `validate_gqa_result`.

**Acceptance:**
- [ ] Remaining public methods document the composition pattern.
- [ ] A notebook shows the new pattern.
- [ ] The extension contract doc reflects GQLAlchemy's revised role.

### Workstream W — Bug sweep

#### W1 — codegen clobbers a user property named `type` (the trigger bug)

**Defect (confirmed 2026-06-25):** `_build_rel_class` (`codegen.py:113-129`)
builds the dynamic class with the model's property annotations in `namespace`,
then unconditionally runs `setattr(cls, "type", rel_label)` (line 127) to set
GQLAlchemy's relationship-type attribute. If a `RelationshipModel` declares a
**user property literally named `type`**, this `setattr` overwrites it with the
relationship **label** string — the property's value/annotation is lost on every
generated instance.

Reproduction (run, observed):
```python
class HasType(RelationshipModel):
    __label__ = "OPERATES"; __source_label__ = "A"; __target_label__ = "B"
    type: str
cls = _build_rel_class(HasType)
getattr(cls, "type")   # -> "OPERATES"  (clobbered; expected the property)
```

**Why it matters / why now:** This is the same class of meta-vs-user-property
collision that the *inspect/profile/compare* path was just proven **immune** to
(meta carried by dunders, properties backtick-quoted). Codegen is the one place
the library uses the **bare** name `type` as a meta attribute, colliding with a
legal user property. GQLAlchemy being out of the active window means this only
bites when a pilot first generates classes from a model with a `type` property —
the "rediscover too late" risk this epic exists to retire.

**Scope of the fix — decision required (see Open Decision below):**
- The Orthograph *graph_definition* side has **no reserved-name handling** and
  needs none for inspection (dunder convention). The collision is purely an
  artefact of how `gqlalchemy.Relationship` exposes its type. The fix lives in
  `backends/gqlalchemy/codegen.py` (and possibly `result_adapter.py`), **not** in
  `graph_definition/`.
- Candidate fixes (pick one in the ADR/scoping):
  1. **Detect-and-reject:** at codegen, if a `RelationshipModel` declares a
     property named `type` (or any GQLAlchemy-reserved attribute — `_type`,
     `_labels`, `_node_id`, …), raise a clear `GraphDefinitionError` naming the
     collision. Cheapest; honest; forbids a legal model shape.
  2. **Map-and-preserve:** store the user `type` under a non-colliding GQLAlchemy
     property key and translate on read/write in `result_adapter`, keeping the
     meta `type` for GQLAlchemy. Preserves the model shape; adds a translation
     layer the result adapter must mirror (read path) to avoid asymmetry.
  3. **Audit the full reserved set first:** enumerate every attribute GQLAlchemy
     `Node`/`Relationship` reserves (`type`, `labels`, `_id`, `_node_id`,
     `_start_node_id`, `_end_node_id`, …) and apply the chosen strategy to **all**
     of them, not just `type` — otherwise W1 recurs under a different name.

**Acceptance:**
- [ ] An ADR (or a recorded decision in this epic) selects reject vs map-and-preserve and the **full** reserved-attribute set.
- [ ] A `RelationshipModel`/`NodeModel` with a property colliding a GQLAlchemy-reserved attribute either (a) raises a clear, named error at codegen, or (b) round-trips correctly (codegen **and** result adapter), per the decision.
- [ ] A regression test reproduces the original `type`-clobber and asserts the chosen behaviour.
- [ ] The non-GQLAlchemy paths (inspect/profile/compare) are confirmed unaffected (already proven; add a guard test if cheap).

#### W2 — General GQLAlchemy bug sweep (catch-all)

Before declaring the backend done, sweep for the latent-defect classes a pilot
would otherwise find late:
- **Pydantic v1↔v2 translation** (`_translate_type`, `codegen.py:163+`): confirm
  Optional/enum/`| None`/constrained types translate without silent type loss.
- **`validate_database`** (`client.py:140-145`): the `getattr(self._db, "_driver", None)`
  / `new_connection()` fallback reaches into GQLAlchemy internals — replace with a
  sanctioned accessor or document the coupling; ensure it does not store a driver.
- **Result-adapter symmetry:** `gqa_results_to_graph_data` must round-trip whatever
  W1's decision changes on the codegen side (no asymmetric mapping).
- **Identifier safety in the builder dialect:** every `Identifiers` value reaches a
  builder method only via `validated_label`/`validate_identifier` (injection guard).

**Acceptance:**
- [ ] Each swept item is either fixed-with-test or recorded as an explicit, justified non-issue.
- [ ] `mypy src/` + `ruff` clean; `tests/backends/gqlalchemy/` green; `tests/test_architecture.py` green.

---

## Open Decision (resolve at epic kickoff)

**How does the library reconcile user property names with GQLAlchemy's reserved
class attributes?** (W1.) The graph_definition layer is vendor-neutral and must
not gain GQLAlchemy-specific reserved-name rules (Constraint 1: no DB-specific
logic in `graph_definition/`). Therefore the reconciliation must live entirely in
`backends/gqlalchemy/`. Decide: **reject** (forbid the collision, loud + cheap)
vs **map-and-preserve** (allow it, translate in codegen + result adapter). Record
in an ADR if it sets a backend-wide convention; otherwise inline here.

---

## Guardrails

```
pwsh> python -m pytest tests/backends/gqlalchemy/ -q
pwsh> python -m pytest tests/test_architecture.py -q     # no backend cross-imports / vendor leaks
pwsh> python -m mypy src/orthograph
pwsh> python -m ruff check src/orthograph/backends/gqlalchemy
pwsh> python -m pre_commit run --files <changed files>
```

Live-DB tests opt-in (`--memgraph`); the backend must be fully testable with a
mocked client.

---

## Relationship to other epics / pilot gate

- **Supersedes E8 and E9** — both retired into this epic; their tasks map to
  Workstreams D and C respectively (E8.1 already done).
- **E11** (Auto-Generated CRUD) populates `GqlAlchemyQueryCatalogue` once D1/D2 land.
- **E16** (done) provides the typed contract D1/D2 implement for the builder dialect.
- **Pilot Readiness gate (E7, done):** the gate's GQLAlchemy line items (E8, E9)
  now read against E52. The gate's *substance* is unchanged; the address moves.
- **PRD §Further Notes (Pilot B)** depends on this backend being complete.
