# ADR-033: Three-Way Neo4j Inspection Strategy — `db.schema.*` as a Type-Bearing Fallback

**Status:** Accepted — 2026-06-19
**Category:** extensions / inspection
**Epic:** E44 (Neo4j `db.schema.*` inspection strategy)
**Depends on:** ADR-009 (inspector query alignment; §8 sanctioned the `_detect_strategy()` + constructor selector), ADR-012 (optional-dependency policy; APOC is optional)
**Relates:** ADR-008 (Cypher identifier safety), ADR-015 (declared/observed mirror), ADR-030 / E41 (per-pair cardinality — shares the catalogue-factory surface)

---

## Context

`Neo4jInspector` selects one of two query sets to read property metadata:

| Strategy | Source | `observed_types` | Completeness counts |
|----------|--------|------------------|---------------------|
| APOC | `apoc.meta.{node,rel}TypeProperties({sample:-1})` | **populated** (`String`, `Long`, …) | **true** (`propertyObservations` / `totalObservations`) |
| pure-Cypher | two-pass `MATCH (n:` … `) UNWIND keys(n)` | **always `[]`** | **true** (counted in-query) |

Selection is auto-detected by:

```cypher
SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.meta' RETURN count(name) AS cnt
```

**The observed failure.** On a real Neo4j 5.12 Enterprise instance (Neo4j Desktop)
the installed plugin was `apoc5plus` (**APOC Extended**), which does **not**
register `apoc.meta.*`. The probe returned `0`, the inspector fell back to
pure-Cypher, and every `PropertyProfile.observed_types` came back `[]` — even
though APOC Core was present in the download cache and the procedure
`db.schema.nodeTypeProperties()` (a **built-in**, no plugin) was available the
whole time.

Two problems surface:

1. **Type information is needlessly lost** whenever APOC Core is not the installed
   APOC flavour. Neo4j ships `db.schema.nodeTypeProperties()` /
   `db.schema.relTypeProperties()` as built-ins since 4.x; they return the same
   `propertyTypes` column APOC does.
2. **The detection is plugin-fragile and not reproducible.** A profiling run's
   output silently depends on which APOC jar an operator happened to drop into
   `plugins/`. A user asked, correctly, whether a native path exists and whether a
   backend-scoped seam should encode it.

### What `db.schema.*` does and does **not** give

`CALL db.schema.nodeTypeProperties() YIELD nodeType, nodeLabels, propertyName,
propertyTypes, mandatory` — and the `relTypeProperties` counterpart — yield
`propertyTypes` (the win) and a `mandatory` boolean, but **no observation counts**
(`propertyObservations` / `totalObservations`). This is the **same shape Memgraph's
`schema.node_type_properties()` already returns**, which the Memgraph inspector
handles with the documented mandatory-heuristic (`present_count = int(mandatory)`,
`total_count = 1`) per ADR-009 §6.

So the three strategies trade off two independent axes:

| Strategy | `observed_types` | completeness counts |
|----------|------------------|---------------------|
| APOC | yes | **true** |
| `db.schema.*` | yes | **heuristic only** (mandatory bool) |
| pure-Cypher | no | **true** |

`db.schema.*` is not a strict superset of pure-Cypher: it gains **types** but loses
**true completeness counts**. This tension drives the decision below.

---

## Decision

### 1. A third inspection strategy: `SCHEMA`, scoped to `backends/neo4j/`

Introduce `db.schema.*`-backed property queries as a third Neo4j strategy. The
strategy concept stays **inside `backends/neo4j/`** — it is not promoted to the
vendor-free `graph_profile/` layer. Rationale: ADR-009 Decision 1 makes
`inspect() -> GraphProfile` the *only* cross-backend contract; query-set selection
is backend-private. Memgraph needs no detection (it always has `schema.*`), and
ADR-012 §4 forbids vendor concepts in vendor-free layers. The seam the user asked
about is therefore the existing `_detect_*` / catalogue-selection seam, widened
from two strategies to three — exactly the surface ADR-009 §8 already named.

### 2. Combined type + count strategy (the key choice)

Because `db.schema.*` yields types-but-not-counts and pure-Cypher yields
counts-but-not-types, the `SCHEMA` strategy **combines** them rather than replacing
pure-Cypher:

- It runs the pure-Cypher two-pass scan to obtain **true** `propertyObservations` /
  `totalObservations` (unchanged), **and**
- enriches each property with the `propertyTypes` reported by `db.schema.*`.

This keeps completeness fidelity identical to today's fallback while adding the
type information that was being lost. The merge is per `(label, propertyName)` for
nodes and `(rel_type, propertyName)` for relationships; a property present in the
scan but absent from `db.schema.*` (or vice-versa) keeps its scan-derived counts
with `observed_types = []`.

> **Rejected simpler variant:** a `SCHEMA` strategy that uses *only* `db.schema.*`
> and adopts Memgraph's mandatory-heuristic for counts. Rejected because it would
> **regress completeness accuracy** for existing pure-Cypher users (true counts →
> 1/1 heuristic) in exchange for types — a silent downgrade on the count axis. The
> combined approach strictly dominates: same counts as today, plus types.

### 3. Auto-detection precedence: APOC → `db.schema.*` → pure-Cypher

When the strategy is auto (the default), detect in order:

1. `apoc.meta.*` available → `APOC` (true counts + types via one procedure;
   **no behavioural change for existing APOC-Core users** — this is the regression
   guard).
2. else `db.schema.nodeTypeProperties` available → `SCHEMA` (true counts via scan +
   types via `db.schema.*`).
3. else → `CYPHER` (true counts, no types — unchanged last resort).

APOC stays first so no existing profile or test that runs against APOC Core changes
output. `db.schema.*` displaces *pure-Cypher* (the no-types path), never APOC.

### 4. Explicit selector; deprecate `use_apoc`

`Neo4jInspector.__init__` gains `strategy: Neo4jInspectionStrategy | None = None`
(enum: `APOC`, `SCHEMA`, `CYPHER`; `None` = auto-detect per §3). The existing
`use_apoc: bool | None` parameter is **kept as a deprecated keyword** that maps onto
the enum (`True → APOC`, `False → CYPHER`, `None → auto`) and emits a
`DeprecationWarning`. This preserves every current caller (ADR-009 §8 flagged this
constructor as a breaking-change surface; we choose the non-breaking path). Removal
of `use_apoc` is a future, separately-noted change.

### 5. Identifier safety unchanged (ADR-008)

The `SCHEMA` strategy's scan half reuses the existing pure-Cypher queries (already
identifier-safe). Its `db.schema.*` half is a bulk `CALL` with **no interpolated
identifiers** (like the Memgraph bulk queries), so it introduces no new injection
surface. Any label/rel-type filtering happens in `materialize()` / inspector
aggregation, not in query text.

### 6. Catalogue parity and E41 coordination

A `build_schema_catalogue()` factory joins `build_apoc_catalogue()` and
`build_cypher_catalogue()` in `backends/neo4j/queries.py`, registering the same
shared neutral queries (cardinality, endpoint-labels, constraints) plus the
`SCHEMA` property queries. **E41 coordination:** E41 (ADR-030) will register
`InspectPartitionedCardinalityQuery` in the APOC and Cypher catalogues; once this
ADR lands there are **three** catalogues, so E41.4 must register the partitioned
query in all three. This is the same "coordinate on a shared surface" obligation
E42↔E43 carried on `models.py`; recorded here and as a note in E41.4.

---

## Consequences

- Profiling produces `observed_types` on **any** Neo4j instance with the built-in
  `db.schema.*` procedures (4.x+), regardless of whether APOC — and which APOC
  flavour — is installed. The plugin-fragility that produced the observed failure
  is removed from the default path.
- **No regression on two axes:** APOC-Core users are unaffected (APOC stays first);
  pure-Cypher's true completeness counts are preserved by the combined strategy
  (§2). Existing default-suite tests that assert pure-Cypher behaviour for an
  APOC-absent mock must be updated to expect `SCHEMA` (now that `db.schema.*` is
  detected first among the no-APOC options) — this is an intended,
  documented test change, not a silent behaviour drift.
- One new strategy, one new catalogue factory, two new property-query classes
  (node + rel) that compose the existing scan with a `db.schema.*` type lookup, an
  enum, a second detection probe, and a deprecation shim. Backend-scoped; the
  vendor-free contract is untouched.
- The mandatory-heuristic question that Memgraph carries does **not** propagate
  here, because the combined strategy keeps real counts from the scan.

---

## Cross-references

- ADR-009 §8: sanctioned `_detect_strategy()` + the `strategy`/`use_apoc` constructor selector (2-way); this ADR widens it to 3-way.
- ADR-009 §6: Memgraph mandatory-heuristic for `db.schema`-shaped count-less procedures (the variant §2 deliberately avoids).
- ADR-012: APOC is optional; this strategy reduces the library's dependence on it for type information.
- ADR-030 / E41: shares the catalogue-factory surface — see §6 coordination note.
- Inspector: `src/orthograph/backends/neo4j/inspector.py` (`_detect_apoc` → `_detect_strategy`).
- Queries / catalogues: `src/orthograph/backends/neo4j/queries.py` (`build_apoc_catalogue`, `build_cypher_catalogue`, new `build_schema_catalogue`).
- Profile models: `src/orthograph/graph_profile/models.py` (`PropertyProfile.observed_types`).
- E44 epic: `.agentic/planning/active_epics/E44_neo4j_db_schema_inspection_strategy.md`
