# Session: Pre-E16 query alignment — grilling notes

> Transient working record. Decisions migrate to ADRs / epics when settled.
> Date: 2026-06-10. Anchor epic: E18 (boundary kept open; overlaps E17 STEP 5).

## Scope agreed

- Deliverable is **conceptual** — decide roles + target architecture + ADRs, defer the rewrite.
- Three pre-E16 query populations in scope:
  1. Inspector query strategies — `neo4j/queries.py`, `memgraph/queries.py`
  2. CypherGenerator output — `cypher/generator.py`
  3. NetworkX inspector internals — `networkx/inspector.py` (no Cypher; can only align on GraphProfile shape)

## Decisions so far

- **D1.** `inspect() -> GraphProfile` is the only contract shared across ALL THREE backends.
  NetworkX can never speak a Cypher-query contract.
- **D2 (altitude reconciliation).** For the TWO Cypher backends, internal introspection queries
  SHOULD become `CypherReadQuery` subclasses run through `CypherExecutor` (library eats its own
  cooking). `GraphProfile` stays the cross-backend currency; typed CypherReadQuery is the
  intra-Cypher-backend mechanism. Per-query `Params`/`Output` may differ entirely between Neo4j
  and Memgraph (Neo4j = per-label, Memgraph = bulk). `QueryStrategy` Protocol retired/demoted.
- **D3 (root technical problem).** Cypher cannot parameterise identifiers (label/rel-type/prop-key).
  Dynamic-label queries therefore cannot use the declarative `cypher_template`; they need an
  imperative `build()` override that splices a *validated* identifier into the text. `validate_identifier`
  does not exist yet (E17 T1).

## Decision: identifier params (D4) — RESOLVED

Rejected both A (custom `__init__`) and B (internal `split_params` switch): each makes an
identifier-query a *visibly different animal* from a value-only query. **Homogeneity, readability
and transparency win** over saving lines. Chosen direction:

- **D4.** Every query OPENLY declares two parameter groups: `Identifiers` (validated + spliced as
  Cypher identifiers) and `Params` (= existing meaning: `$`-substituted values). Queries STAY
  DECLARATIVE — `cypher_template` gains a **distinct, collision-proof placeholder** for identifiers
  (bare `{}` is taken by Cypher map literals; use e.g. `<<label>>`). The Cypher base `build()`
  validates+splices `Identifiers`, passes `Params` as the value dict. Definition-time validator
  extends: `<<ident>>` ↔ `Identifiers` 1:1, `$value` ↔ `Params` 1:1.
- **Generator** (label fixed by model) and **inspector** (label varies per call) use the SAME
  mechanism — generator binds identifier values at synth time, inspector passes them per call.
- **Backend-neutrality:** the `Identifiers`/`Params` *declaration* split is backend-neutral and must
  stay viable for a future GraphORM base; the *placeholder-in-template* handling is Cypher-only
  (GraphORM would consume `Identifiers` via builder calls — TO BE INVESTIGATED).
- Delimiter choice + this whole mechanism → recorded in an ADR (hard to reverse: becomes part of
  every consumer's query-authoring surface).

### Sketch C (chosen shape)

```python
class CardinalityIdentifiers(BaseModel):
    label: str
    rel_type: str

class CardinalityValues(BaseModel):
    pass

class CardinalityQuery(CypherReadQuery[CardinalityIdentifiers, CardinalityValues, CardinalityRow]):
    Identifiers = CardinalityIdentifiers
    Params      = CardinalityValues
    Output      = CardinalityRow
    name = "neo4j.cardinality"
    cypher_template = (
        "MATCH (n:`<<label>>`) OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->() "
        "WITH n, count(r) AS degree "
        "RETURN min(degree) AS min_degree, max(degree) AS max_degree, "
        "avg(degree) AS avg_degree, count(n) AS sample_size"
    )
    def materialize(self, raw): return CardinalityRow(**raw)

# consumer value query — same skeleton:
class MoviesByYear(CypherReadQuery[NoIdentifiers, ReleasedYearValues, Movie]):
    Identifiers = NoIdentifiers
    Params      = ReleasedYearValues   # released: int
    Output      = Movie
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m"
```

### OPEN sub-questions on D4
- Exact delimiter (`<<x>>` vs `${{x}}` vs `:x:`) — pick one in the ADR.
- Does adding a 3rd generic param (`Identifiers`) to `CypherReadQuery[P, D]` break E16's existing
  signature? (Backward-compat: empty `Identifiers` default so existing queries don't change.)
- GraphORM viability of the `Identifiers` split — investigate before finalising the ADR.

### OUTCOME (2026-06-10) — D4 sub-questions closed
- **Delimiter:** `<<name>>` chosen and recorded in ADR-010.
- **3rd generic param: RESOLVED — rejected.** The empty-default `Identifiers` lives at the
  **Cypher base layer** (`CypherReadQuery.Identifiers = _NoIdentifiers`); the generic signature
  stays `ReadQuery[P, D]` (two params, unchanged). Sketch C's
  `CypherReadQuery[Identifiers, Params, Output]` is illustrative only and is NOT the
  implementation shape. Value-only queries declare no `Identifiers` and are byte-for-byte the E16
  query. This is an E17 implementation detail; it does not affect the decision.
- **GraphORM viability: RESOLVED — split survives.** Validated against the GQLAlchemy builder
  surface — see `.agentic/reviews/2026-06-10-graphorm-adr-validation-report.md`. `Identifiers` →
  builder args (`node(labels=...)`, validated via `validate_identifier`); `Params` → value
  bindings; `<<placeholder>>` is the Cypher-only rendering of the neutral split. The generic base
  (`build() -> Any`) already permits a builder return and bakes in no Cypher assumption.
- **Result:** ADR-010 → **Accepted**; ADR-009 (its dependant) → **Accepted**. Confirm in code at
  E8.1 (`GqlAlchemyReadQuery` instantiates both groups + builder `build()`).

## Decision: E18 decomposition (D5) — RESOLVED

- **D5.** Split E18.
  - E18.2 (max_degree), E18.3 (Mermaid `<br>`), E18.4 (stacklevel), E18.5 (deprecation shim)
    STAY in E18 "Validation Correctness" — independent, cheap, do now.
  - **E18.1 (rel endpoint source/target labels) MOVES into the query-alignment epic.** The fix is a
    NEW introspection query; it should be born as a typed `CypherReadQuery`
    (`Identifiers = {rel_type}`), not bolted onto the `QueryStrategy` Protocol being retired (D2).
    Rewrite E18.1's acceptance criteria to target the typed query + the per-backend `inspect()` wiring
    (Neo4j must populate source/target labels; check Memgraph; NetworkX already does).

## Decision: backward-compat (D6) — RESOLVED

- **D6.** `Identifiers` is OPT-IN, empty default. A query with no `<<placeholders>>` and no declared
  `Identifiers` is the unchanged E16 query; hardcoded literal labels (`:Movie`) stay legal and
  idiomatic. The mechanism is only for DYNAMIC identifiers. No existing E16 query changes.

## Decision: NetworkX / non-DB alignment (D7) — RESOLVED

- **D7.** "Inspection mechanism alignment across extensions" = all three inspectors produce the SAME
  COMPLETE `GraphProfile`. It is OUTPUT-SHAPE parity, not shared internal structure. **NetworkX is the
  reference** — it already fills `source_labels`/`target_labels` and `cardinality_stats`. Its
  object-walking mechanism stays idiomatic; no internal change. The DB backends catch up to it.
  Cross-backend contract stays `inspect() -> GraphProfile` (D1).

### Completeness matrix (the catch-up work this implies)
| Field | NetworkX | Neo4j | Memgraph |
|-------|----------|-------|----------|
| node/rel property profiles | ✓ | ✓ | ✓ (mandatory-heuristic, count=0) |
| `source_labels`/`target_labels` | ✓ | ✗ (E18.1 → alignment epic) | ✗ |
| `cardinality_stats` | ✓ | ✓ (first non-empty label) | ✗ |
| node/rel `count` | ✓ | ✓ | ✗ (count=0) |

## Decision: Memgraph parity (D8) — RESOLVED

- **D8.** Close Memgraph's validation-coverage gaps to Neo4j parity wherever Memgraph's query surface
  allows: add typed introspection queries for node/rel `count`, `cardinality_stats` (the Neo4j
  `MATCH ... count(r)` pattern already works on Memgraph), and endpoint `source_labels`/`target_labels`.
  Where a metric is genuinely unavailable from Memgraph procedures, DOCUMENT the gap explicitly so it
  is KNOWN, not silent. Makes PRD US5 ("same interface as Neo4j") honest. Folds into the alignment
  epic (same root cause as E18.1: empty profile fields → silently skipped checks).

## SUPERSEDED — earlier A/B sketches (kept for ADR "alternatives considered")

### Option A — identifiers via constructor; Params = values only

```python
class _EmptyParams(BaseModel):
    pass

class CardinalityQuery(CypherReadQuery[_EmptyParams, CardinalityRow]):
    Params = _EmptyParams
    Output = CardinalityRow
    name = "neo4j.cardinality"

    def __init__(self, label: str, rel_type: str) -> None:
        self._label = validate_identifier(label, kind="label")
        self._rel   = validate_identifier(rel_type, kind="relationship type")

    def build(self, params: _EmptyParams) -> CypherQuery:
        cypher = (f"MATCH (n:`{self._label}`) "
                  f"OPTIONAL MATCH (n)-[r:`{self._rel}`]->() "
                  "WITH n, count(r) AS degree "
                  "RETURN min(degree) AS min_degree, max(degree) AS max_degree, "
                  "avg(degree) AS avg_degree, count(n) AS sample_size")
        return cypher, params.model_dump()

    def materialize(self, raw): return CardinalityRow(**raw)
```
Loop: `for l in labels: for r in rels: executor.read(CardinalityQuery(l, r), {})`
- Pro: Params means ONE thing (value bindings). No new machinery.
- Con: query not a singleton; label NOT visible in describe()/params_schema.

### Option B — identifiers as annotated Params fields

```python
class CardinalityParams(BaseModel):
    label:    Annotated[str, Identifier(kind="label")]
    rel_type: Annotated[str, Identifier(kind="relationship type")]

class CardinalityQuery(CypherReadQuery[CardinalityParams, CardinalityRow]):
    Params = CardinalityParams
    Output = CardinalityRow
    name = "neo4j.cardinality"

    def build(self, params: CardinalityParams) -> CypherQuery:
        idents, values = split_params(params)   # shared helper reads Annotated markers + validates
        lbl, rel = idents["label"], idents["rel_type"]
        cypher = (f"MATCH (n:`{lbl}`) OPTIONAL MATCH (n)-[r:`{rel}`]->() ... ")
        return cypher, values
```
Loop: `executor.read(CardinalityQuery(), CardinalityParams(label=l, rel_type=r))`
- Pro: query stays a registerable singleton; label visible in describe()/params_schema.
- Con: needs new `Identifier` marker + `split_params` helper; every author must use it.

Both leave the contract (`build()->Any`, 4 ClassVars) unchanged. Neither requires a new class.
