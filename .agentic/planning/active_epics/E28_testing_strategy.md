# Epic E28: Testing Strategy — Activation Harness, Shared-Contract Layer, Shared Fixtures & CI

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness
> **Status:** planned (independent — can start immediately; tasks are sequenced internally)
> **Consolidates:** E21 (e2e activation & configuration), E22 (e2e coverage audit & shared-contract
> test layer), E26 (CI containerised e2e). Those three epics are **archived → E28**. This epic is the
> single home for the project's testing strategy.
> **Relates to:** PRD User Stories 4–6 (live Neo4j, Memgraph, and NetworkX inspection with the same
> interface), PRD Constraint 13 (Orthograph never owns a connection — drivers are passed in),
> the root `conftest.py`, the `tests/backends/{neo4j,memgraph,networkx}/` suites, and E8 (GQLAlchemy
> query catalogue — owns its own e2e tests, out of scope here).

---

## Why this epic exists

Three previously-separate epics all concerned the same surface — the project's test
infrastructure — and overlapped heavily:

- **E21** recorded the *finding* that e2e-test activation (markers + CLI flags + root conftest) is
  coarse-grained, does not generalise, and has no CI story. It defined no tasks.
- **E22** recorded the *requirement* for a shared-contract test layer so the same assertions run
  against NetworkX (in-process), Neo4j, and Memgraph without duplicating assertion logic. It defined
  no tasks.
- **E26** defined *concrete tasks* for a containerised CI job, but was written against a now-stale
  premise (that the Memgraph e2e suite was 15 stubs — see Reality Check below).

Splitting these across three epics meant the activation mechanism (E21), the test that consumes it
(E22), and the CI that runs it (E26) could not be reasoned about together. This epic merges them and
adds the **test-data consolidation** work the team asked for: a single shared source for the most-used
datasets, with per-module declarations only for the data that diverges. The objective is **fewer places
to edit** when the model or seed dataset changes.

---

## Reality Check (verified against the codebase 2026-06-15 — read before trusting the source epics)

The source epics contain stale claims. The following were verified by inspection and **supersede**
any contradicting statement in E21/E22/E26:

1. **Directory layout is `tests/backends/<vendor>/`, NOT `tests/extensions/<vendor>/`.** Every path in
   E21/E22/E26 that says `tests/extensions/...` is wrong. Use `tests/backends/...`.
2. **The Memgraph e2e suite is already fully implemented** (`tests/backends/memgraph/test_inspector_e2e.py`,
   15 real tests with real assertions and documented parity gaps). E26 T4 ("fill in the stubs") is
   **obsolete** — there are no stubs. The corresponding task here (T6) is reduced to an audit/verify step.
3. **Two byte-identical copies of the Filmography model already exist** as the consolidation seam:
   `tests/comparison/conftest.py` (lines 15–63) and `tests/backends/gqlalchemy/conftest.py` (lines 18–66).
   Both define `Person/Movie/City` + `ActedIn/LivesIn/Directed` and a `filmography_model` fixture.
4. **Two byte-identical `_seed()` Cypher functions exist:** `tests/backends/neo4j/test_inspector_e2e.py:71`
   and `tests/backends/memgraph/test_inspector_e2e.py:87`. Same logical dataset.
5. **`tests/data/` exists but contains only `.gitkeep`.** There is no `tests/fixtures/`, no YAML test
   data, and no central factory module. `tests/conftest.py` defines only a `data_folder_path` fixture.
6. **The skip hook already gates on the applied marker** (`item.iter_markers()`), not `item.keywords` —
   E21 finding #5 is already fixed. Do not regress this.

---

## Scope

**In scope:**
- A decision on the e2e-test activation/configuration mechanism (E21's open question) — env-var
  activation + whether to keep the root conftest or extract a small internal pytest plugin.
- A **shared test-data module** holding the most-used datasets (Filmography model + the canonical seed
  dataset), with individual test modules importing it and declaring locally only what diverges.
- A **shared-contract test layer**: one parameterised assertion set that runs against NetworkX
  (always), Neo4j (`--neo4j`), and Memgraph (`--memgraph`), consuming the shared seed.
- The **CI containerised e2e job** (GitLab service containers for Neo4j 5 + Memgraph).
- Closing E21 finding #4 (no CI story) and recording the activation decision.

**Out of scope:**
- The **db-optional** third tier (E21's three-tier model). Recorded as an OPEN DECISION in T1; not
  implemented unless T1 decides it earns its keep.
- GQLAlchemy query-catalogue (E8) e2e tests — they belong to E8.
- New validation rules, new `GraphProfile` fields, or any source-code change to inspectors / executor
  / client. **This epic touches the test layer and CI config only.**
- Performance / load testing; flaky-test management; test-data generation (that is E24).

---

## How to use this epic (execution protocol)

Tasks are **sequential within their wave** but two waves are independent (see Task Map). Do not start
T(n+1) until T(n) passes its acceptance gate, unless the Task Map marks them parallel.

Each task is **self-contained**: a single low-context agent can complete it by reading **only**
(a) that task's section and (b) the **Shared Reference** section at the bottom. Tasks state their
exact files, the change to make, and a binary acceptance gate. Where a task makes a decision rather
than code, it produces a written artefact (ADR or epic note) and changes no production/test code.

---

## Task Map (dependency order)

```
T1  Activation & configuration DECISION (ADR)         ─┐ decision-only
                                                        │
WAVE A — shared data + contract (no live DB; CI-safe)   │
T2  Extract shared test-data module                     │  ← unblocks T3, T4
T3  Migrate duplicate conftests + seed to shared module │
T4  Build shared-contract test layer (NetworkX path)    │
                                                        │
WAVE B — live DB + CI (needs T1 decision + a database)  │
T5  Implement activation decision from T1              ◄┘  (env-var / plugin)
T6  Wire live-DB backends into the shared-contract layer + audit Memgraph suite
T7  Add the `pytest-integration` CI job
T8  Close E21 finding #4 + update planning docs
```

- **T1** is decision-only and gates **T5**. T2–T4 (Wave A) do **not** depend on T1 and can start
  immediately.
- **T2 → T3 → T4** are strictly sequential.
- **T5 → T6 → T7 → T8** are strictly sequential and depend on Wave A being done and T1 decided.

---

## Tasks

### T1 — DECISION: e2e activation & configuration mechanism (ADR)

**Type:** Decision-only. Produces an ADR in `.agentic/decisions/`. **No code is written.**

**Goal:** Resolve E21's open question so T5 has a concrete spec to implement. Decide the smallest
mechanism that (a) adds env-var activation for CI/containers, (b) keeps the existing `--neo4j` /
`--memgraph` CLI flags working, and (c) does not regress the marker-based gating.

**What to do:**

1. Read the **Shared Reference → Activation mechanism (current state)** below — that is the full
   current behaviour. You do not need to read any source file other than the root `conftest.py`
   to confirm it.
2. Decide and record, in an ADR, answers to these questions:
   - **Env-var activation.** Should CI opt in via env vars (e.g. `ORTHOGRAPH_E2E_NEO4J_URI`,
     `ORTHOGRAPH_E2E_NEO4J=1`) in addition to CLI flags? Recommended: **yes**, as a fallback the
     fixtures read when the CLI option is unset, because CI matrices and containers prefer env vars
     over long command lines. State the exact env-var names.
   - **Plugin vs root conftest.** Should the flag registration + gating + driver/clean fixtures move
     into a small internal pytest plugin (`[project.entry-points.pytest11]`), or stay in the root
     conftest? Recommended default: **stay in the root conftest** at the current backend count (two)
     — the plugin earns its keep only when a third live backend appears. Record the trigger condition
     for revisiting.
   - **db-optional tier (OPEN DECISION).** Decide whether the third "db-optional" tier (a test whose
     no-db assertions run by default and which *also* runs against a live DB when available) is worth
     the machinery, or whether the no-db + db-required split is sufficient. Recommended: **defer** —
     the shared-contract layer (T4/T6) already gives most of the benefit via backend-factory
     parametrization. If deferred, say so explicitly so no agent builds it speculatively.
   - **Root conftest placement constraint.** Re-state (so it is not lost) why the root conftest cannot
     collapse into `tests/conftest.py`: `notebooks/conftest.py` depends on the `--neo4j`/`--memgraph`
     flags during collection, and pytest only loads the **rootdir** conftest (not `tests/conftest.py`)
     when the target is `notebooks/`. Any future change must preserve `pytest notebooks/ --neo4j`.
3. Cross-link the ADR from this epic (add its number under "References" below) and, if it changes a
   documented boundary, from CONTEXT.md.

**Acceptance gate:**
- [ ] An ADR exists in `.agentic/decisions/` recording: env-var activation decision (with exact names),
      plugin-vs-conftest decision (with trigger to revisit), db-optional tier decision (with
      defer/build rationale), and the root-conftest placement constraint.
- [ ] The ADR states a concrete spec T5 can implement without further decisions.
- [ ] No production or test code changed.

---

### T2 — Extract the shared test-data module

**Type:** Code (test infrastructure). No source-code change. **WAVE A — no live DB needed.**

**Goal:** Create one canonical home for the most-used test datasets so divergent copies stop
multiplying. This is the consolidation the team asked for: declare the common dataset once; let
individual modules import it and declare locally only what diverges.

**What to do:**

1. Create a new package `tests/shared/` with `tests/shared/__init__.py` (empty) and a module
   `tests/shared/filmography.py`.
2. Move the **Filmography model definitions** into `tests/shared/filmography.py` — copy the classes
   verbatim from `tests/comparison/conftest.py` lines 15–55 (`Person`, `Movie`, `City`, `ActedIn`,
   `LivesIn`, `Directed`) and add a module-level factory:
   ```python
   def filmography_definition() -> GraphDefinition:
       """The canonical Filmography GraphDefinition used across the test suite."""
       return GraphDefinition(
           name="Filmography",
           node_types=[Person, Movie, City],
           relationship_types=[ActedIn, LivesIn, Directed],
       )
   ```
   Keep the classes importable at module level (`from tests.shared.filmography import Person, Movie, ...`).
3. Add the **canonical seed dataset** to the same module, as backend-agnostic data plus two thin
   loaders, so there is ONE source of truth for the seed:
   ```python
   # The single logical dataset every backend is seeded with.
   SEED_CYPHER = (
       "MERGE (alice:Person {name: 'Alice', born: 1985})"
       " MERGE (bob:Person {name: 'Bob'})"
       " MERGE (inc:Movie {title: 'Inception', year: 2010})"
       " MERGE (dune:Movie {title: 'Dune', year: 2021})"
       " MERGE (alice)-[:ACTED_IN {role: 'Lead'}]->(inc)"
       " MERGE (alice)-[:ACTED_IN {role: 'Cameo'}]->(dune)"
       " MERGE (bob)-[:ACTED_IN {role: 'Supporting'}]->(inc)"
   )

   def seed_cypher(driver) -> None:
       """Seed a live Cypher backend (Neo4j/Memgraph) with the canonical dataset."""
       driver.execute_query(SEED_CYPHER)

   def seed_networkx():
       """Build the same logical dataset as an nx.MultiDiGraph (no network I/O)."""
       import networkx as nx
       g = nx.MultiDiGraph()
       g.add_node("alice", __label__="Person", name="Alice", born=1985)
       g.add_node("bob", __label__="Person", name="Bob")
       g.add_node("inc", __label__="Movie", title="Inception", year=2010)
       g.add_node("dune", __label__="Movie", title="Dune", year=2021)
       g.add_edge("alice", "inc", __label__="ACTED_IN", role="Lead")
       g.add_edge("alice", "dune", __label__="ACTED_IN", role="Cameo")
       g.add_edge("bob", "inc", __label__="ACTED_IN", role="Supporting")
       return g
   ```
   > **Important:** `seed_networkx()` must produce the dataset that is **logically identical** to
   > `SEED_CYPHER` (two Person — Bob has no `born` — two Movie, three ACTED_IN edges with roles
   > Lead/Cameo/Supporting). The shared-contract layer (T4) depends on this equivalence.
4. Add a short module docstring stating the rule: *"This module is the single source for the
   most-used test datasets. Import from here. Declare data locally in a test module ONLY when it must
   diverge from the canonical dataset (e.g. an empty graph, a deliberately-mismatched model). When you
   diverge, add a one-line comment saying why."*
5. Confirm `tests/shared/` is importable: `pyproject.toml testpaths=["tests"]` and the existing
   `tests/__init__.py` make `tests` a package, so `from tests.shared.filmography import ...` resolves.
   Verify with a throwaway import (`python -c "from tests.shared.filmography import filmography_definition; filmography_definition()"`).

**Acceptance gate:**
- [ ] `tests/shared/__init__.py` and `tests/shared/filmography.py` exist.
- [ ] `filmography.py` exports the six model classes, `filmography_definition()`, `SEED_CYPHER`,
      `seed_cypher(driver)`, and `seed_networkx()`.
- [ ] `python -c "from tests.shared.filmography import filmography_definition, seed_networkx; filmography_definition(); seed_networkx()"` exits 0.
- [ ] No existing test file is changed yet (migration is T3). No source code changed.

---

### T3 — Migrate the duplicate conftests and seed functions to the shared module

**Type:** Code (test infrastructure). **WAVE A — no live DB needed.** Depends on T2.

**Goal:** Delete the duplicated Filmography copies and the duplicated `_seed` Cypher, pointing all
consumers at `tests/shared/filmography.py`. The behaviour of every test must be unchanged.

**What to do:**

1. **`tests/comparison/conftest.py`** — remove the six local class definitions (lines 15–55) and
   replace the `filmography_model` fixture body with a call to the shared factory:
   ```python
   from tests.shared.filmography import filmography_definition

   @pytest.fixture()
   def filmography_model() -> GraphDefinition:
       return filmography_definition()
   ```
   Re-export the classes if any test in `tests/comparison/` imports them from the conftest
   (`from tests.shared.filmography import Person, Movie, City, ActedIn, LivesIn, Directed` at the top of
   the conftest preserves those names).
2. **`tests/backends/gqlalchemy/conftest.py`** — same treatment (it is byte-identical to the
   comparison conftest today).
3. **`tests/backends/neo4j/test_inspector_e2e.py`** — delete the local `_seed` function (line 71) and
   import the shared one: `from tests.shared.filmography import seed_cypher`. Replace `_seed(driver)`
   call sites with `seed_cypher(driver)`. If the file also re-declares the Filmography model locally
   (lines ~43–67), replace those with imports from `tests.shared.filmography`.
4. **`tests/backends/memgraph/test_inspector_e2e.py`** — same: delete local `_seed` (line 87), import
   `seed_cypher`, replace call sites; replace any local model re-declaration with shared imports.
5. **`tests/backends/networkx/test_inspector.py`** — for the test(s) that build the **full**
   filmography graph, replace the inline construction with `seed_networkx()` where the test's intent is
   "the canonical full graph". Leave the small targeted per-test graphs (those that exist to exercise a
   specific stat like cardinality min/max) as local literals, adding a one-line comment that they
   diverge deliberately. **Do not** force every networkx test onto the shared dataset — only the ones
   whose intent is the canonical dataset.
6. Run the full suite (no flags — live DB not needed): `python -m pytest -q`. It must be green with
   the same test count as before the migration (minus none — no tests removed, only de-duplicated
   data sources).

**Acceptance gate:**
- [ ] No `class Person(NodeModel)` / `class Movie` / `class ActedIn` ... definitions remain in
      `tests/comparison/conftest.py` or `tests/backends/gqlalchemy/conftest.py` — they import from
      `tests/shared/filmography.py`.
- [ ] No `def _seed(` remains in either e2e file — both call `seed_cypher`.
- [ ] `python -m pytest -q` (no flags) passes; collected test count is unchanged from before T3.
- [ ] Any deliberately-divergent local dataset carries a one-line "diverges because…" comment.
- [ ] No source code (`src/`) changed.

---

### T4 — Build the shared-contract test layer (NetworkX path)

**Type:** Code (test layer). **WAVE A — no live DB needed.** Depends on T3.

**Goal:** Create one parameterised assertion set that expresses what a correct `GraphProfile` looks
like for the canonical seed dataset, independent of which inspector produced it. In this task, wire
**only** the NetworkX backend (always runs in CI). Neo4j/Memgraph factories are added in T6.

**What to do:**

1. Create `tests/shared/contract.py` (or `tests/backends/test_inspector_contract.py` — pick one and
   note it). It must contain:
   - A **backend-factory parametrize**: a list of `(id, factory)` pairs, where each factory returns an
     `(inspector, target)` ready to call `inspector.inspect(target)`. In T4, the list has exactly one
     entry: `("networkx", _networkx_factory)`, where `_networkx_factory` uses `seed_networkx()` from
     T2 and the `NetworkxInspector`.
   - A **single assertion set** (parametrized test functions or one test class) that asserts the
     `GraphProfile` produced for the canonical dataset:
     - `node_labels == {"Person", "Movie"}`; `relationship_types == {"ACTED_IN"}`.
     - Property profiles: Person `{name, born}` with `born` optional (Bob lacks it); Movie
       `{title, year}`; ACTED_IN `{role}`.
     - `RelationshipTypeProfile` endpoints: `source_labels == {"Person"}`, `target_labels == {"Movie"}`.
     - `cardinality_stats`: `min_degree == 1`, `max_degree == 2`, `avg_degree == 1.5`,
       `sample_size == 2`, and the regression guard `min_degree > 0` (computed on the source label).
     - `validate_database` / `validate_profile` against `filmography_definition()` is valid; a
       deliberately-mismatched model fails with the correct error code(s).
   - For any field where backends will diverge (e.g. `NodeTypeProfile.count` is 0 on Memgraph),
     express the expectation as a **per-factory parameter** (an `expected_person_count` carried in the
     factory tuple), NOT a hardcoded literal — so T6 can add Neo4j (count 2) and Memgraph (count 0)
     without forking the assertion body.
2. Structure the parametrize so adding a backend in T6 is **one new tuple in the factory list** and
   nothing else. Document this at the top of the file in a comment.
3. Run `python -m pytest -q tests/shared/contract.py` (or the chosen path). The NetworkX parametrization
   must pass. Confirm the full suite still passes.

**Acceptance gate:**
- [ ] The shared-contract module exists with a backend-factory parametrize whose only entry is
      NetworkX, and a single assertion set covering labels, property profiles (incl. optional `born`),
      endpoint labels, cardinality stats (incl. `min_degree > 0` regression guard), and validation.
- [ ] Backend-divergent expectations (e.g. node count) are carried as per-factory parameters, not
      hardcoded — proven by a comment showing exactly where T6 adds the Neo4j/Memgraph tuples.
- [ ] `python -m pytest -q` (no flags) passes including the new NetworkX contract tests.
- [ ] No source code changed.

---

### T5 — Implement the activation decision from T1

**Type:** Code (test infrastructure). **WAVE B.** Depends on T1 (ADR) and Wave A complete.

**Goal:** Implement exactly what the T1 ADR decided — typically: env-var fallback for the connection
options and the activation flags, kept in the root `conftest.py` (unless T1 chose the plugin).

**What to do:**

1. Read the T1 ADR. Implement **only** what it specifies. The expected default (confirm against the
   ADR) is:
   - `pytest_addoption` defaults read an env var when set, e.g. the `--neo4j-uri` default becomes
     `os.environ.get("ORTHOGRAPH_E2E_NEO4J_URI", "bolt://localhost:7687")`, and equivalent for user,
     password, and the Memgraph options.
   - The `--neo4j` / `--memgraph` boolean flags additionally activate when
     `ORTHOGRAPH_E2E_NEO4J` / `ORTHOGRAPH_E2E_MEMGRAPH` is truthy (so CI can opt in without the flag).
2. Do **not** change the marker-based skip hook logic — it already gates correctly on
   `item.iter_markers()`. If the ADR added env activation, the hook reads the merged flag (CLI OR
   env), not the raw CLI value.
3. Do not move the conftest out of the project root (the notebook-flag constraint forbids it) unless
   the ADR explicitly chose the plugin route and specified the migration.
4. Verify: with no env and no flags, `python -m pytest -q` runs all unit tests green and skips all
   e2e tests. With `ORTHOGRAPH_E2E_NEO4J_URI` set and `ORTHOGRAPH_E2E_NEO4J=1` against a local Neo4j,
   the Neo4j e2e tests run without any CLI flag.

**Acceptance gate:**
- [ ] The activation mechanism matches the T1 ADR exactly (env-var fallback names match the ADR).
- [ ] `python -m pytest -q` (no env, no flags) passes all unit tests and skips all e2e tests.
- [ ] Setting the documented env vars activates the e2e tests with no CLI flag (verified against a
      local DB, or — if no DB is available — by a unit test asserting the option-resolution logic).
- [ ] `pytest notebooks/ --neo4j` still collects correctly (root-conftest flag registration intact).

---

### T6 — Wire live-DB backends into the shared-contract layer + audit the Memgraph suite

**Type:** Code (test layer). **WAVE B.** Depends on T4 and T5. Requires a live DB (or CI in T7).

**Goal:** Extend the T4 shared-contract parametrize with the Neo4j and Memgraph backend factories so
the same assertions run against all three backends, and verify the existing Memgraph e2e suite is
real (it is — see Reality Check #2) and aligned with the shared seed.

**What to do:**

1. Add two tuples to the T4 backend-factory list:
   - `("neo4j", _neo4j_factory)` — gated by `@pytest.mark.neo4j`; uses `neo4j_driver` + `neo4j_clean`
     fixtures, calls `seed_cypher(driver)`, returns the `Neo4jInspector`. `expected_person_count = 2`.
   - `("memgraph", _memgraph_factory)` — gated by `@pytest.mark.memgraph`; uses `memgraph_driver` +
     `memgraph_clean`, `seed_cypher`, `MemgraphInspector`. `expected_person_count = 0` (PARITY GAP —
     Memgraph schema procedures yield no counts). Add an inline comment on the parity-gap parameter.
2. Handle the documented parity gaps as explicit per-factory parameters, never as silent skips:
   - `NodeTypeProfile.count`: 2 (Neo4j/NetworkX) vs 0 (Memgraph).
   - `PropertyProfile.present_count` / `.total_count`: observation counts (Neo4j/NetworkX) vs
     mandatory-field heuristic (Memgraph) — assert the appropriate value per factory with a comment.
3. **Audit the existing Memgraph e2e suite** (`tests/backends/memgraph/test_inspector_e2e.py`, 15 real
   tests): confirm it now imports the shared `seed_cypher` (done in T3) and that its assertions do not
   contradict the shared-contract layer. **Do not delete it** — it carries Memgraph-specific tests
   (catalogue size = 5, pure-Cypher fallbacks) that the cross-backend layer does not. If any assertion
   is now redundant with the contract layer, leave a `# covered by shared-contract layer (E28 T4)`
   comment rather than removing it, to avoid losing coverage during this epic.
4. Verify both gated paths:
   ```
   docker run --rm -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5
   docker run --rm -p 7688:7687 memgraph/memgraph:latest
   python -m pytest -q --neo4j --memgraph tests/shared/contract.py
   python -m pytest -q --memgraph tests/backends/memgraph/test_inspector_e2e.py
   ```

**Acceptance gate:**
- [ ] The shared-contract parametrize has three factories (networkx, neo4j, memgraph); adding the two
      live ones required only new tuples, no change to the assertion body.
- [ ] Parity gaps (node count 0 on Memgraph; heuristic present/total counts) are explicit per-factory
      parameters with inline comments — none silently skipped.
- [ ] `pytest -q --neo4j --memgraph tests/shared/contract.py` passes against live containers.
- [ ] The existing Memgraph e2e suite still passes and was not stripped of Memgraph-specific coverage.
- [ ] `python -m pytest -q` (no flags) still passes (NetworkX-only contract path runs; live skipped).

---

### T7 — Add the `pytest-integration` CI job

**Type:** Code (CI config). **WAVE B.** Depends on T6.

**Goal:** A dedicated GitLab CI job that runs the e2e + shared-contract live paths against
containerised Neo4j 5 and Memgraph service containers in every merge-request pipeline. The existing
`pytest` (unit) job is unchanged and runs in parallel.

**What to do:**

1. Before writing YAML, verify the images start and accept a Bolt connection locally (catching image
   quirks here is cheaper than in a pipeline):
   ```
   docker pull neo4j:5
   docker pull memgraph/memgraph:latest
   docker run --rm -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5
   docker run --rm -p 7688:7687 memgraph/memgraph:latest
   ```
   Probe each with a 3-line `neo4j.GraphDatabase.driver(...).verify_connectivity()` script; both must
   succeed. Record Neo4j startup time (~10–20 s) to calibrate the readiness loop.
2. Confirm the connection options are fully overridable from the command line / env (T5 made env-var
   fallbacks available; the CI job may use either — match the T1 ADR). No hardcoded `localhost`/port
   may leak into the driver fixtures.
3. Add the job below to `.gitlab-ci.yml` **after** the existing `pytest` job (adapt the activation
   to whatever T1/T5 chose — CLI flags shown; if env-var activation was chosen, set the env vars
   instead and drop the flags):
   ```yaml
   pytest-integration:
     stage: pytest
     rules:
       - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
     image: "python:3.12"
     variables:
       FF_NETWORK_PER_BUILD: "true"
       NEO4J_AUTH: "neo4j/password"
     services:
       - name: neo4j:5
         alias: neo4j
       - name: memgraph/memgraph:latest
         alias: memgraph
     before_script:
       - pip install -e '.[dev]'
       - |
         python - <<'EOF'
         import time, sys
         from neo4j import GraphDatabase
         def wait(uri, auth, label, retries=30, delay=2):
             for i in range(retries):
                 try:
                     d = GraphDatabase.driver(uri, auth=auth); d.verify_connectivity(); d.close()
                     print(f"{label} ready"); return
                 except Exception as e:
                     if i == retries - 1: sys.exit(f"{label} not ready: {e}")
                     time.sleep(delay)
         wait("bolt://neo4j:7687",    ("neo4j", "password"), "Neo4j")
         wait("bolt://memgraph:7687", ("", ""),              "Memgraph")
         EOF
     script:
       - >
         python -m pytest -v
         --neo4j --neo4j-uri bolt://neo4j:7687 --neo4j-user neo4j --neo4j-password password
         --memgraph --memgraph-uri bolt://memgraph:7687
   ```
   Notes: `FF_NETWORK_PER_BUILD: "true"` activates per-job Docker networking so the test container
   reaches services by hostname; both DBs use Bolt 7687 inside their own containers (no host port
   mapping needed); Memgraph needs no auth; the readiness loop covers Neo4j startup. Do **not** add a
   Python-version matrix — e2e correctness does not depend on the interpreter version.
4. Lint locally: `pip install yamllint && yamllint .gitlab-ci.yml`.

**Acceptance gate:**
- [ ] Both probes exit 0 locally; Neo4j startup time recorded.
- [ ] `yamllint .gitlab-ci.yml` reports no errors.
- [ ] The existing `pytest` job is unchanged; `pytest-integration` runs in parallel with it in the
      `pytest` stage.
- [ ] In an MR pipeline the new job completes green with both `--neo4j` and `--memgraph` paths
      (including the T6 shared-contract live paths) executed.

---

### T8 — Close E21 finding #4 and update planning docs

**Type:** Docs. **WAVE B.** Depends on T7.

**Goal:** Record that the "no CI story for the e2e layer" finding is resolved, point the root conftest
docstring at the CI job, and finalise this epic's status in the planning overview.

**What to do:**

1. In `conftest.py` (project root), add a line to the module docstring's usage block:
   ```
   CI (GitLab):  see .gitlab-ci.yml job `pytest-integration` which runs the e2e and
                 shared-contract live paths against Neo4j + Memgraph service containers.
   ```
2. In this epic, mark T7 as resolving the legacy E21 finding #4 (no CI story) — add a one-line note
   under T7's acceptance gate or in the changelog at the bottom.
3. Update `.agentic/planning/overview.md`:
   - Confirm E28 is in the epics table with status reflecting completion of its tasks.
   - Confirm E21/E22/E26 are listed under archived (superseded → E28).
4. Run the full suite once more (`python -m pytest -q`) to confirm green after all doc edits.

**Acceptance gate:**
- [ ] `conftest.py` docstring references the `pytest-integration` CI job.
- [ ] E21 finding #4 is recorded as resolved (here or in the archived E21 banner).
- [ ] `overview.md` reflects E28's state and the E21/E22/E26 archival.
- [ ] `python -m pytest -q` (no flags) passes.

---

## Shared Reference

> Point any agent executing a single task at **this section + their task section only**. Everything
> needed is in those two places.

### Relevant files (verified paths — use these, not the `tests/extensions/...` paths in old epics)

| File | Role |
|---|---|
| `conftest.py` (project root) | CLI options + env activation, marker skip hook, `neo4j_driver`/`memgraph_driver`/`neo4j_clean`/`memgraph_clean` fixtures |
| `notebooks/conftest.py` | Depends on root `--neo4j`/`--memgraph` flags during collection (constrains conftest placement) |
| `tests/conftest.py` | Only a `data_folder_path` fixture today |
| `tests/comparison/conftest.py` | Duplicate Filmography model + `filmography_model` fixture (T3 migrates) |
| `tests/backends/gqlalchemy/conftest.py` | Byte-identical duplicate of the above (T3 migrates) |
| `tests/backends/neo4j/test_inspector_e2e.py` | 21 real Neo4j e2e tests; local `_seed` at line 71 (T3 migrates) |
| `tests/backends/memgraph/test_inspector_e2e.py` | 15 **real** Memgraph e2e tests (NOT stubs); local `_seed` at line 87 (T3 migrates) |
| `tests/backends/networkx/test_inspector.py` | In-process `nx.MultiDiGraph` tests; `_make_graph()` helper |
| `tests/shared/filmography.py` | **Created in T2** — single source for the Filmography model + seed |
| `tests/shared/contract.py` | **Created in T4** — shared-contract parametrized assertion set |
| `tests/data/` | Exists with only `.gitkeep` — no shared data files yet |
| `pyproject.toml` `[tool.pytest.ini_options]` | `testpaths=["tests"]`, `addopts="-v --strict-markers --tb=short"`, markers `slow`/`neo4j`/`memgraph` |
| `.gitlab-ci.yml` | CI pipeline — `pytest-integration` job added in T7 |
| `.agentic/decisions/` | T1 ADR lives here |
| `.agentic/planning/overview.md` | Epic table + dependency graph (T8) |

### The canonical seed dataset (one logical graph for every backend)

- `Person` (uid `name`): **Alice** `{born: 1985}`, **Bob** `{}` (no `born` → exercises optional-property detection).
- `Movie` (uid `title`): **Inception** `{year: 2010}`, **Dune** `{year: 2021}`.
- `ACTED_IN {role}`: Alice→Inception (`Lead`), Alice→Dune (`Cameo`), Bob→Inception (`Supporting`).
- Derived: Person cardinality `min=1` (Bob), `max=2` (Alice), `avg=1.5`, `sample_size=2`; 3 ACTED_IN edges.
- `node_labels == {"Person", "Movie"}`; `relationship_types == {"ACTED_IN"}`; endpoints
  `source_labels == {"Person"}`, `target_labels == {"Movie"}`.

### The Filmography model (broader than the seed — includes City/LIVES_IN/DIRECTED for validation tests)

`Person/Movie/City` node models + `ActedIn (Person→Movie {role})`, `LivesIn (Person→City, source
card ONE, target ZERO_OR_MORE)`, `Directed (Person→Movie)`. Assembled as
`GraphDefinition(name="Filmography", node_types=[Person, Movie, City], relationship_types=[ActedIn, LivesIn, Directed])`.

### Activation mechanism (current state — confirm in `conftest.py`)

```
pytest_addoption registers:
  --neo4j              store_true; activates @pytest.mark.neo4j tests
  --neo4j-uri          default bolt://localhost:7687
  --neo4j-user         default neo4j
  --neo4j-password     default password
  --memgraph           store_true; activates @pytest.mark.memgraph tests
  --memgraph-uri       default bolt://localhost:7688
  --memgraph-user      default ""
  --memgraph-password  default ""

pytest_collection_modifyitems gates on item.iter_markers() (NOT item.keywords) — only tests
explicitly marked @pytest.mark.neo4j / @pytest.mark.memgraph are skipped when the flag is absent.
Do NOT regress to path-name / keyword matching.

Fixtures (root conftest):
  neo4j_driver / memgraph_driver   session-scoped; GraphDatabase.driver(uri, auth=...)
  neo4j_clean / memgraph_clean     function-scoped; "MATCH (n) DETACH DELETE n" before & after

Placement constraint: the conftest MUST stay at the project root because notebooks/conftest.py
reads --neo4j/--memgraph during collection and pytest only loads the rootdir conftest for
`pytest notebooks/`. Do not move it into tests/conftest.py.
```

### Memgraph parity gaps (carry as per-factory params, never silent skips)

- `NodeTypeProfile.count` is always `0` on Memgraph (schema procedures yield no counts); 2 on Neo4j/NetworkX.
- `PropertyProfile.present_count` / `.total_count` are mandatory-field heuristics on Memgraph, real
  observation counts on Neo4j/NetworkX.
- APOC is unavailable on Memgraph — pure-Cypher fallbacks only; no APOC-dependent assertions.

### GitLab CI service-container rules (for T7)

- The in-network hostname equals the `alias:` value; both DBs listen on Bolt **7687** inside their containers.
- No host port mapping needed — the test container talks to services over the job's internal network.
- `FF_NETWORK_PER_BUILD: "true"` must be a **job** variable to activate per-job networking.
- `NEO4J_AUTH: "neo4j/password"` sets Neo4j's initial password on first start; must match the password passed to pytest.

### References

- GitLab CI services: https://docs.gitlab.com/ee/ci/services/
- Neo4j Docker image: https://hub.docker.com/_/neo4j
- Memgraph Docker image: https://hub.docker.com/r/memgraph/memgraph
- T1 ADR: _record the number here once T1 creates it._
- Superseded epics: E21 (finding), E22 (requirement), E26 (CI tasks) — all archived → E28.

---

## Changelog

- **2026-06-15** — Epic created by consolidating E21 + E22 + E26 and adding the shared test-data
  consolidation task (T2/T3). Codebase re-verified; corrected `tests/extensions/` → `tests/backends/`
  and the stale "Memgraph e2e is stubs" premise (the suite is fully implemented).
