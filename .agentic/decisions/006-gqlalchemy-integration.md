# ADR-006: GQLAlchemy Integration as Optional Extension

**Date:** 2026-04-17
**Status:** Accepted
**Category:** extensions

## Problem

Orthograph defines graph schemas and validates data, but has no OGM (object
persistence/retrieval) and no general-purpose query builder. Users who need
both strict schema governance and database interaction must manually wire
Orthograph validation around a separate database client. GQLAlchemy provides
a mature OGM and fluent query builder for Memgraph and Neo4j but lacks
schema validation, cardinality constraints, endpoint enforcement, and Cypher
static analysis.

## Decision: GQLAlchemy as an Optional Orthograph Extension

GQLAlchemy is added as an **optional dependency** and exposed through a new
extension module `orthograph.extensions.gqlalchemy`. This follows the same
pattern as the existing `neo4j`, `memgraph`, and `networkx` extensions.

### Key Architectural Choices

1. **Only Orthograph is modified.** GQLAlchemy is treated as an external
   dependency. No fork, no patches.

2. **Orthograph models are the single source of truth.** Users define
   `NodeModel` / `RelationshipModel` classes. GQLAlchemy `Node` / `Relationship`
   classes are auto-generated at runtime via `codegen.py`. Users never define
   or import GQLAlchemy model classes directly.

3. **Extension module, not deep wrapping.** The integration lives in
   `orthograph.extensions.gqlalchemy/` and is only imported when needed.
   Core Orthograph has zero awareness of GQLAlchemy.

4. **Bridge via plain dicts.** Orthograph (Pydantic v2) and GQLAlchemy
   (Pydantic v1) model hierarchies cannot share a base class. All data
   exchange happens through plain Python dicts. The codegen layer translates
   Orthograph model metadata into GQLAlchemy class definitions. The result
   adapter layer converts GQLAlchemy objects back into validation dicts.

5. **Schema features Orthograph has but GQLAlchemy lacks** (cardinality,
   endpoint types, directed/undirected, entity optionality) are enforced
   by Orthograph's validation layer, not by the generated GQLAlchemy classes.

6. **Both Memgraph and Neo4j** are supported via GQLAlchemy's vendor
   abstraction (`Memgraph` and `Neo4j` classes both implement `DatabaseClient`).

## Deferred Decisions

| Decision | Status | Notes |
|---|---|---|
| Cardinality enforcement on write | Deferred | Requires pre-save DB query for current count. Performance cost unclear. Can be added as opt-in `enforce_cardinality=True` later. |
| Result validation default | Decided: opt-in | `validate_results=False` by default on `execute_validated()`. Activated with `validate_results=True`. |
| Index/constraint auto-creation | Deferred | Not implemented in first version. Users use `CypherGenerator.generate_constraints()` or GQLAlchemy's `Field(unique=True, db=db)` directly. |

## Tradeoffs Accepted

| Tradeoff | Accepted cost | Benefit |
|---|---|---|
| Dynamic class generation via `type()` | Harder to debug, no IDE autocomplete on generated classes | Users never see generated classes; they use Orthograph models |
| Pydantic v1/v2 coexistence | Runtime complexity, potential subtle bugs | No fork of GQLAlchemy needed; clean separation |
| Schema features enforced outside GQLAlchemy | GQLAlchemy's own validation is bypassed/redundant | Orthograph's richer validation is always the authority |
| GQLAlchemy's `Extra.allow` on models | Generated classes accept undeclared properties | Orthograph validates BEFORE save; extra props are caught |
| No re-implementation of query builder | Users must import `gqlalchemy.match/create/merge` | Full access to GQLAlchemy's query builder; no maintenance burden |

## Alternatives Considered

1. **Fork GQLAlchemy and add Pydantic v2 + validation** — Rejected.
   Maintenance burden of a fork. GQLAlchemy's OGM design is fundamentally
   different from Orthograph's schema-first approach.

2. **Build OGM from scratch in Orthograph** — Rejected for now. Large
   effort. GQLAlchemy already handles connection management, Cypher
   generation, result deserialization, and multi-vendor support.

3. **Use Neomodel instead of GQLAlchemy** — Rejected. Neomodel is Neo4j-only,
   not Pydantic-based, and has a heavier ORM abstraction that conflicts with
   Orthograph's schema-first philosophy.

4. **Lightweight bridge (users wire both libraries manually)** — Rejected
   in favor of extension module. A bridge requires users to understand both
   APIs and handle conversion themselves. The extension provides a cohesive
   experience.

5. **Deep wrapping (hide GQLAlchemy completely)** — Rejected. Would require
   re-implementing the query builder API surface. The extension module exposes
   GQLAlchemy's query builder directly and adds validation on top.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pydantic v1/v2 conflict | Low | High | Both coexist since Pydantic 2.0. Test in CI. |
| GQLAlchemy API changes | Medium | Medium | Pin `>= 1.6, < 2.0`. All imports behind extension boundary. |
| `pymgclient` build issues | Medium | Medium | Only needed for Memgraph. Document clearly. |
| Dynamic class generation breaks | Low | Medium | Comprehensive codegen tests. |

## References

- Target behavior notebook: `notebooks/03.03_gqlalchemy_integration.ipynb`

---

## Superseded paths (E25 / ADR-011, 2026-06-11)

The integration design (optional dependency, models as source of truth, dict bridge,
validation outside GQLAlchemy) is unchanged. Only the module *location* moved:

- `orthograph.extensions.gqlalchemy` → `orthograph.backends.gqlalchemy` (vendor-isolated
  backend folder).
- The "Explicit `backend=` parameter for GqlAlchemyClient" decision (ADR-007) is realised:
  `GqlAlchemyClient` no longer dispatches inspectors by class-name string match and no
  longer silently swallows a missing-Cypher `ImportError` (it routes through
  `orthograph.dependencies.require`). See E25.S2 and ADR-011.

See ADR-011 for the full E25 decision record.
