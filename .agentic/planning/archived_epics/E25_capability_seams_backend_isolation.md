# Epic E25: Capability Seams & Vendor-Backend Isolation (Refactor)

> **Priority:** High
> **Status:** **done** (2026-06-11)
> **Origin:** Architecture brainstorm 2026-06-11 (improve-codebase-architecture session)
> **Goal:** Restructure the package so each functionality has a vendor-free public
> interface (seam), each database/ORM backend lives in its own isolated folder, and
> dependency validation lives in exactly one module. Maintain or enhance unit-test
> capability and SOLID properties; increase readability and e2e-test transparency.
> **Blocked by:** None — runs on its own branch.
> **No backward compatibility.** Nobody consumes the library yet. Change signatures
> and import paths outright; do NOT add shims, aliases, or deprecation paths.

---

## How to use this epic (READ FIRST — execution protocol)

This epic is the single source of truth for the refactor. It is written so work can be
**forked out to separate agents to save context**. Each STAGE below is **atomic and
sizeable**: it delivers a coherent, independently testable change.

### Branching

- Integration branch: **`architecture-refactoring`** (already exists, cut from `dev`).
- Each STAGE is forked into its own short-lived task branch off `architecture-refactoring`.
  Naming convention: `E25-Sx-<slug>` (e.g. `E25-S1-inspection-seam`).
- Stages run **sequentially**: start a stage only after the previous stage is merged back.
- When ALL stages (S1–S6) are complete and green, `architecture-refactoring` merges into `dev`.

### Temp planning artefacts

Each stage's planner writes its detailed plan to `.opencode/E25/Sx/plan.md`.
Review notes go to `.opencode/E25/Sx/review-notes.md`.
Verification output goes to `.opencode/E25/Sx/verify.md`.
**`.opencode/` is gitignored — these files are NEVER committed.**
They exist only to carry context between the PLAN, EXECUTE, and REVIEW steps of one stage.
Delete them after the stage is merged, or leave them — they will not appear in git.

### Models

| Step | Model | Full model ID |
|------|-------|---------------|
| PLAN | claude-opus-4-8 | `portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8` |
| EXECUTE | claude-sonnet-4-6 | `portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6` |
| PRE-COMMIT & TEST | claude-sonnet-4-6 | `portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6` |
| REVIEW | claude-opus-4-8 | `portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8` |
| COMMIT & MERGE | claude-sonnet-4-6 | `portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6` |

### Triggering a stage

Point the PLAN agent (claude-opus-4-8) at this file's `§ STAGE Sx` + `§ Shared Reference`.
Everything the agent needs is in those two sections plus the source files listed there.

### Verification gate (applies to EVERY stage)

- `pytest` passes (excluding live-DB tests; `--neo4j`/`--memgraph` remain opt-in and untouched).
- `mypy src/orthograph` is clean.
- No `backends/<X>` module imports `backends/<Y>`. Cross-platform check (this is a **win32/pwsh**
  environment — `rg`/ripgrep is NOT installed; use the language-native commands below):
  - pwsh: `Get-ChildItem src/orthograph/backends -Recurse -Filter *.py | Select-String -Pattern "from orthograph\.backends\.(neo4j|memgraph|networkx|gqlalchemy)"`
  - cross-platform fallback (Python, always available): a tiny `tests/test_architecture.py`
    AST/import check (added in S4) is the authoritative, OS-independent gate.
  Either must show no cross-backend import.
- No NEW conditional/mid-file/in-function imports introduced (the only sanctioned deferred
  import is `api/_registry.py`).
- Behaviour parity: every pre-existing behavioural test assertion still holds. A test is only
  *changed* if it asserted a private internal (see Shared Reference §"Tests that reach past the
  interface") — those are re-routed through the public seam, never deleted to make green.

> **Tooling note (win32):** all shell snippets in this epic are PowerShell (pwsh). `rg` is NOT
> available; use `Select-String` / `Get-ChildItem`. The DEFINITIVE, OS-independent invariant
> checks live in `tests/test_architecture.py` (S4) so the gate does not depend on any external
> CLI tool.

---

## Shared Reference (read once; every stage depends on it)

### Target layout (end state after S1–S5)

```
src/orthograph/
├── __init__.py             # EMPTY (S6) — only docstring + __version__; NO re-exports
├── core/  io/  catalogue/  visualization/        # logic UNCHANGED; their __init__.py emptied (S6)
├── cypher/                 # MOVED from extensions/cypher/ (S2) — query LANGUAGE tool, vendor-free
├── dependencies.py         # NEW (S1) — single dependency-validation authority
├── profile/                # INSPECTION currency — vendor-free ONLY
│   ├── __init__.py         # EMPTY — no re-exports (import models/validation/inspector by true path)
│   ├── models.py           # ← extensions/models.py  (GraphProfile + profile models + neutral
│   │                       #   output/identifier models: CardinalityStats, EndpointLabelsRow,
│   │                       #   CardinalityIdentifiers, RelTypeIdentifiers)
│   ├── validation.py       # ← extensions/validation.py   (validate_profile)
│   ├── inspector.py        # GraphInspector ABC (inspect(self, connection)) + CypherInspector base
│   └── queries/
│       ├── __init__.py     # EMPTY
│       └── shared.py       # VENDOR-NEUTRAL Cypher ONLY: InspectCardinalityQuery,
│                           #   InspectEndpointLabelsQuery, coerce_types (plain MATCH/RETURN)
├── api/                    # NEW — THE ONLY consumer-facing surface (deliberate deep imports inside)
│   ├── __init__.py         # EMPTY — consumers import the specific api module (api.schema, api.inspection…)
│   ├── schema.py           # NEW (S6) — validate(), load_schema(), save_schema()  [core operations]
│   ├── visualization.py    # NEW (S6) — render(), render_mermaid(), render_*_text(), display()
│   ├── inspection.py       # inspect(backend, connection, model=None)  (S1)
│   ├── execution.py        # query execution over catalogue (S3)
│   └── _registry.py        # backend-name -> lazy adapter loader (the ONE sanctioned deferred import)
└── backends/               # vendor-isolated adapters, ONE folder per library — OWN their queries
    ├── __init__.py         # EMPTY — no vendor imports
    ├── neo4j/
    │   ├── inspector.py    # Neo4jInspector(CypherInspector): APOC detect + catalogue + row→profile
    │   └── queries.py      # neo4j-SPECIFIC queries (APOC + pure-Cypher variants, constraints) +
    │                       #   build_apoc/build_cypher catalogue (imports shared from profile.queries.shared)
    ├── memgraph/
    │   ├── inspector.py    # MemgraphInspector(CypherInspector): bulk row→profile mapping
    │   └── queries.py      # memgraph-SPECIFIC queries (schema.* bulk, SHOW CONSTRAINT INFO) +
    │                       #   build_memgraph catalogue (imports shared; NEVER imports backends/neo4j)
    ├── networkx/           # ← extensions/networkx/ : NetworkxInspector(GraphInspector) — no Cypher
    │   ├── inspector.py
    │   └── conversion.py
    └── gqlalchemy/         # ← extensions/gqlalchemy/ (S2)
        ├── codegen.py  client.py  query_builder.py  result_adapter.py  base_models.py
```

> Note: every `__init__.py` in the tree is EMPTY of re-exports (docstring + `__version__` only).
> The `api/*.py` modules are the sole exposure mechanism; they import full deep paths internally.

### Dependency direction (enforced; arrows point DOWN only)

```
consumer code -> api/ -> backends/<vendor> -> {profile, cypher, catalogue, core}
                  │
                  └─ uses dependencies.py (availability) + api/_registry.py (lazy load)

RULES:
 - api/ NEVER imports a concrete backend at module top (goes via _registry + dependencies).
 - backends/<X> NEVER imports backends/<Y>.
 - backends/* NEVER import api/.
 - profile/, cypher/ are vendor-free (no neo4j/networkx/gqlalchemy imports at module top).
 - Backend-specific introspection queries live ONLY in backends/<vendor>/queries.py.
 - profile/queries/shared.py holds ONLY vendor-neutral Cypher (plain MATCH/RETURN; no APOC,
   no schema.* procedures, no SHOW CONSTRAINT INFO).
 - Each backends/<vendor>/queries.py imports the shared neutral queries from
   profile.queries.shared and registers them into ITS OWN catalogue alongside its
   backend-specific queries. The QueryCatalogue is the assembly point — NOT a cross-backend
   import. Neither backend imports the other.
```

### Catalogue ownership & why there is no circular dependency (READ — answers a recurring question)

**The catalogue is NOT owned by `profile/`. It is built privately by each backend adapter.**

A profile-owned catalogue (one shared registry that backends populate) is **rejected** — not
because it would be circular by import (backends→profile points down), but because *something*
would then have to import every backend to populate it before `api/` could read it. That
"import every backend from a high level" IS the leak this epic exists to remove.

The chosen model, and why each of the three concerns the user raised is satisfied:

```
api.inspect("neo4j", connection, model)
  │ 1. dependencies.require("neo4j")          — availability check
  │ 2. _registry: "neo4j" -> Neo4jInspector   — THE ONLY place a vendor NAME maps to an adapter
  ▼
Neo4jInspector()                               — the adapter; builds its OWN catalogue privately
  │   (build_*_catalogue() lives in its sibling backends/neo4j/queries.py and imports the
  │    vendor-neutral shared queries from profile.queries.shared)
  ▼
inspector.inspect(connection)                  — right connection + right catalogue, paired
                                                 inside the one object that knows both
```

- **No circular dependency.** Imports flow `backends/* -> profile` (down) and
  `api -> _registry -> backends` (down). `profile/` never imports a backend; `api/` never imports
  a concrete backend at module top (only the `_registry` lazy load). No cycle exists.
- **Vendor knowledge lives in ONE place.** The backend *name* ("neo4j"/"memgraph"/"networkx")
  appears only in the `_registry` dispatch table (an enum/dict) and in `dependencies.py`. Neither
  `profile/` nor `api/inspection.py` ever names a vendor. There is no "match queries to backend"
  logic at a high level — the adapter *is* the match (it owns its catalogue).
- **Right connection + right queries, together.** The adapter owns the method that builds its
  catalogue AND the `inspect(connection)` loop that runs it. The connection is injected per call
  (never stored). Pairing connection-of-backend-X with queries-of-backend-X happens inside
  adapter X — the only object that legitimately knows both its dialect and its driver protocol.
- **Multiple catalogues, not one — and that is correct.** Each adapter has its own catalogue
  (a private implementation detail), not a shared global registry. This is the price of zero leak,
  and it is cheap: the shared neutral queries are imported once from `profile.queries.shared` and
  registered into whichever catalogue(s) need them.

### Import discipline (CROSS-CUTTING DIRECTIVE — applies to EVERY stage)

**Every module imports symbols from their TRUE source location, using full deep paths —
even when that means long imports.** This is a deliberate, non-negotiable choice: it
maximises source visibility (any reader can see exactly where a symbol originates) and it
keeps the dependency graph honest.

- **No convenience re-exports in ANY `__init__.py`** — not in `core/`, `io/`, `catalogue/`,
  `visualization/`, `profile/`, `profile/queries/`, `backends/*/`, or the top-level
  `orthograph/__init__.py`. Package `__init__.py` files are emptied of re-exports (docstring only;
  the top-level file additionally keeps the `__version__` lookup). **EMPTY the contents — do NOT
  delete the files: `[tool.setuptools.packages.find]` requires `__init__.py` to exist for package
  discovery, and `docs/conf.py` reads `orthograph.__version__`.**
- **The ONLY mechanism to expose functionality to consumers is a deliberate `api/` module.**
  Each `api/` module itself imports full deep paths (e.g.
  `from orthograph.core.validator import GraphValidator`) and wraps them into a stable
  capability surface. The deep imports inside `api/` are *intentional and visible* — they are
  the single place where the "what is exposed" decision lives.
- **Consequence — large blast radius accepted.** Internal modules and tests that previously
  imported a re-exported convenience name (e.g. `from orthograph import GraphValidator`) must
  switch to the true path (`from orthograph.core.validator import GraphValidator`). This churn
  is expected and is the price of visibility. It is handled inside the stages (S6 strips the
  re-exports; every stage that touches a file uses true paths from the outset).
- **Tests** import internal symbols from their true paths; tests that exercise a *capability*
  import from `api/`. A test never relies on a convenience re-export.

This supersedes any layout comment below that says an `__init__.py` "re-exports" something —
those comments are corrected in S6.

### Connection-ownership model (RESOLVED — applies throughout)

Orthograph **never owns** a connection. Two injection shapes by activity:

- **Inspection (one-off):** connection is passed **per call** to `inspect(connection)`. The
  inspector is **stateless** — it does NOT store the driver/graph. (Resolves discrepancy D1
  toward PRD Constraint 13.)
- **Query execution (sustained/load-bearing):** a **connection factory** the consumer owns is
  injected — this already exists as `catalogue.Executor(connection_factory)` /
  `CypherExecutor(driver.session)`. S3 reuses it; does not reimplement it.

#### Connection SHAPE — the two are NOT the same object (read before S1/S3)

The current code uses two different driver-level APIs; the new design must keep them distinct
and NOT confuse them:

| Activity | Injected object | Call inside orthograph | Today's site |
|----------|-----------------|------------------------|--------------|
| Inspection | a **driver** (e.g. `neo4j.Driver`) | `driver.execute_query(cypher, database_=…)` — driver opens/closes its own session | `extensions/{neo4j,memgraph}/inspector.py::_run` |
| Execution | a **session factory** (`driver.session`) | `with factory() as session: session.run(cypher, …)` | `extensions/cypher/query_executor.py::CypherExecutor` |

Implications the planner/executor MUST honour:
- `CypherInspector._run(self, connection, cypher)` receives a **driver** and calls
  `connection.execute_query(...)`. It does NOT receive a session factory. (Inspection is one-off;
  the driver's auto-session is the right tool.)
- The neo4j-only `database_` argument currently stored as `self._database` must move into the
  call path. **Decision:** `inspect(self, connection, *, database: str | None = None)` on the
  neo4j adapter ONLY; the `GraphInspector` ABC stays `inspect(self, connection)` and the neo4j
  adapter widens it with a keyword-only `database`. `api.inspection.inspect(backend, connection,
  model=None, **backend_kwargs)` forwards `backend_kwargs` to the adapter so `database=` reaches
  neo4j without leaking into the vendor-free signature. (Memgraph/networkx ignore it.)
- networkx's "connection" is the in-memory `nx` graph object; `NetworkxInspector.inspect(graph)`
  walks it directly — no driver, no `_run`, no catalogue (it subclasses `GraphInspector`, NOT
  `CypherInspector`).
- S3 execution keeps the **factory** shape unchanged (`CypherExecutor(driver.session)`); it is a
  different injection from inspection's driver and the epic does not unify them.

### Discrepancies this epic resolves (register; verify each is closed by the named stage)

| ID | Issue | Closed by |
|----|-------|-----------|
| D1 | PRD/Constraint 13 say connection never owned; inspectors store `self._driver`/`self._graph` | S1 (per-call `inspect(connection)`) |
| D2 | `GqlAlchemyClient._create_inspector` dispatches by class-name string match (ADR-007 said add explicit selection) | S2 (routes via `api.inspect`) |
| D3 | `extensions/memgraph/queries.py` imports `extensions/neo4j` (Constraint 11 break) | S1 (backend-specific queries stay in their backend; shared NEUTRAL queries move to `profile/queries/shared.py`; each backend builds its own catalogue, neither imports the other) |
| D5 | PRD marks Query Catalogue "not yet implemented" but `catalogue/` exists (E16 done) | S6 (doc sync) |
| D6 | `visualization/mermaid.py` does in-function `import IPython`; IPython in no extra | S1 (route via `dependencies.py`) |
| D7 | `gqlalchemy/query_builder.py` silently skips validation on `ImportError` | S2 (route via `dependencies.require`, fail loud) |
| D8 | Convenience re-exports in `__init__.py` files (top-level + `visualization/`, `catalogue/`, etc.) hide true source locations; consumers bypass the intended exposure path | S5 (strip ALL re-exports; expose only via `api/`) |

### Current code facts the planner/executor must honour

- `GraphInspector` ABC today: `extensions/base.py` — `inspect(self) -> GraphProfile` (NO arg).
- Inspector constructors today (all store the source as state):
  - `Neo4jInspector(driver, database=None, use_apoc=None)` — `extensions/neo4j/inspector.py:60`
  - `MemgraphInspector(driver)` — `extensions/memgraph/inspector.py:49`
  - `NetworkxInspector(graph)` — `extensions/networkx/inspector.py:28`
- **Shared (byte-identical) inspector internals** to lift into `profile/inspector.py::CypherInspector`:
  - `_run(cypher)` — calls `self._driver.execute_query(...)`; neo4j adds `database_=self._database`,
    memgraph does not. In the new design `_run(self, connection, cypher)` takes a **driver**
    (NOT a session factory — see §"Connection SHAPE"); the neo4j `database` becomes a keyword on
    `Neo4jInspector.inspect`. neo4j `extensions/neo4j/inspector.py:126`; memgraph `:74`.
  - `_run_query(query, identifiers)` — byte-identical: neo4j `:138`, memgraph `:79`.
  - rel-profile enrichment (endpoint labels -> cardinality loop): neo4j `_build_rel_profile`
    `:216-240`; memgraph `_enrich_rel_profile` `:175-209`.
  - `inspect()` skeleton (build node profiles -> rel profiles -> constraints -> `GraphProfile`):
    neo4j `:75-97`, memgraph `:57-68`.
- **Genuinely per-vendor** (stays in `backends/<vendor>/inspector.py`):
  - which catalogue: neo4j `build_apoc_catalogue`/`build_cypher_catalogue` + APOC auto-detect
    (`_ensure_catalogue` `:103`, `_detect_apoc` `:113`); memgraph `build_memgraph_catalogue`.
  - row -> profile mapping (neo4j per-label real counts vs memgraph bulk, `count=0` heuristic,
    `nodeType` string-stripping, documented parity gaps — memgraph `:92-173`).
  - `source` tag ("neo4j" / "memgraph").
- `NetworkxInspector` does NOT inherit `CypherInspector` (no Cypher; ADR-009 §1). Its `inspect`
  changes signature to `inspect(self, connection)` where `connection` is the `nx` graph.
- Query relocation (queries follow their owner; only vendor-neutral Cypher goes to `profile/`):
  - `extensions/neo4j/queries.py` -> `backends/neo4j/queries.py` — keep the neo4j-SPECIFIC
    queries (APOC + pure-Cypher property variants, `InspectNodeLabelsQuery`,
    `InspectRelTypesQuery`, `InspectNeo4jConstraintsQuery`, `NodePropertyRow`, etc.) and the two
    catalogue factories `build_apoc_catalogue`/`build_cypher_catalogue`.
  - `extensions/memgraph/queries.py` -> `backends/memgraph/queries.py` — keep the
    memgraph-SPECIFIC queries (`Memgraph*Query`, `Memgraph*Row`) and `build_memgraph_catalogue`.
    **DROP the `from ...neo4j.queries import ...` line entirely.**
  - The VENDOR-NEUTRAL shared queries currently in neo4j (`InspectCardinalityQuery`,
    `InspectEndpointLabelsQuery`, and the private `_coerce_types` -> rename to public
    `coerce_types`) -> `profile/queries/shared.py`. Their output/identifier models
    (`CardinalityStats`, `EndpointLabelsRow`, `CardinalityIdentifiers`, `RelTypeIdentifiers`)
    -> `profile/models.py`.
  - Each backend catalogue factory imports the shared neutral queries from
    `profile.queries.shared` and registers them alongside the backend-specific queries (memgraph
    may register them under memgraph-scoped names for clean `describe()` output). Neither backend
    imports the other.
- `catalogue/` package already provides `ReadQuery/WriteQuery/Executor/QueryCatalogue/ReadPort`
  and `CypherExecutor(driver_factory)` — DO NOT modify in this epic (S3 only consumes it).

### Tests that reach past the interface (re-route, do not delete)

Only 7 assertions touch internals; all are inspector tests asserting `_use_apoc`/`_catalogue`:
- `tests/extensions/neo4j/test_inspector.py:82`
- `tests/extensions/neo4j/test_inspector_e2e.py:102,116,117,396,397`
- `tests/extensions/memgraph/test_inspector_e2e.py:298`

Re-route these to assert observable behaviour through `inspect(connection)` / `api.inspect`
(e.g. assert the produced `GraphProfile` content, or assert no `SHOW PROCEDURES` call when
`use_apoc` is fixed). Everything else tests through the public surface already.

Unit inspector tests inject a `MagicMock()` driver in the constructor today
(`Neo4jInspector(driver)`); after S1 they inject it per call (`Neo4jInspector().inspect(driver)`
or `api.inspect("neo4j", driver, model)`). The `FakeGraphSession` + factory pattern in
`tests/catalogue/` and `tests/extensions/cypher/test_query_executor.py` is the target idiom and
is the model for S3.

### Test tree migration (mirror the source moves)

- `tests/extensions/neo4j/` -> `tests/backends/neo4j/`
- `tests/extensions/memgraph/` -> `tests/backends/memgraph/`
- `tests/extensions/networkx/` -> `tests/backends/networkx/`
- Tests for the SHARED neutral queries (cardinality, endpoint-labels) currently inside
  `tests/extensions/{neo4j,memgraph}/test_inspector_queries.py` -> a new
  `tests/profile/queries/test_shared.py` (they now test `profile/queries/shared.py`). Backend-
  specific query tests (APOC, `schema.*`) stay in `tests/backends/<vendor>/`.
- `tests/extensions/gqlalchemy/` -> `tests/backends/gqlalchemy/` (S2)
- `tests/extensions/cypher/` -> `tests/cypher/` (S2)
- `tests/extensions/test_models.py`, `tests/extensions/test_validation.py` -> `tests/profile/`
- new `tests/api/` for the seam + the cross-backend contract test
- new `tests/test_dependencies.py`
- **Preserve test packaging:** every migrated test directory keeps its `__init__.py` (move it with
  the directory). New test dirs (`tests/backends/`, `tests/backends/<vendor>/`, `tests/profile/`,
  `tests/profile/queries/`, `tests/api/`, `tests/cypher/`) each get an `__init__.py`.
- **Update the root `conftest.py` comment** at line ~95 that references
  `tests/extensions/{neo4j,memgraph}/` (the path-based marker explanation) to the new
  `tests/backends/{neo4j,memgraph}/` location. The marker LOGIC is unchanged; only the comment.
  (Do this in S1 when the neo4j/memgraph test dirs move.)

---

## STAGE S1 — Inspection seam + `profile/` currency + backend-owned queries + `dependencies.py`

**Atomic deliverable:** a vendor-free public `api.inspect(backend, connection, model=None)` seam;
`profile/` holds only vendor-free currency (`GraphProfile` models, `validate_profile`,
`GraphInspector` ABC + `CypherInspector` base) plus the **vendor-neutral** shared Cypher queries;
each backend OWNS its own introspection queries and builds its own catalogue under
`backends/<vendor>/queries.py`; the three inspectors are stateless per-call adapters; one
`dependencies.py` availability authority; D3 + D6 closed. Networkx, neo4j, memgraph inspection all
green through the new seam.

**Backend-code-must-not-leak-upward principle (the core of this stage):**
Backend-specific Cypher (APOC procedures, pure-Cypher per-label variants, Memgraph `schema.*`
bulk procedures, `SHOW CONSTRAINT INFO`) lives ONLY in `backends/<vendor>/queries.py`. The ONLY
queries allowed in `profile/queries/shared.py` are **vendor-neutral** Cypher building blocks —
plain `MATCH`/`RETURN` that run identically on any Cypher backend (the cardinality and
endpoint-label queries qualify; they use no backend-specific procedure). Each backend imports the
shared neutral queries from `profile/queries/shared.py` and **registers them into its own
catalogue** alongside its backend-specific queries. **Neither backend imports the other; the
catalogue is the assembly point.**

**Scope (touch):**
- NEW `src/orthograph/dependencies.py`
- NEW `src/orthograph/profile/`:
  - `models.py` ← move `extensions/models.py` (GraphProfile + profile models + shared
    output/identifier models that are vendor-neutral: `CardinalityStats`, `EndpointLabelsRow`,
    `CardinalityIdentifiers`, `RelTypeIdentifiers`).
  - `validation.py` ← move `extensions/validation.py` (`validate_profile`).
  - `inspector.py` ← move `extensions/base.py` (GraphInspector ABC) + ADD `CypherInspector` base.
  - `queries/__init__.py` (EMPTY), `queries/shared.py` — the vendor-NEUTRAL Cypher queries ONLY:
    `InspectCardinalityQuery`, `InspectEndpointLabelsQuery`, and the public `coerce_types`
    helper (renamed from `_coerce_types`). These use plain MATCH/RETURN — no APOC, no `schema.*`.
- NEW `src/orthograph/backends/{__init__}.py` + `backends/{neo4j,memgraph,networkx}/`:
  - `backends/neo4j/queries.py` ← the neo4j-SPECIFIC queries from `extensions/neo4j/queries.py`
    (`InspectNodeLabelsQuery`, `InspectRelTypesQuery`, APOC `node/rel properties`, pure-Cypher
    `CypherNodePropertiesQuery`/`CypherRelPropertiesQuery`, `InspectNeo4jConstraintsQuery`,
    `NodePropertyRow`/`NodeLabelRow`/`RelTypeLabelRow`/`NodeLabelIdentifiers`) + the two catalogue
    factories `build_apoc_catalogue()` / `build_cypher_catalogue()`. Each factory imports the
    shared neutral queries from `profile.queries.shared` and registers them alongside the
    neo4j-specific ones.
  - `backends/neo4j/inspector.py` ← `Neo4jInspector(CypherInspector)`: APOC detect + catalogue
    selection + neo4j row→profile mapping + `source="neo4j"`.
  - `backends/memgraph/queries.py` ← the memgraph-SPECIFIC queries
    (`MemgraphNodePropertiesQuery`, `MemgraphRelPropertiesQuery`, `MemgraphConstraintsQuery`,
    their `Memgraph*Row` models) + `build_memgraph_catalogue()`. The factory imports the shared
    neutral queries from `profile.queries.shared` and registers them (under memgraph-scoped names
    if desired). **Does NOT import `backends/neo4j`.**
  - `backends/memgraph/inspector.py` ← `MemgraphInspector(CypherInspector)`: bulk row→profile
    mapping + documented parity gaps + `source="memgraph"`.
  - `backends/networkx/{inspector,conversion}.py` ← move `extensions/networkx/*`;
    `NetworkxInspector(GraphInspector)` (no Cypher, no catalogue).
- NEW `src/orthograph/api/{__init__,inspection,_registry}.py`
- EDIT `src/orthograph/visualization/mermaid.py` (route IPython check via `dependencies.py`)
- EDIT root `conftest.py` — update the stale `tests/extensions/{neo4j,memgraph}/` path comment
  (~line 95) to `tests/backends/{neo4j,memgraph}/`. Marker logic unchanged.
- DELETE the moved files from `extensions/{neo4j,memgraph,networkx}/` and
  `extensions/{models,validation,base}.py`
- Tests: migrate per "Test tree migration"; add `tests/api/` contract test + `tests/test_dependencies.py`

**Out of scope:** `extensions/cypher/` (stays put until S2 — `profile/queries/shared.py` and
`backends/*/queries.py` import it from its CURRENT path `orthograph.extensions.cypher...` during
S1; S2 updates those imports). `gqlalchemy/` untouched. Do NOT touch `catalogue/`.

**Key requirements:**
- `GraphInspector.inspect(self, connection)` — stateless inspectors; no stored driver/graph.
- `CypherInspector(GraphInspector)` owns `_run`/`_run_query`/rel-enrichment/`inspect()` template;
  `_run(self, connection, cypher)` receives a **driver** and calls
  `connection.execute_query(...)` (see Shared Reference §"Connection SHAPE"). Subclasses provide
  `source`, the catalogue (built in the backend), and row→profile mapping.
- The neo4j-only `database` argument moves from `self._database` into a keyword-only parameter:
  `Neo4jInspector.inspect(self, connection, *, database=None)`. The ABC stays
  `inspect(self, connection)`; `api.inspection.inspect(backend, connection, model=None,
  **backend_kwargs)` forwards `backend_kwargs` to the adapter (so `database=` reaches neo4j; other
  backends ignore it).
- **`profile/queries/shared.py` contains ONLY vendor-neutral Cypher** (no APOC, no `schema.*`, no
  `SHOW CONSTRAINT INFO`). `coerce_types` is public (no underscore) and lives here.
- **Each backend's `queries.py` builds its catalogue**, importing shared queries from
  `profile.queries.shared` and registering them with its own backend-specific queries. A backend's
  `queries.py` NEVER imports another backend's module.
- `backends/<vendor>/inspector.py` loads its catalogue from its sibling `backends/<vendor>/queries.py`.
- `dependencies.py`: declarative `{backend: (extra, kind, probe-modules)}`, `kind` in
  `{"db-driver","orm","in-memory"}`; `require(name)` raises a uniform `MissingDependencyError`
  with an actionable message (`pip install orthograph[neo4j]`).
- `api/_registry.py`: maps backend name -> dotted adapter path; `load_inspector(name)` calls
  `dependencies.require(name)` THEN does the single lazy import. This is the only sanctioned
  deferred import.
- `api/inspection.py`: `inspect(backend, connection, model=None, **backend_kwargs) -> GraphProfile
  | ValidationResult` (returns `ValidationResult` when `model` given, else `GraphProfile`;
  `backend_kwargs` forwarded to the adapter, e.g. `database=` for neo4j).
- `mermaid.py`: IPython availability checked via `dependencies.py` (no in-function `try/except import`).

**Acceptance criteria:**
- [ ] `from orthograph.api.inspection import inspect` works; `inspect("networkx", g, model)` returns a `ValidationResult`; `inspect("networkx", g)` returns a `GraphProfile`.
- [ ] `GraphInspector` ABC is `inspect(self, connection)`; no inspector stores a connection/graph as instance state.
- [ ] neo4j + memgraph inspectors subclass `CypherInspector`; the `_run`/`_run_query`/rel-enrichment/`inspect()`-skeleton logic exists in `profile/inspector.py` ONCE.
- [ ] **Backend-specific queries live ONLY in `backends/<vendor>/queries.py`** (APOC, pure-Cypher property variants, Memgraph `schema.*`, `SHOW CONSTRAINT INFO`). `profile/queries/shared.py` contains ONLY vendor-neutral Cypher (cardinality, endpoint-labels, `coerce_types`).
- [ ] Each backend builds its own catalogue in `backends/<vendor>/queries.py`, importing the shared neutral queries from `profile.queries.shared`. `backends/memgraph/queries.py` does NOT import `backends/neo4j` (and vice versa). (D3 closed.)
- [ ] `dependencies.py` exists; `require("neo4j")` raises a clear, actionable error when the `neo4j` package is absent; one declarative table; `kind` recorded per backend.
- [ ] No in-function/conditional import remains in `mermaid.py`. (D6 closed.)
- [ ] New `tests/api/test_inspection_contract.py` drives all three backends (mock drivers / nx graph) through `api.inspect` and asserts `GraphProfile` shape parity.
- [ ] The 7 internal-state assertions are re-routed through the public seam (none deleted to pass).
- [ ] Verification gate passes (pytest, mypy, no cross-backend import, no new deferred imports).
- [ ] `extensions/{neo4j,memgraph,networkx,models,validation,base}.py` removed; nothing imports them.

### Agent loop for this stage

Run steps in order. Do not start a step until the previous step is complete.
Branch for this stage: `E25-S1-inspection-seam` (cut from `architecture-refactoring`).

#### STEP 1 — PLAN &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Read sections **'STAGE S1'** and **'Shared Reference'** in
> `.agentic/planning/active_epics/E25_capability_seams_backend_isolation.md`,
> then read every source file listed in **'Scope (touch)'**.
> Produce a file-by-file change list: every file to create, move, edit, or delete,
> with function-level detail for non-trivial changes (new class signatures, which
> methods move where, import-path updates at every call site).
> Write the complete output to `.opencode/E25/S1/plan.md`.
> Do NOT write any production code or tests.

#### STEP 2 — EXECUTE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Read `.opencode/E25/S1/plan.md` and implement every item exactly as specified.
> Work on branch `E25-S1-inspection-seam`.
> When all files are written, run the verification commands (pwsh; `rg` is NOT available on win32):
> `pytest -x -q`, `mypy src/orthograph`, and the cross-backend import check
> (`Get-ChildItem src/orthograph/backends -Recurse -Filter *.py | Select-String -Pattern "from orthograph\.backends\.(neo4j|memgraph|networkx|gqlalchemy)"` — must print nothing).
> Paste all command output into `.opencode/E25/S1/verify.md`.

#### STEP 3 — PRE-COMMIT & TEST &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> On branch `E25-S1-inspection-seam` run:
> `pre-commit run --all-files`
> then `pytest -x -q`
> Fix any failures (formatting, import errors, test regressions).
> Append final pass/fail output to `.opencode/E25/S1/verify.md`.

#### STEP 4 — REVIEW &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Review E25 S1. Read `.opencode/E25/S1/plan.md`, `.opencode/E25/S1/verify.md`,
> and `git diff architecture-refactoring...E25-S1-inspection-seam`.
> Check every acceptance criterion in **'STAGE S1'** one by one against the diff
> and test output. Mark each [ ] as pass or fail with one line of evidence.
> If any criterion fails: write specific fix instructions to
> `.opencode/E25/S1/review-notes.md` and end your response with **BOUNCE**.
> If all pass: write **APPROVED** to `.opencode/E25/S1/review-notes.md`.
>
> On BOUNCE: re-run STEP 2 adding "also read `.opencode/E25/S1/review-notes.md`
> and fix every issue listed", then re-run STEP 3 and STEP 4. Repeat until APPROVED.

#### STEP 5 — COMMIT & MERGE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Commit and merge E25 S1. Run exactly:
> ```
> git add -A
> git commit -m "refactor(E25.S1): inspection seam + profile/ consolidation + dependencies.py"
> git checkout architecture-refactoring
> git merge --no-ff E25-S1-inspection-seam -m "merge(E25.S1): inspection seam + profile/ consolidation"
> git branch -d E25-S1-inspection-seam
> ```

---

## STAGE S2 — Move `cypher/` top-level + `gqlalchemy/` to `backends/` + fix `GqlAlchemyClient`

**Atomic deliverable:** `extensions/` is emptied and deleted. `cypher/` becomes a top-level
language module; `gqlalchemy/` becomes a vendor backend. `GqlAlchemyClient` no longer owns dispatch
by string match and no longer silently skips validation. D2 and D7 closed.

**Scope (touch):**
- MOVE `src/orthograph/extensions/cypher/` -> `src/orthograph/cypher/`; update ALL import sites
  (notably `profile/queries/*` which referenced `orthograph.extensions.cypher...` in S1).
- MOVE `src/orthograph/extensions/gqlalchemy/` -> `src/orthograph/backends/gqlalchemy/`.
- EDIT `backends/gqlalchemy/client.py`: replace `_create_inspector` (class-name string dispatch +
  the 3 in-function imports at `:187,:199,:208`) with a call to `api.inspect(backend, connection, model)`.
  Backend selection becomes explicit (caller passes/declares it), not string-matched. Review `save_*`
  per PRD §248 + ADR-006/007 — at minimum remove the connection-owning dispatch; full `save_*` fate
  may be deferred to E9 if larger, but the string-match and in-function imports MUST go.
- EDIT `backends/gqlalchemy/query_builder.py`: remove the silent `except ImportError: return
  ValidationResult()` at `:141`; route Cypher availability through `dependencies.require("cypher")`
  and fail loud (or skip only by explicit, documented opt-out — not silently).
- EDIT `backends/gqlalchemy/codegen.py`: keep the hard dependency requirement but route it through
  `dependencies.require("gqlalchemy")` at the module entry instead of an ad-hoc top-level try/except.
- DELETE `src/orthograph/extensions/` entirely.
- Tests: migrate per "Test tree migration"; update all import paths.
- UPDATE notebook import paths (broken since S1 deleted `extensions/networkx/`, `extensions/validation.py`, `extensions/models.py`):
  - `notebooks/03.01_networkx_inspection_and_validation.ipynb`: `extensions.networkx.NetworkxInspector` → `backends.networkx.inspector.NetworkxInspector`; `extensions.networkx.schema_to_networkx` → `backends.networkx.conversion.schema_to_networkx`; `extensions.validation.validate_profile` → `profile.validation.validate_profile`.
  - `notebooks/01.04_visualization.ipynb`: same `extensions.networkx` / `extensions.validation` imports updated to the new paths above.
  - Do this as the **last sub-task** of S2 (all source moves are complete at that point).

**Out of scope:** `api/execution.py` (S3). Inspection internals (settled in S1).

**Acceptance criteria:**
- [ ] `src/orthograph/extensions/` no longer exists; nothing imports `orthograph.extensions.*`.
- [ ] `orthograph.cypher` is the language tool's home; all references updated; mypy clean.
- [ ] `orthograph.backends.gqlalchemy` is the ORM backend's home.
- [ ] `GqlAlchemyClient` performs NO class-name string dispatch and has NO in-function imports for
      inspector selection; it uses `api.inspect`. (D2 closed.)
- [ ] `query_builder.py` no longer silently swallows a missing-Cypher `ImportError`. (D7 closed.)
- [ ] All optional-dependency checks for gqlalchemy/cypher route through `dependencies.py`.
- [ ] `notebooks/03.01_networkx_inspection_and_validation.ipynb` and `notebooks/01.04_visualization.ipynb` import paths updated to the post-S1 locations (`backends.networkx.*`, `profile.validation`, `profile.models`); both notebooks execute without `ImportError`.
- [ ] Verification gate passes.

### Agent loop for this stage

Run steps in order. Do not start a step until the previous step is complete.
Branch for this stage: `E25-S2-extensions-cleanup` (cut from `architecture-refactoring`).

#### STEP 1 — PLAN &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Read sections **'STAGE S2'** and **'Shared Reference'** in
> `.agentic/planning/active_epics/E25_capability_seams_backend_isolation.md`,
> then read every source file listed in **'Scope (touch)'**.
> Produce a file-by-file change list: every file to move, edit, or delete,
> with import-path updates at every call site and function-level detail for
> the GqlAlchemyClient and query_builder changes.
> Write the complete output to `.opencode/E25/S2/plan.md`.
> Do NOT write any production code or tests.

#### STEP 2 — EXECUTE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Read `.opencode/E25/S2/plan.md` and implement every item exactly as specified.
> Work on branch `E25-S2-extensions-cleanup`.
> When all files are written, run (pwsh; no `rg`):
> `pytest -x -q`, `mypy src/orthograph`, and the cross-backend import check
> (`Get-ChildItem src/orthograph/backends -Recurse -Filter *.py | Select-String -Pattern "from orthograph\.backends\.(neo4j|memgraph|networkx|gqlalchemy)"`).
> Paste all command output into `.opencode/E25/S2/verify.md`.

#### STEP 3 — PRE-COMMIT & TEST &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> On branch `E25-S2-extensions-cleanup` run:
> `pre-commit run --all-files`
> then `pytest -x -q`
> Fix any failures. Append final output to `.opencode/E25/S2/verify.md`.

#### STEP 4 — REVIEW &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Review E25 S2. Read `.opencode/E25/S2/plan.md`, `.opencode/E25/S2/verify.md`,
> and `git diff architecture-refactoring...E25-S2-extensions-cleanup`.
> Check every acceptance criterion in **'STAGE S2'** one by one.
> If any fail: write fix instructions to `.opencode/E25/S2/review-notes.md` and
> end with **BOUNCE**.
> If all pass: write **APPROVED** to `.opencode/E25/S2/review-notes.md`.
>
> On BOUNCE: re-run STEP 2 adding "also read `.opencode/E25/S2/review-notes.md`
> and fix every issue listed", then re-run STEP 3 and STEP 4. Repeat until APPROVED.

#### STEP 5 — COMMIT & MERGE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Commit and merge E25 S2. Run exactly:
> ```
> git add -A
> git commit -m "refactor(E25.S2): cypher/ top-level + gqlalchemy/ to backends/ + client fix"
> git checkout architecture-refactoring
> git merge --no-ff E25-S2-extensions-cleanup -m "merge(E25.S2): extensions/ deleted; cypher/ and gqlalchemy/ relocated"
> git branch -d E25-S2-extensions-cleanup
> ```

---

## STAGE S3 — `api/execution.py` (the second public API)

**Atomic deliverable:** a vendor-free public query-execution seam that runs a typed query (or a
catalogue) against a database, backend-dispatched, with the connection injected as a
consumer-owned **factory** (sustained-load model). Built ON TOP of the existing
`catalogue.Executor` — no reimplementation.

**Scope (touch):**
- NEW `src/orthograph/api/execution.py`: a thin seam that, given a backend + a consumer-owned
  connection factory + a typed `ReadQuery`/`WriteQuery` (or a `QueryCatalogue` + query name bound
  to a `ReadPort`), constructs the right `Executor` adapter (Cypher-onto-driver via `CypherExecutor`;
  GQLAlchemy-builder via the gqlalchemy backend) and executes. Uses `dependencies.require` +
  `api/_registry.py` for backend selection.
- EDIT `api/__init__.py` to export the execution entry point(s).
- Tests: `tests/api/test_execution.py` using `FakeGraphSession` + factory (the established idiom);
  exercise both the Cypher and GQLAlchemy dispatch paths.

**Constraints:**
- Connection is NEVER owned: the consumer passes a factory callable; orthograph opens/closes per
  call (read) or per transaction (write) exactly as `catalogue.Executor` already documents.
- Do NOT duplicate `Executor.read/write` logic; wrap/select, don't reimplement.
- Respect the catalogue-vs-repository boundary note in `planning/overview.md` (the seam selects and
  executes; it does NOT become a runtime string-keyed dispatch table inside application code).

**Acceptance criteria:**
- [ ] `from orthograph.api import ...` exposes a query-execution entry point distinct from `inspect`.
- [ ] Execution accepts a consumer-owned connection factory; orthograph stores no live connection.
- [ ] Cypher path and GQLAlchemy path both dispatch by backend through `_registry`/`dependencies`.
- [ ] No duplication of `catalogue.Executor` logic.
- [ ] `tests/api/test_execution.py` covers both paths with fakes; verification gate passes.

### Agent loop for this stage

Run steps in order. Do not start a step until the previous step is complete.
Branch for this stage: `E25-S3-execution-api` (cut from `architecture-refactoring`).

#### STEP 1 — PLAN &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Read sections **'STAGE S3'** and **'Shared Reference'** in
> `.agentic/planning/active_epics/E25_capability_seams_backend_isolation.md`,
> then read `src/orthograph/catalogue/typed.py` and `src/orthograph/catalogue/registry.py`
> and `src/orthograph/api/inspection.py` and `src/orthograph/api/_registry.py`.
> Produce a file-by-file change list for `api/execution.py` and its tests,
> with the full public interface and the delegation pattern to `catalogue.Executor`.
> Write the complete output to `.opencode/E25/S3/plan.md`.
> Do NOT write any production code or tests.

#### STEP 2 — EXECUTE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Read `.opencode/E25/S3/plan.md` and implement every item exactly as specified.
> Work on branch `E25-S3-execution-api`.
> When done, run: `pytest -x -q`, `mypy src/orthograph`.
> Paste all command output into `.opencode/E25/S3/verify.md`.

#### STEP 3 — PRE-COMMIT & TEST &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> On branch `E25-S3-execution-api` run:
> `pre-commit run --all-files`
> then `pytest -x -q`
> Fix any failures. Append final output to `.opencode/E25/S3/verify.md`.

#### STEP 4 — REVIEW &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Review E25 S3. Read `.opencode/E25/S3/plan.md`, `.opencode/E25/S3/verify.md`,
> and `git diff architecture-refactoring...E25-S3-execution-api`.
> Check every acceptance criterion in **'STAGE S3'** one by one.
> If any fail: write fix instructions to `.opencode/E25/S3/review-notes.md` and
> end with **BOUNCE**.
> If all pass: write **APPROVED** to `.opencode/E25/S3/review-notes.md`.
>
> On BOUNCE: re-run STEP 2 adding "also read `.opencode/E25/S3/review-notes.md`
> and fix every issue listed", then re-run STEP 3 and STEP 4. Repeat until APPROVED.

#### STEP 5 — COMMIT & MERGE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Commit and merge E25 S3. Run exactly:
> ```
> git add -A
> git commit -m "refactor(E25.S3): api/execution.py — query execution seam"
> git checkout architecture-refactoring
> git merge --no-ff E25-S3-execution-api -m "merge(E25.S3): api/execution.py"
> git branch -d E25-S3-execution-api
> ```

---

## STAGE S4 — (Optional, foldable) Verify isolation invariants & cleanup

**Atomic deliverable:** a hardening pass that mechanically proves the architecture invariants and
removes any residue. Small; may be folded into the S2 review if trivial.

**Scope (touch):**
- Add an import-isolation test (`tests/test_architecture.py`) asserting the invariants that are
  TRUE as of S4 (i.e. after S1–S3):
  - no `backends/<X>` imports `backends/<Y>`;
  - `profile/`, `cypher/`, `core/`, `catalogue/` contain no top-level vendor imports;
  - `api/` contains no top-level concrete-backend import (only `_registry`'s lazy load).
  This test uses Python's `ast`/import inspection so it is OS-independent (no `rg` dependency) and
  becomes the authoritative cross-backend gate cited in the Verification gate.
- Remove any dead `__init__` re-exports pointing at the OLD `extensions` paths (residue only).
- Confirm `pyproject.toml` extras still isolate dependencies (no extra silently pulls another's dep,
  except the documented `memgraph`==neo4j-driver case).

> **Ordering note (resolves the S4/S5 dependency):** S4 runs BEFORE S5 and therefore does NOT
> assert "no re-exports" — at S4 the convenience re-exports still exist (they are stripped in S5).
> The no-re-export invariant is added to `tests/test_architecture.py` **by S5**, not here. S4
> establishes the test module and the cross-backend/vendor-free-layer assertions; S5 extends it.

**Acceptance criteria:**
- [ ] `tests/test_architecture.py` exists and enforces (via Python AST/import inspection, no
      external CLI): no `backends/<X>`→`backends/<Y>` import; vendor-free layers stay vendor-free;
      `api/` has no top-level concrete-backend import. (The no-re-export assertion is added in S5.)
- [ ] No dead exports / dangling references to `orthograph.extensions`.
- [ ] `pyproject.toml` extras reviewed; comments updated to match new package paths.
- [ ] Verification gate passes.

### Agent loop for this stage

Run steps in order. Do not start a step until the previous step is complete.
Branch for this stage: `E25-S4-isolation-tests` (cut from `architecture-refactoring`).

#### STEP 1 — PLAN &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Read sections **'STAGE S4'** and **'Shared Reference'** in
> `.agentic/planning/active_epics/E25_capability_seams_backend_isolation.md`,
> then read `pyproject.toml` and the full `src/orthograph/` tree (directory listing only).
> Produce a change list for: the architecture invariant test module, any dead exports
> to remove, and any pyproject.toml comment updates.
> Write the complete output to `.opencode/E25/S4/plan.md`.
> Do NOT write any production code or tests.

#### STEP 2 — EXECUTE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Read `.opencode/E25/S4/plan.md` and implement every item exactly as specified.
> Work on branch `E25-S4-isolation-tests`.
> When done, run (pwsh; no `rg`): `pytest -x -q`, `mypy src/orthograph`, and the cross-backend
> import check via the new `tests/test_architecture.py` (the OS-independent gate).
> Paste all command output into `.opencode/E25/S4/verify.md`.

#### STEP 3 — PRE-COMMIT & TEST &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> On branch `E25-S4-isolation-tests` run:
> `pre-commit run --all-files`
> then `pytest -x -q`
> Fix any failures. Append final output to `.opencode/E25/S4/verify.md`.

#### STEP 4 — REVIEW &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Review E25 S4. Read `.opencode/E25/S4/plan.md`, `.opencode/E25/S4/verify.md`,
> and `git diff architecture-refactoring...E25-S4-isolation-tests`.
> Check every acceptance criterion in **'STAGE S4'** one by one.
> If any fail: write fix instructions to `.opencode/E25/S4/review-notes.md` and
> end with **BOUNCE**.
> If all pass: write **APPROVED** to `.opencode/E25/S4/review-notes.md`.
>
> On BOUNCE: re-run STEP 2 adding "also read `.opencode/E25/S4/review-notes.md`
> and fix every issue listed", then re-run STEP 3 and STEP 4. Repeat until APPROVED.

#### STEP 5 — COMMIT & MERGE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Commit and merge E25 S4. Run exactly:
> ```
> git add -A
> git commit -m "refactor(E25.S4): import-isolation invariant tests + cleanup"
> git checkout architecture-refactoring
> git merge --no-ff E25-S4-isolation-tests -m "merge(E25.S4): isolation tests and pyproject cleanup"
> git branch -d E25-S4-isolation-tests
> ```

---

## STAGE S5 — Strip re-exports + core-operation `api/` modules (import-discipline enforcement)

**Atomic deliverable:** the **import-discipline directive** is realised in code. Every
`__init__.py` is emptied of convenience re-exports; the consumer-facing surface becomes the
`api/` package alone. Two new core-operation api modules (`api/schema.py`, `api/visualization.py`)
expose schema validation, schema I/O, and rendering. Every internal module and test imports from
true deep paths. D8 closed. Large blast radius is expected and absorbed here.

**Why this stage runs after S1–S4:** the new layout (`profile/`, `backends/`, `cypher/`,
`api/inspection.py`, `api/execution.py`) must already exist so the re-export strip and the
true-path rewrites target final locations, not soon-to-move ones.

**Scope (touch):**
- NEW `src/orthograph/api/schema.py` — core schema operations, importing true paths:
  - `validate(model, nodes, relationships=None) -> ValidationResult`
    (wraps `orthograph.core.validator.GraphValidator`).
  - `load_schema(source) -> GraphDataModel` (wraps `orthograph.io.yaml.load_yaml_file` /
    `load_yaml_string`).
  - `save_schema(model, path) -> None` (wraps `orthograph.io.yaml.save_yaml_file`).
- NEW `src/orthograph/api/visualization.py` — rendering operations, importing true paths
  (`orthograph.visualization.mermaid`, `orthograph.visualization.text`,
  `orthograph.visualization.render`):
  - `render(obj, *, format="text") -> str`; `render_mermaid(model) -> str`;
    `render_schema_text`, `render_profile_text`, `render_result_text`; `display(model) -> None`.
- EDIT — **empty the re-exports** from EVERY `__init__.py`:
  - `src/orthograph/__init__.py` — remove ALL model/type/error re-exports (lines 8–55 today);
    keep only the module docstring and the `__version__` lookup.
  - `src/orthograph/visualization/__init__.py` — remove re-exports; the `render()` function it
    currently defines MOVES to `api/visualization.py` (or `visualization/render.py` imported by
    the api module — planner decides), leaving `visualization/__init__.py` empty.
  - `src/orthograph/catalogue/__init__.py` — remove re-exports (consumers/tests import from
    `orthograph.catalogue.typed` / `orthograph.catalogue.registry`).
  - `src/orthograph/profile/__init__.py`, `src/orthograph/profile/queries/__init__.py`,
    `src/orthograph/backends/__init__.py` and each `backends/*/__init__.py`,
    `src/orthograph/cypher/__init__.py`, `src/orthograph/api/__init__.py`,
    `src/orthograph/core/__init__.py`, `src/orthograph/io/__init__.py` — all empty of re-exports.
- EDIT — **rewrite every internal import to its true deep path.** Anything currently importing a
  convenience name (e.g. `from orthograph import GraphValidator`,
  `from orthograph.catalogue import ReadQuery`, `from orthograph.cypher import CypherGenerator`)
  becomes the true-source path (`from orthograph.core.validator import GraphValidator`,
  `from orthograph.catalogue.typed import ReadQuery`,
  `from orthograph.cypher.generator import CypherGenerator`).
- Tests — update ALL import sites (~50+ files) to true deep paths; capability tests import from
  `api/` (`from orthograph.api.schema import validate`,
  `from orthograph.api.visualization import render`). Add `tests/api/test_schema.py` and
  `tests/api/test_visualization.py`.
- EXTEND `tests/test_architecture.py` (created in S4) with the **no-re-export invariant**: assert
  every `__init__.py` under `src/orthograph/` contains no `from`/`import` re-export (the top-level
  file may keep only the `importlib`/`__version__` machinery). This is the OS-independent guard
  that makes D8 permanent. (If S4 was skipped/folded, CREATE `tests/test_architecture.py` here with
  both the cross-backend and the no-re-export assertions.)

**Key requirements:**
- After this stage, the ONLY `from orthograph import X` style imports that remain are
  `from orthograph.api.<module> import <fn>` for capabilities, and true deep paths for everything
  else. No package `__init__.py` re-exports any symbol.
- `api/schema.py` and `api/visualization.py` import full deep paths internally — those imports are
  the single, visible record of "what is exposed."
- Model *classes* are NOT wrapped by api functions; they are imported from their true core paths
  (`from orthograph.core.node_model import NodeModel`). Only *operations* live in `api/`.

**Acceptance criteria:**
- [ ] Every `__init__.py` under `src/orthograph/` is EMPTIED of re-exports (docstring +
      `__version__` only in the top-level file; the rest contain only a docstring). The files
      still EXIST (setuptools `packages.find` needs them). Verify (pwsh):
      `Get-ChildItem src/orthograph -Recurse -Filter __init__.py | Select-String -Pattern "^from |^import "`
      returns only `importlib`/`__version__` machinery in the top-level file and nothing in the rest.
- [ ] `api/schema.py` exposes `validate`, `load_schema`, `save_schema`; `api/visualization.py`
      exposes `render`, `render_mermaid`, `render_schema_text`, `render_profile_text`,
      `render_result_text`, `display`.
- [ ] No production module imports a symbol from a package `__init__` re-export; all imports are
      true deep paths (or `api/` for capabilities). Spot-check (pwsh):
      `Get-ChildItem src/orthograph -Recurse -Filter *.py | Select-String -Pattern "from orthograph import "` → returns nothing.
- [ ] `tests/api/test_schema.py` and `tests/api/test_visualization.py` exercise the new surface.
- [ ] All test import sites updated to true deep paths / `api/`; full suite green.
- [ ] Verification gate passes (pytest, mypy, no cross-backend import, no new deferred imports).
- [ ] D8 closed.

### Agent loop for this stage

Run steps in order. Do not start a step until the previous step is complete.
Branch for this stage: `E25-S5-strip-reexports` (cut from `architecture-refactoring`).

#### STEP 1 — PLAN &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Read sections **'STAGE S5'**, **'Shared Reference'** (especially 'Import discipline'), in
> `.agentic/planning/active_epics/E25_capability_seams_backend_isolation.md`.
> Then enumerate, using pwsh `Select-String`/`Get-ChildItem` over `src/orthograph/` and `tests/`
> (NOT `rg` — unavailable on win32), EVERY import site that uses a package-level convenience
> re-export, and EVERY `__init__.py` with re-exports.
> Produce: (a) the exact contents of `api/schema.py` and `api/visualization.py`; (b) a complete
> list of every `__init__.py` to empty; (c) a file-by-file list of import rewrites (old path ->
> true deep path) for both `src/` and `tests/`.
> Write the complete output to `.opencode/E25/S5/plan.md`. Do NOT write any code.

#### STEP 2 — EXECUTE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Read `.opencode/E25/S5/plan.md` and implement every item exactly as specified.
> Work on branch `E25-S5-strip-reexports`.
> When done, run (pwsh; `rg` is NOT available): `pytest -x -q`, `mypy src/orthograph`, the
> cross-backend import check, and the no-top-level-convenience-import check
> (`Get-ChildItem src/orthograph -Recurse -Filter *.py | Select-String -Pattern "from orthograph import "` — must print nothing).
> Paste all command output into `.opencode/E25/S5/verify.md`.

#### STEP 3 — PRE-COMMIT & TEST &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> On branch `E25-S5-strip-reexports` run:
> `pre-commit run --all-files`
> then `pytest -x -q`
> Fix any failures (formatting, unresolved imports, test regressions).
> Append final pass/fail output to `.opencode/E25/S5/verify.md`.

#### STEP 4 — REVIEW &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Review E25 S5. Read `.opencode/E25/S5/plan.md`, `.opencode/E25/S5/verify.md`,
> and `git diff architecture-refactoring...E25-S5-strip-reexports`.
> Check every acceptance criterion in **'STAGE S5'** one by one against the diff and test output.
> Confirm NO `__init__.py` re-exports remain and the only exposure path is `api/`.
> If any fail: write fix instructions to `.opencode/E25/S5/review-notes.md` and end with **BOUNCE**.
> If all pass: write **APPROVED** to `.opencode/E25/S5/review-notes.md`.
>
> On BOUNCE: re-run STEP 2 adding "also read `.opencode/E25/S5/review-notes.md`
> and fix every issue listed", then re-run STEP 3 and STEP 4. Repeat until APPROVED.

#### STEP 5 — COMMIT & MERGE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Commit and merge E25 S5. Run exactly:
> ```
> git add -A
> git commit -m "refactor(E25.S5): strip re-exports; add api/schema + api/visualization"
> git checkout architecture-refactoring
> git merge --no-ff E25-S5-strip-reexports -m "merge(E25.S5): import-discipline enforcement + core api modules"
> git branch -d E25-S5-strip-reexports
> ```

---

## STAGE S6 — Documentation, ADR & Epic reconciliation (RUN LAST, only after S1–S5 green)

**Atomic deliverable:** the `.agentic/` knowledge base reflects the new architecture. Obsolete
content removed; still-relevant content re-pathed; a new ADR records the decisions of this epic.

**Scope (touch):**
- NEW ADR `.agentic/decisions/011-capability-seams-and-backend-isolation.md`:
  - Decision: vendor-free capability interfaces (`api/`), vendor-isolated `backends/`, single
    `dependencies.py` authority; inspection currency in `profile/` with a shared `CypherInspector`
    base; **backend-specific introspection queries owned by each backend
    (`backends/<vendor>/queries.py`), only vendor-neutral Cypher in `profile/queries/shared.py`,
    each backend building its OWN catalogue (no profile-owned catalogue)**; connection injected
    per-call (inspection, a driver) / via factory (execution) and never owned.
  - Explicitly supersede: the `inspect(self)` (no-arg) contract; ADR-009's per-vendor query-FILE
    placement under `extensions/<vendor>/queries.py` (backend-specific queries now live in
    `backends/<vendor>/queries.py`; only vendor-neutral Cypher lives in `profile/queries/shared.py`);
    the `extensions/` package name.
  - Record the **import-discipline directive** (no re-exports in any `__init__.py`; `api/` modules
    are the sole exposure mechanism and import full deep paths) and its rejected alternative
    (convenience re-exports at package level).
  - Record rejected alternatives already decided this session (capability-only layout that hides
    vendor lineage; entry-point plugin discovery; keeping connection in constructor; full one-shot
    restructure without staging).
- EDIT `.agentic/knowledge/product_requirements_document.md`:
  - Update every capability path (`extensions/...` -> `backends/...`, `profile/...`, `cypher/...`).
  - Reaffirm Constraint 13 now matches code; note inspectors are stateless + per-call connection.
  - Remove the "*(not yet implemented)*" markers on the Query Catalogue (E16 done) — D5.
  - Document that the consumer-facing surface is `orthograph.api.*` (schema, visualization,
    inspection, execution); model classes are imported from their true `core` paths.
  - Update §"Implementation Decisions" item 4 (GqlAlchemyClient `save_*`) to reflect S2 outcome.
- EDIT `.agentic/knowledge/extension-contract.md`:
  - ABC -> `inspect(self, connection)`.
  - "Adding a New Inspection Backend" recipe -> subclass `CypherInspector` (or `GraphInspector` for
    non-Cypher), add `backends/<vendor>/queries.py` (backend-specific queries + a catalogue factory
    that registers the shared neutral queries from `profile.queries.shared`), add a
    `dependencies.py` row + `_registry` entry.
  - Update all source paths.
- EDIT `.agentic/CONTEXT.md`: add routing rows for `api/`, `dependencies.py`, `backends/`,
  `profile/`, `cypher/`.
- REVIEW every ACTIVE epic in `.agentic/planning/active_epics/` and `planning/overview.md`:
  - **E2 (Code Deduplication):** E2.2 (`pick_primary_label`), E2.4 (QueryStrategy — already retired
    by ADR-009), and the neo4j/memgraph inspector dedup are wholly or partly DONE by E25 (S1). Mark
    the absorbed tasks done/obsolete; re-path the rest.
  - **E4 (Extension Robustness):** re-path to `backends/`; reconcile with the new `dependencies.py`.
  - **E9 (GQLAlchemy Client Review) / E10 (Connection Ownership Audit):** S1+S2 implement much of
    their substance (per-call connection, no string dispatch). Mark the delivered parts done; keep
    only genuinely remaining scope; re-path.
  - **E23 (Inspector Backend-Behaviour Injection Interface):** E25's `api.inspect` + `CypherInspector`
    + `_registry` IS this interface. Likely supersede E23 entirely or reduce to residue; record the
    decision.
  - **E22 (E2E Test Coverage / shared-contract layer):** the S1 contract test seeds it; re-path and
    note the seam now exists.
  - Any epic referencing `orthograph.extensions.*` paths: update to new paths.
  - Update `planning/overview.md` epic table + dependency graph: mark E25 done; adjust statuses of
    E2/E4/E9/E10/E22/E23 per the above; remove dead links.
- Do a repo-wide search (pwsh `Select-String`) for BOTH `orthograph.extensions` AND the broken
  top-level convenience imports `from orthograph import …` in `.agentic/`, `README.rst`, `docs/`,
  and `notebooks/`. **README.rst and notebooks currently use both** (`from orthograph import
  GraphValidator` at `README.rst:119,149`; `from orthograph.extensions.neo4j import …` at
  `README.rst:170`). Rewrite every code example to the post-S5 surface:
  - capability operations -> `from orthograph.api.<module> import <fn>` (schema/visualization/
    inspection/execution);
  - model classes -> true core paths (`from orthograph.core.node_model import NodeModel`);
  - inspection -> `from orthograph.api.inspection import inspect`.
  Notebooks: update import cells; if a notebook is executed in CI (`nbval`), confirm it still runs.

**Acceptance criteria:**
- [ ] ADR-011 exists and records decisions + supersessions + rejected alternatives. It covers:
      the `api/model` + `api/database` + `api/visualization` three-module surface (not the stale
      `schema`/`inspection`/`execution` names); the two-verb `inspect`/`validate` split in
      `api.database`; the `backends/loader.py` typed-thunk loader (Amendment A already present);
      the import-discipline directive; rejected alternatives.
- [ ] ADR-003, ADR-006, ADR-008, ADR-009 each have a supersession/correction note for their stale
      `extensions/` path references (R3–R9 in the conflict register above).
- [ ] PRD, extension-contract.md, CONTEXT.md contain NO stale `extensions/...` paths; all capability
      links resolve to real files in the new layout (`api/model.py`, `api/database.py`,
      `api/visualization.py`; NOT the stale `schema.py`/`inspection.py`/`execution.py` names).
- [ ] D5 markers removed from PRD; Constraint 13 reaffirmed.
- [ ] Two `validate` verbs documented explicitly: `api.model.validate` (in-memory data validation)
      vs `api.database.validate` (live-DB validation against a model).
- [ ] Every active epic reviewed: absorbed tasks marked done/obsolete, survivors re-pathed,
      `overview.md` table + graph updated; E25 marked done.
- [ ] No `.agentic/` doc references a path that no longer exists (search clean for `orthograph.extensions`).
- [ ] `README.rst`, `docs/`, and `notebooks/` code examples use the post-S5 surface only: no
      `from orthograph import <name>` convenience imports, no `orthograph.extensions.*` paths.
      Capability examples use `orthograph.api.*` (specifically `api.model`, `api.database`,
      `api.visualization`); model classes use true `core` paths.

### S5→S6 conflict register (READ BEFORE PLANNING — do NOT silently revert S5 changes)

S5 diverged from the original S6 scope in several significant ways. These are **improvements**,
not mistakes. The planner MUST update the docs to match reality; it must NOT revert the S5
design to match the stale S6 plan text.

| ID | Conflict | What S5 actually built | What stale S6 plan says | Required S6 action |
|----|----------|------------------------|-------------------------|--------------------|
| R1 | `api/` module names | `model.py`, `database.py`, `visualization.py` | `schema.py`, `inspection.py`, `execution.py` | Update ALL doc references (ADR-011, PRD, extension-contract, CONTEXT, epics) to the actual names. Do NOT recreate old modules. |
| R2 | `api/visualization.py` functions | `render_model`, `render_profile`, `render_result`, `display` | `render`, `render_mermaid`, `render_schema_text`, `render_profile_text`, `render_result_text`, `display` | Update all doc references to actual function names. |
| R3 | `inspect` signature | Two explicit verbs: `api.database.inspect(backend, conn)→GraphProfile` and `api.database.validate(backend, conn, model)→ValidationResult` | One overloaded `inspect(backend, conn, model=None)→GraphProfile\|ValidationResult` | Update extension-contract "Adding a New Backend" recipe + PRD to the two-verb shape. |
| R4 | `api/_registry.py` | Deleted — replaced by `backends/loader.py` (typed thunks, `load_inspector`/`load_executor`) | S6 scope says update `api/__init__.py` `_registry` bullet | ADR-011 Amendment A already records this. Verify ADR-011 is complete; do NOT re-add `_registry`. |
| R5 | ADR-011 already exists | File `decisions/011-e25-capability-seams-backend-isolation.md` exists with Amendment A | S6 scope says "NEW ADR-011" | Extend existing ADR-011 with the sections it is missing: import-discipline detail, rejected alternatives, D5 closure, `api/model`+`api/database` decision rationale. Do NOT recreate from scratch. |
| R6 | ADR-009 §12 checklist stale paths | Actual: `orthograph.cypher.identifiers`, `orthograph.cypher` | ADR-009 §12: `orthograph.extensions.cypher.*` | Amend ADR-009 §12 to correct paths. |
| R7 | ADR-008 cross-references stale paths | Actual: `src/orthograph/cypher/`, `tests/cypher/` | ADR-008: `extensions/cypher/`, `tests/extensions/cypher/` | Amend ADR-008 cross-references. |
| R8 | ADR-006 references stale home | Actual: `orthograph.backends.gqlalchemy` | ADR-006: `orthograph.extensions.gqlalchemy` | Add supersession note to ADR-006. |
| R9 | ADR-003 references `extensions/` package | Actual: `backends/` | ADR-003: `extensions/` as neo4j/memgraph/networkx home | Add supersession note to ADR-003. |
| R10 | Two distinct `validate` verbs | `api.model.validate` (in-memory data) vs `api.database.validate` (live DB) | No prior ADR or doc distinguishes these explicitly | Document the distinction explicitly in PRD and extension-contract. |

### Agent loop for this stage

Run steps in order. Do not start a step until the previous step is complete.
Branch for this stage: `E25-S6-docs-reconciliation` (cut from `architecture-refactoring`).

#### STEP 1 — PLAN &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> **CRITICAL: read the 'S5→S6 conflict register' table above FIRST** before reading anything
> else. It lists 10 divergences between what S5 actually built and what this S6 scope text
> expected. You must produce a plan that updates docs to match reality — NOT a plan that
> silently reverts S5's improvements to match stale text.
>
> Read sections **'STAGE S6'**, **'Shared Reference'**, **'Decision log'**, and the
> **'S5→S6 conflict register'** in
> `.agentic/planning/active_epics/E25_capability_seams_backend_isolation.md`.
> Then read every file listed in **'Scope (touch)'**:
> all `.agentic/decisions/` ADRs (including the already-existing `011-e25-capability-seams-backend-isolation.md`),
> `.agentic/knowledge/product_requirements_document.md`,
> `.agentic/knowledge/extension-contract.md`, `.agentic/CONTEXT.md`,
> `src/orthograph/api/` (directory listing + read all three files: `model.py`, `database.py`,
> `visualization.py`), and every active epic in `.agentic/planning/active_epics/`.
>
> Produce a doc-by-doc change list that:
> (a) Resolves every conflict in the R1–R10 register above (update docs to match S5 reality);
> (b) Extends (NOT recreates) the existing ADR-011 with missing sections;
> (c) Updates stale `extensions/` paths in ADR-003, ADR-006, ADR-008, ADR-009;
> (d) Covers all remaining S6 scope items (PRD D5 markers, epic reconciliation, etc.).
>
> Write the complete output to `.opencode/E25/S6/plan.md`.
> Do NOT edit any files.

#### STEP 2 — EXECUTE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Read `.opencode/E25/S6/plan.md` and apply every edit exactly as specified.
> Work on branch `E25-S6-docs-reconciliation`.
> When done, run (pwsh; no `rg`):
> `Get-ChildItem .agentic,README.rst,docs,notebooks -Recurse -Include *.md,*.rst,*.ipynb,*.py | Select-String -Pattern "orthograph\.extensions"`
> `Get-ChildItem .agentic,README.rst,docs,notebooks -Recurse -Include *.md,*.rst,*.ipynb,*.py | Select-String -Pattern "from orthograph import "`
> Both must return nothing except references the plan explicitly justifies (e.g. historical ADR
> quotes). Paste output into `.opencode/E25/S6/verify.md`.

#### STEP 3 — PRE-COMMIT & TEST &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> On branch `E25-S6-docs-reconciliation` run:
> `pre-commit run --all-files`
> (no pytest needed — this stage is docs only).
> Fix any pre-commit failures. Append output to `.opencode/E25/S6/verify.md`.

#### STEP 4 — REVIEW &nbsp;&nbsp; model: `claude-opus-4-8`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-opus-4-8
```

> Review E25 S6. Read `.opencode/E25/S6/plan.md`, `.opencode/E25/S6/verify.md`,
> and `git diff architecture-refactoring...E25-S6-docs-reconciliation`.
> Check every acceptance criterion in **'STAGE S6'** one by one.
> Verify: ADR-011 exists with all required sections (including the import-discipline
> directive); no stale `extensions/` paths remain in any `.agentic/` doc; every active
> epic that overlaps E25 has been updated; overview.md marks E25 done.
> If any fail: write fix instructions to `.opencode/E25/S6/review-notes.md` and
> end with **BOUNCE**.
> If all pass: write **APPROVED** to `.opencode/E25/S6/review-notes.md`.
>
> On BOUNCE: re-run STEP 2 adding "also read `.opencode/E25/S6/review-notes.md`
> and fix every issue listed", then re-run STEP 3 and STEP 4. Repeat until APPROVED.

#### STEP 5 — COMMIT & MERGE &nbsp;&nbsp; model: `claude-sonnet-4-6`

```
opencode --model portkey/@bedrock-aifoundry-euc1-001/eu.anthropic.claude-sonnet-4-6
```

> Commit and merge E25 S6. Run exactly:
> ```
> git add -A
> git commit -m "docs(E25.S6): ADR-011 + PRD/contract/epic reconciliation"
> git checkout architecture-refactoring
> git merge --no-ff E25-S6-docs-reconciliation -m "merge(E25.S6): documentation and epic reconciliation"
> git branch -d E25-S6-docs-reconciliation
> ```

---

## Final merge (after S6 green)

- `pre-commit run --all-files` clean.
- Final review confirms ALL stage acceptance criteria across S1–S6 are checked.
- Merge `architecture-refactoring` -> `dev`.
- Move this epic to `archived_epics/` and mark **done** in `overview.md`.

---

## Decision log (this session, for ADR-011 input)

- Backends stay physically separate, one folder per library; layout must NOT lose
  "what-depends-on-what" (vendor lineage). (User, 2026-06-11.)
- Public interface per functionality + ONE dependency-validation module. (User.)
- Backend loading: **registry with lazy import**; `dependencies.py` probes the extra first. (User.)
- Connection: **never owned**; per-call injection for inspection, consumer-owned factory for
  sustained execution. (User.)
- `cypher/` is a top-level language module, not a backend. (User.)
- Two public APIs: `inspection` (analyse one DB after selecting backend) and `execution` (run
  queries/catalogue against a DB). (User.)
- Backend-specific inspection queries live in their OWN backend (`backends/<vendor>/queries.py`),
  which builds its own catalogue. Only VENDOR-NEUTRAL Cypher (cardinality, endpoint-labels,
  `coerce_types`) lives in `profile/queries/shared.py`. Each backend imports the shared neutral
  queries and registers them into its own catalogue; neither backend imports the other (the
  catalogue is the assembly point). (User, 2026-06-11 — corrected the earlier "queries clustered
  in profile/ by origin" decision, which leaked backend code into profile/.)
- **No profile-owned catalogue.** A single profile-owned catalogue that backends populate is
  rejected: it would force a high-level module to import every backend to populate it (the leak).
  Each adapter builds its OWN catalogue privately. Vendor NAMES appear only in the `backends/loader.py`
  dispatch table and `dependencies.py`; `profile/` and `api/` never name a vendor. No circular
  dependency exists because all imports point down (`backends/* -> profile`, `api -> backends.loader ->
  backends`). The adapter is the single object that pairs the right connection with the right
  queries. (User, 2026-06-11.)
- Shared `CypherInspector` base in `profile/` absorbs the byte-identical neo4j/memgraph inspector
  internals; networkx stays its own inspector. (User, Recommended option.)
- No backward compatibility — change signatures/paths outright, no shims. (User.)
- **Import discipline:** every module imports from the TRUE source location (full deep paths),
  even at the cost of long imports and a large blast radius. NO convenience re-exports in any
  `__init__.py`. The ONLY mechanism to expose functionality is a deliberate `api/` module that
  itself imports full deep paths — maximising source visibility. (User, 2026-06-11.)
- `api/` covers core operations too: `api/model.py` (load/save/validate schema in-memory) and
  `api/visualization.py` (render). `api/database.py` covers live-DB operations (inspect, validate,
  query, execute). Model *classes* are imported from their true `core` paths, not
  wrapped — only *operations* are exposed via `api/`. (User.)
