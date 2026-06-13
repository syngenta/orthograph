# Epic E24: Synthetic Graph Data Generation

> **Priority:** Medium
> **Phase:** post-pilot (v0.2.0 candidate)
> **Blocked by:** E23 (Inspector Backend-Behaviour Injection Interface) — the generator's
> profile-driven mode requires a stable, inspectable `GraphProfile` whose statistics fields
> (`count`, `cardinality_stats`, `PropertyProfile.completeness`) are populated consistently
> across backends. E23 must settle the inspector interface and any remaining parity gaps (e.g.
> Memgraph `source_labels`/cardinality) before the generator can rely on those fields as a
> contract rather than a best-effort fill.
> **Unblocks:** Nothing in v0.1.0. Will be a dependency of any downstream data-engineering or
> testing tooling that needs representative synthetic graph datasets.
> **Relates to:** PRD Constraint 2 (models are single source of truth), PRD Constraint 5 (not a
> query optimizer — generation is schema-shaped data, not query execution), ADR-003 (two-phase
> extension architecture), ADR-005 (cardinality semantics), E23 (inspector interface), the
> `GraphProfile` schema (`decisions/012-optional-dependency-policy.md`).

---

## Why This Epic Is Needed

### The problem

Testing and benchmarking graph-database applications requires realistic graph data. Today, teams
either hand-write fixture data (brittle, small-scale, doesn't represent real distributions) or
dump production data (privacy concerns, scale unpredictable, not reproducible). Neither approach
answers the question *"what does 10× this real database look like?"*

Orthograph already holds both pieces needed to answer that question:

- The **`GraphDataModel`** — the structural blueprint (labels, types, cardinality, property
  declarations, required/optional flags).
- The **`GraphProfile`** — the statistical fingerprint of a real database (node counts, property
  completeness rates, cardinality distributions per relationship type).

Neither piece alone is sufficient. The model says what *can* exist; the profile says what
*typically* exists and in what proportions. A synthetic generator needs both.

### The primary use cases

1. **Scale-up from a real sample.** Inspect a small real database → receive a `GraphProfile` →
   feed the profile and the model to the generator → produce a larger synthetic dataset that
   preserves the same structural ratios and statistical distributions.

2. **Fully synthetic from the model only.** Provide a model and explicit generation parameters
   (target counts, cardinality targets, completeness rates) → produce a dataset without a real
   database to sample from.

3. **Regression / load testing.** Generate reproducible datasets of a known size and distribution
   for benchmarking queries or testing validation logic against non-trivial data.

---

## Design Goals and Invariants

The following goals constrain every implementation decision in this epic. They must be resolved
before tasks are written; any task that violates one must be flagged.

### G1 — Model fidelity (non-negotiable)

Every generated node and relationship must be valid against the `GraphDataModel`. Specifically:

- Every node's label must be a declared node type.
- Every relationship's type must be a declared relationship type.
- Required properties must always be present and of the declared type.
- Endpoint types must match the declared `__source_label__` / `__target_label__`.
- The model is the single source of truth (PRD Constraint 2): the generator derives all structural
  constraints from the model, never from the caller's ad-hoc input.

### G2 — Statistical alignment

When a `GraphProfile` is supplied, the generator must produce distributions that approximate it:

- Node type ratios (`count` fields) are preserved or scaled proportionally.
- Relationship type counts and per-type cardinality distributions are scaled from
  `cardinality_stats` (`min_degree`, `max_degree`, percentiles where available).
- Optional property completeness rates (from `PropertyProfile.completeness`) are matched within a
  configurable tolerance.
- Property value *types* are respected; realistic value *content* is generated (e.g. plausible
  strings, bounded integers) — not guaranteed semantically meaningful.

### G3 — Controllable override

Callers must be able to override any statistic from the profile:

- Total node count (and per-type count, or just a scaling factor relative to the profile).
- Cardinality target per relationship type (e.g. force `ACTED_IN` to ONE-to-MANY regardless of
  the profile).
- Completeness rate per property (e.g. force `email` to 100% present even if the profile shows 60%).
- A random seed for reproducible generation.

The override API should be additive: supply nothing and get profile-driven behaviour; supply
overrides to deviate from the profile selectively.

### G4 — Output-shape agnosticism

The generator must not assume a specific database driver or serialisation format. Its output is
an in-memory graph representation (lists of node dicts and relationship dicts in Orthograph's
existing magic-key format) that callers can pipe into any destination: a Cypher generator, a
GQLAlchemy writer, a NetworkX graph, a file.

No driver, no session, no transaction. The generator is pure (consistent with PRD Constraint 3
and PRD Constraint 13).

### G5 — Profile-input alignment (the inspect → generate pipeline)

The generator's profile-driven input shape must be the `GraphProfile` produced by
`GraphInspector.inspect()` — not a bespoke intermediate format. The inspect → generate pipeline
must work without transformation:

```
GraphInspector.inspect(connection) -> GraphProfile
                                          |
                                          v
SyntheticGraphGenerator(model, profile).generate(scale=10) -> SyntheticGraphDataset
```

This alignment is why E23 is a hard dependency: if `GraphProfile` fields are populated
inconsistently across backends (e.g. `cardinality_stats` is `None` on Memgraph but populated on
Neo4j), the generator cannot treat the profile as a reliable contract.

### G6 — No new graph-model primitives

This epic must not introduce new node/relationship modelling concepts beyond what `NodeModel`,
`RelationshipModel`, and `GraphDataModel` already declare. If a generation use case requires a
new model concept (e.g. property value constraints, domain-specific generation hints), that
concept must first be added to the model layer in a separate epic.

---

## Scope

### In scope

- A `SyntheticGraphGenerator` class (or equivalent) that accepts a `GraphDataModel` and an
  optional `GraphProfile`, and produces in-memory graph data.
- A `SyntheticGraphDataset` output type: typed containers of node-dict lists and relationship-dict
  lists, keyed by label/type, in Orthograph's existing magic-key dict format.
- Scale-factor and per-type count override API.
- Per-property completeness rate override API.
- Per-relationship-type cardinality override API.
- Random seed support for reproducible generation.
- Validation of the generated output against the model (via `GraphValidator`) as an opt-in step —
  proving G1 holds.
- Unit tests using only in-memory fixtures (no live database).
- A profile-less mode (model-only, with sensible defaults or explicit caller-provided parameters).

### Out of scope

- Semantically meaningful property values (realistic names, dates, etc.) — this is a content
  generation concern, not a structural one. Plausible types (strings, ints) are sufficient.
- Writing generated data to a database — the caller does that. The generator is pure.
- Incremental / streaming generation for very large datasets — post-pilot concern.
- Generating query catalogues or Cypher from synthetic data — separate concerns.
- Schema evolution / versioned generation — out of scope.

---

## Key Open Questions

These questions must be resolved (as decisions, in an ADR or as part of the task scoping
session) before task breakdown begins. They are recorded here so they are not forgotten.

### Q1 — Cardinality realisation strategy

`cardinality_stats` carries `min_degree` and `max_degree` (and optionally percentile
distributions). How should the generator translate these into edge counts per node?

- **Option A:** Sample uniformly between `min_degree` and `max_degree` for each source node.
  Simple; ignores percentile shape.
- **Option B:** If percentile data is available, sample from a fitted distribution (e.g.
  log-normal or empirical CDF). More faithful; more complex.
- **Option C:** Use a configurable strategy object — callers can inject their own distribution
  sampler. Most flexible; most surface area.

This decision interacts with G3 (overrides) and with how much statistical structure `GraphProfile`
actually carries after E23's parity work. Decide during task scoping.

### Q2 — Output type: dict lists vs NodeModel instances

Should `SyntheticGraphDataset` emit:

- **Raw dicts** in the magic-key format (`{"__label__": "Person", "name": "x", ...}`), ready for
  `CypherGenerator` and `GraphValidator` without conversion; or
- **Typed `NodeModel` / `RelationshipModel` instances**, which are already valid Pydantic models?

Raw dicts are the existing internal currency everywhere. Typed instances would be more ergonomic
for callers who want to inspect generated data with IDE support. The two are not mutually
exclusive — the dataset could expose both views. Decide during task scoping.

### Q3 — Where does this live?

> **Forward note — ADR-017 (2026-06-12).** The candidate paths below predate
> two refactors. `extensions/` was removed by E25/ADR-011 (now `backends/`,
> `graph_profile/`, `cypher/`). `core/` is renamed to `graph_definition/` by
> ADR-017, and the observed `GraphProfile` now lives in `graph_profile/models.py`
> (not `extensions/models.py`). When this scoping session runs, evaluate the
> location against the **post-ADR-017 topology**: `graph_definition/` (declared),
> `graph_profile/` (observed), `comparison/` (cross-layer), `diagnostics/`
> (result currency). A generator that reads a definition + a profile is a
> cross-layer consumer — weigh a dedicated package over folding it into either
> twin. Do not revert ADR-017.

Candidate module locations:

- `src/orthograph/extensions/synthetic/` — an optional extension, independently installable
  (consistent with PRD Constraint 11). No hard dependency on any specific backend.
- `src/orthograph/core/synthetic.py` — part of core, no extra install required. Justified if
  generation is considered fundamental (it depends only on the model and a profile — both core
  types).

The profile dependency is on `GraphProfile` from `extensions/models.py`, which is currently in
the extensions package. If the generator lives in `core/`, it would create a core → extensions
dependency, which violates PRD Constraint 1 (no database-specific logic in core — though
`GraphProfile` itself is DB-agnostic). This tension must be resolved in the scoping session.

### Q4 — Relationship generation order and referential integrity

Relationships require source and target nodes to already exist. The generation order is therefore:
all nodes first, then relationships. Within relationships, cycles (A → B → A) are structurally
valid; self-loops depend on the model. The question is whether the generator enforces a
deterministic order (predictable with a seed) or uses a topology sort that may fail on cycles.
Decide during task scoping.

---

## Success Criteria (epic-level, to be verified when tasks complete)

- [ ] `SyntheticGraphGenerator(model).generate(...)` produces model-valid data without a profile.
- [ ] `SyntheticGraphGenerator(model, profile).generate(scale=N)` produces data with node-type
      ratios and property-completeness rates within a configurable tolerance of the profile.
- [ ] Every generated item validates against `GraphValidator` without errors (G1 proven by test).
- [ ] A random seed produces byte-for-byte identical output on repeated calls.
- [ ] The generator is pure — no session, driver, or I/O.
- [ ] `mypy src/` clean; `ruff check` clean; full `pytest` green.

---

## Cross-References

- E23 (hard dependency): `.agentic/planning/active_epics/E23_inspector_backend_interface.md`
- `GraphProfile` schema: `.agentic/decisions/012-optional-dependency-policy.md`
- PRD: `.agentic/knowledge/product_requirements_document.md`
- ADR-003 (two-phase architecture): `.agentic/decisions/003-extensions-two-phase-architecture.md`
- ADR-005 (cardinality semantics): `.agentic/decisions/005-cardinality-semantics.md`
