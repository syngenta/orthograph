# Epic E54: Multi-Property Partitioned-Cardinality Profiling (producer generalisation)

> **Priority:** Medium (closes the silent-drift hole at its root: a multi-property
>   conditional rule becomes *profiled and checked* instead of declined to
>   `CARDINALITY_UNVERIFIABLE`)
> **Phase:** v0.1.0 / pre-pilot
> **Type:** Producer generalisation — **no model, serialization, comparison, diff, or
>   visualization change** (E53 already shipped the general map-shaped key). Touches only the
>   inspector internals and the Cypher query layer.
> **Decisions:** **ADR-039 §5/§6** (read it first) · realises **ADR-032 §2** generality on
>   the profile side · relates **ADR-029** (multi-property `PropMatch`), **ADR-009** (parity),
>   **ADR-008** (`validate_identifier` splice safety)
> **Depends on:** **E53 must be complete** (the map-shaped `PartitionKey`, structured rows,
>   name-aware comparison/diff — all reused unchanged here).
> **Rubric:** strongly-typed · SOLID · backend parity mandatory (NetworkX = reference) ·
>   **every spliced identifier passes `validate_identifier`, never f-stringed** · `None`/honesty
>   preserved · the comparison verdicts for single-property cases are **unchanged** (E54 only
>   *adds* the multi-property case) · each task ends green.

---

## Why This Epic Exists

After E53, the profile *model* can represent N discriminator properties per endpoint
(`PartitionKey.source` / `.target` are `dict[str, str | None]`), and comparison/diff already
match by map. But the **producers** still emit at most one property per endpoint:

- `backends/networkx/inspector.py::_discriminator_value` declines `len(keys) > 1` → `{}`.
- `graph_profile/inspection.py::_extract_discriminators` returns `None` when either endpoint
  has `> 1` condition property.
- The six grouped Cypher queries (`graph_profile/queries/shared.py`) group on exactly one
  property per side (`n.<<source_discriminator>> AS sk`, `m.<<target_discriminator>> AS tk`).

So a legal multi-property `ConditionalRule`
(`source=PropMatch({"type": "combine", "stage": "final"})`) constructs fine, is silently
declined by the profiler, and surfaces only as `CARDINALITY_UNVERIFIABLE` (INFO) — the
silent-drift hole recorded in ADR-032 §4 / ADR-039 §Context.

This epic lifts the **producer** restriction so the breakdown is computed for arbitrary
property sets per endpoint, eliminating the gap by *capability* (ADR-039 §6 — **no**
declaration-time guard is added). The model, serialization, comparison, diff, visualization,
and **all their tests** from E53 are reused **unchanged**; E54 adds *new* multi-property
tests only.

---

## Decisions Already Made (do not re-litigate — see ADR-039 §5/§6, ADR-032 §2)

- The general capability lands in the **producers + Cypher query layer**, not the model
  (E53 already generalised the model).
- The partition key for a multi-property endpoint is the full
  `{prop1: v1, prop2: v2, ...}` map — the observed mirror of the rule's `PropMatch`
  conditions.
- **No `len(keys) > 1` rejection at `GraphDefinition` construction** (ADR-039 §6).
- Cypher grouping becomes **variable-width**: the query groups on every discriminator
  property the rule references on each endpoint. Every property name is spliced via
  `<<...>>` → `validate_identifier` (ADR-008) — never f-stringed.
- Backend parity is mandatory: NetworkX reference defines the expected rows; Neo4j and
  Memgraph match them.

---

## Existing Code to Reuse / Touch

| Need | Touch | Location |
|------|-------|----------|
| NetworkX multi-key read | `_discriminator_keys`, `_discriminator_value` (lift `len==1`) | `src/orthograph/backends/networkx/inspector.py` |
| Cypher discriminator extraction | `_extract_discriminators` (return full sets, not decline) | `src/orthograph/graph_profile/inspection.py` |
| Variable-width grouped queries | the 6 query classes + `_materialize_partitioned_row` | `src/orthograph/graph_profile/queries/shared.py` |
| Identifier groups | `PartitionedCardinalityIdentifiers`, `WildcardPartitionedCardinalityIdentifiers` | `src/orthograph/graph_profile/models.py` |
| Identifier splice safety | `validate_identifier`, `<<...>>` mechanism | `src/orthograph/cypher/identifiers.py` |
| Backend query subclasses + catalogue | Memgraph subclasses, Neo4j registration | `src/orthograph/backends/{neo4j,memgraph}/queries.py` |
| Backend inspector wiring | `_enrich_with_partitioned_cardinality` callers | `src/orthograph/backends/{neo4j,memgraph}/inspector.py` |
| Map-shaped key (reuse, do not change) | `PartitionKey`, `PartitionedCardinalityRow`, comparison/diff | E53 outputs |

---

## Per-Task Guardrails (apply to EVERY task)

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

NetworkX is the parity oracle. Live-DB tests opt-in (`--neo4j`/`--memgraph`); default uses
mocks / `FakeGraphSession`. **Do not change any E53 model/comparison/diff/visualization test**
— if one fails, E54 has regressed a single-property path; STOP and fix the producer.

---

## Tasks (execute in order; each ends green)

### E54.1 — NetworkX reference: multi-property discriminator maps

> **Model: Sonnet.** Reference implementation and parity oracle; lifts the `len==1` cut.
> Spec is fully pinned by ADR-039 §5 — read N keys into a map.

**Goal:** the in-memory inspector emits partition keys carrying the **full** discriminator
map per endpoint (one or many properties).

**Operation** — in `src/orthograph/backends/networkx/inspector.py`:
1. `_discriminator_value` (or `_discriminator_map`): for `keys` of **any** size, return
   `{k: (str(attrs[k]) if attrs.get(k) is not None else None) for k in sorted(keys)}`; empty
   `keys` → `{}`. Remove the `len(keys) != 1 → {}` decline.
2. `_partition_degrees` / `_stats_per_partition` unchanged in structure (they already build
   `PartitionKey(source=<map>, target=<map>)` and `PartitionedCardinalityRow` after E53) —
   they now simply receive multi-entry maps.

**Tests (TDD — write first)** — `tests/backends/networkx/test_inspector.py` (NEW tests; do
not edit E53's single-property tests):
- a relationship with `source=PropMatch({"type": "combine", "stage": "final"})` produces a
  partition row with `key.source == {"stage": "final", "type": "combine"}` (sorted),
  un-collapsed; correct `min`/`max`/`count`.
- mixed: one endpoint two properties, the other one → both maps populated correctly.
- the former `_multi_property_declines` test is **superseded** — convert it to assert the
  breakdown is now produced (or delete it and add the multi-property success test above;
  state which in your report).

**Care / risks:** deterministic map ordering (sort keys) so rows are comparable across
backends. A missing/`None` property value on a multi-key endpoint is `{k: None}` for that
key, not a dropped key.

---

### E54.2 — Cypher: variable-width grouped queries + extraction

> **Model: Opus.** Query-flow redesign: variable-width Cypher grouping with N spliced
> property names, the identifier-model widening, and the wildcard collapse — all
> injection-sensitive and parity-gated. The hardest task in the epic.

**Goal:** the grouped cardinality queries group on **every** discriminator property each
endpoint references (1..N per side), splicing each name safely; the inspector assembles the
full maps.

**Operation:**
1. `src/orthograph/graph_profile/inspection.py::_extract_discriminators` → return the full
   `(frozenset[str] source_keys, frozenset[str] target_keys)` (or an equivalent structure),
   **not** `None`-on-multi. A fully-wildcard rule set (both empty) still declines.
2. `src/orthograph/graph_profile/models.py` identifier groups
   (`PartitionedCardinalityIdentifiers`, `WildcardPartitionedCardinalityIdentifiers`): carry
   a **list** of discriminator property names per spliceable side instead of single
   `source_discriminator`/`target_discriminator`. Each name still validates as a label-grammar
   identifier.
3. `src/orthograph/graph_profile/queries/shared.py`: make the Cypher template
   **variable-width** — for `k` source properties and `j` target properties, the `WITH`
   clause projects `n.<<p1>> AS sk1, n.<<p2>> AS sk2, ...` and `m.<<q1>> AS tk1, ...`, the
   `RETURN`/`GROUP BY` carries all of them, and `_materialize_partitioned_row` reconstructs
   `key.source = {p1: sk1, p2: sk2, ...}` / `key.target = {...}`. Wildcard side → empty map,
   no projected column (mirrors the current `null AS sk` collapse, generalised to "no source
   columns"). Each property name spliced via `<<...>>` (`validate_identifier`) — **never**
   f-stringed or string-joined into the template unsafely.
4. Decide the cleanest construction: either keep the 6-class source/target × wildcard layout
   with variable-width bodies, or collapse to fewer classes that build the projection from the
   identifier list. State the choice and rationale in your report; keep the 6 registered query
   **names** stable unless you also update `backends/{neo4j,memgraph}/queries.py` registration
   and `tests/.../test_inspector_queries.py` in this task.
5. `backends/{neo4j,memgraph}/inspector.py`: pass the full key sets through
   `_enrich_with_partitioned_cardinality` (signature widens from two scalars to two name lists).
6. `backends/{neo4j,memgraph}/queries.py`: update the Memgraph subclasses / Neo4j registration
   for any signature/template change.

**Tests (TDD — write first)** — `tests/graph_profile/queries/test_shared.py`,
`tests/backends/{neo4j,memgraph}/test_inspector.py` (NEW multi-property cases) +
`tests/backends/neo4j/test_inspector_queries.py` (only if names change):
- a mocked grouped-query result with two source properties → a row whose `key.source` is the
  two-entry map; parity with the NetworkX reference (E54.1).
- **injection safety:** a discriminator property name failing `validate_identifier` is
  rejected (not spliced) — assert the raised error, for both the 1-prop and N-prop paths.
- wildcard side → empty map, no spurious grouping column.
- 3-backend parity on the same logical multi-property graph.

**Care / risks:** **identifier safety is non-negotiable** — every property name through
`<<...>>`/`validate_identifier`, never an f-string or `" ".join` into Cypher. Keep the
zero-degree-row suppression. Bound the round-trips (one grouped scan per side, not per
property). If you change query names, update registration + the catalogue tests in the same
task or parity tests break.

---

### E54.3 — Comparison & diff: confirm multi-property matching (no code change expected)

> **Model: Sonnet.** Mostly verification: E53 already made matching map-based. Add
> multi-property test coverage; touch code only if a single-property assumption leaked in.

**Goal:** profile↔definition and profile↔profile correctly match multi-property partitions
(map equality + `resolve_for_pair` already handle this).

**Operation:**
1. Audit `src/orthograph/comparison/rules.py` (`_compare_conditional`/`_check_matched`/
   `_check_unmatched`) and `diff_rules.py` for any place that assumed a single-entry map
   (e.g. taking `next(iter(map))`); if found, fix to use the whole map. Expect **no** change
   if E53 was done correctly.
2. Confirm declared partitions are built from the full `rule.source.conditions` /
   `rule.target.conditions` maps (they should be, post-E53).

**Tests (TDD — write first)** — `tests/comparison/test_rules.py`,
`tests/comparison/test_diff_rules.py` (NEW):
- a multi-property conditional rule + a matching observed multi-property partition → correct
  in/out-of-bounds verdict via `resolve_for_pair` (no longer `CARDINALITY_UNVERIFIABLE`).
- a multi-property partition matching no rule → `CARDINALITY_UNMATCHED_KIND` + default floor.
- profile↔profile: two multi-property partitions differing in one property value are distinct.

**Care / risks:** if you must change comparison code here, an E53 task under-delivered —
note it. Do not change single-property verdicts.

---

### E54.4 — Cleanup, docs, planning hygiene, full-suite gate

> **Model: Haiku.** Fully-specified cleanup + doc/planning updates + final guardrail run.

**Operation:**
1. Remove now-dead single-property-only helpers/comments left by the lift (e.g. any
   `# single-kind first cut` / `len(keys) == 1` comments in `inspector.py` /
   `inspection.py` / `rules.py` that are no longer true). **Code logic only where it is
   provably dead**; if unsure whether a line is still reached, STOP and escalate.
2. Update the ADR-039 §5/§6 status note and ADR-032 §4 note from "deferred to E54" to
   "delivered by E54" (the silent-drift hole is closed by capability). Keep them factual.
3. Mark **E54 done** in `.agentic/planning/overview.md`; update the dependency note.
4. Run the **full** guardrail set:
```
pwsh> python -m pytest -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --all-files
pwsh> rg -n "len\(keys\) == 1|single-kind first cut|multi-property.*decline" src/orthograph
```
   The `rg` line should return no stale single-property-only claims in code/comments.

**Care / risks:** doc + dead-code only. A failing full suite means a producer regression —
escalate to E54.1/E54.2, do not edit E53 tests.

---

## Success Criteria

- [ ] NetworkX reference emits multi-property partition maps (sorted keys); single-property
      output unchanged.
- [ ] Cypher grouped queries are variable-width; every discriminator name spliced via
      `validate_identifier`; wildcard side → empty map; 3-backend parity.
- [ ] `_extract_discriminators` no longer declines multi-property; `_discriminator_value`
      reads N keys.
- [ ] A multi-property conditional rule is **profiled and checked** (no longer
      `CARDINALITY_UNVERIFIABLE`); single-property verdicts unchanged.
- [ ] profile↔profile distinguishes multi-property partitions differing in any property.
- [ ] No E53 model/comparison/diff/visualization test changed; only new multi-property tests
      added.
- [ ] ADR-039 §6 / ADR-032 §4 notes updated to "delivered"; full suite + mypy + pre-commit
      green; overview updated.

---

## Out of Scope

- Any `len(keys) > 1` rejection at `GraphDefinition` construction (ADR-039 §6 — never added).
- Relationship-property discriminators (ADR-032 §Rejected — still out of scope; node
  properties only).
- Histogram/full-distribution population for partitions (ADR-034 §3 placeholder stays `None`).
- Changing the partition statistics moments beyond what producers already supply.
