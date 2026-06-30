# Advanced: Neo4j Inspection Strategies

> **Expansion planned for a future release.**
> This page is a scope stub. Full detail on each strategy's query set,
> detection mechanics, trade-off matrix, and operator guidance will be
> written once the inspection layer is fully stabilised.

---

## Scope

This page covers the **three Neo4j inspection strategies** — APOC, SCHEMA,
and CYPHER — and the auto-detection logic that selects among them at runtime.

It is the deep-dive companion to [How profiling works](profiling.md), which
describes the shared profiling algorithm. This page focuses on what is
Neo4j-specific: why three strategies exist, what each one provides and
gives up, and how the inspector chooses between them.

---

## Topics planned for this page

- **Why three strategies exist** — the inspection capabilities available on
  a real Neo4j instance depend on which plugins are installed. APOC Core
  (`apoc.meta.*`), the `db.schema.*` built-ins (available since Neo4j 4.x
  with no plugin), and plain aggregate Cypher queries each provide a different
  combination of property-type information and true observation counts. No
  single strategy strictly dominates on all axes.

- **The trade-off matrix** — a table comparing what each strategy provides
  for `observed_types` (present or absent) and completeness counts (true
  counts from a full scan vs. a schema-metadata heuristic).

- **APOC strategy** — uses `apoc.meta.nodeTypeProperties()` and
  `apoc.meta.relTypeProperties()` for property types and observation counts.
  Available when APOC Core is installed. Provides both true counts and type
  information.

- **SCHEMA strategy** — combines `db.schema.nodeTypeProperties()` /
  `db.schema.relTypeProperties()` (built-in, no plugin) for type information
  with a pure-Cypher two-pass scan for true observation counts. This is the
  strategy that closes the type-loss gap when APOC is absent or only APOC
  Extended (not Core) is installed.

- **CYPHER strategy** — plain aggregate Cypher queries only. Provides true
  counts but no property-type information (`observed_types = []`). The last
  resort when neither APOC Core nor `db.schema.*` are available.

- **Auto-detection precedence** — the probe sequence: APOC first (no change
  for existing APOC Core users), then SCHEMA (if `db.schema.*` is available),
  then CYPHER. The ordering is a regression guard: promoting SCHEMA above APOC
  would silently degrade count fidelity for users who have APOC Core.

- **The `strategy` selector and `use_apoc` deprecation** — how to pin a
  strategy explicitly via `Neo4jInspector(strategy=Neo4jInspectionStrategy.SCHEMA)`
  instead of relying on auto-detection, and why the boolean `use_apoc=` parameter
  is deprecated (a boolean cannot express the three-way choice).

- **APOC observation-count correction** — even on the APOC path,
  `apoc.meta.relTypeProperties` aggregates by bare relationship label and
  underestimates `present_count` for per-shape profiles. Dedicated `count()`
  queries correct this for both nodes and relationships on the APOC path.

- **Catalogue parity** — all three strategies share the same set of neutral
  queries (cardinality, endpoint-label discovery, constraint inspection); only
  the property-metadata queries differ between catalogues.

---

## Implementation pointers

| Concern | Module |
|---|---|
| Inspector + strategy detection | `src/orthograph/backends/neo4j/inspector.py` (`_detect_strategy`, `Neo4jInspectionStrategy`) |
| APOC catalogue | `src/orthograph/backends/neo4j/queries.py` (`build_apoc_catalogue`) |
| SCHEMA catalogue | `src/orthograph/backends/neo4j/queries.py` (`build_schema_catalogue`) |
| CYPHER catalogue | `src/orthograph/backends/neo4j/queries.py` (`build_cypher_catalogue`) |
| `observed_types` on the profile | `src/orthograph/graph_profile/models.py` (`PropertyProfile.observed_types`) |

---

*See [How profiling works](profiling.md) for the vendor-neutral profiling
algorithm, and [Relationship identity and the endpoint signature](relationship-identity.md)
for why per-shape scans require endpoint-filtered pattern queries rather than
bare-label aggregates.*
