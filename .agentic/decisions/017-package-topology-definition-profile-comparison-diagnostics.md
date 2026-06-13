# ADR-017: Package Topology — Definition, Profile, Comparison, Diagnostics

**Date:** 2026-06-12
**Status:** Accepted
**Category:** architecture / package topology / ubiquitous language

> Companion to ADR-013 (ubiquitous-language *naming*), ADR-015 (the
> declared/observed *mirror principle* and injection-based comparison), and
> ADR-016 (naming the mirror objects `GraphDefinition` / `GraphProfile`).
> Where those reconciled **names**, this ADR reconciles **package boundaries**:
> it turns the mirror into a folder topology and gives each domain concern its
> own home sized to its expected growth.

---

## Context

ADR-015/016 established the domain model in words — a **declared side**
(`GraphDefinition`) and an **observed side** (`GraphProfile`), reconciled by a
**comparison** that walks a shared address space and emits issues. The folder
layout never caught up to that vocabulary:

- `core/` is a grab-bag: the declared models (`NodeModel`,
  `RelationshipModel`, `GraphDefinition`), the declared type system
  (`TypeInfo`, `CardinalitySpec`), the in-memory data validator
  (`GraphValidator`), **and** two unrelated concerns — the shared validation
  **result currency** (`ValidationIssue`, `ValidationResult`,
  `GraphValidationError`, `Severity`, `EntityType`) and the
  definition-misuse exceptions (`ModelDefinitionError` & subclasses).
- `profile/` holds both the observed currency (`GraphProfile` models, the
  inspector ABC, shared queries) **and** the cross-layer comparison engine
  (`validation.py` + `rules.py`). The comparison is not "profile" — it is the
  bridge *between* the two sides, and `validate_profile` is misnamed for an
  operation that reconciles two artefacts rather than validating one against a
  schema.
- The folder name `core/` does not echo the ADR-016 rename to
  `GraphDefinition`.

### The overloaded word

`validate` covers four genuinely different operations in this codebase:

| # | Operation | Subjects | Today |
|---|-----------|----------|-------|
| 1 | parse/coerce one record to a typed instance | one record | Pydantic `model_validate` |
| 2 | check in-memory data conforms to the definition | data + definition | `GraphValidator.validate` (`core/validation.py`) |
| 3 | check a query/catalogue conforms to the definition | query + definition | `validate_cypher`, `validate_query_catalogue` (`cypher/`) |
| 4 | reconcile the declared definition against the observed profile | definition + profile | `validate_profile` (`profile/validation.py`) |

Operations 1–3 are **conformance**: "does this *one* thing conform to the
definition?" — the Pydantic mental model. Operation 4 is **comparison**: it
holds two independently-produced artefacts side by side and reports where and
how much they diverge. Naming #4 `validate_*` borrows the Pydantic word for an
operation that is not Pydantic-shaped — the root of the confusion.

### Growth pressure (the deciding force)

ADR-015 §3 documented where this domain grows fastest: the **observed side**
(new measurements — histograms, percentiles, distinct counts: "Case A"
enrichment) and the **comparison rule set** (new comparable aspects: "Case B").
The declared side is comparatively stable. A topology that buries the
fast-growing parts inside a shared `core/`/`profile/` forces wide edits for
narrow growth. The right topology gives the fast-growing concerns their own
package so growth is local.

---

## Decision

Adopt a five-package domain topology. Package names are **nouns** (the domain
objects); activity modules inside them keep ADR-013 **verb** names
(`validation.py`, `inspection.py`, `engine.py`).

```
src/orthograph/
├── api/                      consumer surface (unchanged)
│
├── graph_definition/         THE DECLARED SIDE          (was core/)
│   ├── node_model.py             NodeModel            (base class — you SUBCLASS)
│   ├── relationship_model.py     RelationshipModel    (base class — you SUBCLASS)
│   ├── graph_definition.py       GraphDefinition      (container — you INSTANTIATE)
│   ├── types.py                  TypeInfo, CardinalitySpec, Cardinality, resolve_type_info
│   ├── validation.py             GraphValidator       (data ⟶ definition conformance)
│   └── errors.py                 ModelDefinitionError, MissingClassVarError, MissingUidFieldError
│
├── graph_profile/            THE OBSERVED SIDE          (was profile/)
│   ├── models.py                 GraphProfile, NodeTypeProfile, PropertyProfile, …
│   ├── inspection.py             GraphInspector ABC + shared Cypher inspector base
│   └── queries/                  vendor-neutral Cypher fragments
│
├── comparison/               THE CROSS-LAYER ACTIVITY   (extracted from profile/)
│   ├── rules.py                  Rule, RuleContext, standard_rules()
│   └── engine.py                 compare(definition, profile, rules) -> ValidationResult
│
├── diagnostics/              THE SHARED RESULT CURRENCY (extracted from core/exceptions.py)
│   ├── result.py                 ValidationIssue, ValidationResult, GraphValidationError
│   └── classification.py         Severity, EntityType
│
├── cypher/                   BACKEND-SPECIFIC TOOL (keeps its own validation)
│   ├── parser.py                 validate_cypher          (query ⟶ definition conformance)
│   ├── validation.py             validate_query_catalogue, …_against_profile
│   └── … (generator, identifiers, bindings, query_execution, exceptions)
│
├── catalogue/                unchanged
├── backends/                 unchanged
├── io/                       unchanged
├── visualization/            unchanged
└── dependencies.py
```

### 1. `core/` → `graph_definition/`

The folder becomes the **declared side** and nothing else: base classes you
subclass, the container you instantiate, the declared type system, the
data-vs-definition validator, and the definition-misuse errors. The name
catches up to ADR-016's `GraphDefinition`.

### 2. `core/exceptions.py` splits in two

- The **result currency** — `ValidationIssue`, `ValidationResult`,
  `GraphValidationError`, and the `Severity` / `EntityType` enums they are
  built from — moves to a new top-level `diagnostics/` package. It is the
  shared vocabulary that *every* checker emits and the renderer consumes
  (imported today by ~20 modules across `api/`, `cypher/`, `profile/`,
  `backends/`, `visualization/`).
- The **definition-misuse exceptions** — `ModelDefinitionError`,
  `MissingClassVarError`, `MissingUidFieldError` — move to
  `graph_definition/errors.py`. They are about misusing the *definition* and
  are imported only within that package.

### 3. `core/types.py` splits

- `TypeInfo`, `CardinalitySpec`, `Cardinality`, `resolve_type_info` are the
  **declared face** (ADR-015; `TypeInfo`'s own docstring names its observed
  declared face) → `CardinalitySpec` and `Cardinality` live in
  `graph_definition/relationship_model.py`; `TypeInfo` and `resolve_type_info`
  live in `graph_definition/property_spec.py`.
- `Severity`, `EntityType` describe *issues*, not the definition → move to
  `diagnostics/classification.py`. (`EntityType.QUERY` is the only hint they
  are broader, but a query is still the *subject* of an issue, so it belongs
  with the result currency. Leaving the enums with the definition would force
  `diagnostics/` to depend on the definition and re-couple the foundation —
  rejected.)

### 4. `profile/` → `graph_profile/`, and the comparison engine leaves it

`graph_profile/` holds only the **observed currency**: the profile models, the
inspector ABC, and the shared queries. The comparison engine
(`validation.py` + `rules.py`) moves to a new top-level `comparison/`
package — it is the cross-layer bridge, not part of the observed side.

We use the **noun** `graph_profile/` (mirroring `GraphProfile`), not the verb
`graph_profiling/`: the folder holds the profile *and* its inspector, not only
the act of profiling.

### 5. The shared currency is named `diagnostics/`, not `results/` or `validation/`

- `results/` — rejected: "results of *what*?" is ambiguous and invites a
  junk-drawer, the same failure as `common/`.
- `validation/` — rejected: it would lie. The package holds the *output* of
  validation (value-objects), not validators. The word `validate` is reserved
  for the operations that earn it (operations 2 and 3 above), each living with
  its subject (`graph_definition/validation.py`, `cypher/validation.py`).
- `diagnostics/` — chosen: it is the established term (compilers, linters,
  LSP) for *a finding with a severity and a subject* — exactly
  `ValidationIssue`. Its charter is narrow and self-describing, so it repels
  unrelated code, and it has honest headroom if a check later emits a
  non-issue finding.

### 6. The comparison verb

The public comparison entry point is `compare(definition, profile, rules) ->
ValidationResult` in `comparison/engine.py`, retiring the misnamed
`validate_profile`. (`api.database.validate` may keep its consumer-facing verb;
the deep implementation name becomes `compare`.) The result type remains
`ValidationResult` from `diagnostics/` — comparison *produces* the shared
currency, it does not own a bespoke result class.

### 7. Cypher query-validation stays in `cypher/`

`validate_cypher` and `validate_query_catalogue` are welded to the Cypher
parser and `Backend.CYPHER`; they cannot leave `cypher/` without dragging
backend specifics into a shared package. Query-vs-definition conformance is
backend-local by nature. This is the deciding wrinkle that makes a single
all-conformance `validation/` package (the rejected "Cut A") impossible to
balance.

---

## Dependency DAG (strictly downward, acyclic)

```
api/ ──────────────────────────────────────────────┐
  │                                                 │
backends/ ──► graph_profile/ ──► graph_definition/  │
  │              │                    │             │
cypher/ ─────────┤                    │             │
  │              ▼                    ▼             ▼
comparison/ ──► (reads both) ──────► diagnostics/ ◄─┘
                                        ▲
            everything emits findings ──┘   (diagnostics/ depends on NOTHING)
```

`diagnostics/` is the new foundation (no intra-package imports).
`graph_definition/` sits above it. `graph_profile/` and `comparison/` reference
the definition. `cypher/`, `backends/`, `api/` ride on top. No cycles, no
cross-backend edges, no upward imports — the four ADR-011 architecture
invariants still hold and are easier to enforce because the seams are sharper.

---

## Rationale (scored against the adopted rubric)

- **Growth array.** The two fastest-growing concerns get their own packages:
  observed enrichment lands only in `graph_profile/models.py` (Case A); a new
  comparable aspect lands only in `comparison/rules.py` (Case B). The stable
  declared side stays small.
- **Forces least change.** A new measurement, a new rule, a new backend, or a
  new renderer each touch exactly one package. Every checker depends on the
  abstract `diagnostics/` currency, never on a concrete domain twin, so adding
  a checker never couples the two sides.
- **Readability / coherence.** The top-level folder list *is* the domain
  model taught by ADR-015/016: definition vs profile, compared by
  `comparison/`, producing `diagnostics/`.
- **Less surprise.** `diagnostics/` contains diagnostics — no lie.
  `validation.py` always means "X-vs-definition conformance" wherever it
  appears. `validate` maps 1:1 to conformance; `compare` maps to reconciling
  the two twins.
- **SOLID.** SRP — one reason to change per package. OCP — comparison is open
  via injected rules (ADR-015 §4), now physically isolated so extension never
  edits the engine. DIP — every layer depends on the abstract `diagnostics/`
  currency, not on a concrete twin.
- **Testability.** `diagnostics/` has no dependencies → trivially unit-testable
  and importable by any test. `comparison/` takes definition + profile + rules
  by injection → pure-function testing with hand-built fixtures, no backend.

---

## Consequences

### Positive

- The mirror is visible in the folder tree, not just in prose.
- The fast-growing sides grow locally; the foundation is dependency-free.
- The four-way `validate` overload collapses to a clean `validate`
  (conformance) vs `compare` (reconciliation) split.

### Negative / risks

- **Large mechanical rename surface.** `core/` → `graph_definition/` touches
  imports across `src/`, the full `tests/` tree, notebooks, and docstrings.
  Mitigated by the stepwise plan (one validated step at a time) and by the
  existing `GraphDataModel = GraphDefinition` alias from ADR-016.
- **Interaction with E20 (Tech Debt).** E20 plans a project-wide
  `OrthographError` root and a `get_logger` helper, slated for
  `core/exceptions.py` / `core/logging.py`. Under this ADR those land in
  shared homes instead (the root alongside `diagnostics/`; logging in a shared
  utility module), **not** inside the renamed definition package. This is a
  *re-path*, not a contradiction — see the forward note added to E20. We do
  not revert E20; we point it at the new topology.
- **Stale paths in older records.** Older ADRs and the PRD reference `core/`,
  `profile/validation.py`, `GraphDataModel`, and `validate_profile` as the
  then-current state. Those are historical and are **not** rewritten. This ADR
  is the forward authority; the mapping table below tells a reader how the old
  paths translate.

---

## Path translation (old → new) for readers of older records

| Old reference (in ADR-001/003/004/005/007/012/013/015/016, PRD) | New home |
|---|---|
| `core/` (package) | `graph_definition/` |
| `core/graph_data_model.py` · `GraphDataModel` | `graph_definition/graph_definition.py` · `GraphDefinition` |
| `core/types.py` (TypeInfo) | `graph_definition/property_spec.py` |
| `core/types.py` (CardinalitySpec, Cardinality) | `graph_definition/relationship_model.py` |
| `core/types.py` (Severity, EntityType) | `diagnostics/classification.py` |
| `core/validation.py` · `GraphValidator` | `graph_definition/validation.py` · `GraphValidator` |
| `core/exceptions.py` (ValidationIssue/Result/GraphValidationError) | `diagnostics/result.py` |
| `core/exceptions.py` (ModelDefinitionError & subclasses) | `graph_definition/errors.py` |
| `profile/` (package) | `graph_profile/` |
| `profile/validation.py` · `validate_profile` | `comparison/engine.py` · `compare` |
| `profile/rules.py` | `comparison/rules.py` |
| `profile/models.py`, `profile/inspection.py`, `profile/queries/` | `graph_profile/` (same names) |

---

## Implementation note

Carried out as a **stepwise rename + extraction**, designed to run across
multiple small sessions with reduced context, each step ending green
(`pytest` + `mypy src/` + `ruff check` + the ADR-011 architecture tests). The
ordered step plan lives (temporarily) in
`.opencode/plans/package-topology/` — **not** in an epic, because this is a
cross-cutting architecture effort. On completion the plan folder is disposable;
this ADR is the durable record. Order: `diagnostics/` extraction first (pure
value-objects, lowest risk) → `core/` → `graph_definition/` rename →
`comparison/` extraction last.
