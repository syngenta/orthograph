# Advanced: Conditional Cardinality — Partition Enforcement Algorithm

> **Expansion planned for a future release.**
> This page is a scope stub. Full algorithmic detail — including the
> enforcement walk, partition-key construction, rule-resolution order, and
> the treatment of unmatched nodes — will be written once the profiling
> and comparison layers have stabilised.

---

## Scope

This page covers the **internal enforcement algorithm** for conditional
cardinality: how the validator builds partition keys at data-validation time,
how rules are resolved against those keys, and the correctness invariants the
implementation must satisfy.

It is the algorithmic companion to [Conditional cardinality](conditional-cardinality.md),
which describes the authoring surface and the conceptual model.

---

## Topics planned for this page

- **Partition-key construction** — how the both-endpoint discriminator tuple
  is assembled from live node properties, and why carrying both endpoint
  roles in the key (rather than only the opposite endpoint) eliminates the
  silent-wrong-validation failure mode.

- **Rule resolution order** — `PropMatch` specificity scoring, tie-breaking
  behaviour, and the role of `default=`.

- **Unmatched-partition semantics** — what happens when the database contains
  a partition that no declared rule covers; the `CARDINALITY_UNMATCHED_KIND`
  signal and its severity.

- **Rule-pinned-but-unobserved partition** — why a declared rule whose
  corresponding partition is absent in the profile still enforces its `min`
  bound (treating absence as count = 0), and when this is intentional versus
  a data-quality signal.

- **Multi-property partition keys** — the generalisation to `N` discriminator
  properties per endpoint; how the profiler emits `{name: value}` maps and
  how the comparison engine matches observed rows to declared rules by map
  equality rather than by value position.

- **Absolute predicate convention** — why `rule.source` always refers to the
  declared source-label node and `rule.target` to the declared target-label
  node, regardless of which cardinality side (`__source_cardinality__` or
  `__target_cardinality__`) is being evaluated, and the silent-wrong-validation
  defect this convention closes.

- **Definition-time enforcement guard** — the construction-time checks that
  reject rules whose predicates reference properties that cannot be read for
  a given endpoint, making unenforceable rules a loud error rather than a
  silent wrong verdict.

---

## Implementation pointers

| Concern | Module |
|---|---|
| Partition machinery | `src/orthograph/graph_definition/validation.py` (`_partition_counts`, `_accumulate_partition`, `_check_conditional_side`) |
| Definition-time guard | `src/orthograph/graph_definition/cardinality_checks.py` (`DiscriminatorPropertyExistsCheck`) |
| Observed partition models | `src/orthograph/graph_profile/models.py` (`PartitionKey`, `PartitionedCardinalityRow`) |
| Profile-side producer | `src/orthograph/graph_profile/inspection.py` (`_extract_discriminators`) |
| Comparison (profile↔definition) | `src/orthograph/comparison/rules.py` |
| Comparison (profile↔profile) | `src/orthograph/comparison/diff_rules.py` |

---

*See [Conditional cardinality](conditional-cardinality.md) for the authoring
surface, and [How profiling works](profiling.md) for how partitioned cardinality
rows are populated during inspection.*
