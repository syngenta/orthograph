# Neo4j Property-Type Detection Strategies

**Status:** Implemented (E44 — ADR-033)
**Related decisions:** ADR-012 (optional dependencies), ADR-009 (inspector contract)
**Epics:** E44 (Neo4j `db.schema.*` inspection strategy), E41 (per-pair cardinality — shares catalogue factory surface)

---

## What This Addresses

`Neo4jInspector` reads `PropertyProfile.observed_types` (what data types are stored in each property) using one of three strategies, auto-detected in order of preference:

| Strategy | Source | `observed_types` | Completeness counts |
|---|---|---|---|
| **APOC** | `apoc.meta.*` procedures (requires APOC **Core**) | populated | true |
| **SCHEMA** | built-in `db.schema.*` + pure-Cypher scan | populated | true |
| **CYPHER** | pure-Cypher scan only | `[]` (empty) | true |

The motivating incident: on a real Neo4j 5.12 Enterprise instance with only **APOC Extended** installed (which does *not* register `apoc.meta.*`), the inspector silently fell back to pure-Cypher and reported `observed_types = []` for every property — even though the built-in `db.schema.nodeTypeProperties()` was available the whole time. The result was **non-reproducible profiling output** depending on which APOC jar an operator dropped into `plugins/`.

## What Changed

1. **Three-way detection** (ADR-033 § 3):
   - Probe `apoc.meta` first → `APOC` (existing behaviour, no change for APOC-Core users — regression guard).
   - Else probe `db.schema.nodeTypeProperties` → `SCHEMA` (new).
   - Else → `CYPHER` (existing fallback).

2. **SCHEMA strategy** (ADR-033 § 2):
   - **Counts** come from the pure-Cypher two-pass scan (true completeness, same as pure-Cypher).
   - **Types** come from `db.schema.*` procedures.
   - Merge per `(label, property_name)` or `(rel_type, property_name)`.
   - Properties present in the scan but absent from `db.schema.*` keep `observed_types = []`.

3. **Constructor selector** (ADR-033 § 4):
   - New parameter: `strategy: Neo4jInspectionStrategy | None = None` (explicit selection).
   - Existing `use_apoc: bool | None` is deprecated, kept for backward compatibility, emits `DeprecationWarning`.
   - `use_apoc=True` → `APOC`, `False` → `CYPHER`, `None` → auto-detect.

4. **Three catalogue factories** (ADR-033 § 6):
   - `build_apoc_catalogue()`, `build_cypher_catalogue()`, **`build_schema_catalogue()`** (new).
   - Each registers the shared neutral queries (cardinality, endpoint-labels, constraints) plus the strategy-specific property queries.
   - E41 (per-pair cardinality) must register its partitioned-query in all three.

---

## Backward Compatibility

- APOC-Core users: **no observable change**. Auto-detect still picks APOC first; output identical.
- Pure-Cypher-only deployments: **no observable change**. Auto-detect picks CYPHER as last resort.
- Legacy code using `use_apoc=False`: still works, but emits a deprecation warning. Recommended: migrate to `strategy=Neo4jInspectionStrategy.CYPHER`.

---

## Usage Examples

```python
from orthograph.backends.neo4j.inspector import Neo4jInspector, Neo4jInspectionStrategy

# Auto-detect (APOC → SCHEMA → CYPHER in order)
profile = Neo4jInspector().inspect(driver)

# Force SCHEMA (e.g., APOC not available but db.schema.* is)
profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.SCHEMA).inspect(driver)

# Force pure-Cypher (no types, but still true counts)
profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(driver)

# Deprecated — still works but warns
profile = Neo4jInspector(use_apoc=False).inspect(driver)
```

---

## Architecture Notes

- **Backend-scoped**: The strategy concept and detection logic live entirely in `backends/neo4j/`. The vendor-free `graph_profile/` layer is untouched (ADR-009 D1, ADR-012 § 4).
- **No new injection surface**: `db.schema.*` queries are bulk `CALL` statements with no interpolated identifiers (ADR-008 compliance).
- **No regression on counts**: APOC-Extended users (the original failure) now get types via `db.schema.*` **without sacrificing true completeness counts** (which the mandatory-heuristic would have).

---

## Known Caveats

1. `db.schema.*` exists since Neo4j 4.x but type information completeness varies by version. E44.0 confirmed the exact column shape on 5.12.0.
2. The pure-Cypher scan is always run in SCHEMA mode (for true counts); `db.schema.*` is a *supplementary* type lookup, not a replacement. Properties seen by the scan but absent from `db.schema.*` keep `observed_types = []`.
3. Relationship counts are derived from the property scan's `totalObservations`, same as before. Rel types with no properties report `count = 0`.

---

## See Also

- **ADR-033**: Decision and rationale (backend-scoped strategy, combined type+count merge, deprecation non-breaking, E41 coordination).
- **ADR-009**: Inspector contract (the query-set selection seam this expands).
- **ADR-012**: Optional-dependency policy (APOC is optional; this strategy reduces the library's dependence).
- **E44**: Epic with per-task implementation notes and guardrails.
- **E41**: Per-pair cardinality (shares the `build_*_catalogue()` factory surface — must register new queries in all three).
