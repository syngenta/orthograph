# Reject `row_mapper`; `materialize` stays an explicit required method on `CypherReadQuery`

**Status:** Partially reverted — 2026-06-16
**Supersedes:** E33 Q1 (the `row_mapper: ClassVar[Callable]` proposal)
**Produced by:** E34 T3

> **What stands:** `row_mapper` is **rejected** (see "Why `row_mapper` is rejected").
>
> **What was withdrawn:** the *adoption of a default `materialize`* (the E34 T4
> implementation) is **reverted**. The auto-classifying default — `_MaterializeKind`,
> `_classify_materialize`, `_cypher_materialize_default`, and the `__init_subclass__`
> injection in `cypher/base_models.py` — coupled runtime DTO shaping to the static
> RETURN-clause classifier across three modules (`parser.py` ↔ `validation.py` ↔
> `base_models.py`). It also shipped in a broken, interrupted state (an undefined
> `abstract_methods` reference that raised `NameError` at every `CypherReadQuery`
> subclass definition).
>
> **Current contract:** `materialize` is an **explicit, required one-line method**
> on every read query (`return Output.model_validate(dict(raw["m"]))` for the
> whole-node case). `Output` remains declared and continues to drive
> `QueryCatalogue.describe()`, FastAPI `response_model` wiring, and the **static**
> RETURN→Output alignment check (E34 T1+T2 — `ReturnColumn`/`ReturnKind` in
> `parser.py`, tiered check in `validation.py`). That static validation — the
> project's primary query-governance goal — is **unaffected** and stands. Only the
> attempt to *derive runtime shaping from the same classifier* is withdrawn.

---

## Context

Every `CypherReadQuery` subclass must implement `materialize` as an abstract method.
For the common 1:1 case — whole-node return (`RETURN m`) against a `NodeModel` Output,
or all-scalar aliases matching a flat `BaseModel` — the implementation is always the
same:

```python
def materialize(self, raw: dict) -> Movie:
    return Movie.model_validate(raw)
```

E33 Q1 proposed removing this boilerplate via `row_mapper: ClassVar[Callable[[dict], D]
| None] = None`. The grilling session (E33 T1 / E34 T3) determined that `row_mapper`
is the wrong fix. This ADR records why, and what the correct fix is.

---

## Decision

**`row_mapper` is rejected.** (This part stands.)

**A concrete default `materialize` was originally adopted, then withdrawn.** See the
status banner above. The original proposal (kept here for the record) was:

> A default implementation on `CypherReadQuery` branching on the RETURN-column
> classification produced by the T1 classifier (`ReturnColumn` / `ReturnKind`):
>
> | RETURN shape | Output kind | Default `materialize` behaviour |
> |---|---|---|
> | Single `WHOLE_NODE` column | `NodeModel` | `Output.model_validate(dict(record))` |
> | Single `WHOLE_REL` column | `RelationshipModel` | `Output.model_validate(dict(record))` |
> | All-scalar columns; aliases ⊇ required `Output` fields | flat `BaseModel` | `Output.model_validate(raw)` |
> | Projection Output (fields are themselves Node/Rel models) | any | raises `NotImplementedError` |
> | Imperative query (no `cypher_template`) | any | raises `NotImplementedError` |

**Why it was withdrawn:** the implementation coupled runtime shaping to the static
classifier across three modules, added significant `__init_subclass__` complexity
(MRO walking, abstract-method frozenset patching, classification caching), and was
interrupted mid-implementation in a non-importing state. The simplification decision
(2026-06-16) is: keep `materialize` an explicit required one-liner. The "avoid
boilerplate" goal does not justify the coupling and metaclass machinery it required.
`Output` and the static RETURN→Output alignment check (T1+T2) deliver the
query-governance value without it.

---

## Why `row_mapper` is rejected

### Grilling question 1 (E33): does it actually remove boilerplate?

No — for the 1:1 case it just renames it:

```python
# Before
def materialize(self, raw: dict) -> Movie:
    return Movie.model_validate(raw)

# With row_mapper — same amount of writing, different spelling
row_mapper = Movie.model_validate
```

The author still writes one line per query. The only genuine saving would come from
a *zero-declaration* default, which `row_mapper` does not provide.

### Two sources of truth for the same mapping

Both `materialize` and the T2 validator (`_check_return_output_alignment`) need to
understand the RETURN→Output shape. If `row_mapper` lives outside the T1 classifier,
the two sides are hand-synchronised: a query can pass validation but have a
`row_mapper` that disagrees at runtime. With a classifier-driven default `materialize`,
validation and shaping share one source of truth.

### Ambiguous precedence rule

A query that sets both `row_mapper` and overrides `materialize` requires an explicit
precedence rule and a definition-time error path — complexity that the default-method
approach avoids entirely (override wins; no new rule needed).

### `ClassVar[Callable]` and type-checker behaviour

`row_mapper: ClassVar[Callable[[dict], D] | None]` is poorly typed in practice:
`Movie.model_validate` is typed as `Callable[[Any], Movie]` but the `D` binding
requires the class's generic argument. Type checkers do not infer this correctly;
the ClassVar annotation would effectively be erased to `Any` at the use site, defeating
the typed-contract goal of E16.

---

## Placement decision

The default `materialize` lives on `CypherReadQuery` (not on `ReadQuery`).

Rationale: the classification requires parsing the Cypher RETURN clause, which is
Cypher-specific. The `ReadQuery` abstract layer is backend-agnostic and must not import
from `cypher/`. Placing the default on `CypherReadQuery` keeps the dependency direction
correct (ADR-017).

---

## Precedence rule

1. If the concrete subclass overrides `materialize` → the override is called (existing
   behaviour, unchanged).
2. Otherwise → the cached default branch (computed in `__init_subclass__`) is used.
3. If the default cannot classify the RETURN shape (projection Output, imperative query,
   path return) → the default raises `NotImplementedError` with a message instructing
   the author to implement `materialize`.

There is no `row_mapper` ClassVar. There is no ambiguity.

---

## Runtime contract: `dict(record)` for driver objects

The default `materialize` calls `Output.model_validate(dict(record))`.

For neo4j Python driver `Node` and `Relationship` objects the mapping protocol
(`dict(node)`) produces `{property: value, ...}` — it does **not** include the
internal node id or labels. `model_validate` on a `NodeModel` expects only properties,
so this contract holds. This is verified by the E34 T4 tests against the
`FakeGraphSession` record shape.

---

## Rejected alternative: `row_mapper`

Described in E33 Q1 and above. The core reason for rejection is that it renames
boilerplate instead of eliminating it, splits the RETURN→Output mapping into two
independent mechanisms (validator + mapper), and degrades the typed-contract guarantee.

---

## Cross-references

- E33 Q1 original proposal: `.agentic/planning/active_epics/E33_query_contract_ergonomics_v2.md`
- T1 classifier: `src/orthograph/cypher/parser.py` (`ReturnKind`, `ReturnColumn`,
  `extract_return_columns`)
- T2 tiered validator: `src/orthograph/cypher/validation.py`
  (`_check_return_output_alignment`)
- T4 implementation: `src/orthograph/cypher/base_models.py` (`CypherReadQuery.materialize`)
- ADR-017 (package topology): `.agentic/decisions/017-package-topology-definition-profile-comparison-diagnostics.md`
- ADR-022 (generic-arg auto-population): `.agentic/decisions/022-generic-args-auto-populate-classvar.md`
- Notebook: `notebooks/04.05_cypher_result_shapes.ipynb` (known-gaps table updated in E34 T5)
