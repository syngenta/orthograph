# Orthograph — Product Requirements Document

---

## Problem & Vision

**Problem:** Implicit, scattered schema definition across multiple entry points
to the same graph database or datapackage. When several applications or query
paths write to and read from the same graph without a shared schema declaration,
data drifts silently.

**Vision:** Orthograph provides a single place where the schema can live. It is a
**Pydantic-native graph data model definition and validation library** that is
vendor-agnostic, runtime-configurable, and usable for validation at every layer:
data, queries, results, and ORM interactions.

Orthograph allows any application to own the **data model layer** in a three-layer stack:

```
Ontology        (what entities and relationships exist in this domain)
     ↓
Data Model      ← ORTHOGRAPH (declares the schema in Python or YAML)
     ↓
Schema          (what the database or datapackage enforces: indexes, constraints)
```

Orthograph does not manage ontologies or database schemas directly. It consumes
ontological intent from above and produces schema artefacts (constraints, validated
queries) for the layers below.

### Solution Architecture

Every validation flow follows the same two-phase pattern:

```
Phase 1: INSPECTION                       Phase 2: VALIDATION
GraphInspector.inspect()  ──►  GraphProfile  +  GraphDataModel  ──►  ValidationResult
```

Phase 1 is backend-specific (each inspector knows how to talk to its database).
Phase 2 is backend-agnostic (the validator compares a profile against a model, never touches a database).

---

## Users

**Primary:** Software engineers building tools that interact with graph/network
data — graph databases (Neo4j, Memgraph), datapackages (NetworkX), or Cypher queries.

**Secondary (reached through the tool):** Data engineers and ML engineers who
want to validate their data or queries against a declared schema. They use Orthograph
indirectly via the tools the primary user builds.

---

## Design Principles

1. **Minimise consumer code.** Reduce the amount of code a consuming application
   needs to interact with graph data safely. Prefer declarative configuration
   over imperative wiring. Prefer validated dispatch over inline query strings.

---

## Constraints

Non-negotiable boundaries. Any work that violates these must be flagged before execution.

1. **DB-agnostic in core.** No database-specific logic in `core/`. Extensions exist for that.
2. **Models are the single source of truth.** GQLAlchemy classes, Cypher queries, constraints — all derived from `NodeModel`/`RelationshipModel`, never the reverse.
3. **Not an ORM.** Validates and generates — does not manage connections, transactions, object lifecycle, or data orchestration. Extensions may wrap ORMs as thin validated wrappers, but core never does.
4. **Not a migration tool.** Detects drift, does not apply changes to databases.
5. **Not a query optimizer.** Validates and generates queries — does not optimize execution plans, cache results, or manage connection pools.
6. **No knowledge about consuming projects.** Orthograph is a library, not a platform. Migration plans, project-specific configurations, and team workflows belong in those projects.
7. **YAML sufficient for the common case.** A consuming application can define schema and query catalogue in YAML alone, without Python class definitions.
8. **Runtime configurability over compile-time rigidity.** External YAML, dynamic class generation, runtime validation preferred over patterns requiring code changes for schema updates.
9. **Two input modes always.** Class-based (Python) and config-based (YAML). Neither deprecated. Both first-class.
10. **Extensions are isolated.** Importing one extension never pulls in dependencies of another. Each independently installable.
11. **Tests are the specification.** Any feature without tests is not done.

---

## Capabilities

### `core/` — Schema Definition and Data Validation

Declare what your graph data should look like and validate actual data against that declaration.

- **NodeModel / RelationshipModel** — Pydantic BaseModel subclasses declaring node and relationship types with typed properties, cardinality, and optionality
- **GraphDataModel** — Container holding all node and relationship types as a unified schema
- **GraphValidator** — Validates graph data against a GraphDataModel: labels, property types, required fields, referential integrity, cardinality

### `io/` — Schema Configuration

Load and save schemas from/to external YAML files. Enables runtime configuration without code changes.

### `extensions/` — Database Inspection and Interaction

Connect to graph databases and in-memory graphs to inspect what is actually there, validate against your schema, and interact through validated operations.

- **Cypher** — query generation from schema and static query validation
- **Neo4j** — live database inspection (APOC + fallback), query result validation
- **Memgraph** — live database inspection (Bolt protocol, schema procedures)
- **NetworkX** — in-memory graph inspection, schema-to-graph conversion
- **GQLAlchemy** — OGM integration: codegen from schema, validated client, query builder bridge

### `visualization/` — Human-Readable Output

Render schemas, inspection profiles, and validation results for human consumption — Mermaid diagrams, text tables, Jupyter notebook display.
