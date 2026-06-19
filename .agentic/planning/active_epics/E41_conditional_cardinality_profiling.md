# Epic E41: Conditional Cardinality — Profiling & Live-DB Enforcement (Phase 2)

> **Priority:** Medium (gated on a pilot needing live-DB enforcement of conditional cardinality)
> **Phase:** v0.1.0 / post-pilot
> **Blocked by:** E40 (declaration model + in-memory enforcement must land first)
> **Type:** Build (additive profile field + grouped inspection query ×3 backends) + comparison branch + parity tests
> **Decisions:** ADR-030 (read it first — it is the spec), ADR-029, ADR-008 (identifier safety), ADR-009 (inspector parity)
> **Rubric (every task judged against this):** strongly-typed · SOLID · readability over cleverness · additive-not-breaking to the frozen `GraphProfile` · backend parity is mandatory · each task ends green with guardrails run

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

## Decisions Already Made (do not re-litigate — see ADR-030)

- `RelationshipTypeProfile` gains an **optional** `partitioned_cardinality:
  dict[PartitionKey, CardinalityStats] | None = None`. The aggregate
  `cardinality_stats` is **retained, unchanged**. Replacement is rejected.
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

### E41.1 — Additive `partitioned_cardinality` field + `PartitionKey`

> **Model: Sonnet.** Frozen-model extension that must stay backward-compatible; the serialisable key shape needs a small design choice.

**Goal:** the observed model can hold per-pair stats without breaking any existing
profile consumer.

**Operation** — in `src/orthograph/graph_profile/models.py`:
1. Add a frozen `PartitionKey(BaseModel)`: `source_value: str | None`,
   `target_value: str | None` (None encodes the null/absent-edge partition).
   Provide a deterministic `__str__` for rendering/diff stability.
2. Add to `RelationshipTypeProfile`:
   `partitioned_cardinality: dict[str, CardinalityStats] | None = None`
   (key = `str(PartitionKey)` for JSON/YAML friendliness; document the encoding in
   a one-line docstring). Keep `cardinality_stats` unchanged.

**Tests (TDD — write first)** — append to `tests/graph_profile/test_models.py`:
- a `RelationshipTypeProfile` with `partitioned_cardinality=None` behaves exactly as today (regression).
- a profile with two partitions round-trips through `model_dump`/`model_validate` equal.
- `PartitionKey` `__str__` is stable and reversible enough to key the dict.

**Care / risks:** **do not** change `cardinality_stats`. The default must be `None`
so every existing constructor call and frozen instance is unaffected. Verify no
existing `GraphProfile` test breaks.

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
3. Compute a `CardinalityStats` per partition (reuse `_compute_cardinality`
   shape) and populate `partitioned_cardinality`. Non-conditional types are
   unchanged (aggregate only).
   Extract `_partition_degrees(...)` and `_stats_per_partition(...)` helpers.

**Tests (TDD — write first)** — append to `tests/backends/networkx/test_inspector.py`:
- the deciding-scenario graph (subsampling Operation: 2 subsampling-Sample, 1 nothing-Sample) → `partitioned_cardinality` has the two expected partitions with correct min/max degree.
- a relationship with a **constant** cardinality → `partitioned_cardinality is None` (no needless work).
- an Operation with zero outputs of a declared pair → that partition either absent or zero-degree, consistent with the documented missing-partition convention.

**Care / risks:** only compute partitions for conditional types (avoid bloating
profiles). Null/absent partitions must be representable. Keep helpers small. This
is the reference — its partition semantics are copied by the DB backends, so make
them obviously correct and well-commented.

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
3. `materialize` produces a row model `PartitionedCardinalityRow(source_value, target_value, stats: CardinalityStats)`; the inspector assembles these into the dict.

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

---

### E41.5 — Comparison enforces per-pair bounds

> **Model: Opus.** The cross-layer reconciliation: match each declared rule to its observed partition, handle absent partitions and absent breakdowns, classify severity correctly.

**Goal:** `compare(definition, profile)` enforces each conditional rule against the
observed partition, replacing the E40 blanket `UNVERIFIABLE` **when** the breakdown
is present.

**Operation** — in `src/orthograph/comparison/rules.py` `CardinalityViolationRule`:
1. When the declared side is `ConditionalCardinality`:
   - if `profile...partitioned_cardinality is None` → keep `CARDINALITY_UNVERIFIABLE` (INFO) (E40 behaviour, e.g. backend/definition without grouping).
   - else, for each declared rule, resolve the bound and check the matching
     observed partition's `min_degree`/`max_degree` (absent partition → degree 0,
     per the missing-partition convention); emit `CARDINALITY_VIOLATION` (ERROR)
     per violating pair with the pair in `context`.
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

## Success Criteria

- [ ] `RelationshipTypeProfile.partitioned_cardinality` is an optional, `None`-defaulted, frozen-compatible field; aggregate `cardinality_stats` unchanged; existing profile tests green.
- [ ] NetworkX computes correct per-pair stats for the deciding scenario; constant types stay aggregate-only.
- [ ] Grouped inspection query exists, routes discriminator **property names** through `validate_identifier` (unsafe name rejected), and materialises `null` partitions as `None`.
- [ ] Neo4j (APOC + Cypher) and Memgraph populate `partitioned_cardinality` with parity to NetworkX (mocked + opt-in e2e green).
- [ ] `compare` enforces per-pair bounds when the breakdown is present (ERROR on violation), falls back to `UNVERIFIABLE` when absent, and flags unmatched observed pairs (INFO).
- [ ] Visualisation renders partitions when present; ADR-030 cross-links; overview updated; full suite + mypy + pre-commit green.

---

## Out of Scope

- Changing the declaration model or in-memory semantics (that is E40 / ADR-029 — frozen here).
- Replacing the aggregate `cardinality_stats` (explicitly rejected — additive only).
- Historical / trend storage of partitions (monitoring-platform concern — PRD out-of-scope).
- Multi-property discriminator profiling beyond the guarded single-`kind` first cut (track as a follow-on within this epic only if a pilot needs it).
