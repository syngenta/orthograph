# How Query Validation Works

**Query validation** ensures that a Cypher query — or a whole query catalogue —
is consistent with a declared `GraphDefinition`. It is the third of Orthograph's
validation engines (alongside data validation and database comparison), and the
only one that operates purely on static artefacts: no database connection is
needed.

The public surface lives in `orthograph.queries` and exposes a clean
**2 × 2 matrix** of verbs: two phases (syntax-only vs semantic) crossed with
two input grades (a whole query object vs raw Cypher pieces). See
[ADR-043](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/043-query-validation-public-api-two-phases-two-input-grades.md)
for the rationale behind the surface design.

→ **Tutorials:** {ref}`Pillar 3 — Query management & validation <query-management-validation>`
  walks through syntax checking, semantic validation, and catalogue governance.
  Start with {doc}`../notebooks/03.02_cypher_query_definitions`.

---

## Why static validation matters

Writing a Cypher query that references a label or property is an implicit
contract. If the graph schema evolves — a label is renamed, a property is
dropped — the query silently produces wrong results or no results at all.
Orthograph makes that implicit contract explicit: register the query in a
catalogue, validate the catalogue against the definition, and the mismatch is
reported at governance time, before any query touches a database.

---

## The two-phase, two-grade surface

```python
from orthograph.queries import (
    # OBJECT MODE — pass a whole query object
    check_syntax,               # syntax only; never takes a GraphDefinition
    validate,                   # syntax + semantics; GraphDefinition required
    validate_catalogue,         # whole catalogue, syntax + semantics
    validate_catalogue_against_profile,

    # PIECES MODE — pass raw Cypher + declared field-name sets
    check_cypher_spec,          # syntax only
    validate_cypher_spec,       # syntax + semantics; GraphDefinition required
)
```

**Phase rule:** A `check_*` verb runs **syntax only** and never accepts a
`GraphDefinition`. A `validate*` verb runs **syntax + semantics** and always
requires one. There is no optional definition toggle on any verb.

**Grade rule:** Object mode (a `CypherQuery`, `ReadQuery`, or `WriteQuery`)
is the front door — the verb reads the template and declared fields off the
object. Pieces mode (`cypher` string + `params_fields` set) is the escape hatch
for quick validation without constructing a query object.

For a description of query object kinds, see [Query management](query-management.md).

---

## Algorithmic overview

> **Placeholder** — this section will be expanded with full algorithmic detail
> in the E61 documentation phase. The outline below describes the high-level
> procedure; the governing decisions are linked throughout.

### Step 1 — Query extraction (object mode only)

Object-mode verbs reduce the input to a `(cypher_template, params_fields,
identifier_fields)` triple via a single internal dispatcher. The dispatcher
handles:

- `str` — zero declared params, no identifiers.
- `CypherQuery` — `params_schema` fields → `params_fields`;
  `identifiers_schema` fields → `identifier_fields`.
- `ReadQuery` / `WriteQuery` — same as `CypherQuery` via `getattr`.

### Step 2 — Syntax phase (both verbs)

The Cypher template is passed to the **graphglot** parser
(`src/orthograph/cypher/parser.py`). Parse errors surface as
`CYPHER_SYNTAX_ERROR` issues.

If `params_fields` is non-empty, the parser checks that every `$param`
placeholder used in the template appears in the declared set and vice versa
(alignment check). Same for `<<identifier>>` slots and `identifier_fields`.

`check_syntax` / `check_cypher_spec` stop here.

### Step 3 — Semantic phase (`validate*` verbs only)

The parsed query's node labels, relationship labels, and property keys are
extracted and checked against the `GraphDefinition`:

- **Label check** — every label referenced in the query must be declared in the
  definition (either as a node label or a relationship label).
- **Property check** — every property referenced on a node or relationship must
  be declared for that type.
- **Endpoint check** — a `MATCH (a:A)-[:REL]->(b:B)` pattern is checked against
  the declared `(source_label, REL, target_label)` triple.

Each mismatch produces a `ValidationIssue` with a code such as
`UNDECLARED_LABEL`, `UNDECLARED_PROPERTY`, or `ENDPOINT_MISMATCH`.

### Step 4 — Catalogue validation

`validate_catalogue` runs steps 1–3 for every registered query in the catalogue
and collects all issues into a single `ValidationResult`. This is the bulk
governance function — call it after a definition update to surface every
affected query at once.

`validate_catalogue_against_profile` additionally cross-checks the catalogue
against a `GraphProfile`, surfacing discrepancies between what the definition
declares and what the database actually contains.

---

## Implementation locations

| Concern | Module |
|---|---|
| Six public verbs | `src/orthograph/queries.py` |
| Syntax parser | `src/orthograph/cypher/parser.py` |
| Semantic validation engine | `src/orthograph/cypher/validation.py` |
| Identifier guard | `src/orthograph/cypher/identifiers.py` |
| Query-kind dispatch | `src/orthograph/cypher/validation.py` (internal) |
