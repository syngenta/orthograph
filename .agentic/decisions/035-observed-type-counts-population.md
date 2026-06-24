# ADR-035: Populating `observed_type_counts` — Bounded Value Scan, Two Aggregations, Prevalence-Aware Type Conformance

**Status:** Accepted — 2026-06-23
**Category:** core
**Epic:** E46 (populate `PropertyProfile.observed_type_counts`) — task E46.0
**Discharges:** ADR-015 §162-166 ("type match" rule, the B1 TODO)
**Relates:** ADR-034 (the frozen field shape, `value_distribution`, `BoundedDistribution`,
the comparison matrix), ADR-033 (Neo4j APOC/SCHEMA/CYPHER strategy — drives availability),
ADR-009 (inspector parity, honest degradation), ADR-008 (identifier safety)
**Frozen by ADR-034 (not re-litigated here):** the `observed_type_counts: dict[str, int]`
field shape, its `{}` default, and its serialisation.

---

## Context

`PropertyProfile.observed_type_counts` (`graph_profile/models.py:121`) is the addressed
place ADR-015 §162-166 designates for the observed half of the **type-match rule**, but it
is never populated. E46 populates it. E46.0 (this ADR) resolves four open questions before
any production code is written.

A premise in the epic proved false on inspection and reshapes the work:

- `value_distribution` and the `value_counts_top_n` opt-in exist **only** in the NetworkX
  reference inspector (`backends/networkx/inspector.py:51,189,196`).
- The **Neo4j** inspector populates **neither** `value_distribution` nor
  `observed_type_counts` (both TODO sites, `inspector.py:285,334`); **no value-scan query**
  is registered in any of the three catalogues (`queries.py` — APOC / CYPHER / SCHEMA read
  property *metadata* only, never values).
- The **Memgraph** inspector has no value scan either (`present=int(mandatory), total=1`
  heuristic; `value_distribution=None`).

Therefore, on the database backends, there is **no existing value scan to "ride"**. E46
**introduces the first value-touching scan** on Neo4j/Memgraph; the type-count aggregation
and the value histogram are both products of that one new scan. This makes the cost
question (Q1) load-bearing, exactly as the epic's "bounded" rubric demands.

---

## Decision

### 1. Opt-in: one knob — `value_counts_top_n` gates the whole value scan (Q1)

`value_counts_top_n: int | None` (today only on `NetworkxInspector`) is extended to
`Neo4jInspector` and `MemgraphInspector` with identical semantics. When set, the inspector
runs **one opt-in value-scan transaction** per property that yields *both* the exact
type-count aggregation and the bounded value histogram. When `None`/`0`, the inspector runs
**no value-touching scan at all** ⇒ `observed_type_counts == {}` and
`value_distribution is None`.

No second sampling/bound knob is introduced (epic Out-of-Scope). The scan is the cost; the
two aggregations are cheap once the scan is committed to, so they share one opt-in and one
bound.

### 2. One logical scan, two aggregations, one transaction (Q2)

The two outputs are computed by two aggregating queries that run **inside a single read
transaction (snapshot)** so they observe the same state:

- **Type counts** — `GROUP BY <runtime-type-of-value>` with `count(*)` per group. Returns a
  handful of rows (one per distinct *type*); it **never enumerates distinct values** and so
  is bounded and exact even on a UID / free-text column.
- **Value histogram** — `GROUP BY value … LIMIT top_n`, with the remainder folded into
  `other_count` (the existing `BoundedDistribution` truncation contract, ADR-034 §3).

"Single scan, two aggregations" is the **logical** invariant (both reflect the same column
state); physically they are two cheap aggregating queries, neither materialising distinct
values to the client.

#### Reconciliation invariant (E46.0 step 2)

> `observed_type_counts == {}`
> **OR** `sum(observed_type_counts.values()) == value_distribution.count == present_count`

Every non-null value has exactly one runtime type, so the per-type totals partition the same
population as `value_distribution.count`, which equals `present_count` (non-null
occurrences, ADR-034 §5). This holds **regardless of histogram truncation**, because type
counts are exact and the histogram already accounts for its own truncation via
`count`/`other_count`. The type side and value side reconcile at the **total**, never
per-bucket (they partition the same population two different ways).

The invariant is **hard exact-equality** wherever counts are present. It is enforced on live
backends by running the three feeding reads (`present_count`, type counts, histogram)
**inside one read transaction**, and is asserted exactly in tests against the NetworkX
reference (a single deterministic snapshot). The `observed_type_counts == {}` clause is the
**honest escape**: a backend/strategy that cannot supply type counts makes no numeric claim
(sum 0 vs `present_count > 0` is *not* a violation). When type counts *are* populated,
`value_distribution` is necessarily populated too (they share the snapshot).

### 3. Type-name vocabulary: reuse each backend's `observed_types` (Q3)

`observed_type_counts` keys reuse **exactly** the per-backend type-name vocabulary already
used for `observed_types`:

- Neo4j via `coerce_types` → `'String'`, `'Long'`, `'Double'`, …
- NetworkX via `type(value).__name__` → `'str'`, `'int'`, `'float'`, …

`comparison/engine._DB_TYPE_MAP` already carries **both** vocabularies, so
`db_type_to_python` (`engine.py:51`) applies **unchanged** and `PropertyTypeMismatchRule`'s
mapping path is untouched. Consistency check: `set(observed_type_counts) ⊆ set(observed_types)`.
Parity is judged on **semantics**, not string-identity across backends (ADR-009 — "each
backend honest per its strategy").

### 4. Truncation: type counts exact, only the histogram truncates (Q4)

Distinct-*type* cardinality is tiny and bounded by nature even when distinct-*value*
cardinality is huge. The `GROUP BY <type>` aggregation is the mechanism that makes type
counts **exact and cheap** simultaneously. Only the **value histogram** carries truncation
(`sample_complete=False`, `limit`, `other_count`). Type counts are never truncated.

### 5. Strategy / backend availability — `{}` when no runtime-type function

Exact type counts require a runtime-type function:

- **Neo4j APOC strategy** — `apoc.meta.cypher.type(v)`. Type counts populated.
- **Neo4j SCHEMA strategy** — may use APOC's type function when APOC is present; else `{}`.
- **Neo4j pure-CYPHER strategy** — no portable runtime-type function ⇒
  `observed_type_counts == {}`. The histogram may still populate (it needs only the value),
  which the invariant's `{}` escape permits.

  > **Amendment (E46.2 → E46.6).** E46.2 found the histogram's value key must be
  > **list-safe** (`ACTED_IN.roles` is a `StringArray`; plain `toString(list)` throws), and
  > chose the APOC-only `apoc.convert.toJson(v)`. That made the *whole* value scan
  > APOC-gated, so E46.2 shipped pure-CYPHER / SCHEMA-without-APOC with **no value scan at
  > all** (`observed_type_counts == {}` **and** `value_distribution is None`). **E46.6
  > restores a scalar-only histogram fallback** on these strategies: the pure-Cypher
  > `CypherNode/RelValueHistogramQuery` groups on the built-in `toStringOrNull(v)`, which
  > returns `null` for list / map / non-stringifiable values (dropped by the `WHERE`) so
  > scalar-typed properties get a histogram while list properties are skipped (`None`),
  > never crashing. **Type counts remain `{}`** on these strategies (still no portable
  > runtime-type function). The fallback histogram's total reconciles only over the
  > **scalar** population it scanned; dropped non-scalars fold into `other_count` against the
  > pure-Cypher `present_count` (partial-population semantics, §4).
- **Memgraph** — its `valueType`/equivalent if available; else `{}`.
- **NetworkX (reference)** — `type(value).__name__` per value; the ground truth.

Identifiers (`label` / `rel_type`) are spliced via `<<placeholder>>` (ADR-008); values are
never interpolated. A property the scan cannot type yields `{}` — **never invent counts**.

#### Known cross-backend histogram deviation (E46.3, recorded per ADR-009)

`observed_type_counts` is exact and parity-correct on every backend (the epic's primary
deliverable). The **value histogram** key, however, differs by backend and is *not*
identical across them — parity is judged on semantics, not byte-identical output:

- **Neo4j (APOC)** keys the histogram on `apoc.convert.toJson(v)`, which keeps list/map
  values *in* the histogram.
- **Memgraph** keys on `toStringOrNull(v)` (no portable list-safe key exists), which drops
  list/map values; the dropped non-scalar values fold into `other_count`.

Consequence: a property mixing scalars and lists is reported `sample_complete=False`
(with the lists in `other_count`) on Memgraph but `sample_complete=True` on Neo4j for the
same data. This is honest degradation (Memgraph cannot stringify a list safely), not a
regression, and does not affect `observed_type_counts` reconciliation — the type-count
total remains the authoritative `present_count` on both backends.

#### True completeness denominator (E46.3) — never derive a total from the scan

The value scan supplies `present_count` (non-null occurrences) but **not** the entity
total. `PropertyProfile.total_count` (the `completeness` denominator) and
`NodeTypeProfile.count` / `RelationshipTypeProfile.count` therefore come from a dedicated
property-independent `count()` query (`MATCH (n:Label) RETURN count(n)` / edge equivalent)
on **both** Neo4j (E46.2) and Memgraph (E46.3). Deriving `total_count` from `present_count`
(e.g. `max(1, present_count)`) is forbidden: it fabricates `completeness == 1.0` for every
present property and silently suppresses `PROPERTY_INCOMPLETE` for required-but-unconstrained
properties — exactly the "never invent counts" violation this ADR prohibits.

### 6. Prevalence modulates severity, never the code (E46.4 direction)

When `observed_type_counts` is populated, `PropertyTypeMismatchRule` computes the off-type
**share** and may modulate **severity** (negligible share → WARNING; systematic share →
ERROR) and include the share in the message. It **never** changes the frozen issue code
`PROPERTY_TYPE_MISMATCH` (that needs its own ADR). When `observed_type_counts == {}`, the
rule is **byte-for-byte identical to today** (ERROR per observed off-type) — a hard
regression guard, since the field is additive. The numeric threshold is an E46.4
implementation detail this ADR does not pin.

---

## Consequences

- E46 **introduces** the bounded value-scan transaction on Neo4j and Memgraph (it is not an
  extension of an existing DB scan — that scan did not exist). `value_counts_top_n` is added
  to both DB inspectors.
- `value_distribution` becomes populated on the DB backends as a by-product (previously
  `None` there); this is in-scope for E46, contrary to the epic's original "only populates"
  wording.
- The reconciliation invariant requires the per-property reads to share one read transaction
  on live backends.
- Honest degradation preserved: no runtime-type function ⇒ `{}`, never a fabricated count.
- The comparison side is untouched structurally: `db_type_to_python` and the
  `PROPERTY_TYPE_MISMATCH` code are unchanged; only severity gains prevalence sensitivity.

---

## Rejected alternatives

- **Derive type counts from the value histogram.** Rejected: on a truncated histogram
  (UID/free-text column) the derived counts would be under-counted and wrong — fails the Q4
  exactness goal.
- **One combined Cypher statement for both aggregations.** Rejected: harder to keep parity
  across the four backend surfaces (APOC / CYPHER / SCHEMA / Memgraph); two clear aggregations
  in one transaction are simpler and equally consistent.
- **Type counts always-on (or a second dedicated flag).** Rejected: the epic forbids a second
  sampling/bound knob, and "always-on" still runs a per-property `GROUP BY` scan — not free on
  a cold large database.
- **Canonicalise all type names to one vocabulary in `graph_profile/`.** Rejected: leaks a
  canonical-type concept into the vendor-free layer; `_DB_TYPE_MAP` is already bilingual, so
  `db_type_to_python` needs no canonicalisation.
- **Unconditional exact-equality with no `{}` escape.** Rejected: contradicts the mandated
  honest `{}` (a backend with no type source would have `sum == 0` while `present_count > 0`).
- **Force type counts on every strategy (custom type detection in pure-Cypher).** Rejected:
  breaks "never invent" and the bounded-honesty rubric.

---

## Cross-references

- ADR-015 §162-166: the type-match rule; this ADR discharges its B1 TODO.
- ADR-034 §3/§4/§5/§8: `BoundedDistribution`, the frozen field shape, non-null `present_count`,
  the comparison matrix.
- ADR-033: Neo4j APOC/SCHEMA/CYPHER strategy — drives runtime-type-function availability.
- ADR-009: inspector parity / honest degradation (semantics, not value-identity).
- `PropertyProfile`: `src/orthograph/graph_profile/models.py:93`
- `PropertyTypeMismatchRule`: `src/orthograph/comparison/rules.py:322`; `db_type_to_python` /
  `_DB_TYPE_MAP`: `src/orthograph/comparison/engine.py:30,51`
- Neo4j catalogues / TODO sites: `src/orthograph/backends/neo4j/queries.py`,
  `src/orthograph/backends/neo4j/inspector.py:285,334`
- NetworkX reference value scan: `src/orthograph/backends/networkx/inspector.py:165-234`
- E46 epic: `.agentic/planning/active_epics/E46_observed_type_counts_population.md`
