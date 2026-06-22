# Epic E46: Populate `PropertyProfile.observed_type_counts` — Per-Type Value Counts for Prevalence-Aware Type Conformance

> **Priority:** Medium (closes the ADR-015 B1 TODO; refines type-conformance from "a wrong type exists" to "how prevalent the wrong type is")
> **Phase:** v0.1.0
> **Blocked by:** none (independent; builds on E44 three-catalogue surface and E45 statistical model — both done)
> **Type:** Build (new per-type-count aggregation query across 3 backends + comparison-rule refinement) + parity tests
> **Decisions:** ADR-015 (§ "type match" — the B1 TODO this epic discharges), ADR-034 (E45 statistical model: `observed_type_counts`, `value_distribution`, comparison matrix), ADR-033 (E44 three-way Neo4j strategy + three-catalogue surface), ADR-009 (inspector contract, backend parity, count-less shapes), ADR-008 (identifier safety)
> **Rubric (every task judged against this):** strongly-typed · SOLID · readability over cleverness · backend-scoped (no vendor concept leaks into `graph_profile/`) · **bounded** (a per-type scan must not explode on UID / free-text columns) · truncation is explicit, never silent · backend parity discipline (ADR-009) · `None`/empty when a backend cannot supply counts (never invent) · each task ends green with guardrails run

---

## Why This Epic Exists

`PropertyProfile.observed_type_counts: dict[str, int]` exists (`graph_profile/models.py:121`),
is fully unit-tested (default / populate / serialise — `tests/graph_profile/test_models.py:91-120`),
and is the **addressed place** ADR-015 designates to hold the observed half of the
**type-match rule** (ADR-015 §162-166). But it is **never populated**: two identical
TODOs sit in `backends/neo4j/inspector.py:285` and `:332`, and E44 listed it explicitly
**out of scope** ("Per-type value counts (`observed_type_counts`) — still the ADR-015 B1
TODO; neither APOC nor `db.schema.*` returns per-type counts. Untouched." —
`E44_...md:241`).

The blocker is **data-source, not plumbing**: every property-type source the inspectors
read today yields only *distinct type names*, never a `{type → count}` mapping:

- Neo4j APOC `apoc.meta.nodeTypeProperties` → `propertyTypes` is a **list of distinct
  type names** (`backends/neo4j/queries.py:199,236`).
- Neo4j `db.schema.*` (SCHEMA strategy) → same: distinct names only.
- Neo4j pure-Cypher (CYPHER strategy) → `observed_types = []`.

You cannot derive `{'Long': 95, 'Float': 5}` from `['Long', 'Float']`. Populating the
field requires a **new aggregation** that groups each property's values by their
runtime storage type and counts each group — a real, bounded value scan, distinct from
the metadata-only reads.

### What it buys us

Today `PropertyTypeMismatchRule` (`comparison/rules.py:322`) reasons over
`observed_types` (distinct names): it can flag *that* an off-type value exists, but not
*how prevalent* it is. With counts, the rule can distinguish **systematic type drift**
(e.g. 60% wrong) from **a handful of dirty rows** (e.g. 0.1% wrong) and set severity /
message accordingly — the prevalence-aware conformance ADR-015 §162-166 envisaged.

---

## Open Questions (resolve in E46.0 → ADR before building)

These are **decisions, not yet made**. E46.0 produces an ADR; do not write production
code until it is recorded.

1. **Counting cost & opt-in.** A per-type count is a full value scan per property —
   materially heavier than today's metadata reads. Is it: (a) always-on, (b) gated by
   the existing E45 `value_counts_top_n` inspection parameter, or (c) a new dedicated
   flag? **Working hypothesis:** reuse the E45 bounded-sampling parameter — type counts
   are an aggregate *over the same scan* that already produces `value_distribution`, so
   they should ride the same opt-in and the same bound, not add a second knob.

2. **Relationship to `value_distribution.histogram`.** E45 already added a bounded
   value histogram (`value → count`) and ADR-034 §3/§4 says the type breakdown is
   "preserved alongside … aligned into the distribution model". Decide whether
   `observed_type_counts` is (a) **derived** from the same scan that builds
   `value_distribution` (single scan, two aggregations), or (b) an independent
   aggregation. **Working hypothesis:** single scan, two aggregations — type count is
   `value → type(value) → count`, cheaper to fold into the existing pass than to
   re-scan. Confirm the two never disagree (the per-type totals must reconcile with the
   histogram's covered count, accounting for truncation).

3. **What "type" means per backend.** Neo4j storage types (`Long`, `Double`, `String`)
   vs. Memgraph vs. the NetworkX reference's Python types. The map already exists for
   comparison (`engine._DB_TYPE_MAP`, `db_type_to_python`). Confirm the count keys use
   the **backend-reported type-name strings** (same vocabulary as `observed_types`), so
   the comparison rule's existing `db_type_to_python` path applies unchanged.

4. **Truncation semantics.** When a property exceeds the bound, do type counts stay
   exact (there are few distinct *types* even when there are many distinct *values*) or
   are they also truncated? **Working hypothesis:** type counts stay **exact** — the
   distinct-*type* cardinality is tiny and bounded by nature, even when distinct-*value*
   cardinality is huge; only the *value* histogram truncates.

---

## Decisions Already Made (do not re-litigate)

- The field, its shape (`dict[str, int]`), default (`{}`), and serialisation are
  **fixed** by ADR-034 / E45 — this epic only **populates** it (`models.py:121`).
- `observed_type_counts` is the **observed half of the type-match rule** (ADR-015
  §162-166) — its consumer is comparison, not a new output surface.
- Empty `{}` is the honest value when a backend / strategy cannot supply counts
  (mirrors `observed_types = []` for CYPHER strategy). **Never invent counts.**
- Backend-scoped: no vendor concept enters `graph_profile/`. The vendor-free layer only
  sees the populated model field (ADR-009 D1).

---

## Existing Code to Reuse

| Need | Reuse | Location |
|------|-------|----------|
| The target field (shape, default, serialise — done) | `PropertyProfile.observed_type_counts` | `graph_profile/models.py:121` |
| Bounded sampling parameter + truncation precedent (E45) | `value_distribution`, `BoundedDistribution`, `value_counts_top_n` | `graph_profile/models.py`, the 3 inspectors |
| The two TODO sites to fill | `_build_node_profile`, `_build_rel_profile` | `backends/neo4j/inspector.py:285,:332` |
| Three Neo4j catalogue factories (register the new query in **all three**) | `build_apoc_catalogue`, `build_cypher_catalogue`, `build_schema_catalogue` | `backends/neo4j/queries.py` |
| Row currency / bulk-query materialiser precedent | `NodePropertyRow`, `coerce_types`, Memgraph bulk queries | `backends/neo4j/queries.py`, `backends/memgraph/queries.py`, `graph_profile/queries/shared.py` |
| Type-name → Python mapping (comparison side) | `_DB_TYPE_MAP`, `db_type_to_python` | `comparison/engine.py:30,53` |
| The rule to refine | `PropertyTypeMismatchRule` | `comparison/rules.py:322` |
| Mock-driver test harness | existing inspector mock patterns | `tests/backends/neo4j/test_inspector*.py` |
| NetworkX reference inspector (parity baseline) | reference inspector | `graph_profile/` reference backend |

---

## Per-Task Guardrails (apply to EVERY task unless stated)

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

Live-DB tests are opt-in (`--neo4j` / `--memgraph`); default-suite tests use mocked
drivers / in-memory graphs. The feature is backend-scoped —
`tests/test_architecture.py` must stay green (no vendor import leaks into vendor-free
layers).

---

## Tasks (execute in order; each ends green)

### E46.0 — ADR: per-type-count source, cost/opt-in, and `value_distribution` relationship

> **Model: Opus.** Decision-only. Resolves the four Open Questions above. No production code.

**Goal:** an ADR in `.agentic/decisions/` records: (1) that type counts ride the E45
bounded-sampling opt-in (or the chosen alternative), (2) single-scan-two-aggregations
vs. independent aggregation, (3) count keys use backend type-name strings, (4) type
counts stay exact under value-histogram truncation. Records the rejected alternatives.

**Operation:**
1. Write the ADR resolving Open Questions 1–4 with rationale.
2. State the reconciliation invariant: `sum(observed_type_counts.values())` relates to
   the histogram's covered count in a defined, tested way (accounting for truncation).
3. Cross-link from CONTEXT.md if it changes a documented boundary; supersede the
   ADR-015 B1 TODO note and the E44 out-of-scope line by reference.

**Care / risks:** do **not** add a second sampling knob if the E45 parameter suffices —
re-litigating the bound is out of scope. Keep the field shape frozen (ADR-034).

---

### E46.1 — Per-type-count aggregation query (Neo4j) + register in all three catalogues

> **Model: Opus.** The load-bearing correctness core: the bounded `value → type → count` aggregation, its materialiser, and registration parity across the three E44 catalogues. Gets the data shape right so the inspector wiring is mechanical.

**Goal:** a query (or extension of the existing value-distribution scan, per E46.0)
exposes `{type-name: count}` per property, registered identically in
`build_apoc_catalogue`, `build_cypher_catalogue`, and `build_schema_catalogue`.

**Operation** — in `src/orthograph/backends/neo4j/queries.py`:
1. Per E46.0's decision, either extend the E45 value-scan to also emit per-type counts,
   or add a dedicated bounded aggregation (group each property's values by
   `apoc.meta.cypher.type(v)` / equivalent runtime-type expression, `count()` per
   group). Identifiers via `<<placeholder>>` (ADR-008) — `label` / `rel_type` are the
   only interpolated identifiers; values are not interpolated.
2. Materialise into the row currency carrying `property_name` + `type_counts:
   dict[str, int]`, type names via `coerce_types` vocabulary (parity with
   `observed_types`).
3. Register in **all three** catalogue factories (the E44 three-catalogue obligation).

**Tests (TDD — write first)** — `tests/backends/neo4j/test_inspector_queries.py`:
- `build()` emits the expected aggregation text with correctly-placed identifier slots,
  no value interpolation.
- `materialize()` maps a raw grouped row to `{type-name: count}` with clean type names.
- all three `build_*_catalogue()` factories register the new query (membership parity
  test, mirroring the existing factory parity tests).

**Care / risks:** **bounded** — a per-type aggregation over a UID / free-text column
must not enumerate distinct values; group by *type*, not value (few distinct types).
CYPHER-only deployments without the runtime-type function fall back to `{}` (never
invent). Keep the count-less honesty: a property the scan cannot type yields `{}`.

---

### E46.2 — Wire population into the Neo4j inspector (the two TODO sites)

> **Model: Sonnet.** Mechanical once E46.1 lands: thread the per-type-count row through the two profile builders and delete the two TODO comments.

**Goal:** `_build_node_profile` and `_build_rel_profile` populate
`PropertyProfile(observed_type_counts=...)`; the TODOs at `inspector.py:285,:332`
are removed.

**Operation** — in `src/orthograph/backends/neo4j/inspector.py`:
1. Fetch / merge the per-type counts alongside the existing `observed_types` merge
   (same `(label/rel_type, property_name)` keying used for the SCHEMA type map).
2. Pass `observed_type_counts=` into both `PropertyProfile(...)` constructions; delete
   both TODO comments.
3. When the strategy / opt-in yields no counts, pass `{}` (the model default — explicit
   for readability).

**Tests (TDD — write first)** — `tests/backends/neo4j/test_inspector.py`:
- mocked driver returning grouped type rows → profile's `observed_type_counts` matches.
- strategy / opt-in with no counts → `observed_type_counts == {}`.
- counts reconcile with `observed_types` keys (every counted type appears in
  `observed_types` and vice versa where both are populated).

**Care / risks:** do not regress the existing `observed_types` / count-completeness
behaviour. The merge keying must match the established SCHEMA-map pattern exactly.

---

### E46.3 — Memgraph + NetworkX-reference parity

> **Model: Opus.** Backend parity is a hard contract (ADR-009). The reference backend is the parity baseline; Memgraph must match shape.

**Goal:** the NetworkX reference inspector and the Memgraph inspector populate
`observed_type_counts` with the same semantics, so the field is backend-consistent.

**Operation:**
1. NetworkX reference: count Python-type occurrences per property (the reference is the
   ground truth the others are judged against).
2. Memgraph: implement via its `schema.*` / aggregation surface; `{}` where unavailable.
3. Ensure the type-name vocabulary aligns with `observed_types` per backend.

**Tests (TDD — write first)** — reference + Memgraph inspector test files:
- same logical graph → equivalent `observed_type_counts` across backends (parity test).
- mixed-type property (e.g. mostly int, a few float) → correct per-type split.
- backend without counts → `{}`.

**Care / risks:** parity is judged on **semantics**, not identical type-name strings if
a backend's vocabulary differs — document any backend-specific name mapping. Keep
bounded.

---

### E46.4 — Refine `PropertyTypeMismatchRule` to use prevalence

> **Model: Opus.** The payoff: the comparison rule moves from "a wrong type exists" to "how prevalent", with correct severity discipline. Must not regress when counts are absent.

**Goal:** `PropertyTypeMismatchRule` consults `observed_type_counts` (when present) to
reason about prevalence — distinguishing systematic drift from a few dirty rows — and
falls back to the current `observed_types`-only behaviour when counts are `{}`.

**Operation** — in `src/orthograph/comparison/rules.py`:
1. When `observed_type_counts` is populated, compute the off-type share and include it
   in the issue message (and, per E46.0/ADR, optionally modulate severity — e.g. a
   negligible share is a WARNING, a systematic share an ERROR). Keep the existing
   `db_type_to_python` mapping path.
2. When `observed_type_counts == {}`, behaviour is **identical to today** (no
   regression — the field is additive).

**Tests (TDD — write first)** — `tests/comparison/`:
- populated counts, systematic off-type → ERROR with prevalence in message.
- populated counts, negligible off-type → per-ADR severity (e.g. WARNING).
- empty counts → byte-for-byte the current behaviour (regression guard).

**Care / risks:** do not change the issue `code` (`PROPERTY_TYPE_MISMATCH`) without an
ADR — downstream consumers key on it. The empty-counts path is a hard regression guard.

---

### E46.5 — Docs + close the TODO trail

> **Model: Sonnet.** Documentation and bookkeeping; no behaviour change.

**Goal:** the documentation reflects that `observed_type_counts` is now populated, and
every dangling reference to the old "B1 TODO" points at this epic's outcome.

**Operation:**
1. Update `notes/neo4j_property_type_detection.md` (the "Per-type counts — out of
   scope" caveat) and the ADR-015 §162-166 note to reflect the delivered state.
2. Update `models.py:121` docstring if the "Empty when the backend only yields distinct
   type names" wording needs a pointer to the opt-in.
3. Confirm the two TODO comments are gone (E46.2) and no other source references the
   unpopulated field.

**Care / risks:** documentation-only; do not touch production behaviour here.

---

## Coordination

- **E45 (done):** this epic rides E45's bounded-sampling infrastructure
  (`value_distribution`, `value_counts_top_n`). If E46.0 decides on single-scan-two-
  aggregations, E46.1 extends the E45 value-scan rather than adding a parallel scan.
- **E44 (done):** the three-catalogue surface (`build_apoc/cypher/schema_catalogue`) is
  the registration obligation — the new query must land in **all three** (E46.1).
- **E18 (Validation Correctness, active):** the refined type-match rule (E46.4) is a
  validation-correctness improvement; coordinate edits to `comparison/rules.py` if E18
  is in flight on the same rule.

---

## Out of Scope

- Changing `PropertyProfile.observed_type_counts`'s shape, default, or serialisation
  (frozen by ADR-034 / E45).
- Adding a second sampling/bound knob if the E45 parameter suffices (E46.0 decides).
- Property *value* constraints (min/max/regex/enum) — separately deferred (see
  planning Deferred table).
- Promoting the per-type-count concept into the vendor-free `graph_profile/` layer
  beyond the existing model field (ADR-009 D1).
- Changing the `PROPERTY_TYPE_MISMATCH` issue code (would need its own ADR).
