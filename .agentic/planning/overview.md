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
- [ ] E6 (Cypher Query Catalogue) complete and tested
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
| E4 | Extension Robustness & Consistency | Medium | planned (amended) |
| E5 | Visualization Package | High | **done** (2026-04-15) |
| E6 | Cypher Query Catalogue | High | planned (expanded) |
| E7 | Pilot Readiness (gate) | High | planned (updated) |
| E8 | GQLAlchemy Query Catalogue | High | **new** |
| E9 | GQLAlchemy Client Review | High | **new** |
| E10 | Connection Ownership Audit | High | **new** |
| E11 | Auto-Generated CRUD Operations | Medium | **new** |
| E12 | Shared Catalogue Interface Extraction | Medium | **new** (scope narrowed — see E13 note) |
| E13 | Typed Query Catalogue Contract | High | **new** |
| E14 | SQLAlchemy Backend Extension | High | **new** |
| E15 | Typed Cypher Catalogue Backend | High | **new** |

---

## Dependency Graph

```
INDEPENDENT — can start immediately:
  E1   API Ergonomics
  E2   Code Deduplication
  E3   Documentation & Onboarding
  E6   Cypher Query Catalogue
  E9   GQLAlchemy Client Review [HITL]

AFTER E2:
  E4   Extension Robustness (shared utilities first)

AFTER E6:
  E8   GQLAlchemy Query Catalogue (shares registry interface from E6)
  E11  Auto-Generated CRUD Operations (populates catalogues)

AFTER E6 + E8:
  E12  Shared Catalogue Interface (narrowed: string-key ABC only; typed contract is E13)

INDEPENDENT — typed catalogue track (can start immediately, parallel to E6):
  E13  Typed Query Catalogue Contract (ReadQuery/WriteQuery/Executor/ReadPort)

AFTER E13:
  E14  SQLAlchemy Backend Extension (SqlReadQuery/SqlWriteQuery/SqlExecutor)
  E15  Typed Cypher Catalogue Backend (CypherReadQuery/CypherExecutor)

AFTER E9:
  E10  Connection Ownership Audit (client review informs audit scope)

AFTER E10:
  E4   Extension Robustness (connection patterns settled)

GATE — requires E1, E2, E3, E4, E6, E8, E9, E10, E11 substantially complete:
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
E6 ──────┬──► E8 ──────┬──► E12                     │
         │              │                            │
         └──► E11 ◄────┘                             │
                                                     │
E13 ─────┬──► E14 (SQLAlchemy backend)               │
         └──► E15 (Typed Cypher backend)              │
                                                     ▼
                                                    E7 (gate)
```

---

## Execution Prioritisation

### Wave 1 (start immediately, in parallel)
- **E6** — Cypher Query Catalogue (critical path for both pilots)
- **E9** — GQLAlchemy Client Review (HITL — unblocks E10)
- **E2** — Code Deduplication (unblocks E4)
- **E3** — Documentation (no dependencies)
- **E13** — Typed Query Catalogue Contract (independent; unblocks matterforge + E14/E15)

### Wave 2 (after Wave 1 items complete)
- **E8** — GQLAlchemy Query Catalogue (after E6)
- **E10** — Connection Ownership Audit (after E9)
- **E1** — API Ergonomics (independent but lower urgency)
- **E4** — Extension Robustness (after E2 + E10)
- **E11** — Auto-Generated CRUD Operations (after E6)
- **E14** — SQLAlchemy Backend Extension (after E13)
- **E15** — Typed Cypher Catalogue Backend (after E13)

### Wave 3 (after Wave 2)
- **E12** — Shared Catalogue Interface (narrowed scope: string-key ABC after E6+E8; typed contract is E13)
- **E7** — Pilot Readiness gate (after all others)

---

## Epic Files

- [E1 — API Ergonomics](epics/E1_api_ergonomics.md)
- [E2 — Code Deduplication](epics/E2_code_deduplication.md)
- [E3 — Documentation](epics/E3_documentation.md)
- [E4 — Extension Robustness](epics/E4_extension_robustness.md)
- [E5 — Visualization](epics/E5_visualization.md) *(done)*
- [E6 — Cypher Query Catalogue](epics/E6_query_catalogue.md)
- [E7 — Pilot Readiness](epics/E7_pilot_readiness.md)
- [E8 — GQLAlchemy Query Catalogue](epics/E8_gqlalchemy_query_catalogue.md)
- [E9 — GQLAlchemy Client Review](epics/E9_gqlalchemy_client_review.md)
- [E10 — Connection Ownership Audit](epics/E10_connection_ownership_audit.md)
- [E11 — Auto-Generated CRUD Operations](epics/E11_auto_generated_crud.md)
- [E12 — Shared Catalogue Interface](epics/E12_shared_catalogue_interface.md) *(scope narrowed — see E13)*
- [E13 — Typed Query Catalogue Contract](epics/E13_typed_query_catalogue_contract.md) *(new)*
- [E14 — SQLAlchemy Backend Extension](epics/E14_sqlalchemy_backend_extension.md) *(new)*
- [E15 — Typed Cypher Catalogue Backend](epics/E15_typed_cypher_backend.md) *(new)*

---

## Deferred (not this phase)

Items explicitly out of scope for the current phase. Each is a candidate
for a future scoping session.

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
| Mixed catalogue (Cypher + ORM builders in one registry) | Requires scoping session |

---

## Architecture Note: Two Catalogue Tiers (E6/E8 vs E13/E14/E15)

orthograph now has two catalogue tiers serving different purposes:

| Tier | Epics | String/typed | Use case |
|------|-------|-------------|----------|
| **String-key** | E6, E8 | Named-string dispatch | YAML-configured, schema-validated, named Cypher/GQLAlchemy queries; suitable for external config |
| **Typed** | E13, E14, E15 | `ReadQuery[P,D]`/`WriteQuery[P,R]` generics | Domain-object-returning typed queries; IDE-navigable; suitable for application code (matterforge, mp-backend) |

E12's original scope (extract a shared ABC after E6+E8) is now narrowed: E13 **is** the typed
contract; E12 should focus on extracting the string-key tier ABC and acknowledging E13 as the
typed contract rather than duplicating it.
