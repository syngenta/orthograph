# Epic E22: E2E Test Coverage Audit & Shared-Contract Test Layer

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness
> **Origin:** E17 STEP 5 session 2026-06-10 (first live-DB e2e tests added for the Neo4j
> inspector; audit of the rest of the package revealed the gap).
> **Blocked by:** E21 (the activation mechanism decision should precede building a large live-DB
> suite; at minimum, the shared-contract layer — which requires no live DB — can proceed
> independently of E21).
> **Relates to:** PRD User Stories 4–6 (live Neo4j, Memgraph, and NetworkX inspection with the
> same interface), PRD Constraint 2 (models are the single source of truth), E17 (inspector query
> realignment), E8 (GQLAlchemy query catalogue), E21 (e2e test activation & configuration).
>
> **SCOPE NOTE:** This epic is a **requirements record only** — no tasks are defined yet. It
> captures the current e2e gap, identifies the extensions that need live-DB coverage, and
> articulates the core design requirement: that the same test assertions should be runnable against
> both a fake/in-process backend and a real database, so that the live-DB tests do not duplicate
> the assertion logic of the unit tests but instead exercise the same contract via a different
> execution path.

---

## Context

The current test suite has three layers:

1. **Unit / mock tests** — every source module has one. Driver interactions are mocked;
   `GraphProfile` data is constructed directly. These tests run in CI with no external
   dependencies.

2. **In-process integration tests** (`tests/test_integration.py`) — exercise the full public API
   against in-memory data (NetworkX graphs, YAML files, Python-only workflows). No network.

3. **Live-DB e2e tests** — currently exist only for the inspector:
   - `tests/extensions/neo4j/test_inspector_e2e.py` (21 tests, added in E17)
   - `tests/extensions/memgraph/test_inspector_e2e.py` (15 tests, scaffold added in E17)

Everything outside the inspector layer — `CypherExecutor`, `GqlAlchemyClient`,
`ValidatedQueryBuilder`, `validate_database()` — is covered only by mock-based tests. No live-DB
path is exercised end-to-end.

---

## The Gap

### Extensions with live-DB surface and no e2e coverage

| Extension | Live-DB operations | E2E tests today |
|-----------|--------------------|-----------------|
| `neo4j/inspector.py` | `inspect()`, `validate_database()` | ✅ 21 tests (E17) |
| `memgraph/inspector.py` | `inspect()`, `validate_database()` | ⚠️ scaffold only (E17) |
| `cypher/query_executor.py` | `CypherExecutor.read()`, `.write()` — the typed catalogue's only I/O seam | ❌ none |
| `gqlalchemy/client.py` | `save_node()`, `save_relationship()`, `validate_database()` | ❌ none |
| `gqlalchemy/query_builder.py` | `ValidatedQueryBuilder.execute_validated()` against a real DB | ❌ none |

`CypherExecutor` is architecturally the most important gap: it is the single path through which
all typed `CypherReadQuery` / `CypherWriteQuery` objects reach a live database. Today every
executor test uses a mock session factory. No test proves that `CypherExecutor.read(query,
params)` returns the expected materialised objects against a real Neo4j or Memgraph driver.

The GQLAlchemy client and query builder gaps are less acute (GQLAlchemy is a third-party ORM and
already test-heavy itself) but are still real: `save_node()` → DB → `validate_database()` has
never been exercised against a real instance.

---

## The Core Design Requirement: A Shared-Contract Test Layer

The most important requirement is **not** to add more live-DB tests in isolation. The existing
split — unit tests with mocks, e2e tests with real connections — duplicates the assertion logic
(the same `assert cs.min_degree == 1` appears in both the mock inspector test and the e2e test).
This duplication means that when the profile shape changes, two test files need updating instead
of one.

**The requirement is to design a shared-contract layer: a set of parameterised assertions that
run against any conforming backend, whether that backend is:**

- a **`NetworkxInspector` over a pre-populated `nx.MultiDiGraph`** (no dependencies, runs in CI),
- a **`Neo4jInspector` against a real Neo4j instance** (requires `--neo4j`),
- a **`MemgraphInspector` against a real Memgraph instance** (requires `--memgraph`).

NetworkX is the natural **in-process reference implementation**: it already populates every
`GraphProfile` field (counts, property profiles, cardinality, endpoint labels) without any
network I/O. A test that passes against NetworkX and then the same parametric test that passes
against a live Neo4j database exercises the same `GraphProfile` contract via both paths, without
any assertion duplication.

This has a direct implication for how the shared-contract tests are structured: the seeded
dataset must be expressible once and loaded into all three backends, so the assertions compare the
same logical graph state across implementations.

### What "shared contract" means in practice

- A **single seed function** that inserts the same logical dataset — today this is `_seed()` in
  the e2e files and an equivalent in-process `nx.MultiDiGraph` construction in
  `tests/extensions/networkx/test_inspector.py`. These should be unified.
- A **single parameterised assertion set** (e.g. a base class, a pytest parametrize, or a
  shared fixture + assertion helper) that expresses what a correct `GraphProfile` looks like for
  that dataset, independent of which inspector produced it.
- The parametrize axes are the **backend factories**: in-process NetworkX (always runs),
  Neo4j (requires `--neo4j`), Memgraph (requires `--memgraph`).

---

## Relationship to E21

E22 **depends on E21** for the live-DB tests (the activation mechanism affects how multi-backend
parametrization is wired), but:

- The **audit** (this document) and the **shared-contract design** (deciding how parametrization
  works and where the shared assertion helpers live) can proceed in parallel with or before E21.
- The **NetworkX path** of the shared-contract tests requires no live DB and no activation
  mechanism — it can be built and run in CI immediately.
- The **live-DB paths** (Neo4j, Memgraph) must wait for E21 to decide the activation mechanism
  before being wired into the parametrization.

---

## Extensions to Cover (when E21 decides the activation mechanism)

### Inspector shared-contract tests (NetworkX / Neo4j / Memgraph)

Three backends, one assertion set. Assertions cover:
- `node_labels`, `relationship_types` correctly detected
- `NodeTypeProfile.count` (parity-gap aware: NetworkX and Neo4j give real counts; Memgraph
  always returns 0 — the shared test layer must parametrize or document this asymmetry)
- Property profiles: names, mandatory vs optional, `present_count` / `total_count`
- `RelationshipTypeProfile.count`
- `source_labels` / `target_labels` populated
- `cardinality_stats`: min/max/avg/sample_size, and the regression assertion (not computed
  against a target-only label)
- `validate_profile()` and `validate_database()` pass for a matching model; fail with the correct
  error codes for specific mismatches

### `CypherExecutor` e2e (Neo4j + Memgraph)

End-to-end proof that a typed `CypherReadQuery` / `CypherWriteQuery` class reaches a real
database through `CypherExecutor`:
- `executor.read(query, params)` returns correctly materialised `Output` instances for a seeded
  dataset
- `executor.write(query, params)` commits a change that is visible on the next `read()`
- The typed parameter / identifier contract holds end-to-end (a bad param is caught before the
  driver is touched; a bad identifier is caught in `build()`)

### `GqlAlchemyClient` e2e (Memgraph, possibly Neo4j)

- `save_node()` persists a valid node; a subsequent read returns it
- `save_node()` raises for an invalid node (wrong type, missing required property)
- `save_relationship()` persists a valid relationship between two existing nodes
- `validate_database()` returns valid for a seeded DB matching the model; returns errors for a
  known mismatch

---

## Parity Gaps — Explicit Documentation Required

E17 established the pattern: gaps between backends are **documented explicitly in the test
record, not silently skipped**. The shared-contract layer must carry this through:

- Memgraph `NodeTypeProfile.count` = 0 (schema procedures yield no counts) — the shared
  test that asserts a real count for NetworkX/Neo4j must have a corresponding Memgraph test
  that asserts the documented zero, not a test that is just absent.
- `PropertyProfile.present_count` / `.total_count` are observation counts on Neo4j and NetworkX,
  but a mandatory heuristic on Memgraph — this asymmetry should be documented in the shared
  assertion layer, not hidden.

---

## Out of Scope (this epic, until scoped)

- Implementing any of the candidate solutions from E21 (activation mechanism is E21's domain).
- Adding new validation rules or new `GraphProfile` fields (separate concerns).
- GQLAlchemy query-catalogue (E8) e2e tests — those belong in E8, which is already planned.
- Performance or load testing.
- Any new source-code changes to the inspectors, executor, or client — this epic concerns the
  **test layer only**.
