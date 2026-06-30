# How Profiling Works

**Profiling** is the process of inspecting a live graph database and distilling
its observed structure — node labels, relationship types, property keys, type
distributions, cardinality statistics — into a vendor-free
`GraphProfile` snapshot.

The result is a pure Python value object. It carries no database connection and
makes no further queries. Once produced, a profile can be compared against a
`GraphDefinition` (see [Comparison](comparison.md)), serialised, archived, or
diff-ed against an earlier snapshot.

This is why profiling matters: the declared contract lives in Python or YAML;
the database evolves independently. Profiling is the bridge that makes the two
artefacts comparable without coupling them at runtime.

→ **Tutorial:** {ref}`Pillar 5 — Profiling & comparison <profiling-comparison>`
  starts with {doc}`../notebooks/05.01_introducing_the_graph_profile`
  and walks through a full inspect → compare cycle.

---

## The declared / observed mirror

Profiling is one side of the declared/observed mirror established by
[ADR-015](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/015-declared-observed-mirror.md).
The two artefacts — `GraphDefinition` (declared) and `GraphProfile` (observed)
— are produced independently. Neither inherits from the other; neither is
validated against the other at construction time. They meet only in the
comparison engine.

This separation is intentional: it means inspection can run against *any*
backend without the declared contract leaking into the measurement, and
comparison can be replayed offline against archived profiles without a live
database.

---

## Algorithmic overview

> **Placeholder** — this section will be expanded with full algorithmic detail
> in the E61 documentation phase. The outline below describes the high-level
> procedure; refer to the source modules and the linked ADRs for the current
> implementation.

### Step 1 — Strategy selection

The inspector selects a measurement strategy based on what extensions are
available in the target database:

- **Neo4j** — three strategies in descending capability order: APOC
  (`apoc.meta.*`), SCHEMA (`db.schema.*`), CYPHER (plain aggregate queries).
  The inspector probes availability at startup and falls back automatically.
  See [ADR-033](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/033-neo4j-db-schema-inspection-strategy.md)
  and `src/orthograph/backends/neo4j/` for the per-strategy query sets.
- **NetworkX** — reads the in-memory graph directly; no external queries.
  This is the reference implementation.
- **Memgraph / GQLAlchemy** — SCHEMA + CYPHER strategies (no APOC).

### Step 2 — Node type enumeration and counting

For each distinct node label in the database, the inspector records:

- `total_count` — total nodes with that label.
- `present_count` (per property) — nodes that have a given property key set.
- `value_distribution` / `observed_type_counts` — sampled value histograms
  and DB-reported type information, controlled by the `value_counts_top_n`
  knob (see [ADR-035](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/035-observed-type-counts-population.md)).

### Step 3 — Relationship type enumeration by triple

Relationship types are enumerated by the full endpoint triple
`(source_label, rel_label, target_label)`, not by bare label. This is the
endpoint-aware identity model (ADR-037; see also
[Relationship identity](relationship-identity.md)).

For each `RelTypeKey` triple the inspector records:

- Per-shape `count` and cardinality statistics, derived from an endpoint-filtered
  `MATCH (n:Source)-[r:REL]->(m:Target)` pattern scan — never from an
  unfiltered label aggregate, which would blend distinct shapes.
- Property presence counts and value distributions per shape.
- Partitioned cardinality breakdowns when conditional cardinality is expected
  (see [Conditional cardinality](conditional-cardinality.md)).

> **APOC correction** — APOC's `apoc.meta.*` aggregates by bare relationship
> label and underestimates `present_count`. Per-shape counts are always
> produced by dedicated `count()` queries even on the APOC path.
> See [ADR-036](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/036-apoc-no-scan-present-count-correction.md).

### Step 4 — Assembly into `GraphProfile`

The per-type measurements are assembled into:

- `GraphProfile.node_type_profiles` — `dict[str, NodeTypeProfile]`, keyed by
  label string.
- `GraphProfile.rel_type_profiles` — `dict[str, RelationshipTypeProfile]`,
  keyed by `str(RelTypeKey)` (`"Source:REL:Target"`).

The profile is a frozen snapshot; it carries no backend reference.

---

## Public entry points

```python
from orthograph.profile import inspect_neo4j, inspect_networkx, inspect_memgraph
```

All three return a `GraphProfile`. Parameters follow a common pattern:
a connection / driver argument, an optional `InspectionConfig`, and optional
`value_counts_top_n` to control the depth of value-distribution sampling.

See the [Reference](../reference/index.md) for the full signatures, and
[ADR-034](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/034-graphprofile-statistical-model-and-comparison-contract.md)
for the statistical model and comparison contract.

---

## Implementation locations

| Concern | Module |
|---|---|
| Inspector ABC + shared base | `src/orthograph/graph_profile/inspection.py` |
| `GraphProfile` models | `src/orthograph/graph_profile/models.py` |
| Neo4j inspector + strategies | `src/orthograph/backends/neo4j/` |
| NetworkX inspector | `src/orthograph/backends/networkx/` |
| Memgraph inspector | `src/orthograph/backends/memgraph/` |
| Public entry points | `src/orthograph/profile.py` |
