# Epic E21: `from __future__ import annotations` — Normalise Across Codebase

> **Priority:** Low
> **Phase:** v0.1.0 — Pilot Readiness
> **Origin:** E20 T0; originally E8.1 session 2026-06-11. Extracted from E20 2026-06-30 for independent scheduling.
> **Blocked by:** None — independent cosmetic task.

---

## Context

The import `from __future__ import annotations` is used inconsistently across the project:

- **8 source files** and **7 test files** carry it (all in `gqlalchemy/`, `networkx/`, and `cypher/exceptions`).
- **Primary mirror target** `cypher/base_models.py` does **not** have it.
- Only **one file strictly requires it**: `cypher/exceptions.py` imports `ValidationIssue` under `TYPE_CHECKING`; without deferred evaluation, that name would fail at runtime.
- All other files compile and run fine on **py3.10+** without it (PEP 604 `X | Y` unions evaluate at runtime since py3.10; no forward-reference annotations found).
- The **ruff ruleset** (`E,W,F,I`) does not include `UP010` (unnecessary `__future__` import), so tooling neither enforces nor forbids the import.

This is **purely a cosmetic consistency issue** — no runtime correctness impact.

---

## Decision Surface

Three coherent positions:

1. **Remove everywhere except `cypher/exceptions.py`**
   - Matches the `cypher/base_models.py` precedent.
   - Rely on py3.10 runtime union support.
   - Enable `ruff UP010` to enforce going forward.
   - Rationale: **minimalist** — import only where required.

2. **Add everywhere**
   - Consistent with the majority of `gqlalchemy/` files.
   - Costs nothing on py3.10+.
   - Rationale: **uniform** — every module declares its intent to use PEP 563 deferred evaluation.

3. **Leave as-is**
   - Do nothing; inconsistency is a cosmetic annoyance but causes no failures.
   - Rationale: **defer** — not blocking, low priority, re-evaluate when related work lands.

---

## Recommended Action (when picked up)

1. **Decide** option 1, 2, or 3 and **record the rationale** in this epic's decision section.
2. **If option 1:**
   - Run `sed` / `ruff check --fix` to strip the import from all files except `cypher/exceptions.py`.
   - Enable `ruff UP010`: add `"UP010"` to `select` in `pyproject.toml`.
3. **If option 2:**
   - Add the import to the remaining files without it (run `ruff check --fix` if a rule exists).
4. **Verify:** `pytest` + `mypy src/` + `ruff check` all green before closing.

---

## Acceptance Criteria

- [ ] Decision recorded (option 1/2/3) with rationale in the Decision section below.
- [ ] If option 1 or 2: all files consistent; ruff clean; `pytest` + `mypy src/` green.
- [ ] `cypher/exceptions.py` retains the import regardless of chosen option.
- [ ] No test failures or type-checking regressions.

---

## Decision

**To be recorded when task is picked up.**

---

## Tasks (Ready to Delegate)

| Task | Scope | Model | Notes |
|------|-------|-------|-------|
| E21.1 | Audit & decide | — | Review the three options; record decision rationale in this epic; may require brief team discussion on preference |
| E21.2 | Apply fix | — | Implement chosen option (strip, add, or defer); run tooling |
| E21.3 | Verify | — | `pytest` + `mypy src/` + `ruff check` green; no regressions |
