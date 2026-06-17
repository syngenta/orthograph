# Epic E36: CypherQuery Naming Convergence + Class-Based Query Definitions

> **Priority:** Medium
> **Phase:** v0.1.0 — adoption readiness (makes orthograph adoptable as a noctis/MP dependency)
> **Blocked by:** none (E19/E16 query authoring decision already landed; `CypherQuerySpec` exists)
> **Blocks:** future noctis dependency adoption; a later "Typed* prefix" epic (E37, not in scope here)
> **Type:** Refactor (rename) + small build (new class) + docs + tests

---

## Why This Epic Exists

Orthograph offers two parallel ways to define a Cypher query:

1. **Typed queries** — `CypherReadQuery` / `CypherWriteQuery` (abstract bases you subclass;
   require `Params`, `Output`, `cypher_template`, `materialize()` / `interpret_result()`).
   Full contract, definition-time validation, typed results. Higher ceremony.
2. **Spec queries** — `CypherQuerySpec` (a concrete Pydantic class you instantiate; name +
   cypher string + argument lists, optional `Params`, schema-validatable, YAML-round-trippable).
   Low ceremony. This is the path that mirrors how MP/noctis already author queries.

The spec path is the low-friction on-ramp that lets orthograph become a dependency of noctis
without forcing the typed contract. This epic does three things:

1. **Removes a naming hazard.** The tuple `build()` returns is currently the type alias
   `CypherQuery = tuple[str, dict]`. That name is being claimed for the spec class. The tuple is
   renamed to `CypherQueryData` (a `NamedTuple`) so it cannot be confused with *executed* query
   results (which `materialize()` produces).
2. **Promotes the spec class to the obvious name.** `CypherQuerySpec` → `CypherQuery`. It is the
   first thing a migrator reaches for, so it gets the plain name.
3. **Adds a class-based authoring style** for the spec path (`CypherQueryBase`), mirroring
   noctis's `AbstractQuery` ↔ `CustomQuery` split, so consumers can define named queries as
   classes in code, not only as runtime instances or YAML.

A later epic (out of scope) will rename `CypherReadQuery` / `CypherWriteQuery` to
`TypedCypherReadQuery` / `TypedCypherWriteQuery`. GQLAlchemy bases are left untouched.

---

## Decisions Already Made (do not re-litigate)

- The tuple type is named **`CypherQueryData`** and is a **`NamedTuple`** with fields
  `cypher: str` and `params: dict[str, Any]`. NamedTuple preserves `cypher, params = ...`
  unpacking everywhere, so no call site that unpacks needs to change.
- The spec instance class is renamed **`CypherQuerySpec` → `CypherQuery`**.
- The spec error is renamed **`CypherQuerySpecError` → `CypherQueryError`** and remains an
  unrelated sibling of `CypherQueryDefinitionError` under `CypherError` (no inheritance between
  them).
- The module is renamed **`cypher/query_spec.py` → `cypher/query.py`**.
- The class-based base is named **`CypherQueryBase`** and exposes **`to_spec()`**… renamed to
  **`to_query()`** (returns a `CypherQuery` instance). Class-based definitions are convertible to
  instances; they are NOT independently executable (one execution surface: `CypherQuery.build()`).
- **No registry** in this epic.
- **GQLAlchemy bases unchanged** in this epic.
- The public API function `load_query_catalogue` and `list_catalogue_queries` keep their names
  (they already do not contain "spec").
- `CypherCatalogueLoadError` keeps its name.

---

## Blast Radius (exact, verified)

### `CypherQuery` (the tuple alias) → `CypherQueryData`

Defined in `src/orthograph/cypher/bindings.py:18`. Referenced in **8 files**:

| File | Lines |
|------|-------|
| `src/orthograph/cypher/bindings.py` | 18 (definition + docstring) |
| `src/orthograph/cypher/base_models.py` | 46 (import), 179, 234 (return annotations) |
| `src/orthograph/backends/neo4j/queries.py` | 15 (import), 118, 154, 191 |
| `src/orthograph/backends/memgraph/queries.py` | 13 (import), 86, 113, 136 |
| `tests/cypher/test_base_models.py` | 27 (import), 73, 348, 370 |
| `tests/cypher/test_validate_query_catalogue.py` | 26 (import), 134, 198 |
| `tests/cypher/test_query_execution.py` | 238 (import), 249, 268, 278 |

These are all **type annotations** (`-> CypherQuery`) and imports. No unpacking call site changes
because `CypherQueryData` is a NamedTuple and the producing `build()` returns it positionally.

### `CypherQuerySpec` → `CypherQuery`, `CypherQuerySpecError` → `CypherQueryError`, `query_spec.py` → `query.py`

Referenced in **7 files**:

| File | What |
|------|------|
| `src/orthograph/cypher/query_spec.py` | the class, error import, docstrings, `_validate_structure` return annotation, `__repr__` → rename file to `query.py` |
| `src/orthograph/cypher/exceptions.py` | `CypherQuerySpecError` class (line 58) → `CypherQueryError` |
| `src/orthograph/io/query_catalogue_yaml.py` | import (line 61), annotations (66, 76, 97, 107, 155, 168, 174, 201), docstring (4) |
| `src/orthograph/api/model.py` | imports (19, 22), annotation (120), docstring (131), `__all__` (160, 161) |
| `tests/cypher/test_query_spec.py` | import (36, 37) + ~60 usages → rename file to `test_query.py` |
| `tests/cypher/test_exceptions.py` | import (7), usages (22, 31, 40–43) |
| `tests/io/test_query_catalogue_yaml.py` | import (23), usage (91) |

`src/orthograph/cypher/__init__.py` is a bare docstring — no re-exports to update. `pyproject.toml`
has no references. No `__all__` in the cypher package leaks these names.

---

## Tasks (execute in order; each task ends green)

### E36.1 — Rename the tuple alias to `CypherQueryData` (NamedTuple)

> **Model: Sonnet.** Touches type annotations across 8 files including the abstract `build()`
> bases and imperative test builds; requires judgement on which returns to wrap in the NamedTuple.

**Goal:** the artefact `build()` returns is a named, unpackable tuple, not confusable with results.

1. In `src/orthograph/cypher/bindings.py`, replace:
   ```python
   CypherQuery = tuple[str, dict[str, Any]]
   """A built Cypher query: the Cypher string and its parameter dict."""
   ```
   with:
   ```python
   class CypherQueryData(NamedTuple):
       """A built Cypher query ready to execute: the Cypher string and its
       parameter dict. This is NOT a query result — results are produced by an
       executor materialising records. Unpacks as ``cypher, params = ...``.
       """
       cypher: str
       params: dict[str, Any]
   ```
   Add `from typing import NamedTuple` to the imports (keep `Any`).
2. In every file listed in the blast-radius table for the alias, change the **import name**
   `CypherQuery` → `CypherQueryData` and the **return annotations** `-> CypherQuery` →
   `-> CypherQueryData`.
3. In `base_models.py` `build()` bodies (lines ~179, ~234), the current `return rendered,
   params.model_dump()` continues to work (positional NamedTuple construction is implicit via
   the tuple). **Optionally** make it explicit: `return CypherQueryData(rendered,
   params.model_dump())`. Do this for clarity — it is the canonical construction.
4. In the imperative-style test builds that `return ("...", {...})`, leave them as plain tuples
   OR wrap in `CypherQueryData(...)`. Plain tuples still satisfy the annotation at runtime;
   prefer wrapping the two in `test_base_models.py` for consistency, leave others as-is if they
   already pass.

**Verify:**
```
pwsh> python -m pytest tests/cypher -q
```
All cypher tests green. No reference to the old `CypherQuery` alias remains:
```
pwsh> Select-String -Path src,tests -Include *.py -Pattern "\bCypherQuery\b" -Recurse | Select-String -NotMatch "CypherQueryData|CypherQuerySpec|CypherQueryDefinitionError|CypherQueryError"
```
(should return nothing once E36.2 is also done; at this step the spec class still uses
`CypherQuerySpec`, so matches there are expected and fine.)

---

### E36.2 — Rename spec class, error, and module

> **Model: Haiku.** Pure mechanical rename across a fully-enumerated file list; no design
> judgement. The exact blast-radius table and the final `Select-String` gate make this
> verifiable without reasoning.

**Goal:** `CypherQuerySpec` → `CypherQuery`; `CypherQuerySpecError` → `CypherQueryError`;
`query_spec.py` → `query.py`; `test_query_spec.py` → `test_query.py`.

1. **Exceptions** — in `src/orthograph/cypher/exceptions.py`, rename class
   `CypherQuerySpecError` → `CypherQueryError`. Update its docstring to reference
   `CypherQuery` (the class) instead of `CypherQuerySpec`. Keep it a direct subclass of
   `CypherError`, sibling to `CypherQueryDefinitionError` (no inheritance between the two).
2. **Module rename** — rename file `src/orthograph/cypher/query_spec.py` →
   `src/orthograph/cypher/query.py`. Inside it:
   - class `CypherQuerySpec` → `CypherQuery`
   - import `from orthograph.cypher.exceptions import CypherQuerySpecError` →
     `CypherQueryError`
   - all `raise CypherQuerySpecError(` → `raise CypherQueryError(`
   - `_validate_structure` return annotation `CypherQuerySpec` → `CypherQuery`
   - `__repr__` string `CypherQuerySpec(` → `CypherQuery(`
   - update module + class docstrings: replace `CypherQuerySpec` with `CypherQuery`; keep the
     "instantiate directly; for typed queries use CypherReadQuery/CypherWriteQuery" contrast.
3. **Consumers**:
   - `src/orthograph/io/query_catalogue_yaml.py`: import
     `from orthograph.cypher.query import CypherQuery`; replace every `CypherQuerySpec`
     annotation/usage with `CypherQuery`; update docstring cross-ref to
     `orthograph.cypher.query.CypherQuery`.
   - `src/orthograph/api/model.py`: import `CypherQuery` from `orthograph.cypher.query` and
     `CypherQueryError` from `orthograph.cypher.exceptions`; update the `load_query_catalogue`
     return annotation and docstring; update `__all__` entries `"CypherQuerySpec"` →
     `"CypherQuery"` and `"CypherQuerySpecError"` → `"CypherQueryError"`.
4. **Tests**:
   - rename `tests/cypher/test_query_spec.py` → `tests/cypher/test_query.py`; replace all
     `CypherQuerySpec` → `CypherQuery`, `CypherQuerySpecError` → `CypherQueryError`, and the
     import path `orthograph.cypher.query_spec` → `orthograph.cypher.query`. Update the module
     docstring header (`Tests for CypherQuerySpec.` → `Tests for CypherQuery.`).
   - `tests/cypher/test_exceptions.py`: `CypherQuerySpecError` → `CypherQueryError` in import,
     assertions, and the independence test name/body.
   - `tests/io/test_query_catalogue_yaml.py`: import `CypherQuery` from
     `orthograph.cypher.query`; usage on line ~91 `isinstance(q, CypherQuery)`.

**Verify:**
```
pwsh> python -m pytest tests/cypher tests/io tests/api -q
pwsh> Select-String -Path src,tests -Include *.py -Pattern "CypherQuerySpec|query_spec" -Recurse
```
First command green; second returns nothing.

---

### E36.3 — Add class-based authoring: `CypherQueryBase`

> **Model: Sonnet.** New class with `__init_subclass__` definition-time validation and a shared
> helper extraction; requires care with the abstract-base skip condition and ClassVar semantics.

**Goal:** allow defining a spec query as a class, convertible to a `CypherQuery` instance.

1. In `src/orthograph/cypher/query.py`, extract the structural checks currently inside
   `CypherQuery._validate_structure` (arg-list overlap; Params-field coverage) into a module-level
   helper, e.g.:
   ```python
   def _check_spec_consistency(
       *, name: str,
       query_args_required: list[str],
       query_args_optional: list[str],
       params: type[BaseModel] | None,
   ) -> None:
       """Raise CypherQueryError on overlap or Params/arg mismatch."""
   ```
   Make `CypherQuery._validate_structure` call it (identical messages, identical
   `CypherQueryError`).
2. Add the class-based base in the same module:
   ```python
   class CypherQueryBase:
       """Class-based counterpart to CypherQuery — subclass to define a named
       Cypher query as a class. Declare query metadata as ClassVars. Structural
       validation runs at class-definition time via __init_subclass__ (consistent
       with CypherReadQuery). To author at runtime or from YAML, use CypherQuery
       directly. Convert a subclass to a runnable instance with to_query().
       """
       query_name: ClassVar[str]
       query: ClassVar[str]
       query_args_required: ClassVar[list[str]] = []
       query_args_optional: ClassVar[list[str]] = []
       description: ClassVar[str | None] = None
       Params: ClassVar[type[BaseModel] | None] = None

       def __init_subclass__(cls, **kwargs: Any) -> None:
           super().__init_subclass__(**kwargs)
           # skip the abstract base's own (incomplete) defaults: only validate
           # subclasses that declare query_name AND query
           if not hasattr(cls, "query_name") or not hasattr(cls, "query"):
               return
           _check_spec_consistency(
               name=cls.query_name,
               query_args_required=list(cls.query_args_required),
               query_args_optional=list(cls.query_args_optional),
               params=cls.Params,
           )

       @classmethod
       def to_query(cls) -> "CypherQuery":
           """Convert this class definition to a runnable CypherQuery instance."""
           return CypherQuery(
               name=cls.query_name,
               cypher=cls.query,
               query_args_required=list(cls.query_args_required),
               query_args_optional=list(cls.query_args_optional),
               description=cls.description,
               Params=cls.Params,
           )
   ```
   Add `from typing import ClassVar` to imports.
3. Update `src/orthograph/api/model.py` `__all__` to also export `"CypherQueryBase"`, and add the
   import. (Do not add a registry, loader, or any catalogue support for the class-based form —
   `to_query()` is the only bridge.)

**Verify:** new tests below pass; existing tests unaffected.

---

### E36.4 — Tests for `CypherQueryBase`

> **Model: Sonnet.** Writing six new tests, including definition-time-failure cases that need a
> nested `class` inside `pytest.raises`; requires understanding the behaviour under test.

Append to `tests/cypher/test_query.py` (pytest functions, one-line docstrings, no comments
between functions, movie domain). Cover:

1. `test_query_base_subclass_valid_definition` — a subclass with `query_name` + `query` +
   required args is defined without error.
2. `test_query_base_to_query_returns_equivalent_instance` — `to_query()` yields a `CypherQuery`
   whose `.name`, `.cypher`, `.query_args_required`, `.query_args_optional`, `.description` match
   the ClassVars.
3. `test_query_base_overlap_raises_at_definition_time` — defining a subclass with an arg in both
   required and optional raises `CypherQueryError` (use a nested `class` inside `pytest.raises`).
4. `test_query_base_params_missing_field_raises_at_definition_time` — Params model missing a
   declared arg raises `CypherQueryError` at class definition.
5. `test_query_base_to_query_result_builds_and_validates` — `to_query().build(...)` returns a
   `CypherQueryData` and `to_query().validate(None).is_valid` is True.
6. `test_query_base_and_instance_equivalent_model_dump` — a class-based definition's
   `to_query().model_dump(by_alias=True, exclude_none=True)` equals the equivalent hand-built
   `CypherQuery(...)` model_dump.

**Verify:**
```
pwsh> python -m pytest tests/cypher/test_query.py -q
```
All green.

---

### E36.5 — Documentation: docstrings + notebook + reference

> **Model: Sonnet.** Authoring prose and a runnable end-to-end notebook that must execute clean;
> requires explaining the two-paths distinction clearly and constructing correct example cells.

1. **Module docstrings** — in `src/orthograph/cypher/query.py`, ensure the module docstring opens
   with the "two parallel paths" contrast (typed vs spec) and documents both `CypherQuery` and
   `CypherQueryBase`. In `src/orthograph/cypher/base_models.py`, add one sentence to the module
   docstring pointing to `orthograph.cypher.query.CypherQuery` as the lighter, untyped alternative.
2. **Notebook** — create `notebooks/04.06_cypher_query_definitions.ipynb`:
   - Section 1: the two paths, when to use which (one short markdown table).
   - Section 2: `CypherQuery` instance from Python; `.build()` → `CypherQueryData`
     (show `.cypher` / `.params` access AND `cypher, params = ...` unpacking).
   - Section 3: loading a YAML catalogue via `orthograph.api.model.load_query_catalogue`.
   - Section 4: `CypherQueryBase` class-based definition + `to_query()`.
   - Section 5: `validate()` against a `GraphDefinition` (one valid, one unknown-label example).
   - Use the movie domain (Movie / Festival) consistent with existing tests.
   - Keep cells runnable end-to-end with no DB connection.
3. **Reference** — in `docs/source/reference/index.rst`, add a short subsection distinguishing
   the typed and spec paths and listing `CypherQuery`, `CypherQueryBase`, `CypherQueryData`,
   `CypherQueryError`.

**Verify:**
```
pwsh> python -m pytest --nbval-lax notebooks/04.06_cypher_query_definitions.ipynb -q
```
(notebooks are validated via nbval per the existing `tests/notebooks` setup; if that harness
runs all notebooks, run the whole notebook suite instead.)

---

### E36.6 — Write ADR and update planning index

> **Model: Sonnet.** Recording rationale and trade-offs in ADR prose, matching the existing ADR
> house style; requires synthesis of the decisions made across the epic.

1. Create `.agentic/decisions/026-cypher-query-naming-and-spec-class.md` recording:
   - The rename chain (`CypherQuery` alias → `CypherQueryData` NamedTuple; `CypherQuerySpec` →
     `CypherQuery`; `CypherQuerySpecError` → `CypherQueryError`; module `query_spec.py` →
     `query.py`).
   - The addition of `CypherQueryBase` and the noctis `AbstractQuery`↔`CustomQuery` parallel.
   - The deferred decision: `CypherReadQuery`/`CypherWriteQuery` → `Typed*` prefix (future epic);
     GQLAlchemy bases unchanged.
   - Rationale for `CypherQueryData` over `CypherQueryResult` (avoid confusion with executed
     results).
2. Add E36 to `.agentic/planning/overview.md` epic index with status and the E37 (Typed-prefix)
   follow-on note.

---

## Success Criteria

- [ ] `CypherQueryData` is a `NamedTuple(cypher, params)`; no `CypherQuery` tuple alias remains.
- [ ] `CypherQuery` is the spec class; `CypherQuerySpec` appears nowhere in `src` or `tests`.
- [ ] `CypherQueryError` replaces `CypherQuerySpecError`; sibling of `CypherQueryDefinitionError`.
- [ ] Module is `cypher/query.py`; `query_spec.py` is gone; tests in `test_query.py`.
- [ ] `CypherQueryBase` exists with `to_query()`; definition-time validation works.
- [ ] All of `tests/cypher`, `tests/io`, `tests/api` pass.
- [ ] Notebook `04.06_cypher_query_definitions.ipynb` runs clean.
- [ ] ADR-026 written; overview index updated.
- [ ] `Select-String` for `CypherQuerySpec|query_spec` across `src` + `tests` returns nothing.

---

## Out of Scope

- Renaming `CypherReadQuery` / `CypherWriteQuery` to `Typed*` (future epic E37).
- Any change to GQLAlchemy query bases.
- A query registry for class-based definitions.
- Catalogue/YAML support for `CypherQueryBase` (only `to_query()` bridges to the instance path).
- Changing the executor, `materialize()`, or any runtime execution behaviour.
