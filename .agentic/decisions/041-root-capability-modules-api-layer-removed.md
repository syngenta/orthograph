# ADR-041: Root Capability Modules — Seven Real Modules Replace the api/ Layer

**Date:** 2026-06-27
**Status:** Accepted
**Category:** architecture / api surface
**Supersedes:** ADR-040 (root convenience surface via `api/` promotion)

---

## Context

ADR-040 established `orthograph.api.*` as the single curated consumer surface —
seven intent-named modules — and promoted them as convenience aliases at the
`orthograph` root via `from orthograph.api import ...` in `__init__.py`.

This design worked at runtime and satisfied mypy, but created a structural
problem: the package ships `py.typed`, which publicly promises a statically
type-checkable surface. The `api/` modules were real files at
`orthograph/api/<name>.py`, but the root aliases (`orthograph.definition`,
`orthograph.profile`, ...) were only attribute bindings — no files existed at
`orthograph/definition.py` etc.

Consequence: `from orthograph.definition import X` failed in PyCharm (which
uses a filesystem walk, not `sys.modules`), in pyright (`reportMissingImports`),
and in any consuming application's type checker. Only the attribute-access form
(`import orthograph; orthograph.definition.X`) was type-safe. The package was
effectively lying to downstream type checkers about one of its two documented
import styles.

Attempts to patch this with `sys.modules.setdefault(...)` or a single
`__init__.pyi` stub were unsound: no single stub file can create seven
independently importable module paths for a `py.typed` package.

---

## Decision

### 1. The seven capability modules become real files at the package root

The code previously in `orthograph/api/<name>.py` is moved to
`orthograph/<name>.py` for all seven names:

```
src/orthograph/
  definition.py   ← author/load/save/validate the declared contract
  profile.py      ← inspect a backend into a GraphProfile
  compare.py      ← three comparisons
  queries.py      ← author/catalogue/validate/generate Cypher queries
  execution.py    ← run typed read/write queries
  discovery.py    ← discover available backends
  rendering.py    ← render definitions, profiles, and results
```

These are real Python modules. Both import styles now resolve natively:

```python
# Attribute access (notebooks / interactive)
import orthograph
orthograph.definition.NodeModel

# Direct from-import (library code)
from orthograph.definition import NodeModel, GraphDefinition
```

Both are fully type-safe, IDE-resolvable, and pass pyright/mypy without tricks.

### 2. The `api/` package is deleted

`orthograph/api/` is removed entirely. The seven root modules **are** the
single curated exposure surface. There is no longer a separate `api/` layer.

### 3. `orthograph/__init__.py` promotes the seven submodules as attributes

```python
from orthograph import (
    compare, definition, discovery, execution, profile, queries, rendering,
)
```

This preserves `import orthograph; orthograph.definition.X` attribute-access
ergonomics. The `__init__.py` docstring serves as the agent/human
discoverability index — one line per capability with its verbs.

### 4. Invariant 4 (init re-export policy) is updated (amends ADR-040/ADR-011)

The root `__init__.py` may now contain:
- `import importlib.metadata` (for `__version__`)
- `from orthograph import <capability-module>` — promoting the seven root
  submodules as attributes

Every other `__init__.py` under `src/orthograph/` remains import-free.
No `__init__.py` may reach into deep sub-packages (`graph_definition`,
`cypher`, `backends`, etc.) directly — that invariant is unchanged.

### 5. `tests/api/` is renamed `tests/surface/`

The test folder is renamed to match the new topology. All imports within
updated from `orthograph.api.<name>` to `orthograph.<name>`.

---

## Consequences

- `from orthograph.definition import X` resolves in PyCharm, pyright, and any
  consuming application's type checker — the `py.typed` promise is kept.
- `import orthograph; orthograph.definition.X` continues to work identically.
- `orthograph.api.*` no longer exists — any code using it must migrate to
  `orthograph.<name>` (internal: tests/api/* migrated; external: breaking
  change for any published consumer of `orthograph.api.*`).
- Zero runtime tricks (`sys.modules`, stub files) — the package is structurally
  honest.
- `tests/api/` renamed to `tests/surface/`.

---

## Explicitly supersedes

- **ADR-040** — the `api/` promotion layer is removed; root modules are the
  surface. The intent (seven intent-named capability modules) is preserved;
  only the mechanism changes.
- **ADR-011 invariant 4** — refined again: root `__init__` may do
  `from orthograph import <submodule>`, not `from orthograph.api import`.

---

## Relates to

- **ADR-012** (optional-dependency policy) — unchanged; DB vendors still deferred.
- **E55** (the seven-module facade) — the seven names and their content are
  preserved; the file location changes from `api/` to the root.
