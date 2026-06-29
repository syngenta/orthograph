# Epic E22: Cypher Validation — Backtick-Wrapped Parameter Detection

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness
> **Origin:** E20 T7; originally notebook review session 2026-06-16 (`notebooks/05.01_openapi_ergonomics_assessment.ipynb`). Extracted from E20 2026-06-30 for independent scheduling.
> **Relates to:** PRD Problem Statement ("applications fail silently"), ADR-018 (validation correctness), Epic E18 (Validation Correctness — already done).
> **Blocked by:** None — independent validation fix.

---

## Context

### Silent Validation Failure

A `cypher_template` that wraps a parameter in backticks — e.g. `` MATCH (m:Movie {released: `$released`}) `` — passes **every** validation layer Orthograph currently has, yet is **semantically wrong** in Cypher:

- A backtick-quoted token is an **escaped identifier**, not a parameter.
- The driver never binds `$released`; the query silently fails to filter or returns wrong results.
- This is exactly the "fail silently" failure mode the PRD exists to prevent.

### Why the Bug Exists

Verified empirically (graphglot 2026-06, neo4j dialect):

1. **`parse_cypher` accepts both forms.** The tokenizer reveals why:
   - `` `$released` `` lexes to a **single `VAR` token** `'$released'` (an escaped identifier literally named `$released`).
   - The correct `$released` lexes to two tokens: `DOLLAR_SIGN` + `VAR`.
   - Both produce **structurally identical lineage graphs** → definition-time parse cannot tell them apart.

2. **Alignment checker goes green.** The regex `_PARAM_PATTERN = r"\$([A-Za-z_][A-Za-z0-9_]*)"` matches `$released` **regardless of surrounding backticks** → the 1:1 field↔placeholder alignment check passes on the broken form.

3. **Only the driver catches the mistake.** The real DB returns wrong results — by which time the query is in production.

---

## Decision Surface

### Option 1: Lint in `_validate_declarative_cypher` (Recommended)

After extracting `$param` names via regex, scan the template for the pattern `` `\$NAME` `` (parameter wrapped in backticks) and raise `CypherQueryDefinitionError` with a fix hint:

```
CypherQueryDefinitionError: Parameter "$released" wrapped in backticks;
backtick-quoted tokens are escaped identifiers, not parameters. Remove the backticks.
```

**Pros:**
- Cheap, regex-only, no graphglot dependency.
- Catches the mistake at class-definition time.
- Guards every declarative query.

**Cons:**
- Does not fix the upstream graphglot tokenizer confusion (backlog item for graphglot maintainers).

### Option 2: Push Upstream to graphglot

Ask graphglot to expose recognised parameter bindings on the lineage graph (`lg.parameters` is currently `None`) so Orthograph can assert that each regex-extracted `$param` corresponds to a real parameter node, not a `VAR`.

**Pros:**
- More robust; eliminates the root cause.

**Cons:**
- Depends on external roadmap; longer time to fix.

### Option 3: Both (Recommended)

Ship the regex lint (option 1) **now** as a guard; file the graphglot feature request and track it as a follow-up for the principled fix once graphglot surfaces parameter lineage.

**Rationale:**
- Unblocks v0.1.0 (option 1 is small, self-contained).
- Leaves a clear path for the structural fix.

---

### Related Upstream Gap — `LIMIT $param` Does Not Parse

While fixing backtick templates in the §05.01 notebook, graphglot (neo4j dialect) was found to **reject a parameterised `LIMIT`**:

```cypher
RETURN m LIMIT $limit  -- ParseError: Expected parameter name or number after $
```

- `SKIP $skip` parses ✓
- `LIMIT $limit`, `LIMIT toInteger($limit)`, `SKIP $skip LIMIT $limit` all fail ✗
- Only literal `LIMIT 100` parses ✓

**Consequences:**

- A declarative paginated `CypherReadQuery` (natural use of `PaginatedParams`) **cannot be defined** — `_validate_declarative_cypher` raises at class-definition time.
- The gap also bites at **runtime**: `CypherExecutor.read` re-parses via `_validate_cypher`, so even imperative `build()` emitting `LIMIT $limit` raises on every request.

**Workaround:** The §05.01 notebook uses the **imperative `build()` escape hatch** (no `cypher_template`), inlining `skip`/`limit` as integer literals (`SKIP 0 LIMIT 100`), which graphglot parses. This is injection-safe because `PaginatedParams` validates them as bounded ints; the year filter stays a real `$released` parameter.

**Action:** File a graphglot issue for `LIMIT <parameter>` support and link it in the ADR. Document the imperative-`build()` workaround in the pagination guide until graphglot is fixed.

---

## Recommended Action (when picked up)

1. Implement **option 3** (regex lint now + graphglot request as a follow-up).
2. **E22.1:** Add a regex lint in `_validate_declarative_cypher` that detects `` `\$NAME` `` patterns and raises `CypherQueryDefinitionError` with an actionable message.
3. **E22.2:** Write regression tests covering:
   - ✓ Backtick-wrapped `$param` — **rejected** with message.
   - ✓ Clean `$param` — **accepted**.
   - ✓ Backtick-escaped label (e.g. `` (n:`My Label`) ``) — **not false-positive**.
   - ✓ `<<name>>` identifier placeholders — **not false-positive**.
4. **E22.3:** Verify `pytest` + `mypy src/` + `ruff check` green.
5. **E22.4:** File graphglot issue for `LIMIT <parameter>` support.
6. **E22.5:** Document the imperative-`build()` pagination workaround in the public guide.

---

## Acceptance Criteria

- [ ] A `cypher_template` containing `` `$param` `` raises `CypherQueryDefinitionError` at class-definition time with an actionable message.
- [ ] The lint does **not** false-positive on:
  - Legitimate backtick-escaped identifiers that are not parameters (e.g. `` (n:`My Label`) ``).
  - `<<name>>` identifier placeholders.
- [ ] Regression test covers:
  - ✓ Backtick-wrapped `$param` (rejected).
  - ✓ Clean `$param` (accepted).
  - ✓ Backtick-escaped label with no param (accepted).
- [ ] `pytest` + `mypy src/` + `ruff check` green.
- [ ] graphglot issue filed and linked in the epic.
- [ ] Pagination guide documents the `build()` workaround.

---

## Tasks (Ready to Delegate)

| Task | Scope | Model | Notes |
|------|-------|-------|-------|
| E22.1 | Implement regex lint | Sonnet | `_validate_declarative_cypher` in `base_models.py`; raise `CypherQueryDefinitionError` on `` `\$NAME` `` pattern |
| E22.2 | Write regression tests | Sonnet | Four cases: backtick-param rejected, clean param accepted, backtick-label not false-positive, `<<>>` not false-positive |
| E22.3 | Verify & green | Haiku | `pytest` + `mypy src/` + `ruff check` |
| E22.4 | File graphglot issue | Haiku | `LIMIT $param` not parsing in neo4j dialect; link to this epic |
| E22.5 | Document pagination workaround | Sonnet | Public guide: imperative `build()` with literal integers for `SKIP`/`LIMIT` |
