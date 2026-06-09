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
| E11 | Auto-Generated CRUD Operations | Medium | planned (blocked by E16) |
| E12 | Shared Catalogue Interface Extraction | — | **RETIRED → E16** |
| E13 | Typed Query Catalogue Contract | — | **RETIRED → E16** |
| E14 | SQLAlchemy Backend Extension | High | planned (blocked by E16) |
| E15 | Typed Cypher Catalogue Backend | — | **RETIRED → E16** |
| E16 | Query Catalogue — Unified Interface, Cypher Model, Typed Backends | High | **active** |

---

## Dependency Graph

```
INDEPENDENT — can start immediately:
  E1   API Ergonomics
  E2   Code Deduplication
  E3   Documentation & Onboarding
  E9   GQLAlchemy Client Review [HITL]
  E16  Query Catalogue (unified — replaces E6/E12/E13/E15; unblocks E8/E11/E14/matterforge)

AFTER E2:
  E4   Extension Robustness

AFTER E9:
  E10  Connection Ownership Audit

AFTER E10:
  E4   Extension Robustness (connection patterns settled)

AFTER E16:
  E8   GQLAlchemy Query Catalogue (uses DescribableCatalogue from E16 T8)
  E11  Auto-Generated CRUD (targets StringKeyCypherCatalogue from E16 T4)
  E14  SQLAlchemy Backend Extension (implements ReadQuery from E16 T5)

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
                └──► E14 (SQLAlchemy backend)        │
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

### Wave 2 (after Wave 1)
- **E8** — GQLAlchemy Query Catalogue (after E16)
- **E10** — Connection Ownership Audit (after E9)
- **E4** — Extension Robustness (after E2 + E10)
- **E11** — Auto-Generated CRUD Operations (after E16)
- **E14** — SQLAlchemy Backend Extension (after E16)

### Wave 3 (after Wave 2)
- **E7** — Pilot Readiness gate (after all others)

---

## Epic Files

### Active
- [E1 — API Ergonomics](epics/E1_api_ergonomics.md)
- [E2 — Code Deduplication](epics/E2_code_deduplication.md)
- [E3 — Documentation](epics/E3_documentation.md)
- [E4 — Extension Robustics](epics/E4_extension_robustness.md)
- [E5 — Visualization](epics/E5_visualization.md) *(done)*
- [E7 — Pilot Readiness](epics/E7_pilot_readiness.md)
- [E8 — GQLAlchemy Query Catalogue](epics/E8_gqlalchemy_query_catalogue.md)
- [E9 — GQLAlchemy Client Review](epics/E9_gqlalchemy_client_review.md)
- [E10 — Connection Ownership Audit](epics/E10_connection_ownership_audit.md)
- [E11 — Auto-Generated CRUD Operations](epics/E11_auto_generated_crud.md)
- [E14 — SQLAlchemy Backend Extension](epics/E14_sqlalchemy_backend_extension.md)
- **[E16 — Query Catalogue Unified](epics/E16_query_catalogue_unified.md)** ← start here

### Retired (do not pick up work from these)
- [E6 — Cypher Query Catalogue](epics/E6_query_catalogue.md) *(superseded by E16)*
- [E12 — Shared Catalogue Interface](epics/E12_shared_catalogue_interface.md) *(superseded by E16)*
- [E13 — Typed Query Catalogue Contract](epics/E13_typed_query_catalogue_contract.md) *(superseded by E16)*
- [E15 — Typed Cypher Catalogue Backend](epics/E15_typed_cypher_backend.md) *(superseded by E16)*

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
| Mixed catalogue (all three backends in one registry) | Requires scoping session |

---

## Architecture Note: The Two Catalogue Types (resolved in E16)

After E16 there are exactly **two catalogue types**, with a clear decision rule for each:

| | `StringKeyCypherCatalogue` | `TypedQueryCatalogue` |
|---|---|---|
| **Register** | `register(name, cypher, params, returns)` or `from_yaml()` | `register_read(MyQuery())` |
| **Call site** | `catalogue.execute("name", params, conn)` | `executor.read(query, params)` → `list[D]` |
| **Return type** | untyped records (or auto-materialised if NodeModel declared) | statically typed `list[D]` |
| **Schema validation** | at registration, against GraphDataModel | at build time (pure, no DB) |
| **YAML support** | yes | no (Python-only) |
| **Use when** | queries come from config; external tooling; CRUD auto-gen | domain-typed reads/writes; matterforge; IDE safety |
| **Shared surface** | `describe() → list[QueryDescription]` | same |

`GqlAlchemyQueryCatalogue` (E8) is a third independent type (builder expressions, Python-only)
that also satisfies `DescribableCatalogue`.
