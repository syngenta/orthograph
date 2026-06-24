# Epic E49: Partitioned Cardinality — Profile Rendering & One-Sided Discriminator Extraction

> **Priority:** Medium (correctness + ergonomics; surfaced by the matterforge/MatProt pilot
> profiling exercise, the same domain ADR-029/ADR-032 were written for)
> **Phase:** v0.1.0 — Pilot Readiness
> **Status:** planned
> **Blocked by:** none (both tasks are additive; build on E41 + E43 + E45, all done)
> **Decisions:** ADR-032 (§1a absolute predicate convention, §1 both-endpoint partitioning —
> the enforcement model T2 must mirror), ADR-030 / ADR-034 (per-pair observed statistics as
> `BoundedDistribution`), ADR-015 (declared/observed mirror)
> **Origin:** Pilot profiling exercise 2026-06-24 — `examples/profile_neo4j.py` enhanced to run a
> blank profile and a graph-definition-driven profile against the live MatProt graph, to observe
> how partitioned cardinality is captured in the JSON and shown in the text output. Two gaps
> surfaced; this epic records both.

---

## Why This Epic Exists

The pilot example folder gained a two-pass profiler (`examples/profile_neo4j.py`):

1. **Blank profile** — `inspect(driver)`, no graph definition. Only aggregate
   `cardinality_stats` (min/max/avg/sample_size) is produced per relationship type.
2. **Definition profile** — `inspect(driver, graph_definition=schema)` with
   `examples/full_graph_definition.py`. The intent is that conditional relationship types
   (`IS_INPUT`, `HAS_OUTPUT`, both discriminated on `Operation.type`) gain the
   `source_partitioned_cardinality` / `target_partitioned_cardinality` breakdowns so the
   per-operation-type degree patterns become observable.

Running both passes against the loaded MatProt graph (393 nodes, 6759 rels) showed the two
profiles are **identical** with respect to cardinality — the graph definition had **no
observable effect**. Investigation surfaced two independent gaps.

---

## Task T1 — Render partitioned cardinality in `profile_to_text`

**Type:** ergonomics (text visualisation)
**Files:** `src/orthograph/visualization/text.py`, tests under `tests/visualization/`
**Status:** planned

### The gap

`profile_to_text(profile)` renders only the aggregate `cardinality_stats` line
(`text.py:151-157`). The two partitioned-cardinality fields on `RelationshipTypeProfile`
(`source_partitioned_cardinality`, `target_partitioned_cardinality`, both
`dict[str, BoundedDistribution] | None`, keyed by `str(PartitionKey)` =
`"src=<v>|tgt=<v>"`) are **never rendered**. A consumer profiling a conditional relationship
type sees the breakdown in `profile.model_dump()` / JSON but not in the human-readable view —
the very view used to eyeball whether the partition pattern matches expectations.

This was worked around in the pilot by a **local renderer** in `examples/profile_neo4j.py`
(`_render_partitioned_cardinality` / `_format_partition`) to observe the ergonomics before
promoting it into the library. That local code is the reference shape for T1; T1 moves the
capability into `profile_to_text` so every caller (and `api.visualization`) benefits.

### What to build

- When a `RelationshipTypeProfile` carries a non-`None` `source_partitioned_cardinality` or
  `target_partitioned_cardinality`, render each partition under the relationship-type block,
  after the aggregate `cardinality:` line. Suggested shape (matching the pilot local renderer):

  ```
    IS_INPUT (105 instances)
      sources: ['Sample']
      targets: ['Operation']
      cardinality: min=0.0, max=3.0, avg=0.7, sample_size=149
      target_partitioned_cardinality:
        src=null|tgt=combine: min=2.0, max=4.0, avg=2.70, sample_size=10
        src=null|tgt=split:   min=1.0, max=1.0, avg=1.00, sample_size=8
  ```

- Reuse the existing `BoundedDistribution` fields (`min`, `max`, `mean`, `count`); decode or
  print the `str(PartitionKey)` key verbatim (do **not** re-parse it — the key is already the
  display form). Sort partitions by key for deterministic output.
- `None` (non-conditional or not-computed) renders nothing — no empty section, no change for
  the common path.

### Acceptance criteria

- `profile_to_text` renders both partitioned-cardinality sides when present, and renders
  nothing when both are `None` (no regression for non-conditional relationship types).
- A unit test asserts the rendered text for a `RelationshipTypeProfile` carrying a
  `target_partitioned_cardinality` with ≥2 partitions, including the `null` discriminator case
  (`PartitionKey(source_value=None, ...)` → `src=null`).
- The pilot local renderer in `examples/profile_neo4j.py` can be deleted (or left as-is) once
  T1 ships — it is no longer load-bearing. Note this in the example's docstring.

---

## Task T2 — One-sided discriminator extraction in the profiler (the real cause)

**Type:** correctness (profiling / observed-side parity with ADR-032 enforcement)
**Files:** `src/orthograph/graph_profile/inspection.py` (`_extract_discriminators`),
`src/orthograph/backends/networkx/inspector.py` (the parity reference),
`src/orthograph/graph_profile/queries/shared.py` (the partitioned-cardinality queries),
tests under `tests/backends/`
**Status:** planned — **this is why the definition profile showed no partitions**

### The gap

`_extract_discriminators(card)` (`inspection.py:17-34`) requires **exactly one** condition
property on **both** endpoints across all rules:

```python
if len(src_keys) != 1 or len(tgt_keys) != 1:
    return None
```

`examples/full_graph_definition.py` authors `IS_INPUT.__target_cardinality__` and
`HAS_OUTPUT.__source_cardinality__` with a **one-sided** discriminator: only the `Operation`
endpoint is keyed on `type`; the `Sample` endpoint is a wildcard `PropMatch()` (zero condition
keys). So `src_keys` (or `tgt_keys`) is empty, `len(...) != 1`, extraction returns `None`, the
partitioned-cardinality query is never issued, and the breakdown is `None` in both the text and
the JSON.

This is precisely the pattern ADR-032 §1a fixed for the **in-memory enforcement** path:
"`IS_INPUT: Sample → Operation` with the count rule keyed on `Operation.type` is now fully
enforceable on `__target_cardinality__`." The **profiling** path was not brought into line —
`_extract_discriminators` predates / does not honour the ADR-032 generalisation. The observed
side cannot produce statistics for the exact rule shape the declared side now validates, so the
declared/observed mirror (ADR-015) is broken for one-sided discriminators: the in-memory
validator partitions correctly, the profiler reports `CARDINALITY_UNVERIFIABLE`.

### What to build

- Relax `_extract_discriminators` so a discriminator present on **only one** endpoint is
  honoured (the other endpoint is the wildcard partition). The single-property-**per-endpoint**
  restriction may stay for this task, but a **zero-key (wildcard) endpoint must be allowed** and
  must map to a `null` partition value on that side — mirroring ADR-032's absolute convention
  and the existing `PartitionKey(source_value=None | target_value=None)` representation.
- Keep the NetworkX reference inspector (`backends/networkx/inspector.py`:
  `_discriminator_value`, `_partition_degrees`, `_compute_partitioned_cardinality`) and the
  Neo4j path in lockstep — ADR-009 backend parity. The partitioned-cardinality Cypher queries
  in `queries/shared.py` already splice the discriminator name through `<<...>>`; a wildcard
  side should resolve to "no grouping key on that side" (constant `null`), not a query for a
  non-existent property.
- Confirm the multi-property-per-endpoint case (`len > 1`) still returns `None`/declines, and
  that the definition-time guard (ADR-032 §4,
  `cardinality_checks.py`) remains the authority on enforceability — T2 must not make the
  profiler attempt a breakdown for a discriminator the enforcement path rejects.

### A second, data-level observation (record, do not "fix" in code)

Independently of the extraction bug, the **loaded MatProt graph** has `Operation` nodes whose
only properties are `{comment, description, duration_minutes}` — there is **no `type`
property** (Neo4j emits `UnknownPropertyKeyWarning` for `type`), and the `full_graph_definition`
also declares `Operation.name` which is likewise absent. So even with T2 fixed, the breakdown
for this specific dump would be a single `type=null` partition. This is a **data/definition
mismatch in the example fixture**, not a library defect:

- The discriminator the conditional rules depend on does not exist in the data.
- This is itself a useful conformance signal — a future profile-vs-definition run should flag
  "declared discriminator property `Operation.type` is absent / 0% complete," which is the kind
  of finding the profiler exists to produce.

T2's tests must therefore use a **fixture where the discriminator property is actually present**
(e.g. a small synthetic graph with `Operation.type ∈ {combine, split, ...}`), not the MatProt
dump, to prove the partitions are produced. Whether the example dump / `full_graph_definition`
should be reconciled (add `type`, or re-key the discriminator onto an existing property) is an
**example-maintenance decision**, tracked separately from this library epic — see Coordination.

### Acceptance criteria

- Given a `GraphDefinition` whose conditional side uses a one-sided discriminator
  (`Operation`-keyed, `Sample` wildcard) and a graph where that discriminator property is
  present, `inspect(..., graph_definition=...)` populates
  `target_partitioned_cardinality` (for `IS_INPUT`) / `source_partitioned_cardinality` (for
  `HAS_OUTPUT`) with one `BoundedDistribution` per observed discriminator value.
- The wildcard endpoint is represented as `null` in the `PartitionKey` (`src=null|tgt=combine`).
- Neo4j and NetworkX (and Memgraph, ADR-009) produce structurally identical breakdowns for the
  same logical graph.
- `compare_profile_to_definition` on such a profile resolves the conditional bounds against the
  per-partition observed degrees (no longer `CARDINALITY_UNVERIFIABLE` for the one-sided case).
- Multi-property-per-endpoint discriminators still decline gracefully (no crash, no partial
  breakdown).
- No regression: relationship types with constant cardinality, or with a both-endpoint
  discriminator, behave exactly as before.

---

## Guardrails (every task)

```
pwsh> python -m pytest tests/visualization/ -q                 # T1
pwsh> python -m pytest tests/backends/networkx/ -q             # T2 parity reference
pwsh> python -m pytest tests/backends/neo4j/test_inspector.py -q   # T2 (live: --neo4j)
pwsh> python -m pytest tests/comparison/ -q                    # T2 mirror (UNVERIFIABLE→checked)
pwsh> python -m mypy src/orthograph
pwsh> python -m pytest tests/test_architecture.py -q           # no vendor-concept leaks
pwsh> python -m pre_commit run --files <changed files>
```

Live-DB tests remain opt-in (`--neo4j` / `--memgraph`).

---

## Coordination

- **E41 (done) / E43 + ADR-032 (done):** T2 closes the profiling-side half of the same
  generalisation E43 made on the enforcement side. The model (`PartitionKey`,
  `*_partitioned_cardinality`) is already reshaped (E45/ADR-034); T2 only widens
  `_extract_discriminators` and the per-side query wiring — it does **not** change the model.
- **E24 (Synthetic Graph Data Generation):** the T2 test fixture (a small graph with a real
  `Operation.type` discriminator) overlaps with synthetic-data needs; reuse if available.
- **Example maintenance (separate from this epic):** reconcile `examples/full_graph_definition.py`
  with the actual MatProt dump — either the dump should carry `Operation.type`/`name`, or the
  conditional discriminator should be re-keyed onto a property that exists (e.g. `Sample.role`,
  which is 100% complete). This is an examples decision, not a library change; record it where
  the example dump is maintained.
- **T1 ⟂ T2:** independent. T1 makes any breakdown visible; T2 makes the breakdown exist for the
  one-sided case. Shipping T1 first makes T2's effect immediately observable in the text output.
