# Advanced: Endpoint-Aware Relationship Identity — Structural Implications

> **Expansion planned for a future release.**
> This page is a scope stub. Full detail on the address-space construction,
> per-shape inspection mechanics, YAML migration, and comparison diagnostics
> changes will be written once the endpoint-identity implementation is fully
> settled.

---

## Scope

This page covers the **structural consequences** of the endpoint-aware
identity model: how replacing bare-label identity with the
`(source_label, rel_label, target_label)` triple reshapes the address space,
the inspection mechanics, the YAML format, and the comparison diagnostics.

It is the algorithmic companion to
[Relationship identity and the endpoint signature](relationship-identity.md),
which describes the authoring surface and the conceptual motivation. This page
goes deeper into *what changes internally* when identity is the full triple
rather than the label alone.

---

## Topics planned for this page

- **Address space construction** — how the comparison engine walks a union of
  `RelTypeKey` strings rather than bare label strings, and why this means a
  declared `Person-KNOWS->Person` and an observed `Person-KNOWS->Company` are
  two different addresses (producing `MISSING_RELATIONSHIP` and
  `UNEXPECTED_RELATIONSHIP`) rather than a single "endpoint mismatch" finding.

- **Per-shape inspection mechanics** — how all three inspectors (NetworkX,
  Neo4j, Memgraph) enumerate relationship types by the full endpoint triple,
  not by bare label. Why this requires endpoint-label discovery queries
  followed by endpoint-filtered pattern scans (`MATCH (n:Source)-[r:REL]->(m:Target)`)
  for each discovered shape, and the round-trip cost of the extra queries.

- **Property-type attachment** — why `observed_types` (which come from
  bulk metadata procedures that aggregate by bare label) can still be attached
  to per-shape profiles without blending counts, and the justification for
  treating stored property type as shape-invariant.

- **Diagnostics reclassification** — how the removal of the endpoint-mismatch
  finding changes the diagnostics contract: the former single `INVALID_ENDPOINT`
  error becomes a `MISSING_*` / `UNEXPECTED_*` pair, and when this is the
  more honest representation.

- **`ENDPOINTS_CHANGED` residual scope** — why the diff signal is retained
  at all, narrowed to the `__directed__` attribute delta (a change in direction
  on the *same* triple), and what it signals in practice.

- **YAML list-form migration** — why `relationship_types:` must be a list
  rather than a mapping when same-label/different-endpoint types coexist, and
  the migration path for existing files.

- **Conditional cardinality nesting** — how per-pair partitioned cardinality
  breakdowns nest *inside* an already endpoint-identified profile, and why
  this avoids double-counting against the enforcement path.

---

## Implementation pointers

| Concern | Module |
|---|---|
| `RelTypeKey` — identity encoding | `src/orthograph/graph_definition/identity.py` |
| Declared side — `_rel_type_map` | `src/orthograph/graph_definition/graph_definition.py` |
| Observed side — `RelationshipTypeProfile` | `src/orthograph/graph_profile/models.py` |
| Comparison address space | `src/orthograph/comparison/views.py` |
| Inspection (all three backends) | `src/orthograph/backends/networkx/inspector.py`, `src/orthograph/backends/neo4j/inspector.py`, `src/orthograph/backends/memgraph/inspector.py` |
| YAML serialization | `src/orthograph/io/yaml.py` |

---

*See [Relationship identity and the endpoint signature](relationship-identity.md)
for the authoring surface and the conceptual motivation, and
[How profiling works](profiling.md) for where per-shape enumeration fits in the
broader inspection algorithm.*
