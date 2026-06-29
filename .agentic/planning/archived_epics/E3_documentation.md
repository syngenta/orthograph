# Epic E3: Documentation & Onboarding

> **⚠ SUPERSEDED → E61 (ADR-046).** Do not pick up work from this file directly.
> Its three tasks now live in the phased documentation epic:
> E3.1 (README rewrite) → **E61.1.4**, E3.2 (notebook titles) → **E61.2.1**,
> E3.3 (architecture diagram) → **E61.2.3**. See
> [E61_documentation_readthedocs.md](../active_epics/E61_documentation_readthedocs.md) and
> [../../decisions/046-documentation-architecture.md](../../decisions/046-documentation-architecture.md).
>
> **Priority:** High
> **Origin:** Code review 2026-05-07 (sections 2, 8: README, notebooks)
> **Goal:** Ensure a new developer or pilot user can understand, install, and use Orthograph within 15 minutes
> **Blocked by:** None — can start immediately
> **User stories:** 20

---

## Context

The README is the first artifact any evaluator encounters. Currently it
references Python 3.9, conda, internal Nexus URLs, and contains zero
information about what Orthograph actually does. Notebooks are excellent
but have minor staleness. The revised PRD provides clear positioning
(Pydantic for graphs, like Pandera for DataFrames) that the README should
reflect.

---

## Tasks

### E3.1: Rewrite README

Replace the current README.rst with a complete, accurate document that explains what Orthograph is, how to install it, and shows a minimal working example.

**Acceptance criteria:**
- [ ] README answers "what is this?" in the first 3 lines
- [ ] Positions Orthograph as "Pydantic for graphs, like Pandera for DataFrames"
- [ ] Installation instructions match `pyproject.toml`
- [ ] Quick start example is valid Python
- [ ] No references to Python 3.9, conda, or Nexus
- [ ] Mentions both capabilities: Data Validation and Database Profiling & Inspection

---

### E3.2: Fix Notebook Titles and Metadata

Ensure all notebook titles match their numbering scheme and internal references are consistent.

**Acceptance criteria:**
- [ ] All 10 notebook titles match filename numbering
- [ ] Consistent format: `"XX.YY -- Title"`
- [ ] Notebook tests pass

---

### E3.3: Add Architecture Diagram

Create a Mermaid diagram showing package structure, two-phase architecture, and data flow.

**Acceptance criteria:**
- [ ] Valid Mermaid syntax
- [ ] Accurately represents current architecture (including two validation capabilities)
- [ ] Placed in a location discoverable by new developers
