# ADR-030: Per-Pair Observed Cardinality Statistics (Profiling Phase)

**Status:** Accepted (deferred implementation) — 2026-06-18
**Category:** core
**Epic:** E41 (Phase 2 — profiling)
**Depends on:** ADR-029 (conditional cardinality declaration)
**Relates:** ADR-008 (Cypher identifier safety), ADR-009 (inspector query alignment), ADR-015 (declared/observed mirror)

---

## Context

ADR-029 introduces `ConditionalCardinality`: a relationship's cardinality bound
selected by the pair of endpoint discriminator values
`(source.kind, target.kind)`. In-memory validation (E40) enforces it fully
because it sees every node and edge.

The **observed** side cannot, today. `RelationshipTypeProfile.cardinality_stats`
is a single `CardinalityStats(min_degree, max_degree, avg_degree, sample_size)`
**aggregate per relationship type**, produced by a Cypher query that does **not**
group by any property:

```cypher
MATCH (n:`<<label>>`)
OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->()
WITH n, count(r) AS degree
RETURN min(degree) AS min_degree, max(degree) AS max_degree, ...
```

An aggregate `0..N` band cannot distinguish `discard → 0` from `split → 2..*`. So
a conditional spec is **not verifiable** against the current profile. E40 reports
this honestly as `CARDINALITY_UNVERIFIABLE` (INFO) rather than comparing against a
meaningless aggregate (mirrors the existing `QUERY_UNVERIFIABLE` pattern).

This ADR records how live-DB enforcement is delivered **when a pilot needs it**,
and the constraints that keep the change low-risk.

---

## Decision

### 1. Observed statistics gain an optional per-pair breakdown (additive)

`RelationshipTypeProfile` gains an **optional** field:

```python
partitioned_cardinality: dict[PartitionKey, CardinalityStats] | None = None
```

where `PartitionKey` encodes the observed `(source-discriminator-value,
target-discriminator-value)` (serialisable — e.g. a frozen model or a normalised
string key). The existing `cardinality_stats` aggregate is **unchanged and
retained**. This is an **additive optional field**: existing profiles, existing
comparisons, existing visualisation, and the frozen-model contract are all
backward-compatible. Replacing the aggregate is explicitly rejected — it would
ripple through every `GraphProfile` consumer.

### 2. The inspection query groups by both discriminators

The shared cardinality query becomes parameterised by source and target
discriminator property names and groups by them:

```cypher
MATCH (n:`<<label>>`)
OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->(m)
WITH n, n[$source_disc] AS sk, m[$target_disc] AS tk, count(r) AS degree
RETURN sk, tk, min(degree) AS min_degree, max(degree) AS max_degree,
       avg(degree) AS avg_degree, count(n) AS sample_size
```

Standard Cypher — valid on **Neo4j and Memgraph** alike; no APOC required (the
aggregation is pure Cypher, so both Neo4j strategies use it). The
`null`-partition (no edge → `tk = null`) maps to the "zero of that pair" check.

### 3. Discriminator property names are validated identifiers (ADR-008)

`$source_disc` / `$target_disc` are **injected identifiers** (property names), so
they pass the same **validate-and-reject** policy as labels and relationship
types (ADR-008 / `validate_identifier`). A property name failing the policy is
rejected, never spliced.

### 4. Backend parity is mandatory (ADR-009)

The grouped statistic is implemented for **all three** inspectors — Neo4j
(APOC + pure-Cypher strategies), Memgraph, and NetworkX (in-memory grouping in
`_inspect_relationships`) — with parity tests, per ADR-009. NetworkX is the
cheapest and is implemented first as the reference.

### 5. Comparison checks each rule against its observed partition

`CardinalityViolationRule` (`comparison/rules.py`), when the declared side is a
`ConditionalCardinality` **and** `partitioned_cardinality` is present, checks each
declared rule's `spec` against the matching observed partition (and treats an
absent partition as degree `0`). When `partitioned_cardinality` is absent (older
profile, or backend without the grouped query), it falls back to
`CARDINALITY_UNVERIFIABLE` (INFO) — never a false comparison.

**Default floor (mirrors ADR-029 §7).** An observed source/target whose
discriminator value matches **no declared rule** is governed by `default`: its
observed total degree on that side is checked against `default`, so a `min > 0`
default (e.g. `ONE_OR_MORE`) flags a `CARDINALITY_VIOLATION` for an
unmatched-kind node with zero edges. This keeps the live-DB verdict identical to
the in-memory verdict for the same data; without it, the two layers could
disagree on a `min > 0` default. A permissive default (`min == 0`) admits zero
and never trips the floor.

---

## Consequences

- Live-DB drift detection for conditional cardinality becomes possible without
  changing the declaration model (ADR-029 is unaffected).
- The frozen `GraphProfile` contract is **extended, not broken** — the new field
  is optional with a `None` default.
- Cost concentrates in: the grouped query (×3 backends), the new optional field,
  identifier safety for property names, and the comparison branch. This is a
  larger, parity-gated change than E40 and ships **separately**.
- A multi-property discriminator (more than one key per side) multiplies the
  `GROUP BY` columns and the partition-key cardinality. E41 implements the
  single-property `kind` case first; multi-property grouping is a guarded
  follow-on within E41.

---

## Cross-references

- ADR-029: conditional cardinality declaration and the `resolve_for_pair` seam
- ADR-008: Cypher identifier safety (validate-and-reject) — applies to property names here
- ADR-009: inspector query alignment & GraphProfile parity
- ADR-015: declared/observed mirror
- Shared cardinality query: `src/orthograph/graph_profile/queries/shared.py`
- `RelationshipTypeProfile` / `CardinalityStats`: `src/orthograph/graph_profile/models.py`
- Inspectors: `src/orthograph/backends/{neo4j,memgraph,networkx}/`
- E41 epic: `.agentic/planning/active_epics/E41_conditional_cardinality_profiling.md`
