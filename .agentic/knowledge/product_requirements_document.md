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
     ↓           ▲  Orthograph actively detects drift in BOTH directions:
     ↓           │    • query set    vs data model  (validate_query_catalogue)
     ↓           │    • database schema vs data model (validate_profile)
Schema          (what the database or datapackage enforces: indexes, constraints)
```

The data model is the single declared truth; Orthograph continuously checks the
query set and the live database schema *against* it, so neither drifts silently as
the schema evolves.

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
2. **Validation logic** — schema validation, query validation (parameters, output, language correctness, domain match), result validation, profile comparison, and drift detection across the data-model / query-set / database-schema layers
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

Three distinct validation capabilities:

```
CAPABILITY 1: DATA VALIDATION
"Here is data I have in hand — validate it against my declared schema."
GraphValidator.validate(data, model) ──► ValidationResult

CAPABILITY 2: DATABASE PROFILING & INSPECTION
"Connect to a live database, profile its structure, compare against expectations."
GraphInspector.inspect(connection) ──► GraphProfile
compare(profile, model)            ──► ValidationResult

CAPABILITY 3: QUERY GOVERNANCE
"Declare named, typed queries; validate their parameters, outputs, language
 correctness, and domain-match; detect drift between the query set, the data
 model, and the live database schema."
QueryCatalogue (typed Params/Output per query)
validate_cypher(query, model)                       ──► ValidationResult  (one query vs model)
validate_query_catalogue(query_catalogue, graph_data_model)                ──► ValidationResult  (query set vs model)
validate_query_catalogue_against_profile(cat, profile, m) ──► ValidationResult  (query set + DB shape vs model)
```

Data Validation operates on in-memory records (pre-write or post-read).
Database Profiling & Inspection performs point-in-time structural analysis:
type distributions, completeness statistics, cardinality measurements, drift
detection, and consistency checks. Inspired by SODA for data quality.

#### Capability 3 in detail — the silent-mismatch problem it solves

The core failure mode Orthograph exists to prevent is **silent mismatch between an
evolving schema and the queries written against it**. When a label is renamed, a
property removed, or an endpoint type changed, hand-written queries keep parsing and
keep running — they simply return wrong or empty results, with no error. Orthograph
closes this gap on four axes, all without executing the query:

| Axis | What is checked | Mechanism | Failure surfaced as |
|------|-----------------|-----------|---------------------|
| **Parameter validation** | If a query is parametric, its parameters are typed and validated | `Params` Pydantic model, checked at class-definition time and at call | parameter-binding error before any DB call |
| **Output declaration & validation** | The result shape is declared and validated | `Output` model + each query's `materialize()` (type-checked) | typed `list[Output]`; mismatch raises |
| **Language correctness** | The query is parsed for Cypher syntactic validity | `validate_cypher` parses the AST (via graphglot) | parse failure |
| **Domain match** | Labels, relationship types, property accesses, and endpoints exist in the data model | `validate_cypher` `_check_labels/_check_rel_types/_check_properties/_check_endpoints` | `QUERY_UNKNOWN_NODE_LABEL`, `QUERY_UNKNOWN_REL_TYPE`, `QUERY_UNKNOWN_PROPERTY`, `QUERY_INVALID_ENDPOINT` |

#### Three-layer drift detection

The same machinery answers drift questions across the three-layer stack
(Data Model ↔ Query Set ↔ Database Schema):

```
                 ┌──────────────────────────────────────────────┐
   Query Set ────┤ validate_query_catalogue(query_catalogue, graph_data_model) │──► drift: queries vs model
                 └──────────────────────────────────────────────┘
   Data Model ───┤ (the declared truth)                          │
                  ┌──────────────────────────────────────────────┐
   DB Schema ────┤ compare(profile, model)                        │──► drift: live DB vs model
                  └──────────────────────────────────────────────┘
   All three ────► validate_query_catalogue_against_profile(query_catalogue, profile, graph_data_model)
```

Queries that cannot be statically inspected (imperative `build()`-only queries, or
non-Cypher backends) are reported as `QUERY_UNVERIFIABLE` (INFO) — they state *why*
the query was not checked rather than silently passing.

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
22. As a backend engineer, I want Orthograph backends to be independently installable, so that I only pull in dependencies for the backends I use.
23. As a backend engineer, I want a parametric query's parameters to be typed and validated, so that a wrong or missing parameter is caught before the query reaches the database.
24. As a backend engineer, I want a query's output shape to be declared and validated, so that an unexpected result shape fails loudly at materialisation instead of propagating bad data.
25. As a backend engineer, I want my whole query catalogue validated against my data model in one pass, so that I detect — at build time, without a database — every query that drifted away from the schema (renamed label, removed property, changed endpoint).
26. As a backend engineer, I want to detect drift between my query set, my data model, and the live database schema together, so that schema evolution never silently desynchronises my queries and my database from my declared model.
27. As a backend engineer, I want queries that cannot be statically inspected (imperative or non-Cypher) reported explicitly as unverifiable rather than silently treated as valid, so that I know exactly what was and was not checked.

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

1. **DB-agnostic in graph_definition.** No database-specific logic in `graph_definition/`. Vendor-isolated `backends/` adapters exist for that.
2. **Models are the single source of truth.** GQLAlchemy classes, Cypher queries, constraints — all derived from `NodeModel`/`RelationshipModel`, never the reverse.
3. **Not an ORM.** Validates and generates — does not manage connections, transactions, object lifecycle, or data orchestration. Backends may generate ORM-compatible classes and validate ORM query output, but never own the persistence call.
4. **Not a migration tool.** Detects drift, does not apply changes to databases.
5. **Not a query optimizer.** Validates and generates queries — does not optimize execution plans, cache results, or manage connection pools.
6. **Not a monitoring platform.** Produces point-in-time profiles and comparisons. Historical storage, trend analysis, scheduling, and alerting belong in consuming infrastructure.
7. **No knowledge about consuming projects.** Orthograph is a library, not a platform. Migration plans, project-specific configurations, and team workflows belong in those projects.
8. **YAML sufficient for the common case.** A consuming application can define schema and Cypher query catalogue in YAML alone, without Python class definitions.
9. **Runtime configurability over compile-time rigidity.** External YAML, dynamic class generation, runtime validation preferred over patterns requiring code changes for schema updates.
10. **Two input modes where applicable.** Class-based (Python) and config-based (YAML) for schema definitions and Cypher query catalogues. Python-only for GQLAlchemy query catalogues (builder expressions are inherently code).
11. **Backends are isolated.** Importing one backend never pulls in dependencies of another. Each independently installable. No `backends/<X>` imports `backends/<Y>` (enforced by `tests/test_architecture.py`, E25 / ADR-011).
12. **Tests are the specification.** Any feature without tests is not done.
13. **Connections are never owned.** Database drivers and sessions are passed in by the caller. Orthograph never stores, pools, or manages connection lifecycle as instance state. *(Reaffirmed post-E25: inspectors are stateless — `inspect(self, connection)` — and the code now matches this constraint exactly; ADR-011.)*

---

## Capabilities

### `graph_definition/` — Schema Definition and Data Validation

Declare what your graph data should look like and validate actual data against
that declaration.

- **[NodeModel](../../src/orthograph/graph_definition/node_model.py) / [RelationshipModel](../../src/orthograph/graph_definition/relationship_model.py)** — Pydantic BaseModel subclasses declaring node and relationship types with typed properties, cardinality, and optionality
- **[GraphDefinition](../../src/orthograph/graph_definition/graph_definition.py)** — Container holding all node and relationship types as a unified schema; validates structural consistency at construction (`GraphDataModel` is a backward-compatible alias, ADR-016)
- **[GraphValidator](../../src/orthograph/graph_definition/validation.py)** — Validates in-memory graph data against a GraphDefinition: labels, property types, required fields, referential integrity, cardinality, entity presence

### `io/` — Schema and Catalogue Configuration

Load and save schemas and query catalogues from/to external YAML files. Enables
runtime configuration without code changes.

- **[Schema YAML](../../src/orthograph/io/yaml.py)** — bidirectional serialisation of GraphDataModel (node types, relationship types, properties, cardinality)
- **Cypher Catalogue YAML** — load named parameterised queries with declared parameter types and expected result types *(YAML loading not yet implemented — tracked by E19; the runtime `QueryCatalogue` itself is implemented, see below)*

### `backends/` + `graph_profile/` + `comparison/` + `diagnostics/` + `cypher/` — Database Profiling, Query Governance, and ORM Integration

> **E25 refactor (ADR-011):** the former `extensions/` package was split into vendor-isolated
> `backends/<vendor>/` adapters, the vendor-free inspection currency `graph_profile/`, and the
> top-level Cypher language tool `cypher/`. **ADR-017 further reshapes** the core: `core/` →
> `graph_definition/` (declared side), `profile/` → `graph_profile/` (observed side),
> `profile/validation.py` → `comparison/engine.py` (`compare`, formerly `validate_profile`),
> and shared result types → `diagnostics/`. Consumers reach all of this only through the
> vendor-free `orthograph.api` surface (`api.model`, `api.database`, `api.visualization`).

#### Database Profiling & Inspection

Point-in-time structural analysis of live databases and in-memory graphs.

- **[GraphInspector ABC](../../src/orthograph/graph_profile/inspection.py)** — common interface: `inspect(self, connection) -> GraphProfile`; stateless, connection injected per call
- **[Neo4j Inspector](../../src/orthograph/backends/neo4j/inspector.py)** — live inspection via APOC + pure Cypher fallback strategy
- **[Memgraph Inspector](../../src/orthograph/backends/memgraph/inspector.py)** — live inspection via Memgraph schema procedures
- **[NetworkX Inspector](../../src/orthograph/backends/networkx/inspector.py)** — in-memory graph profiling
- **[GraphProfile](../../src/orthograph/graph_profile/models.py)** — frozen Pydantic model: node/relationship type profiles, property completeness, cardinality statistics, constraints, metadata
- **[compare()](../../src/orthograph/comparison/engine.py)** — compares a GraphProfile against a GraphDefinition, returns categorised ValidationResult; reachable via `api.database.validate` (formerly `validate_profile`)
- Inspired by [SODA](https://soda.io/) for data quality assessment — point-in-time profiling, not a monitoring platform

#### Query Governance — Cypher

Static validation, drift detection, and generation of Cypher queries — all without
executing the query.

- **[CypherParser / validate_cypher()](../../src/orthograph/cypher/parser.py)** — parse Cypher AST (via graphglot), validate labels, relationship types, property accesses, and endpoints against a schema. Domain-mismatch codes: `QUERY_UNKNOWN_NODE_LABEL`, `QUERY_UNKNOWN_REL_TYPE`, `QUERY_UNKNOWN_PROPERTY`, `QUERY_INVALID_ENDPOINT`
- **[CypherGenerator](../../src/orthograph/cypher/generator.py)** — generate MERGE/CREATE/MATCH/constraint statements from schema; identifier safety policy: validate-and-reject (see [ADR-008](../decisions/008-cypher-identifier-safety.md))
- **[QueryCatalogue](../../src/orthograph/query/catalogue.py)** — registry of named, parameterised typed Cypher queries with declared `Params`/`Output` types; populated at runtime, validates parameter↔template alignment at class-definition time (E16, implemented). *YAML loading of the catalogue is not yet implemented (E19).*
- **[validate_query_catalogue() / validate_query_catalogue_against_profile()](../../src/orthograph/cypher/validate_query_catalogue.py)** — drift detection: validate every query in a catalogue against the data model (query-set ↔ model), or against both the model and a live-DB `GraphProfile` in one pass (query-set + DB-schema ↔ model). Statically-uninspectable queries are reported as `QUERY_UNVERIFIABLE` (INFO), never silently passed.

> **Exposed via `api.model` (closed E1.5, 2026-06-11):** `validate_query`,
> `validate_query_catalogue`, and `validate_query_catalogue_against_profile` are now part of the
> `orthograph.api.model` surface. Consumers import them from there; the deep
> `orthograph.cypher.*` paths remain the true implementation and are available for
> advanced use.

#### Query Governance — GQLAlchemy

Validated composition with the GQLAlchemy ORM. Python-only.

- **[Codegen](../../src/orthograph/backends/gqlalchemy/codegen.py)** — auto-generate GQLAlchemy Node/Relationship classes from Orthograph models
- **[ValidatedQueryBuilder](../../src/orthograph/backends/gqlalchemy/query_builder.py)** — decorates GQLAlchemy's fluent query builder with Orthograph schema validation
- **GQLAlchemy Query Catalogue** — registry of named builder expressions with declared parameter types and expected result types; populated at runtime from Python; validates queries at registration and results at execution *(not yet implemented — tracked by E8)*
- **[Result Adapter](../../src/orthograph/backends/gqlalchemy/result_adapter.py)** — converts GQLAlchemy objects to Orthograph validation dicts

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
- Exposed to consumers through **[`api.visualization`](../../src/orthograph/api/visualization.py)** (`render_model`, `render_profile`, `render_result`, `display`)

---

## Implementation Decisions

1. **Two distinct validation engines.** `GraphValidator` (graph_definition) validates raw in-memory data records. `compare()` (`comparison/`) validates aggregated database profiles. These serve different use cases and remain separate. They surface as two distinct `api` verbs: `api.model.validate` (in-memory data) and `api.database.validate` (live DB vs model).

2. **Query Catalogue as registry pattern.** Both Cypher and GQLAlchemy catalogues share a common registry interface (register, lookup, validate, execute-with-validation) but differ in serialisation: Cypher supports YAML + Python; GQLAlchemy is Python-only.

3. **Result type declarations start simple.** Output models are initially flat maps of `field_name: type` for projections. References to existing NodeModel/RelationshipModel types for node-shaped results. Rich output models (nested, computed) are a future evolution.

4. **GQLAlchemy backend is validated composition, not a persistence layer.** Orthograph generates GQLAlchemy classes (codegen), validates queries (query builder), and validates results (result adapter). The consuming project calls GQLAlchemy persistence methods directly. The [`GqlAlchemyClient`](../../src/orthograph/backends/gqlalchemy/client.py) no longer dispatches inspectors by class-name string match and no longer silently skips validation on a missing optional dependency (E25.S2 / ADR-011); full `save_*` review is tracked by E9.

5. **Connections passed per-call.** Backend methods accept database connections as arguments. No backend stores a connection as instance state (E25 / ADR-011 — inspectors are stateless; `inspect(self, connection)`). This ensures consuming projects retain full control of connection lifecycle. (Constraint 13.)

6. **Backend isolation enforced via optional dependency groups.** Each backend has its own pip extra. The Cypher tool is user-facing (query validation/generation) and is not a dependency of other backends — Neo4j/Memgraph write their own Cypher strings internally. Availability is validated in exactly one module, `orthograph.dependencies`; adapter wiring in exactly one module, `orthograph.backends.loader`.

---

## Testing Decisions

- **External behaviour only.** Tests validate inputs and outputs of public interfaces, not internal implementation details.
- **All capabilities tested.** Core models, validators, YAML IO, each extension (inspectors with mocked drivers, result adapters, Cypher parser/generator, GQLAlchemy codegen/client/builder), visualization renderers.
- **Integration tests.** End-to-end flows: schema definition → inspection → validation → visualisation, using a representative domain model.
- **Live database tests opt-in.** `--neo4j` and `--memgraph` pytest flags enable live DB tests; skipped by default.
- **Prior art.** Existing test patterns in `tests/` follow pytest + pytest-mock conventions. Each backend has its own test subdirectory mirroring the source layout (`tests/backends/<vendor>/`).
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
- [ADR-006: GQLAlchemy integration as optional backend](../decisions/006-gqlalchemy-integration.md)
- [ADR-008: Cypher identifier safety — validate-and-reject policy](../decisions/008-cypher-identifier-safety.md)
- [ADR-009: Inspector query alignment and GraphProfile parity](../decisions/009-inspector-query-alignment.md)
- [ADR-010: Declared identifier parameters in typed queries](../decisions/010-declared-identifier-parameters.md)
- [ADR-011: Capability seams and backend isolation (E25 refactor)](../decisions/011-e25-capability-seams-backend-isolation.md)
- [ADR-015: The declared/observed mirror](../decisions/015-declared-observed-mirror.md)
- [ADR-016: Declared/observed naming and the deferred facade](../decisions/016-declared-observed-naming-and-facade.md)
- [ADR-017: Package topology — definition / profile / comparison / diagnostics](../decisions/017-package-topology-definition-profile-comparison-diagnostics.md)

> **Topology (ADR-017 — complete as of migration plan step 06).**
> `core/` → `graph_definition/`, `profile/` → `graph_profile/`,
> `validate_profile` → `compare()` in `comparison/engine.py`,
> result currency → `diagnostics/`. All capability links above now reference
> the new homes. ADR-017 carries the full old→new translation table.

### Open Design Work Required

The runtime `QueryCatalogue` is implemented (E16). Remaining open work:
- YAML serialisation format for the Cypher catalogue (E19)
- GQLAlchemy query catalogue (builder-expression registry) (E8)
- Auto-generated operations specification
- Review of `GqlAlchemyClient` to align with the composition approach (E9)
