# ADR-013: Ubiquitous-Language Naming Pass

**Date:** 2026-06-11
**Status:** Accepted
**Category:** naming / readability

> **Forward note (ADR-017, 2026-06-12).** This ADR's *naming* decisions stand.
> ADR-017 extends them to **package boundaries**: the `core/validation.py` and
> `profile/validation.py` modules cited here move to
> `graph_definition/validation.py` and `comparison/engine.py` (the latter with
> `validate_profile` → `compare`). The activity-module convention this ADR
> established is preserved in the new packages. See ADR-017's path-translation
> table.

---

## Context

Prior to this pass the codebase had accumulated several naming tensions:

1. **`model` overloaded across four distinct senses** — the `GraphDataModel`
   container (the declared truth), Pydantic framework mechanics
   (`model_validate`, `model_dump`), generic Pydantic record types
   (`Output`, `Params`), and loose prose.  A bare `model` parameter gave no
   indication of which sense was intended.

2. **Two words for one concept** — the named-typed-query registry was called
   `catalogue` in variables, `QueryCatalogue` in the class, and `queries` /
   `query_set` in PRD prose.  Three terms for the same thing.

3. **`validate_catalogue` vs `validate_query_catalogue` vs
   `validate_queries_against_profile`** — the API and implementation layers
   used different verb forms for the same operation.

4. **`interpret_result` vs `materialize`** — `ReadQuery` mapped raw records
   via `materialize()`; `WriteQuery` mapped them via `interpret_result()`.
   Same concept, two names, no visible relationship.

5. **Module names described their contents as agents** (`validator.py`,
   `inspector.py`, `query_executor.py`) rather than naming the **activity**
   they implement, inconsistent with `profile/validation.py` which already
   used the activity pattern.

6. **Module–function name collision** — `cypher/validate_catalogue.py`
   exported a function also called `validate_catalogue`, forcing an alias
   (`_validate_query_catalogue`) at every import site.

---

## Decision

### Guiding principle

> **Explicit, self-describing names.  One word per concept.  Classes keep
> their accurate Pydantic-model names; variables spell out what they hold.**

The goal is that a consumer reading any identifier — parameter, variable,
function, or module — understands its domain role without consulting docs.

---

### Variable and parameter names

| Old name | New name | Rule |
|---|---|---|
| `model: GraphDataModel` (any scope) | `graph_data_model: GraphDataModel` | Explicit; prevents overload with Pydantic `model_*` |
| `result_model: GraphDataModel` | `result_graph_data_model: GraphDataModel` | Consistent with above; distinguishes from `graph_data_model` in same function |
| `effective_model` (local) | `effective_graph_data_model` | Same |
| `catalogue` / `cat` (QueryCatalogue variable) | `query_catalogue` | Matches the class name; one term top-to-bottom |
| `q: ReadQuery` / `q: WriteQuery` | `read_query` / `write_query` | Self-describing; `q` carries no meaning |

**Class names are unchanged.**  `GraphDataModel`, `NodeModel`,
`RelationshipModel`, and `QueryCatalogue` are accurate Pydantic model
class names and require no rename.  The `GqlAlchemyClient.model` public
property and the `model=` constructor kwargs on `GqlAlchemyClient` and
`ValidatedQueryBuilder` were renamed to `graph_data_model` because no
consumers exist yet (pre-v0.1.0) and the opportunity was available.

---

### Function and method names

| Old name | New name | Rationale |
|---|---|---|
| `WriteQuery.interpret_result(raw)` | `WriteQuery.materialize(raw)` | Unified with `ReadQuery.materialize(raw)` — same concept (raw driver record → typed result) on both sides of the read/write split |
| `validate_catalogue(catalogue, model)` | `validate_query_catalogue(query_catalogue, graph_data_model)` | Matches the `QueryCatalogue` class name; unambiguous in isolation |
| `validate_catalogue_against_profile(...)` | `validate_query_catalogue_against_profile(...)` | Same root; parallel form |
| `validate_queries_against_profile(...)` (api) | `validate_query_catalogue_against_profile(...)` | Aligned api and impl — one name everywhere |

---

### Module renames

All four follow the same pattern: **noun describing the activity**, not the
agent performing it.  This is consistent with `profile/validation.py`
(already correct before this pass) and makes the module's purpose
self-evident from the file name.

| Old module | New module | Pattern |
|---|---|---|
| `core/validator.py` | `core/validation.py` | activity |
| `cypher/validate_catalogue.py` | `cypher/validation.py` | activity |
| `cypher/query_executor.py` | `cypher/query_execution.py` | activity |
| `profile/inspector.py` | `profile/inspection.py` | activity |

The module–function collision in `cypher/validate_catalogue.py` (where the
module and its primary export shared a name, forcing an import alias) is
resolved by the rename to `cypher/validation.py`: the module is named after
the activity, the functions are named after the specific operations they
perform.

---

### What was intentionally left unchanged

- `core/` package name — the `model` overload in package names requires a
  broader holistic decision (see open work below) and is deferred.
- `model_to_text`, `model_to_mermaid`, `render_model` — these are renderer
  helper function names, not variables holding a `GraphDataModel`.  They
  communicate "convert a GraphDataModel to X" and read naturally.
- `Output` vs `materialize` root mismatch — the vivid verb `materialize` was
  preferred over a noun-paired alternative (`to_output`).  Accepted.
- `backends/<vendor>/inspector.py` files — these are *files inside a vendor
  backend*, not the shared ABC module.  Renaming them is a separate concern.
- `ReadPort`, `WritePort` asymmetry — noted but out of scope for this pass.

---

## Consequences

### Positive

- A consumer reading any public API signature understands the domain role of
  each argument without consulting docs.
- `model` is now unambiguously reserved for Pydantic record types
  (`BaseModel` subclasses in the Pydantic sense).  `graph_data_model` is
  unambiguously the declared graph schema container.
- `query_catalogue` is the single term for the named-query registry
  everywhere: class, variable, parameter, and API verb.
- `materialize` names the raw→typed mapping contract uniformly across both
  read and write queries.
- Module names (`validation.py`, `inspection.py`, `query_execution.py`)
  describe activities, matching the existing `profile/validation.py` pattern.
- The import-alias hack (`_validate_query_catalogue`) in `api/model.py` is
  gone; `api/model.py` imports the implementation module under a short
  private alias (`_cypher_validation`) and calls through it, which is the
  idiomatic Python resolution when a module and a local definition would
  shadow each other.

### Negative / risks

- **Blast radius** — ~430 identifier occurrences, 75 files.  Risk is
  mitigated by the full test suite (691 tests) passing after each
  target, mypy clean (55 source files), ruff clean, and architecture
  isolation tests passing.
- **Verbosity** — `graph_data_model` is longer than `model`.  The tradeoff
  (clarity over brevity) is intentional and aligned with the guiding
  principle.

---

## Open work

- **`core/` package rename** — the most natural name (`schema/`) would
  reclaim "schema" from the PRD's physical-DB-layer meaning.  Deferred until
  the three-layer terminology is updated consistently across docs and code.
- **Notebooks** — updated in this pass but maintained manually; consider
  integrating into CI (`pytest notebooks/ --nbval-lax`) to catch future
  drift.
