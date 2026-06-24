# ADR-036: Correct the APOC No-Scan `present_count` / `total_count` Undercount — Property-Independent Count Queries

**Status:** Accepted — 2026-06-24
**Category:** core
**Epic:** E46 (populate `PropertyProfile.observed_type_counts`) — discharges the open follow-up recorded under "Discovered during E46.2 — APOC relationship-property undercount"
**Relates:** ADR-035 (the value scan; §5 "True completeness denominator" — count queries are the authoritative total), ADR-033 (Neo4j APOC/SCHEMA/CYPHER strategy — the undercount is APOC-strategy-specific), ADR-009 (inspector parity, honest counts), ADR-008 (identifier safety)
**Builds on (already shipped, not re-litigated):** `NodeCountQuery` / `RelCountQuery` (the property-independent instance counts, ADR-035 §5 / E46.2); the scan-path correction in `_fetch_node_value_scan` / `_fetch_rel_value_scan` (`present_count = sum(observed_type_counts.values())`).

---

## Context

E46.2 surfaced (validating against a live filmography DB) that
`apoc.meta.relTypeProperties({sample: -1})` reports `propertyObservations = 100` for
`ACTED_IN.roles` while a real `MATCH ()-[r:ACTED_IN]->() WHERE r.roles IS NOT NULL RETURN
count(r)` returns **172**. APOC's relationship-property observation count is an
**undercount**. `propertyObservations` feeds `PropertyProfile.present_count`, and
`totalObservations` feeds `total_count` (the `completeness` denominator,
`models.py:151` — `completeness = present_count / total_count`), so on the APOC strategy
both halves of a relationship property's completeness can be wrong.

E46.2 corrected this **only on the value-scan path**: when `value_counts_top_n` is set, the
inspector derives `present_count` from the real scan total
(`sum(observed_type_counts.values())`), so the reconciliation invariant holds by
construction. But:

- `value_counts_top_n` defaults to `None` — the **default** inspection (`Neo4jInspector().inspect(driver)`) takes the **no-scan path**.
- On the no-scan path (and the no-APOC path) `present_count` falls back to APOC's
  `propertyObservations` and `total_count` to APOC's `totalObservations`
  (`inspector.py:531,603` — `fallback_present_count`; profile builders read
  `row.total_observations`). **The undercount persists.**

### Why this is APOC-strategy-specific

The pure-Cypher property scan already computes truthful counts:
`CypherRelPropertiesQuery` / `CypherNodePropertiesQuery` (`queries.py:435,463`) do a real
`MATCH … UNWIND keys(e) … count(*)` so `present`/`total` are exact on the **CYPHER** and
**SCHEMA** strategies. Only the **APOC** strategy reads `apoc.meta.*` metadata counts, which
sample and can undercount. The fix therefore targets the APOC strategy's count source, not a
universal new mechanism.

### The observed asymmetry (node vs relationship)

The original finding noted the node-side `apoc.meta.nodeTypeProperties` did **not** exhibit
the undercount in the same DB. We nonetheless correct **both** node and relationship counts:
APOC sampling is a sampling mechanism on both surfaces, the node-side absence of the symptom
in one DB is not a guarantee, and a single symmetric mechanism is cheaper to reason about
and parity-clean (ADR-009) than a relationship-only special case that invites a future
repeat finding on the node side.

---

## Decision

### 1. On the APOC strategy, source both counts from property-independent `count()` queries

The instance total (`NodeTypeProfile.count` / `RelationshipTypeProfile.count`) already comes
from the dedicated `NodeCountQuery` / `RelCountQuery` (ADR-035 §5, E46.2) — those are truthful
and unaffected by the undercount. This ADR extends the same principle to **per-property**
counts on the APOC strategy:

- **Numerator (`present_count`)** — a new bounded, property-independent query per property:
  `MATCH (n:`<<label>>`) WHERE n.`<<property_name>>` IS NOT NULL RETURN count(n)` (node) and
  the `MATCH ()-[r:`<<rel_type>>`]->() WHERE r.`<<property_name>>` IS NOT NULL RETURN count(r)`
  edge equivalent. This returns the **true** non-null occurrence count, superseding APOC's
  `propertyObservations`.
- **Denominator (`total_count`)** — reuse the already-fetched instance count from
  `NodeCountQuery` / `RelCountQuery` (the same `count()` already driving `NodeTypeProfile.count`
  / `RelationshipTypeProfile.count`), superseding APOC's `totalObservations`.

This makes `completeness = true_present / true_total` exact on the APOC strategy, matching
what the CYPHER/SCHEMA strategies already report from their pure-Cypher scan.

### 2. Always-on for the APOC strategy, independent of `value_counts_top_n`

The correction runs on **every** APOC inspection, not gated by `value_counts_top_n`. The
value scan (type counts + histogram) remains opt-in; the **count correction is not part of
the value scan** — it is a metadata-correctness fix for a number the inspector already
claims to report. A count-only `count()` with an `IS NOT NULL` predicate is bounded (one
scalar row, server-side aggregation, no value materialised to the client), so it is cheap
enough to be unconditional, in the same spirit as the always-on `NodeCountQuery` /
`RelCountQuery`.

### 3. Scan path is unchanged and remains authoritative when it runs

When the value scan **does** run (`value_counts_top_n` set, APOC available), `present_count`
continues to come from `sum(observed_type_counts.values())` — the scan already touched every
non-null value, so its total is authoritative and identical to the new count query's result
(both are a real `IS NOT NULL` count over the same snapshot). The new count query is used on
the APOC strategy **only when the scan did not supply the count** (no `value_counts_top_n`).
No double-counting, no second scan when one already ran.

### 4. CYPHER / SCHEMA strategies are untouched

Their pure-Cypher property scan already yields truthful `present`/`total`; this ADR adds no
query to their count path. (The new present-count query is still **registered** in all three
catalogues for catalogue parity and introspection, mirroring how `NodeCountQuery` /
`RelCountQuery` appear in every catalogue, but the inspector only *uses* it on the APOC
strategy's no-scan path.)

### 5. Honest counts, never invented

The correction only ever **replaces an undercounted number with a directly-measured one**.
It never fabricates presence: a property genuinely present on zero entities counts zero. No
`max(1, …)` flooring (forbidden by ADR-035 §5). Identifiers are spliced via `<<placeholder>>`
(ADR-008); the property key is an identifier (label-grammar), never an interpolated value.

---

## Consequences

- The **default** Neo4j inspection (`value_counts_top_n` unset) now reports truthful
  relationship- and node-property `present_count` / `total_count` / `completeness` on the
  APOC strategy. The 100-vs-172 undercount is closed on the default path, not just the
  opt-in scan path.
- One extra bounded `count()` query per property on the APOC no-scan path. On a DB with many
  types × properties this is N additional scalar-aggregation queries per inspection; each is
  cheap (indexed `count` with a null predicate, no value materialisation). Accepted as the
  cost of correctness, consistent with the already-accepted always-on instance counts.
- `total_count` on the APOC strategy now equals the instance count from
  `NodeCountQuery` / `RelCountQuery` (the same number `NodeTypeProfile.count` /
  `RelationshipTypeProfile.count` already report), so a property's `missing_count` and
  `completeness` are internally consistent with the entity count.
- The reconciliation invariant (ADR-035 §2) is unaffected: where the scan runs it still
  drives `present_count`; the new query is the no-scan substitute, producing the same total.
- Parity (ADR-009): all three strategies now report semantically equal `present_count` /
  `total_count` for the same data (APOC via count queries; CYPHER/SCHEMA via the pure-Cypher
  scan).

---

## Rejected alternatives

- **Relationship-only correction.** Rejected: matches the one observed symptom but leaves
  the node-side APOC count on a sampling mechanism that can undercount; a symmetric fix is
  simpler and parity-clean (ADR-009).
- **Correct only `present_count`, leave `total_count` on APOC `totalObservations`.**
  Rejected: `completeness = present / total` would mix a measured numerator with a sampled
  denominator, producing an inconsistent ratio (and a `missing_count` that disagrees with the
  instance count). The truthful total already exists for free (`NodeCountQuery` /
  `RelCountQuery`).
- **Gate the correction on `value_counts_top_n` (only fix when the scan runs).** Rejected:
  that is the *current* state — it leaves the default path wrong. The undercount is a
  metadata-correctness bug, not a value-scan feature.
- **Switch the APOC strategy entirely to the pure-Cypher property scan.** Rejected: APOC's
  metadata read also supplies `observed_types` (real type names) which the pure-Cypher scan
  cannot; the APOC strategy exists precisely to get those. We keep APOC for types and only
  replace its sampled counts.
- **Raise APOC's `sample` parameter (e.g. drop `{sample: -1}` tuning).** Rejected: the call
  already passes `{sample: -1}` (no sampling) and still undercounts relationship
  observations — the undercount is in APOC's relationship-property accounting, not a tunable
  sample size.
- **Document it as an APOC-strategy limitation and do nothing.** Rejected: the inspector
  reports `present_count` / `completeness` as facts; a known wrong fact when the correct one
  is cheaply measurable is not honest degradation, it is a defect.

---

## Cross-references

- Open follow-up discharged: `.agentic/planning/active_epics/E46_observed_type_counts_population.md`
  ("Discovered during E46.2 — APOC relationship-property undercount").
- ADR-035 §5 (count queries are the authoritative total; never derive a total from the scan),
  §2 (reconciliation invariant).
- ADR-033: the APOC/SCHEMA/CYPHER strategy — why only APOC is affected.
- `NodeCountQuery` / `RelCountQuery`: `src/orthograph/backends/neo4j/queries.py:394,412`.
- APOC count source: `ApocNodePropertiesQuery` / `ApocRelPropertiesQuery`
  (`queries.py:308,345`); the no-scan fallback: `src/orthograph/backends/neo4j/inspector.py:531,603`.
- `PropertyProfile.completeness`: `src/orthograph/graph_profile/models.py:151`.
