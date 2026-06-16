# Epic E35: Write Query Return-Row Echo — surface `RETURN` rows from `write()`

> **Priority:** High
> **Origin:** Follow-on to E34 / E33-Q2; notebook ergonomics review 2026-06-16.
> **Goal:** Let a Cypher write query echo what its `RETURN` clause actually
> returns (e.g. `CREATE (m:Movie {...}) RETURN m`), so a `201 Created`-style
> "return the created entity" is expressible without a follow-up read query.
> Today `CypherExecutor.write()` consumes the driver result for its mutation
> counters and **discards every `RETURN` row** before `interpret_result` sees it.
> **Blocked by:** E34 — reuses E34's **RETURN-column classifier (T1, shipped)** and
> its **static tiered alignment (T2, shipped)**. *Note (2026-06-16): E34's default
> `materialize` (T4) was reverted; `materialize` is an explicit required method. E35
> depends only on the static classifier/tiering, not the withdrawn default.*
> ADR-gated: no implementation before ADR-026.
> **Blocks:** Honest write-side documentation (notebook 04.05 / 05.01); fulfils
> the E33-Q2 / ADR-026 slot.

---

## Problem statement (verified against source 2026-06-16)

`CypherExecutor.write()` (`src/orthograph/cypher/query_execution.py:103-134`):
1. `tx.run(cypher, **qparams)` → driver `Result` (line 121).
2. `CypherWriteResultSummary.from_neo4j_result(result)` (line 122) → which calls
   `result.consume().counters` (line 44) — **consuming the cursor and discarding
   any projected rows**.
3. Only the five counters reach `interpret_result(summary)` (line 123).

So `CREATE (m:Movie {title: $title}) RETURN m` runs, creates the node, and the
returned `m` row is **silently dropped**. The docstring (lines 110-113) states
this is intentional ("write queries express their result through
`interpret_result` acting on those counters, not on returned row data"). For a
REST-idiomatic create-and-echo, the consumer must issue a second read query —
the single largest write-side ergonomic gap (E33-Q2).

This is the **symmetric half** of E34: E34 fixes read-side RETURN→Output
*validation*; E35 lets the *write* side return what it returns.

---

## Decisions taken at epic creation (to be ratified in ADR-026, Task T1)

- **Echo model:** add an optional `rows` field to `CypherWriteResultSummary` (and
  the `WriteResultSummary` protocol) — **not** a separate `WriteQueryWithReturn`
  subclass. `interpret_result` then receives both counters and rows. (Chosen over
  the subclass approach to keep one write path; chosen over "defer to v0.2"
  because pilots need create-and-echo.)
- **Backward compatibility is non-negotiable:** `rows` is **optional with a
  default** (`rows: list[dict[str, Any]] = field(default_factory=list)` on the
  dataclass; `rows: list[...]` with a default on the protocol via a default
  property or a non-required member). This keeps every existing test double that
  satisfies `WriteResultSummary` valid **without edits** (see Constraints).
- **Row collection is opt-in by template inspection, not always-on:** collect rows
  only when the built Cypher has a `RETURN` clause (detected via the parser /
  E34's classifier). Counter-only writes keep today's behaviour and cost.
- **`MERGE` / batch `UNWIND` boundary:** the ADR must state honestly that
  create-and-echo is reliable for `CREATE ... RETURN` and single-row `MERGE ...
  RETURN`; multi-row / batch writes return a list and the consumer's
  `interpret_result` decides. We do **not** promise "the created entity" for every
  write — we promise "the rows the `RETURN` clause projected."

---

## Constraints from existing code (must respect)

- **`WriteResultSummary` is `runtime_checkable` and asserted at import**
  (`query_execution.py:55`: `assert isinstance(CypherWriteResultSummary(), WriteResultSummary)`).
  Adding a **required** protocol member would break that assertion and every test
  double. `rows` MUST be optional/defaulted so the following existing doubles stay
  valid untouched:
  - `tests/cypher/test_query_execution.py`: `FakeSummary`/`FakeCounters` (113-145),
    `StubSummary` (312-328), the protocol tests (293-328).
  - `tests/api/test_database.py`: `FakeCounters`/`FakeSummary` (150-219).
  - `tests/cypher/test_generator.py`: `_FakeResult`/`_FakeCounters` (728-784).
  - `tests/query/test_catalogue.py`, `tests/query/test_base_models.py`,
    `tests/cypher/test_base_models.py`, `tests/backends/gqlalchemy/test_base_models.py`:
    `interpret_result` doubles that take `raw: object` and read counters only.
- **Driver-cursor safety (open question for ADR/verify):** does
  `list(result)` (collect rows) **before** `result.consume()` work on the neo4j
  Python driver, or does consuming invalidate the cursor? The current code
  consumes immediately; E35 must collect first, then consume. T2 must verify this
  against the driver semantics (and, if live-DB-gated, behind the `--neo4j` flag).
- **`tests/test_architecture.py`:** `cypher/` stays vendor-free — no top-level
  `neo4j` import. Row collection uses the generic `result` iterable already passed
  in; no vendor import needed.
- **Connections never owned (Constraint 13)** and **transaction boundary
  unchanged:** `write()` still opens the explicit tx, collects rows + counters,
  then commits. Rollback-on-exception path (lines 125-133) must be preserved
  exactly.
- **Tests are the specification (Constraint 12).** Every change ships with tests.
- **No re-exports in `__init__.py`** (architecture test #4).

---

## Tasks

Execute in order. T1 is the ADR gate; do not implement T2+ before ADR-026 is
written. T1 may be skipped/short if ADR-026 already exists from E33-Q2.

---

### T1 — ADR-026: write-query return-row echo

**Output:** `.agentic/decisions/026-write-query-return-rows.md` (the slot E33-Q2
reserved).

**Record:**
- Decision: add optional `rows` to `CypherWriteResultSummary` + `WriteResultSummary`
  protocol (the chosen model); reject the `WriteQueryWithReturn` subclass and the
  "defer to v0.2" alternatives (state why each was rejected).
- The optional-with-default backward-compat rule and why (the import-time
  `isinstance` assertion + the test-double inventory above).
- The opt-in row-collection rule (collect only when the template has `RETURN`).
- The `MERGE`/batch boundary and the honest scope of the guarantee ("returns the
  projected rows", not "always the created entity").
- The driver-cursor-safety requirement (collect-before-consume) as an explicit
  acceptance gate for T2.
- Cross-link: reuses E34's RETURN classifier (ADR is consistent with ADR-025).
- Update `overview.md`: E33-Q2 superseded by E35; mark ADR-026 as the authority.

**Acceptance criteria:**
- [ ] ADR-026 written with the decision, rejected alternatives, compat rule,
      opt-in rule, scope boundary, and cursor-safety gate.
- [ ] `overview.md` notes E35 supersedes E33-Q2.
- [ ] No production code in this task.

---

### T2 — Collect `RETURN` rows before consuming; add `rows` to the summary

**Files:**
- `src/orthograph/query/write_result.py` (`WriteResultSummary` protocol, 11-32).
- `src/orthograph/cypher/query_execution.py` (`CypherWriteResultSummary` 19-55;
  `from_neo4j_result` 41-51; `write()` 103-134).

**Change:**
1. Add to `CypherWriteResultSummary` an optional
   `rows: list[dict[str, Any]] = field(default_factory=list)` (requires
   `from dataclasses import field`).
2. Add `rows` to the `WriteResultSummary` protocol as a **non-required / defaulted**
   member so existing counter-only doubles still satisfy it (e.g. a `@property`
   with no enforced presence, or document that doubles may omit it; verify the
   import-time `isinstance` assertion at line 55 still passes with a bare
   `CypherWriteResultSummary()`).
3. Rewrite `from_neo4j_result` to **collect rows first, then consume**:
   ```
   rows = [dict(rec) for rec in result]   # collect projected rows
   counters = result.consume().counters   # then consume
   ```
   Only collect when rows are expected — see T3 for the opt-in gate; if always
   collecting is simpler and safe, the empty-RETURN case naturally yields `[]`.
4. `write()` (line 122) passes the enriched summary through to `interpret_result`
   unchanged in signature — `interpret_result(summary)` now sees `summary.rows`.

**Tests (modify/add in `tests/cypher/test_query_execution.py`):**
- ADD: a `FakeGraphSession`/`FakeWriteResult` that returns BOTH rows and counters;
  a `CypherWriteQuery` whose `interpret_result` reads `raw.rows[0]` and returns a
  `Movie`. Assert the created entity is echoed.
- ADD: a write with no `RETURN` → `summary.rows == []`, counters intact,
  `interpret_result` reading counters still works (regression).
- KEEP: `test_write_materializes_result` (195-206),
  `test_write_commits_transaction` (220-228),
  `test_write_bad_params_raise_before_run` (209-217),
  `test_write_unparseable_cypher_raises_before_session_run` (264-290) — all green.
- KEEP: the protocol tests
  `test_cypher_write_result_summary_satisfies_protocol` (296-306) and
  `test_plain_dataclass_satisfies_write_result_summary` (309-328) — verify a
  double **without** `rows` still satisfies the protocol (the compat guarantee).
- Driver-cursor-safety: if a live-DB test is warranted, add one behind `--neo4j`
  asserting `CREATE ... RETURN m` echoes the row from a real driver result.

**Acceptance criteria:**
- [ ] `CypherWriteResultSummary` carries `rows`, defaulting to `[]`.
- [ ] `from_neo4j_result` collects rows before `consume()`; counters unchanged.
- [ ] A write with `RETURN m` echoes the row through `interpret_result`.
- [ ] The import-time `isinstance(CypherWriteResultSummary(), WriteResultSummary)`
      assertion (line 55) still passes.
- [ ] `pytest tests/cypher/test_query_execution.py` green.

---

### T3 — Opt-in row collection by template inspection (reuse E34 classifier)

**File:** `src/orthograph/cypher/query_execution.py` (`write()`), reusing
`extract_return_columns` / the `ReturnColumn` classifier from E34/T1
(`src/orthograph/cypher/parser.py`).

**Change:** Detect whether the built Cypher projects a `RETURN` clause (classifier
returns a non-empty column list, or `None` for `RETURN *`). Collect rows only when
a `RETURN` is present; otherwise keep the consume-only fast path (today's
behaviour, zero added cost for pure mutations). This keeps counter-only writes
exactly as fast and side-effect-free as before.

> If T2 already collects unconditionally and the empty case is provably free
> (no rows to iterate), T3 may reduce to a documented note in the ADR rather than
> code. Implementer decides based on measured cost; record the choice.

**Tests (add in `tests/cypher/test_query_execution.py`):**
- A pure-mutation write (`CREATE (m:Movie {...})`, no RETURN) does not attempt row
  iteration / `summary.rows == []`.
- A `RETURN`-bearing write collects rows.

**Acceptance criteria:**
- [ ] Counter-only writes incur no row-collection behaviour change.
- [ ] `RETURN`-bearing writes collect rows.
- [ ] `pytest tests/cypher/test_query_execution.py` green.

---

### T4 — (optional, if ADR-026 + E34 agree) validate the write `RETURN` shape

**File:** `src/orthograph/cypher/validation.py` (`validate_query_catalogue`,
write-query branch — today writes are excluded from alignment, lines 168-180 +
the comment at 168-171).

**Change:** Today `WriteQuery` is explicitly excluded from RETURN→Output alignment
because "writes expose only mutation counters, not projected rows." After E35 that
rationale no longer holds for `RETURN`-bearing writes. IF the ADR decides write
queries should declare the echoed shape (a `WriteQuery` `Output`/`R` type), extend
the E34 tiered alignment check to write queries that have a `RETURN` clause,
reusing the same classifier. Keep counter-only writes excluded.

> This task is **conditional**: only do it if ADR-026 says the write echo shape
> should be statically validated. If the ADR keeps write-echo validation out of
> v0.1, record that and skip T4. Default leaning: include it — it is the natural
> symmetry with E34 and closes the same silent-mismatch gap on the write side.

**Tests (add in `tests/cypher/test_validate_query_catalogue.py`):**
- A `RETURN`-bearing write whose declared echo type matches → no issue.
- A `RETURN`-bearing write missing a required echoed field → ERROR (mirror E34/T2).
- A counter-only write → still excluded (no alignment issue).

**Acceptance criteria:**
- [ ] (if included) Write `RETURN` shape is validated with the same tiering as E34.
- [ ] Counter-only writes remain excluded.
- [ ] `pytest tests/cypher/test_validate_query_catalogue.py` green.

---

### T5 — Notebook write-echo cells (`04.05`, `05.01`)

**Files:** `notebooks/04.05_cypher_result_shapes.ipynb` (the write-discard note),
`notebooks/05.01_openapi_ergonomics_assessment.ipynb` (the `201 Created` / write
ergonomics narrative).

**Why:** 04.05's known-gaps table (lines ~1510-1511) lists "Write queries discard
`RETURN` rows (cannot echo created node) — E33 Q2, ADR-026" as pending; 05.01
discusses the write ergonomics gap. After E35 these are resolved and must be
demonstrated, not just described.

**Change:**
- Update the 04.05 gaps table row from "pending" to resolved (ADR-026 / E35), or
  remove it and add a short cell showing a `CREATE ... RETURN m` write echoing the
  created `Movie` via `interpret_result` reading `summary.rows[0]`.
- Update 05.01's write-echo narrative to show the create-and-return flow.
- Re-execute affected notebooks and re-save outputs (nbval compares stored
  outputs): `jupyter nbconvert --to notebook --execute --inplace <nb>`.

**Acceptance criteria:**
- [ ] `pytest notebooks/ --nbval-lax` green.
- [ ] 04.05 / 05.01 demonstrate write-echo working; the "discards RETURN rows"
      gap note is resolved.
- [ ] Stored outputs regenerated and committed.

---

### T6 — Full-suite review pass & test-double audit

**Steps:**
- Full suite: `pytest` (DB tests auto-skip).
- Notebooks: `pytest notebooks/ --nbval-lax`.
- Architecture: `pytest tests/test_architecture.py`.
- Grep `tests/` for every `WriteResultSummary` / `interpret_result` /
  `from_neo4j_result` double (inventory in Constraints) and confirm each still
  satisfies the protocol without modification (the compat guarantee). If any
  required modification, the `rows`-optional rule was violated — fix the source,
  not the doubles.
- Confirm `api/database.py` write path (`tests/api/test_database.py` doubles)
  still works through the enriched summary.
- If a live driver is available, run the `--neo4j` cursor-safety test.

**Acceptance criteria:**
- [ ] `pytest` fully green (no DB).
- [ ] `pytest notebooks/ --nbval-lax` fully green.
- [ ] `pytest tests/test_architecture.py` green.
- [ ] No existing `WriteResultSummary` test double required edits.
- [ ] A short note appended recording the cursor-safety verification result.

---

## Impacted-files index (for the implementing session)

**Source (change):**
- `src/orthograph/query/write_result.py` — T2 (protocol gains optional `rows`).
- `src/orthograph/cypher/query_execution.py` — T2/T3 (`CypherWriteResultSummary.rows`,
  `from_neo4j_result` collect-before-consume, `write()` opt-in collection).
- `src/orthograph/cypher/validation.py` — T4 (conditional: write RETURN alignment).
- (reuses) `src/orthograph/cypher/parser.py` — E34/T1 classifier; no change here.

**Tests (change / add / re-verify):**
- `tests/cypher/test_query_execution.py` — T2/T3 (write-echo, opt-in, protocol
  compat; KEEP existing write tests).
- `tests/cypher/test_validate_query_catalogue.py` — T4 (write RETURN alignment).
- `tests/api/test_database.py` — T6 (write path doubles still valid).
- Protocol-double files (audit only, expect no edits): `tests/cypher/test_generator.py`,
  `tests/query/test_catalogue.py`, `tests/query/test_base_models.py`,
  `tests/cypher/test_base_models.py`, `tests/backends/gqlalchemy/test_base_models.py`.
- `tests/test_architecture.py` — guard (no change expected).

**Notebooks (re-execute / re-save):**
- `notebooks/04.05_cypher_result_shapes.ipynb`,
  `notebooks/05.01_openapi_ergonomics_assessment.ipynb` — T5.

**Decisions / planning:**
- `.agentic/decisions/026-write-query-return-rows.md` — T1 (new ADR).
- `.agentic/planning/overview.md` — T1 (E33-Q2 superseded by E35).

**Commands:**
- Unit tests: `pytest`
- Notebooks: `pytest notebooks/ --nbval-lax`
- Architecture: `pytest tests/test_architecture.py`
- Live cursor-safety: `pytest tests/cypher/test_query_execution.py --neo4j`
- Regenerate a notebook:
  `jupyter nbconvert --to notebook --execute --inplace notebooks/04.05_cypher_result_shapes.ipynb`

---

## Success Criteria

- [ ] T1: ADR-026 records the `rows`-on-summary decision, rejected alternatives,
      compat rule, opt-in rule, `MERGE`/batch scope, and cursor-safety gate.
- [ ] T2: `write()` echoes `RETURN` rows via `summary.rows`; collect-before-consume
      verified; import-time protocol assertion still passes.
- [ ] T3: row collection is opt-in by template inspection (or proven-free
      always-on); counter-only writes unchanged.
- [ ] T4 (if included): write `RETURN` shape validated with E34's tiering.
- [ ] T5: notebooks demonstrate write-echo; the discard-gap note resolved.
- [ ] T6: full suite + notebooks + architecture green; **no existing
      `WriteResultSummary` double required edits**; cursor-safety recorded.
- [ ] A `CREATE (m:Movie {...}) RETURN m` write returns the created `Movie` without
      a follow-up read query.
