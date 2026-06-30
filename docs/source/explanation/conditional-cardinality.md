# Conditional Cardinality and Property-Based Partitioning

**Conditional cardinality** lets you declare that the allowed relationship count
for a node *depends on* the properties of the source or target node. Instead of
one fixed `CardinalitySpec`, you supply a rule set: each rule binds a predicate
on either or both endpoints to a bound, and the validator selects the most
specific matching rule at data-validation time.

→ **Tutorial:** {doc}`../notebooks/01.05_conditional_cardinality` introduces
  `ConditionalCardinality` and `ConditionalRule` with a worked example.
  {doc}`../notebooks/05.05_conditional_cardinality_profiling` shows how
  conditional cardinality partitions appear in a `GraphProfile`.

---

## When you need it

The simplest case: an `Operation` node has a `type` property (`"combine"` or
`"split"`). A combine operation must have exactly two inputs; a split must have
exactly one. A single `"1..*"` cardinality would accept a split with two inputs
or a combine with one. Conditional cardinality enforces the right bound for each
kind.

---

## The authoring surface

```python
from orthograph.definition import (
    RelationshipModel,
    ConditionalCardinality,
    ConditionalRule,
    PropMatch,
)

class IsInput(RelationshipModel):
    __label__ = "IS_INPUT"
    __source_label__ = "Sample"
    __target_label__ = "Operation"
    __target_cardinality__ = ConditionalCardinality(
        rules=(
            ConditionalRule(
                target=PropMatch({"type": "combine"}),
                spec="2..2",
            ),
            ConditionalRule(
                target=PropMatch({"type": "split"}),
                spec="1..1",
            ),
        ),
        default="0..*",
    )
```

- `source=` fixes a predicate on the **source-label** node (arrow tail).
- `target=` fixes a predicate on the **target-label** node (arrow head).
- `spec=` accepts a UML notation string (see [Cardinality](cardinality.md)) or
  a `CardinalitySpec`.
- `default=` applies to nodes that match no rule.

The convention is **absolute**: `source` always means the declared source-label
node, regardless of whether it is `__source_cardinality__` or
`__target_cardinality__` being evaluated. This eliminates a subtle
"which side is self?" ambiguity — see below.

---

## Both-endpoint partitioning

The validator enforces conditional cardinality by **partitioning** a node's
edges of the relationship type into groups, then checking each group's count
against its resolved bound.

The partition key carries discriminators from **both** endpoints:

```
partition = (self_discriminator_props, other_discriminator_props)
```

This means a rule may discriminate on *either* endpoint's properties — the
counted node's own properties, the opposite node's properties, or both. The
earlier single-axis design only read the *opposite* endpoint's discriminator,
which silently produced wrong results when the counted node was the discriminated
one (e.g. `__target_cardinality__` with `target=PropMatch({"type": "combine"})`
— the validator was reading the property off the *source* node).

The both-endpoint design fixes this structural gap. All existing single-endpoint
rules continue to work unchanged — the `self` component simply does not
subdivide the count when the counted node's own properties are constant across
its edges.

See [ADR-032](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/032-general-conditional-cardinality-partitioning.md)
for the full rationale.

---

## Multi-property partition keys

Each `PropMatch` can carry **multiple** property keys:

```python
ConditionalRule(
    source=PropMatch({"type": "combine", "stage": "final"}),
    target=PropMatch({"role": "internal"}),
    spec="2..5",
)
```

The partition key is the full `{name: value}` map from both sides. This allows
fine-grained sub-partitioning when two properties together determine the allowed
count, and neither alone is sufficient.

The profiler emits **self-describing partition keys** — the observed partition
row carries `{name: value}` maps, not just values — so profile-to-definition
comparison can match observed partitions to declared rules by name, not just
by position.

See [ADR-039](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/039-self-describing-partition-key.md).

---

## Definition-time validation

Unenforceable rules are rejected at `GraphDefinition` construction time —
before any data is validated. A rule is unenforceable if it references a
property key that does not exist on either endpoint. This means a misconfigured
`ConditionalCardinality` is a loud construction error, not a silent data-time
wrong verdict.

---

## Profiling conditional cardinality

When a `GraphProfile` is produced from a live database, the inspector populates
`*_partitioned_cardinality` rows on each relationship type profile. Each row
carries the observed partition key `{name: value}` and the measured count for
that group. The comparison engine matches these observed rows to the declared
rules and checks each count against its resolved bound.

---

## Implementation locations

| Concern | Module |
|---|---|
| `ConditionalCardinality`, `ConditionalRule`, `PropMatch` | `src/orthograph/graph_definition/models.py` |
| Partition machinery | `src/orthograph/graph_definition/validation.py` (`_partition_counts`, `_check_conditional_side`) |
| Definition-time checks | `src/orthograph/graph_definition/cardinality_checks.py` |
| Observed partition models | `src/orthograph/graph_profile/models.py` (`PartitionKey`, `PartitionedCardinalityRow`) |
| ADR-032 (both-endpoint partitioning) | `.agentic/decisions/032-general-conditional-cardinality-partitioning.md` |
| ADR-039 (self-describing partition key) | `.agentic/decisions/039-self-describing-partition-key.md` |
