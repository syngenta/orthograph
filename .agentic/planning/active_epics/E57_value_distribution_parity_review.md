# Epic E57: Value-Distribution Cross-Backend Parity — Review & Verify (no fix this round)

> **Priority:** Medium
> **Phase:** v0.1.0 — quality / correctness review
> **Type:** **Investigation & verification only.** No production code change in
>   this epic. Produces a findings note (and, if warranted, an ADR) that a later
>   *fix* epic will action.
> **Origin:** E56 analysis (2026-06-28). Surfaced while planning the hoist of the
>   duplicated `_build_value_distribution` (E56.3): the two backend bodies are
>   byte-identical, but they ride on **different DB-side histogram keys**, so the
>   *output* diverges. We are deferring the fix and first nailing down exactly
>   what diverges, why, and what must be true before touching it.
> **Relates to:** ADR-035 / ADR-036 (`observed_type_counts` + value scan),
>   ADR-034 (`BoundedDistribution`), E46 (value-scan delivery), E56.3 (the hoist
>   that must preserve, not erase, the deviation).

---

## The finding in one paragraph

`PropertyProfile.value_distribution` is a bounded `{value: count}` histogram with
a `sample_complete` flag and an `other_count` remainder. The Python that assembles
it — `_build_value_distribution` in `backends/neo4j/inspector.py:837` and
`backends/memgraph/inspector.py:478` — is **byte-for-byte identical** (count the
shown values, `sample_complete = top_total >= present_count`, fold the shortfall
into `other_count`). The divergence is **not in this function**; it is in the
**DB-side grouping key** chosen by the histogram *query*:

| Path | Histogram grouping key | List/map values | Effect on a scalar+list property |
|------|------------------------|-----------------|----------------------------------|
| Neo4j **APOC** (`ApocNodeValueHistogramQuery`) | `apoc.convert.toJson(value)` — **list-safe** | kept *in* the histogram | counted → `sample_complete=True` |
| Neo4j **pure-Cypher fallback** (`CypherNodeValueHistogramQuery`) | `toStringOrNull(value)` — **scalar-only** | dropped (→ null, filtered) | dropped → `sample_complete=False`, lists in `other_count` |
| **Memgraph** (`MemgraphNodeValueHistogramQuery`) | `toStringOrNull(value)` — **scalar-only** | dropped | dropped → `sample_complete=False`, lists in `other_count` |

So the real axis is **APOC-Neo4j vs everything-else** (Memgraph *and*
Neo4j-without-APOC behave the same). The existing docstring at
`memgraph/inspector.py:491-500` frames it as "Memgraph vs Neo4j", which is
**incomplete** — Neo4j on the CYPHER/SCHEMA strategies degrades identically. This
mischaracterisation is itself a finding to correct.

---

## Consequences — in the OUTPUT (`GraphProfile`)

For a property whose values are **all scalars** (the overwhelming common case):
**no divergence.** `toStringOrNull` and `apoc.convert.toJson` both stringify every
value; `sample_complete`, `histogram`, `other_count` match across backends.

For a property that **mixes scalar and list/map values** (or is list/map-typed):
- **APOC-Neo4j**: the list/map values appear as JSON-string keys in `histogram`;
  `top_total` can reach `present_count` → `sample_complete=True`, `other_count=0`.
- **Memgraph / Neo4j-no-APOC**: `toStringOrNull` returns null for the list/map
  values, the query's `WHERE value IS NOT NULL` filter drops them, `top_total <
  present_count` → `sample_complete=False`, and the dropped values land in
  `other_count` **without ever appearing as histogram keys**.

Net: for the *same data*, the same property can report a **complete** distribution
on one backend and a **truncated** one on another, with different `other_count`
and a different key set. Any consumer that branches on `sample_complete` or reads
`histogram` keys for list-valued properties sees backend-dependent output.

> **Not affected:** `observed_type_counts` (the E46 headline deliverable) is exact
> and parity-correct on **all** backends — it groups on the *type* function
> (`apoc.meta.cypher.type` / `valueType`), not the value key. Only the *value
> histogram* diverges. This boundary must be preserved by any future fix.

---

## Consequences — in the ALGORITHM / comparison

- **`PropertyEnumValueRule`** (`comparison/rules.py`) stands down to
  `PROPERTY_VALUE_UNVERIFIABLE` (INFO) when `sample_complete is False`. So on
  Memgraph / Neo4j-no-APOC, a scalar+list enum property silently becomes
  *unverifiable* where APOC-Neo4j would *verify* it. The drift verdict is
  **backend-dependent** for these properties — a correctness-relevant asymmetry,
  not just a cosmetic one.
- **`PropertyDistinctCountRule`** / any rule reading `histogram` keys: the key set
  differs (JSON strings present vs absent), so distinct-value reasoning differs.
- This is consistent with the "honest degradation" design (never a *false*
  verdict — the truncated side declines rather than lies), but the **set of
  properties that get verified at all** depends on the backend + strategy.

---

## Supposed causes — in terms of backend capability

1. **Memgraph has no portable list-safe value key.** It exposes `valueType()`
   (built-in, used for type counts) and `toStringOrNull()` (scalars only). There
   is no built-in `toJson`-equivalent usable as a `GROUP BY` key for list/map
   values, so the scalar-only key is the honest ceiling for Memgraph today.
2. **Neo4j's list-safe key is APOC-only.** `apoc.convert.toJson` requires the APOC
   runtime. On the SCHEMA / CYPHER strategies (no APOC) Neo4j has the same ceiling
   as Memgraph, which is *why* the pure-Cypher fallback query also uses
   `toStringOrNull`. The deviation is therefore **APOC-presence-driven**, not
   vendor-driven.
3. The Python assembler is shared-shaped by construction (same `BoundedDistribution`
   arithmetic), which is exactly why hoisting it (E56.3) is safe **provided the
   query-key difference is preserved as the variable**, not flattened away.

---

## Tasks (review/verify only — NO production code)

### E57.1 — Confirm and characterise the divergence empirically — **Sonnet (live DB)**
Against a live Neo4j (APOC available), the same Neo4j with `strategy=CYPHER`
forced, and a live Memgraph, profile a fixture property that mixes scalar and
list values with `value_counts_top_n` set. Record, for each, the resulting
`value_distribution.histogram` keys, `sample_complete`, and `other_count`.
**Confirm** the 3-way table above (APOC-Neo4j complete; the other two truncated)
and capture the actual values in the findings note. *(Password supplied
interactively; never written to a file.)*

### E57.2 — Audit every downstream consumer of `value_distribution` — **Opus**
Grep and read every site that reads `value_distribution`, `.histogram`,
`.sample_complete`, `.other_count` (rules, visualization text, comparison diff
rules). For each, state whether and how its output changes between the
complete/truncated cases, and classify the consequence: cosmetic, INFO-only, or
verdict-changing (the enum-rule stand-down is the known verdict-changing one).
Output: a consumer-impact table in the findings note.

### E57.3 — Correct the mischaracterising docstring(s) — **Haiku** *(only doc text — the single sanctioned edit)*
The deviation note at `memgraph/inspector.py:491-500` (and any neo4j-side echo)
frames this as "Memgraph vs Neo4j". Correct it to "APOC-Neo4j vs Memgraph **and**
Neo4j-without-APOC", referencing the pure-Cypher fallback query. This is the one
permitted code edit (a comment fix); it removes an actively misleading statement.
Suite must stay green (comment-only).

### E57.4 — Write the findings note + decision surface — **Opus**
Produce `.agentic/notes/value_distribution_parity.md` (or an ADR if the team
decides the fix changes a documented contract) capturing: the 3-way behaviour, the
empirical numbers from E57.1, the consumer-impact table from E57.2, the supposed
causes, and a **decision surface** for the future fix epic with at least these
options:
- (a) **Accept & document** as permanent honest degradation (status quo, just
  documented precisely);
- (b) **Normalise down** — make APOC-Neo4j also use `toStringOrNull` so all paths
  agree on scalar-only (loses information on APOC, gains parity);
- (c) **Normalise up** — give Memgraph / Neo4j-no-APOC a list-safe key if/when one
  becomes portable (raises the floor; blocked on backend capability);
- (d) **Surface the difference in the model** — e.g. a field stating which key
  policy produced the histogram, so consumers can branch explicitly.
Record the rejected-for-now options and why; do **not** pick the fix here.

---

## Must be verified BEFORE any future fix is actioned

These are the preconditions the fix epic inherits from this review — list them
explicitly so the fix is not started on assumptions:

1. **Real-data prevalence.** How often do consuming graphs actually have
   scalar+list/map-mixed properties? If effectively never (pilot graphs are
   scalar-typed), the fix priority drops to "document only". Verify against the
   live pilot graph (MatProt) before investing in a behavioural fix.
2. **APOC availability in the field.** If pilots run Neo4j *with* APOC and
   Memgraph is not in the pilot path, the divergence may be unreachable in
   practice this phase. Confirm the deployment matrix.
3. **The `observed_type_counts` parity invariant must hold under any fix.** Any
   change to the histogram key must **not** perturb the type-count aggregation
   (separate query, separate function). Re-assert this with a test before/after.
4. **`sample_complete` semantics are a published contract** (ADR-034). Changing
   when it is True/False is a behaviour change with comparison-rule consequences
   (E57.2). The fix epic must treat it as such, not as an implementation detail.
5. **E56.3 ordering.** If E56.3 hoists `_build_value_distribution` to
   `CypherInspector` first, confirm the hoist kept the query-key difference as the
   variable (the deviation lives in the query layer, not the assembler) so this
   review's conclusions still map onto the code.
6. **Memgraph portable list-safe key.** Option (c) is blocked until a built-in,
   `GROUP BY`-safe list/map value key exists on Memgraph — verify current
   Memgraph capability before assuming it is achievable.

---

## Success Criteria

- [ ] The 3-way divergence (APOC-Neo4j vs Memgraph vs Neo4j-no-APOC) is confirmed
      empirically with recorded numbers (E57.1).
- [ ] Every `value_distribution` consumer is classified by output impact (E57.2).
- [ ] The misleading "Memgraph vs Neo4j" docstring is corrected (E57.3); suite green.
- [ ] A findings note exists with causes, the consumer-impact table, the decision
      surface, and the six pre-fix verification items (E57.4).
- [ ] **No behaviour change shipped**; no fix chosen; the fix is left to a future,
      explicitly-scoped epic.

## Out of Scope

- The fix itself (any change to the histogram key / `sample_complete` logic).
- Touching `observed_type_counts` (parity-correct; not implicated).
- The `_build_value_distribution` hoist — that is E56.3 (this epic only records
  the precondition it must respect).
