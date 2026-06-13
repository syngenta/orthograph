# Epic E26: CI Containerised E2E — Live-Database Tests in the Pipeline

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness
> **Origin:** Conversation 2026-06-11 (developer question about running e2e tests in CI using
> containerised databases).
> **Blocked by:** None — independent of all other epics. Coordinates with E21 (closes its
> open question #4) and E22 (provides the CI infrastructure that live-DB paths in E22 will
> rely on).
> **Relates to:** E21 (e2e activation & configuration), E22 (e2e coverage audit), PRD User
> Stories 4–5 (live Neo4j and Memgraph inspection).

---

## Description

Today, all live-database tests are gated behind `--neo4j` / `--memgraph` CLI flags and run
only on a developer's machine against a manually started database. No MR pipeline exercises
the e2e layer against real graph databases. This is the open question recorded in
E21 finding #4.

This epic introduces a dedicated GitLab CI job (`pytest-integration`) that spins up a
containerised **Neo4j 5** and a containerised **Memgraph** as service containers within a
single job, shared across the whole test session. Both databases start in parallel as
sidecar containers; the test runner connects to them over the job's internal Docker network
using the service alias as hostname.

No application code or fixture changes are required. The existing `--neo4j` / `--memgraph`
CLI flags are kept. CI passes `--neo4j-uri bolt://neo4j:7687` and
`--memgraph-uri bolt://memgraph:7687` so the driver fixtures point at the service hostnames
instead of `localhost`.

The epic also fills in the Memgraph e2e scaffold (`test_inspector_e2e.py` currently has 15
test stubs with no real assertions) so both databases are meaningfully exercised in every
MR pipeline.

### Why service containers are the right approach

GitLab CI's `services:` keyword starts sidecar containers before `before_script`, health-
checks the declared ports, and tears them down at the end of the job. This gives a database
that is:

- **shared for the whole test session** — one driver, one `session`-scoped fixture, no
  per-test container startup cost.
- **isolated per job** — each MR pipeline gets a fresh, empty database with no shared state.
- **zero-infrastructure** — no external database server to maintain; the image is pulled from
  Docker Hub on demand.

The `FF_NETWORK_PER_BUILD: "true"` variable activates per-job Docker networking, which is
required for the test container to reach the service containers by hostname.

---

## How to use this epic (execution protocol)

Tasks are **sequential**. Do not start T(n+1) until T(n) passes its acceptance gate.
Each task is self-contained and designed so a single agent can complete it without reading
the whole epic — just the task section plus the **Shared Reference** section at the bottom.

---

## Tasks

### T1 — Verify Docker images start cleanly and accept a Bolt connection

**Goal:** Confirm the exact `docker run` commands and environment variables needed before
writing any CI YAML. Catching image quirks here is cheaper than debugging inside a pipeline.

**What to do:**

1. Pull both images locally:
   ```
   docker pull neo4j:5
   docker pull memgraph/memgraph:latest
   ```

2. Start Neo4j in the foreground (or `-d`), passing `NEO4J_AUTH` to set credentials:
   ```
   docker run --rm -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5
   ```

3. Start Memgraph — no auth required by default:
   ```
   docker run --rm -p 7688:7687 memgraph/memgraph:latest
   ```

4. Run the Python probe below against each instance. The probe must exit 0:

   ```python
   # probe_neo4j.py
   from neo4j import GraphDatabase
   d = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
   d.verify_connectivity()
   records, _, _ = d.execute_query("RETURN 1 AS n")
   assert records[0]["n"] == 1
   d.close()
   print("Neo4j OK")
   ```

   ```python
   # probe_memgraph.py
   from neo4j import GraphDatabase
   d = GraphDatabase.driver("bolt://localhost:7688", auth=("", ""))
   d.verify_connectivity()
   records, _, _ = d.execute_query("RETURN 1 AS n")
   assert records[0]["n"] == 1
   d.close()
   print("Memgraph OK")
   ```

5. Note any startup time — Neo4j typically takes 10–20 s. The observed startup time is the
   baseline for the readiness loop in T3.

**Acceptance gate:**
- [ ] Both images pull without error.
- [ ] Both probes exit 0.
- [ ] Startup time for each image is recorded (to calibrate the T3 readiness loop).

---

### T2 — Confirm `conftest.py` URI defaults are CI-friendly

**Goal:** Verify that passing `--neo4j-uri` / `--memgraph-uri` from the command line fully
overrides all connection defaults, and that no hardcoded `localhost` or port 7688 leaks into
fixtures that would break in the CI network.

**What to do:**

1. Read `conftest.py` (project root) and trace every place a URI or port appears:
   - `--neo4j-uri` default: `bolt://localhost:7687`
   - `--memgraph-uri` default: `bolt://localhost:7688`
   - `neo4j_driver` and `memgraph_driver` fixtures: both read from `request.config.getoption()`

2. Confirm the fixtures read the option, not a hardcoded string. No changes should be needed
   — this task is a read-and-verify step. If a hardcoded value is found, fix it.

3. Run the full unit-test suite to confirm it is still green (no live DB needed):
   ```
   python -m pytest -v
   ```

4. Run the existing e2e tests locally against a live Neo4j instance started at the
   non-default URI to confirm the override works end-to-end:
   ```
   # start neo4j on 17687 to prove the override is honoured
   docker run --rm -p 17687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5
   python -m pytest -v --neo4j --neo4j-uri bolt://localhost:17687 \
       tests/extensions/neo4j/test_inspector_e2e.py
   ```

**Acceptance gate:**
- [ ] `python -m pytest -v` (no flags) passes — all unit tests green, all e2e tests skipped.
- [ ] Overriding `--neo4j-uri` to a non-default port routes correctly; the e2e tests pass
  against the non-default URI.
- [ ] No hardcoded `localhost` or port literals exist in the driver fixtures.

---

### T3 — Add the `pytest-integration` CI job to `.gitlab-ci.yml`

**Goal:** Introduce a second `pytest`-stage job that runs the e2e test suite against
containerised Neo4j and Memgraph service containers. The existing `pytest` job (unit tests)
is unchanged.

**What to do:**

Add the following job to `.gitlab-ci.yml` (after the existing `pytest` job):

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
                  d = GraphDatabase.driver(uri, auth=auth)
                  d.verify_connectivity()
                  d.close()
                  print(f"{label} ready")
                  return
              except Exception as e:
                  if i == retries - 1:
                      sys.exit(f"{label} not ready after {retries * delay}s: {e}")
                  time.sleep(delay)

      wait("bolt://neo4j:7687",     ("neo4j", "password"), "Neo4j")
      wait("bolt://memgraph:7687",  ("", ""),               "Memgraph")
      EOF
  script:
    - >
      python -m pytest -v
      --neo4j
      --neo4j-uri bolt://neo4j:7687
      --neo4j-user neo4j
      --neo4j-password password
      --memgraph
      --memgraph-uri bolt://memgraph:7687
```

**Notes on the job design:**

- `FF_NETWORK_PER_BUILD: "true"` — activates per-job Docker networking so the test container
  can reach service containers by hostname. Required by GitLab Runner for service networking.
- `NEO4J_AUTH: "neo4j/password"` — Neo4j's official image reads this env var on first start
  to set the initial password. The value must match `--neo4j-password`.
- `alias: neo4j` / `alias: memgraph` — the service is reachable at exactly this hostname
  within the job network. Both use port 7687 (Bolt); no port conflict because they are
  separate containers with separate hostnames.
- Memgraph starts with no auth by default — `--memgraph-user ""` and `--memgraph-password ""`
  match the `conftest.py` defaults, so no extra env var is needed.
- The readiness loop in `before_script` handles Neo4j's ~10–20 s startup time. It runs
  before `script`, so the DB is ready when pytest starts.
- The job does **not** use `parallel: matrix` (Python version matrix). E2E correctness does
  not depend on the Python version; running on 3.12 is sufficient.

**Validation commands (run locally before pushing):**

```bash
# Syntax-check the YAML with GitLab's CI lint endpoint (requires gitlab CLI or curl):
# https://gitlab.com/<namespace>/<project>/-/ci/lint
# Or use the yamllint tool:
pip install yamllint
yamllint .gitlab-ci.yml
```

**Acceptance gate:**
- [ ] `yamllint .gitlab-ci.yml` reports no errors.
- [ ] The existing `pytest` job definition is unchanged.
- [ ] The new `pytest-integration` job appears in the MR pipeline and completes with a green
  status (both `--neo4j` and `--memgraph` e2e tests run and pass).
- [ ] The `pytest` (unit-test) job and `pytest-integration` job run in parallel within the
  `pytest` stage — neither blocks the other.

---

### T4 — Fill in the Memgraph e2e scaffold

**Goal:** Replace the stub tests in `tests/extensions/memgraph/test_inspector_e2e.py` with
real assertions so the Memgraph path is meaningfully exercised by the CI job added in T3.

**Context:**

The Neo4j e2e suite (`tests/extensions/neo4j/test_inspector_e2e.py`) has 21 fully
implemented tests added in E17. The Memgraph file has 15 stubs (test functions with `pass`
or `...` bodies) added as a scaffold in the same session. The two suites are designed to be
parallel: the same logical assertions, adapted for Memgraph-specific parity gaps.

**Parity gaps to handle explicitly (not skip):**

| Field | Neo4j | Memgraph | Required assertion |
|---|---|---|---|
| `NodeTypeProfile.count` | real count from `db.labels()` | always `0` (schema procedures yield no counts) | assert `== 0` with a comment explaining the gap |
| `PropertyProfile.present_count` / `.total_count` | observation counts | mandatory-field heuristic | assert the heuristic value; document that it is not an observation |
| APOC | available, auto-detected | not available | no APOC-dependent assertions; pure-Cypher path only |

**What to do:**

1. Read `tests/extensions/neo4j/test_inspector_e2e.py` in full to understand the assertion
   pattern, the `_seed()` function, and the `neo4j_clean` fixture usage.

2. Read `tests/extensions/memgraph/test_inspector_e2e.py` to see the existing stubs.

3. Implement each stub test. Use `memgraph_driver` and `memgraph_clean` fixtures (already
   defined in the root `conftest.py`). Mirror the Neo4j test structure; adapt for the parity
   gaps above.

4. For each parity gap, add an inline comment of the form:
   ```python
   # PARITY GAP: Memgraph schema procedures do not return node counts.
   # NodeTypeProfile.count is always 0 on Memgraph. See E22 for the
   # shared-contract layer that will document this asymmetry formally.
   assert profile.node_types["Person"].count == 0
   ```

5. Run the suite locally against a live Memgraph:
   ```
   docker run --rm -p 7687:7687 memgraph/memgraph:latest
   python -m pytest -v --memgraph tests/extensions/memgraph/test_inspector_e2e.py
   ```

**Acceptance gate:**
- [ ] All stubs are replaced with real test bodies — no `pass` or `...` remains.
- [ ] `pytest --memgraph tests/extensions/memgraph/test_inspector_e2e.py` passes with ≥ 15
  tests collected and 0 failures.
- [ ] Every parity gap has an explicit assertion and an inline comment — none are silently
  skipped.
- [ ] The Neo4j e2e suite is unchanged.
- [ ] The unit-test suite (`pytest -v`, no flags) still passes (no accidental import-time
  fixture breakage).

---

### T5 — Close E21 open question #4 and update planning docs

**Goal:** Record that the "no CI story for the e2e layer" finding in E21 is resolved, update
the planning overview with E26, and add a sentence to `conftest.py` so future contributors
know where the CI job lives.

**What to do:**

1. In `conftest.py` (project root), update the module docstring to add a line under the
   "Usage" block:

   ```
   CI (GitLab):  see .gitlab-ci.yml job `pytest-integration` which passes
                 --neo4j and --memgraph with service-container URIs.
   ```

2. In `E21_tech_debt_e2e_test_config.md`, add a resolution note to finding #4:

   ```markdown
   > **Resolved by E26 (2026-06-11).** A dedicated `pytest-integration` CI job with
   > Neo4j and Memgraph service containers was added to `.gitlab-ci.yml`. The job passes
   > `--neo4j` / `--memgraph` with `--*-uri` pointing at the service hostnames, so no
   > fixture changes were needed. See E26 for the full implementation record.
   ```

3. Update `planning/overview.md`:
   - Add E26 to the epics table.
   - Add E26 to the dependency section under "INDEPENDENT".
   - Add E26 to the active epics file list.

4. Mark this task complete by adding `**done** (<date>)` to the E26 status in `overview.md`.

**Acceptance gate:**
- [ ] `conftest.py` docstring references the CI job.
- [ ] E21 finding #4 carries a resolution note pointing to E26.
- [ ] E26 appears in the `overview.md` table and file list.
- [ ] No other file changes are introduced in this task.

---

## Shared Reference

> Point any agent executing a single task at this section plus the task section above.
> Everything needed to complete a task is in those two sections.

### Relevant files

| File | Role |
|---|---|
| `conftest.py` (project root) | CLI options, skip hook, `neo4j_driver`, `memgraph_driver`, `neo4j_clean`, `memgraph_clean` fixtures |
| `.gitlab-ci.yml` | CI pipeline — add `pytest-integration` in T3 |
| `tests/extensions/neo4j/test_inspector_e2e.py` | Reference e2e suite for T4 |
| `tests/extensions/memgraph/test_inspector_e2e.py` | Target scaffold to fill in T4 |
| `.agentic/planning/active_epics/E21_tech_debt_e2e_test_config.md` | Finding #4 to close in T5 |
| `.agentic/planning/overview.md` | Table and dependency graph to update in T5 |

### Service container hostname rules (GitLab CI)

- The hostname within the job network equals the `alias:` value.
- Both Neo4j and Memgraph listen on Bolt port **7687** inside their respective containers.
- No port mapping to the host is needed — the test container talks directly to the service
  containers over the job's internal network.
- `FF_NETWORK_PER_BUILD: "true"` must be set as a job variable (not globally) to activate
  per-job networking.

### Existing CLI flags and their defaults

```
--neo4j              bool flag; enables neo4j-marked tests
--neo4j-uri          default bolt://localhost:7687
--neo4j-user         default neo4j
--neo4j-password     default password
--memgraph           bool flag; enables memgraph-marked tests
--memgraph-uri       default bolt://localhost:7688
--memgraph-user      default ""
--memgraph-password  default ""
```

### Memgraph parity gaps (for T4)

- `NodeTypeProfile.count` is always `0` on Memgraph (schema procedures yield no counts).
- `PropertyProfile.present_count` / `.total_count` are mandatory-field heuristics, not
  observation counts.
- APOC is not available on Memgraph — the inspector uses pure Cypher fallbacks only.
- These gaps must be **explicitly asserted and commented**, not silently skipped.

### References

- GitLab CI services: https://docs.gitlab.com/ee/ci/services/
- Neo4j Docker image: https://hub.docker.com/_/neo4j
- Memgraph Docker image: https://hub.docker.com/r/memgraph/memgraph
