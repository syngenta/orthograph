# Epic E43: General Conditional-Cardinality Partitioning

> **Priority:** High
> **Phase:** v0.1.0 — pilot readiness (correctness / pilot-blocking)
> **Status: DONE** (2026-06-19)
> **Blocked by:** E40 (done), E42 (in progress — E42.2 done; this epic touches the
>   same `models.py` cardinality surface, so land after E42 to avoid churn, or
>   coordinate edits)
> **Blocks:** none
> **Type:** Architecture fix (generalise the enforcement partition axis) +
>   `by_kind` removal + definition-time guard + ADR-032 + test/notebook/example migration
> **Decisions:** **produces ADR-032 first (done)**; amends ADR-029 §3/§4/§7;
>   relates ADR-031 (notation), ADR-015 (mirror), ADR-030 (Phase-2 boundary)
> **Rubric:** strongly-typed · SOLID · readability over cleverness · small surgical
>   diffs · break complex logic into named functions · each task ends green with guardrails run

---

## Why This Epic Exists

`ConditionalCardinality`'s rule model and resolution are already fully general:
each `ConditionalRule` carries a `source` and a `target` `PropMatch`, each holding
an arbitrary property map, and `resolve_for_pair` matches both. But the
**enforcement** path in `validation.py` partitions a node's edges **only by the
opposite endpoint's** properties (ADR-029 §3). The counted node's own
discriminator selects rules but never groups the count.

Consequence: a rule keyed on the counted node's own property is enforceable **only
when that node is on the source side and every rule wildcards the opposite
endpoint** (collapsing to one partition). Put the discriminated node on the target
side — the natural `Sample -[:IS_INPUT]-> Operation` direction for the
matterforge/MatProt pilot — and the validator reads the discriminator off the
wrong endpoint and emits **silently wrong violations**, with no definition-time
warning.

This epic makes enforcement partition by **both** endpoints' discriminators (the
general case), removes the `by_kind` sugar that cannot reach the general case, and
adds a definition-time guard so any genuinely unenforceable rule errors at
construction. After this epic, both arrow directions and multi-property-per-side
rules "just work," and the silent-wrong-validation hole is closed.

See [ADR-032](../../decisions/032-general-conditional-cardinality-partitioning.md)
for the decision and rejected alternatives.

---

## Decisions Already Made (ADR-032 — do not re-litigate)

- **Partition by both endpoints.** Partition key = `(self_discriminator_props,
  other_discriminator_props)`. Each group checked against `resolve_for_pair`.
- **No constant-self assumption.** The key carries the self component explicitly,
  so a future per-edge-varying discriminator (relationship property, heterogeneous
  label) partitions correctly with no rework.
- **`by_kind` removed.** Authoring = explicit `ConditionalRule` / `PropMatch`
  (with ADR-031 notation coercion on `spec`). No replacement sugar built now.
- **Definition-time guard.** A new `RuleSetCheck` rejects rules referencing a
  property readable on neither endpoint of the edge.
- **Data-time semantics generalise in axis only** — missing-partition rule,
  default floor, and `CARDINALITY_UNMATCHED_KIND` INFO all stand.
- **Declared/observed mirror and the Phase-2 `UNVERIFIABLE` boundary are untouched.**

---

## Existing Code to Touch

| Concern | File | Anchor (today) |
|---------|------|----------------|
| Partition type alias (`_Partition`, `_PartitionCounts`) | `src/orthograph/graph_definition/validation.py` | `:28`–`:35` |
| `_referenced_other_keys` (opposite-only) | `validation.py` | `:514` |
| `_partition_key` / `_accumulate_partition` (opposite-only) | `validation.py` | `:527`–`:548` |
| `_partition_counts` (drives both sides) | `validation.py` | `:551` |
| `_declared_partitions` (pins rule partitions) | `validation.py` | `:224` |
| `_check_conditional_side` (per-partition resolve + default floor) | `validation.py` | `:388` |
| `_self_discriminator_keys` / `_discriminator_value` (message helpers) | `validation.py` | `:248`–`:268` |
| `by_kind` (DELETE) | `src/orthograph/graph_definition/models.py` | `:476`–`:497` |
| Definition-time checklist (add guard) | `src/orthograph/graph_definition/cardinality_checks.py` | `standard_cardinality_checks` `:317` |
| `by_kind` call sites (MIGRATE) | tests (`test_cardinality_spec`, `test_validation`, `test_relationship_model`, `test_graph_definition`, `test_diff_rules`, `test_rules`, `test_yaml`, `test_relationship_cardinality_coercion`), notebooks (`01.04`, `01.05`), `examples/sample_processing_pipeline.py` | ~79 refs |
| ADR amendment banner | `.agentic/decisions/029-*.md` | done |
| Planning hygiene | `.agentic/planning/overview.md`, `.agentic/CONTEXT.md` | — |

---

## Tasks

> **E43.0 (ADR) done.** **E43.1 → E43.2** are the load-bearing core (partition axis
> + guard) and must precede the mechanical `by_kind` migration (E43.3). E43.4 is
> docs/example/notebook. E43.5 is the integration gate.

---

### E43.0 — ADR-032 (DONE)

ADR-032 recorded; ADR-029 carries the amendment banner. No code.

---

### E43.1 — Generalise the partition axis to both endpoints

> **Model: Opus.** The one load-bearing change. Get the partition identity and the
> resolve wiring right and every downstream behaviour follows.

**Goal:** a conditional side groups a node's edges by `(self_discriminator_props,
other_discriminator_props)` and checks each group; the discriminated node works on
**either** side.

**Operation** — `validation.py`:
1. Widen `_Partition` to a 2-part key:
   `tuple[tuple[tuple[str, object], ...], tuple[tuple[str, object], ...]]`
   (self-props sorted, other-props sorted). Update `_PartitionCounts`.
2. Add `_self_referenced_keys(card, side)` mirror of `_referenced_other_keys`
   (own-endpoint keys). (`_self_discriminator_keys` already exists — reuse/rename
   to one canonical helper.)
3. `_accumulate_partition`: build the key from **both** the counted node's selected
   props and the opposite endpoint's selected props. (Counted-node props are
   available at the call site in `_partition_counts` — pass the self node in.)
4. `_partition_counts`: pass the **self** node (`node_index.get(src_uid)` for
   source side, `node_index.get(tgt_uid)` for target side) in addition to the
   opposite node.
5. `_check_conditional_side` / `_declared_partitions`: derive `self_props` and
   `other_props` from the 2-part partition for `resolve_for_pair`; keep the
   source/target argument order correct per side.
6. Message + context helpers: read each endpoint's discriminator value from the
   correct component (scalar for single-key — preserve the existing
   `context["source_kind"]`/`["target_kind"]` scalar contract from ADR-031 work).

**Tests (TDD — write first)** — `tests/graph_definition/test_validation.py`:
- target-side rule keyed on the counted node's own property enforces correctly
  (the `Sample -[:IS_INPUT]-> Operation` case — currently silently wrong).
- a rule with **two properties on one side** subdivides/selects correctly.
- a rule with properties on **both** endpoints subdivides by the full pair.
- regression: every existing conditional test (source-side, actor/movie, default
  floor, missing partition, unmatched kind) stays green with identical `context`.

**Care / risks:** the load-bearing path. Preserve scalar `*_kind` context values
(single-key) and all ADR-029 §7 behaviours. `mypy` green.

---

### E43.2 — Definition-time guard for unenforceable rules

> **Model: Sonnet.** A new `RuleSetCheck`; mechanical against the existing checklist.

**Goal:** a rule referencing a property readable on **neither** endpoint of the
edge is rejected at `GraphDefinition(...)` with a clear ERROR — no silent
data-time mis-validation.

**Resolution (E43.2 — DONE, no new code):** once E43.1 fixed the
`_check_cardinality_rules` wiring to the **absolute** convention
(`rule.source`→source-label node, `rule.target`→target-label node for both
sides), the existing `DiscriminatorPropertyExistsCheck` already rejects a key
present on neither endpoint with `CARDINALITY_UNKNOWN_DISCRIMINATOR`. Adding a
second check would be redundant. E43.2 therefore ships as **regression tests
only** (`test_unenforceable_rule_rejected_at_definition_time`,
`test_target_side_own_property_rule_accepted_at_definition_time`) that lock the
guarantee, plus this note. No new `RuleSetCheck` class.

---

### E43.3 — Remove `by_kind`; migrate all call sites

> **Model: Haiku/Sonnet.** High-volume mechanical substitution (~79 refs) with a
> fixed translation pattern.

**Goal:** `ConditionalCardinality.by_kind` is deleted; every author uses explicit
`ConditionalRule`/`PropMatch`; suite green.

**Operation:**
1. Delete `by_kind` from `models.py`.
2. Translate each call:
   `by_kind(source_prop="s", target_prop="t", rules={(a, b): spec}, default=d)`
   → `ConditionalCardinality(rules=(ConditionalRule(source=PropMatch({"s": a}) or
   PropMatch() if a=="*", target=PropMatch({"t": b}) or PropMatch() if b=="*",
   spec=spec), ...), default=d)`. Keep `spec` notation strings (ADR-031).
3. Update the E42 epic's E42.2 note that references `by_kind` coercion, and
   ADR-031 line 92 (`by_kind coerces …`) — replace with the explicit-construction
   statement (one-line; do not rewrite ADR bodies beyond the factual change).

**Files:** tests (`test_cardinality_spec`, `test_validation`,
`test_relationship_model`, `test_graph_definition`, `test_diff_rules`,
`test_rules`, `test_yaml`, `test_relationship_cardinality_coercion`), notebooks
(`01.04`, `01.05`), `examples/sample_processing_pipeline.py`.

**Verify:** grep `by_kind` returns nothing in `src/`, `tests/`, `examples/`,
notebooks; `python -m pytest -q` green.

**Care / risks:** do not change test *intent*; only the construction form. Drop the
`test_relationship_cardinality_coercion.py` `by_kind` cases or convert them to
explicit-construction equivalents.

---

### E43.4 — Notebook + example + docs

> **Model: Sonnet.** Prose + notebook cells; show the general case.

**Goal:** `01.05_conditional_cardinality.ipynb` authors with explicit
`ConditionalRule`/`PropMatch`, shows a **both-endpoints** rule and a
**target-side-discriminated** rule (the pilot direction). `examples/` updated to
the natural `IS_INPUT: Sample → Operation` / `HAS_OUTPUT: Operation → Sample`
directions now that they are enforceable. `01.04` `by_kind` cell migrated.

**Verify:** `python -m pytest --nbval-lax notebooks/01.04*.ipynb notebooks/01.05*.ipynb -q`;
`python examples/sample_processing_pipeline.py` prints expected results.

---

### E43.5 — Integration gate

> **Model: Sonnet.** Closing gate.

```
pwsh> python -m pytest -q
pwsh> python -m mypy src/orthograph
pwsh> pre-commit run --all-files
```
- zero `by_kind` references anywhere.
- both-direction + multi-property tests pass.
- ADR-032 cross-linked from CONTEXT.md; overview.md carries the E43 row.

---

## Success Criteria

- [ ] ADR-032 recorded; ADR-029 carries the amendment banner; CONTEXT.md cross-links it.
- [ ] Enforcement partitions by both endpoints; discriminated node works on either side.
- [ ] Multi-property-per-side and both-endpoints rules enforce correctly.
- [ ] Unenforceable rules error at definition time (no silent mis-validation).
- [ ] `by_kind` deleted; no reference remains in `src/`, `tests/`, `examples/`, notebooks.
- [ ] All existing conditional behaviours (source-side, actor/movie, default floor,
      missing partition, unmatched kind) stay green with identical `context`.
- [ ] Notebook + example show the general case and the pilot direction; `mypy` +
      `pre-commit` green.

---

## Out of Scope

- **Relationship-property discriminators** — ADR-029 keeps the discriminator a node
  property; ADR-032 §2 only ensures the partition representation does not preclude
  it later.
- **A replacement authoring helper** — may return later in a form that reaches the
  general case; none built now.
- **Phase-2 profiling / live-DB enforcement** — ADR-030 / E41 boundary untouched.
