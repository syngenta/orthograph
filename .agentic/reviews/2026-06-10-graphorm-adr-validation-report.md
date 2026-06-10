# Report: ADR-010 / ADR-009 validated against the GraphORM (GQLAlchemy) backend

**Date:** 2026-06-10
**Type:** Research + decision (no production code written).
**Prompt:** `.agentic/reviews/2026-06-10-prompt-validate-adrs-graphorm.md`
**Outcome:** ADR-010 and ADR-009 → **Accepted**.

---

## (a) Verdict

**Yes — the `Identifiers` / `Params` split survives GQLAlchemy.**

The split is a *declaration-level* concept (two named parameter groups). The
`<<placeholder>>` template substitution is the **Cypher-specific rendering** of that
neutral split — exactly as ADR-010 already states. A builder-based backend (GQLAlchemy)
consumes the same two groups through a different `build()`:

- `Identifiers` (labels / relationship types) → **builder method arguments**
  (`node(labels=...)`, `.to(relationship_type=...)`), each validated through
  `validate_identifier` (ADR-008) before the call.
- `Params` (values) → **value bindings** (`.where(prop == value)` / parameter dict).

The verdict is **"yes, confirm in code at E8"**: the GQLAlchemy query catalogue (E8) is
not yet built — today `extensions/gqlalchemy/query_builder.py` validates *rendered Cypher
strings*, it does not yet expose a typed `GqlAlchemyReadQuery` base. The split is therefore
validated on paper against the real builder surface; E8.1 instantiates it in code. This is
not a deferral of the decision — the decision is made — it is a forward note for the
implementation epic.

---

## (b) Paper sketches

The declaration shape is **identical** across backends; only `build()` differs. The
generic base (`orthograph.catalogue.typed.ReadQuery[P, D]`) is never mentioned here — it is
untouched (see check 4).

### Shared declaration (backend-neutral)

```python
class CardinalityIdentifiers(BaseModel):   # the NAMES
    label: str
    rel_type: str

class NoValues(BaseModel):                 # the VALUES (none here)
    pass

class CardinalityRow(BaseModel):           # the OUTPUT
    sample_size: int
    max_degree: int
```

### Sketch 1 — match-by-label (identifier only, no value)

```python
# Cypher backend — declarative, <<label>> spliced, no $value
class CypherNodesByLabel(CypherReadQuery[NoValues, NodeRow]):
    Identifiers = LabelIdentifiers          # {label: str}
    Params      = NoValues
    Output      = NodeRow
    name        = "cypher.nodes_by_label"
    cypher_template = "MATCH (n:`<<label>>`) RETURN n"
    def materialize(self, raw): return NodeRow(**raw)

# GQLAlchemy backend — label lands in node(labels=...)
class GqaNodesByLabel(GqlAlchemyReadQuery[NoValues, NodeRow]):
    Identifiers = LabelIdentifiers
    Params      = NoValues
    Output      = NodeRow
    name        = "gqa.nodes_by_label"
    def build(self, idents: LabelIdentifiers, params: NoValues):
        label = validate_identifier(idents.label, kind="label")
        return match().node(labels=label, variable="n").return_()
    def materialize(self, raw): return NodeRow(**raw)
```

### Sketch 2 — match-by-property-value (value only, no identifier)

This is the **majority case**. It declares **no `Identifiers`** (empty default) and is
byte-for-byte the existing E16 query — no new boilerplate.

```python
# Cypher backend — unchanged from E16; literal label, $value
class CypherMoviesByYear(CypherReadQuery[ReleasedYearValues, Movie]):
    Params = ReleasedYearValues             # {released: int}
    Output = Movie
    name   = "cypher.movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m"
    def materialize(self, raw): return Movie(**raw)
# ^ never mentions Identifiers.

# GQLAlchemy backend — value lands in .where(...)
class GqaMoviesByYear(GqlAlchemyReadQuery[ReleasedYearValues, Movie]):
    Params = ReleasedYearValues
    Output = Movie
    name   = "gqa.movies_by_year"
    def build(self, idents, params: ReleasedYearValues):
        return (match().node(labels="Movie", variable="m")
                       .where("m.released", "=", params.released)
                       .return_())
    def materialize(self, raw): return Movie(**raw)
```

### Sketch 3 — relationship query (identifier label + rel-type)

```python
# Cypher backend — two identifiers spliced
class CypherCardinality(CypherReadQuery[NoValues, CardinalityRow]):
    Identifiers = CardinalityIdentifiers    # {label, rel_type}
    Params      = NoValues
    Output      = CardinalityRow
    name        = "cypher.cardinality"
    cypher_template = (
        "MATCH (n:`<<label>>`) OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->() "
        "WITH n, count(r) AS degree "
        "RETURN max(degree) AS max_degree, count(n) AS sample_size"
    )
    def materialize(self, raw): return CardinalityRow(**raw)

# GQLAlchemy backend — both identifiers as builder args
class GqaCardinality(GqlAlchemyReadQuery[NoValues, CardinalityRow]):
    Identifiers = CardinalityIdentifiers
    Params      = NoValues
    Output      = CardinalityRow
    name        = "gqa.cardinality"
    def build(self, idents: CardinalityIdentifiers, params: NoValues):
        label = validate_identifier(idents.label, kind="label")
        rel   = validate_identifier(idents.rel_type, kind="relationship type")
        return (match().node(labels=label, variable="n")
                       .to(relationship_type=rel).node(variable="m")
                       .return_({"count(n)": "sample_size", "max(...)": "max_degree"}))
    def materialize(self, raw): return CardinalityRow(**raw)
```

### Where each declared parameter lands

| Declared group | Cypher backend | GQLAlchemy backend |
|---|---|---|
| `Identifiers.label` | `` `<<label>>` `` text slot | `.node(labels=...)` arg |
| `Identifiers.rel_type` | `` `<<rel_type>>` `` text slot | `.to(relationship_type=...)` arg |
| `Params` (values) | `$value`, driver-substituted | `.where(prop == value)` binding |
| identifier safety | `validate_identifier` before splice | `validate_identifier` before builder call |

GQLAlchemy never sees a `<<...>>`. Same declaration; different `build()`.

---

## (c) Concrete-check results

1. **Sketches (per check 1):** done above — three representative queries, each as a
   `ReadQuery` subclass with `Identifiers` + `Params`, both backends.

2. **`build() -> Any` permits a builder return (check 2): PASS.**
   `typed.py:105` declares `build(self, params: P) -> Any` — it does **not** promise
   `(cypher, dict)`. The Cypher tuple narrowing (`CypherQuery = tuple[str, dict]`) lives
   only in `base_models.py:61`. `Executor.read/write` (`typed.py:170,176`) take the query
   and return `list[D]`/`R`; they never inspect `build()`'s return shape. A GQLAlchemy
   `build()` returning a builder object is already contract-legal at the generic layer.

3. **Identifier safety has a home (check 3): PASS, with a noted obligation.**
   In Cypher: `validate_identifier` + splice (ADR-008 / E17 T1). In GQLAlchemy: the label
   is passed to a builder method; `ValidatedQueryBuilder` validates the *rendered* Cypher
   against the model (`query_builder.py:92-96`) but does **not** itself escape/validate the
   identifier argument. Therefore Orthograph must call `validate_identifier` inside the
   GraphORM `build()` **before** the builder call — same authority, same grammar, different
   call site. The split's identifier group keeps a clear, single job in both backends.

4. **Generic base bakes in no Cypher assumption (check 4): PASS.**
   `typed.py` imports nothing DB-specific (asserted in its own module docstring), declares
   no `cypher_template`, no `Identifiers`, no `<<placeholder>>`. All of that is added only
   at the Cypher layer per ADR-010. Nothing to unwind.

---

## (d) Follow-on findings

### D-1 — No empty-key tax on value-only queries (implementation pin)

ADR-010 states `Identifiers` is **opt-in with an empty default**. The implementation must
honour this by giving the **Cypher base** a default empty `Identifiers` model
(`CypherReadQuery.Identifiers = _NoIdentifiers`) and keeping the **generic signature
`ReadQuery[P, D]` (2 params) unchanged**. A value-only query (Sketch 2) declares no
`Identifiers` and is identical to the E16 query of today.

The grilling log's "Sketch C" shows `CypherReadQuery[Identifiers, Params, Output]` (3
generic params) and itself flags "does a 3rd generic param break E16's signature?" as an
**open** sub-question. **Resolved by this report: Sketch C is illustrative only and is
rejected as the implementation shape.** The 3-param generic is NOT adopted; the empty
default lives at the Cypher layer. This is an E17 implementation detail and does **not**
affect the backend-neutrality verdict (the split is a declaration concern, not a
generic-arity concern).

### D-2 — E8 confirms the split in code

E8.1 will instantiate `GqlAlchemyReadQuery` with the `Identifiers`/`Params` groups and a
builder-returning `build()`, closing the "confirm in code" half of the verdict. Tracked as
an E8 acceptance criterion.

---

## (e) ADR status changes made

- **ADR-010** `Proposed → Accepted`. The "Open / to confirm" Consequences bullet rewritten
  to "Resolved", citing this report; implementation note added (empty-default `Identifiers`
  at Cypher layer, generic `[P, D]` unchanged, confirm in code at E8).
- **ADR-009** `Proposed → Accepted` (its only gate was ADR-010 acceptance).
- Outcome note appended to `.agentic/reviews/2026-06-10-query-alignment-grilling.md`
  (D4 GraphORM sub-question resolved; generic-arity sub-question resolved-by-decision).

No production code changed. No `src/` file touched. E17 T1/T7/T8 and E8 not started.
