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

## Open Questions — RESOLVED by ADR-035 (E46.0 done)

All four resolved in **`.agentic/decisions/035-observed-type-counts-population.md`**.
Summary below; the ADR is authoritative.

> **Premise correction (the reframe E46.0 surfaced).** The epic originally assumed E46
> *rides* an existing E45 value scan. That scan exists **only in the NetworkX reference
> inspector**. Neo4j and Memgraph populate **neither** `value_distribution` **nor**
> `observed_type_counts` today (no value-scan query in any catalogue). **E46 therefore
> introduces the first value-touching scan on the DB backends**; type counts and the
> value histogram are both products of that one new scan.

1. **Counting cost & opt-in.** RESOLVED: **single knob** — extend `value_counts_top_n`
   to `Neo4jInspector` and `MemgraphInspector` (same semantics as NetworkX). Set ⇒ one
   opt-in value-scan transaction yielding *both* aggregations; `None`/`0` ⇒ no
   value-touching scan ⇒ `observed_type_counts == {}` and `value_distribution is None`.
   No second knob.

2. **Relationship to `value_distribution.histogram`.** RESOLVED: **one logical scan, two
   aggregations, run inside one read transaction (snapshot)**. Type counts =
   `GROUP BY runtime-type` (few rows, exact, never enumerates distinct values); histogram
   = `GROUP BY value LIMIT top_n` (+ `other_count`). **Reconciliation invariant:**
   `observed_type_counts == {}` **OR**
   `sum(observed_type_counts.values()) == value_distribution.count == present_count` —
   hard exact-equality where counts are present (shared snapshot on live DB; exact in
   reference tests); `{}` is the honest escape.

3. **What "type" means per backend.** RESOLVED: count keys reuse each backend's existing
   `observed_types` vocabulary (Neo4j `coerce_types`; NetworkX `type(v).__name__`).
   `_DB_TYPE_MAP` already carries both, so `db_type_to_python` is **untouched**.
   Consistency: `set(observed_type_counts) ⊆ set(observed_types)`. Parity on semantics
   (ADR-009).

4. **Truncation semantics.** RESOLVED: type counts stay **exact** (group by *type*, not
   value); only the *value* histogram truncates. Availability: APOC strategy uses
   `apoc.meta.cypher.type(v)`; SCHEMA may use APOC's type fn if present else `{}`;
   pure-CYPHER ⇒ `{}` (histogram may still populate); Memgraph uses `valueType` if
   available else `{}`. Never invent.

---

## Decisions Already Made (do not re-litigate)

- The field, its shape (`dict[str, int]`), default (`{}`), and serialisation are
  **fixed** by ADR-034 / E45 — this epic only **populates** it (`models.py:121`).
- **`value_distribution` is NOT yet populated on the DB backends** (only NetworkX). E46
  introduces the bounded DB value scan, so it populates **both** `value_distribution`
  and `observed_type_counts` on Neo4j/Memgraph (ADR-035). This is in scope, not a
  separate epic.
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

### Live e2e tests (Neo4j instance available)

E46 introduces a **real value scan** whose correctness can only be fully proven against a
live DB (the type-count aggregation, the `apoc.meta.cypher.type(v)` availability path, and
the single-read-transaction reconciliation are all runtime behaviours mocks can only
approximate). Add `@pytest.mark.neo4j` e2e tests to the existing harness
`tests/backends/neo4j/test_inspector_e2e.py` (uses `neo4j_driver` + `neo4j_clean`
fixtures and a `_seed` helper). Run with:

```
pwsh> pytest --neo4j --neo4j-password <pw> tests/backends/neo4j/test_inspector_e2e.py -q
```

**E2E coverage to add (E46.1/E46.2):**
- Seed a mixed-type property (e.g. a `Person.born` mostly `int` with a couple of `String`
  rows) → `observed_type_counts == {'Long': N, 'String': M}` with the exact split.
- **Reconciliation on a live instance:**
  `sum(observed_type_counts.values()) == value_distribution.count == present_count`.
- **Truncation:** seed a high-cardinality UID-like property exceeding `value_counts_top_n`
  → histogram `sample_complete=False` with `other_count`, while `observed_type_counts`
  stays **exact** (single `{'String': total}` entry, not truncated).
- **APOC vs CYPHER strategy:** APOC strategy yields type counts; explicit
  `strategy=CYPHER` yields `observed_type_counts == {}` (no runtime-type fn) while the
  histogram may still populate.
- **Bounded-cost smoke:** the type-count query returns ≤ (distinct-types) rows even on a
  property with many distinct values (assert the client never receives a per-value row set
  for the type aggregation).

Keep e2e tests opt-in and idempotent (the `neo4j_clean` fixture wipes before/after).
Memgraph e2e (E46.3) is opt-in via `--memgraph` if/when an instance is available; mocked
parity tests remain the default-suite guard.

---

## Tasks (execute in order; each ends green)

### E46.0 — ADR: per-type-count source, cost/opt-in, and `value_distribution` relationship — DONE

> **Model: Opus.** Decision-only. Resolved the four Open Questions above. No production code.

**Outcome:** `.agentic/decisions/035-observed-type-counts-population.md` (Accepted).
Resolves Q1–Q4, states the reconciliation invariant, and corrects the false premise that
E46 rides an existing DB value scan (none exists — E46 introduces it). Rejected
alternatives recorded.

---

### E46.1 — Bounded value-scan transaction (Neo4j): histogram + type counts + register in all three catalogues

> **Model: Opus.** The load-bearing correctness core: the **new** bounded value-scan
> transaction (introducing `value_distribution` AND `observed_type_counts` on Neo4j),
> its two aggregations, materialisers, and registration parity across the three E44
> catalogues. Gets the data shape right so the inspector wiring is mechanical.

**Goal:** a value-scan transaction (per ADR-035) exposes, per property: a bounded
`{value: count}` histogram **and** an exact `{type-name: count}` mapping, registered
identically in `build_apoc_catalogue`, `build_cypher_catalogue`, and
`build_schema_catalogue`. The two aggregations run in **one read transaction** so they
reconcile (ADR-035 §2).

**Operation** — in `src/orthograph/backends/neo4j/queries.py`:
1. Add **two** bounded aggregating queries (ADR-035 §2):
   - type counts: group each property's values by `apoc.meta.cypher.type(v)` (APOC) /
     equivalent, `count()` per group — **group by type, never by value** (bounded, exact).
   - value histogram: group by value, `LIMIT top_n`, remainder → `other_count`.
   Identifiers (`label`/`rel_type`) via `<<placeholder>>` (ADR-008); **values never
   interpolated**.
2. Materialise into row currency carrying `property_name` + `type_counts: dict[str, int]`
   (+ the histogram fields), type names via `coerce_types` vocabulary (parity with
   `observed_types`).
3. Register in **all three** catalogue factories (the E44 three-catalogue obligation).

**Tests (TDD — write first)** — `tests/backends/neo4j/test_inspector_queries.py`:
- `build()` emits the expected aggregation text with correctly-placed identifier slots,
  no value interpolation, `GROUP BY type` (not value) for the type-count query.
- `materialize()` maps a raw grouped row to `{type-name: count}` with clean type names.
- all three `build_*_catalogue()` factories register the new queries (membership parity
  test, mirroring the existing factory parity tests).

**Care / risks:** **bounded** — the type-count aggregation groups by *type*, returning a
handful of rows even on a UID / free-text column; the histogram is the only truncating
part. CYPHER-only deployments without a runtime-type function fall back to `{}` for type
counts (histogram may still populate — ADR-035 §5). Keep the count-less honesty.

---

### E46.2 — Wire population into the Neo4j inspector (the two TODO sites)

> **Model: Sonnet.** Mechanical once E46.1 lands: thread the per-type-count row through the two profile builders and delete the two TODO comments.

**Goal:** `_build_node_profile` and `_build_rel_profile` populate
`PropertyProfile(value_distribution=..., observed_type_counts=...)`; the TODOs at
`inspector.py:285,:332` are removed. Add `value_counts_top_n` to `Neo4jInspector.__init__`
(ADR-035 §1) gating the value-scan transaction.

**Operation** — in `src/orthograph/backends/neo4j/inspector.py`:
1. Add `value_counts_top_n: int | None` to `__init__` (same default/semantics as
   `NetworkxInspector`). When set, run the E46.1 value-scan transaction; when `None`/`0`,
   skip it entirely (both fields stay `{}`/`None`).
2. Fetch / merge the per-type counts **and** the histogram alongside the existing
   `observed_types` merge (same `(label/rel_type, property_name)` keying as the SCHEMA
   type map). The value-scan reads run in **one read transaction** with the `present_count`
   source so the reconciliation invariant holds (ADR-035 §2).
3. Pass `value_distribution=` and `observed_type_counts=` into both `PropertyProfile(...)`
   constructions; delete both TODO comments.
4. When the strategy / opt-in yields no counts, pass `{}` / `None` (explicit for
   readability).

**Tests (TDD — write first)** — `tests/backends/neo4j/test_inspector.py`:
- mocked driver returning grouped type rows → profile's `observed_type_counts` matches.
- strategy / opt-in with no counts → `observed_type_counts == {}` (and
  `value_distribution is None` when the scan was skipped).
- reconciliation: where counts are populated,
  `sum(observed_type_counts.values()) == value_distribution.count == present_count`.
- counts reconcile with `observed_types` keys (`set(observed_type_counts) ⊆ set(observed_types)`).

**Care / risks:** do not regress the existing `observed_types` / count-completeness
behaviour. The merge keying must match the established SCHEMA-map pattern exactly.

#### Known deviations from ADR-035 (recorded, not fixed — see E46.2 status below)

**Reconciliation invariant not enforced by a shared transaction (ADR-035 §2).**
ADR-035 §2 states: *"the three feeding reads (`present_count`, type counts, histogram)
run inside one read transaction"* so the snapshot is consistent. The shipped
implementation uses three separate `driver.execute_query(...)` auto-commit transactions
(one for the properties scan that supplies `present_count`, one for the type-count
aggregation, one for the histogram). On a quiescent database — and in all mocked and
reference tests — the invariant holds because nothing changes between calls. Under
concurrent writes on a live DB the three reads can observe different snapshots:
`sum(observed_type_counts.values())`, `value_distribution.count`, and `present_count`
may diverge and break the hard exact-equality the ADR mandates.

*Why not fixed in E46.2:* threading a single read transaction through the inspector's
`execute_query` surface requires exposing or propagating a transaction handle, which the
current `CypherInspector` abstraction does not support. That is a larger structural
change that deserves its own task or ADR amendment rather than an ad-hoc workaround.

*Risk level:* low on typical production usage (neo4j default session auto-commits are
sub-millisecond; concurrent schema-level type changes are rare). High on a DB under
sustained write load with schema mutations. The reconciliation invariant is still
asserted in mocked tests and proven in e2e tests (where the live DB is quiescent by
fixture design).

*Follow-up:* if single-transaction enforcement is required, open a dedicated task to
extend the inspector's execution surface with a transaction context and amend ADR-035
with the implementation approach chosen.

---

### E46.3 — Memgraph + NetworkX-reference parity

> **Model: Opus.** Backend parity is a hard contract (ADR-009). The reference backend is the parity baseline; Memgraph must match shape.

**Goal:** the NetworkX reference inspector and the Memgraph inspector populate
`observed_type_counts` with the same semantics, so the field is backend-consistent.

**Operation:**
1. NetworkX reference: count Python-type occurrences per property in the **same loop**
   that already builds `value_counts` (`_compute_property_profiles`) — the reference is
   the ground truth. Already touches every value; the type counter is free here.
2. Memgraph: add `value_counts_top_n` to `MemgraphInspector` and a value-scan transaction
   (histogram + type counts) via its aggregation surface (`valueType`/equivalent for
   types); `{}`/`None` where unavailable (ADR-035 §5). This also introduces
   `value_distribution` on Memgraph (previously `None`).
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

### E46.6 — Pure-Cypher value-scan fallback (no-APOC histogram for scalar properties)

> **Model: Opus.** Additive resilience task: restore a *bounded* value scan on the pure-CYPHER strategy (and SCHEMA-without-APOC) so deployments without APOC still get a histogram for scalar-typed properties. Builds on the delivered APOC value scan (E46.1/E46.2); must not regress the honest-`{}`/`None` contract.

**Why this exists (the E46.2 scope decision it discharges).** E46.2 made the **whole
value scan an APOC feature** and removed the histogram from `build_cypher_catalogue`.
Reason: the histogram's value key must be **list-safe** — `ACTED_IN.roles` is a
`StringArray`, and plain `toString(list)` throws (`Invalid input for function 'toString()':
… got: StringArray`). The list-safe key chosen was `apoc.convert.toJson(v)`, which is
APOC-only. Type counts already required `apoc.meta.cypher.type(v)`. So on pure-CYPHER /
SCHEMA-without-APOC the value scan is skipped entirely: `observed_type_counts == {}` **and**
`value_distribution is None` (honest degradation — see the amended §5 below). This task
restores a fallback *histogram* (not type counts) where it is safe to do so.

**Goal:** on a strategy without APOC, `value_counts_top_n` populates `value_distribution`
for **scalar-typed** properties via a pure-Cypher histogram that groups on `toString(v)`;
**list/array** (and other non-stringifiable) properties are skipped (left `None`) rather
than crashing. Type counts remain `{}` on these strategies (no portable runtime-type
function — unchanged from E46.2). Re-register the pure-Cypher histogram queries in
`build_cypher_catalogue` (and the SCHEMA-without-APOC path).

**Operation** — `src/orthograph/backends/neo4j/queries.py` + `inspector.py`:
1. Add pure-Cypher histogram query variants whose grouping key is safe for scalars only —
   e.g. `WITH toString(v) AS value, count(*) …` guarded so a list value does not reach
   `toString`. Options to evaluate (pick the most version-portable that the graphglot
   parser accepts): a `WHERE NOT v IS :: LIST<ANY>` filter, a `size()`-based guard, or a
   `CASE` that emits `null` for lists (then dropped). **Never** let `toString(list)` execute.
2. In the inspector, when `value_counts_top_n` is set but `apoc_available` is `False`, run
   the pure-Cypher histogram (scalars only) and leave `observed_type_counts == {}`. Keep the
   `present_count` source honest (the pure-Cypher histogram's total reconciles only over the
   scalar population it scanned — document the partial-population semantics).
3. Re-register the fallback histogram queries in `build_cypher_catalogue`; update the
   `test_internal_catalogue_populated` membership set accordingly.

**Tests (TDD — write first):**
- pure-CYPHER + scalar property → `value_distribution` populated, `observed_type_counts == {}`.
- pure-CYPHER + **list** property → `value_distribution is None` (skipped, **no crash** — the
  hard regression guard for the discovered `toString(list)` failure).
- SCHEMA-without-APOC → same fallback behaviour as pure-CYPHER for the histogram.
- live e2e (`test_inspector_e2e.py`): seed a `StringArray` property under
  `strategy=CYPHER` and assert the inspection completes (no `toString` TypeError) with that
  property's `value_distribution is None`.

**Care / risks:** the `IS :: LIST<ANY>` type predicate / `valueType()` availability is
version-sensitive (Neo4j 5.x) and must pass the graphglot dialect validator — prefer a
guard that degrades safely on older servers. This is **additive**: the APOC value scan
(E46.1/E46.2) is unchanged; only the no-APOC path gains a histogram. Keep bounded (still
`LIMIT $top_n`).

**ADR amendment (do as part of this task or fold into E46.5).** ADR-035 §5 currently says
"the histogram may still populate" on pure-CYPHER. E46.2 tightened this to "no value scan at
all without APOC". Record the amendment: *the histogram needs a list-safe value key
(`apoc.convert.toJson`), making the full value scan APOC-gated; E46.6 restores a
scalar-only pure-Cypher histogram fallback.*

---

### Discovered during E46.2 — APOC relationship-property undercount (record + decide)

> Surfaced when validating E46.2 against a live filmography DB.

**Finding.** `apoc.meta.relTypeProperties({sample: -1})` reports
`propertyObservations = 100` for `ACTED_IN.roles` while a real
`MATCH ()-[r:ACTED_IN]->() WHERE r.roles IS NOT NULL RETURN count(r)` returns **172** (all
edges have it). APOC's relationship-property observation count is an **undercount**; the
node-side `apoc.meta.nodeTypeProperties` did not exhibit this in the same DB. This made the
pre-existing `present_count` wrong on the APOC strategy for relationship properties.

**E46.2 resolution (already applied).** When the value scan runs, the inspector now derives
`present_count` from the **real scan total** (`sum(observed_type_counts.values())`) instead
of APOC's `propertyObservations`, so `present_count` is truthful and the reconciliation
invariant holds by construction. When the scan is skipped (no `value_counts_top_n`, or no
APOC), `present_count` still falls back to APOC's value — so **the undercount persists on the
no-scan path** and is *not* fully fixed by E46.2.

**Open follow-up (needs its own decision/epic).** Decide whether the no-scan APOC path
should also correct the relationship `present_count` (e.g. a cheap count-only `MATCH … WHERE
… IS NOT NULL` per rel property, independent of `value_counts_top_n`), or whether this is
documented as an APOC-strategy limitation. Out of scope for E46; do not silently expand.

**RESOLVED — ADR-036 (`.agentic/decisions/036-apoc-no-scan-present-count-correction.md`).**
The no-scan APOC path now sources `present_count` from a dedicated property-independent
`count() … IS NOT NULL` query (`NodePresentCountQuery` / `RelPresentCountQuery`, registered
in all three catalogues) and `total_count` from the existing `NodeCountQuery` /
`RelCountQuery` instance count — for **both** relationships and nodes. The undercount is
closed on the default path, not just the opt-in scan path. Live e2e guards seed > 100 edges
to actually trip APOC's relationship sampling:
`test_apoc_no_scan_rel_present_count_is_truthful`,
`test_apoc_no_scan_partial_completeness_is_truthful`
(`tests/backends/neo4j/test_inspector_e2e.py`). The CYPHER / SCHEMA strategies were already
truthful (pure-Cypher scan) and are untouched; the value-scan path is unchanged and remains
authoritative when it runs.

---

### Discovered during E46.2 — property-less types reported instance count = 0 (FIXED)

> Surfaced when profiling a live Syngenta materials DB.

**Finding.** Relationship (and node) instance `count` was derived from property
observations: `total_count = max(row.total_observations)` over the property-scan rows. A
type with **edges/nodes but no properties** produced **zero property rows**, so `count`
collapsed to `0` — e.g. `GENERATES` (49 edges), `HAS_OUTPUT` (105 edges) all displayed
`(0 instances)` while their cardinality stats correctly showed `sample_size > 0`. The
pure-Cypher property query compounded this: `UNWIND keys(n)` emits no row for a
property-less entity, so even the pure-Cypher path undercounted.

**Resolution (applied alongside E46.2).** Added dedicated, **property-independent** count
queries — `NodeCountQuery` (`MATCH (n:\`<<label>>\`) RETURN count(n)`) and `RelCountQuery`
(`MATCH ()-[r:\`<<rel_type>>\`]->() RETURN count(r)`) — registered in all three catalogues.
`_build_node_profile` / `_build_rel_profile` now set `count` from these, never from property
observations. Live e2e guards added: `test_property_less_relationship_has_nonzero_count`,
`test_property_less_node_label_has_nonzero_count`. This is a **pre-existing** count-derivation
bug independent of the `observed_type_counts` work; fixed here because it blocked correct
profiling.

---

## Coordination

- **E45 (done for NetworkX only):** the bounded-sampling infrastructure
  (`value_distribution`, `value_counts_top_n`) exists **only** in the NetworkX reference
  inspector. E46 **introduces** the equivalent bounded value scan on Neo4j/Memgraph
  (E46.1/E46.3) — it does not extend a pre-existing DB scan (ADR-035 Context).
- **E44 (done):** the three-catalogue surface (`build_apoc/cypher/schema_catalogue`) is
  the registration obligation — the new query must land in **all three** (E46.1).
- **E18 (Validation Correctness, active):** the refined type-match rule (E46.4) is a
  validation-correctness improvement; coordinate edits to `comparison/rules.py` if E18
  is in flight on the same rule.

---

## Out of Scope

- Changing `PropertyProfile.observed_type_counts`'s shape, default, or serialisation
  (frozen by ADR-034 / E45).
- Adding a second sampling/bound knob — RESOLVED: reuse `value_counts_top_n` (ADR-035 §1).
- Property *value* constraints (min/max/regex/enum) — separately deferred (see
  planning Deferred table).
- Promoting the per-type-count concept into the vendor-free `graph_profile/` layer
  beyond the existing model field (ADR-009 D1).
- Changing the `PROPERTY_TYPE_MISMATCH` issue code (would need its own ADR). NOTE:
  E46.4 modulates **severity** by prevalence (WARNING vs ERROR) — that is in scope and
  does **not** touch the code (ADR-035 §6).
