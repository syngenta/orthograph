# Orthograph — Product Requirements Document

---

## Problem Statement

Property graph databases are powerful because they are schema-flexible. Teams
can add new labels, relationship types, and properties without a migration.
That flexibility is valuable during exploration, but it creates a compounding
set of problems once a graph database becomes part of a production system.

### The structural problem: no declared contract in the application layer

Graph databases do expose *some* structure — uniqueness and existence
constraints, indexes, and metadata procedures (e.g. `db.schema.*`, APOC) that
report what labels and properties currently exist. But that structure lives
*inside the database*, describes only what is enforced or currently observed,
and is not the same as an application's *intended* contract. The intended model
— which labels and relationship types are expected, which properties are
required, what types they carry, which endpoints a relationship connects, what
cardinalities hold — is typically never declared anywhere the application can
read. Properties get loosely typed or inconsistently named across write paths;
relationship cardinalities are assumed but never checked. When several
applications or services read from and write to the same graph without a shared
declared contract, the graph drifts silently and there is no single authority on
what it *should* contain.

### The query problem: raw strings with no safety net

Cypher queries are typically stored as raw strings scattered across the
codebase. Parameters are untyped. Result shapes are undeclared. Query errors
appear only at runtime — and the most dangerous failure mode is not an
exception but a silent wrong-result: when a label is renamed or a property
removed, a hand-written query continues to parse, continues to execute, and
simply returns empty or incorrect data with no signal to the caller.

### The drift problem: declared intent and observed reality diverge

Even teams that maintain careful internal conventions find that the live
database drifts away from the intended model over time. New properties appear
directly in production; a relationship type gets added by a script that no one
updated the model for; staging and production diverge quietly. Application DTOs
become stale. There is no reliable, automated way to compare what the graph
*should* contain with what it *actually* contains.

### The ecosystem gap

Pieces of this problem are individually solvable. Graph databases provide
constraints, indexes, and metadata procedures; Python graph ORMs (neomodel,
GQLAlchemy) provide object mapping; GraphQL libraries generate API schemas;
data-quality tools validate tabular data; RDF tools validate semantic graphs.
For other data shapes the Python ecosystem is mature: Pydantic for record-shaped
objects, Pandera for DataFrames, Alembic for relational schema evolution, Soda
for tabular data-quality checks.

What is missing is a single, library-native layer for *property graph
applications* that combines all of the following:

- a declared graph contract that is the application's source of truth (distinct
  from the database's own constraints, which enforce a subset and live below the
  application);
- typed Cypher query definitions with typed parameters and typed outputs;
- a query catalogue that validates queries at registration time;
- live database profiling and declared-vs-observed drift detection;
- CI-friendly validation that runs without executing the queries.

No existing tool brings these together. Orthograph fills this gap. It is a
**contract and governance layer that sits above** graph databases, drivers, and
ORMs — it does not replace any of them. The database still enforces its
constraints and indexes; the driver still executes; an ORM (if used) still maps
objects. Orthograph adds the declared contract, the typed query IO, and the
drift detection that none of those layers provide.

---

## Vision

Orthograph is a **contract and governance layer for property graph applications
in Python — not another graph ORM.** It provides a single place where the graph
contract can live: a **Pydantic-native graph definition, validation, and query
governance library** that is vendor-agnostic, runtime-configurable, and usable
for validation at every layer: data, queries, results, and ORM interactions.

In the Python ecosystem it plays a role analogous to Pydantic (makes data
structure explicit and typed), Pandera (validates structured data expectations),
Soda (detects quality and drift problems in real systems), and Alembic (helps
teams reason about schema evolution) — but designed specifically for property
graphs and Cypher-oriented workflows rather than records, DataFrames, tabular
data, or relational schemas.

Orthograph allows any application to own the **graph-definition layer** in a
three-layer stack:

```
Ontology         (what entities and relationships exist in this domain)
      ↓           consumed informally — domain experts inform contract decisions
Graph Definition ← ORTHOGRAPH (declares the contract in Python or YAML)
      ↓           ▲  Orthograph actively detects drift in BOTH directions:
      ↓           │    • query set     vs graph definition  (validate_query_catalogue)
      ↓           │    • database schema vs graph definition (compare)
Schema           (what the database or datapackage enforces: indexes, constraints)
```

The graph definition is the single declared truth; Orthograph continuously
checks the query set and the live database schema *against* it, so neither
drifts silently as the contract evolves.

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
2. **Validation logic** — schema validation, query validation (parameters, output, language correctness, domain match), result validation, profile comparison, and drift detection across the graph-definition / query-set / database-schema layers
3. **Generation utilities** — auto-generated CRUD queries, GQLAlchemy class codegen, constraint DDL

Consuming projects provide:

1. **Actual graph definitions** — concrete NodeModel/RelationshipModel subclasses or YAML definitions
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
"Here is data I have in hand — validate it against my declared contract."
GraphValidator.validate(data, definition) ──► ValidationResult

CAPABILITY 2: DATABASE PROFILING & INSPECTION
"Connect to a live database, profile its structure, compare against expectations."
GraphInspector.inspect(connection) ──► GraphProfile
compare(definition, profile)       ──► ValidationResult

CAPABILITY 3: QUERY GOVERNANCE
"Declare named, typed queries; validate their parameters, outputs, language
 correctness, and domain-match; detect drift between the query set, the graph
 definition, and the live database schema."
QueryCatalogue (typed Params/Output per query)
validate_cypher(query, definition)                          ──► ValidationResult  (one query vs definition)
validate_query_catalogue(query_catalogue, graph_definition) ──► ValidationResult  (query set vs definition)
validate_query_catalogue_against_profile(cat, profile, def) ──► ValidationResult  (query set + DB shape vs definition)
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
| **Domain match** | Labels, relationship types, property accesses, and endpoints exist in the graph definition | `validate_cypher` `_check_labels/_check_rel_types/_check_properties/_check_endpoints` | `QUERY_UNKNOWN_NODE_LABEL`, `QUERY_UNKNOWN_REL_TYPE`, `QUERY_UNKNOWN_PROPERTY`, `QUERY_INVALID_ENDPOINT` |

#### Three-layer drift detection

The same machinery answers drift questions across the three-layer stack
(Graph Definition ↔ Query Set ↔ Database Schema):

```
                    ┌──────────────────────────────────────────────────────────┐
   Query Set ───────┤ validate_query_catalogue(query_catalogue, graph_definition) │──► drift: queries vs definition
                    └──────────────────────────────────────────────────────────┘
   Graph Definition ┤ (the declared truth)                                       │
                     ┌─────────────────────────────────────────────────────────┐
   DB Schema ───────┤ compare(definition, profile)                              │──► drift: live DB vs definition
                     └─────────────────────────────────────────────────────────┘
   All three ───────► validate_query_catalogue_against_profile(query_catalogue, profile, graph_definition)
```

Queries that cannot be statically inspected (imperative `build()`-only queries, or
non-Cypher backends) are reported as `QUERY_UNVERIFIABLE` (INFO) — they state *why*
the query was not checked rather than silently passing.

---

## Users

**Primary:** Software engineers building tools that interact with graph/network
data — graph databases (Neo4j, Memgraph), datapackages (NetworkX), or Cypher
queries. Includes backend and platform engineers responsible for graph-backed
APIs, authorization graphs, fraud graphs, supply-chain graphs, and
entity-resolution systems.

**Secondary (reached through the tool):** Data engineers and ML engineers who
want to validate their data or queries against a declared schema. They use
Orthograph indirectly via the tools the primary user builds. Also includes
GraphRAG and knowledge-graph teams that need stable graph semantics and
predictable query outputs for retrieval and AI applications, and data/governance
teams that monitor whether live databases still match the intended graph design.

**Tertiary: Library authors.** Third-party Python packages that declare graph
contracts and publish reusable query catalogues so downstream applications can
consume validated definitions without duplicating model or query code. Orthograph
is the mechanism by which a domain library ships a typed, validated graph
interface alongside its own logic.

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
25. As a backend engineer, I want my whole query catalogue validated against my graph definition in one pass, so that I detect — at build time, without a database — every query that drifted away from the contract (renamed label, removed property, changed endpoint).
26. As a backend engineer, I want to detect drift between my query set, my graph definition, and the live database schema together, so that contract evolution never silently desynchronises my queries and my database from my declared truth.
27. As a backend engineer, I want queries that cannot be statically inspected (imperative or non-Cypher) reported explicitly as unverifiable rather than silently treated as valid, so that I know exactly what was and was not checked.
28. As a library author, I want to declare a graph contract and a typed query catalogue inside my package so that downstream applications can import validated model and query definitions without duplicating them or reimplementing validation.
29. As a backend engineer, I want to import and extend a third-party Orthograph query catalogue or graph contract so that I reuse validated definitions from a domain library without copying its schema.
30. As a backend engineer, I want to compare two versions of my graph definition so that I can see exactly what changed (added labels, removed properties, altered cardinalities) and reason about backward compatibility — without applying any migration.
31. As a backend engineer, I want to compare two observed database profiles (for example staging versus production) so that I can detect environment divergence independently of the graph definition.
32. As a data engineer, I want drift findings classified by severity — breaking, warning, or informational — and surfaced as structured, CI-consumable report data so that a build can fail automatically on breaking drift while warnings are reviewed without blocking a release.

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
11. **Backends are isolated.** Importing one backend never pulls in dependencies of another. Each independently installable. No `backends/<X>` imports `backends/<Y>` (enforced by `tests/test_architecture.py`).
12. **Tests are the specification.** Any feature without tests is not done.
13. **Connections are never owned.** Database drivers and sessions are passed in by the caller. Orthograph never stores, pools, or manages connection lifecycle as instance state. Inspectors are stateless — `inspect(self, connection)`.

---

## Capabilities

### `graph_definition/` — Schema Definition and Data Validation

Declare what your graph data should look like and validate actual data against
that declaration.

- **[NodeModel](../../src/orthograph/graph_definition/models.py) / [RelationshipModel](../../src/orthograph/graph_definition/models.py)** — Pydantic BaseModel subclasses declaring node and relationship types with typed properties, cardinality, and optionality
- **[GraphDefinition](../../src/orthograph/graph_definition/graph_definition.py)** — Container holding all node and relationship types as a unified contract; validates structural consistency at construction
- **[GraphValidator](../../src/orthograph/graph_definition/validation.py)** — Validates in-memory graph data against a GraphDefinition: labels, property types, required fields, referential integrity, cardinality, entity presence

### `io/` — Schema and Catalogue Configuration

Load and save graph definitions and query catalogues from/to external YAML
files. Enables runtime configuration without code changes.

- **[Schema YAML](../../src/orthograph/io/yaml.py)** — bidirectional serialisation of a GraphDefinition (node types, relationship types, properties, cardinality)
- **Cypher Catalogue YAML** — load named parameterised queries with declared parameter types and expected result types *(planned; the runtime `QueryCatalogue` itself is available, see below)*

### `backends/` + `graph_profile/` + `comparison/` + `diagnostics/` + `cypher/` — Database Profiling, Query Governance, and ORM Integration

The package topology mirrors the domain: `graph_definition/` is the declared
side, `graph_profile/` is the observed side, `comparison/` is the cross-layer
activity that reconciles them, `diagnostics/` is the shared result currency
(`ValidationIssue`, `ValidationResult`, `Severity`), and `cypher/` is the
top-level Cypher language tool. Vendor backends live in vendor-isolated
`backends/<vendor>/` packages. Consumers reach all of this only through the
vendor-free `orthograph.api` surface (`api.model`, `api.database`,
`api.visualization`).

#### Database Profiling & Inspection

Point-in-time structural analysis of live databases and in-memory graphs.

- **[GraphInspector ABC](../../src/orthograph/graph_profile/inspection.py)** — common interface: `inspect(self, connection) -> GraphProfile`; stateless, connection injected per call
- **[Neo4j Inspector](../../src/orthograph/backends/neo4j/inspector.py)** — live inspection via APOC + pure Cypher fallback strategy
- **[Memgraph Inspector](../../src/orthograph/backends/memgraph/inspector.py)** — live inspection via Memgraph schema procedures
- **[NetworkX Inspector](../../src/orthograph/backends/networkx/inspector.py)** — in-memory graph profiling
- **[GraphProfile](../../src/orthograph/graph_profile/models.py)** — frozen Pydantic model: node/relationship type profiles, property completeness, cardinality statistics, constraints, metadata
- **[compare()](../../src/orthograph/comparison/engine.py)** — compares a GraphDefinition against a GraphProfile, returns a categorised `ValidationResult` with findings explicitly classified by severity: **breaking** (schema violation that will cause runtime failures), **warning** (likely drift or degraded quality), or **informational** (observable difference that does not block runtime). The `ValidationResult` is structured data intended to be consumed by CI pipelines, release gates, and developer tooling; surfacing and orchestration (CLI, scheduled jobs) is the consuming application's responsibility. Reachable via `api.database.validate`.
- **Version-to-version comparison** *(planned, not yet implemented)* — compare two `GraphDefinition` snapshots (model-vs-model) or two `GraphProfile` snapshots (profile-vs-profile, e.g. staging vs production) and produce a diff of added/removed/changed labels, relationship types, properties, and cardinalities. Framed as drift-between-versions analysis, not migration; never applies changes to a database (constraint #4).
- Inspired by [SODA](https://soda.io/) for data quality assessment — point-in-time profiling, not a monitoring platform

#### Query Governance — Cypher

Static validation, drift detection, and generation of Cypher queries — all without
executing the query.

- **[CypherParser / validate_cypher()](../../src/orthograph/cypher/parser.py)** — parse Cypher AST (via graphglot), validate labels, relationship types, property accesses, and endpoints against a schema. Domain-mismatch codes: `QUERY_UNKNOWN_NODE_LABEL`, `QUERY_UNKNOWN_REL_TYPE`, `QUERY_UNKNOWN_PROPERTY`, `QUERY_INVALID_ENDPOINT`
- **[CypherGenerator](../../src/orthograph/cypher/generator.py)** — generate MERGE/CREATE/MATCH/constraint statements from schema; identifier safety policy: validate-and-reject (see [ADR-008](../decisions/008-cypher-identifier-safety.md))
- **[QueryCatalogue](../../src/orthograph/query/catalogue.py)** — registry of named, parameterised typed Cypher queries with declared `Params`/`Output` types; populated at runtime, validates parameter↔template alignment at class-definition time. The catalogue is also the mechanism by which **third-party Python libraries publish reusable graph contracts and query sets**: a library ships a pre-populated catalogue and graph definition that downstream applications import, extend, and validate against their own contract — without duplicating model or query code. *(YAML loading of the catalogue is planned.)*
- **[validate_query_catalogue() / validate_query_catalogue_against_profile()](../../src/orthograph/cypher/validation.py)** — drift detection: validate every query in a catalogue against the graph definition (query-set ↔ definition), or against both the definition and a live-DB `GraphProfile` in one pass (query-set + DB-schema ↔ definition). Statically-uninspectable queries are reported as `QUERY_UNVERIFIABLE` (INFO), never silently passed.

> **Consumer entry point.** `validate_query`, `validate_query_catalogue`, and
> `validate_query_catalogue_against_profile` are part of the `orthograph.api.model`
> surface. Consumers import them from there; the `orthograph.cypher.*` paths are
> the underlying implementation and remain available for advanced use.

#### Query Governance — GQLAlchemy

Validated composition with the GQLAlchemy ORM. Python-only.

- **[Codegen](../../src/orthograph/backends/gqlalchemy/codegen.py)** — auto-generate GQLAlchemy Node/Relationship classes from Orthograph models
- **[ValidatedQueryBuilder](../../src/orthograph/backends/gqlalchemy/query_builder.py)** — decorates GQLAlchemy's fluent query builder with Orthograph schema validation
- **GQLAlchemy Query Catalogue** — registry of named builder expressions with declared parameter types and expected result types; populated at runtime from Python; validates queries at registration and results at execution *(planned)*
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

4. **GQLAlchemy backend is validated composition, not a persistence layer.** Orthograph generates GQLAlchemy classes (codegen), validates queries (query builder), and validates results (result adapter). The consuming project calls GQLAlchemy persistence methods directly. The [`GqlAlchemyClient`](../../src/orthograph/backends/gqlalchemy/client.py) does not dispatch inspectors by class-name string match and does not silently skip validation on a missing optional dependency.

5. **Connections passed per-call.** Backend methods accept database connections as arguments. No backend stores a connection as instance state; inspectors are stateless (`inspect(self, connection)`). This ensures consuming projects retain full control of connection lifecycle. (Constraint 13.)

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
| CLI tool | Future direction: a CLI that drives validate / profile / diff / report workflows and integrates with CI is desirable (see Aspirational Direction in Further Notes); not part of the current library |
| Async driver support | Future direction: async execution under the existing connection-ownership constraint (caller passes an async session) is aspirational; deferred until a concrete backend and use case are identified |
| Scheduling or recurring inspections | Platform concern |
| Synthetic graph data generation | Later-stage differentiator — generate realistic test datasets from declared contracts and observed profiles; deferred until contracts and profiling are stable (post-MVP) |

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
- [ADR-011: Capability seams and backend isolation](../decisions/011-e25-capability-seams-backend-isolation.md)
- [ADR-015: The declared/observed mirror](../decisions/015-declared-observed-mirror.md)
- [ADR-016: Declared/observed naming and the deferred facade](../decisions/016-declared-observed-naming-and-facade.md)
- [ADR-017: Package topology — definition / profile / comparison / diagnostics](../decisions/017-package-topology-definition-profile-comparison-diagnostics.md)
- [ADR-018: Query package naming (`query/`, `base_models.py`, `catalogue.py`)](../decisions/018-query-package-naming.md)

> **Topology.** `graph_definition/` (declared side), `graph_profile/` (observed
> side), `comparison/` (`compare`, the cross-layer reconciliation),
> `diagnostics/` (shared result currency), `cypher/` (Cypher language tool), and
> `query/` (query subsystem: `base_models.py` contracts + `catalogue.py`
> registry). ADR-017 and ADR-018 are the authority for these boundaries.

### Open Design Work Required

The runtime `QueryCatalogue` is available. Remaining open work:
- YAML serialisation format for the Cypher catalogue
- GQLAlchemy query catalogue (builder-expression registry)
- Auto-generated operations specification
- Review of `GqlAlchemyClient` to align with the composition approach

---

### Aspirational Direction (not committed scope)

The following directions are consistent with Orthograph's contract/governance
positioning and are worth tracking, but are **not part of the current library
scope** and must not be built until explicitly promoted out of this section.

- **CLI-driven CI workflow.** A CLI that exposes `validate` (model + catalogue),
  `profile` (live DB → GraphProfile), `diff` (declared vs observed, or
  version-vs-version), and `report` (structured drift output with severity
  classification) would make Orthograph directly usable in CI pipelines without
  any Python wrapper. The library already produces the structured data; the CLI
  would be the orchestration surface. Constraint: CLI is a consumer of the
  library API, not embedded in the library core.

- **Async execution.** Supporting async database drivers (e.g. the async Neo4j
  Python driver) under the existing connection-ownership constraint — the caller
  would pass an async session; Orthograph would await it. Deferred until a
  concrete backend and pilot use case justify the complexity.

- **Synthetic graph data generation.** Using declared contracts and observed
  profiles to generate realistic test datasets (node/relationship distributions,
  property value shapes, cardinality-respecting topology). Useful for staging
  fixtures, demos, and privacy-safe development datasets. Blocked on contracts
  and profiling reaching stability; intended as a post-MVP differentiator.
