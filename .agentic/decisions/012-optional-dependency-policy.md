# ADR-012: Optional-Dependency Policy — Declare Once, Probe, Fail Loud

**Date:** 2026-06-11
**Status:** Accepted (graphglot promoted to core by ADR-040, 2026-06-26)
**Category:** architecture / backend isolation
**Supersedes:** `knowledge/extension-contract.md` (retired — its inspector-ABC and
GraphProfile reference content moves into this ADR and ADR-011/ADR-003)

> **Amendment — ADR-040 (2026-06-26).** `graphglot` (the Cypher parser,
> previously the `cypher` extra) is now a **core dependency**. The root
> `orthograph` package eagerly promotes `orthograph.api.queries` to the root
> surface; making `graphglot` optional would mean `import orthograph` could
> raise `ModuleNotFoundError` on a core-only install. The `cypher` extra
> becomes an empty backward-compat alias — existing `pip install
> orthograph[cypher]` invocations continue to work but install nothing new.
> DB/ORM vendors (`neo4j`, `networkx`, `gqlalchemy`) remain optional and
> deferred. The "never pay for what you don't use" principle now applies to
> *database drivers*, not to the in-tree Cypher language tool which is always
> present as part of the core contract surface.

> **Forward note (ADR-017, 2026-06-12).** Path references in this ADR
> (`profile/validation.py`, `validate_profile`, `core/…`) are as of its date.
> Under ADR-017: `profile/` → `graph_profile/`, `validate_profile` → `compare`
> in `comparison/engine.py`, `core/` → `graph_definition/`, and the
> `ValidationResult` currency lives in `diagnostics/`. The inspector-ABC /
> GraphProfile *contract* in this ADR is unchanged; only locations move. See
> ADR-017's path-translation table.

---

## Context

Orthograph is a single library with several optional backends (Neo4j, Memgraph,
NetworkX, GQLAlchemy) and optional tools (the `cypher` parser, the `ipython`
notebook display path). The core library — model definition, in-memory data
validation, YAML I/O — must install and import with **only** Pydantic and PyYAML.

Before E25 the situation was inconsistent:

- Some modules did `try: import X except ImportError: ...` with ad-hoc messages.
- `query_builder.py` silently swallowed a missing-Cypher `ImportError` and returned
  an empty `ValidationResult` — a validation that *looked* like it passed.
- `visualization/mermaid.py` did an in-function `import IPython` with no actionable
  error.
- Importing a vendor adapter could raise `ImportError` at package load time even
  when the consumer never used that backend.

Three forces are in tension:

1. **Never pay for what you don't use.** Installing `orthograph` (no extras) must not
   require `neo4j`, `gqlalchemy`, `networkx`, or `graphglot`.
2. **Fail loud, fail early, fail actionable.** If a consumer *does* reach for a
   backend whose dependency is absent, the error must name the missing package and the
   exact `pip install` command — never a silent skip, never a bare `ModuleNotFoundError`.
3. **One place to look.** Availability logic must not be scattered across modules as
   repeated `try/except ImportError` blocks.

---

## Decision

### 1. One availability authority: `orthograph.dependencies`

A single module declares every optional backend/tool **once** in a table:

```python
# name -> (pip-extra, kind, probe-modules)
_BACKENDS: dict[str, tuple[str, Kind, tuple[str, ...]]] = {
    "neo4j":      ("neo4j",      "db-driver",  ("neo4j",)),
    "memgraph":   ("memgraph",   "db-driver",  ("neo4j",)),   # shares the Bolt driver
    "networkx":   ("networkx",   "in-memory",  ("networkx",)),
    "gqlalchemy": ("gqlalchemy", "orm",        ("gqlalchemy",)),
    "cypher":     ("cypher",     "tool",       ("graphglot",)),
    "ipython":    ("notebook",   "tool",       ("IPython",)),
}

Kind = Literal["db-driver", "orm", "in-memory", "tool"]
```

Two public functions, and **only** these touch dependency availability:

- `is_available(name) -> bool` — non-raising probe (unknown name → `False`).
- `require(name) -> None` — raises `MissingDependencyError` (an `ImportError`
  subclass) if the name is unknown or its probe modules are not importable. The
  message names the missing package and the extra:
  `"The 'neo4j' backend requires the neo4j package, which is not installed. Install
  it with: pip install orthograph[neo4j]"`.

The probe uses `importlib.util.find_spec` (plus a `sys.modules` check so injected
test doubles count as present) — it confirms a module is **locatable** without
importing it, so probing is cheap and side-effect-free.

**Rule:** no module anywhere else performs `try: import X except ImportError` for an
optional dependency. They call `require` / `is_available` instead.

### 2. Deferred adapter loading: `orthograph.backends.loader`

A backend *name* maps to a concrete adapter class in exactly one table, and the
import is **deferred** behind a thunk so an uninstalled vendor package never fails at
module load:

```python
def _neo4j_inspector() -> type[GraphInspector]:
    from orthograph.backends.neo4j.inspector import Neo4jInspector   # deferred
    return Neo4jInspector

_BACKENDS: dict[str, BackendSpec] = {
    "neo4j": BackendSpec(inspector=_neo4j_inspector, executor=_cypher_executor),
    ...
}
```

`load_inspector(name)` / `load_executor(name)`:

1. resolve the `BackendSpec` (unknown name → `MissingDependencyError` listing the
   known backends);
2. call `dependencies.require(name)` — so the missing-dependency error fires
   **before** any import is attempted;
3. invoke the thunk (the single deferred import) and return the typed class.

Thunks are plain module-level functions: lazy, rename-safe (the type-checker sees
the symbol), and visible to static analysis — no `importlib.import_module` /
`getattr` stringly-typed indirection.

`dependencies._BACKENDS` (availability: extras + probe modules) and
`loader._BACKENDS` (adapter wiring: inspector/executor thunks) are **separate tables
for separate audiences** and are not merged: `dependencies` additionally covers
`ipython` and `cypher`, which have no adapter.

### 3. Three sanctioned consumption shapes — and only three

When a module needs a dependency the core does not have, it declares that need
through `dependencies`, in one of exactly three shapes:

| Shape | When | Example |
|-------|------|---------|
| **Deferred via loader** | A consumer selects a backend by name through `api.*` | `api.database.inspect("neo4j", driver)` → `loader.load_inspector("neo4j")` → `require("neo4j")` → deferred import |
| **Module-top `require` + post-require import** | The *entire module* is unusable without the dependency | `backends/gqlalchemy/codegen.py`: `require("gqlalchemy")` then `from gqlalchemy import Node` (`# noqa: E402`) |
| **In-function `require` + post-require import** | One *capability function* needs it; the rest of the module does not | `visualization/mermaid.py::display_mermaid`: `require("ipython")` then `from IPython.display import Image`; `backends/gqlalchemy/query_builder.py`: `require("cypher")` before importing the parser |

In every shape the `require(...)` call comes **before** the guarded import, so a
missing dependency surfaces as an actionable `MissingDependencyError`, never a raw
`ModuleNotFoundError` and never a silent no-op.

### 4. Isolation invariants (enforced by `tests/test_architecture.py`)

- No `backends/<X>` imports `backends/<Y>` (one extra never drags in another's deps;
  the documented exception is `memgraph`, which deliberately reuses the `neo4j`
  Bolt driver).
- Vendor-free layers (`profile/`, `core/`, `catalogue/`, `cypher/`) contain no
  top-level graph-DB vendor import.
- `api/` contains no top-level concrete-backend import; the only deferred imports
  live inside `backends/loader.py` thunks and the three sanctioned `require`-guarded
  sites above.

---

## Inspection contract (absorbed from the retired `extension-contract.md`)

The inspection ABC and `GraphProfile` schema previously documented in
`knowledge/extension-contract.md` are recorded here so the knowledge folder no longer
carries a separate, drift-prone contract file.

```python
class GraphInspector(ABC):
    @abstractmethod
    def inspect(self, connection) -> GraphProfile: ...
```

- **Stateless**: the source (driver / graph) is passed to `inspect` **per call** and
  never stored (Constraint 13; ADR-011).
- Cypher-speaking backends subclass `CypherInspector` (shared `_run` / `_run_query`
  driver-I/O seam + cardinality/endpoint enrichment); non-Cypher backends subclass
  `GraphInspector` directly.
- Source: `src/orthograph/profile/inspector.py`.

`GraphProfile` (frozen Pydantic, `src/orthograph/profile/models.py`) is the shared
currency between inspection and validation: `source`, `timestamp`,
`node_type_profiles`, `rel_type_profiles`, `constraints`, `metadata`.
`validate_profile(profile, model)` (`src/orthograph/profile/validation.py`) compares
a profile against a `GraphDataModel` and returns a categorised `ValidationResult` (10
codes, unchanged from ADR-003 / ADR-009). All of this is reachable to consumers only
through `api.database.inspect` / `api.database.validate`.

### Adding a new inspection backend

1. Create `backends/<backend>/inspector.py`; subclass `CypherInspector` (Cypher) or
   `GraphInspector` (non-Cypher); implement `inspect(self, connection) -> GraphProfile`.
2. Put backend-specific introspection queries in `backends/<backend>/queries.py` and
   build the catalogue there, importing the vendor-neutral shared queries from
   `orthograph.profile.queries.shared`.
3. Add a row to `orthograph.dependencies._BACKENDS` (extra, kind, probe modules).
4. Add a `BackendSpec` to `orthograph.backends.loader._BACKENDS` (inspector thunk; add
   an executor thunk if applicable).
5. Validation comes for free via `validate_profile`, reached through `api.database.validate`.

---

## Alternatives Considered

- **`try: import X except ImportError` at each call site (status quo before E25).**
  Rejected: scatters availability logic, produces inconsistent messages, and (in
  `query_builder.py`) had already degraded into a *silent* skip that masked a real
  validation gap.
- **Import everything; mark extras as hard dependencies.** Rejected: violates "never
  pay for what you don't use"; a core install would pull `neo4j`, `gqlalchemy`, etc.
- **Entry-point / plugin auto-discovery for backends.** Rejected (also in ADR-011):
  an explicit in-tree, type-checked `loader._BACKENDS` table is preferred over runtime
  discovery for a single-library, known-set-of-backends design.
- **Merge the two tables (`dependencies` + `loader`).** Rejected: they serve different
  audiences (availability vs adapter-wiring) and `dependencies` legitimately covers
  entries (`ipython`, `cypher`) that have no adapter.
- **Stringly-typed `(module_path, classname)` loader entries + `importlib`.** Rejected
  (ADR-011 Amendment A): not rename-safe, returns `type[Any]`, invisible to the
  type-checker. Thunks fix all three.

---

## Consequences

- `pip install orthograph` (no extras) installs and imports with only Pydantic +
  PyYAML; no optional package is imported at load time.
- A consumer that reaches for an absent backend gets one consistent, actionable
  `MissingDependencyError` (`pip install orthograph[<extra>]`) — never a silent skip,
  never a bare `ModuleNotFoundError`.
- Availability lives in one module; adapter wiring in one module; the import-isolation
  invariants are machine-checked.
- Adding a backend is two table rows (availability + wiring) plus the adapter itself.

---

## Relates to / supersedes

- **Retires** `knowledge/extension-contract.md` (content absorbed above; CONTEXT.md
  re-pointed to this ADR + ADR-011).
- Relates to **ADR-011** (capability seams & backend isolation) — this ADR details the
  optional-dependency mechanism ADR-011 references.
- Relates to **ADR-003** (two-phase inspect-then-validate; `GraphProfile` currency).
- Relates to **ADR-006** (GQLAlchemy as an optional backend) and **ADR-007** (explicit
  `backend=` selection; no silent validation skip).
- Closes E25 discrepancies **D6** (mermaid in-function `import IPython`) and **D7**
  (gqlalchemy `query_builder` silent `ImportError` skip).
