# Prompt: Validate ADR-010 / ADR-009 against the GraphORM (GQLAlchemy) backend

> **Type:** Research + decision task (no production code).
> **Goal:** Close the single open item blocking ADR-010 and ADR-009 from moving
> `Proposed → Accepted`: confirm (or refute) that the declared-`Identifiers` / `Params`
> parameter-group split is **backend-neutral** — i.e. it survives a backend that builds queries
> via Python builder expressions (GQLAlchemy) rather than Cypher string templates.

---

## Context you must read first (in this order)

1. `.agentic/reviews/2026-06-10-query-alignment-grilling.md` — the decision log (D1–D8) and the
   A/B/C sketches that produced these ADRs.
2. `.agentic/decisions/010-declared-identifier-parameters.md` — the mechanism under test. Note the
   explicit open item in its **Consequences** section: the split is *intended* backend-neutral but
   **has not been validated against GQLAlchemy**.
3. `.agentic/decisions/009-inspector-query-alignment.md` — depends on ADR-010.
4. `src/orthograph/catalogue/typed.py` — the generic `ReadQuery`/`WriteQuery` base
   (`Params`/`Output`/`name`/`backend` ClassVars; `build(params) -> Any`; `__init_subclass__`
   contract enforcement). This is the base both Cypher and any GraphORM backend must subclass.
5. `src/orthograph/extensions/cypher/base_models.py` — how the Cypher backend specialises that base
   today (declarative `cypher_template`, definition-time `$param`↔`Params` validation). ADR-010 adds
   an `Identifiers` group + `<<placeholder>>` to THIS layer.

## The GQLAlchemy surface to investigate

- `src/orthograph/extensions/gqlalchemy/query_builder.py` — `ValidatedQueryBuilder`; how GQLAlchemy
  fluent builder expressions are constructed and where labels / relationship types / property keys
  enter the expression.
- `src/orthograph/extensions/gqlalchemy/codegen.py` — how Node/Relationship classes are generated
  from the model (where labels become Python class identifiers).
- `src/orthograph/extensions/gqlalchemy/result_adapter.py` — how results map back to validation dicts
  (the GQLAlchemy analogue of `materialize()`).
- `.agentic/planning/epics/E8_gqlalchemy_query_catalogue.md` — the planned GQLAlchemy query catalogue
  (it is "planned, blocked by E16"); read what shape E8 expects a `GqlAlchemyQueryCatalogue` query to
  take, since that is the future consumer of this base contract.

## The precise question to answer

In GQLAlchemy, a query is a **Python builder expression**, e.g. roughly
`match().node(labels="Person", variable="n").where(...).return_(...)`. There is **no string template**,
so the `<<placeholder>>` substitution mechanism from ADR-010 cannot apply directly. The question is
whether the *declaration-level* split still holds:

- Does separating parameters into an **`Identifiers` group** (label / rel-type — things that select a
  builder method argument like `node(labels=...)`) and a **`Params` group** (values — things that go
  into `.where(prop == $value)` bindings) make sense for a builder-based backend?
- If yes: the GraphORM `build()` consumes `Identifiers` by passing them as builder arguments (and
  still validates them as safe identifiers), and consumes `Params` as value bindings — the
  `<<placeholder>>` mechanism is simply the *Cypher-specific rendering* of the same neutral split. ADR-010
  stays as written, the open item closes, both ADRs → `Accepted`.
- If no (the split distorts the GQLAlchemy case, or builder methods don't cleanly partition into
  identifier-args vs value-args): ADR-010 must be **revised** to scope `Identifiers`+`<<placeholder>>`
  as Cypher-only, and the generic base in `typed.py` must NOT assume the split. Record the revision.

## Concrete checks to perform

1. Pick 2–3 representative GQLAlchemy queries (one match-by-label, one match-by-property-value, one
   relationship query) and sketch — **on paper, in the report, no code committed** — how each would be
   expressed as a subclass of the generic `ReadQuery` base with an `Identifiers` group and a `Params`
   group. Show where each declared parameter lands in the builder expression.
2. Confirm whether `build(params) -> Any` returning a builder object (instead of a `(cypher, dict)`
   tuple) is already supported by `typed.py`'s contract and the executor abstraction. (`build` returns
   `Any` by design — verify nothing downstream assumes the Cypher tuple shape at the generic layer.)
3. Confirm identifier safety still has a home: in Cypher it's `validate_identifier` + splice; in
   GQLAlchemy, is the label passed to a builder method, and does that builder escape/validate it, or
   must Orthograph validate it before the call?
4. Check the generic base in `typed.py` does **not** already bake in any Cypher-template assumption
   that would have to be unwound (it should be clean — `Identifiers` is only added at the Cypher layer
   per ADR-010, not the generic layer).

## Constraints

- **No production code.** This is a decision task. The only writes permitted are: updating the two ADR
  files' `Status` (and, if refuted, ADR-010's Decision/Consequences), and appending a short outcome
  note to `.agentic/reviews/2026-06-10-query-alignment-grilling.md`.
- Do not start E17 T1 / T7 / T8 — those are downstream of this gate.
- If GQLAlchemy code is too sparse to decide (the catalogue is unbuilt — E8 is "planned"), say so
  explicitly and record the decision as "deferred — insufficient GraphORM surface to validate;
  ADR-010 scoped Cypher-only for now, revisit at E8." That is a valid, honest outcome.

## Deliverable

A short report stating: **(a)** does the `Identifiers`/`Params` split survive GQLAlchemy — yes / no /
insufficient-evidence; **(b)** the paper sketches for the 2–3 example queries; **(c)** the resulting
ADR status changes made; **(d)** any follow-on noted for E8. Then flip ADR-010 and ADR-009 to
`Accepted` (if validated) or revise ADR-010 to Cypher-only scope (if refuted) or leave `Proposed`
with a recorded deferral (if insufficient evidence).
