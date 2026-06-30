# Explanation

Deep dive into Orthograph's design and concepts.
These pages explain *why* the library is shaped the way it is, how its internals
work, and what the non-obvious design decisions mean in practice.
They are cross-referenced from the tutorials and how-to guides wherever a concept
needs more than a one-line introduction.

---

## Architecture

```{toctree}
:maxdepth: 1

architecture
the-three-layer-stack
```

- **[Architecture overview](architecture.md)** — the three-layer stack, the seven
  public modules, the one-place re-export pattern, and a map of every internal
  subpackage and its responsibility.
- **[The three-layer stack](the-three-layer-stack.md)** — the governance
  positioning: ontology → graph definition → database schema, and how Orthograph
  detects drift in both directions around the declared contract.

---

## Core concepts

```{toctree}
:maxdepth: 1

relationship-identity
cardinality
conditional-cardinality
```

- **[Relationship identity](relationship-identity.md)** — why a relationship type
  is identified by `(source_label, rel_label, target_label)`, not just its label;
  the `RelTypeKey` encoding; multi-shape declarations.
- **[Cardinality and optionality](cardinality.md)** — the two-axes model, the
  UML notation grammar, `CardinalitySpec`, and the difference between existence
  and optionality.
- **[Conditional cardinality](conditional-cardinality.md)** — property-based
  partitioning, both-endpoint rule conventions, multi-property partition keys,
  and definition-time enforcement guards.

---

## Algorithms

```{toctree}
:maxdepth: 1

profiling
comparison
query-validation
```

- **[How profiling works](profiling.md)** — strategy selection, node and
  relationship enumeration, per-shape statistics, and the declared/observed
  mirror.
- **[How comparison works](comparison.md)** — address space construction,
  presence pass, satisfaction rules, diff rules, and result assembly.
- **[How query validation works](query-validation.md)** — the 2 × 2
  phase × grade surface, syntax checking, semantic label/property/endpoint
  validation, and catalogue governance.

---

## Query authoring and execution

```{toctree}
:maxdepth: 1

query-management
execution
```

- **[Query management](query-management.md)** — `CypherQuery` (simple path)
  vs typed query contracts; the catalogue; Cypher template language.
- **[Execution](execution.md)** — the two executor paths, sync and async
  flavours, caller-owned transactions, and choosing the right verb.

---

## Advanced topics

> These pages are scope stubs — full content is planned for expansion after
> the current release round. Each names its topic and points at the relevant
> implementation modules.

```{toctree}
:maxdepth: 1

advanced-conditional-cardinality-partitioning
advanced-neo4j-inspection-strategies
advanced-endpoint-aware-relationship-identity
```

- **[Conditional cardinality — partition enforcement algorithm](advanced-conditional-cardinality-partitioning.md)**
  — the internal enforcement walk, partition-key construction, rule-resolution
  order, and multi-property generalisation.
- **[Neo4j inspection strategies](advanced-neo4j-inspection-strategies.md)**
  — the APOC / SCHEMA / CYPHER trade-off matrix, auto-detection precedence,
  and the `strategy` selector.
- **[Endpoint-aware relationship identity — structural implications](advanced-endpoint-aware-relationship-identity.md)**
  — address-space construction, per-shape inspection mechanics, YAML list-form
  migration, and diagnostics reclassification.
