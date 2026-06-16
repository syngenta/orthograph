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
- [ ] E8 (GQLAlchemy Query Catalogue) complete and tested
- [ ] E9 (GQLAlchemy Client Review) complete — composition pattern enforced
- [ ] E10 (Connection Ownership Audit) complete
- [ ] End-to-end pilot notebook exists and runs against a live database
- [ ] An agent reading `.agentic/` can make correct decisions without asking

---

## Epics

| Epic | Title | Priority | Status |
|------|-------|----------|--------|
| E1 | API Ergonomics & Developer Experience | High | planned |
| E2 | Code Deduplication & Internal Quality | Medium | planned |
| E3 | Documentation & Onboarding | High | planned |
| E4 | Extension Robustness & Consistency | Medium | planned |
| E5 | Visualization Package | High | **done** (2026-04-15) |
| E6 | Cypher Query Catalogue | — | **RETIRED → E16** |
| E7 | Pilot Readiness (gate) | High | planned |
| E8 | GQLAlchemy Query Catalogue | High | planned (blocked by E16) |
| E9 | GQLAlchemy Client Review | High | planned |
| E10 | Connection Ownership Audit | High | planned |
| E11 | Auto-Generated CRUD Operations | Medium | planned (E16 + E17 done — unblocked) |
| E12 | Shared Catalogue Interface Extraction | — | **RETIRED → E16** |
| E13 | Typed Query Catalogue Contract | — | **RETIRED → E16** |
| E14 | SQLAlchemy Backend Extension | Low | planned (not blocking — see E14 note) |
| E15 | Typed Cypher Catalogue Backend | — | **RETIRED → E16** |
| E16 | Query Catalogue — Typed Contract, Cypher Backend, Registry | High | **done** (2026-06-10) |
| E17 | CypherGenerator — Injection Hardening, Typed-Query Realignment & Inspector Alignment | High | **done** (2026-06-10) |
| E18 | Validation Correctness | High | planned |
| E19 | YAML Query Authoring — Scoping and Decision | Medium | planned (blocked by E16; needs team scoping session) |
| E20 | Technical Debt | Medium | planned (independent; cross-cutting) |
| E21 | Technical Debt — E2E Test Activation & Configuration | — | **RETIRED → E28** |
| E22 | E2E Test Coverage Audit & Shared-Contract Test Layer | — | **RETIRED → E28** |
| E23 | Inspector Backend-Behaviour Injection Interface | Medium | **RETIRED → E25** (the `api.database.inspect` + `CypherInspector` + `backends/loader` seam delivers E23's substance; ADR-011) |
| E24 | Synthetic Graph Data Generation | Medium | planned (was blocked by E23; now reads the GraphProfile contract directly — re-path via E25) |
| E25 | Capability Seams & Vendor-Backend Isolation (Refactor) | High | **done** (2026-06-11; branch `architecture-refactoring`; superseded parts of E2/E4/E9/E10/E22/E23 — see ADR-011) |
| E26 | CI Containerised E2E — Live-Database Tests in the Pipeline | — | **RETIRED → E28** |
| E27 | Symmetric Comparison — Compare Any Two Graph Descriptions | Medium | **done** (2026-06-15) |
| E28 | Testing Strategy — Activation Harness, Shared-Contract Layer, Shared Fixtures & CI | Medium | planned (independent; consolidates E21+E22+E26; delegation-ready tasks) |
| E29 | `__uid_field__` Hardening — definition-time validation, nullable rejection, phantom-key fallback removal | Medium | **done** (2026-06-15) |

---

## Dependency Graph

```
INDEPENDENT — can start immediately:
  E1   API Ergonomics
  E2   Code Deduplication
  E3   Documentation & Onboarding
  E9   GQLAlchemy Client Review [HITL]
  E16  Query Catalogue (unified — replaces E6/E12/E13/E15; unblocks E8/E11/E14/matterforge)
  E20  Tech Debt (cross-cutting; coordinate edits)
  E23  Inspector backend-behaviour injection interface (needs scoping session → ADR; coordinate
       with E4)
  E27  Symmetric Comparison (independent; generalises comparison/ to compare any two operands)
  E28  Testing Strategy (independent; consolidates E21+E22+E26 — activation harness, shared-contract
       layer, shared test fixtures, containerised CI; Wave A tasks need no live DB)
  E29  __uid_field__ Hardening (independent; T1 + T2 can be executed individually)

AFTER E23:
  E24  Synthetic Graph Data Generation (profile-driven mode requires consistent GraphProfile
       statistics contract across backends)

AFTER E2:
  E4   Extension Robustness

AFTER E10:
  E4   Extension Robustness (connection patterns settled)

AFTER E16:
  E8   GQLAlchemy Query Catalogue (exposes describe() for uniform introspection)
  E11  Auto-Generated CRUD (emits typed CypherReadQuery/WriteQuery instances) — also needed E17 (done)
  E14  SQLAlchemy Backend Extension (implements ReadQuery/WriteQuery/Executor from E16 STEP 1)
  E19  YAML Query Authoring scoping (real consumers exist; needs team session → ADR-009 → optional
       follow-on build epic)

DONE:
  E17  CypherGenerator hardening (closed identifier-injection risk; aligned generator + inspector
       queries to E16 typed contract; unblocked E11; closed "library does not eat its own cooking")
  E25  Capability Seams & Backend Isolation (vendor-free api/ seam, backends/<vendor>/ isolation,
       single dependency authority; superseded parts of E2/E4/E9/E10/E22/E23 — see ADR-011)
  E27  Symmetric Comparison (generalised comparison/ to compare any two operands; views.py +
       diff_rules.py; three public entry points; 2026-06-15)

GATE — requires E1, E2, E3, E4, E8, E9, E10, E11, E16 substantially complete:
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
E9 [HITL] ──► E10 ──┘                               │
                                                     │
E16 (unified) ──┬──► E8  (GQLAlchemy catalogue)     │
                ├──► E11 (CRUD auto-generation)      │
                ├──► E14 (SQLAlchemy backend)        │
                └──► E17 ✓ (generator hardening) ──► E11
                                                     ▼
                                                    E7 (gate)
```

---

## Execution Prioritisation

### Wave 1 (start immediately, in parallel)
- **E16** — Query Catalogue unified (critical path; unblocks E8/E11/E14 and matterforge Phase 2)
- **E9** — GQLAlchemy Client Review (HITL — unblocks E10)
- **E2** — Code Deduplication (unblocks E4)
- **E3** — Documentation (no dependencies)
- **E1** — API Ergonomics (independent)
- **E20** — Tech Debt (independent; cross-cutting — coordinate with epics editing the same modules)

### Wave 2 (after Wave 1)
- **E8** — GQLAlchemy Query Catalogue (after E16)
- **E10** — Connection Ownership Audit (after E9)
- **E4** — Extension Robustness (after E2 + E10)
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
- [E1 — API Ergonomics](active_epics/E1_api_ergonomics.md)
- [E2 — Code Deduplication](active_epics/E2_code_deduplication.md)
- [E3 — Documentation](active_epics/E3_documentation.md)
- [E4 — Extension Robustness](active_epics/E4_extension_robustness.md)
- [E7 — Pilot Readiness](active_epics/E7_pilot_readiness.md)
- [E8 — GQLAlchemy Query Catalogue](active_epics/E8_gqlalchemy_query_catalogue.md)
- [E9 — GQLAlchemy Client Review](active_epics/E9_gqlalchemy_client_review.md)
- [E10 — Connection Ownership Audit](active_epics/E10_connection_ownership_audit.md)
- [E11 — Auto-Generated CRUD Operations](active_epics/E11_auto_generated_crud.md)
- [E14 — SQLAlchemy Backend Extension](active_epics/E14_sqlalchemy_backend_extension.md)
- [E18 — Validation Correctness](active_epics/E18_validation_correctness.md)
- [E19 — YAML Query Authoring — Scoping and Decision](active_epics/E19_yaml_query_authoring.md)
- [E20 — Technical Debt](active_epics/E20_tech_debt.md)
- [E23 — Inspector Backend-Behaviour Injection Interface](active_epics/E23_inspector_backend_interface.md)
- [E24 — Synthetic Graph Data Generation](active_epics/E24_synthetic_graph_data_generation.md)

### Archived — [`archived_epics/`](archived_epics/) (do not pick up work from these)

**Done:**
- [E5 — Visualization](archived_epics/E5_visualization.md) *(done 2026-04-15)*
- [E16 — Query Catalogue Unified](archived_epics/E16_query_catalogue_unified.md) *(done 2026-06-10)*
- [E17 — CypherGenerator Hardening](archived_epics/E17_cypher_generator_hardening.md) *(done 2026-06-10)*
- [E25 — Capability Seams & Vendor-Backend Isolation (Refactor)](archived_epics/E25_capability_seams_backend_isolation.md) *(done 2026-06-11)*
- [E27 — Symmetric Comparison — Compare Any Two Graph Descriptions](archived_epics/E27_symmetric_comparison.md) *(done 2026-06-15)*
- [E29 — `__uid_field__` Hardening](archived_epics/E29_uid_field_hardening.md) *(done 2026-06-15)*

**Retired (superseded by E16):**
- [E6 — Cypher Query Catalogue](archived_epics/E6_query_catalogue.md)
- [E12 — Shared Catalogue Interface](archived_epics/E12_shared_catalogue_interface.md)
- [E13 — Typed Query Catalogue Contract](archived_epics/E13_typed_query_catalogue_contract.md)
- [E15 — Typed Cypher Catalogue Backend](archived_epics/E15_typed_cypher_backend.md)

**Retired (superseded by E28 — Testing Strategy):**
- [E21 — Technical Debt: E2E Test Activation & Configuration](archived_epics/E21_tech_debt_e2e_test_config.md)
- [E22 — E2E Test Coverage Audit & Shared-Contract Test Layer](archived_epics/E22_e2e_test_coverage_audit.md)
- [E26 — CI Containerised E2E — Live-Database Tests in the Pipeline](archived_epics/E26_ci_containerized_e2e.md)


---

## Deferred (not this phase)

Items explicitly out of scope for the current phase.

| Item | Rationale |
|------|-----------|
| OWL / RDF machine-readable ontology import | No concrete use case yet |
| Schema / Projection hierarchy (`GraphSchema` vs `GraphProjection`) | Large. Post-pilot. |
| Custom validators / checks (Pandera-style `Check`) | Deferred |
| Property value constraints (min/max/regex/enum) | Deferred |
| Schema composition / inheritance | Deferred |
| CLI tool | Future |
| Async driver support | Deferred |
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

`GqlAlchemyQueryCatalogue` (E8) is an independent backend catalogue (builder expressions,
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
2. **E8** implements the same split in the GQLAlchemy builder dialect (`Identifiers` → builder
   args; `Params` → `.where()` bindings), confirming ADR-010 in code.
