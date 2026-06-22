# Epic E41: Conditional Cardinality — Profiling & Live-DB Enforcement (Phase 2)

> **Priority:** Medium (gated on a pilot needing live-DB enforcement of conditional cardinality)
> **Phase:** v0.1.0 / post-pilot
> **Blocked by:** E40 (declaration model + in-memory enforcement) *(E45 done — model reshaped)*
> **Type:** Build (partitioned profile field on the reshaped model + grouped inspection query ×3 backends) + comparison branch (cardinality rows of the ADR-034 matrix) + parity tests
> **Decisions:** ADR-034 (the reshaped model + comparison matrix — read it with ADR-030) · ADR-030 (per-pair stats spec) · ADR-029 · ADR-008 (identifier safety) · ADR-009 (inspector parity)
> **Rubric (every task judged against this):** strongly-typed · SOLID · readability over cleverness · backend parity is mandatory · `None` is honest (`CARDINALITY_UNVERIFIABLE`, never a false verdict) · each task ends green with guardrails run

> **Re-based by E45 (ADR-034).** The "additive-onto-frozen-model" framing in the
> sections below is **superseded**: E45 reshapes `GraphProfile` first (breaking
> changes permitted, no external consumers), and E41 lands its partitioned
> cardinality directly in the reshaped form — each partition is a
> `BoundedDistribution` (not a bare `CardinalityStats`), `partitioned_cardinality`
> is `dict[str, BoundedDistribution] | None`. The simple label↔label aggregate is
> retained (now also a `BoundedDistribution`). E41.1 and E41.5 are updated for
> this; the gating (partition only for declared-conditional types when a
> definition is injected) is unchanged.

---

## Why This Epic Exists

E40 enforces `ConditionalCardinality` for in-memory data but reports it
`CARDINALITY_UNVERIFIABLE` against a live database, because the observed currency
(`RelationshipTypeProfile.cardinality_stats`) is a **single aggregate per
relationship type** — it cannot distinguish `discard → 0` from `split → 2..*`.

This epic makes the observed side carry a **per-pair breakdown** so `compare()`
can enforce each conditional rule against the live database, across **all three
backends** (NetworkX, Neo4j, Memgraph). It is additive: the existing aggregate is
retained; the new statistic is an **optional** field, so no existing profile,
comparison, or visualisation breaks.

---

## Decisions Already Made (do not re-litigate — see ADR-030 + ADR-034)

- **E41 lands on the E45-reshaped model (ADR-034).** `RelationshipTypeProfile`
  gains `partitioned_cardinality: dict[str, BoundedDistribution] | None = None`.
  The simple label↔label cardinality is **always** gathered (retained, now a
  `BoundedDistribution`). The earlier "additive optional `CardinalityStats` field"
  framing is superseded by the reshape — the *intent* (optional, default `None`,
  partition only for conditional types) is unchanged.
- The grouped inspection query groups by source and target **discriminator
  property names**, parameterised; standard Cypher (Neo4j + Memgraph), no APOC.
- Discriminator **property names** are validated identifiers (ADR-008,
  validate-and-reject).
- **All three** inspectors implement the grouped statistic with parity tests
  (ADR-009). NetworkX first (reference, no DB).
- `null`-partition (no edge) maps to the "zero of that pair" check.
- When `partitioned_cardinality` is absent, comparison falls back to
  `CARDINALITY_UNVERIFIABLE` (never a false comparison).
- Single-property `kind` discriminator implemented first; multi-property grouping
  is a guarded follow-on within this epic.

---

## Existing Code to Reuse

| Need | Reuse | Location |
|------|-------|----------|
| Aggregate cardinality query | `InspectCardinalityQuery` | `graph_profile/queries/shared.py` |
| Profile models | `RelationshipTypeProfile`, `CardinalityStats` | `graph_profile/models.py` |
| Inspection assembly | `_finish_relationship_profile` | `graph_profile/inspection.py` |
| In-memory edge grouping | `_inspect_relationships`, `_compute_cardinality` | `backends/networkx/inspector.py` |
| Neo4j catalogue strategies | `build_apoc_catalogue`, `build_cypher_catalogue` | `backends/neo4j/queries.py` |
| Memgraph cardinality subclass | `MemgraphCardinalityQuery` | `backends/memgraph/queries.py` |
| Identifier safety | `validate_identifier` | `cypher/identifiers.py` (ADR-008) |
| Comparison cardinality rule | `CardinalityViolationRule` | `comparison/rules.py` |
| Declared resolution seam | `ConditionalCardinality.resolve_for_pair` | `graph_definition/models.py` (from E40) |

---

## Per-Task Guardrails (apply to EVERY task unless stated)

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

Live-DB tests are opt-in (`--neo4j` / `--memgraph`); default-suite tests use
mocked drivers / `FakeGraphSession` and the in-memory NetworkX backend. New
profile field must be `None`-defaulted and frozen-model-compatible.

---

## Tasks (execute in order; each ends green)

### E41.1 — `partitioned_cardinality` field on the reshaped model + `PartitionKey`

> **Model: Sonnet.** Extends the E45-reshaped `RelationshipTypeProfile`; the serialisable key shape needs a small design choice.

**Goal:** the observed model can hold per-pair stats (as `BoundedDistribution`)
without breaking any profile consumer.

**Pre-req:** E45 has landed — `BoundedDistribution` exists and `CardinalityStats`
is re-expressed on it. If E45 is not yet done, **do not** add this field
additively onto the old shape; finish E45 first (ADR-034).

**Operation** — in `src/orthograph/graph_profile/models.py`:
1. Add a frozen `PartitionKey(BaseModel)`: `source_value: str | None`,
   `target_value: str | None` (None encodes the null/absent-edge partition).
   Provide a deterministic `__str__` for rendering/diff stability.
2. Add to `RelationshipTypeProfile`:
   `partitioned_cardinality: dict[str, BoundedDistribution] | None = None`
   (key = `str(PartitionKey)` for JSON/YAML friendliness; document the encoding in
   a one-line docstring). The simple label↔label cardinality stays present.

**Tests (TDD — write first)** — append to `tests/graph_profile/test_models.py`:
- a `RelationshipTypeProfile` with `partitioned_cardinality=None` behaves as the reshaped baseline (regression).
- a profile with two partitions (each a `BoundedDistribution`) round-trips through `model_dump`/`model_validate` equal.
- `PartitionKey` `__str__` is stable and reversible enough to key the dict.

**Care / risks:** the default must be `None` so non-conditional relationships are
unaffected. Each partition is a `BoundedDistribution` (carries its own truncation
signal + optional `histogram` placeholder — ADR-034 §7). Verify no E45 profile
test breaks.

---

### E41.2 — NetworkX per-pair statistics (reference implementation)

> **Model: Opus.** First correct implementation of the pair-grouped statistic, including the discriminator-key derivation and null-partition handling; sets the contract the DB backends must match.

**Goal:** the in-memory inspector computes `partitioned_cardinality` grouped by
`(source.kind, target.kind)` for relationship types whose declared side is
conditional.

**Operation** — in `src/orthograph/backends/networkx/inspector.py`:
1. The inspector receives (or already has access to) the `GraphDefinition` so it
   can learn which discriminator property names a relationship's
   `ConditionalCardinality` references. (If it does not currently receive the
   definition, thread it through the inspection entry point — additive parameter,
   confirm no signature break for callers; mirror how labels are resolved today.)
2. In `_inspect_relationships`, for each conditional relationship type, accumulate
   per-`(src_disc_value, tgt_disc_value)` outgoing degree (reuse the existing
   `outgoing` per-source-node counting, but key the inner aggregation by the
   discriminator value tuple read from `src_attrs` / `tgt_attrs`). Edges with a
   missing other-endpoint map to `target_value=None`.
3. Compute a `BoundedDistribution` per partition (reuse the `_compute_cardinality`
   shape) and populate `partitioned_cardinality`. Construct `BoundedDistribution`
   directly (not the `CardinalityStats` marker subclass — see E41.1/E41.3 for the
   round-trip reason). Non-conditional types are unchanged (aggregate only).
   Extract `_partition_degrees(...)` and `_stats_per_partition(...)` helpers.

**Tests (TDD — write first)** — append to `tests/backends/networkx/test_inspector.py`:
- the deciding-scenario graph (subsampling Operation: 2 subsampling-Sample, 1 nothing-Sample) → `partitioned_cardinality` has the two expected partitions with correct min/max degree.
- a relationship with a **constant** cardinality → `partitioned_cardinality is None` (no needless work).
- an Operation with zero outputs of a declared pair → that partition either absent or zero-degree, consistent with the documented missing-partition convention.

**Care / risks:** only compute partitions for conditional types (avoid bloating
profiles). Null/absent partitions must be representable. Keep helpers small. This
is the reference — its partition semantics are copied by the DB backends, so make
them obviously correct and well-commented.

> **Known gap (tracked as E41.7):** the first cut profiles a single conditional
> side (`_conditional_side` returns the first of source/target). A relationship
> type declaring `ConditionalCardinality` on **both** endpoints is enforced on
> both sides in memory (`validation._check_conditional_side` is called per side),
> so the live-DB verdict will diverge. Scoped out of E41.2 because the flat
> `partitioned_cardinality: dict[str, BoundedDistribution]` shape cannot hold two
> per-side breakdowns without collision. See E41.7.

---

### E41.3 — Grouped inspection Cypher + identifier safety (shared)

> **Model: Opus.** Parameterised grouped Cypher with property-name injection safety and null-partition semantics; the security and correctness core for live backends.

**Goal:** a shared, identifier-safe grouped cardinality query producing per-pair
rows, consumable by Neo4j and Memgraph.

**Operation** — in `src/orthograph/graph_profile/queries/shared.py`:
1. Add `InspectPartitionedCardinalityQuery` (mirrors `InspectCardinalityQuery`)
   with identifiers `label`, `rel_type`, `source_discriminator`,
   `target_discriminator`. Template:
   ```cypher
   MATCH (n:`<<label>>`)
   OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->(m)
   WITH n, n.`<<source_discriminator>>` AS sk, m.`<<target_discriminator>>` AS tk, count(r) AS degree
   RETURN sk, tk, min(degree) AS min_degree, max(degree) AS max_degree,
          avg(degree) AS avg_degree, count(n) AS sample_size
   ```
2. All four identifiers pass through the existing `<<...>>` rendering, which
   already calls `validate_identifier` (ADR-008). Add a focused test that an
   unsafe discriminator name is **rejected**, not spliced.
3. `materialize` produces a row model `PartitionedCardinalityRow(source_value, target_value, stats: BoundedDistribution)`; the inspector assembles these into the dict. Construct the partition values as `BoundedDistribution` directly — the field is typed on `BoundedDistribution`, **not** on the `CardinalityStats` marker subclass (which adds no fields), so storing a `CardinalityStats` would be restored as its base on reload and break round-trip equality (E41.1, `test_relationship_type_profile_cardinality_stats_partition_loses_subtype`). The aggregate `cardinality_stats` field keeps using `CardinalityStats`.

**Tests (TDD — write first)** — append to `tests/graph_profile/queries/test_shared.py` and `tests/cypher/test_validate_query_catalogue.py`:
- the query renders with safe identifiers; the template contains all four slots.
- an unsafe discriminator identifier raises the identifier error (ADR-008 parity with the existing `inspect.cardinality` injection test).
- `materialize` maps a raw row (incl. `tk = null`) to `target_value=None`.

**Care / risks:** property names are **injected identifiers** — they MUST go
through `validate_identifier`; never f-string them. `null` `tk` must materialise to
`None`, not the string `"null"`. Keep the aggregate `InspectCardinalityQuery`
intact (constants still use it).

---

### E41.4 — Wire grouped query into Neo4j + Memgraph inspectors (parity)

> **Model: Sonnet.** Registration and assembly across two backends following the existing patterns; parity is the discipline, not novelty.

**Goal:** Neo4j (APOC + pure-Cypher) and Memgraph populate
`partitioned_cardinality` for conditional relationship types, matching the
NetworkX reference.

**Operation:**
1. Register `InspectPartitionedCardinalityQuery` in `build_apoc_catalogue` and
   `build_cypher_catalogue` (`backends/neo4j/queries.py`); add the Memgraph
   subclass name in `backends/memgraph/queries.py` (mirror `MemgraphCardinalityQuery`).
   > **Coordination (ADR-033 / E44):** if E44 has landed, there is a **third** Neo4j
   > catalogue `build_schema_catalogue` — register the partitioned query there too
   > (three factories, not two). If E44 has not landed, no action; E44.1 will add it.
2. In `graph_profile/inspection.py` `_finish_relationship_profile` (or its caller),
   when the declared relationship side is conditional, run the partitioned query
   per source label (reuse the per-label candidate loop already there), assemble
   `partitioned_cardinality`, and attach it. Non-conditional types unchanged.
3. The inspectors must obtain the discriminator names from the `GraphDefinition`
   (same threading as E41.2). If an inspector is invoked without a definition,
   `partitioned_cardinality` stays `None` (graceful — comparison then reports
   `UNVERIFIABLE`).

**Tests (TDD — write first)** — append to `tests/backends/neo4j/test_inspector.py`, `tests/backends/memgraph/test_inspector.py` (mocked drivers), and the `_e2e` files (opt-in):
- mocked: given grouped-query rows, the inspector assembles the expected `partitioned_cardinality`.
- parity: the same logical graph yields equivalent partitions on NetworkX and the mocked DB inspectors.
- e2e (opt-in `--neo4j` / `--memgraph`): a seeded graph with the deciding scenario produces the expected partitions.

**Care / risks:** backend isolation (no cross-backend import). Parity with the
NetworkX reference is the acceptance bar (ADR-009). Keep the conditional-only
gating so non-conditional profiling cost is unchanged.

> **Parity notes from E41.3 review (must be settled here):**
>
> 1. **Zero-degree absent-edge partition.** The shared query uses
>    `OPTIONAL MATCH ... count(r) AS degree`, so source nodes with no matching
>    edge produce a `(sk, null)` partition with `degree = 0`. The NetworkX
>    reference (`_partition_degrees`, inspector.py) iterates only actual edges and
>    never emits that row. The two backends will therefore disagree on the
>    existence/contents of the absent-edge partition for the same logical graph.
>    Decide the canonical convention (emit or suppress the zero-degree row on the
>    DB side) and encode it in the parity tests so both backends agree.
>
> 2. **`variance`/`std` not materialised by Cypher.** `materialize` in
>    `shared.py` does not compute `variance`; NetworkX's `_stats_per_partition`
>    does. A `BoundedDistribution` equality assertion between the two backends
>    will fail on those fields. Parity tests must either exclude `variance`/`std`
>    from the equality check or accept `None` from the DB side explicitly.

---

### E41.5 — Comparison enforces per-pair bounds

> **Model: Opus.** The cross-layer reconciliation: match each declared rule to its observed partition, handle absent partitions and absent breakdowns, classify severity correctly.

**Goal:** `compare(definition, profile)` enforces each conditional rule against the
observed partition, replacing the E40 blanket `UNVERIFIABLE` **when** the breakdown
is present. This implements the **cardinality rows of the ADR-034 §8 comparison
matrix** (simple aggregate bound check + partitioned per-pair check); the
node/property/constraint/value rows are delivered by E45.4.

**Operation** — in `src/orthograph/comparison/rules.py` `CardinalityViolationRule`:
1. When the declared side is `ConditionalCardinality`:
   - if `profile...partitioned_cardinality is None` → keep `CARDINALITY_UNVERIFIABLE` (INFO) (E40 behaviour, e.g. backend/definition without grouping).
    - else, for each declared rule, resolve the bound and check the matching
      observed partition's `.min` / `.max` (these are `BoundedDistribution` fields —
      **not** the old `min_degree`/`max_degree` names removed in E45); absent
      partition → degree 0, per the missing-partition convention; emit
      `CARDINALITY_VIOLATION` (ERROR) per violating pair with the pair in `context`.
   - also surface observed partitions matching **no** declared rule as
     `CARDINALITY_UNMATCHED_KIND` (INFO) (drift signal). For such an unmatched
     partition, additionally apply the **default floor** (mirrors ADR-029 §7 /
     E40.5): check the observed total degree of the unmatched source/target
     against `default` and emit `CARDINALITY_VIOLATION` (ERROR) when a `min > 0`
     default is unmet — so the live-DB verdict matches the in-memory verdict.
2. Constant spec → unchanged aggregate comparison.

Decompose into `_compare_conditional(...)` and keep the existing constant path in
its own helper.

**Tests (TDD — write first)** — append to `tests/comparison/test_rules.py`:
- conditional declared + matching `partitioned_cardinality` within bounds → no violation.
- a partition out of bounds → `CARDINALITY_VIOLATION` ERROR naming the pair.
- absent partition with `min > 0` → violation.
- profile without `partitioned_cardinality` → `CARDINALITY_UNVERIFIABLE` INFO (E40 fallback preserved).
- observed partition with no declared rule → `CARDINALITY_UNMATCHED_KIND` INFO.
- unmatched-kind partition with `min > 0` default and zero observed degree → `CARDINALITY_VIOLATION` ERROR (default floor, parity with E40.5).
- constant spec → existing comparison codes unchanged (regression).

**Care / risks:** the absent-breakdown fallback must stay (older profiles must not
suddenly pass/fail wrongly). Severity discipline: real bound violation = ERROR;
drift/unmatched = INFO. Do not read `.min`/`.max` on the conditional container —
always go through `resolve_for_pair`.

---

### E41.6 — Visualisation of observed partitions, notebook, ADR cross-link, overview

> **Model: Sonnet.** Rendering + a runnable (opt-in/mocked) notebook section + planning hygiene.

**Operation:**
1. `visualization/text.py` profile rendering: when `partitioned_cardinality` is
   present, render a compact per-pair table under the relationship; absent → today's
   aggregate line only.
2. Notebook section (cardinality or a profiling notebook): inspect the
   deciding-scenario graph (NetworkX, no DB), show `partitioned_cardinality`, run
   `compare` against the conditional definition, show an enforced per-pair
   violation. Keep DB cells opt-in/skipped.
3. Confirm ADR-030 cross-references; mark E41 in `.agentic/planning/overview.md`;
   if E40+E41 together change a documented boundary, cross-link from CONTEXT.md /
   PRD (the cardinality capability description).

**Tests / verify:**
```
pwsh> python -m pytest --nbval-lax notebooks/<the touched notebook>.ipynb -q
pwsh> python -m pytest -q
pwsh> python -m mypy src/orthograph
```

**Care / risks:** rendering must handle `None` (most relationships) without change.
Keep notebook deterministic and DB-free in the default path.

---

### E41.7 — Both-endpoint conditional cardinality: profile both sides ✅ done

> **Model: Opus.** Closes the parity gap where a relationship type is conditional
> on both endpoints; touches the observed model shape, all three inspectors, and
> comparison. Sequenced last because it widens the contract E41.2–E41.5 establish.

> **Landed.** The flat `partitioned_cardinality` field was replaced by two named
> fields `source_partitioned_cardinality` / `target_partitioned_cardinality`
> (each `dict[str, BoundedDistribution] | None`), so source-counted and
> target-counted partitions cannot collide on the same `str(PartitionKey)`.
> `_conditional_side` became `_conditional_sides` (returns *every* conditional
> directed side) in both the NetworkX inspector and `comparison/rules.py`; the
> DB inspectors loop both sides (no early `break`) and call
> `_enrich_with_partitioned_cardinality(..., side)` per processable side;
> `_compare_conditional` reads the side-specific field and an absent side yields
> `CARDINALITY_UNVERIFIABLE` for that side only. The original implementation had
> a correctness bug: the DB inspectors used a single source-anchored query for
> both sides, storing source-outgoing degree in `target_partitioned_cardinality`.
> Fixed by splitting into two symmetric queries:
> `InspectSourcePartitionedCardinalityQuery` (`MATCH (n:src_label)…count(n)`,
> outgoing degree) and `InspectTargetPartitionedCardinalityQuery`
> (`MATCH (m:tgt_label)…count(m)`, incoming degree); both registered in all
> three Neo4j catalogues and Memgraph. `_enrich_with_partitioned_cardinality`
> now anchors on the side's own labels. Mocked parity tests dispatch on
> rendered Cypher and assert `issued == ["source","target"]` (verified to fail
> on the bug). Opt-in e2e both-sides tests added for Neo4j and Memgraph.

**Goal:** when a relationship type declares `ConditionalCardinality` on **both**
`__source_cardinality__` and `__target_cardinality__`, the observed profile carries
a per-pair breakdown for **each** side, and `compare()` enforces both — matching the
in-memory path, which checks each conditional side independently
(`validation._check_conditional_side` called per side, validation.py:681 / :701).

**Problem this fixes:** E41.2's `_conditional_side` (inspector.py:279) returns the
*first* conditional side and stops, so a both-sides-conditional type is profiled on
the source side only; the target-side breakdown is silently dropped and comparison
falls back to `CARDINALITY_UNVERIFIABLE` for it (E41.5) even though the data was
available. No definition-time guard forbids both sides being conditional
(`cardinality_checks.py` has no such check; ADR-032 §1a makes both sides
first-class), so the case is reachable.

**Operation:**
1. **Model (graph_profile/models.py):** the flat
   `partitioned_cardinality: dict[str, BoundedDistribution] | None` cannot hold two
   per-side breakdowns (source-counted and target-counted partitions can collide on
   the same `str(PartitionKey)`). Separate them per counted side — e.g.
   `dict[str, dict[str, BoundedDistribution]] | None` keyed by `"source"`/`"target"`,
   or two named fields. Pick the shape that keeps E41.1 round-trip and the §8
   comparison matrix clean; document the encoding. Keep `None` the default.
2. **NetworkX (backends/networkx/inspector.py):** replace `_conditional_side` with
   a `_conditional_sides` that returns *every* conditional directed side; compute a
   breakdown per side (the counted node is the source node on the source side, the
   target node on the target side — already the `side` semantics) and assemble the
   per-side structure.
3. **Shared query + DB backends (E41.3/E41.4 surfaces):** run the grouped query
   once per conditional side and attach both breakdowns; preserve identifier safety
   and parity (ADR-009).
4. **Comparison (comparison/rules.py):** `_compare_conditional` iterates each
   conditional side, matching the per-side observed breakdown to that side's rules;
   absent side → `CARDINALITY_UNVERIFIABLE` for that side only.

**Tests (TDD — write first):**
- NetworkX: a relationship type conditional on both endpoints → both per-side
  breakdowns populated with correct partitions (extends the existing target-side
  test, which only covers target-alone).
- parity: NetworkX vs mocked Neo4j/Memgraph for the both-sides graph.
- comparison: a both-sides type with one side in bounds and the other violating →
  exactly one `CARDINALITY_VIOLATION`; source-only or target-only profiles still
  behave as in E41.5 (regression).

**Care / risks:** single-side-conditional (the common case) must produce the same
profile and verdict as before this task (regression). Do not reintroduce a
collision between source-counted and target-counted partitions. Constant sides stay
aggregate-only.

---

## Success Criteria

- [ ] `RelationshipTypeProfile.source_partitioned_cardinality` / `target_partitioned_cardinality` are optional, `None`-defaulted, frozen-compatible per-side fields of `dict[str, BoundedDistribution]` on the E45-reshaped model; the simple label↔label cardinality is retained; E45 profile tests stay green.
- [ ] NetworkX computes correct per-pair stats for the deciding scenario; constant types stay aggregate-only.
- [ ] Grouped inspection query exists, routes discriminator **property names** through `validate_identifier` (unsafe name rejected), and materialises `null` partitions as `None`.
- [ ] Neo4j (APOC + Cypher) and Memgraph populate the per-side partitioned cardinality fields with parity to NetworkX (mocked + opt-in e2e green).
- [ ] `compare` enforces per-pair bounds when the breakdown is present (ERROR on violation), falls back to `UNVERIFIABLE` when absent, and flags unmatched observed pairs (INFO).
- [ ] Visualisation renders partitions when present; ADR-030 cross-links; overview updated; full suite + mypy + pre-commit green.
- [x] A relationship type conditional on **both** endpoints carries a per-side observed breakdown and `compare` enforces each side, matching the in-memory per-side verdict; single-side types are unchanged (E41.7).

---

## Out of Scope

- Changing the declaration model or in-memory semantics (that is E40 / ADR-029 — frozen here).
- Reshaping the `GraphProfile` statistical model (that is **E45 / ADR-034** — a prerequisite; E41 consumes the reshaped model, it does not reshape it).
- Historical / trend storage of partitions (monitoring-platform concern — PRD out-of-scope).
- Multi-property discriminator profiling beyond the guarded single-`kind` first cut (track as a follow-on within this epic only if a pilot needs it).
