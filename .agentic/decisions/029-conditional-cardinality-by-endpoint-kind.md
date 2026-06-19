# ADR-029: Conditional Cardinality by Endpoint Property (Pair-Keyed)

**Status:** Accepted — 2026-06-18
**Category:** core
**Epic:** E40 (Phase 1 — in-memory), E41 (Phase 2 — profiling)
**Extends:** ADR-005 (cardinality semantics), ADR-014 (relationship endpoint labels)
**Relates:** ADR-015 (declared/observed mirror), ADR-017 (package topology)

> **Amended by [ADR-032](032-general-conditional-cardinality-partitioning.md):**
> §3 (partition axis) is generalised to partition by **both** endpoints'
> discriminators (not opposite-only); §4's `by_kind` sugar is removed in favour of
> explicit `ConditionalRule`/`PropMatch`; §7 data-time semantics generalise
> accordingly. Read ADR-032 for the current enforcement model.

---

## Context

A pilot domain (matterforge / MatProt) models laboratory operations as a single
node label `Operation` discriminated by a `kind` property
(`subsampling`, `split`, `combine`, `discard`, ...). The number of input and
output relationships an `Operation` may have **depends on its `kind`**, and — as
the pilot confirmed — on the **kind of the node on the other end** as well:

```
Operation(subsampling) -[:HAS_OUTPUT]-> Sample(subsampling)   1..2
Operation(split)       -[:HAS_OUTPUT]-> Sample(nothing)        0
Operation(combine)     -[:HAS_OUTPUT]-> Sample(nothing)        0
```

Today (ADR-005) cardinality is a single `CardinalitySpec(min, max)` per
relationship side (`__source_cardinality__` / `__target_cardinality__`),
**declared on the relationship type** but **validated per node**. It cannot
express a bound that varies by an endpoint's property value.

Three alternatives were evaluated against the existing code:

1. **Distinct relationship labels per kind** (`SPLIT_OUTPUT`, `JOIN_OUTPUT`).
   Rejected for this data: the database stores a single label `HAS_OUTPUT`; the
   discriminator is a node property, not the relationship label. Relationship
   identity is the label everywhere (`GraphDefinition._rel_type_map` keys on
   `__label__`; duplicate labels are rejected by `_check_duplicate_labels`), so
   two model classes sharing one label is not representable.
2. **Cardinality declared on the node.** Rejected: it splits one edge constraint
   across two node classes and **breaks the declared/observed mirror** (ADR-015),
   because the observed side profiles cardinality per *relationship type*
   (`RelationshipTypeProfile.cardinality_stats`), not per node.
3. **Conditional cardinality declared on the relationship, discriminated by an
   endpoint property.** Chosen.

---

## Decision

### 1. Cardinality stays declared on the relationship; identity stays the label

`__source_cardinality__` / `__target_cardinality__` remain the declaration site.
Relationship identity remains `__label__`. The discriminator is a **node
property**, never a second relationship label. This preserves the
declared/observed mirror (both sides keyed by relationship type) and the
one-label-one-type invariant.

### 2. The cardinality field becomes a polymorphic seam

Each cardinality field is typed `CardinalitySpec | ConditionalCardinality`. Both
expose one method:

```python
resolve_for_pair(self_props: Mapping[str, Any],
                 other_props: Mapping[str, Any]) -> CardinalitySpec
```

- `CardinalitySpec.resolve_for_pair(...)` returns `self` (a constant ignores both
  endpoints — fully backward compatible).
- `ConditionalCardinality.resolve_for_pair(...)` selects a `CardinalitySpec` from
  a rule set keyed by the **pair** `(self-endpoint properties, other-endpoint
  properties)`.

Because the seam always yields a plain `CardinalitySpec`, every existing consumer
keeps working by calling `resolve_for_pair(...)` then `contains(count)`. The
conditional logic never leaks past the seam.

### 3. Which endpoint drives each side (the partition axis)

- `__source_cardinality__` counts a **source** node's outgoing edges of the type,
  **partitioned by the target node's** discriminator value. The source node's own
  properties supply the `self`-side predicate; the target node's the `other`-side.
- `__target_cardinality__` counts a **target** node's incoming edges,
  **partitioned by the source node's** discriminator value.

Each side discriminates only on its **own** endpoint and the **opposite**
endpoint of the same edge — never a third node. Cross-endpoint-only dependence
that is not on the counted edge is out of scope.

### 4. Rule model: property-map predicates, most-specific-wins

A rule is `(source: PropMatch, target: PropMatch, spec: CardinalitySpec)`.
`PropMatch` is a conjunction of `property == value` predicates on one endpoint
(empty map = match-all). Resolution:

- A rule matches when **both** its `source` and `target` `PropMatch` match the
  respective endpoints' properties.
- Among matching rules, the one with the **highest specificity**
  (`len(source.conditions) + len(target.conditions)`) wins. **Order is
  irrelevant.**
- If two matching rules share the top specificity → **ambiguity, rejected at
  definition time** (see §6).
- If no rule matches → the **required, explicit `default`** spec applies.

Predicates are **equality on literal values only** — no ranges, callables, or
regex. This keeps the model YAML-serialisable (PRD constraint #8) and, for
Phase 2, translatable to a Cypher `GROUP BY`.

### 5. `default` is required and explicitly stated

`ConditionalCardinality.default: CardinalitySpec` has **no implicit value**. An
absent default would silently turn an uncovered pair into "anything goes" — the
exact silent-pass failure mode the library exists to prevent. The author states
the fallback. A `(*, *)` (empty-on-both) rule is **forbidden**; `default` is the
one way to express the catch-all.

**Forward-compatible extension point:** `default`'s type may later widen to
`CardinalitySpec | <UnlistedPolicy>` (a union widening — backward-compatible, no
rename, no signature change) to support "an unlisted pair is itself an error".
Not built now; the seam is reserved.

### 6. Definition-time cross-validation is an extensible checklist

Rule-set checks run at `GraphDefinition` construction via a pluggable factory
`standard_cardinality_checks()` (mirrors `comparison/rules.standard_rules()`), so
new overlap checks are added as a class + one list entry, with no engine change.
Phase-1 checks (all **ERROR**, demotable later):

| Code | Check |
|------|-------|
| `CARDINALITY_UNKNOWN_DISCRIMINATOR` | every `PropMatch` key is a declared property of the relevant endpoint node type |
| `CARDINALITY_DISCRIMINATOR_OPTIONAL` | a property used as a discriminator is **required** (non-nullable); optional discriminators silently fall through to `default` |
| `CARDINALITY_DUPLICATE_RULE` | no two rules share an identical `(source, target)` predicate |
| `CARDINALITY_AMBIGUOUS_RULES` | no two rules co-match a pair at equal top specificity |
| `CARDINALITY_CATCHALL_RULE` | a `(*, *)` empty-on-both rule is forbidden (use `default`) |

Semantic "contradictions" where a **narrow** rule overrides a **broad** one are
**not** flagged — that is intentional refinement under most-specific-wins.

### 7. Data-time semantics

In-memory validation (`GraphValidator.validate`) counts a node's degree
**partitioned by the opposite endpoint's discriminator value** and checks each
partition against `resolve_for_pair(...)`.

- A **missing** partition counts as `0` and is still checked against its rule's
  `min` (so a `min > 0` bound on an absent pair is a violation). Code:
  `CARDINALITY_VIOLATION` (existing), now carrying the matched pair in `context`.
- A node whose discriminator value matches **no rule and no wildcard** falls
  through to `default`. Two things happen, both deliberately:
  1. The node's **total** degree on that side is checked against `default`. This
     is the **default floor**: a `default` with `min > 0` (e.g. `ONE_OR_MORE`) on
     a node with **zero** edges is a `CARDINALITY_VIOLATION`. Without this, a
     `min > 0` default would be silently inert for an edgeless node — the exact
     silent-pass failure mode §5 exists to prevent. A permissive default
     (`min == 0`, e.g. the common `ZERO_OR_MORE`) admits a zero total, so the
     floor never fires for it. The violation's `context` carries `default: true`.
  2. A `CARDINALITY_UNMATCHED_KIND` (**INFO**) is emitted so unmodelled kinds
     surface as drift, independently of whether the floor fired.

  Rationale: §7's missing-partition rule governs **rule-pinned** partitions; the
  default floor governs **unmatched** nodes. They are complementary, and together
  they guarantee that every conditional side is enforced — never silently skipped.

### 8. Query-string validation is explicitly unaffected

Cardinality is a count over instances; a static Cypher string contains no counts.
`validate_cypher` continues to check labels, relationship types, property
existence, and endpoints only. The property-existence guarantee a consumer might
expect for discriminators is delivered at **definition time** (§6) and **data
time** (§7), never as a query-string check. Blast radius on `cypher/` is zero.

---

## Two-phase boundary

- **Phase 1 (E40):** declaration model, the `resolve_for_pair` seam,
  `Cardinality.ZERO` + `EXACTLY`, definition-time checklist, in-memory
  partitioned validation, YAML round-trip, presentation. On the **DB-profile**
  path a conditional spec is reported `CARDINALITY_UNVERIFIABLE` (INFO) — see
  ADR-030 — because the observed currency is an aggregate that cannot represent
  per-pair bounds. No frozen-model change. Ships independently.
- **Phase 2 (E41):** per-pair observed statistics and live-DB enforcement —
  governed by ADR-030.

---

## Consequences

- The in-memory pre-write use case (validate a graph fragment before persisting)
  is fully solved by Phase 1.
- Existing schemas are unaffected: a relationship with a constant
  `CardinalitySpec` runs the unchanged single-count path and zero new checks.
- The declared/observed mirror is preserved: cardinality remains relationship-keyed
  on both sides.
- This is a **cardinality discriminator**, not the deferred "property value
  constraints (min/max/regex/enum)" out-of-scope item — it does not constrain a
  property's value, it selects a count bound by one.

---

## Cross-references

- ADR-005: cardinality semantics — `CardinalitySpec`, `__optional__` vs cardinality
- ADR-014: relationship endpoint labels
- ADR-015: declared/observed mirror — why both sides are relationship-keyed
- ADR-030: per-pair observed cardinality statistics (Phase 2)
- `CardinalitySpec` / `Cardinality`: `src/orthograph/graph_definition/models.py`
- `GraphValidator`: `src/orthograph/graph_definition/validation.py`
- `standard_cardinality_checks`: `src/orthograph/graph_definition/cardinality_checks.py` (new, E40)
- E40 epic: `.agentic/planning/active_epics/E40_conditional_cardinality_in_memory.md`
- E41 epic: `.agentic/planning/active_epics/E41_conditional_cardinality_profiling.md`
