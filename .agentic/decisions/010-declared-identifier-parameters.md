# ADR-010: Declared Identifier Parameters in Typed Queries

**Date:** 2026-06-10
**Status:** Proposed
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
- **Open / to confirm:** the `Identifiers`/`Params` split is intended to be *backend-neutral*
  at the declaration level so the base query classes stay viable for a future GraphORM
  (GQLAlchemy) backend, where identifiers are consumed via builder calls rather than template
  placeholders. This has **not** been validated against GQLAlchemy yet; this ADR is `Proposed`
  until that investigation confirms the split survives the GraphORM case. The
  template-placeholder handling is explicitly Cypher-only.

## Relates to

- ADR-008 (Cypher identifier safety — `validate_identifier`), planned under E17 T1/T6.
- E16 (typed query catalogue) — this ADR is additive and changes no existing E16 query.
- ADR-009 (inspector query alignment) — the inspector queries are the first consumers.
