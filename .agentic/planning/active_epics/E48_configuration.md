# Epic E48: Configuration — Thread Tunable Knobs Through the Public API

> **Priority:** Medium
> **Origin:** E46.4 follow-up — `PropertyTypeMismatchRule.severity_threshold` (`comparison/rules.py:345`) is a per-instance field with no convenient override; survey 2026-06-24 found inspector knobs (`value_counts_top_n`, Neo4j `strategy`) were unreachable through the old `api.database.inspect`/`validate`. **Re-pathed 2026-06-28:** E55 shipped the new API as root-level modules — `profile.inspect_networkx/_neo4j/_memgraph` already expose `value_counts_top_n` and Neo4j `strategy` as typed per-backend keyword args (the old `api/database.py:38` no-arg gap is gone). E48's remaining scope narrows to: (a) the comparison-rule threshold convenience, and (b) deciding whether to fold the now-exposed inspector keywords into a **config object** rather than loose kwargs.
> **Goal:** Make the tunable knobs conveniently overridable through the public API with a single documented configuration approach — without introducing a global settings / file / env-var layer.
> **Blocked by:** ~~the new-API epic~~ **UNBLOCKED** — E55 (root-level capability modules) is **done** (2026-06-26). E48.0 (ADR-036) may begin now; build tasks attach to the shipped `profile.*` / `compare.*` / `queries.*` surface.
> **Decisions:** ADR-036 (this epic's E48.0 — the configuration approach; decided before any build) · ADR-035 §1 (minimal-knob bias — "no second sampling/bound knob") · ADR-009 (backend parity) · ADR-040/041 (the root-module API the knobs attach to)
> **Rubric (every task judged against this):** minimal knobs (no speculative configurability) · no global settings object / file / env layer this phase · strongly-typed · backend-scoped (no vendor concept leaks into vendor-free public modules) · additive & non-regressing (existing `rules=` injection keeps working) · honest defaults preserved (NetworkX scan-on `10`; DB scan-off `None`) · **config object only if it removes net complexity, not for its own sake** · each task ends green with guardrails run

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

2. **Inspector knobs: now exposed per-backend, but not as a config object.** Under the old
   `api.database.inspect` the inspector was built with **no arguments** (`inspector_cls()`),
   swallowing the knobs. **E55 fixed reachability:** `profile.inspect_neo4j(driver, *, strategy=,
   value_counts_top_n=, ...)`, `inspect_memgraph(...)`, and `inspect_networkx(...)` now take the
   knobs as typed, documented keyword args, routed via `loader.run_inspection` into the inspector
   constructor. **The remaining E48 question is ergonomic, not reachability:** as more knobs are
   added, do we keep loose keywords or fold them into a typed per-backend **options/config
   object** passed once? (See "Underlying prep" above — gated.)

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

### Underlying prep — per-backend internal options consolidation (gated; from E56 review 2026-06-28)

The three inspectors each store the knobs as **loose private fields** (`self._value_counts_top_n`
on all three; Neo4j additionally `self._strategy` plus the `use_apoc` deprecation translation in
`__init__`). When E48 threads a **config object** through the public surface (the idea: pass one
options object rather than repeating keywords), the natural internal landing is a small **frozen
per-backend options dataclass** held as `self._config`, replacing the loose fields.

| # | Place | Today | Internal prep |
|---|-------|-------|---------------|
| P1 | `backends/neo4j/inspector.py.__init__` | `self._strategy`, `self._value_counts_top_n` (+ `use_apoc`→strategy) | collapse into one frozen `_Neo4jInspectionConfig` field |
| P2 | `backends/memgraph/inspector.py.__init__` | `self._value_counts_top_n` | same shape (parity with neo4j) |
| P3 | `backends/networkx/inspector.py.__init__` | `self._value_counts_top_n` (default 10) | same shape |

**Explicitly gated — do NOT do this prep yet.** With only 1–2 knobs per backend, the dataclass
**adds** more than it deletes, so it fails the "no abstraction unless it removes net complexity"
rubric (ADR-042 §2). It also collides with **E56.3** (the inspector-helper hoist that edits the
same `__init__`s). **Start P1–P3 only when the threshold is crossed:** E56.3 has landed **and**
either a third per-backend knob appears **or** E48.2's config-object shape (ADR-036 §2) is fixed
and needs an internal home. Run it as the **first build step of E48.2**, after E56.3, never before.
Public `__init__` signatures stay unchanged by the prep itself; only E48.2 changes the surface.

---

## Sequencing — the new API has shipped; config now attaches to it

The new public API (E55, root-level modules) is **done**. Configuration was always
**API → configuration**: knobs attach to entry points. Those entry points now exist
(`profile.inspect_*`, `compare.*`, `queries.validate_*`), and the inspector knobs are
**already reachable** through `profile.inspect_*` (E55). So:

1. **The "reserve a config-ready seam" constraint is satisfied** — `profile.inspect_*` already
   take typed per-backend keyword args; no `inspector_cls()`-no-args mistake remains.
2. **ADR-036 (E48.0)** is now **unblocked** and decides the *ergonomic* shape: keep loose
   keywords vs a typed per-backend options/config object, and the threshold-override shape — all
   against the concrete, shipped entry points.
3. **The E48 build tasks attach to the shipped surface.** No new-API rework trap remains.

> **Earlier ordering note retired:** E48 is no longer gated on an unwritten API epic. ADR-036
> may start immediately; build tasks follow it.

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

2. **Inspector-knob ergonomics.** `value_counts_top_n` and Neo4j `strategy` already reach the
   inspector through `profile.inspect_*` (E55, typed per-backend keyword args). The open
   question is whether to **fold them into a typed per-backend options/config object** (passed
   once) as the knob set grows, or keep loose keywords. Must stay backend-scoped (no Neo4j
   `strategy` concept leaking into a vendor-free module — ADR-009 / ADR-011). If a config object
   is chosen, sequence the internal `_config` consolidation prep (P1–P3 above) as the first build
   step — and only because it then removes net complexity.

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
| The public entry points that already accept `rules=` | `compare.profile_to_definition` (+ `profiles`/`definitions`); `queries.validate_catalogue_against_profile` | `src/orthograph/compare.py`; `src/orthograph/queries.py` |
| The inspector knobs already exposed (E55) | `profile.inspect_neo4j/_memgraph/_networkx` keyword args | `src/orthograph/profile.py` |
| Inspector `__init__` knob signatures | NetworkX / Neo4j / Memgraph | `backends/networkx/inspector.py`; `backends/neo4j/inspector.py`; `backends/memgraph/inspector.py` |
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
> Unblocked now that E55 has shipped the entry points.

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

> **Blocked by:** E48.0. (Entry points exist — E55 shipped `compare.*` / `queries.*`.)

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

### E48.2 — Inspector-knob ergonomics (config object vs loose keywords)

> **Blocked by:** E48.0. The knobs are **already reachable** via `profile.inspect_*` (E55) — this
> task is about ergonomics, not reachability.

**Goal:** decide and (if ADR-036 chooses the config object) deliver a typed per-backend options
object so callers pass one object instead of repeating keywords, **without** changing defaults or
leaking a vendor type into a vendor-free module. If ADR-036 keeps loose keywords, this task is a
no-op confirmation + docs.

**Operation:** per ADR-036 §2. If a config object is chosen, **first** run the internal P1–P3
`_config` consolidation (after E56.3), then expose the object on `profile.inspect_*`. Preserve
honest defaults (NetworkX `10`, DB `None`).

**Tests (TDD — write first):**
- `inspect_*` with the knob/object set → the resulting `GraphProfile` has populated
  `value_distribution` / `observed_type_counts` (E46 scan ran).
- `inspect_*` without it → defaults preserved (DB: no scan; NetworkX: top-10).
- Neo4j `strategy` selectable; no `Neo4jInspectionStrategy` import in a vendor-free module
  (`tests/test_architecture.py` green).

**Acceptance criteria:**
- [ ] The chosen ergonomic shape (object or keywords) is delivered on `profile.inspect_*`.
- [ ] Defaults unchanged; backend isolation preserved (architecture test green).
- [ ] Guardrails green.

---

### E48.3 — Docs + close the loop

> **Model: Sonnet.** Documentation and bookkeeping; no behaviour change.

**Goal:** the documented configuration story matches the delivered approach.

**Operation:**
1. Document the configuration approach (the ADR-036 shape) wherever the public API is
   described (the root-module docstrings / README / onboarding).
2. Confirm CONTEXT.md's "How is the library configured?" row resolves to ADR-036 and the API.
3. Confirm no stale reference implies knobs are unreachable.

**Acceptance criteria:**
- [ ] Public-API docs show how to set a rule threshold and an inspector knob.
- [ ] CONTEXT.md routing accurate.
- [ ] Documentation-only; no production behaviour change.

---

## Coordination

- **E55 (new API, done 2026-06-26):** shipped the root-level `profile.*` / `compare.*` /
  `queries.*` entry points and already exposes the inspector knobs as typed keyword args.
  E48 attaches the configuration ergonomics to this surface — no longer a prerequisite gap.
- **E56 (readability distillation):** E56.3 edits the inspector `__init__`s. The P1–P3
  `_config` consolidation prep (above) must run **after** E56.3 to avoid collisions.
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
- Building the new public API itself — that shipped in E55; E48 only attaches configuration
  to it.
