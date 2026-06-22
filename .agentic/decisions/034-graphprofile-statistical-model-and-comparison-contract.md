# ADR-034: GraphProfile Statistical Model & Comparison Contract

**Status:** Accepted — 2026-06-22
**Category:** core
**Epic:** E45 (GraphProfile statistical-model reshape) — runs before E41
**Amends:** ADR-030 §1 (the observed per-pair field now sits on the shared distribution model)
**Relates:** ADR-015 (declared/observed mirror), ADR-009 (inspector parity),
ADR-033 (Neo4j three-way strategy — drives field availability), ADR-017 (package topology),
ADR-027/ADR-031 (cardinality notation)

---

## Context

`GraphProfile` is the **observed currency**: a point-in-time snapshot produced by
inspection, whose only purpose is to be **compared** — against a `GraphDefinition`
(declared contract) or against another `GraphProfile` (drift between two
snapshots, e.g. staging vs production). It is **not** a monitoring artefact
(PRD constraint #6): no history, no trend, no scheduling.

E41/ADR-030 was scoped to extend the **frozen** profile *additively* with an
optional `partitioned_cardinality` field. While capturing the requirements for
that work we found three structural gaps that are cheaper to fix **now**, before
`partitioned_cardinality` ships and its shape becomes a compatibility surface:

1. **Presence is conflated.** `PropertyProfile.is_required` means "the data
   happens to be 100% present", but reads like a *contract*. The declared
   contract (`TypeInfo.is_required`) and a **database constraint** that
   *guarantees* presence are three different sources wearing one name. Worse, a
   DB constraint is not linked to the property at all (constraints live in a flat
   `GraphProfile.constraints` list), so "is this declared-required property
   actually backed by a DB constraint?" cannot be asked.

2. **Statistics are not honest about truncation.** Property value distributions
   are bounded in practice but the model has no way to say "I sampled up to a
   limit and there may be more". The same will be true of any future
   degree-distribution detail.

3. **Repeated statistical shapes.** Cardinality stats and (future) property-value
   distributions are the same idea — a *bounded statistical summary with a
   truncation signal* — expressed twice. The requirement is explicit: **share the
   data models.**

Because there are **no external consumers yet**, E45 is permitted to make
**breaking** changes to the profile models (not merely additive). This ADR
records the reshaped model and, critically, **the full comparison contract** —
what each field contributes to profile↔description and profile↔profile.

---

## Decision

### 1. Comparison is field-level analysis, never byte-level

A profile is meaningful only inside a comparison. Comparison reads **fields** and
reasons about them; it does **not** compare serialised blobs. Any hashing /
quick-compare shortcut is a concern of the **comparing function** (it may derive a
hash from selected fields), **never** a property baked into the profile model.
The model's job is to carry well-structured, individually-interpretable fields.

### 2. Field availability is backend- and strategy-dependent — `None` is first-class

Which fields a profile can populate depends on the backend (Neo4j / Memgraph /
NetworkX) **and** the retrieval machinery (APOC / `db.schema.*` / pure-Cypher —
ADR-033). Every statistical or constraint-derived field therefore distinguishes:

- **measured value** (the backend supplied it), versus
- **`None` / absent** (this backend+strategy could not measure it).

`None` is **never** conflated with zero/false. A `None` field that a comparison
would otherwise check yields an `*_UNVERIFIABLE` (INFO) finding — never a false
pass or fail. This mirrors `QUERY_UNVERIFIABLE` / `CARDINALITY_UNVERIFIABLE`.

### 3. Shared primitive: `BoundedDistribution`

A single frozen model carries a **bounded statistical summary with a truncation
signal**, reused for *both* property-value distributions and
cardinality-degree distributions:

```python
class BoundedDistribution(BaseModel):
    model_config = {"frozen": True}

    # first moments — first-class
    count: int                       # observations summarised
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    variance: float | None = None    # std derivable; None when backend can't supply

    # higher moments — optional, populated only when a backend returns them
    skewness: float | None = None
    kurtosis: float | None = None

    # optional full breakdown (placeholder; populated only when feasible)
    histogram: dict[str, int] | None = None   # observed value/degree -> count

    # truncation honesty
    sample_complete: bool = True     # False => the histogram hit `limit`
    limit: int | None = None         # configured cap, when one applied
    other_count: int = 0             # observations beyond the limit (remainder)
```

- `min`/`max`/`mean`/`variance` are the **first-class moments**. Higher moments
  (`skewness`, `kurtosis`) are optional and stay `None` unless cheaply available.
- `histogram` is an **optional placeholder** for a full distribution; it is
  populated only when a backend can provide it, otherwise `None`.
- `sample_complete` / `limit` / `other_count` make truncation explicit: a
  high-cardinality property (UID, free text) is summarised to the top-N values
  plus an `other_count` remainder, with `sample_complete=False`.

`CardinalityStats` is **re-expressed on this model** (today's
`min_degree`/`max_degree`/`avg_degree`/`sample_size` map to
`min`/`max`/`mean`/`count`, gaining `variance`). The per-pair
`partitioned_cardinality` of ADR-030/E41 becomes a `dict[str,
BoundedDistribution]`, each partition carrying its own truncation signal and an
optional `histogram` placeholder.

### 4. `PropertyProfile` carries three distinct presence signals

The declared/observed/constraint distinction is made explicit so comparison can
run **two independent presence checks**:

```python
class PropertyProfile(BaseModel):
    model_config = {"frozen": True}

    name: str
    present_count: int               # non-null occurrences (see §5)
    total_count: int                 # entities of this type
    # completeness == present_count / total_count  (computed)

    constraint_required: bool | None = None
    # True  -> a DB presence/existence constraint covers this property
    # False -> inspected, no such constraint found
    # None  -> constraint info unavailable for this backend/strategy (ADR-033)

    value_distribution: BoundedDistribution | None = None   # values + types, bounded
    # observed type names remain available via the distribution / type breakdown
```

- **observed presence** (the statistic) stays as `completeness`. The misleading
  `is_required` name is **removed** from `PropertyProfile`; the *concept* it named
  ("data is 100% present") is read from `completeness == 1.0`.
- **constraint-derived presence** is the new `constraint_required` — the inspector
  cross-references `GraphProfile.constraints` onto each property (parity across
  the three backends per ADR-009; `None` where unreadable per ADR-033).

### 5. Completeness counts non-null values

`present_count` counts **non-null** occurrences: a property explicitly set to
`null` is **not present**. Rationale: a declared-required property full of nulls
must not report 100% complete. (Neo4j/Memgraph do not store nulls, so this only
affects NetworkX / explicit-null inputs, but the rule is uniform.)

### 6. Total count is diff-only — never a description contract check

`NodeTypeProfile.count` / `RelationshipTypeProfile.count` are statistics that
move over time. They are **excluded** from profile↔description comparison and
participate **only** in profile↔profile diff (an INFO drift signal). Presence of
the *type* is the contract check; the *count* is not.

### 7. Relationships: always the simple cardinality, partitioned as a deep dive

- **Always** gather the simple **label↔label** degree summary
  (`BoundedDistribution`) — today's aggregate, retained.
- **Deep dive (optional, backend-dependent):** **partitioned** cardinality keyed
  by `label + one-or-more properties`, populated **only** for declared-conditional
  relationship types when a `GraphDefinition` is injected (ADR-030/E41 gating —
  unchanged). Each partition is a `BoundedDistribution`. Getting a full degree
  distribution may be impossible on a backend → `histogram=None`, summary moments
  only; the placeholder remains for the day a backend can supply it.

### 8. The comparison contract (the full matrix)

This ADR is the authority for **what enters each comparison**. E45 implements the
node/property/constraint/value rows; E41 implements the cardinality rows.

| Field | profile ↔ description | profile ↔ profile |
|-------|----------------------|-------------------|
| node-type / rel-type list | presence: `MISSING_*` (ERROR) / `UNEXPECTED_*` (WARNING) | added/removed (INFO) |
| **total count** | — (excluded, §6) | count delta (INFO) |
| **completeness ratio** | declared-required & `completeness < 1` ⇒ violation | ratio delta ⇒ drift (INFO) |
| **constraint_required** | declared-required & `False` ⇒ "declared required, no DB constraint" ; observed `True` & not declared-required ⇒ "DB constraint not declared" ; `None` ⇒ `*_UNVERIFIABLE` (INFO) | constraint-presence delta (INFO) |
| **value_distribution (enum)** | declared enum: observed value ∉ declared ⇒ undeclared-value signal ; declared value never observed ⇒ INFO | distribution delta (INFO) |
| **value_distribution (non-enum)** | — | distribution delta (INFO) |
| **simple cardinality** | aggregate bound check (`CARDINALITY_VIOLATION` ERROR) | degree-summary delta (INFO) |
| **partitioned cardinality** | per-pair bound check when present, else `CARDINALITY_UNVERIFIABLE` (INFO) | per-partition delta (INFO) |

Any field whose value is `None` and which a row would otherwise check yields the
corresponding `*_UNVERIFIABLE` (INFO), never a false verdict (§2).

#### Open severity sub-decisions (settled during E45, recorded back here)

- declared-required-vs-occurrence violation: **settled WARNING** (E45.4).
  `PROPERTY_INCOMPLETE` (declared-required & `completeness < 1.0`) stays WARNING —
  it reports a *statistic that breaches the contract*, not a hard structural error.
- codes/severities for the declared-vs-constraint row (E45.4,
  `PropertyConstraintPresenceRule`):
  - declared-required & `constraint_required is False` → `PROPERTY_UNCONSTRAINED`
    (**WARNING**): the contract demands presence but no DB constraint guards it
    (declaration-vs-DB drift that can let data degrade silently).
  - observed `constraint_required is True` & not declared-required →
    `UNDECLARED_CONSTRAINT` (**INFO**): the DB is stricter than the declaration.
  - declared-required & `constraint_required is None` → `CONSTRAINT_UNVERIFIABLE`
    (**INFO**): constraint info unreadable for this backend/strategy — never a
    false verdict (§2/ADR-033).
- enum/value row (E45.4, `PropertyEnumValueRule`; fires only when the declared
  `python_type` is an `enum.Enum`, comparing `str(member.value)` against the
  `value_distribution.histogram` keys):
  - observed value ∉ declared → `UNDECLARED_PROPERTY_VALUE` (**WARNING**): the
    *data* violates the declared contract.
  - declared value never observed → `UNOBSERVED_PROPERTY_VALUE` (**INFO**): drift.
  - `value_distribution` / its `histogram` is `None` → `PROPERTY_VALUE_UNVERIFIABLE`
    (**INFO**): backend supplied no per-value counts (§2).
- total-count delta (E45.4): profile↔profile only, `COUNT_CHANGED` (**INFO**) on
  node-label and rel-type addresses; **never** emitted in profile↔description (§6).
- whether constraint cross-referencing is mandatory-all-backends or best-effort:
  **settled mandatory-all-backends** (E45.2). Each backend cross-references
  constraints onto every property; `None` is reserved for genuinely silent sources
  (NetworkX), never a fabricated `False` (ADR-033 honesty). "Parity" means
  ADR-009 *"each backend honest per its strategy"*, not value-identity across
  backends.

---

## Consequences

- **One statistical shape** (`BoundedDistribution`) is reused for property values
  and cardinality degrees, satisfying the "share the data models" requirement and
  giving every statistic a truncation signal and a full-distribution placeholder.
- **Three presence sources are separable**, enabling two genuinely different
  comparison checks (data-violates-contract; DB-constraint-vs-declared) that the
  current single `is_required` cannot express.
- **Breaking change, taken now on purpose.** `PropertyProfile.is_required`
  removed; `CardinalityStats` re-expressed; existing profile readers
  (`comparison/rules.py`, `visualization/text.py`, tests) updated in E45. This is
  the cheapest moment — no external consumers exist.
- **E41 is re-based, not additive.** Its `partitioned_cardinality` lands directly
  in the reshaped form (`dict[str, BoundedDistribution]`); E41.5 implements the
  cardinality rows of the matrix above.
- **Honest degradation** across backends/strategies (ADR-033): missing fields are
  `None` → `*_UNVERIFIABLE`, never silent wrong verdicts.

---

## Rejected alternatives

- **Stay additive (ship E41 onto the frozen model, reshape later).** Rejected:
  `partitioned_cardinality`'s shape would become a compatibility surface and we'd
  reshape immediately after. Cheaper to reshape before any consumer exists.
- **Byte/serialised comparison with a profile-embedded hash.** Rejected: the
  information is in the fields; hashing is a comparison-function optimisation, not
  a model property (§1).
- **Keep `is_required` on `PropertyProfile` as an alias.** Rejected: the name is
  the bug. Removing it forces every reader to choose the correct one of the three
  sources.
- **Separate `ValueDistribution` and `DegreeDistribution` models.** Rejected in
  favour of one shared `BoundedDistribution` (the requirement was explicit about
  sharing).
- **Full moment set (skew/kurtosis) as first-class required fields.** Rejected:
  uneven backend support; carried as optional `None`.

---

## Cross-references

- ADR-030: per-pair observed statistics (amended — the field now sits on `BoundedDistribution`)
- ADR-015: declared/observed mirror
- ADR-009: inspector query alignment & GraphProfile parity
- ADR-033: Neo4j three-way strategy (drives `constraint_required` / type availability)
- `GraphProfile` / `PropertyProfile` / `CardinalityStats`: `src/orthograph/graph_profile/models.py`
- comparison rules: `src/orthograph/comparison/rules.py`, `src/orthograph/comparison/diff_rules.py`
- E45 epic: `.agentic/planning/active_epics/E45_graphprofile_statistical_model_reshape.md`
- E41 epic: `.agentic/planning/active_epics/E41_conditional_cardinality_profiling.md`
