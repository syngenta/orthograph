# Epic E48: Configuration — Thread Tunable Knobs Through the Public API

> **Priority:** Medium
> **Origin:** E46.4 follow-up — `PropertyTypeMismatchRule.severity_threshold` (`comparison/rules.py:345`) is a per-instance field with no convenient override; survey 2026-06-24 found inspector knobs (`value_counts_top_n`, Neo4j `strategy`) are unreachable through `api.database.inspect`/`validate`.
> **Goal:** Make the existing tunable knobs reachable and overridable through the public API, with a single documented configuration approach — without introducing a global settings / file / env-var layer.
> **Blocked by:** the new-API epic (NOT YET CREATED — see "Sequencing" below). Reserve the config seam in the API epic now; build E48 against the API once it lands.
> **Decisions:** ADR-036 (this epic's E48.0 — the configuration approach; decided before any build) · ADR-035 §1 (minimal-knob bias — "no second sampling/bound knob") · ADR-009 (backend parity)
> **Rubric (every task judged against this):** minimal knobs (no speculative configurability) · no global settings object / file / env layer this phase · strongly-typed · backend-scoped (no vendor concept leaks into vendor-free `api/`) · additive & non-regressing (existing `rules=` injection keeps working) · honest defaults preserved (NetworkX scan-on `10`; DB scan-off `None`) · each task ends green with guardrails run

---

## Context

The project has **no configuration system** — no settings class, no env-var reading, no
defaults module (survey 2026-06-24). Tuning happens only through per-object constructor
arguments and a handful of module-level constants. This is deliberate: ADR-035 §1 resisted
even a *second* sampling knob. E48 does **not** change that bias — it makes the knobs that
already exist **reachable and overridable through the public API**, and records the one
approach in an ADR so future knobs follow it.

### Two real gaps the survey found

1. **No convenience to override one comparison-rule threshold.** All three engine
   functions and `api.database.validate` / `api.model.validate_query_catalogue_against_profile`
   already accept `rules: Sequence[Rule] | None`. A caller *can* inject
   `PropertyTypeMismatchRule(severity_threshold=0.10)` — but only by **rebuilding the whole
   `standard_rules()` list by hand** (`comparison/rules.py:1108`). There is no "standard rules,
   but tweak this one threshold" helper.

2. **Inspector knobs are unreachable through the public API.** `api.database.inspect`
   instantiates the inspector with **no arguments** — `inspector_cls()` (`api/database.py:38`,
   mirrored at `:54` in `validate`). `**backend_kwargs` is forwarded to the per-call
   `.inspect(...)` method, **not** to the inspector `__init__`. So `value_counts_top_n`
   (NetworkX `inspector.py:51`; Neo4j keyword-only `inspector.py:91`; Memgraph
   `inspector.py:76`) and the Neo4j `strategy` enum are **invisible to API consumers** —
   the whole opt-in value scan (E46) cannot be switched on through the public surface.

### Known tunable knobs (the inventory E48 governs — do not invent more)

| Knob | Location | Default | Controls |
|------|----------|---------|----------|
| `PropertyTypeMismatchRule.severity_threshold` | `comparison/rules.py:345` | `0.05` | off-type share cutoff: ≥ → ERROR (systematic drift), < → WARNING (dirty rows). ADR-035 §6 leaves the number unpinned. |
| `value_counts_top_n` (NetworkX) | `backends/networkx/inspector.py:51` (`VALUE_COUNTS_TOP_N = 10`, `:34`) | `10` (scan on) | value-scan opt-in + histogram truncation cap. |
| `value_counts_top_n` (Neo4j) | `backends/neo4j/inspector.py:91` (keyword-only) | `None` (scan off) | value-scan opt-in (E46). |
| `value_counts_top_n` (Memgraph) | `backends/memgraph/inspector.py:76` | `None` (scan off) | value-scan opt-in (E46). |
| Neo4j `strategy` | `backends/neo4j/inspector.py:91` (`Neo4jInspectionStrategy`) | `None` (auto) | APOC / SCHEMA / CYPHER detection (ADR-033). |

Candidate-but-deferred: `PropertyIncompleteRule`'s hardcoded `completeness < 1.0`
(`comparison/rules.py:299`). Out of scope unless the ADR decides otherwise — do not silently
make it configurable.

---

## Sequencing — config lands AFTER the new API; reserve the seam NOW

A **new public API is planned** but not yet an epic. Configuration is not free-standing:
every knob must attach to an API entry point (`inspect`/`compare`/`validate`). Building a
config layer against the *current* API surface (the one being replaced) means re-threading
it later — the rework trap. The dependency runs **API → configuration**, not the reverse.

Therefore:

1. **In the new-API epic (when it is written): add one constraint** — the new
   `inspect` / `compare` / `validate` entry points must be **config-ready**: reserve an
   explicit seam for knobs (options bag, kwargs, or builder — shape TBD by ADR-036) instead
   of repeating the `inspector_cls()`-with-no-args mistake (`api/database.py:38`). This is a
   one-line constraint on that epic, **not** a build task here.
2. **ADR-036 (E48.0)** is written **alongside or just after** the new-API decision, because
   "where knobs live and how they thread through the API" can only be pinned once the API's
   entry points exist. (E48.0 stays the first task *within* E48; it must not precede the API
   decision.)
3. **The E48 build tasks land after the new API**, threading the inventory knobs through the
   now-stable surface. No rework.

> **Do NOT start E48 build tasks (E48.1+) until the new-API epic exists and its entry-point
> shapes are settled.** E48.0 (the ADR) may begin once the API decision is in flight.

---

## Open Questions — RESOLVED by ADR-036 (E48.0)

E48.0 is decision-only and resolves these before any build task:

1. **Configuration shape.** How does a caller override a knob without rebuilding
   `standard_rules()` and without a global settings object? Options to weigh in the ADR
   (none pre-selected):
   - `standard_rules(type_mismatch_threshold=...)` gains optional kwargs returning the
     standard list with that rule reconfigured (smallest, most discoverable).
   - A typed options/config dataclass parameter on the new API's `compare`/`validate`
     (`options=ComparisonOptions(type_mismatch_threshold=...)`) threaded into rule
     construction.
   - Builder / per-call kwargs on the new API entry points.
   Decide one; record the rejected alternatives.

2. **Inspector-knob plumbing.** How do `value_counts_top_n` and Neo4j `strategy` reach the
   inspector through the new `inspect`/`validate` — given today's surface swallows them
   (`inspector_cls()`, `api/database.py:38`)? Must stay backend-scoped (no Neo4j
   `strategy` concept leaking into vendor-free `api/` typing — ADR-009 / ADR-011). Decide
   whether knobs are generic pass-through or a typed per-backend options object.

3. **Scope of the knob inventory.** Confirm the five knobs above are the complete public
   set for this phase; rule explicitly in/out on the `completeness < 1.0` candidate. Honour
   ADR-035 §1 (no new sampling/bound knobs invented).

4. **No global config this phase?** Confirm (and record the rationale for) *not* introducing
   a Settings object / config file / env-var layer now — per the project's minimal-knob bias
   and the API churn risk. If a future phase needs it, the ADR notes the seam.

---

## Decisions Already Made (do not re-litigate)

- **Config lands after the new API; the API epic reserves the seam.** (Sequencing above.)
- **ADR-036 first** — E48.0 is decision-only; no production code until the approach is
  recorded.
- **No global settings / file / env-var layer this phase** — confirmed direction; the ADR
  records the rationale, not a contrary design.
- **The threshold-override shape is decided in ADR-036**, not pre-chosen here.
- **The `rules=` injection seam stays.** Whatever convenience E48 adds is *additive* — the
  existing ability to pass a fully custom rule list to the engine / API must keep working
  unchanged.
- **Honest defaults are preserved** — NetworkX `value_counts_top_n=10` (scan on, reference
  baseline), DB inspectors `None` (scan off, cost-bearing opt-in per ADR-035 §1). E48 does
  not flip these defaults; it only makes them overridable.

---

## Existing Code to Reuse

| Need | Reuse | Location |
|------|-------|----------|
| The threshold to expose | `PropertyTypeMismatchRule.severity_threshold` | `comparison/rules.py:345` |
| The rule-list factory to extend with a convenience | `standard_rules()` | `comparison/rules.py:1108` |
| The engine seam already accepting custom rules | `compare_profile_to_definition` / `compare_profiles` / `compare_definitions` (`rules=` param) | `comparison/engine.py:173,210,225` |
| The API entry points that already accept `rules=` | `api.database.validate`; `api.model.validate_query_catalogue_against_profile` | `api/database.py:41`; `api/model.py:96` |
| The API gap to fix | `inspect` instantiates `inspector_cls()` with no args | `api/database.py:38,54` |
| Inspector `__init__` knob signatures | NetworkX / Neo4j / Memgraph | `backends/networkx/inspector.py:51`; `backends/neo4j/inspector.py:91`; `backends/memgraph/inspector.py:76` |
| Prior decision-only ADR precedent (format + rejected-alternatives discipline) | ADR-035 | `.agentic/decisions/035-observed-type-counts-population.md` |

---

## Per-Task Guardrails (apply to EVERY build task)

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

`tests/test_architecture.py` must stay green — no vendor concept (e.g. Neo4j
`strategy`) may leak into the vendor-free `api/` typing (ADR-009 / ADR-011). Existing
`rules=`-injection tests are a regression guard: the convenience is additive.

---

## Tasks (execute in order; each ends green)

### E48.0 — ADR-036: the configuration approach (decision-only)

> **Model: Opus.** Decision-only. Resolves the four Open Questions. No production code.
> May begin once the new-API decision is in flight; must not precede it.

**Goal:** `.agentic/decisions/036-configuration-approach.md` (Accepted) pins: the
threshold-override shape, inspector-knob plumbing through the new API, the closed knob
inventory, and the explicit *no global config this phase* stance with rationale. Records
rejected alternatives (global Settings object; file/env layer; per-knob ad-hoc params).

**Acceptance criteria:**
- [ ] ADR-036 exists, status Accepted, following the ADR format (Status / Category / Epic /
      Relates → Context → Decision (numbered) → Consequences → Rejected alternatives →
      Cross-references).
- [ ] Resolves Open Questions 1–4 unambiguously; each build task below can cite a specific
      ADR section.
- [ ] CONTEXT.md routing table gains a "How is the library configured?" row pointing at
      ADR-036.
- [ ] No production code.

---

### E48.1 — Comparison-rule threshold override (the convenience helper)

> **Blocked by:** E48.0 + the new-API entry points existing.

**Goal:** a caller can override `PropertyTypeMismatchRule.severity_threshold` (and any other
ADR-036-listed rule threshold) through the shape ADR-036 chose, without rebuilding
`standard_rules()` by hand and without breaking the existing `rules=` injection path.

**Operation:** implement exactly the shape ADR-036 §1 specifies (e.g. `standard_rules(...)`
kwargs, or a typed options object on the new API's `compare`/`validate`). Thread it to rule
construction. Do not change the `PROPERTY_TYPE_MISMATCH` code or the rule's logic (E46.4
already landed that).

**Tests (TDD — write first):**
- override propagates: a non-default threshold changes the WARNING/ERROR split for a known
  off-type share.
- default unchanged: omitting the override reproduces E46.4 behaviour byte-for-byte
  (regression guard).
- existing `rules=` injection still works untouched.

**Acceptance criteria:**
- [ ] Threshold overridable via the ADR-036 shape; default 0.05 preserved when unset.
- [ ] `rules=` injection path unchanged (regression test green).
- [ ] Guardrails green.

---

### E48.2 — Inspector knobs reachable through the new API

> **Blocked by:** E48.0 + the new-API `inspect`/`validate` entry points existing.

**Goal:** `value_counts_top_n` (all three backends) and Neo4j `strategy` are settable
through the new public `inspect` / `validate`, closing the `inspector_cls()`-no-args gap
(`api/database.py:38`). Backend-scoped: no Neo4j-specific type leaks into vendor-free `api/`.

**Operation:** thread the knobs per ADR-036 §2 (generic pass-through to inspector `__init__`,
or a typed per-backend options object). Preserve honest defaults (NetworkX `10`, DB `None`).

**Tests (TDD — write first):**
- `inspect` with `value_counts_top_n` set → the resulting `GraphProfile` has populated
  `value_distribution` / `observed_type_counts` (E46 scan ran).
- `inspect` without the knob → defaults preserved (DB: no scan; NetworkX: top-10).
- Neo4j `strategy` selectable through the API; vendor-free `api/` typing carries no
  `Neo4jInspectionStrategy` import (`tests/test_architecture.py` green).

**Acceptance criteria:**
- [ ] `value_counts_top_n` and Neo4j `strategy` reachable through the new API entry points.
- [ ] Defaults unchanged; backend isolation preserved (architecture test green).
- [ ] Guardrails green.

---

### E48.3 — Docs + close the loop

> **Model: Sonnet.** Documentation and bookkeeping; no behaviour change.

**Goal:** the documented configuration story matches the delivered approach.

**Operation:**
1. Document the configuration approach (the ADR-036 shape) wherever the public API is
   described (API docstrings / README / onboarding, per the new-API epic's doc surface).
2. Confirm CONTEXT.md's "How is the library configured?" row resolves to ADR-036 and the API.
3. Confirm no stale reference implies knobs are unreachable.

**Acceptance criteria:**
- [ ] Public-API docs show how to set a rule threshold and an inspector knob.
- [ ] CONTEXT.md routing accurate.
- [ ] Documentation-only; no production behaviour change.

---

## Coordination

- **New-API epic (not yet created):** hard prerequisite for E48.1/E48.2. Add the
  "config-ready entry points" constraint to that epic when it is written. E48.0 may run
  alongside the API decision.
- **E46 (done):** delivered `severity_threshold` (E46.4) and the inspector
  `value_counts_top_n` opt-in (E46.1/2/3) — the two knobs E48 exposes. E48 does not change
  their behaviour, only their reachability.
- **E1 (API Ergonomics, planned) / E18 (Validation Correctness):** if either reshapes the
  same API or `comparison/rules.py` surface, coordinate edits.

---

## Out of Scope

- A global Settings object, configuration file, or environment-variable layer (this phase —
  ADR-036 records the rationale; minimal-knob bias per ADR-035 §1).
- Inventing new tunable knobs beyond the five surveyed (no speculative configurability).
- Making `PropertyIncompleteRule`'s `completeness < 1.0` configurable unless ADR-036
  explicitly decides to include it.
- Changing any default value (NetworkX `10`, DB `None`, threshold `0.05`) — E48 exposes, it
  does not re-tune.
- Changing the `PROPERTY_TYPE_MISMATCH` code or any issue code (would need its own ADR).
- Building the new public API itself — that is the (separate) new-API epic; E48 only attaches
  configuration to it.
