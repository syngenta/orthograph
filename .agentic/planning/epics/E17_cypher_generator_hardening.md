# Epic E17: CypherGenerator — Injection Hardening and Typed-Query Realignment

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Blocked by:** E16 (provides the typed `CypherReadQuery`/`CypherWriteQuery` contract this epic
> aligns the generator to). E17 can begin once E16 STEP 2 (Cypher backend bases) is merged.
> **Unblocks:** E11 (Auto-Generated CRUD) — CRUD codegen will emit generator-produced queries, so
> the generator must be safe and typed first.
> **Relates to:** ADR-001 (architecture), ADR-005 (cardinality semantics), PRD Constraint 2 (models
> are the single source of truth), PRD Constraint 5 (not a query optimizer), PRD User Story 9
> (auto-generated CRUD), User Story 10 (static Cypher validation).
>
> **SCOPE NOTE:** This epic reviews and hardens the EXISTING `CypherGenerator`
> (`src/orthograph/extensions/cypher/generator.py`). It does NOT add new query kinds beyond what the
> PRD's "Auto-Generated Operations" list already names (get-by-uid, merge, create, delete,
> match-by-label, constraint DDL). The two goals are: **(1) close the identifier-injection risk**,
> and **(2) realign the generator's output with the typed query contract from E16** so that
> generated queries flow into the catalogue instead of being loose `(str, dict)` tuples.

---

## Why This Epic Is Needed

### The security finding (primary driver)

The generator builds Cypher by **interpolating identifiers** — node labels, relationship types, and
property keys — directly into the query string via f-strings:

```python
# generator.py:32  — label and uid_field interpolated as identifiers
query = f"MERGE (n:{label} {{{uid_field}: ${uid_field}}})"
# generator.py:36  — property keys interpolated as identifiers
set_clauses = ", ".join(f"n.{k} = ${k}" for k in set_props)
# generator.py:48-49 — property keys interpolated
prop_str = ", ".join(f"{k}: ${k}" for k in props)
```

Cypher parameters (`$value`) **cannot** parameterise identifiers (labels, relationship types,
property keys) — only values. This is a language limitation, so identifier interpolation is
unavoidable in a generator. The risk is therefore **conditional**: it is safe only while every
identifier originates from a trusted, model-bound source. Today the generator reads
`data["__label__"]` and property keys straight from a caller-supplied `dict[str, Any]`. If any of
those keys ever derive from untrusted input, the result is **Cypher injection via identifiers**
(e.g. a property key of `` x} ) DETACH DELETE n //`` ).

The values are correctly parameterised (`$uid_field`, `$k`) and the label is validated against the
model (`get_node_type(label)` raises for unknowns) — but **property keys are not validated at all**,
and the validation that does exist runs *after* the key has already been embedded in the string in
some paths. This epic makes identifier safety **structural and total**, not incidental.

### The architectural drift (secondary driver)

E16 established a typed query contract: queries are `CypherReadQuery`/`CypherWriteQuery` subclasses
whose `build()` returns `(cypher, params)` and which validate `$param` ↔ `Params` field alignment at
class-definition time. The generator predates this and returns bare `tuple[str, dict]` /
`list[str]`. As a result:

- Generated queries **cannot be registered** in the `TypedQueryCatalogue` or introspected via
  `describe()`.
- Generated queries get **none of E16's definition-time guarantees** (param alignment, dialect
  parse).
- E11 (CRUD auto-generation) is specified to "emit typed `CypherReadQuery`/`WriteQuery` instances"
  — but the only generator available emits loose strings. E11 is blocked on this realignment.

---

## Implementation Order (build in this sequence)

```
STEP 1 — Identifier safety core         (T1, T2)   pure, no behaviour change to valid queries
STEP 2 — Model-bound generation         (T3)       every identifier resolved through the model
STEP 3 — Typed-query emission           (T4, T5)   generator emits E16 query objects
STEP 4 — Audit, docs, decision record   (T6)       prove the risk is closed; record the decision
─────────────────────────────────────────────────────────────────────────────────────────────
```

Files touched:
```
src/orthograph/extensions/cypher/generator.py     hardened + typed emission (T1–T5)
src/orthograph/extensions/cypher/identifiers.py    NEW — identifier validation/escaping (T1)
src/orthograph/core/errors.py                      reuse ValidationIssue codes (T3)
tests/extensions/cypher/test_generator.py          extended (every step)
tests/extensions/cypher/test_identifiers.py        NEW (T1)
.agentic/decisions/008-cypher-identifier-safety.md NEW (T6)
```

---

## STEP 1 — Identifier safety core

### T1: `identifiers.py` — validate and escape Cypher identifiers

**What:** A small, pure module that is the single authority on whether a string is a safe Cypher
identifier, and on how to render one. No generator logic, no model — just string rules. This is the
seam every interpolation must pass through.

**Actions:**
1. Create `src/orthograph/extensions/cypher/identifiers.py`.
2. Define the safe-identifier rule (Cypher unescaped identifier grammar):
   ```python
   # Letters, digits, underscore; must not start with a digit.
   _SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
   ```
3. Define `is_safe_identifier(name: str) -> bool`.
4. Define `validate_identifier(name: str, *, kind: str) -> str`:
   - Returns `name` unchanged if it matches `_SAFE_IDENTIFIER`.
   - Otherwise raises `ValueError(f"Unsafe Cypher {kind}: {name!r}")`. `kind` is one of
     `"label"`, `"relationship type"`, `"property key"`.
   - This is the function f-string interpolation sites MUST call before embedding any identifier.
5. (Defensive, documented as a fallback — not the primary defence) Define
   `escape_identifier(name: str) -> str` that backtick-quotes and doubles internal backticks
   (`` `Foo `` → `` `Foo` ``, `` Fo`o `` → `` `Fo``o` ``). The generator's policy is
   **validate-and-reject by default**; escaping exists only for a future explicit opt-in and is not
   wired into generation in this epic.

**Tests (`tests/extensions/cypher/test_identifiers.py`):**
- `is_safe_identifier("Person")` is True; `is_safe_identifier("Per son")`,
  `is_safe_identifier("1Movie")`, `is_safe_identifier("x} ) DETACH DELETE n //")` are False.
- `validate_identifier("Person", kind="label")` returns `"Person"`.
- `validate_identifier("x`y", kind="property key")` raises `ValueError` mentioning `property key`.
- `escape_identifier("Fo`o")` returns `` `Fo``o` `` (doubled backtick).

**Verification:** `from orthograph.extensions.cypher.identifiers import validate_identifier` works.
`mypy src/` passes. Module imports nothing from `generator.py` or `core` (pure string utility).

---

### T2: Route every generator interpolation through `validate_identifier`

**What:** Make identifier safety total in the generator without changing the output for any
currently-valid query. Every f-string that embeds a label, relationship type, or property key must
first call `validate_identifier`.

**Actions:**
1. In `generator.py`, import `validate_identifier`.
2. In `merge_node`, `create_node`, `_rel_query`, `match_node`, `match_relationship`,
   `generate_constraints`: wrap each interpolated identifier:
   - labels → `validate_identifier(label, kind="label")`
   - relationship type/label → `validate_identifier(label, kind="relationship type")`
   - property keys (the `k` in `f"n.{k} = ${k}"`, `f"{k}: ${k}"`) →
     `validate_identifier(k, kind="property key")`
   - uid field names → `validate_identifier(uid_field, kind="property key")`
3. Do NOT change the produced Cypher for valid identifiers — only add the guard. (Parameter
   placeholders `$k` already protect values; this protects the key names.)

**Tests (extend `test_generator.py`):**
- Existing tests still pass unchanged (no behaviour change for valid input).
- `merge_node({"__label__": "Person", "name": "Alice", "x} ) DETACH DELETE n //": 1})` raises
  `ValueError` mentioning `property key`.
- A relationship payload with an injected key raises before any string is returned.
- A node payload whose `__label__` is `"Person) DETACH DELETE (n"` raises (note: this label also
  fails the model lookup, but the identifier guard must reject it independently — prove with a
  generator built on a permissive/no-model path if needed).

**Verification:** Full `tests/extensions/cypher/` green. No valid-query output changed (diff the
generated strings in existing assertions).

---

## STEP 2 — Model-bound generation

### T3: Property keys resolved against the model, not the input dict

**What:** Today property keys come from arbitrary `dict` keys. Per PRD Constraint 2 (models are the
single source of truth), the set of writable properties must be derived from the model, and unknown
keys must be a structured error — not silently embedded.

**Actions:**
1. In `merge_node`/`create_node`/`_rel_query`, after resolving the node/relationship type from the
   model, intersect the incoming property keys with the type's declared property names
   (`get_all_property_names()` — already used by the parser's `_check_properties`).
2. For any incoming key not in the model:
   - Raise a `ValueError` (or collect into a `ValidationResult`/`GraphValidationError` for
     consistency with the parser — pick one and document it in T6) naming the offending key and the
     type.
3. Keep the `validate_identifier` guard from T2 as defence-in-depth (a key could be model-declared
   yet still need the grammar check if models ever allow exotic names; today they won't, but the
   guard stays cheap and total).

**Tests (extend `test_generator.py`):**
- `merge_node` with a property not declared on the model raises, naming the property and label.
- `merge_node` with only declared properties produces the same output as today.
- A relationship payload with an undeclared property raises.

**Verification:** Generated queries can only ever contain model-declared identifiers + parameterised
values. `tests/extensions/cypher/` green.

---

## STEP 3 — Typed-query emission

### T4: `generate_match_by_uid` / `generate_merge` / `generate_create` / `generate_delete` return typed query objects

**What:** Add generator methods that return E16 `CypherReadQuery`/`CypherWriteQuery` **instances**
(or instantiable classes) instead of bare strings, so generated queries register in the
`TypedQueryCatalogue`, gain definition-time `$param`↔`Params` checks, and carry an `Output` model.
The existing string-returning methods remain (used internally and by callers that want raw Cypher)
but are now hardened by T1–T3.

**Actions:**
1. For a given `NodeModel` subclass, synthesise:
   - a `Params` model (Pydantic) carrying the UID field (e.g. `{uid_field: <type>}`),
   - an `Output` model = the `NodeModel` itself (it is already a Pydantic BaseModel),
   - a concrete `CypherReadQuery`/`CypherWriteQuery` subclass whose `cypher_template` ClassVar is the
     generated, identifier-validated string, and whose `materialize()` maps the record dict to the
     `Output`.
2. Because E16 validates `$param`↔`Params` at class-definition time, generated `$param` names MUST
   equal the `Params` field names (use the UID/property field names directly as placeholders, e.g.
   `MATCH (n:Person {name: $name})` with `Params.name`).
3. Methods to add (mirroring PRD's auto-generated operations list):
   - `match_by_uid_query(node_type) -> CypherReadQuery`
   - `merge_query(node_type) -> CypherWriteQuery`
   - `create_query(node_type) -> CypherWriteQuery`
   - `delete_by_uid_query(node_type) -> CypherWriteQuery`
4. Keep these PURE (R1) — they build classes/instances, touch no session.

**Tests (extend `test_generator.py`):**
- `match_by_uid_query(Person)` returns a `CypherReadQuery`; its `backend is Backend.CYPHER`; its
  `Output` is `Person`; `build(Params(name="Alice"))` returns `(cypher, {"name": "Alice"})`.
- The generated query's `cypher` references only model identifiers (assert `:Person`, `$name`).
- A generated query passes E16's definition-time validation (it constructs without raising — proving
  `$param`↔`Params` alignment holds).
- `delete_by_uid_query(Person).build(...)` produces a `DETACH DELETE`-style statement with a
  parameterised UID.

**Verification:** `from orthograph.extensions.cypher import CypherGenerator` and the new methods
return E16 query objects. `tests/extensions/cypher/` + `tests/catalogue/` green.

---

### T5: Register generated queries in a `TypedQueryCatalogue`

**What:** Prove the realignment end-to-end: generated typed queries register and introspect like
hand-written ones.

**Actions:**
1. In a test (no new src needed beyond T4), build a `GraphDataModel`, generate the four CRUD typed
   queries for `Person`, register them in a `TypedQueryCatalogue`, and call `describe()`.
2. Assert each `QueryDescription` carries the correct `kind` (read for match-by-uid; write for
   merge/create/delete), `backend = CYPHER`, and a non-None `output_schema` for the read.

**Tests (extend `test_generator.py` or add `tests/catalogue/test_generated_query_registration.py`):**
- Four generated queries register without name collision.
- `describe()` returns four entries with correct kinds and backends.
- The read's `output_schema == Person.model_json_schema()`.

**Verification:** Generated queries are first-class catalogue citizens. Suite green.

---

## STEP 4 — Audit, docs, decision record

### T6: Injection audit, generator docstrings, and ADR-008

**What:** Make the security posture explicit and durable.

**Actions:**
1. Add a focused **injection audit test** (`test_generator.py`) that asserts: for every
   string-returning and typed-query-returning generator method, an injection attempt in a label,
   relationship type, or property key raises before any Cypher is produced. This is the regression
   guard that keeps the risk closed.
2. Update `generator.py` module + method docstrings to state the safety policy plainly:
   *"Values are always parameterised. Identifiers (labels, relationship types, property keys) are
   validated against the model and the Cypher identifier grammar; unsafe identifiers are rejected,
   never escaped-and-embedded by default."*
3. Write `.agentic/decisions/008-cypher-identifier-safety.md` (ADR format consistent with
   `001`–`007`) recording:
   - the conditional risk (Cypher cannot parameterise identifiers),
   - the chosen policy (**validate-and-reject**, model-bound keys, optional escaping not wired),
   - the alternative considered (backtick-escaping by default) and why it was rejected for the
     pilot (silently accepting attacker-named identifiers is worse than failing loudly).
4. Cross-link the ADR from this epic and from the PRD's "Query Governance — Cypher" capability bullet
   (one-line reference, no content duplication).

**Tests:** the audit test above (it IS the verification).

**Verification:** Running the audit test demonstrates every interpolation site rejects injection.
ADR-008 exists and is linked. `mypy src/` and full `pytest` green.

---

## Success Criteria (epic-level)

- [ ] No generator code path embeds an unvalidated identifier into a Cypher string (T1, T2, audit in T6).
- [ ] Property keys are model-bound; unknown keys raise a structured error (T3).
- [ ] Generator can emit E16 `CypherReadQuery`/`CypherWriteQuery` objects that register in
      `TypedQueryCatalogue` and pass definition-time `$param`↔`Params` validation (T4, T5).
- [ ] Every currently-valid generated query is byte-for-byte unchanged (no regression for good input).
- [ ] ADR-008 records the identifier-safety decision; PRD links it (T6).
- [ ] `mypy src/` clean; `ruff check` clean; full `pytest` green (PRD Constraint 12 — tests are the
      specification).

---

## Out of Scope (this epic)

- New query *kinds* beyond the PRD's auto-generated operations list (no aggregations, no path
  queries, no projections).
- YAML emission of generated queries (tracked under the E16 OPEN DECISION: YAML).
- Query optimisation or execution planning (PRD Constraint 5 — not a query optimizer).
- Changing the `validate_cypher` parser (separate concern; the generator now produces strings the
  parser already accepts).
