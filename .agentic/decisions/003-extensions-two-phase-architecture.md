# ADR-003: Extensions Redesign — Two-Phase Architecture

**Date:** 2026-04-14
**Status:** Accepted
**Category:** architecture

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
