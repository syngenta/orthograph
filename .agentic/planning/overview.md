# Planning Overview

> What we're building now, in what order, and what's parked for later.
> For permanent product boundaries, see [knowledge/product.md](../knowledge/product.md).

---

## Current Phase: v0.1.0 — Pilot Readiness

Deliver a stable, documented, agent-navigable library that a pilot project
team can adopt with minimal friction and no prior knowledge of Orthograph.

### Success Criteria

- [ ] `product.md` complete
- [ ] README accurately describes the library
- [ ] E1–E4 quality epics complete
- [ ] E6 (CypherQueryCatalogue) complete and tested
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
| E6 | Query Catalogue | High | planned |
| E7 | Pilot Readiness (gate) | High | in progress |

### Dependency Order

```
E5  done
E3  independent — start anytime
E2  independent — pure refactoring
E1  after E2 (shared base)
E4  after E2 (shared utilities)
E6  independent of E1–E4
E7  gate — requires E1–E6 substantially complete
```

### Epic Files

- [E1 — API Ergonomics](epics/E1_api_ergonomics.md)
- [E2 — Code Deduplication](epics/E2_code_deduplication.md)
- [E3 — Documentation](epics/E3_documentation.md)
- [E4 — Extension Robustness](epics/E4_extension_robustness.md)
- [E5 — Visualization](epics/E5_visualization.md) (done)
- [E6 — Query Catalogue](epics/E6_query_catalogue.md)
- [E7 — Pilot Readiness](epics/E7_pilot_readiness.md)

---

## Deferred (not this phase)

Items explicitly out of scope for the current phase. Each is a candidate
for a future scoping session.

| Item | Rationale |
|------|-----------|
| ORM Query Catalogue (GQLAlchemy builder patterns) | Prerequisite: E6 validated in pilot |
| Schema / Projection hierarchy (`GraphSchema` vs `GraphProjection`) | Large. Post-pilot. |
| Custom validators / checks (Pandera-style `Check`) | Deferred |
| Property value constraints (min/max/regex/enum) | Deferred |
| Schema composition / inheritance | Deferred |
| OWL / RDF import | Future exploration |
| Multi-tool schema registry / central store | Designed for (YAML portability), not built |
| CLI tool | Future |
| Async driver support | Deferred |

---

## Backlog

Ideas, feedback, and open questions parked for future consideration.

### Technical

| # | Topic | Notes |
|---|-------|-------|
| T1 | `GraphDataModel` split into `GraphSchema` + `GraphProjection`? | Enables governance workflows |
| T2 | Custom checks: Pandera-style `Check` class or Pydantic `Field` + `validator`? | Design TBD |
| T3 | Property constraints: Pydantic `Field` or separate constraint model? | Design TBD |
| T4 | NetworkX `observed_types`: Python names or standardised names? | Open |
| T5 | Cypher generator dialect-aware (Neo4j vs Memgraph differences)? | Deferred |
| T6 | GQLAlchemy cardinality enforcement on write? | Opt-in later |
| T7 | Undirected relationships through GQLAlchemy OGM? | Open |
| T8 | ORM catalogue: how are builder patterns stored/serialised? | Requires scoping session |
| T9 | Mixed catalogue (Cypher strings + ORM builders)? | Requires scoping session |

### Strategic

| # | Topic | Notes |
|---|-------|-------|
| S1 | Which projects adopt Orthograph first as a pilot? | Identified internally |
| S2 | Schema definitions in project repos or central registry? | Current: project repos via YAML |
| S3 | Who owns the schema definition for data governance? | Open |
| S4 | Should `GraphDataModel` become a standard graph schema doc format? | Open |
| S5 | Existing OWL/RDF ontologies that need importers? | Open |
