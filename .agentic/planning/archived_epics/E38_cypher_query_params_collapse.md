# Epic E38: CypherQuery Signature Collapse — `Params` + `Identifiers` Only

> **Priority:** Medium
> **Origin:** Critical-review session 2026-06-18 on `class CypherQuery`.
> **Goal:** Collapse the three overlapping parameter representations on `CypherQuery`
> (`query_args_required`, `query_args_optional`, `Params`) down to a single typed
> source — a required `Params` model plus an optional `Identifiers` model — making the
> simple path a strict subset of the typed path (`CypherReadQuery` / `CypherWriteQuery`).
> File-authoring is preserved by round-tripping `Params`/`Identifiers` through **JSON
> Schema** instead of plain string lists.
> **Blocked by:** none (E36, E37 done — they introduced `cypher_template` on the typed
> path and the shared `validate_cypher_spec` core this epic depends on).
> **Blocks:** nothing currently; simplifies the public `CypherQuery` surface before v0.1.
> **Departs from spec:** Yes — intentionally drops the Noctis-style `query_args_*`
> name-list authoring style in favour of orthograph's own `Params`-model convention. No
> back-compat shim.

---

## How to use this epic (for the human + delegated agents)

This epic is written to be picked up **stepwise by lower-capability agents with limited
memory**. Each task is self-contained: it names the exact files, the exact edits, and a
verification command. Tasks are tagged with a **recommended model**:

- **`[HAIKU]`** — mechanical, fully-specified edits (renames, find/replace, fixture
  rewrites following a worked example). No design judgement required. Hand to Haiku.
- **`[SONNET]`** — requires reasoning about types, Pydantic internals, edge cases, or
  writing non-trivial new logic. Hand to Sonnet.

**Execution order is strict** unless a task says otherwise. T1 → T2 → T3 → T4 → T5 →
T6 → T7 → T8 → T9. T8 (test migration) sub-tasks can run in parallel once T1–T7 land.

**Definition of done for every task:** `uv run pytest <named tests>` green and
`uv run mypy src` clean for the files touched, unless the task says otherwise.

---

## Background — the problem (read once)

`CypherQuery` (`src/orthograph/cypher/query.py`) currently carries three ways to declare
"what parameters does this query take":

```python
query_args_required: list[str]
query_args_optional: list[str]
Params: type[BaseModel] | None
```

The required/optional split is **exactly** a Pydantic field default (no default =
required; has default = optional). The codebase already proves the equivalence:
`_make_passthrough_params_model` (`cypher/query_execution.py:134`) mechanically converts
the two lists into a `create_model` model with `(Any, ...)` for required fields and
`(Any, None)` for optional ones. `_check_spec_consistency` (`query.py:95`) exists only to
police drift between the lists and a declared `Params`.

The typed path already proves the target shape — `CypherReadQuery` / `CypherWriteQuery`
declare only `Params` + `Identifiers` (`cypher/base_models.py`), required/optional via
field defaults, template string named `cypher_template`.

**The only thing the string lists bought was file-authorability** (a Python class cannot
be written into YAML). We replace "list of names" with "JSON Schema of the model" — the
exact direction the catalogue already uses (`Params.model_json_schema()` at
`query/catalogue.py:144`) — and reconstruct on load via `create_model` (the primitive
already used at `generator.py:405` and `query_execution.py:145`).

---

## Locked decisions (do not re-litigate)

1. **`Params` is a required field**, no default. Zero-arg queries pass `Params = NoParams`
   (the existing sentinel in `cypher/bindings.py:28`, used by every typed zero-arg query).
2. **Wire format = JSON Schema** via `model_json_schema()` ↔ `create_model()`.
   `params_schema` and `identifiers_schema` keys in files.
3. **The JSON-Schema `required` array is kept.** It is the file-native replacement for
   `query_args_optional`: a name in `required` → field with no default; a name absent
   from `required` → optional field with a default. (It plays **no** role in `$param` ↔
   field matching — that is driven by `properties` keys alone.)
4. **Rename `cypher` → `cypher_template`** on `CypherQuery` — both the Python attribute
   **and** the file key. **No** `query` / `cypher` alias is accepted any more.
5. **Round-trip helpers live in a new module** `src/orthograph/cypher/schema_codec.py`.
6. **`Identifiers` also round-trips** as `identifiers_schema`, symmetric with `Params`.
7. **Full migration, no back-compat shim.** `query_args_required` / `query_args_optional`
   are removed entirely.

---

## Target signature (end state)

```python
class CypherQuery(BaseModel):
    name: str = Field(..., alias="query_name")          # alias kept (legacy name only)
    cypher_template: str                                # renamed from `cypher`; NO alias
    description: str | None = None
    Params: type[BaseModel]                             # REQUIRED; NoParams for zero-arg
    Identifiers: type[BaseModel] | None = None
    identifiers: BaseModel | None = None                # bound instance (unchanged role)
```

Removed: `query_args_required`, `query_args_optional`, `_check_spec_consistency`.
`list_arguments()` derives required/optional from `Params.model_fields`.

### Target file format

```yaml
- name: movies_by_year
  cypher_template: "MATCH (m:Movie {released: $released}) RETURN m.title LIMIT $limit"
  description: "Movies released in a given year."
  params_schema:
    title: MovieByYearParams
    type: object
    properties:
      released: {type: integer, title: Released}
      limit:    {type: integer, title: Limit, default: 10}
    required: [released]
  identifiers_schema:        # optional; omit entirely when no <<name>> splicing
    title: NoIdentifiers
    type: object
    properties: {}
```

### Round-trip lifecycle (the whole story)

- **Write (object → file):** `Params` → `Params.model_json_schema()`. Same for
  `Identifiers`. (Custom Pydantic field serializer on `CypherQuery`.)
- **Read (file → object):** `params_schema` dict → `model_from_json_schema()` →
  `create_model(...)` → passed as `Params=`. Same for `identifiers_schema` → `Identifiers=`.
- **Two independent reads of the schema:** `properties` keys → `$param` field-existence
  alignment (`validate_cypher_spec`); `required` array → required/optional at `build()`.

---

## Scope — files touched

| File | Role |
|------|------|
| `src/orthograph/cypher/schema_codec.py` | **NEW** — round-trip helpers |
| `src/orthograph/cypher/query.py` | core refactor |
| `src/orthograph/io/query_catalogue_yaml.py` | loader: read schemas, reconstruct models |
| `src/orthograph/cypher/query_execution.py` | delete passthrough-model fallback |
| `src/orthograph/cypher/validation.py` | drop `query_args_*` branch |
| `src/orthograph/query/catalogue.py` | always emit `params_schema` |
| `src/orthograph/api/model.py` | verify loader path / return type |
| `tests/cypher/test_query.py` (68 refs) | migrate |
| `tests/cypher/test_query_e2e.py` (13) | migrate |
| `tests/cypher/test_query_execution.py` (4) | migrate |
| `tests/cypher/test_validate_query_catalogue.py` (5) | migrate |
| `tests/io/test_query_catalogue_yaml.py` (11) | migrate |

---

## Tasks

### T1 — `[SONNET]` Build the schema codec (foundation; everything depends on it)

**Create** `src/orthograph/cypher/schema_codec.py` with two public functions:

```python
def model_to_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Thin wrapper over model.model_json_schema(). Exists for symmetry + a single
    seam to evolve the wire format later."""

def model_from_json_schema(
    schema: dict[str, Any], *, model_name: str | None = None
) -> type[BaseModel]:
    """Reconstruct a Pydantic model from a JSON-Schema 'object' dict via create_model.

    Field rules:
      * field names      <- schema["properties"].keys()
      * required field   <- name IN schema.get("required", [])   -> (T, ...)
      * optional field   <- name NOT in required                 -> (T | None, default)
                            default = property.get("default", None)
      * model_name       <- argument, else schema.get("title"), else "ReconstructedParams"

    JSON-Schema type -> Python type (SUPPORTED SCALAR TABLE ONLY):
      "integer" -> int, "string" -> str, "number" -> float, "boolean" -> bool

    Raises CypherQueryDefinitionError (loud, never silent Any) when:
      * schema["type"] != "object" or "properties" missing
      * a property uses an unsupported construct: "$ref", "enum", "type": "array"|"object",
        "anyOf"/"allOf"/"oneOf", or a "type" not in the scalar table.
    """
```

**Implementation notes:**
- Use `from pydantic import create_model` and `from orthograph.cypher.exceptions import
  CypherQueryDefinitionError`.
- An empty `properties` (`{}`) is valid and produces an empty model (the `NoParams` /
  `NoIdentifiers` case). `model_from_json_schema(NoParams.model_json_schema())` must
  return a model with zero fields.
- Keep the supported-type table as a module-level dict so it is easy to extend later.
- The error message for unsupported constructs must name the offending field and what
  construct tripped it (e.g. `"field 'tags' uses unsupported construct 'array'"`).

**Tests** — create `tests/cypher/test_schema_codec.py`:
- [ ] round-trip a model with one required `int`, one optional `int` with default 10:
      `model_to_json_schema` → `model_from_json_schema` yields a model whose
      `model_fields` has the same names; the required field has no default, the optional
      one defaults to 10.
- [ ] round-trip `NoParams` → zero-field model.
- [ ] each scalar type (`int`/`str`/`float`/`bool`) survives.
- [ ] `required`/optional split is reconstructed correctly (a model built from a schema
      with `required: [a]` and property `b` makes `b` omittable in `model_validate`).
- [ ] unsupported constructs raise `CypherQueryDefinitionError` with the field name:
      a nested object, an `array`, an `enum`, a `$ref`, an unknown scalar type.

**Verify:** `uv run pytest tests/cypher/test_schema_codec.py -q` green; `uv run mypy
src/orthograph/cypher/schema_codec.py` clean.

---

### T2 — `[SONNET]` Refactor `cypher/query.py` core

Depends on T1. **Edit** `src/orthograph/cypher/query.py`.

1. **Remove fields** `query_args_required`, `query_args_optional`.
2. **Rename field** `cypher` → `cypher_template`. **Remove the `alias="query"`** — the new
   field has no alias. Keep `name`'s `alias="query_name"`.
3. **Make `Params` required:** `Params: type[BaseModel]` (no default, drop `| None`).
4. **Delete** `_check_spec_consistency` entirely.
5. **Field (de)serialization** — add a `@field_serializer("Params")` and
   `@field_serializer("Identifiers")` that emit `model_to_json_schema(value)` (None →
   None for Identifiers), and a `@field_validator("Params", "Identifiers", mode="before")`
   that, **when the incoming value is a `dict`**, reconstructs it via
   `model_from_json_schema`. (A `type[BaseModel]` passed directly in Python is left as-is.)
   Import the codec from `orthograph.cypher.schema_codec`.
6. **`_validate_structure`** (the `model_validator(mode="after")`): drop the
   `_check_spec_consistency` call. Keep the `identifiers` vs `Identifiers` consistency
   checks unchanged.
7. **`build()`**: replace the params construction with
   ```python
   validated = self.Params.model_validate(kwargs)
   params = validated.model_dump(exclude_unset=True)
   ```
   Keep the identifier-render branch (`render_with_identifiers`). **NOTE for reviewer:**
   `exclude_unset` replaces the previous "only keys the caller supplied" logic — verify
   against T8 optional-arg tests; if a default must be injected for an omitted optional,
   reconsider `exclude_unset` vs `exclude_defaults`. This is the one behavioural subtlety
   in the epic — flag it, do not guess silently.
8. **`_validate_call_kwargs`**: derive required/known from `Params.model_fields`:
   ```python
   required = [n for n, f in self.Params.model_fields.items() if f.is_required()]
   known = set(self.Params.model_fields)
   ```
   Keep the same `CypherQueryError` messages (update wording away from
   `query_args_required`).
9. **`validate_query`**: drop the `Params is None` fallback branch — always
   `params_fields = set(self.Params.model_fields)`. Reference `self.cypher_template`.
10. **`list_arguments()`**: derive from `Params.model_fields` (`is_required()` → required,
    else optional).
11. **`__repr__`**: replace `required=/optional=` with `params=<Params.__name__>`.
12. **Docstrings** (module header + class): rewrite to drop the name-list authoring style,
    document `cypher_template`, `Params` (required, `NoParams` for none), and the JSON-
    Schema round-trip. Remove the `query_args_required=[...]` usage examples.

**Verify:** `uv run mypy src/orthograph/cypher/query.py` clean. Tests will be red until
T8 — that is expected; do not migrate tests here.

---

### T3 — `[SONNET]` Rewrite the file loader

Depends on T1, T2. **Edit** `src/orthograph/io/query_catalogue_yaml.py`.

1. In `_build_one` (around line 189): read `name` from `name`/`query_name` (keep legacy
   `query_name`), read **`cypher_template`** (NO `query`/`cypher` alias — error if absent),
   `description`, `params_schema` (dict, required), `identifiers_schema` (dict, optional).
2. Reconstruct: `Params = model_from_json_schema(params_schema, model_name=...)`;
   `Identifiers = model_from_json_schema(identifiers_schema, ...)` if present else `None`.
   When `params_schema` is absent or empty, default to the `NoParams` sentinel
   (`from orthograph.cypher.bindings import NoParams`).
3. Construct `CypherQuery(name=..., cypher_template=..., description=..., Params=...,
   Identifiers=...)`.
4. Remove all `query_args_required` / `query_args_optional` reads.
5. Update the module docstring (the format table at lines 7–51) to the new keys
   (`cypher_template`, `params_schema`, `identifiers_schema`); drop the `query`/`cypher`
   alias rows and the `query_args_*` bullets.
6. Update error messages: the missing-field error must reference `cypher_template`.

**Verify:** `uv run mypy src/orthograph/io/query_catalogue_yaml.py` clean.

---

### T4 — `[HAIKU]` Delete the passthrough-model fallback in the executor

Depends on T2. **Edit** `src/orthograph/cypher/query_execution.py`.

- **Delete** the function `_make_passthrough_params_model` (lines ~134–145).
- In `CypherQueryReadAdapter.__init__` (lines ~164–172) and
  `CypherQueryWriteAdapter.__init__` (lines ~204–211): replace the
  `if query.Params is not None: ... else: _make_passthrough_params_model(...)` blocks with
  a single line: `self.Params = query.Params` (always present now).
- Remove the now-unused `create_model` import **only if** nothing else in the file uses it
  (grep first).
- Leave `build()` / `model_dump(exclude_none=True)` at line ~181 **as-is** for now; the
  reviewer of T2 owns the `exclude_unset` vs `exclude_none` reconciliation.

**Verify:** `uv run mypy src/orthograph/cypher/query_execution.py` clean.

---

### T5 — `[HAIKU]` Drop the `query_args_*` branch in catalogue validation

Depends on T2. **Edit** `src/orthograph/cypher/validation.py`, lines ~344–366.

Replace:
```python
if query.Params is not None:
    params_fields: set[str] = set(query.Params.model_fields)
else:
    params_fields = set(query.query_args_required) | set(query.query_args_optional)
```
with:
```python
params_fields: set[str] = set(query.Params.model_fields)
```
And change `cypher=query.cypher` (line ~358) to `cypher=query.cypher_template`.
Leave the `Identifiers` block and the typed-path branch below untouched.

**Verify:** `uv run mypy src/orthograph/cypher/validation.py` clean.

---

### T6 — `[HAIKU]` Always emit `params_schema` in the catalogue

Depends on T2. **Edit** `src/orthograph/query/catalogue.py`, the `CypherQuery` loop in
`describe` (lines ~163–174).

Replace:
```python
params_schema=q.Params.model_json_schema() if q.Params is not None else {},
```
with:
```python
params_schema=q.Params.model_json_schema(),
```

**Verify:** `uv run mypy src/orthograph/query/catalogue.py` clean.

---

### T7 — `[SONNET]` Verify / fix the public loader path

Depends on T3. **Inspect** `src/orthograph/api/model.py:120`
(`def load_query_catalogue(source) -> list[CypherQuery]`). Confirm it delegates to the
`io/query_catalogue_yaml.py` loaders and that the return type and any re-exported field
names still hold after the rename. Fix any reference to `.cypher` (now `.cypher_template`)
or to `query_args_*`. If `model.py` has its own docstring examples using the old format,
update them.

**Verify:** `uv run mypy src/orthograph/api/model.py` clean; grep the whole `src/` tree
for residual `query_args_required|query_args_optional|\.cypher\b` references on
`CypherQuery` and report any remaining.

---

### T8 — Test & fixture migration (the bulk; split for parallel Haiku work)

Depends on T1–T7 all landed. **Each sub-task is independent** and can be handed to a
separate Haiku agent. Provide each agent the **worked example** below so the mechanical
transform is unambiguous.

**Worked transform example (give this verbatim to each Haiku agent):**

```python
# BEFORE
query = CypherQuery(
    name="movies_by_year",
    cypher="MATCH (m:Movie {released: $released}) RETURN m.title LIMIT $limit",
    query_args_required=["released"],
    query_args_optional=["limit"],
)

# AFTER
from pydantic import BaseModel
class MoviesByYearParams(BaseModel):
    released: int          # required arg  (was query_args_required)
    limit: int | None = None   # optional arg (was query_args_optional)

query = CypherQuery(
    name="movies_by_year",
    cypher_template="MATCH (m:Movie {released: $released}) RETURN m.title LIMIT $limit",
    Params=MoviesByYearParams,
)
```
Rules for the transform:
- `cypher=` → `cypher_template=`.
- Every name in `query_args_required` → a **required** field (no default) on a `Params`
  model. Use the type the test already expects; default to `str` if the test only passes
  strings, `int` if it passes ints, etc. (Look at the `build(...)` / `read(...)` call in
  the same test to pick the type.)
- Every name in `query_args_optional` → an **optional** field (`T | None = None`).
- Zero-arg query (`query_args_required=[]`, no optional) → `Params=NoParams`
  (`from orthograph.cypher.bindings import NoParams`).
- For **YAML/JSON fixtures**, apply the file-format transform instead: `query:` →
  `cypher_template:`; replace `query_args_required`/`query_args_optional` with a
  `params_schema:` block (see Target file format above). A required arg → listed in
  `required:` and in `properties:`; an optional arg → in `properties:` only (with a
  `default:`).
- Any assertion on `q.query_args_required` / `q.query_args_optional` → assert on
  `q.list_arguments()["required"]` / `["optional"]`, or on `q.Params.model_fields`.
- Any assertion on `q.cypher` → `q.cypher_template`.
- Tests that asserted `_check_spec_consistency` raised on overlap/mismatch (e.g.
  `test_query.py` cases passing the same name in both lists) **are obsolete** — the
  redundancy no longer exists. Delete those specific tests and note the deletion in the
  task report. **`[SONNET]` judgement** — if unsure whether a test is obsolete vs needs a
  new equivalent, flag it rather than deleting.

Sub-tasks:

- **T8a `[HAIKU]`** — `tests/cypher/test_query_execution.py` (4 refs). Smallest; do first
  as a pilot to validate the transform before fanning out.
  Verify: `uv run pytest tests/cypher/test_query_execution.py -q`.
- **T8b `[HAIKU]`** — `tests/cypher/test_query_e2e.py` (13 refs) + its YAML literals
  (note: `@pytest.mark.neo4j` tests need a DB; run the non-neo4j subset and rely on mypy +
  the YAML-load assertions).
  Verify: `uv run pytest tests/cypher/test_query_e2e.py -q -m "not neo4j"`.
- **T8c `[HAIKU]`** — `tests/cypher/test_validate_query_catalogue.py` (5 refs).
  Verify: `uv run pytest tests/cypher/test_validate_query_catalogue.py -q`.
- **T8d `[HAIKU]`** — `tests/io/test_query_catalogue_yaml.py` (11 refs). Pure file-format
  transform (no Python `Params` classes — use `params_schema:` blocks). The loader-level
  tests here are the canonical proof that the JSON-Schema round-trip works on load.
  Verify: `uv run pytest tests/io/test_query_catalogue_yaml.py -q`.
- **T8e `[SONNET]`** — `tests/cypher/test_query.py` (68 refs — the largest, and contains
  the consistency/overlap tests that are now obsolete). Needs judgement on which tests to
  delete vs migrate. Hand to Sonnet, not Haiku.
  Verify: `uv run pytest tests/cypher/test_query.py -q`.

---

### T9 — `[SONNET]` Full sweep, docs, and overview update

Depends on T8 complete.

1. Add new positive tests (if not already covered by T8):
   - A `CypherQuery` constructed in Python with a `Params` model, dumped via
     `model_dump(by_alias=True)`, re-loaded through the file loader, produces an
     equivalent query (`Params.model_fields` match, `cypher_template` matches).
   - A `CypherQuery` with `Identifiers` round-trips its `identifiers_schema`.
2. Run the **whole** suite: `uv run pytest -q -m "not neo4j"` and `uv run mypy src`.
   Both must be clean. (Run the neo4j-marked subset if a DB is available.)
3. Grep the entire repo (excluding `.mypy_cache`) for `query_args_required`,
   `query_args_optional`, and `CypherQuery(...).cypher` — must be zero hits in `src/` and
   `tests/`.
4. Update `.agentic/planning/overview.md`: add the E38 row, mark status, link the file.
5. Consider whether an ADR is warranted (this departs from the documented Noctis-derived
   spec). If yes, write `decisions/0NN-cypher-query-params-collapse.md` recording: the
   three-into-one collapse, the JSON-Schema wire format + `required`-array rationale, the
   `cypher`→`cypher_template` rename, and the no-back-compat decision. **`[SONNET]`
   judgement** — check existing ADRs (ADR referenced by E36/E37) to see if this amends
   one rather than adding a new one.

---

## Success Criteria

- [ ] `CypherQuery` exposes only `name`, `cypher_template`, `description`, `Params`
      (required), `Identifiers`, `identifiers`. No `query_args_*`, no
      `_check_spec_consistency`.
- [ ] `schema_codec.py` round-trips scalar `Params`/`Identifiers` models and fails loudly
      on unsupported constructs.
- [ ] File loader reads `cypher_template` + `params_schema` (+ optional
      `identifiers_schema`) and reconstructs typed models; old keys are rejected.
- [ ] `query_execution.py` no longer manufactures passthrough param models.
- [ ] `validation.py` and `catalogue.py` always source param fields from `Params`.
- [ ] Zero residual `query_args_*` references in `src/` and `tests/`.
- [ ] `uv run pytest -q -m "not neo4j"` and `uv run mypy src` clean.
- [ ] `overview.md` updated; ADR written or existing ADR amended.

---

## Risks / watch-items

- **`exclude_unset` vs `exclude_none` (T2/T4):** the read adapter currently strips `None`
  (`query_execution.py:181`). Switching `build()` to `exclude_unset` changes how an
  explicitly-passed `None` flows into the param dict. Reconcile against the migrated
  optional-arg tests; this is the single behavioural subtlety — escalate, don't guess.
- **Schema fidelity (T1):** only scalars round-trip. The codec must raise on
  nested/enum/array/constrained schemas rather than silently degrading to `Any`. Any real
  query that needs a non-scalar param is out of scope for the file-authored path and must
  use the typed path (`CypherReadQuery`/`CypherWriteQuery`).
- **Validation timing unchanged:** the simple path still validates at `validate_query()`
  time, not class-definition time like the typed path — the `cypher_template` rename does
  not change that. Note it in the docstring so the shared name doesn't imply the typed-
  path definition-time contract.
- **`.mypy_cache` hits:** the two `.mypy_cache/.../*.json` files containing
  `query_args_*` are regenerated artefacts — ignore; do not edit.
