# Orthograph — CONTEXT

Routing table. No content lives here — each link points to the single canonical source.

---

## Navigate

| Question | Read |
|----------|------|
| What is this project, who is it for, what are the constraints? | [knowledge/product_requirements_document.md](knowledge/product_requirements_document.md) |
| What is the package topology (definition/profile/comparison/diagnostics) and why? | [decisions/017-package-topology-definition-profile-comparison-diagnostics.md](decisions/017-package-topology-definition-profile-comparison-diagnostics.md) |
| What is the inspection contract (inspector ABC, GraphProfile) and how are optional deps handled? | [decisions/012-optional-dependency-policy.md](decisions/012-optional-dependency-policy.md) |
| What is the consumer-facing API surface? | `src/orthograph/api/` — `model.py` (load/save/validate in-memory), `database.py` (inspect/validate/query/execute), `visualization.py` (render_*/display) |
| How does a backend name map to an adapter, and how is availability checked? | `src/orthograph/backends/loader.py` (adapter wiring) + `src/orthograph/dependencies.py` (availability) |
| Where do vendor backends and the vendor-free inspection currency live? | `src/orthograph/backends/<vendor>/` (adapters + queries) and `src/orthograph/graph_profile/` (GraphProfile, inspector ABC); the declared side is `src/orthograph/graph_definition/`, the cross-layer comparison is `src/orthograph/comparison/` (`compare_profile_to_definition`, `compare_profiles`, `compare_definitions`), and the shared result currency is `src/orthograph/diagnostics/`. The Cypher language tool is top-level `src/orthograph/cypher/`. *(Topology per ADR-017.)* |
| How does comparison work? How do I add a new validation rule? | `src/orthograph/comparison/engine.py` (engine: `compare_profile_to_definition`, `compare_profiles`, `compare_definitions`) + `src/orthograph/comparison/views.py` (`GraphView` adapters) + `src/orthograph/comparison/rules.py` (satisfaction rules) + `src/orthograph/comparison/diff_rules.py` (symmetric diff rules) + [decisions/015-declared-observed-mirror.md](decisions/015-declared-observed-mirror.md) |
| Why was a specific architectural decision made? | [decisions/](decisions/) — search by title or category |
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
