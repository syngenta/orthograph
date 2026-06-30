# Planning Overview

> What we're building now, in what order, and what's parked for later.
> For permanent product boundaries, see [knowledge/product_requirements_document.md](../knowledge/product_requirements_document.md).

---

## Current Phase: v0.1.0 — Pilot Readiness

Deliver a stable, documented, agent-navigable library that two pilot project
teams can adopt with minimal friction: one using raw Cypher, one using GQLAlchemy.

### Success Criteria

- [ ] PRD complete and accurate
- [ ] README accurately describes the library
- [ ] E1–E4 quality epics complete
- [ ] E16 (Query Catalogue — unified) complete and tested
- [ ] E52 (GQLAlchemy backend — complete delivery & bug sweep) complete and tested *(consolidates the former E8 + E9)*
- [ ] Connection ownership (Constraint 13) enforced — inspectors via E25 (done); executor transaction ownership via E39 (ADR-028); GQLAlchemy client via E52 (was E9). *(E10 retired → E25/E39/E52.)*
- [ ] End-to-end pilot notebook exists and runs against a live database
- [ ] An agent reading `.agentic/` can make correct decisions without asking

---

## Epics

| Epic | Title | Priority | Status                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
|------|-------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| E1 | API Ergonomics & Developer Experience | High | **RETIRED** -> E55                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| E2 | Code Deduplication & Internal Quality | Medium | **done** (2026-06-24)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E3 | Documentation & Onboarding | High | **SUPERSEDED → E61** (its 3 tasks fold into E61 P1/P2: README rewrite, notebook titles, architecture diagram)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| E4 | Extension Robustness & Consistency | Medium | **done** (2026-06-24)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E5 | Visualization Package | High | **done** (2026-04-15)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E6 | Cypher Query Catalogue | — | **RETIRED → E16**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| E7 | Pilot Readiness (gate) | High | **done** (2026-06-24)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E8 | GQLAlchemy Query Catalogue | — | **RETIRED → E52** (consolidated into the single GQLAlchemy delivery epic; E8.1 base_models already done; E8.2–E8.5 become E52 Workstream D)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| E9 | GQLAlchemy Client Review | — | **RETIRED → E52** (consolidated into the single GQLAlchemy delivery epic; tasks become E52 Workstream C)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| E10 | Connection Ownership Audit | — | **RETIRED → E25 / E39 / E52** (inspectors made stateless by E25/ADR-011 D1; executor transaction ownership by E39/ADR-028; GQLAlchemy client by E52 — was E9 — 2026-06-24)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| E11 | Auto-Generated CRUD Operations | Medium | planned (E16 + E17 done — unblocked)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| E12 | Shared Catalogue Interface Extraction | — | **RETIRED → E16**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| E13 | Typed Query Catalogue Contract | — | **RETIRED → E16**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| E14 | SQLAlchemy Backend Extension | Low | planned (not blocking — see E14 note)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E15 | Typed Cypher Catalogue Backend | — | **RETIRED → E16**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| E16 | Query Catalogue — Typed Contract, Cypher Backend, Registry | High | **done** (2026-06-10)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E17 | CypherGenerator — Injection Hardening, Typed-Query Realignment & Inspector Alignment | High | **done** (2026-06-10)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E18 | Validation Correctness | High | **done** (2026-06-24) — E18.3 fixed (Mermaid `<br>`→space); E18.2/E18.4/E18.5 dissolved by architecture refactor; E18.1 reassigned to E17                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| E19 | YAML Query Authoring — Scoping and Decision | Medium | planned (blocked by E16; needs team scoping session)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| E20 | Technical Debt | Medium | **done** (2026-06-30; E20.1–E20.11 ADRs 048–049 + CONTEXT links; T0 + T7 extracted to E21/E22 for independent scheduling)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| E21 | `from __future__ import annotations` — Normalise Across Codebase | Low | planned ([planning/active_epics/E21_future_annotations.md](planning/active_epics/E21_future_annotations.md); cosmetic; three-option decision surface; extracted from E20 T0) |
| E22 | Cypher Validation — Backtick-Wrapped Parameter Detection | Medium | planned ([planning/active_epics/E22_backtick_param_validation.md](planning/active_epics/E22_backtick_param_validation.md); silent validation failure `` `$param` ``; regex lint in `_validate_declarative_cypher` + graphglot upstream request; extracted from E20 T7) |
| E23_old | Technical Debt — E2E Test Activation & Configuration *(was E21)* | — | **RETIRED → E28**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| E24_old | E2E Test Coverage Audit & Shared-Contract Test Layer *(was E22)* | — | **RETIRED → E28**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| E23 | Inspector Backend-Behaviour Injection Interface | Medium | **RETIRED → E25** (the `api.database.inspect` + `CypherInspector` + `backends/loader` seam delivers E23's substance; ADR-011)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| E24 | Synthetic Graph Data Generation | Medium | planned (was blocked by E23; now reads the GraphProfile contract directly — re-path via E25)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| E25 | Capability Seams & Vendor-Backend Isolation (Refactor) | High | **done** (2026-06-11; branch `architecture-refactoring`; superseded parts of E2/E4/E9/E10/E22/E23 — see ADR-011)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| E26 | CI Containerised E2E — Live-Database Tests in the Pipeline | — | **RETIRED → E28**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| E27 | Symmetric Comparison — Compare Any Two Graph Descriptions | Medium | **done** (2026-06-15)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E28 | Testing Strategy — Activation Harness, Shared-Contract Layer, Shared Fixtures & CI | Medium | planned (independent; consolidates former E21+E22+E26; delegation-ready tasks)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| E29 | `__uid_field__` Hardening — definition-time validation, nullable rejection, phantom-key fallback removal | Medium | **done** (2026-06-15)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E30 | Query Contract Decisions — E31 precursor decision session | — | **done** (2026-06-16; produced E31)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| E31 | Query Contract Ergonomics — Implementation | High | **ARCHIVED** (2026-06-29; E60/ADR-045 hard-renamed vocabulary; work items completed under current names by E34/E36/E38/E60)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| E32 | Bulk Write Query | Medium | planned                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| E33 | Query Contract Ergonomics v2 — `row_mapper` / `materialize` alternative + write return expansion | High | planned (blocked by E31; **Q1 superseded by E34 — ADR-025, `row_mapper` rejected; the default-`materialize` alternative was also withdrawn — `materialize` stays explicit**; Q2 superseded by E35; grill via `.agentic/reviews/E33_grill_prompt.md`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| E34 | RETURN→Output Alignment Correctness & ~~`materialize` Default~~ | High | **done** (2026-06-24; T1+T2 shipped + test-locked; T3 ADR-025 amended; T4 reverted; T5 deferred)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| E35 | Write Query Return-Row Echo — surface `RETURN` rows from `write()` | High | planned (blocked by E34; ADR-026 gated; supersedes E33 Q2)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| E36 | CypherQuery Naming Convergence + Class-Based Query Definitions | Medium | **done** (2026-06-17)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E37 | Simple Cypher Query — Shared Validation, Catalogue Parity, and Executor | Medium | **done** (2026-06-17)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E38 | CypherQuery Signature Collapse — `Params` + `Identifiers` Only | Medium | **done** (2026-06-18; collapsed three parameter representations to single typed source)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| E39 | Async Query Runner — `AsyncExecutor` & Caller-Owned Transactions | High | **done** (2026-06-29; ADR-028; AsyncExecutor + run_read_async/run_write_async; caller-owned transactions; e2e async tests; notebook 06.03)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| E40 | Conditional Cardinality — In-Memory (Phase 1) | High | **done** (2026-06-19; ADR-029; relationship-declared, endpoint-property-discriminated cardinality; in-memory enforcement + `UNVERIFIABLE` on profile)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E41 | Conditional Cardinality — Profiling & Live-DB Enforcement (Phase 2) | Medium | **done** (2026-06-22); partitioned per-pair observed stats as `BoundedDistribution` across 3 backends, on the reshaped model — E45 done)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| E42 | Unify Cardinality on UML Notation | Medium | **done** (2026-06-19; ADR-031; `CardinalitySpec.parse`⇄`.notation`, removes `Cardinality.*`/`EXACTLY`, one notation everywhere incl. YAML; `*` canonical for unbounded)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| E43 | General Conditional-Cardinality Partitioning | High | **done** (2026-06-19; ADR-032; partition by both endpoints, removes `by_kind`, definition-time guard — closes the silent-wrong-validation hole; coordinate with E42 on models.py)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| E44 | Neo4j `db.schema.*` Inspection Strategy — Reproducible Type Detection | Medium | **done** (2026-06-19; ADR-033; three-way APOC→SCHEMA→CYPHER detection; `use_apoc` deprecated in favour of `Neo4jInspectionStrategy` enum; landed before E41)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| E45 | GraphProfile Statistical Model & Comparison-Contract Reshape | High | **done** (2026-06-22; ADR-034; shared `BoundedDistribution`, presence-source split + `constraint_required`, bounded value distributions, full comparison matrix non-cardinality rows)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E46 | Populate `PropertyProfile.observed_type_counts` — Per-Type Value Counts for Prevalence-Aware Type Conformance | Medium | **done** (2026-06-24; ADR-035 + ADR-036; bounded Neo4j/Memgraph value scan populates `observed_type_counts` + `value_distribution`, prevalence-aware `PropertyTypeMismatchRule`, E46.6 pure-Cypher scalar histogram fallback; closes ADR-015 B1 TODO + both `inspector.py` TODOs; snapshot-consistency deviation tracked as E47)                                                                                                                                                                                                                                                                                                                                                                                                              |
| E47 | Inspector Snapshot Consistency — Single Read Transaction per Property Scan | Low | planned (do not start unless reconciliation invariant observed failing in practice; structural follow-on to E46.2; see ADR-035 §2)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| E48 | Configuration - Thread Tunable Knobs Through the Public API | Medium | planned (**unblocked** - E55 shipped the API; re-pathed 2026-06-28: inspector knobs already exposed via `profile.inspect_*`, so E48 narrows to the rule-threshold convenience + the config-object-vs-loose-kwargs decision (ADR-036); per-backend `_config` consolidation prep gated behind E56.3; no global settings/file/env layer this phase)                                                                                                                                                                                                                                                                                                                                                                                              |
| E49 | Partitioned Cardinality — Profile Rendering & One-Sided Discriminator Extraction | Medium | **done** (2026-06-25; T1 renders `*_partitioned_cardinality` in `profile_to_text`; T2 widened profiler `_extract_discriminators` for one-sided/wildcard discriminators with `null`-rendering wildcard query variants on Neo4j/Memgraph, mirroring the ADR-032 enforcement path; verified read-only against the live MatProt graph — `Operation.type` breakdowns now produced)                                                                                                                                                                                                                                                                                                                                                                 |
| E50 | Endpoint-Aware Relationship Identity | High | **done** (2026-06-24; ADR-037; relationship identity becomes the `(source, label, target)` triple — fixes the observed-side blending of distinct shapes; breaking across declaration/profiling/comparison/Cypher + YAML format; supersedes the identity implication of ADR-014, amends ADR-015 §address-space + ADR-034 §7/§8; delegation-ready tasks Opus/Sonnet/Haiku)                                                                                                                                                                                                                                                                                                                                                                      |
| E51 | Multi-Label Endpoint Relationship Shapes | Medium | planned (depends on E50; ADR-038 decision-only; scopes and resolves asymmetry: observed side can discover multi-label endpoint nodes (causing double-count bugs), but declared side cannot declare them; decision pending: first-class multi-label declaration vs. detect-and-harden-warn/error; E51.0 = scoping session + ADR)                                                                                                                                                                                                                                                                                                                                                                                                               |
| E52 | GQLAlchemy Backend — Complete Delivery & Bug Sweep | High | planned (consolidates+supersedes E8+E9; blocked by E16 (done) for catalogue/executor; client+codegen tasks independent; Workstreams D=delivery, C=composition-cleanup [HITL], W=bug sweep incl. the codegen `type`-clobber found 2026-06-25; Open Decision: reject vs map-and-preserve GQLAlchemy-reserved property names)                                                                                                                                                                                                                                                                                                                                                                                                                    |
| E53 | Self-Describing, Name-Aware Partitioned-Cardinality Key (single-property) | High | **done** (2026-06-25; ADR-039; reshapes `PartitionKey` to `{name:value}` maps + field → `list[PartitionedCardinalityRow]`; deletes the lossy string-key parse; name-aware comparison **and** profile↔profile diff; **single-property**, delivers the MatProt `Operation.type` value; amends ADR-034 §3/§7/§8 + ADR-032 §4; **no** declaration-time guard; blocks E54)                                                                                                                                                                                                                                                                                                                                                                         |
| E54 | Multi-Property Partitioned-Cardinality Profiling (producer generalisation) | Medium | **done** (2026-06-25; ADR-039 §5/§6; lifts the `len(keys)==1` producer cut — NetworkX multi-key read + variable-width Cypher grouping with N spliced discriminator names; closes the silent-drift hole by *capability* — no declaration-time guard; reuses E53's model/serialization/comparison/diff/visualization + their tests **unchanged**)                                                                                                                                                                                                                                                                                                                                                                                               |
| E55 | Public API Facade Redesign — Intent-Named Capability Surface | High | **done** (2026-06-26; restructured `api/` into 7 intent-named modules — `definition`/`profile`/`compare`/`queries`/`execution`/`backends`/`visualization` — split the overloaded `validate`, surfaced the shipped `compare.profiles`/`compare.definitions` (US 30/31), returned an assembled `QueryCatalogue` from `load_catalogue`, added Option-B backend discovery; removed the redundant `api.model`/`api.database` modules (clean break — no shims; facade fixed before any external dependency relies on it, all internal consumers migrated); all tests/mypy/pre-commit green; E48 unblocked)                                                                                                                                          |
| E56 | Capability Readability Distillation — Make Validation / Query / Profiling / Comparison Read Cleanly | High | **done** (2026-06-28; ADR-042; W1–W5 complete; four headline capabilities distilled; 7 radon targets ≤ B; contracts named (`RuleContext.extra`, validation tuple-keys, cardinality convention); duplication removed (inspector helpers→`CypherInspector`, presence-rule boilerplate, executor prologue seam); dead code deleted; LOC trend down; all tests green; no test/behaviour/signature changes)                                                                                                                                                                                                                                                                                                                                        |
| E57 | Value-Distribution Cross-Backend Parity — Review & Verify | Medium | planned (review-only, no fix; origin E56.3; `value_distribution` histogram diverges **APOC-Neo4j vs Memgraph & Neo4j-no-APOC** because of the DB-side key — `apoc.convert.toJson` list-safe vs `toStringOrNull` scalar-only — not the byte-identical `_build_value_distribution`; characterises output/algorithm consequences + causes, audits consumers, corrects the misleading "Memgraph vs Neo4j" docstring, writes findings note + decision surface; lists 6 pre-fix verification items; `observed_type_counts` parity-correct and untouched)                                                                                                                                                                                            |
| E58 | Comparison Dispatch & Rule Symmetry — Scope & Decide | Low | **done** (2026-06-29; ADR-044; both items verdict **no change**: (A) the satisfaction-path `left`/`right` inversion is the correct resting state — removing it would re-key all 11 satisfaction rules to eliminate one call-site swap, and `RuleContext` cannot carry declared/observed role fields because the diff path treats left/right as neutral positional; (B) the `rules.py`↔`diff_rules.py` type/operand-kind symmetry is coincidental — the one genuinely shared piece `db_type_to_python` was already in `type_mapping.py`; remaining logic is semantically divergent and a hoist would add indirection; E58.1 + E58.2 closed as not needed; docstrings in `engine.py` + `diff_rules.py` updated with self-documenting rationale) |
| E59 | Query Validation Public API — Two Phases × Two Input Grades | Medium | **done** (2026-06-29) — ADR-043; six public verbs (2×2 matrix); `validate_query` removed; primitives privatized; suite green, mypy clean
| E60 | Query Shape Alignment — One Vocabulary Across Typed / Cypher / ORM Paths | Medium | **done** (2026-06-29; ADR-045; E60.1–E60.5 complete; typed path renamed to `params_schema`/`identifiers_schema`/`query_id`; one `build(params)` signature; deleted `_query_shape` reconciliation + adapters; all tests green; E39 unblocked) |
| E61 | Documentation — Read the Docs Site (Diátaxis × Three Audiences) | High | **ARCHIVED** (2026-06-30; ADR-046; supersedes E3; phased P0–P4 complete — walking skeleton, front door + reference, tutorials + doctest wired, explanation architecture + advanced topics documented; notebooks compiled in place via myst-nb; pydata-sphinx-theme + RTD deployed)                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| E62 | Simple-Path Cypher Execution Surface — `CypherQueryExecutor` & `run_cypher_*` Verbs | High | **done** (2026-06-29; ADR-047; CypherQueryExecutor/AsyncCypherQueryExecutor + run_cypher_* verbs; removed all simple-path type: ignore + the file-wide mypy disable; async simple-path e2e restored) |

---

## Dependency Graph

```
INDEPENDENT — can start immediately:
  E1   API Ergonomics
  E2   Code Deduplication
  E3   Documentation & Onboarding
  E16  Query Catalogue (unified — replaces E6/E12/E13/E15; unblocks E11/E14/E52/matterforge)
  E20  Tech Debt (cross-cutting; coordinate edits)
  E23  Inspector backend-behaviour injection interface (needs scoping session → ADR; coordinate
       with E4)
  E27  Symmetric Comparison (independent; generalises comparison/ to compare any two operands)
  E28  Testing Strategy (independent; consolidates E21+E22+E26 — activation harness, shared-contract
       layer, shared test fixtures, containerised CI; Wave A tasks need no live DB)
   E29  __uid_field__ Hardening (independent; T1 + T2 can be executed individually)
  E40  Conditional Cardinality — In-Memory (independent; ADR-029; additive to graph_definition/;
       blocks E41) ✓ done (2026-06-19)
  E44  Neo4j db.schema.* Inspection Strategy (independent; ADR-033; third property-type strategy
        APOC→db.schema.*→pure-Cypher; backend-scoped to backends/neo4j/; landed before E41)
        ✓ done (2026-06-19)
  E50  Endpoint-Aware Relationship Identity (independent; ADR-037; relationship identity becomes
         the (source, label, target) triple — fixes the observed-side blending of distinct shapes;
         breaking across graph_definition/ + graph_profile/ + comparison/ + cypher/ + io/yaml;
         supersedes the identity implication of ADR-014, amends ADR-015 §address-space and
         ADR-034 §7/§8; E50.0 writes ADR-037 first; delegation-ready Opus/Sonnet/Haiku)
         ✓ done (2026-06-24)
   E51  Multi-Label Endpoint Relationship Shapes (depends on E50; ADR-038 scoping decision; observed
         side can discover multi-label endpoint nodes (causing double-count bugs in profiles), but
         declared side cannot declare them (NodeModel.__label__ is scalar); decision pending:
         first-class multi-label declaration vs. detect-and-harden-warn/error; E51.0 = scoping
         session + ADR; see epic file for open questions)

AFTER E16 (done) — GQLAlchemy:
   E52  GQLAlchemy Backend — Complete Delivery & Bug Sweep (consolidates+supersedes E8+E9 into one
         coherent unit; Workstream D = catalogue + executor + notebook (was E8.2–E8.5; E8.1
         base_models already done); Workstream C = remove persistence ownership from GqlAlchemyClient
         [HITL, Constraint 13] (was E9); Workstream W = bug sweep, incl. the codegen `type`-clobber
         found 2026-06-25 — a user property named `type` on a RelationshipModel is overwritten by the
         GQLAlchemy rel-label at codegen.py:127. Open Decision: reject vs map-and-preserve the full
         GQLAlchemy-reserved-attribute set; fix stays in backends/gqlalchemy/ — Constraint 1 forbids
         it in graph_definition/. Client+codegen tasks independent; catalogue/executor need E16 (done))

AFTER E40:
  E45  GraphProfile Statistical Model & Comparison-Contract Reshape (ADR-034; shared
        BoundedDistribution, presence-source split + constraint_required, bounded value
        distributions, full comparison matrix; breaking reshape — no external consumers;
        BLOCKS E41)
        ✓ done (2026-06-22)
  E41  Conditional Cardinality — Profiling (ADR-030 + ADR-034; per-pair observed statistics
        as BoundedDistribution + live-DB enforcement across NetworkX/Neo4j/Memgraph;
        runs on the reshaped model — E45 done)
  E42  Unify Cardinality on UML Notation (ADR-031; CardinalitySpec.parse⇄.notation, removes
        Cardinality.*/EXACTLY, one notation everywhere incl. YAML — refactor, mostly mechanical)
        ✓ done (2026-06-19)
  E43  General Conditional-Cardinality Partitioning (ADR-032; partition enforcement by BOTH
       endpoints' discriminators, removes by_kind sugar, definition-time guard — closes the
       silent-wrong-validation hole; coordinate with E42 on models.py)

AFTER E41 + E49 (partitioned cardinality shipped):
   ✓ E54  Multi-Property Partitioned-Cardinality Profiling (**done** 2026-06-25; ADR-039 §5/§6; lifts
         the len(keys)==1 producer cut — NetworkX multi-key + variable-width Cypher grouping with
         N safely-spliced discriminator names; closes the silent-drift hole by capability, not a
         construction-time guard; reuses E53's model/comparison/diff/viz + tests unchanged)

AFTER E44 + E45 (both done):
  E46  Populate observed_type_counts (closes ADR-015 B1 TODO + the two backends/neo4j/inspector.py
       TODOs; new bounded value→type→count aggregation across 3 backends, registered in all three
       E44 catalogues; refines PropertyTypeMismatchRule from "a wrong type exists" to "how
       prevalent"; rides E45 bounded-sampling opt-in; E46.0 produces an ADR first)
       ✓ done (2026-06-24)

AFTER E46.2 (or when reconciliation invariant observed failing):  E47  Inspector Snapshot Consistency (structural follow-on to E46.2; enforces ADR-035 §2
       reconciliation invariant by shared read transaction; low priority — start only if the
       invariant breaks in production or deployment profile changes to write-heavy)

AFTER the new-API epic (E55 — done):
  E48  Configuration (UNBLOCKED — E55 shipped the API and `profile.inspect_*` already exposes
       the inspector knobs; E48 narrows to the rule-threshold convenience + the
       config-object-vs-loose-kwargs ergonomic decision; E48.0 ADR-036 first; per-backend
       `_config` consolidation prep gated behind E56.3; NO global settings/file/env layer this
        phase — ADR-035 §1 minimal-knob bias)

AFTER E60 (done):
   E39  Async Query Runner (ADR-028; Wave 0 realigns sync write() to caller-owned transactions, Wave 1 adds the parallel AsyncExecutor path; query runner only — inspection stays sync; unblocked by E60)

AFTER E23:
  E24  Synthetic Graph Data Generation (profile-driven mode requires consistent GraphProfile
       statistics contract across backends)

AFTER E2:
  E4   Extension Robustness

AFTER E16:
  E11  Auto-Generated CRUD (emits typed CypherReadQuery/WriteQuery instances) — also needed E17 (done)
  E14  SQLAlchemy Backend Extension (implements ReadQuery/WriteQuery/Executor from E16 STEP 1)
  E19  YAML Query Authoring scoping (real consumers exist; needs team session → ADR-009 → optional
       follow-on build epic)
  E52  GQLAlchemy Backend — Complete Delivery & Bug Sweep (Workstream D catalogue/executor need E16;
       Workstream C client cleanup [HITL] + Workstream W bug sweep are independent; consolidates E8+E9)

DONE:
  E17  CypherGenerator hardening (closed identifier-injection risk; aligned generator + inspector
       queries to E16 typed contract; unblocked E11; closed "library does not eat its own cooking")
  E25  Capability Seams & Backend Isolation (vendor-free api/ seam, backends/<vendor>/ isolation,
       single dependency authority; superseded parts of E2/E4/E9/E10/E22/E23 — see ADR-011)
  E27  Symmetric Comparison (generalised comparison/ to compare any two operands; views.py +
       diff_rules.py; three public entry points; 2026-06-15)

GATE — requires E1, E2, E3, E4, E11, E16, E52 substantially complete:
  E7   Pilot Readiness
```

### Visual Dependency Map

```
E1 ─────────────────────────────────────────────────┐
E2 ──────────────────┬──────────────────────────────┤
E3 ─────────────────────────────────────────────────┤
                     │                               │
                     ▼                               │
                     E4 ─────────────────────────────┤
                     ▲                               │
                     │                               │
E2 ──────────────────┘                               │
E52 [HITL] (GQLAlchemy backend — complete delivery)  │
E16 (unified) ──┬──► E52 (GQLAlchemy catalogue/exec) │
                ├──► E11 (CRUD auto-generation)      │
                ├──► E14 (SQLAlchemy backend)        │
                └──► E17 ✓ (generator hardening) ──► E11
                                                     ▼
                                                    E7 (gate)
```

---

## Execution Prioritisation

### Wave 1 (start immediately, in parallel)
- **E16** — Query Catalogue unified (critical path; unblocks E11/E14/E52 and matterforge Phase 2)
- **E52** — GQLAlchemy Backend, Workstream C+W (HITL client cleanup + bug sweep incl. the codegen `type`-clobber; independent of E16)
- **E2** — Code Deduplication (unblocks E4)
- **E3** — Documentation (no dependencies)
- **E1** — API Ergonomics (independent)
- **E20** — Tech Debt (independent; cross-cutting — coordinate with epics editing the same modules)

### Wave 2 (after Wave 1)
- **E52** — GQLAlchemy Backend, Workstream D (catalogue + executor + notebook; after E16)
- **E4** — Extension Robustness (after E2)
- **E11** — Auto-Generated CRUD Operations (after E16 + E17 — both done)
- **E14** — SQLAlchemy Backend Extension (after E16, only when a second project needs it)
- **E17** — CypherGenerator Hardening — **done** (2026-06-10)

### Wave 3 (after Wave 2)
- **E7** — Pilot Readiness gate (after all others)

---

## Epic Files

Active epics live in [`active_epics/`](active_epics/); completed and retired epics are moved to
[`archived_epics/`](archived_epics/) (do not pick up work from archived epics).

### Active — [`active_epics/`](active_epics/)
- [E1 — API Ergonomics](archived_epics/E1_api_ergonomics.md)
- [E11 — Auto-Generated CRUD Operations](active_epics/E11_auto_generated_crud.md)
- [E14 — SQLAlchemy Backend Extension](active_epics/E14_sqlalchemy_backend_extension.md)
- [E20 — Technical Debt](active_epics/E20_tech_debt.md)
- [E23 — Inspector Backend-Behaviour Injection Interface](active_epics/E23_inspector_backend_interface.md)
- [E24 — Synthetic Graph Data Generation](active_epics/E24_synthetic_graph_data_generation.md)
- [E35 — Write Query Return-Row Echo](active_epics/E35_write_query_return_rows.md)
- [E39 — Async Query Runner](active_epics/E39_async_query_runner.md)
- [E47 — Inspector Snapshot Consistency — Single Read Transaction per Property Scan](active_epics/E47_inspector_snapshot_consistency.md)
- [E48 — Configuration — Thread Tunable Knobs Through the Public API](active_epics/E48_configuration.md)
- [E51 — Multi-Label Endpoint Relationship Shapes](active_epics/E51_multi_label_endpoint_relationship_shapes.md)
- [E52 — GQLAlchemy Backend — Complete Delivery & Bug Sweep](active_epics/E52_gqlalchemy_complete_delivery_and_bug_sweep.md) *(consolidates+supersedes E8+E9)*
- [E57 — Value-Distribution Cross-Backend Parity — Review & Verify](active_epics/E57_value_distribution_parity_review.md) *(review-only; no fix; origin E56.3)*
- [E58 — Comparison Dispatch & Rule Symmetry — Scope & Decide](active_epics/E58_comparison_dispatch_symmetry.md) *(decision-first; no fix until ADR; origin E56 W2 deferred Note — `left`/`right` inversion + rules↔diff_rules symmetry)*
- [E59 — Query Validation Public API — Two Phases × Two Input Grades](archived_epics/E59_query_validation_public_api.md) *(done 2026-06-29; ADR-043; six verbs, 2×2 matrix, `validate_query` removed)*
- [E61 — Documentation — Read the Docs Site (Diátaxis × Three Audiences)](active_epics/E61_documentation_readthedocs.md) *(ADR-046; supersedes E3; P0 walking-skeleton review gate → P1 front-door+reference → P2 tutorials → P3 how-to+doctest → P4 explanation; notebooks compiled in place as the single tutorial source; reference = public surface only; delegation-ready tasks tagged opus/sonnet/haiku/qwen)*

### Archived — [`archived_epics/`](archived_epics/) (do not pick up work from these)

**Done:**
- [E5 — Visualization](archived_epics/E5_visualization.md) *(done 2026-04-15)*
- [E16 — Query Catalogue Unified](archived_epics/E16_query_catalogue_unified.md) *(done 2026-06-10)*
- [E17 — CypherGenerator Hardening](archived_epics/E17_cypher_generator_hardening.md) *(done 2026-06-10)*
- [E25 — Capability Seams & Vendor-Backend Isolation (Refactor)](archived_epics/E25_capability_seams_backend_isolation.md) *(done 2026-06-11)*
- [E27 — Symmetric Comparison — Compare Any Two Graph Descriptions](archived_epics/E27_symmetric_comparison.md) *(done 2026-06-15)*
- [E29 — `__uid_field__` Hardening](archived_epics/E29_uid_field_hardening.md) *(done 2026-06-15)*
- [E36 — CypherQuery Naming Convergence + Class-Based Query Definitions](archived_epics/E36_cypher_query_naming_and_spec_class.md) *(done 2026-06-17)*
- [E37 — Simple Cypher Query — Shared Validation, Catalogue Parity, and Executor](archived_epics/E37_simple_cypher_query_shared_validation.md) *(done 2026-06-17; `CypherQueryBase` fate is a separate follow-on discussion)*
- [E38 — CypherQuery Signature Collapse — `Params` + `Identifiers` Only](archived_epics/E38_cypher_query_params_collapse.md) *(done 2026-06-18; collapsed three-into-one via JSON-Schema round-trip and ADR-027)*
- [E43 — General Conditional-Cardinality Partitioning](archived_epics/E43_general_conditional_cardinality_partitioning.md) *(done 2026-06-19)*
- [E44 — Neo4j `db.schema.*` Inspection Strategy](archived_epics/E44_neo4j_db_schema_inspection_strategy.md) *(done 2026-06-19)*
- [E42 — Unify Cardinality on UML Notation](archived_epics/E42_unify_cardinality_uml_notation.md) *(done 2026-06-19)*
- [E45 — GraphProfile Statistical Model & Comparison-Contract Reshape](archived_epics/E45_graphprofile_statistical_model_reshape.md) *(done 2026-06-22; ADR-034; shared `BoundedDistribution`, presence-source split + `constraint_required`, bounded value distributions, full comparison matrix non-cardinality rows)*
- [E34 — RETURN→Output Alignment Correctness](archived_epics/E34_return_output_alignment_correctness.md) *(done 2026-06-24; T1+T2 ship PRD silent-mismatch guarantee; test-locked; T4 reverted; ADR-025)*
- [E18 — Validation Correctness](archived_epics/E18_validation_correctness.md) *(done 2026-06-24; E18.3 fixed — Mermaid pipe-label `<br>`→space; E18.2/E18.4/E18.5 dissolved by arch refactor; E18.1 reassigned to E17)*
- [E2 — Code Deduplication & Internal Quality](archived_epics/E2_code_deduplication.md) *(done 2026-06-24)*
- [E4 — Extension Robustness & Consistency](archived_epics/E4_extension_robustness.md) *(done 2026-06-24)*
- [E7 — Pilot Readiness (gate)](archived_epics/E7_pilot_readiness.md) *(done 2026-06-24)*
- [E46 — Populate `observed_type_counts` — Per-Type Value Counts](archived_epics/E46_observed_type_counts_population.md) *(done 2026-06-24; ADR-035 + ADR-036; bounded Neo4j/Memgraph value scan populates `observed_type_counts` + `value_distribution`, prevalence-aware `PropertyTypeMismatchRule`, E46.6 pure-Cypher scalar histogram fallback; snapshot-consistency deviation tracked as E47)*
- [E6 — Cypher Query Catalogue](archived_epics/E6_query_catalogue.md)
- [E12 — Shared Catalogue Interface](archived_epics/E12_shared_catalogue_interface.md)
- [E13 — Typed Query Catalogue Contract](archived_epics/E13_typed_query_catalogue_contract.md)
- [E15 — Typed Cypher Catalogue Backend](archived_epics/E15_typed_cypher_backend.md)
- [E50 — Endpoint-Aware Relationship Identity](archived_epics/E50_endpoint_aware_relationship_identity.md) *(done 2026-06-24)*
- [E53 — Self-Describing, Name-Aware Partitioned-Cardinality Key (single-property)](archived_epics/E53_self_describing_partition_key.md) *(done 2026-06-25; ADR-039; reshapes `PartitionKey` to `{name:value}` maps + field → `list[PartitionedCardinalityRow]`, deletes the lossy string-key parse, name-aware comparison + profile↔profile diff; single-property delivers the MatProt `Operation.type` value; amends ADR-034 §3/§7/§8 + ADR-032 §4; blocks E54)*
- [E54 — Multi-Property Partitioned-Cardinality Profiling](archived_epics/E54_multi_property_partition_profiling.md) *(done 2026-06-25; ADR-039 §5/§6; lifts the `len(keys)==1` producer cut — NetworkX multi-key read + variable-width Cypher grouping with N safely-spliced discriminator names; closes the silent-drift hole by **capability** — no declaration-time guard; reuses E53's model/serialization/comparison/diff/visualization + their tests **unchanged**)*
- [E55 — Public API Facade Redesign — Intent-Named Capability Surface](archived_epics/E55_public_api_facade_redesign.md) *(done 2026-06-26; ADR-016/017; restructured `api/` into 7 intent-named modules — `definition`/`profile`/`compare`/`queries`/`execution`/`backends`/`visualization` — split the overloaded `validate`, surfaced the shipped `compare.profiles`/`compare.definitions` (US 30/31), returned an assembled `QueryCatalogue` from `load_catalogue`, added Option-B backend discovery; removed the redundant `api.model`/`api.database` modules (clean break — no shims; facade fixed before any external dependency relies on it, all internal consumers migrated); all tests/mypy/pre-commit green; E48 unblocked)*
- [E56 — Capability Readability Distillation — Make Validation / Query / Profiling / Comparison Read Cleanly](archived_epics/E56_internal_logic_distillation.md) *(done 2026-06-28; ADR-042; W1–W5 complete; four headline capabilities distilled; 7 radon targets ≤ B; contracts named; duplication removed; dead code deleted; LOC trend down; all tests green; no test/behaviour/signature changes)*
- [E59 — Query Validation Public API — Two Phases × Two Input Grades](archived_epics/E59_query_validation_public_api.md) *(done 2026-06-29; ADR-043; six public verbs (2×2 matrix); `validate_query` removed; primitives privatized; suite green, mypy clean)*
- [E60 — Query Shape Alignment — One Vocabulary Across Typed / Cypher / ORM Paths](archived_epics/E60_query_shape_alignment.md) *(done 2026-06-29; ADR-045; E60.1–E60.5 complete; typed path renamed to `params_schema`/`identifiers_schema`/`query_id`; one `build(params)` signature; deleted `_query_shape` reconciliation + adapters; all tests green; E39 unblocked)*

**Retired (superseded by E28 — Testing Strategy):**
- [E21 — Technical Debt: E2E Test Activation & Configuration](archived_epics/E21_tech_debt_e2e_test_config.md)
- [E22 — E2E Test Coverage Audit & Shared-Contract Test Layer](archived_epics/E22_e2e_test_coverage_audit.md)
- [E26 — CI Containerised E2E — Live-Database Tests in the Pipeline](archived_epics/E26_ci_containerized_e2e.md)

**Superseded (folded into E61 — Documentation):**
- [E3 — Documentation & Onboarding](archived_epics/E3_documentation.md) *(superseded by ADR-046 + E61; E3.1 README rewrite → E61.1.4, E3.2 notebook titles → E61.2.1, E3.3 architecture diagram → E61.2.3; left in active_epics as a pointer, do not pick up directly)*

**Retired (consolidated into E52 — GQLAlchemy Backend, Complete Delivery & Bug Sweep):**
- [E8 — GQLAlchemy Query Catalogue](archived_epics/E8_gqlalchemy_query_catalogue.md) *(retired 2026-06-25 → E52 Workstream D; E8.1 base_models already done)*
- [E9 — GQLAlchemy Client Review](archived_epics/E9_gqlalchemy_client_review.md) *(retired 2026-06-25 → E52 Workstream C)*

**Retired (superseded by E25 + E39 + E52 — connection-ownership work re-homed):**
- [E10 — Connection Ownership Audit](archived_epics/E10_connection_ownership_audit.md) *(retired 2026-06-24; inspectors made stateless by E25/ADR-011 D1; executor transaction ownership by E39/ADR-028; GQLAlchemy client by E52 — was E9)*


---

## Deferred (not this phase)

Items explicitly out of scope for the current phase.

| Item | Rationale |
|------|-----------|
| OWL / RDF machine-readable ontology import | No concrete use case yet |
| Schema / Projection hierarchy (`GraphSchema` vs `GraphProjection`) | Large. Post-pilot. |
| Custom validators / checks (Pandera-style `Check`) | Deferred |
| Property value constraints (min/max/regex/enum) | Deferred. *(Distinct from conditional cardinality — E40/ADR-029 uses a property value to **select a count bound**, it does not constrain the property's value.)* |
| Schema composition / inheritance | Deferred |
| CLI tool | Future |
| Async driver support | Query runner delivered (E39 / ADR-028 — `AsyncExecutor`, `query_async`/`execute_async`, caller-owned transactions); async inspection (`inspect`/`validate`) deferred |
| Historical profile storage / trend analysis | Monitoring platform concern |
| Rich output models (nested, computed projections) | Post-pilot, after flat types validated |
| Mixed catalogue (all three backends in one registry) + Catalogue-vs-Repository boundary | Requires scoping session → ADR. See "Scoping task" below. |

---

## Scoping task: Catalogue-vs-Repository boundary + mixed-backend catalogue

> **Type:** Architecture decision (produces an ADR in `.agentic/decisions/`)
> **Origin:** E16 scoping session 2026-06-10
> **Status:** not started — do NOT implement until the ADR is recorded

**Two related, unresolved questions surfaced while building the typed catalogue:**

1. **Catalogue vs Repository.** The `QueryCatalogue` is a flat, introspectable
   registry keyed by query name. Applications adopting this library are expected to
   also have **repositories** that group operations around an aggregate
   (`SampleRepository.by_protocol()`, `.create()`). These are different layers, and the
   working hypothesis (to be confirmed in the ADR) is:
   - The catalogue is a **build-time registry + introspection** surface, not a runtime
     dispatch table.
   - Repositories hold **`ReadPort`s** (bound at the composition root), never call the
     catalogue by string name (that would re-introduce the string-key dispatch E16
     deliberately removed).
   - The two meet only at the composition root: register queries → bind to ports →
     inject ports into repositories.
   - *Rejected alternative to record:* repository-calls-catalogue-by-name.

2. **Mixed-backend catalogue.** One `QueryCatalogue` can already hold queries from
   different backends (proven by `tests/catalogue/test_port_swap.py` and the
   backend-filtered `describe()`/`names()`). Confirm whether a single mixed registry is
   the intended end state, or whether per-backend catalogues are preferred, and why.

**Acceptance criteria:**
- [ ] An ADR in `.agentic/decisions/` records the catalogue-vs-repository layering and
      the rejected "repository-calls-catalogue-by-name" alternative.
- [ ] The ADR states the mixed-backend-catalogue decision (single mixed registry vs
      per-backend) with rationale.
- [ ] CONTEXT.md / PRD cross-link the ADR if it changes a documented boundary.
- [ ] No production code is written under this task — it is decision-only.

---

## Architecture Note: The Typed Query Catalogue (E16)

E16 builds a **single, typed query catalogue** in strict order:
**(1) Read/Write generics + Executor → (2) Cypher backend → (3) QueryCatalogue**.

| | `QueryCatalogue` (built in E16) |
|---|---|
| **Register** | `register_read(MyQuery())` — a typed `ReadQuery`/`WriteQuery` instance |
| **Call site** | `executor.read(query, params)` → statically typed `list[D]` |
| **Return type** | statically known domain type (NodeModel or projection) |
| **Validation** | params at the boundary (R4); build() pure, no DB (R1) |
| **Materialise** | each query owns a type-checked `materialize()` (R3) |
| **Introspection** | `describe() → list[QueryDescription]` |
| **Swappable reads** | `ReadPort` + composition-root binding |

**YAML is NOT built in E16.** The retired E6 offered a YAML/string-key catalogue; whether YAML
returns (and in which of three forms) is an explicit **OPEN DECISION** documented in the E16 epic.
The typed core is built first; the YAML decision is made afterwards, on evidence, only if a real
consumer needs config-driven queries — and only in a form that does not reintroduce string-key
dispatch or untyped returns into application code.

`GqlAlchemyQueryCatalogue` (E52 Workstream D) is an independent backend catalogue (builder expressions,
Python-only) that should also expose `describe()` for uniform introspection.

---

## Decision Note: Declared identifier parameters (ADR-009 / ADR-010) — Accepted 2026-06-10

ADR-010 (declared `Identifiers`/`Params` split for typed queries) and its dependant ADR-009
(inspector query alignment) are **Accepted**. The backend-neutrality gate that blocked them closed
after validating the split against the GQLAlchemy builder surface — see
`.agentic/reviews/2026-06-10-graphorm-adr-validation-report.md`.

Execution order this implies:
1. **E17 T1** (`validate_identifier`) → **E17 T2.5** (adds `Identifiers` + `<<placeholder>>` to the
   Cypher bases; generic `typed.py` untouched) → **E17 T4/T8** (generator + inspector use it).
   **— E17 complete (2026-06-10); ADR-008/009/010 Accepted.**
2. **E52** (Workstream D, was E8) implements the same split in the GQLAlchemy builder dialect (`Identifiers` → builder
   args; `Params` → `.where()` bindings), confirming ADR-010 in code.
