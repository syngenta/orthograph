# ADR-043: Query Validation Public API — Two Phases × Two Input Grades

**Date:** 2026-06-29
**Status:** Accepted
**Category:** api surface / query validation
**Relates to:** ADR-041 (root capability modules), E56 (distillation), E60 (query shape alignment)
**Implemented by:** E59 (query validation public API)

---

## Context

The package is about to gain its first external consumers, so the query
validation surface must be frozen and documentable before the release.

The surface that exists today overloads two unrelated axes onto a single verb:

```python
# orthograph/queries.py  (current)
def validate_query(query: str | CypherQuery, definition: GraphDefinition) -> ValidationResult:
    if isinstance(query, CypherQuery):
        return _cypher_validation.validate_cypher_query(query, definition)
    return validate_cypher(query=query, graph_definition=definition)
```

Two problems hide inside `validate_query` and the functions it calls:

1. **Kind axis** — the query can be a raw Cypher `str`, a `CypherQuery`
   (simple/YAML), or a typed `ReadQuery`/`WriteQuery`. A future OGM kind
   (GqlAlchemy, neomodel) is anticipated. The typed kind has **no public verb**
   at all today — it can only be validated by registering it in a catalogue.

2. **Phase axis** — validation is two things: **syntactic** (parse + `$param`
   / `<<id>>` alignment, via graphglot) and **semantic** (labels / properties /
   endpoints checked against a `GraphDefinition`). Today the phase is selected
   *implicitly* by whether a `GraphDefinition` is passed: `definition=None` →
   syntactic only; `definition` given → syntactic + semantic. The presence of an
   argument silently changes what the function *does*.

There are also three near-identical internal names — `validate_cypher`,
`validate_cypher_query`, `validate_typed_cypher_query` — that leak the type
taxonomy and are impossible to disambiguate from a docstring.

A documentation author cannot write one clean sentence per verb against this
surface.

---

## Decision

Model the surface as an explicit **2 × 2 matrix**: **phase** (check / validate)
× **input grade** (object / pieces). Four public verbs result, plus the two
catalogue verbs (unchanged in shape).

### 1. Phase axis — `check_*` never takes a definition; `validate*` always requires one

The implicit `definition: GraphDefinition | None` phase-toggle is **removed from
the entire public surface**. The universal rule:

> A `check_*` verb runs **syntax only** and **never** accepts a
> `GraphDefinition`. A `validate*` verb runs **syntax + semantics** and
> **always requires** a `GraphDefinition`. There is no optional definition on
> any public verb, in either input grade.

Semantic-only is not a real cell: label/property checks require a successful
parse, so semantics always implies syntax. The matrix therefore has exactly two
phase columns, both populated.

### 2. Input grade — object mode (a whole query) and pieces mode (raw cypher + declared field sets)

**Object mode** — the front door. The caller passes a *query* and the verb
reads the template and declared params/identifiers off it. The verb is
polymorphic over kinds (`str | CypherQuery | ReadQuery | WriteQuery`); a bare
`str` is the degenerate zero-parameter query.

**Pieces mode** — the advanced escape hatch (already tested, kept public). The
caller passes the raw Cypher plus the declared field-name sets. Used for quick
validation of a Cypher string without first constructing a query object.

The two modes are symmetric — each has a `check_*` and a `validate*` verb:

```python
# orthograph.queries

# OBJECT MODE — pass a whole query
check_syntax(query, *, parser=None)                              # str|CypherQuery|Read|Write
validate(query, definition, *, parser=None)                     # definition REQUIRED
validate_catalogue(catalogue, definition, *, parser=None)
validate_catalogue_against_profile(catalogue, profile, definition, rules=None)

# PIECES MODE — pass raw cypher + declared field-name sets
check_cypher_spec(*, cypher, params_fields, identifier_fields=None,
                  output_model=None, parser=None)
validate_cypher_spec(*, cypher, params_fields, identifier_fields=None,
                     graph_definition, output_model=None, parser=None)  # def REQUIRED
```

### 3. Declared fields are name **sets**, not type maps

`params_fields` / `identifier_fields` are `set[str]` — declared **names only**.
The validation engine performs name-level *alignment* (`$param` used ↔ declared)
and does **not** type-check param values. A `dict[str, type]` would advertise a
type check the engine does not perform and would duplicate the role of
`CypherQuery` / typed-query Pydantic models. If type-aware validation is ever
added, it belongs in **object mode** (where a real Pydantic model exists), not
in the pieces-mode escape hatch.

### 4. `output_model` is optional because it is feature-presence, not a phase toggle

`output_model` (RETURN → Output alignment) is checked only for read queries that
declare a result shape. `WriteQuery`, `CypherQuery`, and bare strings have none.
Optional here means "this query happens to declare an output"; it is not a phase
selector and does not violate the §1 rule.

### 5. The kind-dispatch is one internal, documented function

Object-mode verbs reduce a query to `(cypher, params, identifiers)` via a single
private dispatcher (folding today's two separate extraction sites — the
`CypherQuery` reader and the typed `getattr`/`isinstance` block — into one). The
shared validation pipeline is one private engine that both phases call (syntactic
= no definition, full = with definition). The `graph_definition=None` path
survives **only** as this internal seam; it is never public. The dispatch table
is documented in code so the algorithm can be lifted into user docs verbatim.

### 6. Three taxonomy-leaking primitives become private

`validate_cypher`, `validate_cypher_query`, `validate_typed_cypher_query` are
made private (underscore-prefixed). The four object/pieces verbs plus the two
catalogue verbs cover every public need; these three only leaked the type
taxonomy and were mutually confusable.

### 7. `validate_query` is removed outright — no deprecation shim

The package has no external consumers yet, so the old overloaded
`validate_query` is **removed**, not shimmed. Internal callers, tests, and
notebooks are migrated in the same change.

### 8. Parser configuration — expose the seam now, defer the config object

The graphglot swap-seam already exists internally
(`CypherParserStrategy` Protocol, `parser=` on `parse_cypher`/`validate_cypher`).
Every public verb exposes it as a keyword-only `parser: CypherParserStrategy |
None = None`. Richer syntactic configuration (custom procedures, strip-rules,
dialect selection beyond a parser swap) is **deferred**: with one parser
(graphglot) and zero consumers, a config object would be speculative. The `*,
parser=None` keyword-only slot makes any later addition purely additive and
non-breaking.

---

## Consequences

- A documentation author writes one sentence per verb: phase × grade is a clean
  2 × 2, no conditional behaviour.
- The typed `ReadQuery`/`WriteQuery` kind gains a standalone public verb
  (`check_syntax` / `validate`) for the first time — no catalogue required.
- `validate_query` removal is a hard break, but pre-release with no external
  consumers the blast radius is internal (façade, `tests/surface`,
  `tests/test_root_surface`, ~2 notebooks).
- The `parser=` seam is frozen on all six verbs; a future config object must be
  reachable additively through keyword-only parameters.
- A future OGM kind is absorbed by adding one branch to the internal dispatcher
  plus a guard, with **no new public verb** — the object-mode verbs stay
  polymorphic.
- `validate_cypher_spec` keeps a **required** `graph_definition` (no default),
  diverging from its current `GraphDefinition | None = None`; pieces-mode
  syntactic-only now routes through `check_cypher_spec` instead.

---

## Considered and rejected

- **Single polymorphic `validate(query, definition=None)`** — keeps one name but
  re-introduces the implicit phase-toggle this ADR exists to kill.
- **Three split kind-verbs** (`validate_cypher` / `validate_cypher_query` /
  `validate_typed_cypher_query`) on the façade — multiplies near-identical names,
  leaks the taxonomy, and grows the frozen surface with every new query kind.
- **`dict[str, type]` for declared fields** — advertises a type check the engine
  does not perform and duplicates the Pydantic-model role of `CypherQuery`.
- **Soft-deprecate `validate_query` with a `DeprecationWarning` shim** —
  unnecessary ceremony with zero external consumers; a clean break is cheaper.
