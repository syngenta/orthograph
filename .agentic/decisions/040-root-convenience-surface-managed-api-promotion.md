# ADR-040: Root Convenience Surface — Managed Promotion of the API Chokepoint

**Date:** 2026-06-26
**Status:** Accepted
**Category:** architecture / api surface
**Amends:** ADR-011 (invariant 4 — refined from syntactic to semantic rule)
**Amends:** ADR-012 (graphglot promoted from optional to core dependency)

---

## Context

E55 established `orthograph.api.*` as the single curated consumer surface —
seven intent-named modules (`definition`, `profile`, `compare`, `queries`,
`execution`, `discovery`, `rendering`) that each own one capability.

After E55 shipped, two issues remained:

1. **Discoverability gap.** Notebooks and library code routinely bypassed
   `orthograph.api` and imported directly from deep internal paths
   (`orthograph.graph_definition.models`, `orthograph.cypher.generator`, etc.)
   because `import orthograph; orthograph.<capability>` did not work.
   The facade existed but was not ergonomically reachable.

2. **Vocabulary inconsistency residue.** Multiple competing names
   (`graph_definition`/`graph_profile`/`description`/`visualization`) for the
   same modules were scattered across docstrings, CONTEXT.md, the PRD, notebooks,
   and the E55 epic — several pointing at modules that did not exist.

ADR-011's "no re-exports in `__init__.py`" invariant (invariant 4) was a
*syntactic* blanket ban originally written to prevent *indiscriminate deep
re-exports* (e.g. `from orthograph import GraphValidator` pulling straight from
`graph_definition/` and bypassing `api/`). It made no distinction between that
anti-pattern and a disciplined promotion of the already-curated `api/` surface
to the root.

---

## Decision

### 1. The root `orthograph` package promotes the `api/` surface eagerly and explicitly

`orthograph/__init__.py` imports all seven `api/` modules by name:

```python
from orthograph.api import (
    compare, definition, discovery, execution, profile, queries, rendering,
)
```

This makes `orthograph.profile.inspect(...)`, `orthograph.definition.NodeModel`,
`orthograph.rendering.render_result(...)` etc. work directly, with full static
typing, mypy visibility, and IDE autocomplete — no `__getattr__`, no
`TYPE_CHECKING` tricks, no lazy loading.

`api/` remains the **single curated exposure chokepoint**: the root is a
convenience alias of that chokepoint, not an independent surface.

### 2. Invariant 4 is refined from syntactic to semantic (amends ADR-011)

The new rule, enforced by `tests/test_architecture.py`:

- Root `orthograph/__init__.py` may contain:
  - `import importlib.metadata` (the existing `__version__` exception), and
  - `from orthograph.api import …` — the managed promotion, `api/` only.
  - Any other import source (deep internal packages) is a violation.
- Every other `__init__.py` under `src/orthograph/` remains import-free.
- A second test (`test_root_surface_delegates_only_to_api`) verifies at
  runtime that every name in `orthograph.__all__` resolves to an
  `orthograph.api.*` module — catching any future drift.

This encodes the *intent* of ADR-011 as an enforceable policy rather than
forbidding the disciplined promotion it was not designed to prevent.

### 3. `api.backends` is renamed `api.discovery` (amends E55 topology)

`orthograph.backends` already exists as the real vendor-adapter package
(`neo4j/`, `memgraph/`, `loader.py`, `registry.py`). The discovery facade
(`available`, `can_inspect`, `can_execute`) is renamed `api.discovery` so
`orthograph.discovery` at the root is unambiguous.

### 4. `graphglot` is promoted to a core dependency (amends ADR-012)

`orthograph.queries` (the query-governance module) re-exports the Cypher
parser types and is part of the always-present root surface. Making it
optional would mean `import orthograph` could raise `ModuleNotFoundError`
on a core-only install — a direct robustness regression.

`graphglot>=0.9` moves from `[project.optional-dependencies].cypher` to
`[project.dependencies]`. The `cypher` extra becomes an empty backward-compat
alias so existing `orthograph[cypher]` installs continue to work.

DB/ORM vendors (`neo4j`, `networkx`, `gqlalchemy`) remain optional and
continue to be deferred behind `backends/loader.py` thunks. The invariant
"importing `orthograph` loads no DB-vendor package" is preserved and
machine-checked by `tests/test_root_surface.py::test_import_orthograph_pulls_no_db_vendor`.

---

## Explicitly not the rejected ADR-011 pattern

ADR-011 §"Import-discipline directive" rejected:

> **Convenience re-exports at package level** (`from orthograph import
> GraphValidator`). They hide the true source location and let consumers
> bypass the intended `api/` exposure path.

This ADR does **not** do that. The difference:

| ADR-011 rejected pattern | This ADR |
|--------------------------|----------|
| `from orthograph import GraphValidator` — reaches deep into `graph_definition/` | `orthograph.definition.GraphDefinition` — reaches `api.definition`, which itself imports from `graph_definition/` |
| Bypasses `api/`; creates a second uncontrolled surface | Promotes `api/`; `api/` remains the single source of truth |
| Scattered across any `__init__.py` | One place only: the root `__init__.py`, constrained by the semantic invariant |
| Hides source location | Source chain is fully traceable: `orthograph.definition` → `orthograph.api.definition` → `orthograph.graph_definition.*` |

---

## Consequences

- `import orthograph` followed by `orthograph.<capability>.<verb>(...)` works
  with full static typing everywhere — notebooks, scripts, library code.
- `orthograph.api.<capability>` continues to work identically (same objects).
- The `cypher` pip extra is a no-op alias; existing installs are not broken.
- DB vendors remain optional and deferred; `import orthograph` loads only
  `pydantic`, `pyyaml`, and `graphglot`.
- Invariant 4 is now a meaningful semantic rule rather than a syntactic ban
  that could not distinguish the two very different cases.

---

## Relates to / supersedes

- **Amends ADR-011** invariant 4 (the semantic refinement described above).
- **Amends ADR-012** (graphglot promoted to core; `cypher` extra is now empty).
- **Follows E55** (the seven-module `api/` facade that this ADR promotes).
