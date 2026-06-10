# Epic E21: Technical Debt — E2E Test Activation & Configuration

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness
> **Origin:** E17 STEP 5 session 2026-06-10 (live Neo4j inspector e2e tests added; surfaced
> the limitations of the current marker + CLI-flag activation mechanism).
> **Blocked by:** None — can start when capacity allows. Cross-cutting test-infrastructure
> concern; coordinate with any epic adding new live-database test suites.
> **Relates to:** PRD User Story 4/5 ("inspect a live Neo4j / Memgraph database"),
> PRD Constraint 13 (Orthograph never owns a connection — drivers are passed in),
> the `tests/extensions/{neo4j,memgraph}/test_inspector_e2e.py` suites and the root
> `conftest.py` added in E17.
>
> **SCOPE NOTE:** This epic is a **finding record only** — no tasks are defined yet. It captures
> the current e2e activation mechanism, its known constraints, and the open question of whether a
> cleaner general solution exists. A scoping/decision session should precede any task breakdown.

---

## Context

E17 STEP 5 added the first **live database end-to-end tests** for the Cypher inspectors
(`tests/extensions/neo4j/test_inspector_e2e.py`, with a Memgraph parallel). To run these without
breaking CI, an activation mechanism was assembled from pytest's standard building blocks:

- **Markers** (`@pytest.mark.neo4j`, `@pytest.mark.memgraph`) tag the live tests; they are
  declared in `pyproject.toml` under `[tool.pytest.ini_options] markers`.
- **CLI flags** (`--neo4j`, `--memgraph`) opt in to running marked tests; without them,
  `pytest_collection_modifyitems` skips every marked test.
- **Connection options** (`--neo4j-uri`, `--neo4j-user`, `--neo4j-password`, and the Memgraph
  equivalents) carry connection details, defaulting to a stock local install.
- **Session fixtures** (`neo4j_driver` / `memgraph_driver`) open one driver per session;
  **function fixtures** (`neo4j_clean` / `memgraph_clean`) wipe the database before and after
  each test for isolation.

All of the above except the markers live in the **root `conftest.py`**.

---

## The Finding

The current arrangement works and is correctly minimal, but it has a structural constraint worth
recording and, ideally, improving:

1. **A root `conftest.py` is mandatory, not optional.** The `--neo4j`/`--memgraph` flags are
   registered via `pytest_addoption`, which is a Python-only hook — `pyproject.toml` cannot
   register custom CLI options (it only accepts pytest's built-in settings). The conftest cannot
   move into `tests/` because `notebooks/conftest.py` also depends on those flags during
   collection, and pytest only loads the **rootdir** conftest (not `tests/conftest.py`) when the
   target is `notebooks/`. So the flags must be registered at the project root.

2. **Activation is coarse-grained and manual.** A flag exists per backend; there is no notion of
   "run all e2e tests", "run e2e against a remote/staging instance", or environment-variable-based
   activation (useful in CI matrices and containerised runners). Connection details are passed as
   long CLI strings rather than read from a discoverable config or `.env`.

3. **The pattern does not generalise cheaply.** Each new live backend (a future SQLAlchemy
   backend, a remote GQLAlchemy target, etc.) requires another flag, another set of connection
   options, another driver fixture, and another `clean` fixture — all hand-written in the root
   conftest. There is no shared abstraction for "a gated live-backend test suite".

4. **No CI story for the e2e layer.** The e2e tests are silently skipped in the default CI run by
   design, which means they currently run **only on a developer's machine against a manually
   started database**. There is no documented or automated path for exercising them (e.g. a
   dedicated CI job with service containers, a nightly run, or a pre-release gate).

5. **The gating was matching on directory name, not marker (FIXED 2026-06-10).** The original
   `pytest_collection_modifyitems` skipped any item whose `item.keywords` contained `"neo4j"` /
   `"memgraph"`. Because `item.keywords` also includes the names of a test's parent directories,
   **every** pure unit test under `tests/extensions/{neo4j,memgraph}/` (e.g. the entire
   `test_inspector_queries.py` suite — 27 tests including the identifier-injection-safety tests)
   was silently skipped in the default run, not just the marked e2e tests. A default
   `pytest tests/extensions/neo4j/test_inspector_queries.py` reported `27 skipped` rather than
   running. The hook now gates on the **applied marker** (`item.iter_markers()`) instead of
   `item.keywords`, so only tests explicitly tagged `@pytest.mark.neo4j` / `@pytest.mark.memgraph`
   are gated. This was a pre-existing flaw, but became load-bearing when E17 populated those
   directories with the security-critical unit tests. Recorded here as a cautionary note: any
   future "smart" gating logic (see Open Question below) must not reintroduce path-name matching.

---

## Why This Matters

- **Pilot readiness.** PRD User Stories 4 and 5 promise live Neo4j *and* Memgraph inspection with
  the same interface. The e2e tests are the only thing that proves this against real databases,
  yet they are the least-exercised part of the suite (off by default, no CI job).
- **Avoiding drift.** Without a general mechanism, every backend reinvents its own activation
  plumbing in the root conftest — the same cross-cutting redundancy E2 and E20 were created to
  prevent, but for test infrastructure.
- **The conftest constraint is non-obvious.** The reason the root conftest cannot be collapsed into
  `tests/conftest.py` (notebook flag dependency + rootdir loading rules) is subtle and was
  rediscovered during this session. Recording it prevents a future "let's just move this" change
  that silently breaks `pytest notebooks/ --neo4j`.

---

## Open Question (for a future scoping session)

**Is there a cleaner, more general solution for managing e2e-test activation and configuration?**
Candidate directions to evaluate (not decisions):

- A small **internal pytest plugin** (`[project.entry-points.pytest11]`) that owns flag
  registration, marker gating, env-var fallbacks, and a reusable "gated live-backend" fixture
  factory — removing the bespoke root-conftest plumbing and giving one place to add a backend.
- **Environment-variable activation** (e.g. `ORTHOGRAPH_E2E_NEO4J_URI`) alongside or instead of
  CLI flags, so CI runners and containers can opt in without long command lines.
- A **dedicated CI job** (service containers for Neo4j + Memgraph) that runs the e2e layer on a
  schedule or as a pre-release gate, so the live-database promise is continuously verified.
- Confirm whether the root `conftest.py` can be slimmed further or whether the notebook
  dependency makes its current placement permanent.

A decision session should weigh whether the added abstraction earns its keep at the current
backend count (two) or whether the present hand-written approach is acceptable until a third live
backend appears.

---

## Requirement — Three-Tier Test Classification (for scoping)

> **Origin:** E17 T7/T8 review session 2026-06-10. Surfaced while fixing finding #5 above.

The current model is binary: a test is either **gated** (needs a live DB, marked
`@pytest.mark.neo4j`/`memgraph`, off by default) or **always-on** (everything else). This conflates
two distinct categories of always-on test and offers no way to express a third, useful category.

The desired model has **three tiers**:

| Tier | Needs a DB? | Default run | If a DB is available |
|------|-------------|-------------|----------------------|
| **no-db** | Never — pure unit / mock tests (e.g. `test_inspector_queries.py`: `build()`, `materialize()`, injection-safety). | Always runs. | Runs (unchanged). |
| **db-optional** | No, but *can* run against a live DB if one is present — e.g. a query that is asserted as a string today could additionally be executed end-to-end when a driver is configured. | Runs in its no-db form. | *Also* exercised against the live DB. |
| **db-required** | Yes — assertions that only make sense against real data (current `*_e2e.py`). | Skipped. | Runs. |

**The requirement:** devise a classification mechanism that lets a test declare which tier it
belongs to, such that:

- **no-db** tests run unconditionally (this is the default and must never regress to the
  directory-name-matching bug of finding #5).
- **db-required** tests are gated behind `--neo4j` / `--memgraph` (current behaviour).
- **db-optional** tests run their database-free assertions by default *and* opt into an additional
  live execution when the corresponding flag/driver is available — without duplicating the test
  body across two files.

Open sub-questions to resolve during scoping:

- Is the **db-optional** tier worth the machinery, or is the no-db + db-required split sufficient
  in practice? (A db-optional test is essentially a parametrised fixture that yields a fake backend
  by default and a real driver when available.)
- How is the tier declared — a new marker (`@pytest.mark.db_optional`), a fixture that resolves to
  fake-or-real, or naming convention? Whatever is chosen must gate on the **marker/fixture**, never
  on the file path (finding #5).
- Does this fold into the candidate "internal pytest plugin" above, or is it a lighter-weight
  fixture-factory addition?

This requirement is **recorded for scoping only** — no implementation decision is made here.

---

## Out of Scope (this epic, until scoped)

- Implementing any of the candidate solutions above (decision-first).
- Application-level test observability, flaky-test management, or test-data factories beyond the
  existing `_seed` / `*_clean` helpers.
- Changing the inspector or query code under test — this epic concerns the **activation and
  configuration harness only**, not the e2e assertions themselves.
