# ADR-045: Query Shape Alignment — Rename Strategy and Migration Contract

> **Status:** Accepted
> **Date:** 2026-06-29 (amended 2026-06-29 — Q2 and Q4 revised in second decision pass)
> **Epic:** E60 (Query Shape Alignment — One Vocabulary Across Typed / Cypher / ORM Paths)
> **Depends on:** ADR-043 (query validation public API), E59 (done — gates E60.1)
> **Relates to:** ADR-022 (generic-args auto-populate ClassVar), ADR-017 (package
>   topology), ADR-018 (query package naming), E39 (async executor — E60 must complete first)

---

## Context

Orthograph has two query authoring shapes describing the same concepts under
different attribute names. The divergence is accidental. As isolated by E56 W4,
the reconciliation is contained in `CypherExecutor._query_shape` and two near-mirror
extraction blocks in `cypher/validation.py`. Full diagnosis: E60 epic file.

This ADR records decisions from the E60.0 session (2026-06-29), amended in a
second pass the same day. The rename direction (typed path adopts Cypher names)
was ratified 2026-06-28 and is not re-litigated here.

---

## Blast-Radius Count

| ClassVar renamed | Named classes declaring it | Key files |
|---|---|---|
| `Params` → `params_schema` | **35** concrete named classes | `query/base_models.py`, `cypher/base_models.py`, `graph_profile/queries/shared.py`, `backends/neo4j/queries.py`, `backends/memgraph/queries.py`, `cypher/generator.py` (dynamic) |
| `Identifiers` → `identifiers_schema` | **31** classes (incl. abstract intermediates) | same minus `query/base_models.py` |
| `name` → `query_id` | **39** classes + 9 consumer call-sites | same + `query/catalogue.py`, `cypher/validation.py`, `cypher/query_execution.py` |

The 9 `name` consumer call-sites: `QueryCatalogue.register_read` (×1), `register_write` (×1),
`describe()` comprehensions (×2), `CypherExecutor._query_shape` (×1),
`_validate_typed_cypher_query` (×2), `_extract_typed_query_spec` (×1).

---

## Decisions

### Q1 — Hard rename, no aliases

Pre-v0.1.0 codebase. All affected classes are internal (`backends/` subclasses are
not re-exported per ADR-041). Aliases add dead weight with no benefit. E60.1 renames
every class body and consumer call-site in one commit. mypy + suite green before merge.

`cypher/generator.py` dynamic synthesis: the dict passed to `type(name, bases, dict)`
must use the new names (`"params_schema"`, `"query_id"`, `"identifiers_schema"`).

---

### Q2 — Full rename of identity attribute including `QueryDescription`

**Amended decision:** Rename the identity attribute uniformly across the entire
stack — source ClassVar on typed queries (`name` → `query_id`), `QueryDescription`
field (`name` → `query_id`), `QueryCatalogue` keys, root API surface, tests, and
notebooks. Do it now before external dependencies accumulate.

`QueryDescription.name` → `QueryDescription.query_id`. All call-sites that read
`desc.name` or `d.name` become `desc.query_id`. The three `describe()` comprehensions
collapse to one reading `q.query_id` uniformly. `register_read`/`register_write`
key on `q.query_id`. `names()`/`get()` plumbing updated accordingly.

**Rationale:** Symmetry reduces cognitive load and eliminates the need to explain why
the declared attribute and the description attribute have different names for the same
concept. Doing it now, before E39 and any ORM epic, costs least.

---

### Q3 — `__init_subclass__` auto-population strings

`_auto_populate_classvar` and `_enforce_query_contract` mechanics unchanged. Only the
string literals change:

- `query/base_models.py` — `ReadQuery.__init_subclass__`: `"Params"` → `"params_schema"`,
  `model_attrs=("Params","Output")` → `("params_schema","Output")`,
  `other_attrs=("name","backend")` → `("query_id","backend")`. Same in `WriteQuery`.
- `cypher/base_models.py` — auto-populate target `"Params"` → `"params_schema"`;
  class default `Identifiers: ClassVar = NoIdentifiers` →
  `identifiers_schema: ClassVar = NoIdentifiers`; error messages updated.
- `backends/gqlalchemy/base_models.py` — same `Identifiers` → `identifiers_schema` rename.

---

### Q4 — Delete adapters; full symmetry (Option A) — `CypherQuery` binds identifiers at construction, `build(self, params)`

**Amended decision (Option A, chosen 2026-06-29):** Delete `CypherQueryReadAdapter`
and `CypherQueryWriteAdapter` entirely within this epic, AND make `CypherQuery` bind
identifier **values** at construction so its `build` signature becomes identical to
the typed path: `build(self, params: BaseModel) -> CypherQueryData`. After this, all
three query paths share **one construction shape** (`Query(identifiers=...)`) and
**one build shape** (`build(params)`).

**Verified ground truth that makes Option A correct and bounded (2026-06-29):**

- **Typed path** (`CypherReadQuery`/`CypherWriteQuery`): identifiers bound at
  **construction** — `__init__` validates `identifiers` into the private instance
  attribute `self._identifiers` (`base_models.py:163-166/219-222`). `build(self, params: P)`
  takes NO identifiers argument and reads `self._identifiers` (`base_models.py:191`).
  Every execution call-site passes only params: `query.build(params)`
  (`query_execution.py:115`), `instance.build(NoParams())` after `query(identifiers=...)`
  (`inspection.py:99-100`).
- **Simple path today** (`CypherQuery`): `build(identifiers=None, **kwargs)` renders
  at **call time** (`query.py:269`). Identifier values are NEVER stored on the
  instance — they are purely a `build()` argument (`query.py:35-37` docstring states
  this explicitly). The **adapters never pass `identifiers=`** (`query_execution.py:186-192`),
  so the simple *execution* path is already de facto **`NoIdentifiers`-only**.
- **YAML wire format stores SHAPE only, never VALUES** (verified): `CypherQuery`'s
  five Pydantic fields are `query_id`, `cypher_template`, `description`,
  `params_schema` (a `type[BaseModel]`), `identifiers_schema` (a `type[BaseModel] | None`).
  The loader (`io/query_catalogue_yaml.py:244-250`) only ever reads schemas. There is
  **no** identifier-values key in YAML and **no** out-bound `CypherQuery` save path
  anywhere (only `GraphDefinition` has `save_yaml_file`). Identifier values have never
  been part of the wire format.

**Option A implementation contract — must NOT touch the serialization surface:**

- Bind identifier values as a **private instance attribute** (`PrivateAttr`, e.g.
  `_identifiers`), exactly as the typed path does — NOT as a new Pydantic field.
  A new public field would auto-appear in `model_dump()` and break the YAML round-trip.
  A `PrivateAttr` is invisible to `model_dump`/JSON-Schema, so the wire format is
  unchanged.
- Accept identifier values at construction time. Because `CypherQuery` is a Pydantic
  `BaseModel`, the binding runs in `model_post_init` (Pydantic v2): validate the raw
  identifiers against `self.identifiers_schema or NoIdentifiers` into `self._identifiers`,
  mirroring `CypherReadQuery.__init__`. The five serialized fields are untouched.
- `build(self, params: BaseModel) -> CypherQueryData`: validate `params` against
  `self.params_schema`, render the template with `self._identifiers`, return
  `CypherQueryData(rendered, params.model_dump(exclude_unset=True))`. NO `**kwargs`,
  NO `identifiers` parameter — identical to `CypherReadQuery.build`.

**Behaviour preservation:** For `NoIdentifiers` queries (every query that flows through
the executor today), `self._identifiers` is the empty `NoIdentifiers()` and render is a
no-op — identical execution behaviour. Queries needing identifiers now bind them at
construction (a strict improvement: previously they could not be executed at all
through the adapter path). The YAML round-trip is byte-for-byte unchanged.

> **An earlier draft claimed "the cypher template is already fully rendered when the
> CypherQuery is constructed." That was FALSE** — rendering happens in `build()`.
> Option A does NOT pre-render at construction either; it binds the identifier *values*
> at construction (like the typed path) and still renders in `build()`. The corrected
> reasoning rests on verified facts, not the false premise.

**Consequence for direct consumers (notebooks, tests):**
- `query.build(movie_id="M-001")` → `query.build(MyParams(movie_id="M-001"))`.
- `CypherQuery(query_id=..., cypher_template=..., params_schema=..., identifiers_schema=Foo)`
  then `query.build(params, identifiers=Foo(...))` → identifiers now move to
  construction: `CypherQuery(..., identifiers_schema=Foo, identifiers=Foo(...))` then
  `query.build(params)`. Updated in E60.4. (Loader-constructed queries are unaffected —
  they pass no identifier values and default to `NoIdentifiers()`.)

**Executor simplification:** `CypherExecutor._prepare_statement` calls `query.build(params)`
uniformly for all query types. `_query_shape` deleted. Adapters deleted.

**E39 compatibility:** E39 T5 code snippets still reference `query.Params`, `query.name`,
and reuse of the adapters. E60.5 updates the E39 epic text so E39 starts against the
aligned, adapter-free codebase. E39 must not start until E60 is complete.

---

### Q5 — E59 gates E60.1 (unchanged; E59 is done)

E59 landed. `cypher/validation.py` already has the unified `_extract_query_spec`
dispatcher. E60.2 only renames the attribute that dispatcher reads.

---

### Q6 — Rename the abstract base CLASSES to `…QueryModel` (added 2026-06-29)

**Decision:** rename the four abstract query bases so their names signal "subclass me,
do not instantiate me" — distinguishing them from `CypherQuery`, which IS instantiated.
Done as a **dedicated, last, behaviour-free task (E60.6)**, never sharing a commit with
the attribute rename (E60.1).

| Current | New | Reason |
|---|---|---|
| `ReadQuery` | `ReadQueryModel` | backend-AGNOSTIC base — `GqlAlchemyReadQuery` subclasses it too, so it must NOT carry a `Cypher` prefix |
| `WriteQuery` | `WriteQueryModel` | same |
| `CypherReadQuery` | `TypedCypherReadQueryModel` | Cypher-specific typed base |
| `CypherWriteQuery` | `TypedCypherWriteQueryModel` | Cypher-specific typed base |

**`CypherQuery` is NOT renamed** — the absence of the `Model` suffix is the signal that
it is the instantiable simple-path class.

**Naming correction:** the proposal was `TypedCypherRead/WriteQueryModel` for all four.
That is wrong for `ReadQuery`/`WriteQuery`: they are the backend-agnostic ABCs that the
gqlalchemy path also subclasses (verified: `GqlAlchemyReadQuery(ReadQuery[P, D])`,
`base_models.py:29`). Only the `cypher/` subclasses get the `TypedCypher` prefix.

**Why last + separate:** ~326 occurrences across ~20 source/test files + 5 notebooks.
This is a pure symbol rename with zero behaviour change. Folding it into E60.1 (itself a
~300-site attribute rename) would make both commits unreviewable and bisection useless.
Doing it now — after the attribute work, before E39 and the ORM path add subclasses — is
the cheapest moment; deferring it only grows the blast radius. The Haiku tail does the
longest-name-first whole-word replace to avoid partial-match collisions.

**Risk:** public symbol rename — accepted on the same grounds as the rest of E60
(pre-v0.1.0, internal consumers only). `tests/test_architecture.py` and mypy are the
safety net for a missed reference.

---

## Consequences


### Positive
- One vocabulary across all query types and all consumption layers.
- `_query_shape`, the three-comprehension `describe()`, and the adapters are deleted.
- **One construction shape** (`Query(identifiers=...)`) and **one build shape**
  (`build(params)`) across typed and simple paths (Option A).
- `**kwargs` removed from the query authoring/execution surface — explicit typed
  params end to end.
- E39 starts against a clean, adapter-free, aligned executor.
- Future ORM path authors against the aligned vocabulary from day one.

### Risks
- E60.1 (rename) and E60.3 (build unify + adapter delete) are the two larger commits.
  Mitigated by: uniform mechanical changes, mypy as safety net, staged task sequence,
  and Opus/Sonnet handling the judgement steps while Haiku does the mechanical tails.
- `CypherQuery.build` signature change + construction-time identifier binding is a
  public API change for direct consumers (notebooks/tests). Accepted: pre-v0.1.0, all
  callers internal, E60.4 updates them all.
- **Option A serialization hazard (mitigated):** the bound identifier values MUST be a
  `PrivateAttr`, never a Pydantic field, or `model_dump()`/YAML round-trip breaks.
  E60.3 acceptance gate includes a YAML round-trip test proving the wire format is
  unchanged.
- E39 T5 code must not be executed before E60 is complete (E60.5 updates the E39 text).

---

## Not in Scope

- Unifying query types into one hierarchy or union (the class RENAME in Q6/E60.6 keeps
  every type distinct — it changes names, not the hierarchy).
- Changing the YAML wire format (must stay byte-for-byte identical — gated by test).
- Async inspection.
- Any `ValidationIssue` message change.
