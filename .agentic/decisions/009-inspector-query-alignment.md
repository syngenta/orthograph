# ADR-009: Inspector Query Alignment and GraphProfile Completeness Parity

**Date:** 2026-06-10
**Status:** Accepted
**Category:** extensions / inspection

## Context

The library proposes a typed query contract (`CypherReadQuery` + `QueryCatalogue` +
`CypherExecutor`) to its consumers, yet runs its **own** introspection queries as raw
f-string Cypher behind a `QueryStrategy` Protocol — and that Protocol only exists for Neo4j.
Memgraph uses an unrelated `MemgraphQueries` class with different method signatures, and
NetworkX has no query layer at all. The library "does not eat its own cooking."

Separately, a completeness audit of `inspect() -> GraphProfile` across the three inspectors
exposed a silent-validation gap: `GraphProfile` fields left empty cause `validate_profile`
to skip checks with no error (the same bug class E18 was created to fix).

| GraphProfile field | NetworkX | Neo4j | Memgraph |
|--------------------|----------|-------|----------|
| property profiles | yes | yes | partial (mandatory-heuristic, count=0) |
| source/target labels | yes | **no** | **no** |
| cardinality_stats | yes | yes | **no** |
| node/rel count | yes | yes | **no** |

For Neo4j this means `INVALID_ENDPOINT` is never emitted; for Memgraph, endpoint, cardinality
and count-based checks are all silently skipped — contradicting PRD User Story 5 ("inspect a
live Memgraph database with the same interface I use for Neo4j").

## Considered Options

- **Leave inspector queries as `QueryStrategy` strings, fix only the empty fields.** Cheapest;
  keeps the eat-own-cooking contradiction and the Neo4j-only Protocol asymmetry.
- **Force a single cross-backend query Protocol over Neo4j + Memgraph.** Rejected: Neo4j
  introspects per-label, Memgraph in bulk — one Protocol would distort one of them.
- **Type the Cypher-backend inspector queries; keep `inspect()->GraphProfile` as the only
  cross-backend contract (CHOSEN).**

## Decision

1. **`inspect() -> GraphProfile` is the only contract shared across all three backends.**
   NetworkX has no Cypher and can never speak a Cypher-query contract; its object-walking
   mechanism stays idiomatic and unchanged. NetworkX is the **completeness reference** — it
   already populates every `GraphProfile` field.

2. **For the two Cypher backends, internal introspection queries become typed
   `CypherReadQuery` subclasses** run through `CypherExecutor`, registered in an internal
   `QueryCatalogue`. Their `Output` types are projection models that `materialize()` into the
   existing `NodeTypeProfile`/`PropertyProfile`/etc. The dynamic label/rel-type is carried as a
   declared identifier parameter per ADR-010. The `GraphProfile` remains the cross-backend
   currency; per-query `Params`/`Output` may differ entirely between Neo4j (per-label) and
   Memgraph (bulk). The `QueryStrategy` Protocol is retired (APOC vs pure-Cypher becomes two
   `CypherReadQuery` subclass sets selected at construction).

3. **Completeness parity.** Neo4j and Memgraph must populate the same `GraphProfile` fields as
   NetworkX wherever the backend's query surface allows — including `source_labels`/
   `target_labels` (the original E18.1 fix, now delivered here as a typed query), cardinality,
   and counts. Metrics genuinely unavailable from a backend's procedures are **documented
   explicitly** so the gap is known, not silent.

## Consequences

- The library uses internally the same typed-query + executor + catalogue pattern it proposes
  to consumers.
- `INVALID_ENDPOINT` and `CARDINALITY_VIOLATION` fire for Neo4j and (where supported) Memgraph,
  closing the silent-skip class of bug for live databases.
- **Scope move:** E18.1 (rel endpoint labels) leaves the "Validation Correctness" epic and is
  delivered here as a typed introspection query; E18 retains only its independent cheap fixes
  (max_degree, Mermaid `<br>`, stacklevel, deprecation shim). This work is the substance of
  E17 STEP 5 (T7/T8), widened to include Memgraph parity.
- **Depends on ADR-010** (declared identifier parameters) and **ADR-008** (`validate_identifier`).
  ADR-010 was accepted 2026-06-10 (the GraphORM backend-neutrality gate closed — see
  `.agentic/reviews/2026-06-10-graphorm-adr-validation-report.md`), so this dependency is
  satisfied and this ADR is `Accepted`.

## Relates to

- E17 (CypherGenerator hardening — STEP 5 inspector realignment).
- E18 (Validation Correctness — E18.1 reassigned here).
- ADR-010 (declared identifier parameters), ADR-008 (identifier safety), ADR-003 (two-phase
  inspect-then-validate), PRD User Story 5.

---

## T7 Scoping Annex — Inspector Query Typed-Wrapper Design

**Date:** 2026-06-10
**Author:** E17 T7 scoping pass
**Status:** Scoping complete — ready for T8 implementation

This annex documents the full surface analysis required by T7 before any production code is
written: Cypher text, interpolated identifiers, result-row shapes, target `Params`/`Identifiers`
models, target `Output` models, and identifier-safety approach for every inspector query across
all three strategy classes. It then records the Option A / Option B decision and the
`QueryStrategy` disposition.

---

### 1. Reference inventory

**Source files read:**

| File | Lines | Contents |
|------|-------|----------|
| `src/orthograph/extensions/neo4j/queries.py` | 112 | `QueryStrategy` Protocol, `ApocQueryStrategy`, `CypherQueryStrategy` |
| `src/orthograph/extensions/memgraph/queries.py` | 30 | `MemgraphQueries` |
| `src/orthograph/extensions/models.py` | 102 | `PropertyProfile`, `CardinalityStats`, `ConstraintInfo`, `NodeTypeProfile`, `RelationshipTypeProfile`, `GraphProfile` |
| `src/orthograph/extensions/neo4j/inspector.py` | 198 | Inline result-mapping for all Neo4j queries |
| `src/orthograph/extensions/memgraph/inspector.py` | 136 | Inline result-mapping for all Memgraph queries |
| `src/orthograph/extensions/cypher/base_models.py` | 301 | `CypherReadQuery`, `CypherWriteQuery`, `Identifiers`/`<<placeholder>>` mechanism |
| `src/orthograph/extensions/cypher/identifiers.py` | 56 | `validate_identifier`, `escape_identifier` |

---

### 2. Neo4j — `ApocQueryStrategy` (6 methods)

#### 2a. `node_labels()`

**Cypher:**
```cypher
CALL db.labels() YIELD label RETURN label
```

**Interpolated identifiers:** none.

**Result-row shape:** `{"label": str}`

**Target `Params` model:** `Params = NoParams` (no `$` placeholders, no `<<>>` slots).

**Target `Identifiers` model:** `Identifiers = NoIdentifiers`.

**Target `Output` model:** new thin projection `NodeLabelRow(BaseModel): label: str`.
(`materialize` returns `NodeLabelRow`; the inspector collects the strings for
`_get_labels()`.)

**Notes:** Identical between `ApocQueryStrategy` and `CypherQueryStrategy`. One shared
`CypherReadQuery` subclass `InspectNodeLabelsQuery` covers both strategies — register under
the same catalogue name.

---

#### 2b. `rel_types()`

**Cypher:**
```cypher
CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType
```

**Interpolated identifiers:** none.

**Result-row shape:** `{"relationshipType": str}`

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:** `Identifiers = NoIdentifiers`.

**Target `Output` model:** new thin projection `RelTypeLabelRow(BaseModel): relationship_type: str`
(field alias `"relationshipType"` via Pydantic `model_config` `populate_by_name=True` or
`Field(alias=...)`).

**Notes:** Identical between the two Neo4j strategies. Shared class.

---

#### 2c. `node_properties(label: str)` — APOC variant

**Cypher:**
```cypher
CALL apoc.meta.nodeTypeProperties({sample: -1})
YIELD nodeType, nodeLabels, propertyName, propertyTypes, mandatory, propertyObservations, totalObservations
WHERE '<<label>>' IN nodeLabels
RETURN propertyName, propertyTypes, mandatory, propertyObservations, totalObservations
```

> Note: the current implementation uses a Python `.format(label=label)` string substitution
> which inlines the label as a bare string inside a Cypher string literal (`WHERE '<label>' IN
> nodeLabels`). In the typed design this is **a Cypher string-value filter, not an identifier
> interpolation** — the label appears inside single quotes `'...'` in the original query, so it
> is treated as a string constant by the Cypher engine, not an identifier. Nevertheless it is
> caller-supplied data embedded in query text, so it must still pass through
> `validate_identifier` (the safe-identifier grammar guarantees it cannot break out of the
> string-literal context via a backtick or closing-quote attack on the APOC path).

**Interpolated identifiers (in the identifier-safety sense):** `label` — embedded as a string
literal inside `WHERE '<<label>>' IN nodeLabels`. Kind: `"label"`.

**Result-row shape:**
```python
{
    "propertyName": str,
    "propertyTypes": list[str],
    "mandatory": bool,
    "propertyObservations": int,
    "totalObservations": int,
}
```

**Target `Params` model:** `Params = NoParams` (no `$` Cypher parameter placeholders in this
query — the label is a template identifier, not a value).

**Target `Identifiers` model:**
```python
class NodeLabelIdentifiers(BaseModel):
    label: str   # kind="label" (not *_rel_type)
```

**Template:** `"WHERE '<<label>>' IN nodeLabels"` — the `<<label>>` placeholder is inside
single quotes; `validate_identifier` still validates `label` before substitution.

**Target `Output` model:** new intermediate projection:
```python
class NodePropertyRow(BaseModel):
    property_name: str          # alias "propertyName"
    property_types: list[str]   # alias "propertyTypes"; default []
    mandatory: bool             # alias "mandatory"
    property_observations: int  # alias "propertyObservations"
    total_observations: int     # alias "totalObservations"
```
`materialize()` returns `NodePropertyRow`; the inspector's `_build_node_profile` aggregates
multiple rows into `PropertyProfile` and then `NodeTypeProfile`.

---

#### 2d. `rel_properties(rel_type: str)` — APOC variant

**Cypher:**
```cypher
CALL apoc.meta.relTypeProperties({sample: -1})
YIELD relType, propertyName, propertyTypes, mandatory, propertyObservations, totalObservations
WHERE relType = ':`<<rel_type>>`'
RETURN propertyName, propertyTypes, mandatory, propertyObservations, totalObservations
```

> Note: the current implementation embeds `rel_type` inside the APOC `WHERE relType = ':\`{rel_type}\`'`
> string literal (backtick-quoted label-form inside a string value). `rel_type` is a
> relationship-type identifier appearing inside the APOC metadata string value — same
> string-literal-in-query reasoning as `node_properties`.

**Interpolated identifiers:** `rel_type` — embedded inside a string literal in the WHERE
clause. Kind: `"relationship type"`.

**Result-row shape:**
```python
{
    "propertyName": str,
    "propertyTypes": list[str],
    "mandatory": bool,
    "propertyObservations": int,
    "totalObservations": int,
}
```
(Same shape as `node_properties`.)

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:**
```python
class RelTypeIdentifiers(BaseModel):
    rel_type: str   # name ends in _rel_type → kind="relationship type"
```

**Template:** `"WHERE relType = ':\`<<rel_type>>\`'"`.

**Target `Output` model:** same `NodePropertyRow` projection as 2c (the column names are
identical).

---

#### 2e. `cardinality(label: str, rel_type: str)` — shared between APOC and CypherQueryStrategy

**Cypher:**
```cypher
MATCH (n:`<<label>>`)
OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->()
WITH n, count(r) AS degree
RETURN min(degree) AS min_degree, max(degree) AS max_degree,
       avg(degree) AS avg_degree, count(n) AS sample_size
```

> The current implementations use f-string backtick-quoting (`f"\`{label}\`"`).
> In the typed design, both identifiers move to `Identifiers`/`<<placeholder>>` with
> backtick quoting preserved in the `cypher_template` literal around each `<<name>>` slot:
> `` MATCH (n:`<<label>>`) ``.

**Interpolated identifiers:** `label` (kind `"label"`) and `rel_type` (kind `"relationship
type"`). Both already backtick-quoted in the current raw strings — the template preserves the
backtick wrapper around each `<<name>>` slot.

**Result-row shape:**
```python
{
    "min_degree": int,
    "max_degree": int,
    "avg_degree": float,
    "sample_size": int,
}
```

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:**
```python
class CardinalityIdentifiers(BaseModel):
    label: str       # kind="label"
    rel_type: str    # kind="relationship type"
```

**Target `Output` model:** `CardinalityStats` (already exists in `models.py`). Field names
match directly: `min_degree`, `max_degree`, `avg_degree`, `sample_size`. `materialize()` is
`CardinalityStats.model_validate(raw)`.

**Notes:** This is **one shared subclass** for both `ApocQueryStrategy.cardinality` and
`CypherQueryStrategy.cardinality` — the Cypher is byte-for-byte identical.

---

#### 2f. `constraints()` — shared between APOC and CypherQueryStrategy

**Cypher:**
```cypher
SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties, propertyType
```

**Interpolated identifiers:** none.

**Result-row shape:**
```python
{
    "name": str | None,
    "type": str,
    "entityType": str,
    "labelsOrTypes": list[str],
    "properties": list[str],
    "propertyType": str | None,
}
```

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:** `Identifiers = NoIdentifiers`.

**Target `Output` model:** `ConstraintInfo` (already exists in `models.py`). `materialize()`
maps with field aliases (`type` → `constraint_type`, `labelsOrTypes` → `labels`).

**Notes:** Shared between `ApocQueryStrategy.constraints` and `CypherQueryStrategy.constraints`
— identical Cypher text.

---

### 3. Neo4j — `CypherQueryStrategy` (6 methods, pure-Cypher fallback)

`node_labels()`, `rel_types()`, `cardinality()`, and `constraints()` are **identical** to the
APOC variants. No additional subclasses needed; the shared classes above cover them.

#### 3a. `node_properties(label: str)` — CypherQueryStrategy variant

**Cypher:**
```cypher
MATCH (n:`<<label>>`)
WITH count(n) AS total
MATCH (n:`<<label>>`)
UNWIND keys(n) AS key
WITH key, count(*) AS present, total
RETURN key AS propertyName, [] AS propertyTypes,
       present = total AS mandatory,
       present AS propertyObservations, total AS totalObservations
```

> The label appears as a true identifier in a `MATCH` clause — a backtick-quoted node-label
> pattern. This IS an identifier interpolation in the full sense.

**Interpolated identifiers:** `label` (kind `"label"`), backtick-quoted in template.

**Result-row shape:**
```python
{
    "propertyName": str,
    "propertyTypes": list[str],    # always [] in this strategy
    "mandatory": bool,
    "propertyObservations": int,
    "totalObservations": int,
}
```

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:** `NodeLabelIdentifiers` (same as 2c — reuse).

**Target `Output` model:** `NodePropertyRow` (same projection as 2c). `materialize()` is
identical.

**Difference from APOC:** query shape changes (two-pass MATCH vs APOC CALL); the identifier
placement shifts from inside a string literal (APOC) to inside a MATCH pattern (pure Cypher).
These become **two distinct subclasses** with the same `Identifiers` and `Output` types but
different `cypher_template` values — this is exactly the "two subclass sets" decision in
ADR-009.

---

#### 3b. `rel_properties(rel_type: str)` — CypherQueryStrategy variant

**Cypher:**
```cypher
MATCH ()-[r:`<<rel_type>>`]->()
WITH count(r) AS total
MATCH ()-[r:`<<rel_type>>`]->()
UNWIND keys(r) AS key
WITH key, count(*) AS present, total
RETURN key AS propertyName, [] AS propertyTypes,
       present = total AS mandatory,
       present AS propertyObservations, total AS totalObservations
```

**Interpolated identifiers:** `rel_type` (kind `"relationship type"`), backtick-quoted.

**Result-row shape:** same as 3a.

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:** `RelTypeIdentifiers` (same as 2d — reuse).

**Target `Output` model:** `NodePropertyRow` (same projection — reuse).

---

### 4. Memgraph — `MemgraphQueries` (4 methods)

#### 4a. `node_properties()`

**Cypher:**
```cypher
CALL schema.node_type_properties()
YIELD nodeType, nodeLabels, mandatory, propertyName, propertyTypes
```

**Interpolated identifiers:** none — bulk query, no per-label filter.

**Result-row shape:**
```python
{
    "nodeType": str,      # e.g. ":`Person`"
    "nodeLabels": list[str],
    "mandatory": bool,
    "propertyName": str | None,
    "propertyTypes": list[str],
}
```

> The `nodeType` raw string (e.g. `":\`Person\`"`) is stripped of `` :` `` and trailing `` ` ``
> in the current inspector to recover the label string. This stripping logic moves into
> `materialize()`.

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:** `Identifiers = NoIdentifiers`.

**Target `Output` model:** new intermediate projection:
```python
class MemgraphNodePropertyRow(BaseModel):
    node_type: str          # alias "nodeType"
    node_labels: list[str]  # alias "nodeLabels"; default []
    mandatory: bool
    property_name: str | None  # alias "propertyName"
    property_types: list[str]  # alias "propertyTypes"; default []
```
`materialize()` returns `MemgraphNodePropertyRow`. The inspector's `_build_node_profiles()`
aggregates multiple rows; this aggregation logic stays in the inspector (it is orchestration,
not per-row mapping).

---

#### 4b. `rel_properties()`

**Cypher:**
```cypher
CALL schema.rel_type_properties()
YIELD relType, mandatory, propertyName, propertyTypes
```

**Interpolated identifiers:** none — bulk query.

**Result-row shape:**
```python
{
    "relType": str,       # e.g. ":`OWNS`"
    "mandatory": bool,
    "propertyName": str | None,
    "propertyTypes": list[str],
}
```

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:** `Identifiers = NoIdentifiers`.

**Target `Output` model:** new intermediate projection:
```python
class MemgraphRelPropertyRow(BaseModel):
    rel_type: str              # alias "relType"
    mandatory: bool
    property_name: str | None  # alias "propertyName"
    property_types: list[str]  # alias "propertyTypes"; default []
```

---

#### 4c. `constraints()`

**Cypher:**
```cypher
SHOW CONSTRAINT INFO
```

**Interpolated identifiers:** none.

**Result-row shape (Memgraph-specific columns):**
```python
{
    "constraint type": str,
    "entity type": str,
    "label": str,       # present for node constraints
    "properties": list[str],
}
```
> Column names differ from Neo4j (`"constraint type"` with space, no `"name"`/`"propertyType"`).
> The current inspector maps these differently from the Neo4j path.

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:** `Identifiers = NoIdentifiers`.

**Target `Output` model:** new intermediate projection:
```python
class MemgraphConstraintRow(BaseModel):
    constraint_type: str   # alias "constraint type"
    entity_type: str       # alias "entity type"
    label: str | None = None
    properties: list[str] = Field(default_factory=list)
```
`materialize()` returns `MemgraphConstraintRow`. The inspector maps to `ConstraintInfo`.

---

#### 4d. `cardinality(label: str, rel_type: str)`

**Cypher:**
```cypher
MATCH (n:`<<label>>`)
OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->()
WITH n, count(r) AS degree
RETURN min(degree) AS min_degree, max(degree) AS max_degree,
       avg(degree) AS avg_degree, count(n) AS sample_size
```

**Interpolated identifiers:** `label` (kind `"label"`), `rel_type` (kind `"relationship
type"`). Both backtick-quoted. **Identical Cypher to Neo4j cardinality** (both current
implementations share the same f-string pattern).

**Result-row shape:** `{"min_degree": int, "max_degree": int, "avg_degree": float, "sample_size": int}`.

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:** `CardinalityIdentifiers` (reuse from 2e).

**Target `Output` model:** `CardinalityStats` (reuse from 2e). `materialize()` is
`CardinalityStats.model_validate(raw)`.

**Notes:** The Memgraph cardinality query is identical to the Neo4j cardinality query. A
**single shared** `CypherReadQuery` subclass `InspectCardinalityQuery` can be registered in
both the Neo4j and Memgraph internal catalogues — avoiding duplication at the typed-class
level.

---

### 5. New query — `source_labels` / `target_labels` (E18.1 reassignment)

This query is new — it does not exist in any current `QueryStrategy` or `MemgraphQueries`. It
is required to populate `RelationshipTypeProfile.source_labels` / `.target_labels` and make
`INVALID_ENDPOINT` fire on live Cypher databases.

#### 5a. Neo4j + Memgraph — endpoint labels for a relationship type

**Cypher (same query works on both Neo4j and Memgraph):**
```cypher
MATCH (src)-[r:`<<rel_type>>`]->(tgt)
RETURN DISTINCT labels(src) AS source_labels, labels(tgt) AS target_labels
```

> `MATCH` with a backtick-quoted rel-type pattern and `DISTINCT` to avoid returning one row
> per relationship. The `labels()` function returns a list of all labels on the node; for
> typical single-label nodes this is a list of one string.

**Interpolated identifiers:** `rel_type` (kind `"relationship type"`), backtick-quoted.

**Result-row shape:**
```python
{
    "source_labels": list[str],
    "target_labels": list[str],
}
```

**Target `Params` model:** `Params = NoParams`.

**Target `Identifiers` model:** `RelTypeIdentifiers` (reuse from 2d — the same
`class RelTypeIdentifiers(BaseModel): rel_type: str`).

**Target `Output` model:** new projection:
```python
class EndpointLabelsRow(BaseModel):
    source_labels: list[str]
    target_labels: list[str]
```
`materialize()` returns `EndpointLabelsRow`. The inspector's `_build_rel_profile()` collects
all rows, unions the source/target label sets, and sets
`RelationshipTypeProfile.source_labels` / `.target_labels`.

**Notes:** Shared between Neo4j and Memgraph — register in both internal catalogues.

---

### 6. Parity gaps — what Memgraph cannot provide natively

| Gap | Current state | Decision |
|-----|--------------|----------|
| `NodeTypeProfile.count` | Always 0 in Memgraph inspector | **Document explicitly** in `memgraph/inspector.py` as `# Memgraph schema.node_type_properties() yields no observation counts`. The `count=0` placeholder remains; no silent skip. |
| `RelationshipTypeProfile.count` | Always 0 in Memgraph inspector | Same — document explicitly. |
| `PropertyProfile.present_count` / `.total_count` | Set to `1`/`1` (mandatory heuristic) in Memgraph | **Document explicitly** — Memgraph `schema.rel_type_properties` yields `mandatory` bool, not observation counts. The heuristic `present_count=int(mandatory), total_count=1` is the best available approximation; note it in the model docstring in the inspector file. |

`cardinality_stats` and `source_labels`/`target_labels` **are** achievable via queries 4d and
5a above — those gaps close in T8.

---

### 7. Implementation option decision — A vs B

**Option A — Direct typed subclasses; retire `QueryStrategy`:**
Each strategy method becomes a `CypherReadQuery` subclass. `QueryStrategy` Protocol and both
strategy classes (`ApocQueryStrategy`, `CypherQueryStrategy`, `MemgraphQueries`) are deleted.
The APOC / pure-Cypher split becomes two named subclass sets registered in a catalogue keyed by
strategy selection at inspector construction time (or two internal catalogues swapped in).

**Option B — Typed wrappers over the existing strategy:**
The strategy stays for raw string logic; thin `CypherReadQuery` subclasses delegate `build()`
to the strategy and add `Params`/`Output`/`materialize()`.

**Decision: Option A.**

Rationale: the `QueryStrategy` Protocol is a duplicate swappability mechanism — it solves the
same backend-swap problem that `CypherReadQuery` + internal catalogue solves, using a
completely different shape (method-dispatch on a mutable object vs. registered typed query
objects). Keeping both mechanisms in parallel does not reduce complexity; it adds an invisible
maintenance surface. Option A removes the entire `QueryStrategy`/`MemgraphQueries` layer (112 +
30 lines) and replaces it with typed subclasses that carry Params, Output, identifier safety,
and catalogue registration as first-class properties. The query text (Cypher) already exists —
the migration is lifting it from a method return value into a `cypher_template` ClassVar, which
is a trivial mechanical change. The only material work is the new projection models and
`materialize()` implementations.

The ADR's own language confirms this: "APOC vs pure-Cypher becomes two `CypherReadQuery`
subclass sets selected at construction" (ADR-009, Decision 2). Option B would keep the
`QueryStrategy` as an implementation detail inside `build()`, which contradicts the ADR's
"retire" language.

**Option B is rejected** — it removes no duplication (both mechanism layers remain), gains
nothing over Option A, and adds wrapper boilerplate on top of the already-deletable strategy
code.

---

### 8. `QueryStrategy` disposition

`QueryStrategy` (Protocol), `ApocQueryStrategy`, `CypherQueryStrategy` in
`neo4j/queries.py` and `MemgraphQueries` in `memgraph/queries.py` are **retired** — the entire
files are replaced by typed `CypherReadQuery` subclasses in T8.

Concrete retirement plan:
1. The module `neo4j/queries.py` is rewritten as the home of the typed query subclasses for
   the Neo4j inspector (APOC set + pure-Cypher set). The Protocol and both strategy classes are
   deleted.
2. The module `memgraph/queries.py` is rewritten as the home of the Memgraph typed query
   subclasses. `MemgraphQueries` is deleted.
3. `Neo4jInspector.__init__` loses the `strategy: QueryStrategy | None` parameter (removed) and
   gains a `use_apoc: bool = True` (or `strategy: Literal["apoc", "cypher"] = "auto"`) parameter
   that selects which internal catalogue to load. This is a breaking API change on the inspector
   constructor — the `strategy` parameter is currently public. Document as a breaking change in
   T8's changelog.
4. `Neo4jInspector._detect_strategy()` retains its APOC-detection logic but instead of
   returning a `QueryStrategy` object, it sets `self._catalogue` to the APOC or pure-Cypher
   catalogue.

---

### 9. Identifier-safety approach (T2.5 `<<placeholder>>` / `validate_identifier`)

**All queries with dynamic identifiers use the `Identifiers`/`<<placeholder>>` declarative
mechanism from ADR-010/T2.5.** The `validate_identifier` call is wired into the Cypher base
`build()` via `render_with_identifiers` — query authors do not call it manually.

For the APOC variant of `node_properties`/`rel_properties`, the identifier appears **inside a
Cypher string literal** (`WHERE '<<label>>' IN nodeLabels`) rather than as a bare Cypher
identifier pattern. The `<<label>>` placeholder still gets validated by `validate_identifier`
before substitution — the safe-identifier grammar (letters, digits, underscore; no starting
digit) is a sufficient containment guarantee: a safe identifier cannot contain characters that
would break out of the surrounding single-quote string literal. The APOC query therefore uses
the same declarative mechanism as the pure-Cypher queries; no special escaping is needed.

For the MATCH-pattern queries (pure-Cypher `node_properties`, `rel_properties`, `cardinality`,
Memgraph `cardinality`, new endpoint query), the identifier appears directly in the Cypher
pattern as a backtick-quoted label (`` MATCH (n:`<<label>>`) ``). The backtick wrapper is
written as a literal in `cypher_template`; `validate_identifier` confirms the value is safe
before it is spliced in.

**The `escape_identifier` fallback is NOT wired in.** All dynamic identifiers must satisfy the
safe-identifier grammar — sources are `db.labels()` / `db.relationshipTypes()` results, which
in practice are always valid identifiers for any well-formed database. If a database is
pathologically named (a label with spaces, etc.) `validate_identifier` raises
`CypherIdentifierError` before any Cypher is produced, which is the correct fail-loud
behaviour.

---

### 10. Projection models required (new, not in `models.py`)

The existing profile models (`NodeTypeProfile`, `PropertyProfile`, `CardinalityStats`,
`ConstraintInfo`, `RelationshipTypeProfile`, `GraphProfile`) remain unchanged and continue to
be the cross-backend currency produced by `inspect()`. The new models below are intermediate
**projection models** — the typed `Output` of each query's `materialize()` step — and live in
the query modules (not in `models.py`).

| New model | Location | Fields | Maps to |
|-----------|----------|--------|---------|
| `NodeLabelRow` | `neo4j/queries.py` | `label: str` | `str` (label string) |
| `RelTypeLabelRow` | `neo4j/queries.py` | `relationship_type: str` (alias `"relationshipType"`) | `str` (rel-type string) |
| `NodePropertyRow` | `neo4j/queries.py` | `property_name`, `property_types`, `mandatory`, `property_observations`, `total_observations` | `PropertyProfile` |
| `MemgraphNodePropertyRow` | `memgraph/queries.py` | `node_type`, `node_labels`, `mandatory`, `property_name`, `property_types` | `PropertyProfile` (via inspector aggregation) |
| `MemgraphRelPropertyRow` | `memgraph/queries.py` | `rel_type`, `mandatory`, `property_name`, `property_types` | `PropertyProfile` (via inspector aggregation) |
| `MemgraphConstraintRow` | `memgraph/queries.py` | `constraint_type`, `entity_type`, `label`, `properties` | `ConstraintInfo` |
| `EndpointLabelsRow` | shared (e.g. `extensions/models.py` or each query module) | `source_labels: list[str]`, `target_labels: list[str]` | `RelationshipTypeProfile.source_labels/.target_labels` |

`CardinalityStats` is used directly as `Output` for the cardinality query — no new model
needed (fields match 1:1 with driver column names).
`ConstraintInfo` is used directly as `Output` for the Neo4j constraints query — `materialize()`
does field aliasing inline.

---

### 11. Summary table — all queries

| # | Query | Strategy class | Shared? | Identifiers model | Params model | Output model (per `materialize()`) |
|---|-------|---------------|---------|-------------------|--------------|-------------------------------------|
| N1 | `node_labels` | Neo4j (both) | ✓ shared | `NoIdentifiers` | `NoParams` | `NodeLabelRow` |
| N2 | `rel_types` | Neo4j (both) | ✓ shared | `NoIdentifiers` | `NoParams` | `RelTypeLabelRow` |
| N3a | `node_properties` (APOC) | Neo4j APOC only | — | `NodeLabelIdentifiers` | `NoParams` | `NodePropertyRow` |
| N3b | `node_properties` (pure) | Neo4j Cypher only | — | `NodeLabelIdentifiers` | `NoParams` | `NodePropertyRow` |
| N4a | `rel_properties` (APOC) | Neo4j APOC only | — | `RelTypeIdentifiers` | `NoParams` | `NodePropertyRow` |
| N4b | `rel_properties` (pure) | Neo4j Cypher only | — | `RelTypeIdentifiers` | `NoParams` | `NodePropertyRow` |
| N5 | `cardinality` | Neo4j (both) + Memgraph | ✓ shared | `CardinalityIdentifiers` | `NoParams` | `CardinalityStats` |
| N6 | `constraints` (Neo4j) | Neo4j (both) | ✓ shared | `NoIdentifiers` | `NoParams` | `ConstraintInfo` |
| M1 | `node_properties` (bulk) | Memgraph only | — | `NoIdentifiers` | `NoParams` | `MemgraphNodePropertyRow` |
| M2 | `rel_properties` (bulk) | Memgraph only | — | `NoIdentifiers` | `NoParams` | `MemgraphRelPropertyRow` |
| M3 | `constraints` (Memgraph) | Memgraph only | — | `NoIdentifiers` | `NoParams` | `MemgraphConstraintRow` |
| X1 | `endpoint_labels` (new) | Neo4j + Memgraph | ✓ shared | `RelTypeIdentifiers` | `NoParams` | `EndpointLabelsRow` |

**Total typed subclasses to write:** 9 distinct `CypherReadQuery` subclasses (N1, N2, N3a,
N3b, N4a, N4b, N5/N6 shared, M1, M2, M3, X1 = 11 — minus 2 shared already counted = **9**
unique classes). Identifier models to write: `NodeLabelIdentifiers`, `RelTypeIdentifiers`,
`CardinalityIdentifiers` (3 new). Projection models to write: 7 new (see Section 10).

---

### 12. Pre-implementation checklist for T8

- [ ] T2.5 / ADR-010 mechanism confirmed implemented: `CypherReadQuery.Identifiers`,
  `NoIdentifiers`, `<<placeholder>>` substitution via `render_with_identifiers`.
- [ ] `validate_identifier` / `CypherIdentifierError` available from
  `orthograph.extensions.cypher.identifiers`.
- [ ] `NoParams` exported from `orthograph.extensions.cypher` (already done per T2.5).
- [ ] Internal `QueryCatalogue` instantiation pattern confirmed (construct inside inspector
  `__init__` or at module level as a module-scope constant — prefer module-scope for the
  shared subclasses, per-instance for strategy selection).
- [ ] `Neo4jInspector` constructor `strategy` parameter replacement plan confirmed (breaking
  change; needs release note).
