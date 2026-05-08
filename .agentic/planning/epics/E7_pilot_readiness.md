# Epic E7: Pilot Readiness

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Ensure Orthograph is stable and documented enough that a pilot project team can adopt it with agent assistance, with no prior knowledge of the library
> **Origin:** Product definition grilling session 2026-05-07 — see `reviews/2026-05-07_product-definition-grilling.md`

---

## Context

Orthograph reaches "pilot ready" when a software engineer on a target project —
guided by an agent reading `knowledge/product.md` — can:

1. Understand what Orthograph is and whether it fits their use case (README + product.md)
2. Define a `GraphDataModel` for their existing graph database schema
3. Validate their existing query results against that model
4. Inspect their live Neo4j or Memgraph database and compare against the model
5. Declare their queries in a `queries.yaml` and dispatch them via `CypherQueryCatalogue`

This epic is a **gate epic** — it is not a feature epic. It validates that all other
epics (E1–E6) combine into a coherent, adoptable product. Its tasks are integration,
documentation, and agent-readiness checks, not new features.

---

## Description of Tasks (not yet fully scoped)

### E7.1: `product.md` — Complete and Validated

Write `knowledge/product.md` with all three layers:
- L1: North star (drift prevention, three-layer model, KPI)
- L2: Phase definition (current scope, out-of-scope, guardrails)
- L3: Capability map (headings mirror subpackages, product language + code pointers)

**Prerequisite:** Product definition grilling session complete (in progress — see `reviews/2026-05-07_product-definition-grilling.md`).

### E7.2: `CONTEXT.md` North Star and Guardrails

Add `## North Star` and `## Guardrails` sections to `CONTEXT.md`, derived from `product.md` L1 and L2.
These are the sections that agent scope checks read before acting.

**Prerequisite:** E7.1 complete.

### E7.3: Agent Migration Pattern Validation

Validate that an agent reading `product.md` + `CONTEXT.md` can autonomously generate a migration roadmap for a pilot project. This is tested by running an agent session against a pilot project repo with Orthograph's `.agentic/` as context.

**Prerequisite:** E7.1, E7.2, E1–E6 complete or substantially done.
**Output:** A documented migration pattern that can be reused across pilot projects.

### E7.4: End-to-End Pilot Notebook

Write a notebook (`04.02_pilot_integration_walkthrough.ipynb`) that demonstrates the full vertical slice:
1. Existing graph database with no schema declared
2. Define `GraphDataModel` matching the existing data
3. Inspect the live database → `GraphProfile`
4. Validate the profile → `ValidationResult`
5. Load query catalogue from YAML
6. Execute named queries with result validation

This notebook is the demo artefact used to recommend adoption.
**Prerequisite:** E6 complete, live DB available (Neo4j or Memgraph).

### E7.5: Version and Release Preparation

- Bump version to `0.1.0` in `pyproject.toml`
- Confirm all CI checks pass (tests, pre-commit, notebook tests)
- Tag the release in git

---

## Success Criteria

- [ ] `product.md` exists and is complete (L1, L2, L3)
- [ ] `CONTEXT.md` has North Star and Guardrails sections
- [ ] README accurately describes the library and matches the API
- [ ] E1–E4 quality epics complete
- [ ] E6 (CypherQueryCatalogue) complete and tested
- [ ] End-to-end pilot notebook exists and runs against a live database
- [ ] An agent reading `.agentic/` can generate a pilot project migration roadmap without human intervention
