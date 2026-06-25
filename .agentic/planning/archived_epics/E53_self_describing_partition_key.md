# Epic E53: Self-Describing, Name-Aware Partitioned-Cardinality Key (single-property)

> **Priority:** High (correctness + value — makes the MatProt pilot's `Operation.type`
>   breakdown self-describing and the comparison name-aware on both paths; deletes the
>   fragile string-parse contract)
> **Phase:** v0.1.0 / pre-pilot
> **Type:** Breaking model reshape (no external profile consumers — ADR-034 §Context)
>   across `graph_profile/` + `comparison/` + `visualization/` + the three inspectors
> **Decisions:** **ADR-039** (read it first — it is the spec) · amends **ADR-034 §3/§7/§8**
>   · amends **ADR-032 §4** (records the never-added guard; closed by capability in E54) ·
>   relates **ADR-030/ADR-029** (conditional cardinality), **ADR-037** (identity triple the
>   partition nests under), **ADR-009** (inspector parity)
> **Delivers value:** after this epic, a serialized profile alone tells you which property
>   each partition discriminates on; profile↔definition stops re-deriving the name by
>   convention; profile↔profile stops colliding partitions of different properties.
> **Rubric (every task judged against this):** strongly-typed · SOLID · readability over
>   cleverness · backend parity mandatory (NetworkX = reference) · `model_dump`/`model_validate`
>   round-trip holds · `None`/honesty preserved · single-property behaviour is **identical in
>   value** to today (only the *shape* and *name-awareness* change) · each task ends green.

---

## Why This Epic Exists

The observed partitioned-cardinality key (`PartitionKey`) carries only discriminator
**values**, not their **property names**. A profile fragment reads
`"src=null|tgt=combine"` with nothing saying the target discriminator is `type`. Three
consequences (ADR-039 §Context):

1. The profile is **not self-describing** — `combine` is interpretable only by re-deriving
   `type` from the `GraphDefinition` rules.
2. **profile↔profile drift is name-blind** — `type` and `stage` discriminators collide on
   the same value string.
3. The `"src=v|tgt=v"` string key is **lossy/fragile** (ambiguous on `|`/`=`) and is
   load-bearing in `comparison/rules.py::_decode_partition` despite the model docstring
   forbidding parsing it.

This epic reshapes `PartitionKey` to carry `{property_name: value}` **maps** per endpoint,
turns the field into a `list[PartitionedCardinalityRow]` (deleting the string-key parse),
and makes comparison name-aware on **both** paths — **for the single-property case**, which
is everything the producers can measure today. The map shape is already general
(`dict[str, str | None]`), so E54 extends the *producers* to multiple properties with **no**
change to the model, serialization, comparison, diff, visualization, or their tests.

**No declaration-time guard is added** (ADR-039 §6, owner direction). A multi-property
conditional rule keeps yielding `CARDINALITY_UNVERIFIABLE` (INFO) until E54 — unchanged from
today, honest per ADR-034 §2.

---

## Decisions Already Made (do not re-litigate — see ADR-039)

- **`PartitionKey` carries maps:** `source: dict[str, str | None]`,
  `target: dict[str, str | None]`. `{}` = endpoint has no discriminator (replaces the `null`
  value-literal); `{"k": None}` = discriminator present but observed value is null.
- **Field becomes `list[PartitionedCardinalityRow] | None`**; `PartitionedCardinalityRow =
  {key: PartitionKey, stats: BoundedDistribution}`. `stats` stays `BoundedDistribution`
  (not `CardinalityStats`) for round-trip equality.
- **`str(PartitionKey)` is display-only** (visualization), never a serialization/dict key.
  `comparison/rules.py::_decode_partition` is **deleted**.
- **Comparison matches by map:** declared partitions built from
  `rule.source.conditions`/`rule.target.conditions`; observed from `row.key.source`/`.target`;
  fed to `resolve_for_pair` directly. Both `rules.py` and `diff_rules.py` become name-aware.
- **Single-property producers unchanged in value:** `_discriminator_value` /
  `_extract_discriminators` keep the `len(keys) == 1` cut; they now wrap the single value in
  a `{name: value}` map. Multi-property emission is E54.
- **No `len(keys) > 1` rejection at construction** in this epic or E54.

---

## Existing Code to Reuse / Touch

| Need | Touch | Location |
|------|-------|----------|
| Key model + field | `PartitionKey`, `PartitionedCardinalityRow`, `RelationshipTypeProfile.{source,target}_partitioned_cardinality` | `src/orthograph/graph_profile/models.py` |
| NetworkX reference producer | `_discriminator_keys`, `_discriminator_value`, `_partition_degrees`, `_stats_per_partition`, `_compute_partitioned_cardinality` | `src/orthograph/backends/networkx/inspector.py` |
| Cypher producer (shared) | `_extract_discriminators`, `_enrich_with_partitioned_cardinality` | `src/orthograph/graph_profile/inspection.py` |
| Grouped-query row build | `_materialize_partitioned_row`, the 6 partitioned query classes | `src/orthograph/graph_profile/queries/shared.py` |
| profile↔definition match | `_single_disc_key`, `_partition_props`, `_rule_value`, `_decode_partition`, `CardinalityViolationRule._compare_conditional/_check_matched/_check_unmatched` | `src/orthograph/comparison/rules.py` |
| profile↔profile diff | per-partition delta rule | `src/orthograph/comparison/diff_rules.py` |
| GraphView adapters | partitioned-field accessors (if any) | `src/orthograph/comparison/views.py` |
| Rendering | `_render_partitioned_cardinality` | `src/orthograph/visualization/text.py` |

---

## Per-Task Guardrails (apply to EVERY task unless stated)

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

Reshaped models must round-trip through `model_dump`/`model_validate`. Live-DB tests are
opt-in (`--neo4j` / `--memgraph`); default-suite tests use mocked drivers /
`FakeGraphSession` and the in-memory NetworkX backend.

**Test-token economy:** the mechanical test rewrites (constructor signature changes,
assertion-shape changes) are isolated into dedicated **Haiku** tasks (E53.7a–E53.7d) with a
fully-pinned find/replace recipe so they need no design reasoning. The *behavioural* test
changes live with their feature task (Opus/Sonnet). Do not mix the two.

---

## Tasks (execute in order; each ends green)

### E53.1 — Model reshape: map-shaped `PartitionKey`, structured rows, list field

> **Model: Opus.** The contract origin; every producer/consumer and ~250 test sites depend
> on getting the frozen-model shape and the round-trip exactly right.

**Goal:** `PartitionKey` carries `{name: value}` maps; `PartitionedCardinalityRow` carries
`{key, stats}`; the two profile fields are `list[PartitionedCardinalityRow] | None`.

**Operation** — in `src/orthograph/graph_profile/models.py`:
1. Replace `PartitionKey.source_value`/`target_value` with `source: dict[str, str | None]`
   and `target: dict[str, str | None]` (both frozen). Update the docstring: `{}` = no
   discriminator on that endpoint; `{"k": None}` = present-but-null value; the maps mirror a
   `ConditionalRule`'s `PropMatch` conditions.
2. Rewrite `PartitionKey.__str__` as **display-only**: a deterministic, sorted-key form,
   e.g. `source={} target={type=combine}`. Document that nothing parses it back.
3. Reshape `PartitionedCardinalityRow` to `{key: PartitionKey, stats: BoundedDistribution}`
   (drop the old flat `source_value`/`target_value`/`stats`). Keep `stats` typed on
   `BoundedDistribution` with the existing round-trip note.
4. Change both `RelationshipTypeProfile.source_partitioned_cardinality` and
   `target_partitioned_cardinality` to `list[PartitionedCardinalityRow] | None = None`;
   rewrite their field docstrings to describe the list-of-rows shape and the name-carrying
   key. Keep the "split into two fields" rationale (same key can appear on both sides).
5. Update `__all__` if any names changed (they should not).

**Tests (TDD — write first)** — `tests/graph_profile/test_models.py` (this task owns the
*new* model tests; the mechanical rewrite of pre-existing PartitionKey tests is E53.7a):
- `PartitionKey(source={}, target={"type": "combine"})` constructs, is frozen, equal-by-value.
- `str(PartitionKey(...))` is deterministic and stable (display form).
- `PartitionedCardinalityRow(key=..., stats=BoundedDistribution(...))` round-trips
  (`model_validate(model_dump()) == row`).
- A full `RelationshipTypeProfile` with a `list[PartitionedCardinalityRow]` on each side
  round-trips; rows preserved in order.
- **Regression-of-the-old-bug:** a discriminator value containing `|` and `=` (e.g.
  `{"label": "a|b=c"}`) round-trips losslessly (impossible under the old string key).
- A `CardinalityStats` passed as `stats` is restored as `BoundedDistribution`
  (`type(restored.stats) is BoundedDistribution`) — the documented subtype-loss invariant.

**Care / risks:** breaking — every reader updates in its own task. Do **not** add a `parse`
classmethod to `PartitionKey` (the string is display-only by decision). Keep both fields
typed on `BoundedDistribution`, never `CardinalityStats`.

---

### E53.2 — NetworkX producer: emit `{name: value}` maps (reference)

> **Model: Sonnet.** Reference implementation; the single-property spec is fully pinned by
> E53.1 — mechanical-but-careful (the produced rows are the parity oracle for E53.3).

**Goal:** the in-memory inspector emits `list[PartitionedCardinalityRow]` whose keys carry
the discriminator **name**, with identical *values* to today.

**Operation** — in `src/orthograph/backends/networkx/inspector.py`:
1. `_discriminator_value(attrs, keys)` → return `dict[str, str | None]`: when `len(keys) == 1`
   return `{the_key: str(value) or None}`; when `keys` is empty return `{}`; when
   `len(keys) > 1` return `{}` (decline — unchanged behaviour, E54 lifts this). Rename to
   `_discriminator_map` for clarity if helpful.
2. `_partition_degrees` builds `PartitionKey(source=<src map>, target=<tgt map>)`.
3. `_stats_per_partition` emits `list[PartitionedCardinalityRow]` (each
   `PartitionedCardinalityRow(key=partition, stats=BoundedDistribution(...))`), constructing
   `BoundedDistribution` directly. Order rows deterministically (sort by `str(key)`).
4. `_compute_partitioned_cardinality` returns the two lists (or `None`) unchanged in gating.

**Tests (TDD — write first)** — `tests/backends/networkx/test_inspector.py` (new-shape
assertions for the *deciding* scenario only; the bulk constructor rewrite is E53.7b):
- the deciding scenario asserts a row with `key.target == {"type": "subsampling"}` (name
  present) and the same `min`/`max`/`count` as before.
- the one-sided/wildcard scenario asserts `key.source == {}` and `key.target == {"type": ...}`.
- the multi-property scenario still declines (field is `None` or rows with `{}` keys) —
  **unchanged value**, documents the E54-deferred gap.

**Care / risks:** values must stringify exactly as before (no behaviour drift). A missing /
`None` attribute maps to `{key: None}` on a one-key endpoint, `{}` on a zero-key endpoint —
keep that distinction.

---

### E53.3 — Cypher producers: map rows on Neo4j + Memgraph (backend parity)

> **Model: Sonnet.** Thread the discriminator **names** (already in scope as identifiers)
> into row construction; Cypher templates unchanged (still one prop/side). Parity-gated
> against E53.2.

**Goal:** Neo4j and Memgraph emit the same `list[PartitionedCardinalityRow]` (name-carrying
keys) as the NetworkX reference.

**Operation:**
1. `src/orthograph/graph_profile/queries/shared.py` — `_materialize_partitioned_row` (and
   the row type usage) now needs the discriminator **names** to build the maps. The names are
   the `source_discriminator`/`target_discriminator` (or the single `discriminator` for the
   wildcard variants) already spliced into each query's identifiers. Pass them into the
   materialiser so a `sk`/`tk` value becomes `{name: value}` (or `{}` when that side is a
   wildcard). **Cypher template strings are unchanged** (still group on one property/side).
2. `src/orthograph/graph_profile/inspection.py` — `_enrich_with_partitioned_cardinality`
   builds `PartitionKey(source=<map>, target=<map>)` from the row's maps and assembles a
   `list[PartitionedCardinalityRow]` (it already knows `source_discriminator`/
   `target_discriminator`). Zero-degree-row suppression and `None`-when-empty unchanged.
3. No change to `backends/{neo4j,memgraph}/inspector.py` wiring or the query classes
   themselves beyond what the materialiser signature forces.

**Tests (TDD — write first)** — `tests/backends/{neo4j,memgraph}/test_inspector.py`
(mocked) — new-shape assertions for the assemble + parity scenarios; bulk rewrite is E53.7c:
- mocked grouped-query rows → a `PartitionedCardinalityRow` list with name-carrying keys.
- **parity:** the same logical graph yields equivalent rows across NetworkX/Neo4j/Memgraph
  (same keys, same stats).
- wildcard-source rows → `key.source == {}`.

**Care / risks:** the materialiser must receive names from the *identifiers it was given*,
never re-derive them. Keep the zero-degree suppression (parity with NetworkX). Do not touch
the 6 query names or their catalogue registration (out of scope; E54 may).

---

### E53.4 — profile↔definition comparison: match by map, delete the string parse

> **Model: Opus.** The soundness core. Deletes `_decode_partition` and the single-key name
> re-derivation; matches `PropMatch` maps against observed maps; must preserve every existing
> verdict/severity for the single-property case.

**Goal:** `CardinalityViolationRule` enforces conditional bounds by matching observed
`PartitionKey` maps against declared `ConditionalRule` predicate maps — no string parsing, no
name re-derivation by convention.

**Operation** — in `src/orthograph/comparison/rules.py`:
1. **Delete** `_decode_partition` (the string parser) and `_single_disc_key` /`_rule_value`
   value-only round-trip helpers (or repurpose them to read `rule.source.conditions` maps
   directly).
2. `_compare_conditional`: iterate `partitioned` (now a `list[PartitionedCardinalityRow]`);
   build the **declared** partition set as `PartitionKey(source=dict(rule.source.conditions
   stringified), target=dict(rule.target.conditions stringified))`; match observed rows to
   declared by `PartitionKey` equality.
3. `_check_matched`: feed `row.key.source` / `row.key.target` (maps) straight to
   `card.resolve_for_pair`; `_partition_props` is no longer needed (the map *is* the props).
4. `_check_unmatched`: group unmatched rows by the counted-side **map** (was the scalar
   value); emit `CARDINALITY_UNMATCHED_KIND` / default-floor `CARDINALITY_VIOLATION` as
   today. Messages/`context` now carry the maps (`source`/`target` dicts) instead of scalar
   `source_value`/`target_value`.
5. The `partitioned is None` → `CARDINALITY_UNVERIFIABLE` (INFO) fallback is unchanged
   (covers the E54-deferred multi-property case).

**Tests (TDD — write first)** — `tests/comparison/test_rules.py` (behavioural; the `_obs_key`
helper + builder rewrites are E53.7d, but the *verdict* assertions belong here):
- single-property conditional, observed row `key.target == {"type": "combine"}`, in-bounds →
  no violation; out-of-bounds → `CARDINALITY_VIOLATION` naming `{"type": "combine"}`.
- observed map matching no rule → `CARDINALITY_UNMATCHED_KIND` + default floor.
- no breakdown (field `None`) → `CARDINALITY_UNVERIFIABLE` (INFO) (multi-property regression).
- both-endpoint-conditional type enforced independently per side.

**Care / risks:** preserve every existing code/severity — this is a *shape* change, not a
verdict change, for single-property. Stringify rule condition values the same way the
producer stringifies observed values (so maps compare equal). Confirm `comparison/views.py`
exposes the list field unchanged; adjust only if it materialised the old dict.

---

### E53.5 — profile↔profile diff: name-aware per-partition delta

> **Model: Opus.** Closes ADR-034 §8's profile↔profile partition row honestly — the gap the
> whole epic was motivated by. May be partly new code.

**Goal:** the symmetric diff matches partitions between two profiles by `PartitionKey` **map
equality**, so partitions discriminating on different properties no longer collide, and emits
a per-partition delta (INFO).

**Operation** — in `src/orthograph/comparison/diff_rules.py`:
1. Locate (or add) the per-partition delta rule for `{source,target}_partitioned_cardinality`.
2. Match rows across the two operands by `PartitionKey` equality (maps); a partition present
   on one side only, or with differing `stats`, emits a per-partition delta (INFO) keyed by
   the partition's maps. Total-count exclusion (ADR-034 §6) unchanged.

**Tests (TDD — write first)** — `tests/comparison/test_diff_rules.py`:
- two profiles, same `{"type": "combine"}` partition, differing degree stats → one
  per-partition delta (INFO).
- two profiles, one with `{"type": "combine"}` and one with `{"stage": "combine"}` →
  treated as **distinct** partitions (added/removed), **not** a single matched delta
  (the name-blindness regression this epic fixes).
- partition present on left only → added/removed delta.

**Care / risks:** if no per-partition diff rule exists today, scope it minimally to the
list-of-rows shape; do not invent new severities (INFO per the matrix). Keep determinism
(sort by `str(key)`).

---

### E53.6 — Rendering: render the name-carrying maps

> **Model: Sonnet.** Iterate the list of rows; render the maps. Mechanical but owns its
> behavioural render test.

**Goal:** `profile_to_text` renders each partition with its discriminator name(s).

**Operation** — in `src/orthograph/visualization/text.py`:
- `_render_partitioned_cardinality(side, rows)` iterates `list[PartitionedCardinalityRow]`,
  rendering each `row.key` via its display `__str__` (e.g. `source={} target={type=combine}`)
  plus the `stats` summary. Sort rows deterministically by `str(row.key)`.
- Update the two call sites (`source_partitioned_cardinality` /
  `target_partitioned_cardinality`) for the list shape; `None`/absent unchanged.

**Tests (TDD — write first)** — `tests/visualization/test_text.py` (behavioural lines; the
constructor rewrites are E53.7a's domain if shared, else inline here):
- a target-side breakdown renders `type=combine` (name visible) for each partition.
- a wildcard-source partition renders `source={}` (or the chosen empty-map form).
- absent fields render nothing (regression).

**Care / risks:** deterministic ordering; the display form is the *only* place `__str__` is
used — keep it human-readable, not machine-parseable.

---

### E53.7a — Mechanical test rewrite: `graph_profile` + `visualization` constructors

> **Model: Haiku.** Pure find/replace to the new constructor shape. **No design, no new
> assertions** beyond the literal shape swap. Verification = the targeted test files pass.

**Recipe (apply verbatim):** in `tests/graph_profile/test_models.py` and
`tests/visualization/test_text.py`, rewrite every `PartitionKey(source_value=X,
target_value=Y)` to `PartitionKey(source=<map for X>, target=<map for Y>)` where:
- a non-`None` value `"v"` on the **source** side discriminating on property `P` becomes
  `source={"P": "v"}`; on the **target** side `target={"P": "v"}`.
- `None` (the old null partition) becomes `{}` (empty map — no discriminator on that side).
- The property name `P` for each test is stated in that test's setup (the
  `ConditionalCardinality` rules it builds); if the test has no definition context, use the
  name already asserted nearby. **If you cannot determine the name from local context, STOP
  and leave a `# TODO(E53.7a): name?` and list it in your report** — do not guess.
- Every old `dict[str, BoundedDistribution]` literal assigned to a partitioned field becomes
  a `list[PartitionedCardinalityRow]`: `{str(PartitionKey(...)): dist}` →
  `[PartitionedCardinalityRow(key=PartitionKey(...), stats=dist)]`.
- Old `PartitionedCardinalityRow(source_value=..., target_value=..., stats=...)` →
  `PartitionedCardinalityRow(key=PartitionKey(source=..., target=...), stats=...)`.

**Verify:**
```
pwsh> python -m pytest tests/graph_profile/test_models.py tests/visualization/test_text.py -q
```

**Care / risks:** mechanical only. If a test asserts *behaviour* that genuinely changed
(not just shape), STOP and escalate to the owning task rather than force-fit. Report any
`# TODO(E53.7a): name?` left behind.

---

### E53.7b — Mechanical test rewrite: NetworkX inspector tests

> **Model: Haiku.** Same recipe as E53.7a, scoped to
> `tests/backends/networkx/test_inspector.py`.

**Recipe:** apply the E53.7a constructor/field recipe to
`tests/backends/networkx/test_inspector.py`. Discriminator names come from each test's
`ConditionalCardinality` setup (e.g. `Operation.type` → `{"type": ...}`). The
`_multi_property_declines` test keeps asserting decline (field `None` / `{}` keys) — the
*value* is unchanged, only the shape.

**Verify:**
```
pwsh> python -m pytest tests/backends/networkx/test_inspector.py -q
```

**Care / risks:** if the deciding/parity numbers change (they must not), STOP — that is a
real E53.2 bug, not a test-shape issue.

---

### E53.7c — Mechanical test rewrite: Neo4j + Memgraph inspector tests

> **Model: Haiku.** Same recipe, scoped to the four backend test files.

**Recipe:** apply the E53.7a constructor/field recipe to
`tests/backends/neo4j/test_inspector.py`, `tests/backends/neo4j/test_inspector_e2e.py`,
`tests/backends/memgraph/test_inspector.py`, `tests/backends/memgraph/test_inspector_e2e.py`.
The `_PAIR = str(PartitionKey(source_value="assembler", target_value="final"))` constants
become a `PartitionKey(source={"<name>": "assembler"}, target={"<name>": "final"})` (names
from the test's definition setup). `test_inspector_queries.py` / `test_shared.py` change only
if `_materialize_partitioned_row`'s signature changed — update the call/assertion shape, not
the query names.

**Verify:**
```
pwsh> python -m pytest tests/backends/neo4j tests/backends/memgraph tests/graph_profile/queries -q
```
(Live-DB e2e remain opt-in; default run uses mocks.)

**Care / risks:** do not alter the 6 query-name assertions in `test_inspector_queries.py`.
Report any name you could not resolve.

---

### E53.7d — Mechanical test rewrite: comparison tests (`_obs_key` + builders)

> **Model: Haiku.** Rewrite the partition-construction helper and profile builders;
> behavioural verdict assertions were already set by E53.4/E53.5.

**Recipe:** in `tests/comparison/test_rules.py` and `tests/comparison/test_diff_rules.py`:
- Replace the `_obs_key(source_value, target_value)` helper (which returned
  `str(PartitionKey(...))`) with one that returns a `PartitionedCardinalityRow(key=PartitionKey(
  source=<map>, target=<map>), stats=...)` — or inline the row construction. The maps' names
  come from the `ConditionalCardinality` rules each test declares.
- Every profile built with `{source,target}_partitioned_cardinality={...dict...}` becomes a
  `list[PartitionedCardinalityRow]`.

**Verify:**
```
pwsh> python -m pytest tests/comparison -q
```

**Care / risks:** if a verdict assertion fails after the shape swap, that is an E53.4/E53.5
behavioural bug — STOP and escalate; do not change the asserted code/severity.

---

### E53.8 — Docs, planning hygiene, full-suite gate

> **Model: Haiku.** Fully-specified doc/planning updates + final guardrail run.

**Operation:**
1. Add the **E53 row** to `.agentic/planning/overview.md` (Epics table + dependency note +
   Active epic-files list). Mark it independent/correctness, blocks E54.
2. Add the **ADR-039 routing row** to `.agentic/CONTEXT.md` (under the conditional-cardinality
   / partitioned-cardinality questions); confirm ADR-032/ADR-034 cross-links resolve.
3. Run the **full** guardrail set and confirm green:
```
pwsh> python -m pytest -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --all-files
```

**Care / risks:** purely mechanical/doc. If the full suite reveals a partition assertion no
earlier task touched, escalate to that task's model tier.

---

## Success Criteria

- [ ] **ADR-039** Accepted; ADR-034 §3/§7/§8 and ADR-032 §4 amendments cross-linked.
- [ ] `PartitionKey` carries `source`/`target` `{name: value}` maps; `__str__` is
      display-only; no `parse` method.
- [ ] Field is `list[PartitionedCardinalityRow] | None`; `PartitionedCardinalityRow =
      {key, stats}`; `stats` is `BoundedDistribution`; full round-trip holds (incl. a value
      containing `|`/`=`).
- [ ] All three inspectors emit name-carrying partition rows; **single-property values are
      identical to today**; 3-backend parity.
- [ ] profile↔definition matches by map; `_decode_partition` **deleted**; every
      single-property verdict/severity preserved; multi-property → `CARDINALITY_UNVERIFIABLE`.
- [ ] profile↔profile matches by `PartitionKey` map equality; `{"type":...}` ≠ `{"stage":...}`.
- [ ] Rendering shows discriminator names.
- [ ] Full suite + mypy + pre-commit green; overview + CONTEXT updated.

---

## Out of Scope (→ E54)

- Multi-property-per-endpoint **profiling** (producers still cap at one property/side).
- Cypher **N-property grouping** templates, identifier-model widening,
  `_extract_discriminators`/`_discriminator_value` multi-key lifting.
- Any `len(keys) > 1` rejection at `GraphDefinition` construction (not added in any epic —
  ADR-039 §6).
- Relationship-property discriminators (ADR-032 §Rejected — still out of scope).
