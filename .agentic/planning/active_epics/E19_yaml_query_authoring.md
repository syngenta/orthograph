# Epic E19: YAML Query Authoring — Scoping and Decision

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness (decision needed before pilot gate E7)
> **Blocked by:** E16 (typed core must exist to evaluate YAML against it — done)
> **Blocks:** any YAML build work; the E16 OPEN DECISION cannot be resolved without this
> **Type:** Scoping + architecture decision → produces an ADR; may produce a follow-on build epic

---

## Why This Epic Exists

E16 deliberately excluded YAML and left an OPEN DECISION. At the time it was believed no
consumer needed config-driven query authoring. That assumption was wrong: **other projects in
the organisation already build parameterised Cypher queries from YAML files**. Real consumers
exist. The decision therefore requires a proper scoping session with the team against real
requirements — not a unilateral architectural preference.

This epic does not build anything. It produces:
1. A clear picture of what the real consumers need (use cases, query shapes, who authors them).
2. A decision on which of the three options fits those needs without re-opening the tensions
   E16 resolved.
3. An ADR recording the decision, the rejected alternatives, and the build constraints.
4. If the decision is to build YAML support: a follow-on epic with a concrete implementation
   plan scoped to the chosen option.

---

## Background: The Three Options (from E16)

The E16 epic identified three viable options. They are reproduced here for the scoping session.

### Option A — Drop YAML entirely
Queries are always Python classes. Simplest; fully preserves the typed architecture.

**Cost:** No config-driven query authoring. Ops/analysts must write Python or ask an engineer.

**When to choose:** No real consumer needs YAML and the team is comfortable with Python-only
authoring across all current and near-term projects.

### Option B — YAML as a constrained, auto-materialising subset
YAML may declare ONLY queries whose `returns` is a `NodeModel`; the catalogue auto-materialises
via `NodeModel(**fields)` by convention. No custom `materialize()` from YAML. Two catalogue
types coexist; both expose `describe()`.

**Cost:** Re-introduces two registration models (typed Python classes + YAML/string-key). The
exact Tension 1 E16 resolved. Must be explicitly contained.

**When to choose:** Consumers need to author simple node-fetching queries in config without
writing Python, and the team accepts the two-tier surface with a documented boundary.

### Option C — YAML as a code-generator (build-time only)
A YAML file *generates* `CypherReadQuery` Python classes at build time. Runtime stays 100%
typed; YAML is an authoring convenience that disappears after generation. No second runtime
catalogue.

**Cost:** A code-generation step; round-trip questions (what if generated and hand-written
classes collide? how do you edit a generated query?).

**When to choose:** Consumers need YAML authoring convenience but the team will not accept
runtime untyped returns or string-key dispatch. Highest implementation cost.

---

## Decision Criteria (from E16, preserved here)

Choose the option that:
1. **Does not reintroduce string-key dispatch** into application code.
2. **Keeps `materialize()` type-checked** — the return type of a read is statically known.
3. **Is justified by a real consumer** who genuinely needs config-driven queries.

If the scoping session reveals that the real consumer use cases can be served by Python classes
(e.g. the YAML files are simple enough that a one-time migration is feasible), prefer option A.

---

## Scoping Tasks

### E19.1: Map the real consumer requirements

Interview / review the projects that currently use YAML-driven Cypher query authoring:

1. **What do their YAML files look like?** Collect 3–5 representative examples.
   - What fields are declared? (name, cypher template, params, returns spec?)
   - Are `materialize()` equivalents present, or are results used as raw dicts?
   - Are the queries simple node fetches, or do they include projections, aggregations,
     conditional clauses?
2. **Who authors the YAML files?** Engineers, analysts, ops?
   - Would they be willing/able to write `CypherReadQuery` Python subclasses instead?
3. **How are the queries loaded and executed today?**
   - Is there an existing runtime that registers them?
   - Do callers use string-key dispatch (`execute("name", params)`)?
4. **What is the migration cost** from YAML-today to Python-class?

**Output:** A one-page summary of use cases, query shapes, and authors. This drives the option
selection.

---

### E19.2: Evaluate each option against the real use cases

For each of the three options, answer:
- Does it serve the documented use cases without requiring the YAML authors to change workflow?
- Does it reintroduce string-key dispatch or untyped returns at any call site?
- What is the implementation effort (rough T-shirt size)?
- What is the migration effort for existing YAML-based projects?

---

### E19.3: Team scoping session and decision

Run a session with the relevant engineers and stakeholders. Present the use cases (E19.1) and
the option evaluation (E19.2). Reach a decision.

**Inputs:** E19.1 summary, E19.2 evaluation.
**Output:** A chosen option with rationale and the conditions under which it was chosen.

---

### E19.4: Write ADR-009

Record the decision in `.agentic/decisions/009-yaml-query-authoring.md`:
- The real consumer use cases that drove the decision.
- The chosen option and its implementation constraints.
- The rejected options and why they were rejected.
- Cross-link from E16's OPEN DECISION section and from the PRD.

If the decision is option B or C: create a follow-on build epic (E20 or similar) with a
concrete implementation plan. E19 itself produces only the decision.

---

## Success Criteria

- [ ] Real consumer use cases documented (E19.1).
- [ ] All three options evaluated against real use cases (E19.2).
- [ ] Team decision recorded (E19.3).
- [ ] ADR-009 written and cross-linked from E16 and PRD (E19.4).
- [ ] If option B or C: a follow-on build epic exists with a concrete plan.
- [ ] E16's OPEN DECISION section updated to reference the ADR.

---

## Out of Scope

- Building any YAML support (that is a follow-on epic if the decision calls for it).
- Changing the typed `QueryCatalogue` contract (E16 is done and closed).
- Migrating existing YAML-based projects (that is the consuming project's work, after the
  decision is made and the library support exists).
