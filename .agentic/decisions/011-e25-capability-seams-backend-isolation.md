# ADR-011: E25 Capability Seams and Backend Isolation

**Date:** 2026-06-11
**Status:** Accepted
**Category:** architecture / backend isolation

## Context

Before E25 the package had no stable consumer-facing surface and no enforced
separation between vendor adapters and the rest of the code.  Concrete backend
imports appeared at arbitrary import time; there was no single place where a
backend name mapped to an adapter; optional dependencies could cause
``ImportError`` on package load even when the feature was not used.

E25 established four structural invariants (enforced by ``tests/test_architecture.py``):

1. No ``backends/<X>`` module imports a different ``backends/<Y>``.
2. Vendor-free layers (``profile/``, ``core/``, ``catalogue/``, ``cypher/``) contain no
   top-level graph-DB vendor import.
3. ``api/`` contains no top-level concrete-backend import; deferred thunks
   live inside function bodies in ``backends/loader.py`` (see Amendment A below).
4. No ``__init__.py`` contains a convenience re-export; the only sanctioned way
   to expose functionality is a deliberate ``api/`` module.

## Decision

### Core architecture

- The consumer-facing surface is ``orthograph.api.*`` (``model``, ``database``,
  ``visualization``).  All capability verbs live there.
- Imports flow downward only: ``api/ → backends/ → profile/``.  No upward
  imports exist.
- ``orthograph.dependencies`` is the **single source of availability truth**:
  one ``_BACKENDS`` table maps backend names to probe modules and pip extras.
  ``require(name)`` is the only function that raises
  ``MissingDependencyError``; no other module performs ad-hoc
  ``try: import X except ImportError``.
- ``orthograph.backends.loader`` is the **single source of adapter-wiring
  truth**: one ``_BACKENDS`` table maps backend names to ``BackendSpec``
  instances (inspector thunk + executor thunk + optional deferred reason).
  See Amendment A for the rationale for this placement.
- Inspectors are stateless; the connection is injected per ``inspect()`` call
  and never stored (PRD Constraint 13).
- ``api/`` query/execute verbs receive a consumer-owned connection factory;
  Orthograph opens and closes sessions per call.

### Import discipline

No ``__init__.py`` re-exports symbols.  All imports use full deep paths.
This maximises source visibility and keeps the dependency graph honest.

## Amendment A — Backend loader placement and de-stringing (2026-06-11)

**Supersedes the E25 design detail** that named the loader ``api/_registry.py``.

### Problem with the original placement

E25's design placed the backend-name → adapter loader at ``api/_registry.py``.
This was a deliberate decision in the E25 plan — the loader was the one
sanctioned deferred import in the package — but it produced three pieces of
friction once the rest of E25 landed:

1. **Wrong home.** An internal adapter-loading mechanism sat in the
   consumer-facing ``api/`` directory beside ``model``, ``database``, and
   ``visualization``.  Vendor knowledge belongs under ``backends/``, not in the
   capability surface layer.
2. **Stringly-typed targets.** Each entry was a ``(module_path, classname)``
   string tuple plus ``importlib.import_module`` + ``getattr``.  A rename of
   ``Neo4jInspector`` would break silently at runtime, not at import time or
   type-check time.
3. **Untyped seam.** Both load functions returned ``type[Any]``, requiring
   ``# type: ignore[no-any-return]`` at all four call sites in ``database.py``.
   The most important seam in the package had no type teeth.

### Decision

The loader is **``orthograph.backends.loader``**.

- ``load_inspector(name) -> type[GraphInspector]`` — typed return, no ignore.
- ``load_executor(name) -> type[Executor]`` — typed return, no ignore.
- Each adapter target is a **thunk** — a plain module-level function whose body
  contains the deferred import:
  ```python
  def _neo4j_inspector() -> type[GraphInspector]:
      from orthograph.backends.neo4j.inspector import Neo4jInspector
      return Neo4jInspector
  ```
  A thunk is lazy (import deferred until called), rename-safe (the type-checker
  sees the symbol), and readable (ordinary Python — no ``importlib`` / ``getattr``).
- One ``BackendSpec`` dataclass per backend consolidates inspector thunk,
  executor thunk, and deferred-executor reason in a single record.

### Invariants preserved

- No top-level ``orthograph.backends.<vendor>`` import in ``api/``.
  ``database.py`` imports ``from orthograph.backends import loader`` — the
  loader module, not a concrete backend — which does not trigger the
  architecture test's ``startswith("orthograph.backends.")`` check for a
  specific backend path.
- All thunks remain inside function bodies; the architecture test's
  top-level-only AST walk keeps them invisible.
- ``dependencies._BACKENDS`` (availability) and ``loader._BACKENDS``
  (adapter-wiring) remain separate tables serving distinct audiences.
  ``dependencies`` additionally covers ``ipython`` and the ``cypher`` parser
  tool — neither has an adapter — and is consumed directly by
  ``visualization/mermaid.py``, ``backends/gqlalchemy/codegen.py``, and
  ``backends/gqlalchemy/query_builder.py``.  Merging the two tables would
  couple availability to adapter-wiring and break those callers.

### Files changed

| Before | After |
|--------|-------|
| ``src/orthograph/api/_registry.py`` | deleted |
| — | ``src/orthograph/backends/loader.py`` (new) |
| ``src/orthograph/api/database.py`` | import updated; 4× ``# type: ignore`` removed |
| ``src/orthograph/api/__init__.py`` | ``_registry`` bullet removed |
| ``src/orthograph/backends/__init__.py`` | docstring updated |
| ``tests/test_architecture.py`` | comments updated (assertions unchanged) |
| — | ``tests/backends/test_loader.py`` (new — tests the typed seam directly) |

## Consequences

- ``api/`` is now a pure capability surface: three modules, no internal
  loader mechanism.
- The adapter-wiring seam is typed end-to-end: callers get real
  ``GraphInspector`` and ``Executor`` subtypes.
- Adding a backend requires one record in ``loader._BACKENDS`` (thunks) and
  one record in ``dependencies._BACKENDS`` (availability).  Both are
  co-located documentation of the same backend from their respective angles.
- The architecture tests are unchanged in their assertions and continue to
  enforce all four E25 invariants.

## Supersedes / relates to

- Supersedes the ``api/_registry.py`` placement detail from E25's design.
- Supersedes E23 (Inspector Backend-Behaviour Injection Interface) — the
  ``load_inspector`` seam in ``backends/loader.py`` delivers E23's substance.
- Relates to ADR-009 (inspector-query alignment) — ``CypherInspector`` and
  its backend subclasses are the inspection adapters wired here.
- Relates to ADR-007 (post-gqlalchemy api decisions) — the ``api/`` surface
  and connection-ownership model this ADR enforces.

## Amendment B — Domain-first ``api/`` surface and import discipline (2026-06-11)

**Records the realised shape of the ``api/`` package and closes documentation gaps.**

### Domain-first ``api/`` modules (supersedes the E25 plan's ``schema``/``inspection``/``execution`` names)

The E25 plan sketched ``api/schema.py``, ``api/inspection.py``, and ``api/execution.py``.
The implemented surface is reorganised around the **domain noun** the consumer holds, not
around the lifecycle phase:

| Module | Verbs | Connection |
|--------|-------|------------|
| ``api.model`` | ``load``, ``save``, ``validate`` (in-memory data vs model) | none |
| ``api.database`` | ``inspect``, ``validate`` (live DB vs model), ``query``, ``execute`` | per-call **driver** (inspect/validate); consumer-owned **factory** (query/execute) |
| ``api.visualization`` | ``render_model``, ``render_profile``, ``render_result``, ``display`` | none |

Two deliberate decisions captured here:

1. **Two distinct ``validate`` verbs, not one overloaded ``inspect(model=None)``.**
   ``api.model.validate(model, nodes, relationships)`` validates in-memory records;
   ``api.database.validate(backend, driver, model)`` inspects a live database and validates
   the resulting profile. The E25 plan's single ``inspect(backend, conn, model=None) ->
   GraphProfile | ValidationResult`` overload (whose return type depended on an argument) is
   **rejected** — two precisely-typed verbs are clearer and avoid a union return.

2. **Explicit per-type render functions, not a runtime-dispatch ``render(obj)``.**
   ``render_model`` / ``render_profile`` / ``render_result`` each accept exactly one type and
   take a ``format=`` keyword (``RenderFormat.TEXT`` default, ``MERMAID`` where supported). A
   single ``render(obj)`` that ``isinstance``-dispatches at runtime is **rejected** — it hides
   the supported (type, format) matrix behind a dynamic switch.

Model *classes* (``NodeModel``/``RelationshipModel``/``GraphDataModel``) are NOT wrapped by
``api/`` — they are imported from their true ``orthograph.core.*`` paths. Only *operations*
live in ``api/``.

### Import-discipline directive (closes D8)

- **No convenience re-exports in ANY ``__init__.py``** (core, io, catalogue, visualization,
  profile, backends, cypher, api, and the top-level package). Files are emptied of re-exports
  (docstring only; the top-level file additionally keeps the ``__version__`` lookup) but are
  **not deleted** — setuptools package discovery and ``docs/conf.py`` require them to exist.
- **The only mechanism to expose functionality to consumers is a deliberate ``api/`` module**
  that itself imports full deep paths. Those deep imports are the single, visible record of
  "what is exposed."
- **Every internal module and test imports symbols from their TRUE source location** using
  full deep paths. The large blast radius (≈50+ test files, README, notebooks) is accepted as
  the price of source visibility and an honest dependency graph.
- Enforced by ``tests/test_architecture.py`` (AST/import inspection, OS-independent): the
  no-re-export invariant joins the cross-backend and vendor-free-layer invariants there.
- **Rejected alternative:** convenience re-exports at package level (``from orthograph import
  GraphValidator``). They hide the true source location and let consumers bypass the intended
  ``api/`` exposure path.

### D5 closure (PRD Query-Catalogue status)

The runtime ``QueryCatalogue`` (``orthograph.query.catalogue`` /
``orthograph.query.base_models``) is **implemented** (E16). The PRD's blanket
"*(not yet implemented)*" markers on the Query Catalogue are removed; only the **YAML
loading** of a catalogue remains unimplemented (tracked by E19) and the GQLAlchemy builder
catalogue (E8).

### Other rejected alternatives (recorded for the session)

- **Capability-only layout that hides vendor lineage** — rejected; the layout must keep
  "what-depends-on-what" visible (one folder per vendor under ``backends/``).
- **Entry-point / plugin discovery for backends** — rejected in favour of an explicit
  ``loader._BACKENDS`` table; discovery is in-tree and type-checked.
- **Keeping the connection in the inspector constructor** — rejected; connection is injected
  per call (Constraint 13).
- **A single profile-owned catalogue that backends populate** — rejected; it would force a
  high-level module to import every backend to populate it (the leak this epic removes). Each
  adapter builds its OWN catalogue privately.
- **Full one-shot restructure without staging** — rejected in favour of the S1–S6 staged
  refactor, each stage independently green.

### Note on ``dependencies._BACKENDS`` ``kind`` vocabulary

The realised ``kind`` literal is ``{"db-driver", "orm", "in-memory", "tool"}`` — the E25 plan
listed only the first three; ``"tool"`` was added for non-adapter entries (``cypher`` parser,
``ipython`` display). The ``cypher`` probe module is ``graphglot`` (the Cypher-parser package),
and ``ipython`` is keyed to the ``notebook`` extra.
