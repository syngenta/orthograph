# ADR-010: Declared Identifier Parameters in Typed Queries

**Date:** 2026-06-10
**Status:** Accepted
**Category:** extensions / query catalogue

## Context

E16 shipped a typed query contract (`CypherReadQuery`/`CypherWriteQuery`) in which a
`cypher_template` may contain `$value` placeholders that map 1:1 to the fields of a
`Params` Pydantic model, validated at class-definition time. The driver substitutes
`$value` placeholders safely.

Cypher (and Cypher-like languages) **cannot parameterise identifiers** — node labels,
relationship types, and property keys are not values and cannot be passed as `$param`.
Yet several real queries need a *dynamic* identifier:

- **Inspector introspection queries** ask "what are the properties of `:Person`?" where the
  label is discovered at runtime via `db.labels()` and varies per call.
- **Generated CRUD queries** (CypherGenerator) target a specific node type whose label comes
  from the model.

Today these are handled by raw f-string interpolation of the identifier into the query
text (`neo4j/queries.py`, `cypher/generator.py`), which (a) sits outside the typed contract
entirely and (b) is an injection vector when the identifier is not model-bound.

The question: **how does a typed query carry a dynamic identifier**, given it cannot be a
`$param`, without making identifier-bearing queries a visibly different kind of object from
value-only queries?

## Considered Options

- **A — Identifiers via constructor args; `Params` = values only.** The identifier is a
  `__init__` argument (validated there); `Params` carries only `$`-values. *Rejected:* makes
  identifier queries structurally different (custom `__init__`); query is no longer a
  registerable singleton; the identifier never appears in `describe()`.

- **B — Identifiers as `Annotated` fields inside `Params`, split inside `build()`.** A
  marker (`label: Annotated[str, Identifier()]`) plus a `split_params()` helper the author
  calls inside `build()`. *Rejected:* hides an internal switch inside each `build()`; the
  author must remember to call the helper; non-homogeneous and error-prone.

- **C — Openly declared `Identifiers` group + distinct template placeholder (CHOSEN).**

## Decision

Every typed query openly declares **two parameter groups**:

- `Identifiers` — a Pydantic model whose fields are validated as safe identifiers and
  **spliced into the query text** via a distinct, collision-proof template placeholder.
- `Params` — unchanged E16 meaning: fields mapped to `$value` placeholders and substituted
  by the driver.

Queries stay **declarative**: `cypher_template` gains an identifier placeholder distinct
from Cypher's `$value` and from Cypher's bare `{...}` map literals (which are already taken).
The placeholder delimiter is **`<<name>>`** (e.g. `` MATCH (n:`<<label>>` {released: $released}) ``).
The Cypher base `build()` validates each `Identifiers` field through `validate_identifier`
(rejecting anything outside the safe-identifier grammar — see ADR-008) and substitutes it into
the matching `<<name>>` slot; `Params` fields flow to the driver as today.

The class-definition-time validator is extended: `<<name>>` placeholders must map 1:1 to
`Identifiers` fields, and `$value` placeholders 1:1 to `Params` fields.

`Identifiers` is **opt-in with an empty default**. A query that declares no `Identifiers`
and uses no `<<placeholder>>` is exactly the E16 query of today, unchanged. Hardcoded literal
labels (`:Movie`) remain legal and idiomatic — the mechanism is only for *dynamic* identifiers.

## Consequences

- One homogeneous authoring shape for all queries: declare `Identifiers`, declare `Params`,
  write a template, write `materialize`/`interpret_result`. No custom `__init__`, no hidden
  switch. Readability and transparency are preserved — a reader sees which parameters are
  identifiers and which are values, in the declaration.
- The same mechanism serves both the inspector queries (label varies per call) and the
  CypherGenerator (label fixed by model at synthesis).
- Identifier safety becomes structural: every dynamic identifier passes `validate_identifier`
  before reaching the query string.
- **Resolved (2026-06-10):** the `Identifiers`/`Params` split is *backend-neutral* at the
  declaration level. Validated against the GQLAlchemy (GraphORM) builder surface — see
  `.agentic/reviews/2026-06-10-graphorm-adr-validation-report.md`. In a builder-based backend
  the same two groups are consumed by `build()` as builder arguments (`Identifiers` →
  `node(labels=...)`, validated via `validate_identifier`) and value bindings (`Params` →
  `.where(...)`); the `<<placeholder>>` template substitution is the **Cypher-specific
  rendering** of the neutral split, not part of the split itself. The generic base
  (`orthograph.query.base_models.ReadQuery[P, D]`) bakes in no Cypher assumption and is
  unchanged (`build() -> Any` already permits a builder return).
- **Implementation note (no empty-key tax):** `Identifiers` carries an empty default at the
  **Cypher base layer** (`CypherReadQuery.Identifiers = NoIdentifiers`); the generic
  signature stays `ReadQuery[P, D]` / `WriteQuery[P, R]` (two type params, unchanged). A
  value-only query declares no `Identifiers` and is byte-for-byte the E16 query of today. The
  grilling log's "Sketch C" 3-generic-param form (`CypherReadQuery[Identifiers, Params,
  Output]`) is illustrative only and is **rejected** as the implementation shape. This is an
  E17 implementation detail and does not affect the backend-neutrality verdict.
- **Amendment (2026-06-10, E17 T2.5 implementation):** the two empty defaults are realised as
  **public** models — `NoParams` and `NoIdentifiers` (exported from
  `orthograph.extensions.cypher`) — not a private `_NoIdentifiers`. `Identifiers` defaults to
  `NoIdentifiers` and may be omitted; `Params` is **always declared** (e.g. `Params = NoParams`
  for a value-only query) because it is the generic type parameter `P` of `ReadQuery[P, D]` and
  must stay bound for `build(self, params: P)` to remain precisely typed. This is the one
  honest asymmetry between the groups: `Identifiers` is omittable, `Params` is named. Auto-
  defaulting `Params` to an empty model (mirroring `Identifiers` fully) was considered and
  **rejected** — it would leave `P` unbound and reopen E16's accepted "`Params` is mandatory"
  contract. The call shape is **(a)**: identifier values are bound on the query instance at
  construction (`MyQuery(identifiers={...})`); `build(self, params)` keeps its single argument
  and the generic `Executor.read/write` seam in `query/base_models.py` is untouched. Kind
  resolution: an `Identifiers` field named `rel_type` or ending in `_rel_type` validates as a
  `"relationship type"`, every other field as a `"label"`.
- **Confirm in code at E8:** the GQLAlchemy query catalogue (E8.1) instantiates a
  `GqlAlchemyReadQuery` with these two groups and a builder-returning `build()`, exercising
  the split in code (tracked as an E8 acceptance criterion).

## Relates to

- ADR-008 (Cypher identifier safety — `validate_identifier`), planned under E17 T1/T6.
- E16 (typed query catalogue) — this ADR is additive and changes no existing E16 query.
- ADR-009 (inspector query alignment) — the inspector queries are the first consumers.
