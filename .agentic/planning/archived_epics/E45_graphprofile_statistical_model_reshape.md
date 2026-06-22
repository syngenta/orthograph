# Epic E45: GraphProfile Statistical Model & Comparison-Contract Reshape

> **Priority:** High (blocks E41 — the partitioned-cardinality field must land on the reshaped model, not be reshaped afterwards)
> **Phase:** v0.1.0 / pre-pilot
> **Blocks:** E41 (Conditional Cardinality — Profiling)
> **Type:** Reshape (breaking changes permitted — no external consumers yet) + shared model + comparison rules + 3-backend parity
> **Decisions:** ADR-034 (read it first — it is the spec) · ADR-015 (declared/observed mirror) · ADR-009 (inspector parity) · ADR-033 (strategy-driven field availability) · ADR-017 (topology)
> **Rubric (every task judged against this):** strongly-typed · SOLID · readability over cleverness · backend parity is mandatory · `None` is honest (never a silent wrong verdict) · each task ends green with guardrails run

---

## Why This Epic Exists

`GraphProfile` is the **observed currency**: a point-in-time snapshot whose only
purpose is to be **compared** against a `GraphDefinition` or another
`GraphProfile`. Capturing the E41 requirements surfaced three structural gaps in
the model that are cheaper to fix **before** E41 ships `partitioned_cardinality`
and freezes its shape:

1. **Presence is conflated.** `PropertyProfile.is_required` names a *statistic*
   ("data is 100% present") as if it were a *contract*. The declared contract, a
   DB **constraint** that guarantees presence, and the observed completeness are
   three different sources — and the constraint is not even linked to the
   property today.
2. **Statistics aren't honest about truncation.** Bounded value/degree
   distributions have no "I hit the sampling limit" signal.
3. **Repeated statistical shapes.** Cardinality stats and property-value
   distributions are the same idea — a *bounded summary with a truncation signal* —
   and the requirement is explicit: **share the data models.**

Because there are **no external consumers yet**, this epic is allowed to make
**breaking** changes. E41 then lands its partitioned cardinality directly in the
reshaped form. See ADR-034 for the full model and the comparison matrix.

---

## Decisions Already Made (do not re-litigate — see ADR-034)

- Comparison is **field-level**, never byte-level; any hashing is a
  *comparison-function* concern, never baked into the model.
- Field availability is **backend/strategy-dependent**; `None` is first-class and
  yields `*_UNVERIFIABLE` (INFO), never a false verdict (ADR-033).
- One shared **`BoundedDistribution`** (moments `count/min/max/mean/variance`,
  optional `skewness/kurtosis`, optional `histogram` placeholder,
  `sample_complete/limit/other_count`) is reused for property-value distributions
  **and** cardinality-degree distributions. `CardinalityStats` is re-expressed on it.
- `PropertyProfile` carries **three presence signals**: observed `completeness`
  (computed), `constraint_required: bool | None`, and the declared side stays on
  `TypeInfo`. `is_required` is **removed** from `PropertyProfile`.
- **`completeness` counts non-null values** (explicit `null` = not present).
- **Total count is diff-only** — excluded from profile↔description.
- Relationship: **always** the simple label↔label degree summary; **partitioned**
  (label + properties) only for declared-conditional types (E41 gating, unchanged).
- The **full comparison matrix** (ADR-034 §8) is the contract; E45 implements the
  node/property/constraint/value rows, E41 implements the cardinality rows.

---

## Existing Code to Reuse / Touch

| Need | Reuse / Touch | Location |
|------|---------------|----------|
| Profile models | `PropertyProfile`, `CardinalityStats`, `NodeTypeProfile`, `RelationshipTypeProfile`, `GraphProfile`, `ConstraintInfo` | `graph_profile/models.py` |
| Inspection assembly | `_finish_relationship_profile`, property assembly | `graph_profile/inspection.py` |
| NetworkX reference inspector | `_inspect_relationships`, `_compute_cardinality`, property counting | `backends/networkx/inspector.py` |
| Neo4j strategies / constraints | catalogue builders, constraint reads | `backends/neo4j/queries.py`, `backends/neo4j/inspector.py` (ADR-033) |
| Memgraph inspector | constraint + cardinality subclasses | `backends/memgraph/*` |
| Comparison rules | `PropertyIncompleteRule`, `CardinalityViolationRule`, `PropertyTypeMismatchRule`, `PropertyDistinctCountRule`, `standard_rules` | `comparison/rules.py` |
| Profile↔profile diff | `diff_rules`, `compare_profiles` | `comparison/diff_rules.py`, `comparison/engine.py` |
| Declared presence/enum | `TypeInfo.is_required`, declared enum source | `graph_definition/property_spec.py`, `graph_definition/models.py` |
| Rendering | profile text rendering | `visualization/text.py` |

---

## Per-Task Guardrails (apply to EVERY task unless stated)

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

Live-DB tests are opt-in (`--neo4j` / `--memgraph`); default-suite tests use
mocked drivers / `FakeGraphSession` and the in-memory NetworkX backend. Reshaped
models must round-trip through `model_dump`/`model_validate`.

---

## Tasks (execute in order; each ends green)

### E45.1 — Shared `BoundedDistribution`; re-express `CardinalityStats` on it

> **Model: Opus.** Establishes the shared statistical primitive every downstream task depends on; the moment/truncation contract must be obviously correct.

**Goal:** one frozen statistical-summary model exists and `CardinalityStats` is a
specialisation/consumer of it, with the truncation signal in place.

**Operation** — in `src/orthograph/graph_profile/models.py`:
1. Add `BoundedDistribution` per ADR-034 §3 (moments `count/min/max/mean/variance`;
   optional `skewness/kurtosis`; optional `histogram: dict[str,int] | None`;
   `sample_complete: bool = True`, `limit: int | None = None`, `other_count: int = 0`).
   Provide a `std` computed property (from `variance`) returning `None` when absent.
2. Re-express `CardinalityStats` on `BoundedDistribution` (today's
   `min_degree`/`max_degree`/`avg_degree`/`sample_size` → `min`/`max`/`mean`/`count`,
   gaining `variance`). Update the NetworkX `_compute_cardinality` shape to emit it.

**Tests (TDD — write first)** — `tests/graph_profile/test_models.py`:
- a complete distribution round-trips; moments read back equal.
- a truncated distribution (`sample_complete=False`, `limit` set, `other_count>0`)
  round-trips and reports truncation.
- `std` derives from `variance`; `None` when `variance is None`.

**Care / risks:** this is breaking — every constructor of `CardinalityStats`
(inspectors + tests) updates in this task or its dependants. Keep moments
`None`-tolerant for backends that supply only `min/max`.

---

### E45.2 — `PropertyProfile` presence-source split + constraint cross-reference (3-backend parity)

> **Model: Opus.** The declared/observed/constraint separation and the inspector wiring that links flat constraints onto properties; parity-gated.

**Goal:** `PropertyProfile` exposes observed completeness (non-null) **and**
`constraint_required`, populated consistently across NetworkX/Neo4j/Memgraph.

**Operation:**
1. In `graph_profile/models.py`: `present_count` counts **non-null** (ADR-034 §5);
   **remove `is_required`** from `PropertyProfile`; add
   `constraint_required: bool | None = None`. Keep `completeness` computed.
2. In each inspector (`backends/{networkx,neo4j,memgraph}`): when assembling
   `property_profiles`, cross-reference `GraphProfile.constraints` (existence/presence
   constraints) → set `constraint_required=True/False`; leave `None` when the
   strategy cannot read constraints (ADR-033 — e.g. pure-Cypher fallback).
   NetworkX (no DB constraints) sets `None` unless the input carries them.
3. Non-null counting: explicit `null` values do not increment `present_count`.

**Tests (TDD — write first)** — `tests/graph_profile/test_models.py`,
`tests/backends/{networkx,neo4j,memgraph}/test_inspector.py` (mocked):
- a property with a covering existence constraint → `constraint_required=True`.
- inspected, no such constraint → `False`.
- strategy without constraint info → `None`.
- a property set to `null` on some entities → `completeness` reflects non-null only.
- parity: same logical graph → equivalent `constraint_required`/`completeness` across backends.

**Care / risks:** removing `is_required` breaks `comparison/rules.py` and
`visualization/text.py` — they are repointed in E45.4/E45.5. Honour ADR-033
strategy variance for `None`; never invent `False` when the source is silent.

**Outcome (E45.2 landed — decisions recorded for ADR-034 §8):**
- **Constraint cross-referencing is mandatory-all-backends, not best-effort.**
  This settles the ADR-034 §8 open sub-decision *"whether constraint
  cross-referencing is mandatory-all-backends or best-effort."* Each backend
  cross-references constraints onto every property; `None` is reserved for
  genuinely silent sources (NetworkX, which has no constraint channel), never a
  fabricated `False` (ADR-033 honesty). "Parity" = ADR-009 *"each backend honest
  per its strategy"*, **not** value-identity across backends. *(Fold this line
  into ADR-034 §8 in E45.5's planning-hygiene step.)*
- **Presence-guaranteeing constraint types** (shared vendor-free helper
  `graph_profile/constraints.py::is_presence_constraint_for`): Neo4j
  `NODE_PROPERTY_EXISTENCE` / `RELATIONSHIP_PROPERTY_EXISTENCE` / `NODE_KEY` /
  `RELATIONSHIP_KEY`; Memgraph `EXISTS`. `UNIQUENESS` / `UNIQUE` alone does **not**
  guarantee presence. Entity-type comparison is case-insensitive; label match is
  `label in constraint.labels`. `property_type` and label-*combination*
  constraints are intentionally ignored (no current backend emits them — revisit
  only if a multi-label existence-constraint backend appears).
- **I/O ordering changed (Neo4j + Memgraph):** constraints are now read **before**
  building property profiles (so each profile can be cross-referenced). Inspector
  test mocks were reordered to match.
- **Repoint done in E45.2 (minimal, not the full rework):** `rules.py`
  `PropertyIncompleteRule` reads `completeness < 1.0`; `text.py` reads
  `completeness == 1.0`. Behaviour-equivalent to the old `is_required`, including
  the `total_count == 0` edge case. The full presence/enum rule work stays in E45.4/E45.5.

---


### E45.3 — Bounded value/type distribution on `PropertyProfile`

> **Model: Opus.** Bounded sampling with a configurable top-N and honest truncation; the value/type alignment that feeds enum comparison.

**Goal:** `PropertyProfile.value_distribution: BoundedDistribution | None` carries a
bounded value (and type) breakdown with a truncation signal, controlled per
inspection.

**Operation:**
1. Add `value_distribution: BoundedDistribution | None = None` to `PropertyProfile`.
   The `histogram` holds observed value → count; type breakdown is preserved
   alongside (reuse existing `observed_type_counts` semantics, aligned into the
   distribution model per ADR-034 §3/§4).
2. Inspection gains a per-call parameter `value_counts_top_n: int | None`
   (default a module constant, e.g. 10; `None`/0 disables). When the distinct
   values exceed `top_n`, keep the top-N, set `sample_complete=False`, `limit=top_n`,
   and accumulate the remainder into `other_count`.
3. Implement in NetworkX reference first, then Neo4j + Memgraph (parity). Where a
   backend cannot supply value counts, `value_distribution=None`.

**Tests (TDD — write first)** — model + 3 inspector test files:
- low-cardinality property → full `histogram`, `sample_complete=True`.
- high-cardinality property with `top_n` → top-N kept, `sample_complete=False`,
  `other_count` = remainder.
- backend without value counts → `value_distribution is None`.
- parity across backends for the same logical graph.

**Care / risks:** must be bounded (UID/free-text columns must not explode the
profile). Truncation must be explicit — never silently drop values. `top_n`
defaulting and the disable path both tested.

---

### E45.4 — Comparison rules: presence (3 sources), enum/value, total-count diff-only

> **Model: Opus.** The cross-layer reconciliation implementing the node/property/constraint/value rows of the ADR-034 matrix, with correct severity discipline.

**Goal:** `compare_profile_to_definition` and `compare_profiles` implement the
ADR-034 §8 matrix for the non-cardinality rows; total count is diff-only.

**Operation** — in `comparison/rules.py` (and `diff_rules.py`):
1. **Declared-required vs occurrence**: replace `PropertyIncompleteRule`'s reliance
   on `prop_profile.is_required` with `completeness < 1.0` while declared-required.
   Severity per the resolved sub-decision (default WARNING; record in ADR-034).
2. **Declared-required vs constraint** (new rule): declared-required &
   `constraint_required is False` → "declared required, no DB constraint"
   (WARNING/INFO); observed `constraint_required is True` & not declared-required →
   "DB constraint not declared" (INFO); `constraint_required is None` →
   `*_UNVERIFIABLE` (INFO).
3. **Enum/value** (new or extended rule): when the declared property is an enum,
   compare `value_distribution` keys — observed value ∉ declared ⇒ undeclared-value
   signal; declared value never observed ⇒ INFO. `None` distribution ⇒ unverifiable.
4. **Total count diff-only**: ensure no rule reads `count` against the description;
   add/confirm a `diff_rules` count-delta (INFO) for profile↔profile.

**Tests (TDD — write first)** — `tests/comparison/test_rules.py`,
`tests/comparison/test_diff_rules.py`:
- declared-required + `completeness<1` → incomplete finding (correct severity).
- declared-required + `constraint_required False/None/True` → the three outcomes.
- declared enum + observed undeclared value → undeclared-value finding.
- count never produces a description finding; profile↔profile emits a count delta.
- regression: existing type-mismatch / presence codes unchanged.

**Care / risks:** severity discipline (data-violates-contract vs drift vs
unverifiable). `None` everywhere ⇒ unverifiable, never false verdict. Do not break
existing `standard_rules` codes other than the intended `is_required` repointing.

**Outcome (E45.4 landed — severities settled, folded into ADR-034 §8):**
- **New rules in `comparison/rules.py`** (both added to `standard_rules()`, which
  now returns **12** rules): `PropertyConstraintPresenceRule`
  (`property.constraint_presence`) and `PropertyEnumValueRule`
  (`property.enum_value`).
- **Declared-vs-occurrence** stays `PROPERTY_INCOMPLETE` (**WARNING**); the
  E45.2 `completeness < 1.0` repoint is the final form (no further change).
- **Declared-vs-constraint** (3 outcomes): declared-required & `False` →
  `PROPERTY_UNCONSTRAINED` (**WARNING**); `True` & not declared-required →
  `UNDECLARED_CONSTRAINT` (**INFO**); declared-required & `None` →
  `CONSTRAINT_UNVERIFIABLE` (**INFO**). declared-required & `True` is silent.
- **Enum/value**: rule fires only when the declared `python_type` is an
  `enum.Enum`; compares `str(member.value)` against `value_distribution.histogram`
  keys. observed ∉ declared → `UNDECLARED_PROPERTY_VALUE` (**WARNING**); declared
  never observed → `UNOBSERVED_PROPERTY_VALUE` (**INFO**); distribution/histogram
  `None` → `PROPERTY_VALUE_UNVERIFIABLE` (**INFO**).
- **Total count is diff-only**: no satisfaction rule reads `count`; a new
  `CountChangedRule` (`diff.count_changed`, **INFO**) emits `COUNT_CHANGED` on
  node-label / rel-type addresses in profile↔profile only. `diff_rules()` now
  returns **10** rules. A regression test asserts no `COUNT_*` code ever appears
  in `compare_profile_to_definition`.
- **Behaviour change captured in tests:** `test_case_b_extension_via_injection`
  now also sees one `CONSTRAINT_UNVERIFIABLE` (the declared-required `Person.name`
  carries `constraint_required=None`), correct per ADR-034 §8 — its hard total was
  updated 2 → 3.
- **ADR-034 §8 sub-decisions folded** (the "Open severity sub-decisions" block now
  records all of the above). E45.5's planning-hygiene step need only confirm the
  cross-links, not re-decide.

---

### E45.5 — Serialisation/versioning contract, rendering, CONTEXT/overview, re-base E41

> **Model: Sonnet.** Contract documentation, rendering update, planning hygiene, and the E41 re-base.

**Operation:**
1. **Serialisation contract**: add round-trip tests for the full reshaped
   `GraphProfile` (incl. `BoundedDistribution`, `value_distribution`,
   `constraint_required`); document the versioning-comparison contract (which
   fields `compare_profiles` reads) in a short note or in ADR-034 cross-link.
2. **Rendering** (`visualization/text.py`): render observed **presence ratio**
   (not "mandatory"); show `constraint_required` when not `None`; render value
   distributions compactly with a truncation marker when `sample_complete=False`;
   handle every `None` field without change.
3. **Planning hygiene**: confirm ADR-034 cross-links; mark E45 in
   `.agentic/planning/overview.md` and order E45 → E41; add a CONTEXT.md row for the
   profile statistical model. Re-base E41.1 onto the reshaped model (E41 amended in
   its own file).
4. **Fold settled sub-decisions into ADR-034 §8**: record the
   constraint-cross-referencing resolution from E45.2's *Outcome* block
   (mandatory-all-backends; `None` reserved for silent sources) plus the
   declared-vs-occurrence / declared-vs-constraint severities settled in E45.4.

**Tests / verify:**
```
pwsh> python -m pytest -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

**Care / risks:** rendering must tolerate all-`None` (most properties have no
constraint/value distribution). Keep notebooks/tests deterministic.

---

## Success Criteria

- [ ] `BoundedDistribution` exists and is reused by `CardinalityStats`; truncation
      signal round-trips; moments `None`-tolerant.
- [ ] `PropertyProfile` exposes `completeness` (non-null) and
      `constraint_required: bool | None`; `is_required` removed; 3-backend parity;
      `None` honours ADR-033 strategy variance.
- [ ] Bounded `value_distribution` with configurable `top_n` + `other_count` +
      `sample_complete`; 3-backend parity; bounded on high-cardinality properties.
- [ ] Comparison implements the ADR-034 §8 non-cardinality rows: declared-vs-occurrence,
      declared-vs-constraint (3 outcomes), enum/value; total count is diff-only.
- [ ] Full `GraphProfile` round-trips; rendering shows observed ratio + constraint +
      bounded distributions; full suite + mypy + pre-commit green.
- [ ] E41 re-based onto the reshaped model; overview ordered E45 → E41; CONTEXT row added.

---

## Out of Scope

- Cardinality comparison rows of the matrix (ADR-034 §8) — implemented in **E41.5**.
- Partitioned cardinality computation/queries — **E41** (lands on this reshaped model).
- Historical / trend storage of any statistic (monitoring-platform concern — PRD out-of-scope).
- Hashing / quick-compare shortcuts (a future comparison-function optimisation, not a model field — ADR-034 §1).
- Property value *constraints* (min/max/regex) — still deferred; this epic profiles values, it does not constrain them.
