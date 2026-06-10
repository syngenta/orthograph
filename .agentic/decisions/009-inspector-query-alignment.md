# ADR-009: Inspector Query Alignment and GraphProfile Completeness Parity

**Date:** 2026-06-10
**Status:** Proposed
**Category:** extensions / inspection

## Context

The library proposes a typed query contract (`CypherReadQuery` + `QueryCatalogue` +
`CypherExecutor`) to its consumers, yet runs its **own** introspection queries as raw
f-string Cypher behind a `QueryStrategy` Protocol — and that Protocol only exists for Neo4j.
Memgraph uses an unrelated `MemgraphQueries` class with different method signatures, and
NetworkX has no query layer at all. The library "does not eat its own cooking."

Separately, a completeness audit of `inspect() -> GraphProfile` across the three inspectors
exposed a silent-validation gap: `GraphProfile` fields left empty cause `validate_profile`
to skip checks with no error (the same bug class E18 was created to fix).

| GraphProfile field | NetworkX | Neo4j | Memgraph |
|--------------------|----------|-------|----------|
| property profiles | yes | yes | partial (mandatory-heuristic, count=0) |
| source/target labels | yes | **no** | **no** |
| cardinality_stats | yes | yes | **no** |
| node/rel count | yes | yes | **no** |

For Neo4j this means `INVALID_ENDPOINT` is never emitted; for Memgraph, endpoint, cardinality
and count-based checks are all silently skipped — contradicting PRD User Story 5 ("inspect a
live Memgraph database with the same interface I use for Neo4j").

## Considered Options

- **Leave inspector queries as `QueryStrategy` strings, fix only the empty fields.** Cheapest;
  keeps the eat-own-cooking contradiction and the Neo4j-only Protocol asymmetry.
- **Force a single cross-backend query Protocol over Neo4j + Memgraph.** Rejected: Neo4j
  introspects per-label, Memgraph in bulk — one Protocol would distort one of them.
- **Type the Cypher-backend inspector queries; keep `inspect()->GraphProfile` as the only
  cross-backend contract (CHOSEN).**

## Decision

1. **`inspect() -> GraphProfile` is the only contract shared across all three backends.**
   NetworkX has no Cypher and can never speak a Cypher-query contract; its object-walking
   mechanism stays idiomatic and unchanged. NetworkX is the **completeness reference** — it
   already populates every `GraphProfile` field.

2. **For the two Cypher backends, internal introspection queries become typed
   `CypherReadQuery` subclasses** run through `CypherExecutor`, registered in an internal
   `QueryCatalogue`. Their `Output` types are projection models that `materialize()` into the
   existing `NodeTypeProfile`/`PropertyProfile`/etc. The dynamic label/rel-type is carried as a
   declared identifier parameter per ADR-010. The `GraphProfile` remains the cross-backend
   currency; per-query `Params`/`Output` may differ entirely between Neo4j (per-label) and
   Memgraph (bulk). The `QueryStrategy` Protocol is retired (APOC vs pure-Cypher becomes two
   `CypherReadQuery` subclass sets selected at construction).

3. **Completeness parity.** Neo4j and Memgraph must populate the same `GraphProfile` fields as
   NetworkX wherever the backend's query surface allows — including `source_labels`/
   `target_labels` (the original E18.1 fix, now delivered here as a typed query), cardinality,
   and counts. Metrics genuinely unavailable from a backend's procedures are **documented
   explicitly** so the gap is known, not silent.

## Consequences

- The library uses internally the same typed-query + executor + catalogue pattern it proposes
  to consumers.
- `INVALID_ENDPOINT` and `CARDINALITY_VIOLATION` fire for Neo4j and (where supported) Memgraph,
  closing the silent-skip class of bug for live databases.
- **Scope move:** E18.1 (rel endpoint labels) leaves the "Validation Correctness" epic and is
  delivered here as a typed introspection query; E18 retains only its independent cheap fixes
  (max_degree, Mermaid `<br>`, stacklevel, deprecation shim). This work is the substance of
  E17 STEP 5 (T7/T8), widened to include Memgraph parity.
- **Depends on ADR-010** (declared identifier parameters) and **ADR-008** (`validate_identifier`).
  `Proposed` until ADR-010 is accepted.

## Relates to

- E17 (CypherGenerator hardening — STEP 5 inspector realignment).
- E18 (Validation Correctness — E18.1 reassigned here).
- ADR-010 (declared identifier parameters), ADR-008 (identifier safety), ADR-003 (two-phase
  inspect-then-validate), PRD User Story 5.
