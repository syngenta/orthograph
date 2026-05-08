# ADR-001: Core Architecture and Naming Conventions

**Date:** 2026-04-10
**Status:** Accepted
**Category:** architecture

## Context

Initial design session for Orthograph. Established the foundational concepts,
naming conventions, type system, and philosophy that all subsequent decisions
build on.

## Decisions

### Core Concept

- **GraphDataModel** is the single unified concept for representing graph data structure.
- Usable for any purpose: DB schema definition, query result validation, ETL contracts.
- Schema/projection distinction deferred to a later phase.

### Naming

- `NodeModel`: Base class for node type definitions (Pydantic BaseModel subclass)
- `RelationshipModel`: Base class for relationship type definitions
- `GraphDataModel`: Container that holds node types + relationship types + constraints
- `GraphValidator`: Engine that validates data against a GraphDataModel

### Type System

- Native Python types via Pydantic (no string-based type mapping)
- `Optional[T]` for optional properties
- `__optional__` ClassVar for entity-level optionality

### Optionality (3 levels)

1. **Property-level**: `Optional[str] = None` vs required `str`
2. **Entity-level**: `__optional__ = True` on NodeModel/RelationshipModel
3. **Cardinality-level**: `Cardinality.ZERO_OR_MORE` etc. on relationships

### Cardinality

- Named constants backed by min/max: `Cardinality.ONE`, `Cardinality.ZERO_OR_MORE`, etc.
- Custom via `CardinalitySpec(min=2, max=5)`

### Two Input Modes

1. Class-based: Python classes inheriting from NodeModel/RelationshipModel
2. YAML config: For configuration-driven schema definitions

### Backend-Agnostic

- Core validation is DB-independent
- Extensions for Cypher, NetworkX, (future: RDF, GQL)
- Inspired by Pandera's multi-backend approach

### No Backward Compatibility

- Legacy code moved to `src/orthograph_legacy/` and `tests/legacy/`
- Clean start for the new implementation

### Tools Landscape (key gaps filled)

- No existing Pydantic-native graph schema validation tool
- Neomodel: no Pydantic, Neo4j-only, runtime-only cardinality
- Neontology: Pydantic but no cardinality, no graph-wide validation
- Orthograph fills: Pydantic-native, DB-agnostic, cardinality, graph-wide validation
