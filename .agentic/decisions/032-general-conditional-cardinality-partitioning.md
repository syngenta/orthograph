# ADR-032: General Both-Endpoint Conditional-Cardinality Partitioning

**Date:** 2026-06-19
**Status:** Accepted
**Category:** core
**Epic:** E43 (General Conditional-Cardinality Partitioning)
**Amends:** ADR-029 §3 (partition axis), §4 (`by_kind` sugar), §7 (data-time semantics)
**Extends:** ADR-005 (cardinality semantics), ADR-031 (UML notation authoring)
**Relates:** ADR-015 (declared/observed mirror), ADR-030 (per-pair observed stats),
ADR-017 (package topology)

---

## Context

ADR-029 introduced `ConditionalCardinality`: a rule set where each rule fixes a
`PropMatch` predicate on the **source** endpoint and one on the **target**
endpoint, and `resolve_for_pair(self_props, other_props)` selects the bound by
most-specific-match. The *rule model* and *resolution* were built fully
symmetric — both predicates already carry arbitrary property maps, and
`specificity` already sums both sides.

The **enforcement** path, however, was specialised. ADR-029 §3 chose a single
partition axis:

> "`__source_cardinality__` counts a source node's outgoing edges, **partitioned
> by the target node's** discriminator value … Each side discriminates only on
> its **own** endpoint and the **opposite** endpoint of the same edge."

In code (`validation.py`) this became: a node's edges are grouped **only by the
opposite endpoint's** properties (`_referenced_other_keys` →
`_accumulate_partition`); the counted node's **own** discriminator is used solely
to *select* eligible rules in `resolve_for_pair`, never to *group* the count.

### The failure this produces

The matterforge/MatProt pilot (the very domain ADR-029 was written for) models a
single `Operation` label discriminated by `type`, where the input/output count
depends on the **operation's own type**. Authored with the operation on the
**source** side this works — but only by accident: every rule wildcards the
opposite endpoint, collapsing all edges into one partition, so "group-by-opposite"
is a no-op and only rule-selection matters.

The moment the discriminated node is on the **target** side (the natural
`Sample -[:IS_INPUT]-> Operation` direction), the partition machinery reads the
discriminator key off the **wrong** endpoint, the real edges land in a `None`
partition, declared partitions count 0, and the validator emits **silently wrong
violations**. There is no definition-time signal that the rule is unenforceable —
the exact silent-pass failure mode the library exists to prevent (ADR-029 §5).

This is not a domain quirk; it is a structural gap. Because the project scope is
open-ended, we fix the architecture generally rather than constrain authors to a
"put the discriminated node on the source side" convention they cannot discover
in advance.

---

## Decision

### 1. The partition key carries discriminators from **both** endpoints

A node's edges of a relationship type are grouped by the full discriminator
tuple:

```
partition = ( self_discriminator_props , other_discriminator_props )
```

where, for the side being checked:

- `self_discriminator_props` = the values, read from the **counted node**, of
  every key any rule references on that node's endpoint.
- `other_discriminator_props` = the values, read from the **opposite endpoint**,
  of every key any rule references on the opposite endpoint.

Each group's count is checked against `resolve_for_pair(self, other)` exactly as
today. This is the **general case**: a rule may fix any set of properties on
either endpoint, and the count is subdivided by every observed combination.

### 1a. One canonical predicate convention: **absolute** (source-label / target-label)

ADR-029 left a latent ambiguity that is the *root* of the silent-wrong-validation
bug. A `ConditionalRule` has a `source` and a `target` `PropMatch`, but two
incompatible readings existed in the code:

- **Relative (validator, pre-fix):** `source` = the *counted* node, `target` =
  the *opposite* node — meaning swaps with the side being checked.
- **Absolute (definition checks + `by_kind`):** `source` = the relationship's
  **source-label** node, `target` = the relationship's **target-label** node —
  fixed, regardless of side.

For the *source* side the two coincide, so the conflict was invisible until a
`__target_cardinality__` discriminated on the counted (target) node's own
property — at which point the validator and the definition-time checks disagreed
about which predicate names which node, producing silent wrong results.

**Decision: the convention is absolute.** `rule.source` always describes the
edge's **source-label** node (arrow tail); `rule.target` always describes the
edge's **target-label** node (arrow head) — independent of whether
`__source_cardinality__` or `__target_cardinality__` is being evaluated.
`resolve_for_pair` is therefore always called as
`resolve_for_pair(source_label_node_props, target_label_node_props)`; the
"self/other" relativity is removed. This matches the author's mental model
(`source=` is the tail), the definition-time checks, and (while it exists)
`by_kind`'s `source_prop`/`target_prop`.

Under this convention, on the `__target_cardinality__` side the counted node is
the *target-label* node, so a rule discriminating on the counted node's own
property fixes it via `rule.target` — and the validator now reads it from the
correct endpoint.

### 2. No assumption that the self-discriminator is constant per node

With node-property discriminators a node's own discriminator value is in fact
constant across its edges, so the `self` component does not subdivide the count —
it only selects rules. But the partition key **carries it explicitly anyway**, so
that a future discriminator that varies per edge (e.g. a relationship property, or
a heterogeneous-label endpoint) partitions correctly with **no rework**. This is
the "fix it for good" requirement: the enforcement model is general; the current
node-property restriction is a property of the *discriminator source*, not of the
partitioning.

### 3. `by_kind` is removed

ADR-029 §4's `by_kind(source_prop, target_prop, rules={(s, t): spec})` sugar
hardcodes exactly one property per side and scalar tuple keys. It cannot express
the general case (multiple properties per side) and would have to be removed or
rebuilt the moment a two-property rule is needed. Rather than ship sugar we will
remove, **authoring is the explicit value objects**:

```python
ConditionalCardinality(
    rules=(
        ConditionalRule(
            source=PropMatch({"type": "combine", "stage": "final"}),
            target=PropMatch({"role": "internal"}),
            spec=CardinalitySpec(min=2, max=5),
        ),
        ...
    ),
    default=CardinalitySpec(min=0, max=0),
)
```

`PropMatch`, `ConditionalRule`, `ConditionalCardinality`, and `CardinalitySpec`
(with ADR-031 notation coercion: `spec="2..5"` still works) are the authoring
surface. A future ergonomic helper may return, but only one that reaches the
general case; none is built now.

### 4. Definition-time guard against unenforceable rules

The existing `standard_cardinality_checks()` checklist (ADR-029 §6) gains a check
that **rejects at `GraphDefinition(...)` construction** any rule whose predicate
references a property the enforcement path cannot read for that endpoint — so an
unenforceable rule is a construction-time ERROR, never a silent data-time
mis-validation. With both-endpoint partitioning the previously-broken case is now
*supported*, so the guard's residual job is to catch genuine impossibilities
(a key that exists on neither endpoint of the edge), closing the silent-pass hole
for good.

### 5. Data-time semantics (amends ADR-029 §7)

Unchanged in spirit; generalised in axis:

- A node's degree on a conditional side is grouped by the both-endpoint
  discriminator tuple (§1). Each observed group is checked against its resolved
  spec.
- A **rule-pinned but unobserved** partition still counts as 0 and is checked
  against its `min` (missing-partition rule — unchanged).
- A node matching **no rule** falls to `default`, with the **default floor**
  enforced against its total side degree and a `CARDINALITY_UNMATCHED_KIND` INFO
  emitted (unchanged).
- Violation messages name the discriminator values of **both** endpoints
  (already the message shape; now correct for both axes).

### 6. The declared/observed mirror is preserved

Cardinality stays declared on the relationship type, keyed by `__label__`
(ADR-015, ADR-029 §1). Both-endpoint partitioning changes only how the *declared*
side counts in memory; the Phase-2 observed side (ADR-030) remains
`CARDINALITY_UNVERIFIABLE` until per-pair statistics exist, and that boundary is
untouched.

---

## Consequences

- **Both arrow directions "just work."** `IS_INPUT: Sample → Operation` with the
  count rule keyed on `Operation.type` is now fully enforceable on
  `__target_cardinality__`. The "which side must the discriminated node be on"
  footgun is gone.
- **The general case is expressible:** multiple properties on both endpoints,
  subdivided correctly.
- **`by_kind` callers migrate** to explicit `ConditionalRule`/`PropMatch`
  (~mechanical; wide test/notebook footprint).
- **No silent wrong validation:** unenforceable rules error at definition time.
- **Constant `CardinalitySpec` sides are unaffected** — they keep the unpartitioned
  single-count path and run zero new checks.
- **Frozen model unchanged:** `PropMatch`/`ConditionalRule`/`ConditionalCardinality`
  signatures already support the general case; only the internal `_Partition`
  representation in `validation.py` widens.

---

## Rejected alternatives

- **Keep opposite-only partitioning + a "put the discriminated node on the source
  side" convention.** Rejected: the constraint is undiscoverable at authoring
  time and produces silent wrong results when violated — unacceptable for a
  validation library.
- **Guard-only (reject the unsupported case, add no capability).** Rejected as the
  end state: it makes the footgun loud but still forbids the natural model
  direction. Adopted only as the *residual* safety net on top of the general fix.
- **Keep `by_kind`, extend it to multi-property keys.** Rejected: any tuple-keyed
  table sugar collapses under N-property-per-side; the explicit value objects are
  the honest general surface. Sugar can return later if a clean general form is
  found.
- **Discriminate on relationship properties now.** Out of scope: ADR-029 keeps the
  discriminator a node property. §2 ensures the partition representation does not
  *preclude* it later, but no relationship-property discriminator is built here.

---

## Cross-references

- ADR-029: conditional cardinality (amended here — §3, §4, §7)
- ADR-031: UML notation authoring (`spec="2..5"` coercion stays the rule-spec form)
- ADR-015: declared/observed mirror
- ADR-030: per-pair observed statistics (Phase 2; boundary untouched)
- `ConditionalCardinality` / `ConditionalRule` / `PropMatch`:
  `src/orthograph/graph_definition/models.py`
- partition machinery: `src/orthograph/graph_definition/validation.py`
  (`_partition_counts`, `_accumulate_partition`, `_check_conditional_side`)
- definition-time checks: `src/orthograph/graph_definition/cardinality_checks.py`
- E43 epic: `.agentic/planning/active_epics/E43_general_conditional_cardinality_partitioning.md`
