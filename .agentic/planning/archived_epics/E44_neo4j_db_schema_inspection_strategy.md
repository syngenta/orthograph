# Epic E44: Neo4j `db.schema.*` Inspection Strategy — Reproducible Type Detection

> **Priority:** Medium (fixes a reproducibility gap in profiling; unblocks accurate `observed_types` without APOC)
> **Phase:** v0.1.0
> **Blocked by:** none (independent; **land before E41** — see Coordination)
> **Type:** Build (third Neo4j inspection strategy + auto-detection + deprecation shim) + parity tests
> **Decisions:** ADR-033 (read it first — it is the spec), ADR-009 (§8 selector seam, §6 Memgraph count-less shape), ADR-008 (identifier safety), ADR-012 (APOC optional)
> **Rubric (every task judged against this):** strongly-typed · SOLID · readability over cleverness · backend-scoped (no vendor concept leaks into `graph_profile/`) · **no regression** to APOC-Core output or to pure-Cypher completeness counts · backend parity discipline (ADR-009) · each task ends green with guardrails run

---

## Why This Epic Exists

`Neo4jInspector` auto-selects APOC or pure-Cypher to read property metadata. On a
real Neo4j 5.12 Enterprise instance the installed APOC flavour was **APOC Extended**
(`apoc5plus`), which does **not** register `apoc.meta.*`. Detection returned `0`,
the inspector fell back to pure-Cypher, and **every** `PropertyProfile.observed_types`
came back `[]` — despite the built-in `db.schema.nodeTypeProperties()` procedure
being available the whole time.

Result: a profiling run's type output silently depends on which APOC jar an operator
dropped into `plugins/` — **not reproducible**. This epic adds a third strategy that
reads property **types** from the always-present built-in `db.schema.*` procedures,
combined with the existing pure-Cypher scan so **true completeness counts are kept**.
Auto-detection prefers APOC → `db.schema.*` → pure-Cypher, so APOC-Core users see no
change and the no-types fallback is displaced, not the accurate one.

---

## Decisions Already Made (do not re-litigate — see ADR-033)

- The strategy concept stays **inside `backends/neo4j/`**; it is **not** promoted to
  the vendor-free `graph_profile/` layer (ADR-009 D1, ADR-012 §4).
- `SCHEMA` strategy **combines** the pure-Cypher scan (true counts) with a
  `db.schema.*` type lookup (types). It does **not** use the Memgraph
  mandatory-heuristic for counts — that would regress count fidelity (ADR-033 §2).
- Auto-detection precedence is fixed: **APOC → `db.schema.*` → pure-Cypher**
  (ADR-033 §3). APOC stays first as the regression guard.
- Constructor gains `strategy: Neo4jInspectionStrategy | None`; `use_apoc` is **kept
  and deprecated** (maps onto the enum + `DeprecationWarning`), not removed
  (ADR-033 §4).
- `db.schema.*` queries are **bulk, no interpolated identifiers** — no new injection
  surface (ADR-033 §5).
- A third `build_schema_catalogue()` joins the two existing factories; **E41.4 must
  register its partitioned query in all three** (ADR-033 §6).

---

## Existing Code to Reuse

| Need | Reuse | Location |
|------|-------|----------|
| Pure-Cypher property scan (true counts) | `CypherNodePropertiesQuery`, `CypherRelPropertiesQuery` | `backends/neo4j/queries.py` |
| Row currency | `NodePropertyRow` | `backends/neo4j/queries.py` |
| Bulk `schema.*` shape precedent | `MemgraphNodePropertiesQuery`, `MemgraphRelPropertiesQuery`, `coerce_types` | `backends/memgraph/queries.py`, `graph_profile/queries/shared.py` |
| Catalogue factories | `build_apoc_catalogue`, `build_cypher_catalogue` | `backends/neo4j/queries.py` |
| Detection seam | `_detect_apoc`, `_resolve_catalogue` | `backends/neo4j/inspector.py` |
| Profile builders | `_build_node_profile`, `_build_rel_profile` | `backends/neo4j/inspector.py` |
| Type field | `PropertyProfile.observed_types` | `graph_profile/models.py` |
| Mock-driver test harness | existing `FakeGraphSession` / mock patterns | `tests/backends/neo4j/test_inspector.py` |

---

## Per-Task Guardrails (apply to EVERY task unless stated)

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

Live-DB tests are opt-in (`--neo4j`); default-suite tests use mocked drivers. The
strategy is backend-scoped — `tests/test_architecture.py` must stay green (no vendor
import leaks into vendor-free layers).

---

## Tasks (execute in order; each ends green)

### E44.0 — ADR-033 (done in planning) + confirm `db.schema.*` column shape

> **Model: Sonnet.** Decision is recorded; this task only verifies the procedure signature against a live instance and locks the query text.

**Goal:** the spec exists (ADR-033) and the exact `YIELD` columns of
`db.schema.nodeTypeProperties()` / `db.schema.relTypeProperties()` are confirmed so
E44.1's query text is correct.

**Operation:**
1. Against a live Neo4j (opt-in), confirm:
   `CALL db.schema.nodeTypeProperties() YIELD nodeType, nodeLabels, propertyName, propertyTypes, mandatory`
   and `CALL db.schema.relTypeProperties() YIELD relType, propertyName, propertyTypes, mandatory`.
2. Record any version-specific column differences (4.x vs 5.x) in a one-line comment
   in `queries.py` where the new classes will live.

**Care / risks:** if a supported Neo4j version omits a column, the materialiser must
default it (mirror Memgraph's `.get(...)` defensiveness). Do not assume counts exist
— they do not.

---

### E44.1 — `SCHEMA` property queries + `build_schema_catalogue()`

> **Model: Opus.** The load-bearing correctness core: the combined types-from-`db.schema` + counts-from-scan merge, the bulk-query materialiser, and the new catalogue. Gets the data shape and the merge semantics right so the inspector task is mechanical.

**Goal:** two new query classes expose `db.schema.*` property **types**, and a third
catalogue assembles the `SCHEMA` strategy.

**Operation** — in `src/orthograph/backends/neo4j/queries.py`:
1. Add `DbSchemaNodeTypesQuery` and `DbSchemaRelTypesQuery` (bulk; `Identifiers =
   NoIdentifiers`; imperative `build()` like the Memgraph bulk queries, since
   `CALL db.schema.*` is not standard Cypher the graphglot parser accepts). Output a
   small projection row carrying `label`/`rel_type`, `property_name`,
   `property_types` (via `coerce_types`). Mirror `MemgraphNodePropertyRow` /
   `MemgraphRelPropertyRow` precisely in shape and stripping of `:` `` ` `` prefixes.
2. Add `build_schema_catalogue()`: register the shared neutral queries
   (`InspectNodeLabelsQuery`, `InspectRelTypesQuery`, `InspectCardinalityQuery`,
   `InspectNeo4jConstraintsQuery`, `InspectEndpointLabelsQuery`) **and** the existing
   `CypherNodePropertiesQuery` / `CypherRelPropertiesQuery` (for true counts) **and**
   the two new `DbSchema*` type queries.

**Tests (TDD — write first)** — `tests/backends/neo4j/test_inspector_queries.py`:
- `DbSchemaNodeTypesQuery.build()` emits the confirmed `CALL db.schema...` text; no
  `<<...>>` slots (bulk, no identifiers).
- `materialize()` maps a raw row (incl. `:` `` ` ``-wrapped `nodeType`, list
  `propertyTypes`) to the projection with a clean label and `observed_types`.
- `build_schema_catalogue()` registers exactly the expected query names (parity with
  the other two factories' membership tests).

**Care / risks:** the `db.schema.*` rows carry **no counts** — the projection must
**not** invent any. Counts come exclusively from the pure-Cypher scan in E44.2. Keep
the two halves independent so the merge in the inspector is the single join point.

---

### E44.2 — Inspector: `_detect_strategy()`, `strategy` enum, count+type merge

> **Model: Opus.** The three-way detection, the strategy enum, the `use_apoc` deprecation shim, and the per-`(label, property)` merge of scan-counts with `db.schema` types. The behaviour the whole epic hinges on.

**Goal:** `Neo4jInspector` auto-detects three strategies, exposes a `strategy`
selector (deprecating `use_apoc`), and under `SCHEMA` produces profiles with **true
counts and populated `observed_types`**.

**Operation** — in `src/orthograph/backends/neo4j/inspector.py`:
1. Add `class Neo4jInspectionStrategy(str, Enum)`: `APOC = "apoc"`, `SCHEMA =
   "schema"`, `CYPHER = "cypher"`.
2. `__init__(self, strategy: Neo4jInspectionStrategy | None = None, *, use_apoc:
   bool | None = _UNSET)`: if `use_apoc` is passed, emit `DeprecationWarning` and map
   `True→APOC`, `False→CYPHER`, `None→auto`; `strategy` wins if both given (document).
3. Rename `_detect_apoc` → `_detect_strategy` returning a `Neo4jInspectionStrategy`:
   probe `apoc.meta` (→ APOC), else probe `db.schema.nodeTypeProperties` via
   `SHOW PROCEDURES` (→ SCHEMA), else CYPHER. Keep the existing APOC probe text.
4. `_resolve_catalogue` selects among the three `build_*_catalogue()` factories.
5. In `_build_node_profile` / `_build_rel_profile`, when strategy is `SCHEMA`: run the
   pure-Cypher property query for counts (as today) **and** the `DbSchema*` type query;
   **merge** by `(label/rel_type, property_name)` — counts from the scan,
   `observed_types` from `db.schema.*`; properties seen only by the scan keep
   `observed_types = []`. APOC and CYPHER paths are unchanged.

**Tests (TDD — write first)** — `tests/backends/neo4j/test_inspector.py` (mocked) +
`tests/backends/neo4j/test_inspector_e2e.py` (opt-in):
- mocked: `apoc.meta` present → strategy `APOC`, output unchanged (regression lock).
- mocked: `apoc.meta` absent, `db.schema` present → strategy `SCHEMA`; a node property
  gets **both** true counts (from the scan rows) **and** `observed_types` (from the
  `db.schema` rows) — the merge assertion.
- mocked: both absent → strategy `CYPHER`; `observed_types == []`, counts intact
  (today's behaviour, now the explicit last resort).
- `Neo4jInspector(use_apoc=False)` emits `DeprecationWarning` and behaves as
  `strategy=CYPHER`; `Neo4jInspector(use_apoc=True)` as `APOC`.
- explicit `strategy=Neo4jInspectionStrategy.SCHEMA` forces the merge path regardless
  of probes.
- e2e (opt-in `--neo4j`): on an instance **without** `apoc.meta` but with
  `db.schema.*`, a seeded graph yields populated `observed_types` and correct
  completeness — the reproduced-failure scenario, now fixed.

**Care / risks:** **APOC-first is the regression guard** — verify no existing
APOC-path test changes. Existing tests that assumed pure-Cypher for an APOC-absent
mock now get `SCHEMA`; update them deliberately (ADR-033 Consequences) and confirm the
counts they assert are unchanged. The `use_apoc` default sentinel must distinguish
"not passed" from "passed `None`".

---

### E44.3 — Docs, profiling guide, overview/CONTEXT hygiene

> **Model: Sonnet.** Documentation + planning hygiene; no new logic.

**Operation:**
1. Update `notebooks/profiling_neo4j_APOC.md` (or rename/extend): document the
   three strategies, the auto-detection order, the APOC-Extended-vs-Core pitfall that
   motivated this, and the `db.schema.*` fallback. Note the count vs type tradeoff
   table from ADR-033.
2. PRD line 338 currently reads *"live inspection via APOC + pure Cypher fallback
   strategy"* — update to name the three strategies, cross-link ADR-033.
3. Add the **E44 row** to `.agentic/planning/overview.md` (Epics table + dependency
   note: independent, land before E41) and the Active list + Epic Files list.
4. Add ADR-033 to the PRD "Key Architectural References" list if inspector-strategy
   detail warrants it; add a CONTEXT.md routing row only if a documented boundary
   changed (the inspection-contract row may now point at ADR-033 for the strategy
   detail).

**Tests / verify:**
```
pwsh> python -m pytest --nbval-lax notebooks/<touched notebook>.ipynb -q   # if a notebook gains a cell
pwsh> python -m pytest -q
pwsh> python -m mypy src/orthograph
```

**Care / risks:** keep notebook deterministic / DB-free in the default path. Do not
overclaim: `db.schema.*` gives types but the **counts still come from the scan** —
state this so a reader does not expect APOC-grade per-type counts.

---

## Success Criteria

- [ ] `Neo4jInspectionStrategy` enum exists; `Neo4jInspector(strategy=…)` selects APOC / SCHEMA / CYPHER; `use_apoc` still works and emits `DeprecationWarning`.
- [ ] Auto-detection order is APOC → `db.schema.*` → pure-Cypher; APOC-Core output is byte-for-byte unchanged (regression lock green).
- [ ] Under `SCHEMA`, `PropertyProfile` carries **true completeness counts** (from the scan) **and** populated `observed_types` (from `db.schema.*`); scan-only properties keep `observed_types = []`.
- [ ] `build_schema_catalogue()` exists with parity membership tests; `db.schema.*` queries carry no interpolated identifiers (no new injection surface).
- [ ] Opt-in e2e reproduces the original failure (APOC-Extended only) and shows it fixed: `observed_types` populated via `db.schema.*`.
- [ ] `tests/test_architecture.py` green — no vendor concept leaked into `graph_profile/`; full suite + mypy + pre-commit green.
- [ ] Docs updated (profiling guide + PRD line 338); overview/CONTEXT updated; E41.4 carries the "register partitioned query in `build_schema_catalogue` too" note.

---

## Coordination with E41 (mandatory)

E41 (ADR-030, planned) registers `InspectPartitionedCardinalityQuery` in
`build_apoc_catalogue` and `build_cypher_catalogue`. After E44 there are **three**
catalogues. **Land E44 before E41**, and add a one-line note to **E41.4** that the
partitioned-cardinality query must also be registered in `build_schema_catalogue`.
This mirrors the E42↔E43 "coordinate on the shared surface" obligation. If E41 lands
first instead, E44.1 must add the partitioned query to the new catalogue at creation.

---

## Out of Scope

- Changing the vendor-free `graph_profile/` inspection contract or promoting the
  strategy concept out of `backends/neo4j/` (ADR-009 D1 — frozen here).
- Per-type value counts (`observed_type_counts`) — still the ADR-015 B1 TODO; neither
  APOC nor `db.schema.*` returns per-type counts. Untouched.
- Removing `use_apoc` (deprecation only; removal is a separate future change).
- Memgraph changes — Memgraph already reads `schema.*`; its mandatory-heuristic is
  unchanged (ADR-009 §6).
- Auto-installing or copying APOC jars — operator concern, not a library concern.
