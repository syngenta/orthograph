# Epic E7: Pilot Readiness (Gate)

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Validate that Orthograph is stable and documented enough for two pilot teams to adopt with no prior knowledge
> **Blocked by:** E1, E2, E3, E4, E6, E8, E9, E10, E11 substantially complete
> **User stories:** All

---

## Context

Orthograph reaches "pilot ready" when a software engineer on a target project can:

1. Understand what Orthograph is and whether it fits their use case (README + PRD)
2. Define a `GraphDataModel` for their existing graph database schema
3. Validate their existing query results against that model
4. Inspect their live Neo4j or Memgraph database and compare against the model
5. Declare their queries in a `queries.yaml` and dispatch them via `CypherQueryCatalogue`
6. Use GQLAlchemy codegen + validated query builder for ORM interactions

Two pilot projects:
- **Pilot A:** Hardcoded Cypher, transactional, no schema → Cypher catalogue path
- **Pilot B:** Existing Cypher catalogue pattern → formalise with Orthograph validation

This epic is a **gate** — it validates that all other epics combine into a
coherent, adoptable product. Its tasks are integration, documentation, and
verification checks, not new features.

---

## Tasks

### E7.1: PRD Accuracy Check

Verify the PRD (`knowledge/product_requirements_document.md`) accurately reflects the implemented library. Check all file links are valid and descriptions match reality.

**Acceptance criteria:**
- [ ] All file links in PRD resolve to existing files
- [ ] Capability descriptions match actual implementations
- [ ] Items marked "not yet implemented" are either done or still accurately flagged
- [ ] No drift between PRD constraints and actual code patterns

---

### E7.2: CONTEXT.md Update

Update `CONTEXT.md` routing table to reflect new epics, new packages (catalogue), and add North Star / Guardrails sections derived from PRD.

**Acceptance criteria:**
- [ ] Routing table includes catalogue package
- [ ] North Star section: one paragraph defining Orthograph's purpose
- [ ] Guardrails section: link to PRD constraints
- [ ] An agent can navigate from any question to the correct file in ≤2 hops

---

### E7.3: End-to-End Pilot Notebook

Write a notebook demonstrating the full vertical slice for a pilot team.

**Acceptance criteria:**
- [ ] Schema definition (YAML or Python) for a representative domain
- [ ] Database inspection → `GraphProfile` → drift detection
- [ ] Query catalogue loaded from YAML
- [ ] Named query execution with result validation
- [ ] Visualisation of schema and validation results
- [ ] Runs against a live database (Neo4j or Memgraph)

---

### E7.4: Agent Migration Pattern Validation

Validate that an agent reading `.agentic/` can generate a migration roadmap for a pilot project without human intervention.

**Acceptance criteria:**
- [ ] Agent session produces a coherent adoption plan
- [ ] Documented as a reusable pattern for future pilot onboarding

---

### E7.5: Version and Release Preparation

Bump version to `0.1.0`, confirm CI passes, tag release.

**Acceptance criteria:**
- [ ] `pyproject.toml` version = `0.1.0`
- [ ] All CI checks pass (tests, pre-commit, notebook tests)
- [ ] Git tag `v0.1.0` created

---

## Success Criteria (gate conditions)

- [ ] PRD is accurate and all links valid
- [ ] README matches the library
- [ ] E1–E4 quality epics complete
- [ ] E6 (Cypher Query Catalogue) complete and tested
- [ ] E8 (GQLAlchemy Query Catalogue) complete and tested
- [ ] E9 + E10 (composition pattern + connection audit) complete
- [ ] End-to-end pilot notebook runs against live database
- [ ] An agent reading `.agentic/` can generate a pilot migration roadmap
