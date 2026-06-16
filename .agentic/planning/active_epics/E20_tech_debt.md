# Epic E20: Technical Debt

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness
> **Origin:** E17 refactor session 2026-06-10. General tech-debt bucket — each sub-section
> records a distinct finding with its own origin date and scope note.
> **Blocked by:** None — tasks here are independent unless noted. Coordinate with epics
> actively editing the same modules.

---

## T0: `from __future__ import annotations` — normalise across the codebase

> **Origin:** E8.1 session 2026-06-11
> **Priority:** Low — cosmetic; no runtime impact on py3.10+
> **Scope:** `src/` + `tests/`

**Finding.** The import is used inconsistently across the project:

- 8 source files and 7 test files carry it (all in the `gqlalchemy`, `networkx`, and
  `cypher/exceptions` modules).
- `cypher/base_models.py` — the primary mirror target — does **not** have it.
- Only one file (`cypher/exceptions.py`) **strictly requires** it: it imports `ValidationIssue`
  under `TYPE_CHECKING`, and without deferred evaluation that name would fail at runtime.
- All other files compile and run fine on py3.10+ without it (PEP 604 `X | Y` unions evaluate
  at runtime since py3.10; no forward-reference annotations were found).
- The ruff ruleset (`E,W,F,I`) does not include `UP010` (unnecessary `__future__` import), so
  tooling neither enforces nor forbids the import today.

**Decision surface.** Three coherent positions:

1. **Remove everywhere except `cypher/exceptions.py`** — matches the `cypher/base_models.py`
   precedent; rely on py3.10 runtime union support. Enable `ruff UP010` to enforce going forward.
2. **Add everywhere** — consistent with the majority of `gqlalchemy/` files; costs nothing.
3. **Leave as-is** — do nothing; inconsistency is a cosmetic annoyance but causes no failures.

**Recommended action (when picked up):**
1. Decide option 1, 2, or 3 and record the rationale here.
2. If option 1: run `sed`/ruff-fix to strip the import from all files except
   `cypher/exceptions.py`; enable `ruff UP010` (add `"UP010"` to `select` in `pyproject.toml`).
3. If option 2: add the import to the remaining files without it.
4. Run `pytest` + `mypy src/` + `ruff check` green before closing.

**Acceptance criteria:**
- [ ] Decision recorded (option 1/2/3) with rationale.
- [ ] If option 1 or 2: all files consistent; ruff clean; pytest + mypy green.
- [ ] `cypher/exceptions.py` retains the import regardless of chosen option.

---

## T7: Cypher validation does not distinguish a `$param` from a backtick-escaped identifier

> **Origin:** Notebook review session 2026-06-16 (`notebooks/05.01_openapi_ergonomics_assessment.ipynb`)
> **Priority:** Medium — silent correctness gap; affects definition-time *and* runtime Cypher validation.
> **Scope:** `src/orthograph/cypher/parser.py`, `src/orthograph/cypher/bindings.py`, `src/orthograph/cypher/base_models.py`
> **Relates to:** Epic E18 (validation correctness).

**Finding.** A `cypher_template` that wraps a parameter in backticks — e.g.
`` MATCH (m:Movie {released: `$released`}) `` — passes **every** validation layer Orthograph
currently has, yet is semantically wrong: in Cypher a backtick-quoted token is an *escaped
identifier*, not a parameter, so the driver never binds `$released` and the query silently
fails to filter (returns nothing / errors against a live driver).

Verified empirically (graphglot 2026-06 build, neo4j dialect):

- **graphglot parse** (`parse_cypher`) accepts both forms without error. The tokenizer reveals
  why: `` `$released` `` lexes to a **single `VAR` token** `'$released'` (an escaped identifier
  literally named `$released`), whereas the correct `$released` lexes to two tokens
  `DOLLAR_SIGN` + `VAR`. Both produce structurally identical lineage graphs, so the
  definition-time dialect parse in `_validate_declarative_cypher` cannot tell them apart.
- **Alignment checker** (`check_placeholder_alignment` → `extract_cypher_params`,
  `bindings.py:52`) uses the regex `\$([A-Za-z_][A-Za-z0-9_]*)`, which matches `$released`
  regardless of surrounding backticks. So the `$param` ↔ `Params`-field 1:1 check also goes
  green on the broken form.
- **Runtime check** (`CypherExecutor._validate_cypher`) reuses `parse_cypher`, so it inherits
  the same blind spot.

**Net effect.** The only thing that catches the mistake is a real driver returning wrong
results — exactly the "fail silently" failure mode the PRD exists to prevent. A consumer
copying a backtick template from documentation gets a green definition-time validation and a
silently broken query.

**Decision surface.**

1. **Lint in `_validate_declarative_cypher`** — after extracting `$param` names, scan the
   template for the pattern `` `\$NAME` `` (a parameter immediately wrapped in backticks) and
   raise `CypherQueryDefinitionError` with a fix hint ("remove the backticks around `$NAME`;
   parameters must not be backtick-quoted"). Cheap, regex-only, no graphglot dependency.
2. **Push upstream to graphglot** — ask graphglot to expose recognised parameter bindings on
   the lineage graph (`lg.parameters` is currently `None`) so Orthograph can assert that each
   regex-extracted `$param` corresponds to a real parameter node, not a `VAR`. More robust but
   depends on an external roadmap.
3. **Both** — ship the regex lint now (option 1) as a guard; track option 2 as the principled
   fix once graphglot surfaces parameter lineage.

**Recommended action (when picked up):** option 3. Land the regex lint immediately; file the
graphglot feature request and link it here.

**Related graphglot gap — `LIMIT $param` does not parse.** While fixing the backtick templates
in the §05.01 notebook, the bundled graphglot (neo4j dialect) was found to **reject a
parameterised `LIMIT`**: `RETURN m LIMIT $limit` raises `ParseError: Expected parameter name or
number after $`. `SKIP $skip` parses; `LIMIT $limit`, `LIMIT toInteger($limit)`, and
`SKIP $skip LIMIT $limit` all fail. Only a literal `LIMIT 100` parses. Consequences:

- A declarative paginated `CypherReadQuery` (the natural use of `PaginatedParams`) **cannot be
  defined** — `_validate_declarative_cypher` raises at class-definition time. The gap also bites
  at **runtime**: `CypherExecutor.read` re-parses the built Cypher via `_validate_cypher`, so even
  an imperative `build()` that emits `LIMIT $limit` raises `CypherSyntaxError` on every request.
- The §05.01 notebook works around this with the **imperative `build()` escape hatch** (no
  `cypher_template`) that **inlines `skip`/`limit` as integer literals** (`SKIP 0 LIMIT 100`),
  which graphglot parses. This is injection-safe because `PaginatedParams` validates them as
  bounded ints; the year filter stays a real `$released` parameter.
- This is an upstream graphglot parser limitation, not an Orthograph bug, but it directly blocks
  the headline pagination ergonomic. File a graphglot issue for `LIMIT <parameter>` support and
  link it here; until then, document the imperative-`build()` workaround in the pagination guide.

**Acceptance criteria:**
- [ ] A `cypher_template` containing `` `$param` `` raises `CypherQueryDefinitionError` at
      class-definition time with an actionable message.
- [ ] The lint does **not** false-positive on legitimate backtick-escaped *identifiers* that
      are not parameters (e.g. `` (n:`My Label`) ``) or on `<<name>>` identifier placeholders.
- [ ] Regression test covers: backtick-wrapped `$param` (rejected), clean `$param` (accepted),
      backtick-escaped label with no param (accepted).
- [ ] `pytest` + `mypy src/` + `ruff check` green.

---

## Error Hierarchy & Library Logging Discipline

> **Forward note — ADR-017 (2026-06-12) re-paths this section's file targets.**
> ADR-017 renames `core/` → `graph_definition/` and extracts the validation
> result currency to a new `diagnostics/` package. This section is **not
> contradicted** — its decisions (an `OrthographError` root; a `get_logger` +
> `NullHandler` convention) still stand — but its *destinations move*:
> - the project-wide `OrthographError` root and `get_logger`/logging helper are
>   **cross-cutting infrastructure**, so under ADR-017 they belong in a shared
>   home (alongside or near `diagnostics/`), **not** inside the renamed
>   definition package `graph_definition/`. Treat the `core/exceptions.py` /
>   `core/logging.py` paths below as **`diagnostics/`-adjacent** when this epic
>   is executed.
> - the ADR numbers cited below (`011-error-hierarchy.md`, `012-library-logging.md`)
>   are **stale** — those numbers are already taken (ADR-011 = capability seams,
>   ADR-012 = optional-dependency policy). Allocate the next free numbers when
>   picked up.
> - the `extensions/cypher/` and `extensions/networkx/` paths below predate the
>   E25 split (now `cypher/` and `backends/networkx/`).
> Do **not** revert ADR-017. When this section is executed, target the
> post-ADR-017 topology.


> **Origin:** E17 refactor session 2026-06-10 (Cypher exception hierarchy introduced; surfaced
> the absence of a project-wide exception root and any logging convention).
> **Relates to:** PRD Problem Statement ("applications fail silently"), PRD Constraint 1
> (DB-agnostic core), PRD Constraint 13 (Orthograph never owns a connection — it is a library,
> not an application), ADR-008 (Cypher identifier safety — raises on unsafe input).
>
> **SCOPE NOTE:** This section establishes two cross-cutting foundations and migrates the existing
> code onto them. It does NOT invent new diagnostics features, a metrics system, structured-event
> emission, or any application-level observability. The library emits diagnostics through the
> standard `logging` module and raises a coherent exception hierarchy; configuring sinks, levels,
> and formatting remains the consuming application's responsibility.

---

### Context

Two cross-cutting concerns have grown ad-hoc and now warrant a deliberate, one-time foundation:

1. **Exception hierarchy.** The Cypher extension recently gained a package base
   (`CypherError`) with `CypherQueryDefinitionError` / `CypherSyntaxError` inheriting it (E17
   refactor). No equivalent root exists elsewhere: `core/` and the other extensions raise bare
   `TypeError` / `ValueError` / `Exception`, so a consumer cannot catch "any Orthograph error"
   or reason about error provenance. There is no project-wide base to hang subpackage bases off.

2. **Logging.** Logging is incidental, not designed. Today only
   `extensions/networkx/inspector.py` calls `logging.getLogger(__name__)` (one `warning`). There
   is no convention for *when* to log vs raise vs warn, no `NullHandler` guard (a library must
   never configure the root logger or emit to a handler the application did not opt into), and no
   guidance separating user-facing `warnings.warn` (already used for imperative-query definitions
   in `cypher/base_models.py`) from operational `logging`.

The PRD's founding problem is that consuming applications "fail silently." A library whose own
diagnostics are inconsistent undercuts that mission. This epic makes both foundations explicit,
documents them, and migrates existing call sites — without expanding scope into
application-level observability.

---

### Why This Is Needed

- **Catchability.** A consumer should be able to `except OrthographError` to isolate every error
  this library raises from errors raised by their own code or third-party drivers.
- **Provenance + differentiation.** Errors should be differentiated by *subclass and message*,
  not by docstring inventories that go stale. (E17 already established this pattern for Cypher.)
- **Library hygiene.** A library must attach a `NullHandler` and never configure logging; the
  current ad-hoc `getLogger` usage has no such guard and no shared convention.
- **Consistency.** Without a single decision, every future extension reinvents both, drifting
  apart again — exactly the redundancy E2 set out to prevent, but for cross-cutting concerns.

---

### Implementation Order (build in this sequence)

```
STEP 1 — Exception hierarchy        (T1, T2, T3)   define root → adopt in subpackages → migrate raises
STEP 2 — Logging discipline + ADR   (T4, T5)       decide policy + helper → migrate call sites
STEP 3 — Documentation              (T6)           CONTEXT/PRD cross-links; developer guidance
─────────────────────────────────────────────────────────────────────────────────────────────
```

Files likely touched:
```
src/orthograph/core/exceptions.py                  NEW — OrthographError root (T1)
src/orthograph/extensions/cypher/exceptions.py     CypherError reparented under root (T2)
src/orthograph/<subpackages>/exceptions.py         NEW per-subpackage bases as needed (T2)
src/orthograph/**/*.py                             bare raises migrated to the hierarchy (T3)
src/orthograph/core/logging.py                     NEW — get_logger() + NullHandler convention (T4)
src/orthograph/extensions/networkx/inspector.py    migrated to the convention (T5)
.agentic/decisions/011-error-hierarchy.md          NEW (T1/T2)
.agentic/decisions/012-library-logging.md          NEW (T4)
tests/core/test_exceptions.py                      NEW (T1)
tests/core/test_logging.py                         NEW (T4)
```

---

### STEP 1 — Exception hierarchy

#### T1: Define the `OrthographError` root and record the decision

**What:** A single project-wide base exception that every Orthograph-raised error derives from,
directly or via a subpackage base.

**Actions:**
1. Create `src/orthograph/core/exceptions.py` with `class OrthographError(Exception)`. No
   behaviour beyond being a catchable root; the message carries specifics (no fixed cause-lists —
   the E17 anti-stale-docstring rule applies project-wide).
2. Decide and record in `.agentic/decisions/011-error-hierarchy.md`:
   - the root (`OrthographError`) and the two-level shape (root → subpackage base → concrete),
   - the rule that differentiation is by **subclass and message**, never by docstring inventory,
   - the policy on inheriting builtins: prefer the hierarchy over `TypeError`/`ValueError` for
     *library-domain* errors, while leaving genuinely generic type/value misuse as builtins where
     that is the honest signal (record the boundary so it is not re-litigated per PR),
   - the rejected alternative (no root / bare builtins everywhere) and why.

**Tests (`tests/core/test_exceptions.py`):**
- `OrthographError` is an `Exception` subclass.
- A subclass raised under `OrthographError` is catchable as the root.

**Verification:** `from orthograph.core.exceptions import OrthographError` works; ADR-011 exists.

---

#### T2: Reparent subpackage bases under the root

**What:** Each subpackage that raises domain errors gets (or keeps) a base inheriting
`OrthographError`.

**Actions:**
1. Reparent `CypherError` (in `extensions/cypher/exceptions.py`) to inherit `OrthographError`.
   `CypherQueryDefinitionError` / `CypherSyntaxError` already inherit `CypherError` — unchanged.
2. For each other subpackage that raises its own domain errors (neo4j, memgraph, gqlalchemy,
   io, core), introduce a base (`Neo4jError`, etc.) inheriting `OrthographError` **only where a
   subpackage actually raises domain errors** — do not create empty bases speculatively.
3. Keep each subpackage's exceptions in that subpackage's `exceptions.py` (the E17 pattern).

**Tests:** extend `tests/.../test_exceptions.py` per subpackage: each base inherits
`OrthographError`; each concrete exception inherits its subpackage base.

**Verification:** `except OrthographError` catches a Cypher, neo4j, etc. exception. `mypy src/`
clean.

---

#### T3: Migrate bare `raise` sites onto the hierarchy

**What:** Replace bare `raise TypeError/ValueError/Exception(...)` that signal a *library-domain*
failure with the appropriate hierarchy exception, preserving the message.

**Actions:**
1. Audit `raise` sites across `src/`. For each, decide: library-domain error (→ hierarchy) or
   genuine builtin misuse (→ leave as builtin, per the ADR-011 boundary).
2. Migrate the library-domain ones. Preserve message text so existing
   `pytest.raises(match=...)` assertions still match; update the `pytest.raises(<type>)` *type*
   where it changes, and document each behavioural change in the PR.
3. Do NOT change `warnings.warn` call sites (those are user advisories, not exceptions — see T4).

**Tests:** existing suites stay green; where an exception type legitimately changed, update the
`pytest.raises` type (not the message) and note it.

**Verification:** No library-domain `raise` bypasses the hierarchy (spot-checked by an audit
list in the PR). Full `pytest` green; `mypy src/` clean; `ruff check` clean.

---

### STEP 2 — Logging discipline

#### T4: Define the library logging convention + helper, and record the decision

**What:** A single, documented way the library emits operational diagnostics, honouring
"Orthograph is a library, not an application" (PRD Constraint 13's spirit).

**Actions:**
1. Create `src/orthograph/core/logging.py` providing `get_logger(name) -> logging.Logger`
   (thin wrapper over `logging.getLogger`) and attach a `logging.NullHandler` to the top-level
   `orthograph` logger so the library never emits unless the application opts in.
2. Decide and record in `.agentic/decisions/012-library-logging.md`:
   - **Library hygiene:** never call `basicConfig`, never add non-null handlers, never set levels
     on the root logger, never `print`.
   - **When to log vs raise vs warn:** raise (hierarchy) for caller errors the caller must handle;
     `warnings.warn` (e.g. the existing imperative-query `UserWarning`) for authoring advisories
     a developer should see once; `logging` for operational events (skipped record, fallback
     strategy chosen, retry) at the right level (`DEBUG`/`INFO`/`WARNING`).
   - **Logger naming:** module `__name__` under the `orthograph.*` tree.
   - the rejected alternative (ad-hoc `getLogger` per module with no `NullHandler`) and why.

**Tests (`tests/core/test_logging.py`):**
- The `orthograph` logger has a `NullHandler` (importing the library emits nothing to stderr).
- `get_logger("orthograph.x")` returns a logger under the `orthograph` tree.
- A logged warning is *capturable* via `caplog` but produces no output without app config.

**Verification:** Importing `orthograph` and exercising a code path that logs produces no stderr
output by default; ADR-012 exists.

---

#### T5: Migrate existing logging call sites to the convention

**What:** Bring the one current ad-hoc logger (and any added since) onto the convention.

**Actions:**
1. `extensions/networkx/inspector.py`: replace `logging.getLogger(__name__)` with
   `get_logger(__name__)` (or confirm equivalence and the `NullHandler` guard now covers it);
   confirm the existing `warning` is the right level per ADR-012.
2. Sweep `src/` for any `print(` used as diagnostics and convert to logging or remove.

**Tests:** the networkx inspector's existing behaviour is unchanged (its tests stay green); add a
`caplog` assertion on the skipped-node warning.

**Verification:** Full `pytest` green; no `print(` diagnostics remain in `src/`.

---

### STEP 3 — Documentation

#### T6: Cross-link the decisions and add developer guidance

**Actions:**
1. Add a one-line cross-link to ADR-011 and ADR-012 from CONTEXT.md's decisions routing (no
   content duplication).
2. If the PRD documents an error/diagnostics boundary, add a one-line reference; otherwise note
   in ADR-011/012 that this is a library-internal convention (not a PRD capability).
3. Brief "Errors & Logging" note for contributors (where to put a new exception; how to get a
   logger; raise-vs-warn-vs-log) — placed wherever contributor guidance lives, not duplicated.

**Verification:** An agent reading `.agentic/` can find both decisions from CONTEXT.md and apply
them without asking.

---

### Success Criteria (Error Hierarchy & Logging)

- [ ] `OrthographError` root exists; every library-raised domain error derives from it (T1–T3).
- [ ] Differentiation is by subclass + message; no stale "possible causes" docstring lists (T1).
- [ ] ADR-011 records the error-hierarchy decision and the builtin-vs-hierarchy boundary.
- [ ] The library attaches a `NullHandler` and never configures logging; `get_logger` is the one
      entry point (T4).
- [ ] ADR-012 records the raise-vs-warn-vs-log policy and library logging hygiene.
- [ ] Existing logging/`print` diagnostics migrated to the convention (T5).
- [ ] CONTEXT.md links both ADRs; contributor guidance exists (T6).
- [ ] `mypy src/` clean; `ruff check` clean; full `pytest` green.

---

### Out of Scope (Error Hierarchy & Logging section)

- Application-level observability: metrics, tracing, structured-event emission, log shipping.
- Changing `warnings.warn` semantics or removing existing user advisories.
- Async logging, custom handlers/formatters, or any sink configuration (application concern).
- Reworking `ValidationResult` / `ValidationIssue` (those are value-objects, not exceptions; a
  separate concern owned by validation epics).
- A blanket conversion of every builtin `TypeError`/`ValueError` to custom types — only
  *library-domain* errors migrate; honest builtin misuse stays builtin (per the ADR-011 boundary).
