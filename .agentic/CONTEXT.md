# Orthograph — CONTEXT

Routing table. No content lives here — each link points to the single canonical source.

---

## Navigate

| Question | Read |
|----------|------|
| What is this project, who is it for, what are the constraints? | [knowledge/product_requirements_document.md](knowledge/product_requirements_document.md) |
| What is the package topology (definition/profile/comparison/diagnostics) and why? | [decisions/017-package-topology-definition-profile-comparison-diagnostics.md](decisions/017-package-topology-definition-profile-comparison-diagnostics.md) |
| What is the inspection contract (inspector ABC, GraphProfile) and how are optional deps handled? | [decisions/012-optional-dependency-policy.md](decisions/012-optional-dependency-policy.md) — for the Neo4j three-way strategy (APOC / SCHEMA / CYPHER), see [decisions/033-neo4j-db-schema-inspection-strategy.md](decisions/033-neo4j-db-schema-inspection-strategy.md) |
| What is the consumer-facing API surface? | `src/orthograph/` — seven real root modules: `definition` (load/save/validate), `profile` (inspect), `compare` (three comparisons), `queries` (catalogue/CRUD/validation), `execution` (run typed queries), `discovery` (backend availability), `rendering` (render). Both `from orthograph.definition import X` and `import orthograph; orthograph.definition.X` are fully type-safe (ADR-041). The `api/` sub-package was removed. See [decisions/041-root-capability-modules-api-layer-removed.md](decisions/041-root-capability-modules-api-layer-removed.md). |
| How does a backend name map to an adapter, and how is availability checked? | `src/orthograph/backends/loader.py` (adapter wiring) + `src/orthograph/dependencies.py` (availability) |
| Where do vendor backends and the vendor-free inspection currency live? | `src/orthograph/backends/<vendor>/` (adapters + queries) and `src/orthograph/graph_profile/` (GraphProfile, inspector ABC); the declared side is `src/orthograph/graph_definition/`, the cross-layer comparison is `src/orthograph/comparison/` (`compare_profile_to_definition`, `compare_profiles`, `compare_definitions`), and the shared result currency is `src/orthograph/diagnostics/`. The Cypher language tool is top-level `src/orthograph/cypher/`. *(Topology per ADR-017.)* |
| Why is the satisfaction-path `left`/`right` argument order inverted in `compare_profile_to_definition`, and why aren't `rules.py`/`diff_rules.py` type helpers merged? | [decisions/044-comparison-dispatch-and-rule-symmetry.md](decisions/044-comparison-dispatch-and-rule-symmetry.md) (no-change verdict for both: inversion is the correct resting state; type-logic symmetry is coincidental; the one shared piece `db_type_to_python` is already in `type_mapping.py`) |
| How does comparison work? How do I add a new validation rule? | `src/orthograph/comparison/engine.py` (engine: `compare_profile_to_definition`, `compare_profiles`, `compare_definitions`) + `src/orthograph/comparison/views.py` (`GraphView` adapters) + `src/orthograph/comparison/rules.py` (satisfaction rules) + `src/orthograph/comparison/diff_rules.py` (symmetric diff rules) + [decisions/015-declared-observed-mirror.md](decisions/015-declared-observed-mirror.md) |
| How is cardinality authored? What is the UML notation grammar (`"1..*"`)? | [decisions/031-unify-cardinality-on-uml-notation.md](decisions/031-unify-cardinality-on-uml-notation.md) (notation grammar, round-trip invariant; supersedes the cardinality-naming parts of ADR-001/005) |
| How does conditional cardinality partition/enforce counts? Why discriminate on both endpoints? | [decisions/032-general-conditional-cardinality-partitioning.md](decisions/032-general-conditional-cardinality-partitioning.md) (both-endpoint partitioning, `by_kind` removed; amends ADR-029 §3/§4/§7) + `src/orthograph/graph_definition/validation.py` (`_partition_counts`, `_check_conditional_side`) |
| Why does the observed partition key carry discriminator **names** ({name:value} maps), not just values? Where is the partitioned-cardinality field shape (`list[PartitionedCardinalityRow]`)? | [decisions/039-self-describing-partition-key.md](decisions/039-self-describing-partition-key.md) (self-describing key, name-aware comparison + profile↔profile diff, structured rows replace the lossy string key; single-property = E53, multi-property = E54; amends ADR-034 §3/§7/§8 + ADR-032 §4; **no** declaration-time guard) + `src/orthograph/graph_profile/models.py` (`PartitionKey`, `PartitionedCardinalityRow`) |
| What is the GraphProfile statistical model (BoundedDistribution, presence-source split, value distributions) and the comparison contract (what enters profile↔description vs profile↔profile)? | [decisions/034-graphprofile-statistical-model-and-comparison-contract.md](decisions/034-graphprofile-statistical-model-and-comparison-contract.md) (the full comparison matrix; `None`=unverifiable; total count is diff-only) + `src/orthograph/graph_profile/models.py` |
| What identifies a relationship type — the bare label or its endpoints? Why are `Person-KNOWS->Person` and `Company-KNOWS->Company` distinct? | [decisions/037-relationship-identity-includes-endpoints.md](decisions/037-relationship-identity-includes-endpoints.md) (identity = `(source, label, target)` triple via `RelTypeKey`; endpoint mismatch → `MISSING_*`/`UNEXPECTED_*`; supersedes the identity implication of ADR-014, amends ADR-015 §address-space + ADR-034 §7/§8) — implementation tracked by E50 ([planning/active_epics/E50_endpoint_aware_relationship_identity.md](planning/archived_epics/E50_endpoint_aware_relationship_identity.md)) |
| How is `observed_type_counts` populated (the bounded DB value scan, two aggregations, opt-in, prevalence-aware type conformance)? | [decisions/035-observed-type-counts-population.md](decisions/035-observed-type-counts-population.md) (single `value_counts_top_n` knob; type counts exact, histogram truncates; reconciliation invariant; discharges the ADR-015 B1 TODO) |
| Why does the APOC strategy correct `present_count`/`total_count` with dedicated `count()` queries instead of trusting `apoc.meta.*`? | [decisions/036-apoc-no-scan-present-count-correction.md](decisions/036-apoc-no-scan-present-count-correction.md) (APOC observation counts undercount — the 100-vs-172 finding; `NodePresentCountQuery`/`RelPresentCountQuery` + instance counts fix it on the no-scan path, rels + nodes) |
| Why was a specific architectural decision made? | [decisions/](decisions/) — search by title or category |
| Why are some internal validation/comparison functions being distilled, and what is the no-behaviour-change contract? | [decisions/042-internal-logic-distillation.md](decisions/042-internal-logic-distillation.md) (behaviour-preserving extraction; the radon hotspots; documentation-readiness lens) + [planning/active_epics/E56_internal_logic_distillation.md](planning/active_epics/E56_internal_logic_distillation.md) |
| What is the public query-validation surface (which verbs, what they accept, why)? | [decisions/043-query-validation-public-api-two-phases-two-input-grades.md](decisions/043-query-validation-public-api-two-phases-two-input-grades.md) (2×2 matrix: phase `check_*`/`validate*` × grade object/pieces → six verbs; `check_*` never takes a `GraphDefinition`, `validate*` always requires one; `params_fields`=`set[str]`; `parser=` seam, config deferred) + [planning/active_epics/E59_query_validation_public_api.md](planning/active_epics/E59_query_validation_public_api.md) |
| What is the query-shape alignment strategy — rename direction, blast radius, adapter fate, migration ordering? | [decisions/045-query-shape-alignment-rename-strategy.md](decisions/045-query-shape-alignment-rename-strategy.md) (hard rename pre-v0.1.0; typed adopts Cypher names: `Params`→`params_schema`, `Identifiers`→`identifiers_schema`, `name`→`query_id`; `QueryDescription.name` preserved; adapters kept for `build()` shape only; E59 gates E60.1) + [planning/active_epics/E60_query_shape_alignment.md](planning/active_epics/E60_query_shape_alignment.md) |
| How does the simple-path `CypherQuery` execute, and why is it not passed to the typed `CypherExecutor`? | [decisions/047-simple-path-cypher-execution-surface.md](decisions/047-simple-path-cypher-execution-surface.md) (`CypherQuery` output is `dict[str, Any]`, not a `BaseModel`, so it cannot be a `ReadQueryModel[P, D]` — `D` is `bound=BaseModel`; instead of `# type: ignore`, it gets a dedicated `CypherQueryExecutor`/`AsyncCypherQueryExecutor` with `fetch`→`list[dict]` / `execute`→`CypherWriteResultSummary` + public `run_cypher_*` verbs; caller owns the tx per ADR-028) + [planning/active_epics/E62_simple_path_cypher_execution.md](planning/active_epics/E62_simple_path_cypher_execution.md) |
| How does Neo4j's `Neo4jInspector` detect and read property types? | [notes/neo4j_property_type_detection.md](notes/neo4j_property_type_detection.md) (APOC / SCHEMA / CYPHER strategies, deprecation, backward compatibility) |
| How is the documentation structured (Diátaxis quadrants × three audiences), and what are the authoring guardrails? | [decisions/046-documentation-architecture.md](decisions/046-documentation-architecture.md) (quadrants are the tree, audiences are entry points; notebooks compiled in place as the single tutorial source; reference = public surface only; thin contributor docs) + [planning/archived_epics/E61_documentation_readthedocs.md](planning/archived_epics/E61_documentation_readthedocs.md) (the phased build; supersedes E3) |
| What is the project-wide error hierarchy and how do errors self-log? | [decisions/048-error-hierarchy.md](decisions/048-error-hierarchy.md) — public surface is the `orthograph.errors` shim |
| How does the library log, and how does a consuming app capture Orthograph logs? | [decisions/049-library-logging.md](decisions/049-library-logging.md) — public surface is the `orthograph.logging` shim (`get_logger`) |
| What work is planned and in what order? | [planning/overview.md](planning/overview.md) |
| What are the tasks for a specific epic? | [planning/active_epics/](planning/active_epics/) (archived: [planning/archived_epics/](planning/archived_epics/)) |

---

## Folder Structure

```
.agentic/
├── CONTEXT.md                  ← you are here (routing table only)
├── knowledge/                  ← stable reference, rarely changes
│   └── product_requirements_document.md  ← problem, vision, constraints, capabilities
├── decisions/                  ← architectural decisions (ADR format, flat numbered)
├── notes/                      ← technical notes, memoranda, implementation guides
├── planning/                   ← work to do (temporary — migrates to Jira)
│   ├── overview.md             ← epic index with status and dependency order
│   ├── active_epics/           ← one file per in-progress/planned epic with tasks
│   └── archived_epics/         ← completed and retired epics (do not pick up work)
└── reviews/                    ← transient session records (do not read unless prompted)
```

---

## Reading Order (agents)

1. This file (orient)
2. [knowledge/product_requirements_document.md](knowledge/product_requirements_document.md) (constraints and capabilities)
3. The one file relevant to the task at hand

Maximum 3 files for any question.
