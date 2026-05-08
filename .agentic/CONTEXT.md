# Orthograph — CONTEXT

Routing table. No content lives here — each link points to the single canonical source.

---

## Navigate

| Question | Read |
|----------|------|
| What is this project, who is it for, what are the constraints? | [knowledge/product_requirements_document.md](knowledge/product_requirements_document.md) |
| What is the extension contract (inspector ABC, GraphProfile)? | [knowledge/extension-contract.md](knowledge/extension-contract.md) |
| Why was a specific architectural decision made? | [decisions/](decisions/) — search by title or category |
| What work is planned and in what order? | [planning/overview.md](planning/overview.md) |
| What are the tasks for a specific epic? | [planning/epics/](planning/epics/) |

---

## Folder Structure

```
.agentic/
├── CONTEXT.md                  ← you are here (routing table only)
├── knowledge/                  ← stable reference, rarely changes
│   ├── product_requirements_document.md  ← problem, vision, constraints, capabilities
│   └── extension-contract.md   ← inspector ABC interface, GraphProfile schema
├── decisions/                  ← architectural decisions (ADR format, flat numbered)
├── planning/                   ← work to do (temporary — migrates to Jira)
│   ├── overview.md             ← epic index with status and dependency order
│   └── epics/                  ← one file per epic with tasks
└── reviews/                    ← transient session records (do not read unless prompted)
```

---

## Reading Order (agents)

1. This file (orient)
2. [knowledge/product_requirements_document.md](knowledge/product_requirements_document.md) (constraints and capabilities)
3. The one file relevant to the task at hand

Maximum 3 files for any question.
