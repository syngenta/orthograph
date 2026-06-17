# Noctis YAML Query Method — Analysis and Migration Recommendation

**Date:** 2026-06-17
**Author:** analysis session (engineering)
**Status:** input to E19 scoping decision — not an ADR
**Feeds:** E19.1 (real consumer requirements), E19.2 (option evaluation)
**Does NOT:** resolve E19, write ADR-009, or produce any code

---

## Purpose and scope

This document evaluates Noctis's YAML-serialisable query-definition method as a candidate for
integration into Orthograph, and assesses its role as a transitional validation on-ramp for
migrating Material Protocolling (MP) off its current raw-string repository pattern.

Three codebases were read in full:

| Project | Location | Query method |
|---------|----------|-------------|
| **Noctis** | `github.com/syngenta/noctis` — `src/noctis/repository/neo4j/` | YAML-serialisable registry (`AbstractQuery` + `CustomQuery`) |
| **Orthograph** | `src/orthograph/query/`, `src/orthograph/cypher/` | Strongly-typed `CypherReadQuery`/`CypherWriteQuery` + `QueryCatalogue` |
| **Material Protocolling** | `mp-backend/app/repos/*_neo4j_repo.py` | Raw `LiteralString` static methods; 8 repo classes; async driver |

---

## 1. How each approach works

### 1.1 Material Protocolling — current baseline

MP's pattern is the simplest possible: a `*Neo4jQueries` class holds static methods
that return raw `LiteralString` Cypher. A `*Neo4jRepo` class receives an `AsyncSession`,
calls those methods, and maps `dict(node)` manually. Eight repositories follow this pattern
(`sample`, `protocol`, `operation`, `sub_sample`, `sub_sampling`, `inference`,
`data_asset`, `analysis`).

What the Cypher strings imply about the graph (inferred from the query bodies, since no
contract is declared anywhere):

**Node labels:**
`Sample`, `Protocol`, `Operation`, `Subsample`

**Relationship types:**
`HAS_SAMPLE` (Protocol→Sample), `IS_INPUT` (Sample→Operation),
`HAS_OUTPUT` (Operation→Sample), `HAS_OPERATION` (Protocol→Operation),
`HAS_SUBSAMPLE` (Sample→Subsample)

**What does not exist:** no `GraphDefinition`, no schema YAML, no param models, no
output models, no static validation, no drift detection. Every property name is a bare
string literal repeated across repos. A rename of any label, rel-type, or property key
is invisible until a query executes and returns empty or wrong results.

**Additional constraint:** all repo methods are `async` (`AsyncTransaction | AsyncSession`).
Orthograph's `Executor` abstraction is synchronous today; async support is listed as
deferred in the PRD. This is a hard execution boundary that shapes the migration plan.

---

### 1.2 Noctis — the YAML-serialisable approach

**Core pattern.** Every query is an `AbstractQuery(pydantic.BaseModel)` subclass with
class variables declaring its identity and argument contract:

```python
@Neo4jQueryRegistry.register_query()
class GetTree(AbstractQuery):
    query_name: ClassVar[str]    = "get_tree"
    query_type: ClassVar[str]    = "retrieve_graph"   # drives execution strategy
    parameters_embedded          = False
    query_args_required: ClassVar = ["root_match_value", "max_level"]
    query_args_optional: ClassVar = ["match_property"]
    match_property: str = Field(default="uid")
    query: str = None

    def _build_query(self):
        self.query = (
            f"MATCH (start {{{ self.match_property }:$root_match_value}}) "
            f"CALL apoc.path.subgraphAll(start, {{ ... maxLevel:$max_level }}) ..."
        )
```

**Execution.** `Neo4jRepository.execute_query("get_tree", root_match_value=..., max_level=...)`
dispatches by string key. The `query_type` classvar selects one of three strategies
(`retrieve_graph`, `modify_graph`, `retrieve_stats`), which in turn determines
read vs write transaction and result format.

**YAML twin.** `CustomQuery.from_yaml(yaml_file, query_name)` loads the same shape from YAML:

```yaml
- query_name: get_tree
  query_type: retrieve_graph
  query:
    "MATCH (start {uid:$root_match_value}) CALL apoc.path.subgraphAll(start, ...)
     YIELD nodes, relationships RETURN nodes, relationships"
  query_args_required: [root_match_value, max_level]
  query_args_optional: [match_property]
```

Executed via `repo.execute_custom_query_from_yaml(yaml_file, "get_tree", root_match_value=..., max_level=...)`.

After a custom query runs, `_compare_user_schema_and_gdb_schema` fires a *post-hoc* warning if
the live DB schema deviates from the user's declared `GraphSchema`.

---

### 1.3 Orthograph — the strongly-typed approach

A query is a Python class inheriting from `CypherReadQuery[Params, Output]` or
`CypherWriteQuery[Params, R]`. Both `Params` and `Output` are Pydantic models, auto-populated
from the generic type arguments. The class-definition hook (`__init_subclass__`) fires the
following checks **before the class even exists in memory**:

1. `cypher_template` (a ClassVar `str`) is dialect-parsed by graphglot.
2. Every `$param` placeholder is checked against `Params` field names (strict 1:1).
3. Every `<<identifier>>` placeholder is checked against an `Identifiers` model.

```python
class MoviesByYear(CypherReadQuery[ReleasedYearParams, Movie]):
    name = "movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m"

    def materialize(self, raw):
        return Movie.model_validate(raw["m"])
```

This is the **declarative** (preferred) style. An **imperative** style is allowed (omit the
classvar, override `build()`) but emits a `UserWarning` at class definition time — a
deliberate signal that definition-time checks are skipped.

Queries are stored in a `QueryCatalogue` (typed object registry, not string-key dispatch).
Execution is behind a separate `Executor` seam — Orthograph never owns a connection.

`validate_query_catalogue(catalogue, graph_definition)` then runs four-axis static validation
**with no DB call**:

| Axis | What is checked |
|------|-----------------|
| Parameter validation | `$param` names in the template exactly match `Params` model fields |
| Output declaration | RETURN columns checked against `Output` model; missing required fields → ERROR |
| Language correctness | AST dialect parse via graphglot |
| Domain match | Labels, rel-types, property names, endpoints validated against `GraphDefinition` |

Queries that cannot be statically inspected (imperative build, non-Cypher backend) are reported
as `QUERY_UNVERIFIABLE` (INFO) — they are never silently passed.

---

## 2. Side-by-side comparison

| Axis | MP (current) | Noctis YAML | Orthograph typed |
|------|-------------|-------------|-----------------|
| **Authoring surface** | Python static methods | Python class **or** YAML file | Python class (YAML is open E19 decision) |
| **Param typing** | None — `**kwargs` at call site | None — `any`, validated by name only | `Params` Pydantic model; type-checked at class definition and at call |
| **Output typing** | `dict(node)` — unstructured | `DataFrame` / `list[Record]` — unstructured | `Output` Pydantic model; statically known return type |
| **IDE / mypy** | No | No | Yes — params and return are typed |
| **Static language validation** | None | None | Dialect parse at class-definition time |
| **Static domain validation** | None | None | Labels, rel-types, properties, endpoints checked against `GraphDefinition` before any execution |
| **Injection safety** | `LiteralString` annotation only | `parameters_embedded=True` allows f-string value injection into Cypher strings — ADR-008 violation | `<<identifier>>` placeholders validated and spliced by `build()`; value params passed as driver bindings |
| **Post-hoc drift warning** | None | `_compare_user_schema_and_gdb_schema` after query runs | `validate_query_catalogue_against_profile` — static, before execution, with severity classification |
| **Dispatch model** | Direct method call | String-key: `execute_query("name", **kwargs)` | Typed object registry + `Executor.read(query, params)` — no string-key dispatch |
| **YAML serialisable** | No | Yes — `CustomQuery.from_yaml(...)` | Not yet — planned as E19 open decision |
| **Connection ownership** | Caller owns async session | Repository owns driver (`GraphDatabase.driver(...)`) — violates Orthograph constraint #13 | Connection injected per call; Orthograph never stores it |
| **Async** | Yes (`AsyncSession`) | No — synchronous | Synchronous today; async deferred in PRD |
| **Schema / contract** | None declared | `GraphSchema` (base nodes + rels dict; informational only) | `GraphDefinition` (NodeModel / RelationshipModel with typed properties, cardinality, uid field) |
| **Ceremony per query** | Low (one staticmethod) | Medium (class + ClassVars) | Higher (class + Params model + Output model + `materialize()`) — mitigated by generator codegen |
| **CI-time validation** | None | None | `validate_query_catalogue(catalogue, definition)` — zero DB calls |

---

## 3. What Noctis does well and what it lacks

### 3.1 Genuine strengths

**YAML serialisability.** The `CustomQuery.from_yaml` path is the most operationally useful
feature. Queries can live in config files, be edited without redeployment, and be authored by
non-Python engineers. The format is simple and round-trippable.

**Uniform dispatch.** A single `execute_query("name", **kwargs)` entry point covers all query
types. The `query_type` ClassVar drives the execution strategy; adding a new strategy is
localized to the repository class.

**Argument-level validation.** `validate_query_kwargs` checks required/optional arg names
at call time. This catches the most common call-site mistakes without any schema.

**Schema coupling.** `GraphSchema` is interpolated into query templates at build time — the
query references `self.graph_schema.base_nodes['molecule']` rather than hardcoding `"Molecule"`.
This is the right instinct: label names are not scattered as string literals. It is an
incomplete form of what Orthograph's `GraphDefinition` does fully.

**Registry as discoverable catalogue.** `Neo4jQueryRegistry.info()` prints a formatted table
of all registered queries with their argument lists. This is directly analogous to
`QueryCatalogue.describe()`.

### 3.2 Gaps against Orthograph's guarantees

**No static, pre-execution semantic validation.** Noctis does not parse the Cypher AST and
cannot check whether the labels, rel-types, and properties in a query template exist in the
declared schema. A renamed label (`Molecule` → `Compound`) continues to parse, continues to
execute, and returns empty results — the "silent wrong-result" failure mode the Orthograph PRD
was written to close.

**Params and output are untyped.** `query_args_required` is a list of strings; call-site params
are `**kwargs` passed as-is to the driver. The return is a `DataFrame` or list of records. There
is no Pydantic model enforcing the shape of inputs or outputs; mypy sees nothing.

**`parameters_embedded=True` is injection-unsafe.** Several Noctis queries (`GetRoutes`,
`GetPathsThroughIntermediates`, `AddNodesAndRelationships`) use `parameters_embedded=True` and
build Cypher strings by f-string interpolation of runtime values — e.g.
`f"MATCH (n {{{self.match_property}:'{self.root_match_value}'}})"`). Orthograph's ADR-008
identifies exactly this pattern as the injection risk the `<<identifier>>` + validate-and-reject
policy was designed to prevent.

**Post-hoc drift only.** `_compare_user_schema_and_gdb_schema` runs *after* the query executes
and only compares node-label sets and rel-type sets — not property names, cardinalities, or
endpoints. Orthograph's `validate_query_catalogue` finds the same class of drift *before*
execution, with zero DB calls, with structured severity (ERROR / WARNING / INFO) that can gate CI.

**Connection ownership.** `Neo4jRepository.__init__` calls `GraphDatabase.driver(...)` and stores
it as `self._driver`. This means tests cannot inject a mock driver without monkey-patching the
class. Orthograph constraint #13 ("connections are never owned") addresses exactly this: the
caller passes a session per call.

---

## 4. Can the lightweight method be strengthened via typing?

Yes. The mapping from Noctis concepts to Orthograph types is direct:

| Noctis concept | Orthograph equivalent |
|---------------|----------------------|
| `query_name: ClassVar[str]` | `name: ClassVar[str]` |
| `query_type: ClassVar[str]` → selects strategy | `backend: ClassVar[Backend]` + `Executor` strategy |
| `query_args_required` (list of strings) | `Params(BaseModel)` — fields are required by default |
| `query_args_optional` (list of strings) | `Params(BaseModel)` — fields with `= None` are optional |
| `query: str = _build_query()` | `cypher_template: ClassVar[str]` (declarative) or `build()` (imperative) |
| `GraphSchema` node/rel dict | `GraphDefinition(node_types=[...], relationship_types=[...])` |
| `_compare_user_schema_and_gdb_schema` (post-hoc) | `validate_query_catalogue(catalogue, definition)` (pre-execution, CI-time) |
| `Neo4jQueryRegistry.info()` | `QueryCatalogue.describe()` |
| `CustomQuery.from_yaml(...)` | E19 Option B/C (open decision) |
| Result as `DataFrame` / `list[Record]` | `Output(BaseModel)` + `materialize()` + typed `list[D]` return |

The YAML form is the Noctis `CustomQuery` shape. In Orthograph terms, strengthening it via typing
means: the YAML declares the query string and the arg names (what Noctis already has) plus
a reference to a `GraphDefinition` (what Noctis has as `GraphSchema`) and, optionally, an
`Output` model. `validate_query_catalogue` can then check it statically. The result is
E19 Option C: YAML as the authoring surface, the product is a validated `CypherReadQuery`
class at runtime — no untyped returns in application code.

The `cypher/generator.py` module already demonstrates this synthesis: `_read_query()` and
`_write_query()` call `type(name, (CypherReadQuery,), {..., "cypher_template": cypher, ...})`
to programmatically create fully-validated typed query classes from a `(name, cypher, Params,
Output)` tuple. A YAML loader needs only to produce that tuple from a YAML record.

---

## 5. Recommendation: YAML as a validation-only on-ramp for MP

This recommendation selects **E19 Option C (used transitionally)** and is scoped specifically
to the MP migration. It is *not* a permanent YAML-authoring strategy; that decision belongs to
the E19 team session and ADR-009.

### 5.1 The migration in three phases

**Phase 0 — Declare the MP graph contract (no query changes)**

MP has no `GraphDefinition` today. Every label, rel-type, and property name is implicit in
the Cypher string bodies across 8 repos. The first step is to surface that implicit contract
as an explicit Orthograph `GraphDefinition`, either in Python or YAML.

From reading the 8 MP repositories, the observable graph contract is:

```yaml
# mp_graph_definition.yaml  (illustrative — to be validated against the live DB)
name: material_protocolling
version: "0.1"

node_types:
  Protocol:
    uid_field: id
    properties:
      id:   { type: str, required: true }
      name: { type: str, required: true }

  Sample:
    uid_field: sample_id
    properties:
      id:                  { type: str, required: true }
      sample_id:           { type: str, required: true }
      name:                { type: str, required: true }
      role:                { type: str, required: true }
      source_external_id:  { type: str, required: false }
      source_name:         { type: str, required: false }
      target_name:         { type: str, required: false }
      target_external_id:  { type: str, required: false }
      comment:             { type: str, required: false }

  Operation:
    uid_field: id
    properties:
      id:               { type: str, required: true }
      type:             { type: str, required: true }
      description:      { type: str, required: false }
      duration_minutes: { type: int, required: false }
      comment:          { type: str, required: false }

  Subsample:
    uid_field: sample_id
    properties:
      id:        { type: str, required: true }
      sample_id: { type: str, required: true }

relationship_types:
  HAS_SAMPLE:
    source: Protocol
    target: Sample
    directed: true

  IS_INPUT:
    source: Sample
    target: Operation
    directed: true

  HAS_OUTPUT:
    source: Operation
    target: Sample
    directed: true

  HAS_OPERATION:
    source: Protocol
    target: Operation
    directed: true

  HAS_SUBSAMPLE:
    source: Sample
    target: Subsample
    directed: true
```

This YAML can be loaded with `orthograph.io.yaml.load_yaml_file(path)` → `GraphDefinition`,
immediately, with no DTO changes and no execution changes in MP.

**Phase 1 — Capture existing queries as validated YAML (no DTO changes)**

Translate MP's raw Cypher strings into a Noctis-shaped YAML file (or, better, directly into
the Orthograph YAML catalogue format when E19 decides it). The critical constraint: **no
existing DTO, service, or execution path in MP changes**. All 8 async repos continue to
operate exactly as they do today.

The YAML entries serve one purpose at this stage: **CI-time static validation via
`validate_query_catalogue(catalogue, mp_definition)`**. Each entry becomes a `CypherReadQuery`
or `CypherWriteQuery` instance (via the generator's `_read_query()` / `_write_query()` pattern
or a light YAML loader) and is passed through:

- Dialect parse — catches syntax errors
- `$param` ↔ `Params` alignment — catches stale parameter names
- Domain match — catches renamed labels (`Sample` → `Specimen`), unknown rel-types,
  unknown property accesses

Example of what Phase 1 would surface **without executing a single query**:

```
ERROR  QUERY_UNKNOWN_NODE_LABEL   query 'find_internal_input_samples': label 'Protocol'
                                  not in GraphDefinition           (if label renamed)
ERROR  QUERY_UNKNOWN_REL_TYPE     query 'select_samples_by_protocol': rel 'HAS_SAMPLE'
                                  not in GraphDefinition           (if rel renamed)
INFO   QUERY_UNVERIFIABLE         query 'merge_sample': uses imperative build(); static
                                  validation skipped
```

The output is structured `ValidationResult` data that a CI step can consume. No DB connection
required.

**Phase 2 — Incremental migration to typed `CypherReadQuery` classes (optional, deferred)**

After Phase 1 establishes confidence (all queries pass static validation; the `GraphDefinition`
matches the live DB via `compare()`), individual queries can be migrated to typed
`CypherReadQuery`/`CypherWriteQuery` classes — one aggregate at a time, behind `ReadPort`
bindings at the composition root.

MP keeps its async `AsyncSession` execution throughout. Orthograph contributes:

- The `GraphDefinition` (schema authority)
- The `QueryCatalogue` (CI-time validation registry)
- Generated typed query classes (via `CypherGenerator` or manual subclassing)
- Optionally: the `cypher_template` strings, which MP's async repo methods call directly
  (`query, params = my_query.build(my_params); await session.run(query, params)`)

This separation is clean: Orthograph validates and generates, MP owns async execution. The
async `Executor` gap never blocks the migration because Orthograph's `Executor` is not
required in this path — MP routes `build()` output to its own async session.

### 5.2 What each phase delivers

| Phase | MP changes | Orthograph changes | Value |
|-------|-----------|-------------------|-------|
| Phase 0 | None | Add `mp_graph_definition.yaml` (outside MP repo — or in it) | Explicit graph contract; first use of `load_yaml_file` in a real project |
| Phase 1 | CI step added; no production code changes | YAML query catalogue loader (or manual `_read_query` wiring) | CI catches label/rel-type/property drift; feeds E19.1 with real YAML shape data |
| Phase 2 | Replace raw Cypher strings with `query.build(params)` calls, one repo at a time | Auto-generated or manually-typed `CypherReadQuery` classes | Typed params and outputs; mypy support; full Orthograph governance |

---

## 6. Constraint and risk audit

### 6.1 PRD constraints satisfied by this plan

| Constraint | Status |
|-----------|--------|
| #2 Models are the single source of truth | Phase 0 establishes a `GraphDefinition`; all query classes derive from it — not the reverse. |
| #8 YAML sufficient for the common case | Phase 0 uses `load_yaml_file`; Phase 1 relies on a YAML query catalogue. |
| #9 Runtime configurability | The `GraphDefinition` and query catalogue both load from YAML without code changes. |
| #13 Connections never owned | Phase 1/2 use `build()` output only; execution stays with MP's caller-owned sessions. |
| E16 no-string-key-dispatch | Orthograph `CypherReadQuery` classes are typed objects. If a YAML loader is introduced, it must emit typed query instances (Option C) not runtime string-key dispatch (Option B risk). |

### 6.2 Risks to track

**Async Executor gap.** The plan deliberately avoids needing Orthograph's `Executor` until Phase 2,
and even then MP calls `session.run(query.build(params))` directly. If the team later wants
`executor.read(query, params)` to be async, that promotes the async-Executor item from
"deferred" to "needed" and requires scoping before Phase 2 can be considered complete.

**YAML catalogue E19 not yet decided.** Phase 1 is described as "YAML entries → typed query
instances." The exact mechanism depends on E19's decision. If Option A (Python-only) wins,
Phase 1 means writing `CypherReadQuery` subclasses by hand or via the generator, not loading
a YAML file. The validation value is identical; only the authoring surface changes.

**`parameters_embedded` / injection pattern.** If any MP query is migrated using the Noctis
`parameters_embedded=True` pattern (f-string value injection), it must be rejected — ADR-008
classify this as an injection risk. All driver-bound values must go through `$param` bindings.

**Two-tier surface risk (Option B).** If E19 selects Option B (YAML as a permanent runtime
tier with string-key dispatch alongside typed classes), the "repository-calls-catalogue-by-name"
anti-pattern identified in the planning overview scoping note re-enters application code. This
plan recommends Option C (YAML as a transient authoring surface; runtime is always typed) to
avoid that tension.

**MP graph definition is inferred, not verified.** Phase 0 produces a `GraphDefinition` inferred
from reading Cypher string bodies. It must be validated against the live MP database via
`compare(definition, profile)` before Phase 1 validation results are trusted. Until that
comparison runs, Phase 1 errors may reflect an incorrect definition rather than a real query
problem.

---

## 7. How this feeds E19

This document provides:

- **E19.1 (real consumer requirements):** Noctis is the organisation's live example of
  YAML-driven Cypher authoring. The `CustomQuery.from_yaml` shape, the YAML field set
  (`query_name`, `query_type`, `query`, `query_args_required`, `query_args_optional`), and
  the way MP's 8 async repos would consume a validation-only on-ramp are the concrete
  requirements the E19 scoping session needs.

- **E19.2 (option evaluation):** See Section 2 (comparison table), Section 3 (Noctis
  strengths and gaps), and Section 5 (phased plan). In brief:
  - **Option A** (Python-only): feasible for Phase 2 but makes Phase 1 higher-friction —
    writing 8 × N typed query classes by hand before CI validation is available is
    discouraging. Viable if the team accepts one-time migration cost.
  - **Option B** (YAML as permanent runtime tier): introduces the string-key dispatch tension
    that E16 deliberately resolved. Not recommended unless the team explicitly decides the
    two-tier surface is acceptable with a documented boundary.
  - **Option C** (YAML as transitional / code-gen): recommended. YAML is the low-friction
    Phase 1 on-ramp; the runtime artefact is always a typed `CypherReadQuery` instance. The
    generator already proves this is mechanically feasible (`cypher/generator.py:_read_query`).

**E19.3 (team decision) and E19.4 (ADR-009)** remain for the team scoping session. This
document does not make that decision unilaterally.
