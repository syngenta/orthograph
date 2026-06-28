# Epic E60: Query Shape Alignment — One Vocabulary Across Typed / Cypher / ORM Paths

> **Priority:** Medium
> **Phase:** post-v0.1.0 — architecture / decoupling
> **Type:** **Design + public-surface + serialization-adjacent change.** This is
>   NOT the behaviour-preserving distillation E56 is limited to. It changes
>   public class attribute names on the typed query bases. Requires an ADR (this
>   file records the ratified direction; the ADR formalises the migration and
>   deprecation policy) **before** the rename lands.
> **Depends on:** E56 (distillation — the W4 prologue/seam cleanup that made the
>   divergence visible and isolated it to one place), E59 (query validation
>   public API — touches the same `validate_*` surface; sequence so the two do
>   not fight over `queries.py`).
> **Blocks:** a future dedicated ORM (e.g. SQLAlchemy / gqlalchemy) query path —
>   see ADR-017 backends, E14, E52. The ORM path should be authored against the
>   *aligned* vocabulary, not the current divergent one.
> **Origin:** E56 Workstream W4 re-analysis (2026-06-28). The W4 task E56.15
>   originally said "route the executor through the adapters and delete the
>   `getattr` shim." That instruction was **rejected** and rewritten — see the
>   "Latent bug in the original E56.15" section below — because it (a) contained
>   a correctness trap and (b) would have *deepened* the union/abstraction
>   coupling this epic exists to remove. W4 instead did only the reversible
>   prologue de-duplication and isolated the divergence into a single named
>   function (`CypherExecutor._query_shape`) that points here.

---

## Why This Epic Exists

Orthograph has two query authoring shapes that describe the **same concepts**
under **different attribute names**. The divergence is *accidental* — it was
never a deliberate contract — and it forces a reconciliation step at every place
that consumes a query generically.

### The divergence (the core problem)

| Concept | Typed path (`ReadQuery` / `WriteQuery` / `CypherReadQuery` / `CypherWriteQuery`) | Simple path (`CypherQuery`) |
|---------|-----------------------------------------------------------------------------------|------------------------------|
| params model | `Params` (ClassVar) | `params_schema` (Pydantic field) |
| identifiers model | `Identifiers` (ClassVar) | `identifiers_schema` (Pydantic field) |
| identity | `name` (ClassVar) | `query_id` (field) |
| Cypher text | `cypher_template` (ClassVar) | `cypher_template` (field) — **already identical** ✓ |
| build signature | `build(params: P)` | `build(**kwargs)` / `build(identifiers=..., **kwargs)` |

Only `cypher_template` already agrees. Everything else differs in name while
meaning the same thing.

### Where the divergence is paid for (the reconciliation sites)

Because the two shapes do not share names, generic consumers must bridge them.
As of the E56 W4 cleanup the bridging is **isolated**, but it still exists at
these sites:

1. **`cypher/query_execution.py` — `CypherExecutor._query_shape`** (post-W4 the
   *single* executor reconciliation point). Reads
   `getattr(query, "params_schema", None) or query.Params` and
   `getattr(query, "query_id", None) or query.name`. This is the seam to delete.
2. **`query/catalogue.py` — `QueryCatalogue.describe()`** emits a unified
   `QueryDescription(name=..., params_schema=...)` by reading `q.Params`/`q.name`
   for typed queries and `q.params_schema`/`q.query_id` for `CypherQuery` (three
   separate comprehensions, lines ~136–170).
3. **`cypher/validation.py`** — `validate_typed_cypher_query` reads
   `Params`/`Identifiers`/`Output` off the typed class; `_validate_simple_cypher_query`
   reads `params_schema`/`identifiers_schema`/`query_id` off `CypherQuery`. Two
   near-mirror extraction blocks feeding the same `validate_cypher_spec`.
4. **`io/query_catalogue_yaml.py`** — the YAML loader already accepts
   `query_id` (with legacy `query_name`/`name` aliases) and `params_schema` as
   the **wire format**. This is the constraint that makes `query_id`/`params_schema`
   the natural canonical names (see Ratified Direction).
5. **`cypher/query_execution.py` — `CypherQueryReadAdapter` / `CypherQueryWriteAdapter`**
   wrap a `CypherQuery` and re-expose `params_schema`/`query_id` plus translate
   `build(**kwargs)` → `build(params)`. These exist purely because of the shape
   gap; once the shapes align, the adapters' *name-bridging* role disappears and
   only the `build()` call-shape translation (kwargs vs single model) may remain.

### Why this is real coupling, not cosmetics

The product direction is **separate, parallel query paths** — typed, plain
Cypher, and (future) ORM — that do **not** collapse into one union type or one
abstraction hierarchy. The current divergence pushes in the opposite direction:
every generic consumer grows a `query: ReadQuery | WriteQuery | CypherQuery`
union and an `isinstance`/`getattr` reconciliation. That union-plus-bridge
pattern is the strong coupling we want to dissolve. Aligning the *attribute
names* lets each path stay its own type while a generic consumer reads **one**
attribute set — removing the reconciliation without unifying the types.

---

## Ratified Direction (decided 2026-06-28; the ADR formalises it)

**The typed path adopts the Cypher names.** `ReadQuery` / `WriteQuery` (and the
`CypherReadQuery` / `CypherWriteQuery` subclasses) move from
`Params` / `Identifiers` / `name` toward `params_schema` / `identifiers_schema`
/ `query_id`.

**Why this direction and not the reverse:**

- `CypherQuery` is **YAML-serialised** with `query_id` and `params_schema` as the
  on-the-wire field names (`io/query_catalogue_yaml.py`). Renaming *those* is a
  public serialization-format break with legacy aliases already in the loader.
  Renaming the typed-class ClassVars is a code/public-attribute change with no
  wire-format impact.
- The simple `CypherQuery` shape is the one the product team finds more readable
  and wants the others to "resemble" (stated requirement).
- The future ORM path is greenfield — it should be authored against the aligned
  vocabulary from day one.

**Not unifying the types.** This epic renames attributes so the three paths
*share a vocabulary*; it does **not** merge `ReadQuery`/`WriteQuery`/`CypherQuery`
into one class or one union. Each path keeps its own type and its own contract
(typed = class-definition-time validation + statically-typed results; simple =
runtime validation + raw `list[dict]`; ORM = its own).

---

## Latent Bug in the Original E56.15 (recorded so it is not reintroduced)

The original E56.15 text instructed: *"route the executor through the existing
adapters and delete the redundant `getattr ... or ...` fallback."* This is
**wrong** and was not actioned:

- The adapters (`CypherQueryReadAdapter`/`CypherQueryWriteAdapter`) **re-expose
  the simple names** (`self.params_schema = query.params_schema`,
  `self.query_id = query.query_id`). They do **not** translate to the typed
  `Params`/`name`.
- Therefore the executor `getattr(query, "params_schema", None) or query.Params`
  shim and the adapters are **coupled, not competing**: the shim is exactly what
  reads the names the adapter exposes. Deleting the shim while routing through
  the adapters would break the `CypherQuery` execution path (the adapter's
  `params_schema`/`query_id` would no longer be read).
- Routing everything through adapters would also *add* a permanent bridging
  layer — the opposite of this epic's goal.

W4 therefore did the safe half only: collapsed the duplicated read/write
prologue into `CypherExecutor._prepare_statement` and isolated the divergence
into `CypherExecutor._query_shape`, whose docstring points here. The real fix is
the rename below, which lets `_query_shape` be deleted outright.

---

## Open Questions (decide in the ADR before any code)

### Q1 — Rename vs alias-and-deprecate
Hard rename `Params` → `params_schema` etc. (breaking for every typed subclass
in `backends/*`, `graph_profile/*`, generated CRUD, and downstream consumers),
or introduce the new names with the old as deprecated aliases (property shims +
`DeprecationWarning`) for a transition window? Count the subclass call sites
first — `CypherReadQuery`/`CypherWriteQuery` subclasses across
`backends/neo4j`, `backends/memgraph`, `graph_profile/queries`, and
`cypher/generator.py`.

### Q2 — `name`/`query_id` and the catalogue
`QueryCatalogue` keys, `register_read`/`register_write`/`register_cypher_query`,
and `QueryDescription.name` all read the identity attr. Does `QueryDescription`
keep `name` (consumer-facing) while the *source* attr becomes `query_id`, or does
it also rename? Decide the public `describe()` surface.

### Q3 — The `__init_subclass__` generic auto-population
`base_models.py::_auto_populate_classvar` sets `Params`/`Output` from the
`ReadQuery[P, D]` generic args. After the rename it must set `params_schema`.
Confirm the generic-arg → attr mapping and the conflict-detection error message
are updated coherently.

### Q4 — Adapter fate
Once names align, the adapters' name-bridging role is gone. Does the
`build(**kwargs)` ↔ `build(params)` call-shape difference still justify keeping
the adapters, or can `CypherQuery.build` grow a `build(params: BaseModel)`
overload so the executor speaks one `build` contract and the adapters are
deleted? (`CypherQuery.build` currently takes `**kwargs` + `identifiers=`.)

### Q5 — Migration ordering vs E59
E59 reworks the public `validate_*` surface in `queries.py`; this epic renames
attributes those validators read. Sequence so one lands fully (suite green)
before the other starts — same-file/same-surface contention.

---

## What W4 Already Did to Prepare (E56, 2026-06-28)

- `CypherExecutor` read/write prologue de-duplicated into
  `_prepare_statement` (one place: resolve shape → validate → build → parse).
- The shape divergence isolated into **one** method,
  `CypherExecutor._query_shape`, with a docstring naming the two shapes,
  declaring the divergence accidental, and pointing at this epic + ADR-042. When
  the rename lands, `_query_shape` collapses to a direct attribute read and is
  deleted.
- No public attribute renamed, no adapter touched, no test edited — fully
  reversible, nothing for this epic to undo.

---

## Proposed Tasks (after ADR)

#### E60.0 — ADR: decide Q1–Q5 + count subclass blast radius — **Opus**
Record the rename direction (ratified: typed adopts Cypher names), the
alias-vs-hard-rename decision, the catalogue/`describe()` surface, the
`__init_subclass__` mapping, the adapter fate, and the E59 sequencing. Enumerate
every typed-query subclass that declares `Params`/`name`/`Identifiers`. No code.

#### E60.1 — Rename the typed base attributes (per ADR) — **Opus**
`query/base_models.py` + `cypher/base_models.py`: introduce
`params_schema`/`identifiers_schema`/`query_id` on `ReadQuery`/`WriteQuery`/
`CypherReadQuery`/`CypherWriteQuery`, update `__init_subclass__` auto-population,
and (per ADR) add deprecated aliases or migrate subclasses. Suite + mypy green.

#### E60.2 — Collapse the reconciliation sites — **Sonnet**
Delete `CypherExecutor._query_shape` (direct attribute read); simplify
`QueryCatalogue.describe()` to one comprehension; merge the two extraction
blocks in `cypher/validation.py`. Each deletion is gated on E60.1.

#### E60.3 — Resolve the adapters (per Q4) — **Sonnet/Opus**
Either delete the adapters (if `CypherQuery.build` gains a single-model overload)
or document their reduced role. Update `execution.py __all__` + notebooks
accordingly.

#### E60.4 — Surface tests + notebooks + docs — **Haiku**
Update any test/notebook that references the renamed attributes; update the
`queries.py` / `execution.py` module docstrings to describe the aligned shape.

---

## Success Criteria

- [ ] All three query paths expose `params_schema` / `identifiers_schema` /
      `query_id` (typed adopts the Cypher names); `cypher_template` already
      shared.
- [ ] No generic consumer performs `getattr(... ) or ...` or `isinstance`
      name-reconciliation: `_query_shape` deleted, `describe()` one comprehension,
      validation one extraction.
- [ ] The three query *types* remain distinct — no union collapse, no shared
      abstraction hierarchy introduced.
- [ ] `python -m pytest tests -q` (incl. notebooks) green; `python -m mypy
      src/orthograph` clean; `tests/test_architecture.py` green.
- [ ] If aliases were used: `DeprecationWarning` fires; no consumer silently
      broken.

---

## Out of Scope

- Unifying `ReadQuery`/`WriteQuery`/`CypherQuery` into one type or one union
  (explicitly rejected — the paths stay parallel).
- The validation public-API split (that is E59).
- Changing the YAML wire format (`query_id`/`params_schema` already canonical
  there).
- Any `ValidationIssue` code/severity/message or rendered-output change.
