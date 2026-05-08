# Orthograph — Product Requirements Document

---

## Problem Statement

Implicit, scattered schema definition across multiple entry points to the same
graph database or datapackage. When several applications or query paths write to
and read from the same graph without a shared schema declaration, data drifts
silently. Queries are hardcoded without validation, results are consumed without
type checking, and there is no single authority on what the graph should contain.

The Python ecosystem has strong schema validation for structured data — Pydantic
for record-shaped objects, Pandera for DataFrames — but no equivalent exists for
graph data and networks. Orthograph fills this gap.

---

## Vision

Orthograph provides a single place where the graph schema can live. It is a
**Pydantic-native graph data model definition, validation, and query governance
library** that is vendor-agnostic, runtime-configurable, and usable for
validation at every layer: data, queries, results, and ORM interactions.

Orthograph allows any application to own the **data model layer** in a
three-layer stack:

```
Ontology        (what entities and relationships exist in this domain)
     ↓           consumed informally — domain experts inform schema decisions
Data Model      ← ORTHOGRAPH (declares the schema in Python or YAML)
     ↓
Schema          (what the database or datapackage enforces: indexes, constraints)
```

Orthograph does not manage ontologies or database schemas directly. It encodes
ontological intent received from domain experts and produces schema artefacts
(constraints, validated queries, type-safe catalogues) for the layers below.

Machine-readable ontology import (OWL/RDF) is not planned unless a concrete use
case emerges. The ontology layer describes Orthograph's position in a stack, not
a runtime integration.

---

## Solution

Orthograph is a **library** (not a platform) that provides:

1. **Interfaces and containers** — ABCs, Protocols, registries, base models
2. **Validation logic** — schema validation, query validation, result validation, profile comparison
3. **Generation utilities** — auto-generated CRUD queries, GQLAlchemy class codegen, constraint DDL

Consuming projects provide:

1. **Actual data models** — concrete NodeModel/RelationshipModel subclasses or YAML definitions
2. **Actual queries** — Cypher strings or GQLAlchemy builder expressions
3. **Actual catalogue content** — populated query registries
4. **Database connections** — drivers, sessions, passed to Orthograph methods as arguments
5. **Orchestration** — when to validate, when to query, transaction management

**Orthograph never owns a database connection.** When it needs one (to inspect,
validate results, or execute a validated query), the connection is passed in by
the caller.

### Solution Architecture

Two distinct validation capabilities:

```
CAPABILITY 1: DATA VALIDATION
"Here is data I have in hand — validate it against my declared schema."
GraphValidator.validate(data, model) ──► ValidationResult

CAPABILITY 2: DATABASE PROFILING & INSPECTION
"Connect to a live database, profile its structure, compare against expectations."
GraphInspector.inspect(connection) ──► GraphProfile
validate_profile(profile, model)   ──► ValidationResult
```

Data Validation operates on in-memory records (pre-write or post-read).
Database Profiling & Inspection performs point-in-time structural analysis:
type distributions, completeness statistics, cardinality measurements, drift
detection, and consistency checks. Inspired by SODA for data quality.

---

## Users

**Primary:** Software engineers building tools that interact with graph/network
data — graph databases (Neo4j, Memgraph), datapackages (NetworkX), or Cypher
queries.

**Secondary (reached through the tool):** Data engineers and ML engineers who
want to validate their data or queries against a declared schema. They use
Orthograph indirectly via the tools the primary user builds.

---

## User Stories

1. As a backend engineer, I want to define my graph schema in YAML so that I can declare node types, relationship types, and their properties without writing Python classes.
2. As a backend engineer, I want to define my graph schema in Python (Pydantic models) so that I get IDE autocomplete and type checking during development.
3. As a backend engineer, I want to validate in-memory graph data against my schema before writing to the database, so that invalid data never reaches persistence.
4. As a backend engineer, I want to inspect a live Neo4j database and compare it against my declared schema, so that I can detect silent drift introduced by other applications.
5. As a backend engineer, I want to inspect a live Memgraph database with the same interface I use for Neo4j, so that I don't learn two different profiling APIs.
6. As a backend engineer, I want to inspect a NetworkX graph in-memory against my schema, so that I can validate prototypes and test data without a live database.
7. As a backend engineer, I want database profiling to include property completeness statistics, type distributions, and cardinality measurements, so that I can assess data quality beyond binary pass/fail.
8. As a backend engineer, I want to define a catalogue of named Cypher queries with declared parameters and expected result types, so that every query in my application is schema-validated.
9. As a backend engineer, I want auto-generated CRUD queries for basic operations (get-by-id, merge, delete) derived from my schema, so that I don't handwrite boilerplate Cypher.
10. As a backend engineer, I want to validate Cypher query structure statically against my schema (labels, relationship types, property accesses, endpoints), so that I catch schema violations before runtime.
11. As a backend engineer, I want to validate query results at runtime against declared output types, so that I catch unexpected result shapes immediately.
12. As a backend engineer, I want to register queries in my catalogue at runtime from Python, so that dynamically constructed queries can participate in validation.
13. As a backend engineer, I want to load my query catalogue from a YAML file, so that query definitions live alongside schema definitions in configuration.
14. As a backend engineer, I want to define a GQLAlchemy query catalogue with parameterised builder expressions and result type declarations, so that ORM queries get the same validation treatment as raw Cypher.
15. As a backend engineer, I want Orthograph to generate GQLAlchemy Node/Relationship classes from my schema, so that I never manually synchronise OGM classes with my data model.
16. As a backend engineer, I want to validate GQLAlchemy query builder output against my schema, so that fluent queries are checked before execution.
17. As a backend engineer, I want to visualise my schema as a Mermaid diagram, so that I can include it in documentation.
18. As a backend engineer, I want to render inspection profiles and validation results as text tables, so that I can read them in a terminal or notebook.
19. As a data engineer, I want to receive a ValidationResult with categorised issues (errors, warnings, info) when profiling a database, so that I can triage problems by severity.
20. As a backend engineer, I want to adopt Orthograph with only YAML configuration and no custom Python, so that I minimise onboarding effort.
21. As a backend engineer, I want to own my database connections and pass them to Orthograph methods, so that I control connection pooling, transaction boundaries, and lifecycle.
22. As a backend engineer, I want Orthograph extensions to be independently installable, so that I only pull in dependencies for the backends I use.

---

## Design Principles

1. **Minimise consumer code.** Reduce the amount of code a consuming application
   needs to interact with graph data safely. Prefer declarative configuration
   over imperative wiring. Prefer validated dispatch over inline query strings.

2. **Interfaces over orchestration.** Orthograph declares contracts (ABCs,
   Protocols, registries) and implements validation. Consuming projects provide
   content, connections, and orchestration. The library never makes decisions
   about when or how to persist.

3. **Validated composition.** When Orthograph integrates with ORMs (GQLAlchemy),
   it generates compatible data structures and decorates query paths with
   validation. The consuming project composes these into its own persistence
   flow — Orthograph does not own the persistence call.

---

## Constraints

Non-negotiable boundaries. Any work that violates these must be flagged before
execution.

1. **DB-agnostic in core.** No database-specific logic in `core/`. Extensions exist for that.
2. **Models are the single source of truth.** GQLAlchemy classes, Cypher queries, constraints — all derived from `NodeModel`/`RelationshipModel`, never the reverse.
3. **Not an ORM.** Validates and generates — does not manage connections, transactions, object lifecycle, or data orchestration. Extensions may generate ORM-compatible classes and validate ORM query output, but never own the persistence call.
4. **Not a migration tool.** Detects drift, does not apply changes to databases.
5. **Not a query optimizer.** Validates and generates queries — does not optimize execution plans, cache results, or manage connection pools.
6. **Not a monitoring platform.** Produces point-in-time profiles and comparisons. Historical storage, trend analysis, scheduling, and alerting belong in consuming infrastructure.
7. **No knowledge about consuming projects.** Orthograph is a library, not a platform. Migration plans, project-specific configurations, and team workflows belong in those projects.
8. **YAML sufficient for the common case.** A consuming application can define schema and Cypher query catalogue in YAML alone, without Python class definitions.
9. **Runtime configurability over compile-time rigidity.** External YAML, dynamic class generation, runtime validation preferred over patterns requiring code changes for schema updates.
10. **Two input modes where applicable.** Class-based (Python) and config-based (YAML) for schema definitions and Cypher query catalogues. Python-only for GQLAlchemy query catalogues (builder expressions are inherently code).
11. **Extensions are isolated.** Importing one extension never pulls in dependencies of another. Each independently installable.
12. **Tests are the specification.** Any feature without tests is not done.
13. **Connections are never owned.** Database drivers and sessions are passed in by the caller. Orthograph never stores, pools, or manages connection lifecycle as instance state.

---

## Capabilities

### `core/` — Schema Definition and Data Validation

Declare what your graph data should look like and validate actual data against
that declaration.

- **[NodeModel](../../src/orthograph/core/node_model.py) / [RelationshipModel](../../src/orthograph/core/relationship_model.py)** — Pydantic BaseModel subclasses declaring node and relationship types with typed properties, cardinality, and optionality
- **[GraphDataModel](../../src/orthograph/core/graph_data_model.py)** — Container holding all node and relationship types as a unified schema; validates structural consistency at construction
- **[GraphValidator](../../src/orthograph/core/validator.py)** — Validates in-memory graph data against a GraphDataModel: labels, property types, required fields, referential integrity, cardinality, entity presence

### `io/` — Schema and Catalogue Configuration

Load and save schemas and query catalogues from/to external YAML files. Enables
runtime configuration without code changes.

- **[Schema YAML](../../src/orthograph/io/yaml.py)** — bidirectional serialisation of GraphDataModel (node types, relationship types, properties, cardinality)
- **Cypher Catalogue YAML** — load named parameterised queries with declared parameter types and expected result types *(not yet implemented)*

### `extensions/` — Database Profiling, Query Governance, and ORM Integration

#### Database Profiling & Inspection

Point-in-time structural analysis of live databases and in-memory graphs.

- **[GraphInspector ABC](../../src/orthograph/extensions/base.py)** — common interface: `inspect(connection) -> GraphProfile`
- **[Neo4j Inspector](../../src/orthograph/extensions/neo4j/inspector.py)** — live inspection via APOC + pure Cypher fallback strategy
- **[Memgraph Inspector](../../src/orthograph/extensions/memgraph/inspector.py)** — live inspection via Memgraph schema procedures
- **[NetworkX Inspector](../../src/orthograph/extensions/networkx/inspector.py)** — in-memory graph profiling
- **[GraphProfile](../../src/orthograph/extensions/models.py)** — frozen Pydantic model: node/relationship type profiles, property completeness, cardinality statistics, constraints, metadata
- **[validate_profile()](../../src/orthograph/extensions/validation.py)** — compares a GraphProfile against a GraphDataModel, returns categorised ValidationResult
- Inspired by [SODA](https://soda.io/) for data quality assessment — point-in-time profiling, not a monitoring platform

#### Query Governance — Cypher

Static validation and generation of Cypher queries.

- **[CypherParser / validate_cypher()](../../src/orthograph/extensions/cypher/parser.py)** — parse Cypher AST (via graphglot), validate labels, relationship types, property accesses, and endpoints against a schema
- **[CypherGenerator](../../src/orthograph/extensions/cypher/generator.py)** — generate MERGE/CREATE/MATCH/constraint statements from schema
- **CypherQueryCatalogue** — registry of named, parameterised Cypher queries with declared parameter types and expected result types; loadable from YAML or populated at runtime; validates queries at registration and results at execution *(not yet implemented)*

#### Query Governance — GQLAlchemy

Validated composition with the GQLAlchemy ORM. Python-only.

- **[Codegen](../../src/orthograph/extensions/gqlalchemy/codegen.py)** — auto-generate GQLAlchemy Node/Relationship classes from Orthograph models
- **[ValidatedQueryBuilder](../../src/orthograph/extensions/gqlalchemy/query_builder.py)** — decorates GQLAlchemy's fluent query builder with Orthograph schema validation
- **GQLAlchemy Query Catalogue** — registry of named builder expressions with declared parameter types and expected result types; populated at runtime from Python; validates queries at registration and results at execution *(not yet implemented)*
- **[Result Adapter](../../src/orthograph/extensions/gqlalchemy/result_adapter.py)** — converts GQLAlchemy objects to Orthograph validation dicts

#### Auto-Generated Operations

Standard CRUD and janitor operations derived from the schema, available in both
Cypher and GQLAlchemy forms:

- Get by UID
- Merge (upsert)
- Create
- Delete
- Match by label
- Uniqueness constraint DDL

### `visualization/` — Human-Readable Output

Render schemas, inspection profiles, and validation results for human
consumption.

- **[Mermaid](../../src/orthograph/visualization/mermaid.py)** — graph diagrams with properties, cardinality labels, directed/undirected arrows
- **[Text](../../src/orthograph/visualization/text.py)** — plain text tables for terminal and notebook display
- **Jupyter integration** — inline rendering via mermaid.ink

---

## Implementation Decisions

1. **Two distinct validation engines.** `GraphValidator` (core) validates raw in-memory data records. `validate_profile()` (extensions) validates aggregated database profiles. These serve different use cases and remain separate.

2. **Query Catalogue as registry pattern.** Both Cypher and GQLAlchemy catalogues share a common registry interface (register, lookup, validate, execute-with-validation) but differ in serialisation: Cypher supports YAML + Python; GQLAlchemy is Python-only.

3. **Result type declarations start simple.** Output models are initially flat maps of `field_name: type` for projections. References to existing NodeModel/RelationshipModel types for node-shaped results. Rich output models (nested, computed) are a future evolution.

4. **GQLAlchemy extension is validated composition, not a persistence layer.** Orthograph generates GQLAlchemy classes (codegen), validates queries (query builder), and validates results (result adapter). The consuming project calls GQLAlchemy persistence methods directly. The current [`GqlAlchemyClient.save_*`](../../src/orthograph/extensions/gqlalchemy/client.py) pattern should be reviewed and potentially removed in favour of the composition approach.

5. **Connections passed per-call.** Extension methods accept database connections as arguments. No extension stores a connection as instance state. This ensures consuming projects retain full control of connection lifecycle.

6. **Extension isolation enforced via optional dependency groups.** Each extension has its own pip extra. The Cypher extension is user-facing (query validation/generation) and is not a dependency of other extensions — Neo4j/Memgraph write their own Cypher strings internally.

---

## Testing Decisions

- **External behaviour only.** Tests validate inputs and outputs of public interfaces, not internal implementation details.
- **All capabilities tested.** Core models, validators, YAML IO, each extension (inspectors with mocked drivers, result adapters, Cypher parser/generator, GQLAlchemy codegen/client/builder), visualization renderers.
- **Integration tests.** End-to-end flows: schema definition → inspection → validation → visualisation, using a representative domain model.
- **Live database tests opt-in.** `--neo4j` and `--memgraph` pytest flags enable live DB tests; skipped by default.
- **Prior art.** Existing test patterns in `tests/` follow pytest + pytest-mock conventions. Each extension has its own test subdirectory mirroring the source layout.
- **Query Catalogue tests.** Must cover: registration validation (reject invalid queries), runtime result validation (catch type mismatches), YAML loading (round-trip), auto-generated operations (correct Cypher output).

---

## Out of Scope

Items explicitly outside the boundary of Orthograph. Each is a candidate for
future exploration but must not be built into the library.

| Item | Rationale |
|------|-----------|
| Schema migration / applying changes to databases | Orthograph detects drift, does not fix it |
| Query optimisation, caching, connection pooling | Consuming infrastructure concern |
| Historical profile storage, trend analysis, alerting | Monitoring platform concern — not a library concern |
| OWL / RDF machine-readable import | No concrete use case yet |
| Schema composition / inheritance | Future — post-pilot |
| Property value constraints (min/max/regex/enum) | Deferred |
| CLI tool | Future |
| Async driver support | Deferred |
| Scheduling or recurring inspections | Platform concern |

---

## Further Notes

### Pilot Context

Two internal pilot projects are identified:
- **Pilot A:** Hardcoded Cypher queries in transactional mode with no schema declaration → benefits from schema definition + Cypher query catalogue + validation
- **Pilot B:** Existing Cypher catalogue pattern → benefits from Orthograph formalising it with schema validation and result typing

Both paths (Cypher and GQLAlchemy) are needed for v0.1.0 to validate the extensibility of the catalogue interface and assess readiness for future graph ORM backends.

### Key Architectural References

- [ADR-001: Core architecture and naming conventions](../decisions/001-architecture-and-naming.md)
- [ADR-003: Two-phase architecture (inspect then validate)](../decisions/003-extensions-two-phase-architecture.md)
- [ADR-006: GQLAlchemy integration as optional extension](../decisions/006-gqlalchemy-integration.md)

### Open Design Work Required

The Query Catalogue (both Cypher and GQLAlchemy) requires full scoping:
- Registry interface design (shared abstract base)
- Parameter type declaration and validation
- Result type declaration format (flat types initially, model references later)
- YAML serialisation format for Cypher catalogue
- Auto-generated operations specification
- Review of `GqlAlchemyClient` to align with composition approach
