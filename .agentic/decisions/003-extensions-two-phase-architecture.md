# ADR-003: Extensions Redesign — Two-Phase Architecture

**Date:** 2026-04-14
**Status:** Accepted
**Category:** architecture

> **Forward note (ADR-017, 2026-06-12).** The package layout described here is
> historical. The two-phase split (inspect → validate) still holds as a concept,
> but the *files* moved: `validate_profile` is renamed `compare` in
> `comparison/engine.py`, the observed `GraphProfile` lives in
> `graph_profile/`, and `validate_query_catalogue` lives in `cypher/`. See
> ADR-017's path-translation table. This record is not rewritten.

## Context

The original extensions (flat files: `introspector.py`, `adapter.py`, `_neo4j_common.py`)
mixed inspection logic with validation logic. Each backend produced `IntrospectedSchema`
dataclasses that were compared via `compare_schema()`. This was functional but:

- No shared interface (no ABC) across backends
- `IntrospectedSchema` was a plain dataclass, not serialisable or injectable
- Validation was tightly coupled to introspection (no way to inject external profiles)
- No property completeness metrics, no cardinality stats populated
- Duplicated logic across Neo4j/Memgraph introspectors

## Decision: Two-Phase Architecture (Inspect, then Validate)

Inspired by Soda Core (inspect-then-check) and SHACL (shapes graph vs. data graph):

- **Phase 1: Inspection** — `GraphInspector` ABC with `inspect() -> GraphProfile`.
  Three implementations: `NetworkxInspector`, `Neo4jInspector`, `MemgraphInspector`.
- **Phase 2: Validation** — `validate_profile(profile, model) -> ValidationResult`.
  The validator never touches the backend. Profiles are injectable, serialisable.

## `GraphProfile` as Shared Currency

A frozen Pydantic model with `NodeTypeProfile`, `RelationshipTypeProfile`,
`PropertyProfile` (with `completeness`, `observed_types`, `is_mandatory`),
`CardinalityStats`, and `ConstraintInfo`. Replaces the old `IntrospectedSchema`
dataclass. Richer data: counts, completeness, observed endpoint labels.

## `QueryStrategy` Protocol (Neo4j)

Extensible strategy for Neo4j query generation. `ApocQueryStrategy` uses APOC
procedures; `CypherQueryStrategy` uses pure Cypher. Auto-detected, user-overridable.

## Module Naming

No underscore-prefixed modules. Clear names: `models.py` (not `_base.py`),
`queries.py` (not `_queries.py`), `validation.py` (not `_validation.py`).

## Visualization Moved to Extensions (Temporary)

`depiction.py` moved to `extensions/visualization/mermaid.py`. Clean break,
no backward-compatible shim. All import sites updated.
*(Note: visualization was subsequently moved to a top-level package — see ADR-004.)*

## `schema_to_networkx()` Kept in `networkx/conversion.py`

Useful utility for future converters. Prepares for a conversion extension
that can reshape data between formats.

---

## Superseded paths (E25 / ADR-011, 2026-06-11)

The two-phase inspect-then-validate architecture itself stands. Only the *locations*
and the inspector ABC *signature* changed in the E25 backend-isolation refactor:

- `extensions/` package → split into `backends/<vendor>/` (vendor adapters), `profile/`
  (vendor-free inspection currency: `GraphProfile` models, `validate_profile`,
  `GraphInspector`/`CypherInspector`), and `cypher/` (top-level language tool).
- `GraphInspector.inspect(self)` → `inspect(self, connection)` — connection injected
  per call, never stored.
- The `QueryStrategy` Protocol described above is **retired** (see ADR-009 §8): APOC vs
  pure-Cypher is now two typed `CypherReadQuery` subclass sets selected at construction.
- `extensions/visualization/` already moved to top-level `visualization/` (ADR-004).

See ADR-011 for the full E25 decision record.
