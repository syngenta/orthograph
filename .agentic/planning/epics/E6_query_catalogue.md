# Epic E6: Query Catalogue

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Provide a schema-validated, named-query dispatch layer that eliminates inline Cypher strings from consuming applications
> **KPI:** A consuming application that today has N lines of inline Cypher should have 0 after adopting the query catalogue
> **Origin:** Product definition grilling session 2026-05-07 — see `reviews/2026-05-07_product-definition-grilling.md` Q7–Q8

---

## Context

Consuming applications today scatter Cypher query strings across Python files,
with no validation against the graph schema and no central catalogue. Each
application re-implements the same patterns: build a string, execute it, parse
results. This is the primary source of schema drift across multiple entry points
to the same database.

The query catalogue provides:
1. **A single place to declare queries** — in YAML (external config) or in Python (inline)
2. **Schema validation at load time** — every query is checked against the `GraphDataModel` before any execution
3. **Named dispatch** — consuming code calls `catalogue.execute("find_actors", params)` with no knowledge of the underlying Cypher
4. **Result validation** — returned data is optionally validated against the model

Two catalogue types share one dispatch interface:
- `CypherQueryCatalogue` — queries declared as Cypher strings (YAML or inline)
- `ORMQueryCatalogue` — queries declared as GQLAlchemy builder fragments (Python)

This epic covers the **CypherQueryCatalogue** in full. The ORMQueryCatalogue is described at epic level only — it requires a dedicated scoping session (see E7-placeholder below).

---

## Task E6.1: Define the YAML Schema for Query Declaration

**Objective:** Establish the YAML format for declaring named Cypher queries, their parameters, and their expected result shape.

**Context:** The YAML format is the primary interface for external configuration — it is what allows a consuming application to integrate Orthograph without code changes. The format must be human-readable, version-controllable, and self-documenting.

**Proposed format:**

```yaml
# queries.yaml
version: "1.0"
model: "path/to/schema.yaml"   # optional: path to GraphDataModel YAML

queries:
  find_actors:
    description: "Find all actors optionally filtered by name"
    cypher: |
      MATCH (p:Person)-[:ACTED_IN]->(m:Movie)
      WHERE $name IS NULL OR p.name = $name
      RETURN p, m
    parameters:
      name:
        type: string
        required: false
        default: null
    returns:
      - variable: p
        label: Person
      - variable: m
        label: Movie

  create_person:
    description: "Create or merge a Person node"
    cypher: |
      MERGE (p:Person {name: $name})
      SET p.born = $born
      RETURN p
    parameters:
      name:
        type: string
        required: true
      born:
        type: integer
        required: false
    returns:
      - variable: p
        label: Person
```

**Implementation:**

1. Define a Pydantic model for the YAML schema in `src/orthograph/catalogue/models.py`:
   - `QueryCatalogueConfig` — top-level container
   - `QueryDefinition` — single query: name, description, cypher, parameters, returns
   - `ParameterDefinition` — name, type, required, default
   - `ReturnDefinition` — variable name, expected label

2. Write `src/orthograph/catalogue/loader.py`:
   - `load_catalogue_config(path: str | Path) -> QueryCatalogueConfig`
   - Validates YAML structure against `QueryCatalogueConfig` at load time
   - Raises `CatalogueLoadError` with clear message on schema mismatch

3. Add tests in `tests/catalogue/test_loader.py`:
   - `test_load_valid_catalogue`
   - `test_load_missing_required_field_raises`
   - `test_load_unknown_parameter_type_raises`
   - `test_load_empty_catalogue_valid`

**Acceptance criteria:**
- Valid YAML loads without error
- Missing required fields raise `CatalogueLoadError` with field name in message
- Pydantic model is frozen (immutable after load)

---

## Task E6.2: Implement Query Validation Against GraphDataModel

**Objective:** Validate each query in the catalogue against the `GraphDataModel` at load time — labels, relationship types, properties, and endpoint patterns must all be known to the model.

**Context:** This is the core value of the catalogue: errors are caught at startup, not at runtime. A query referencing an unknown label `Persoon` (typo) should fail immediately when the catalogue is loaded, not when it is first executed in production.

**Implementation:**

1. In `src/orthograph/catalogue/validation.py`, implement:

```python
def validate_catalogue(
    config: QueryCatalogueConfig,
    model: GraphDataModel,
) -> ValidationResult:
    """
    Validate all queries in a catalogue against a GraphDataModel.
    Reuses extensions/cypher/parser.py validate_cypher() for each query.
    Returns aggregated ValidationResult across all queries.
    """
```

2. Each query's Cypher string is passed through the existing `validate_cypher(query, model)` from `extensions/cypher/parser.py`. No new validation logic — reuse what exists.

3. Additionally validate `returns` declarations: each `label` in `returns` must exist in the model.

4. Collect all issues across all queries into one `ValidationResult` — include the query name in each issue message.

5. Add tests in `tests/catalogue/test_validation.py`:
   - `test_validate_valid_catalogue`
   - `test_validate_unknown_label_raises`
   - `test_validate_unknown_rel_type_raises`
   - `test_validate_unknown_property_raises`
   - `test_validate_multiple_queries_collects_all_errors`

**Acceptance criteria:**
- Valid catalogue against matching model returns clean `ValidationResult`
- Invalid queries produce `ValidationResult` with query name in issue message
- All 4 existing Cypher validation codes are surfaced

---

## Task E6.3: Implement `CypherQueryCatalogue` — Core Class

**Objective:** Implement the catalogue object that consuming applications hold and call queries on.

**Context:** This is the primary interface for consuming applications. It loads, validates, and dispatches queries. The application never writes a Cypher string.

**Implementation:**

1. In `src/orthograph/catalogue/cypher.py`:

```python
class CypherQueryCatalogue:
    """
    A validated, named-query catalogue for Cypher queries.

    Load from YAML:
        catalogue = CypherQueryCatalogue.from_yaml("queries.yaml", model=model)

    Register inline:
        catalogue = CypherQueryCatalogue(model=model)
        catalogue.register("find_actors", cypher="MATCH ...", parameters={...})

    Execute:
        results = catalogue.execute("find_actors", {"name": "Alice"}, db=driver)
    """

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        model: GraphDataModel,
        validate: bool = True,
    ) -> "CypherQueryCatalogue": ...

    def register(
        self,
        name: str,
        cypher: str,
        parameters: dict | None = None,
        description: str = "",
    ) -> None: ...

    def execute(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        db: Any = None,
        validate_results: bool = False,
    ) -> list[dict[str, Any]]: ...

    def validate_query(self, name: str) -> ValidationResult: ...

    def query_names(self) -> list[str]: ...

    def get_definition(self, name: str) -> QueryDefinition: ...
```

2. `from_yaml` calls `load_catalogue_config()` then `validate_catalogue()` (if `validate=True`), then constructs the catalogue.

3. `execute` resolves the named query, substitutes parameters, executes via the provided `db` driver, optionally validates results using existing `validate_result()` from `extensions/neo4j/result_adapter.py`.

4. `register` allows inline query registration — validates the Cypher string immediately against the model.

5. Add tests in `tests/catalogue/test_cypher_catalogue.py`:
   - `test_from_yaml_valid`
   - `test_from_yaml_invalid_query_raises`
   - `test_register_valid_query`
   - `test_register_invalid_query_raises`
   - `test_execute_returns_results` (mocked driver)
   - `test_execute_unknown_name_raises`
   - `test_execute_missing_required_param_raises`
   - `test_query_names_returns_all`

**Acceptance criteria:**
- `catalogue.execute("find_actors", {"name": "Alice"}, db=driver)` executes the registered query
- Unknown query name raises `KeyError` with catalogue name in message
- Missing required parameter raises `ValueError`
- `from_yaml` with invalid queries raises on construction (fail fast)

---

## Task E6.4: Public API and Package Structure

**Objective:** Expose the query catalogue through a clean top-level import, consistent with the rest of Orthograph's public API.

**Implementation:**

1. Create `src/orthograph/catalogue/` package:
   ```
   src/orthograph/catalogue/
   ├── __init__.py         # Public re-exports
   ├── models.py           # QueryCatalogueConfig, QueryDefinition, etc.
   ├── loader.py           # load_catalogue_config()
   ├── validation.py       # validate_catalogue()
   └── cypher.py           # CypherQueryCatalogue
   ```

2. In `src/orthograph/catalogue/__init__.py`:
   ```python
   from orthograph.catalogue.cypher import CypherQueryCatalogue
   from orthograph.catalogue.models import QueryCatalogueConfig, QueryDefinition
   from orthograph.catalogue.validation import validate_catalogue

   __all__ = [
       "CypherQueryCatalogue",
       "QueryCatalogueConfig",
       "QueryDefinition",
       "validate_catalogue",
   ]
   ```

3. Add `catalogue` as a top-level re-export in `src/orthograph/__init__.py` (or keep it explicit — prefer explicit to avoid surprises).

4. Add optional dependency: `catalogue` extra in `pyproject.toml` requires `graphglot` (already needed for Cypher parsing).

5. Add notebook `04.01_query_catalogue.ipynb`:
   - Define a `GraphDataModel`
   - Write a `queries.yaml`
   - Load and validate the catalogue
   - Execute queries (mocked or live Neo4j/Memgraph)
   - Show inline registration as alternative

**Acceptance criteria:**
- `from orthograph.catalogue import CypherQueryCatalogue` works
- Notebook demonstrates end-to-end workflow
- `pip install orthograph[catalogue]` installs required extras

---

## Epic E6-ORM: ORM Query Catalogue *(scoping required)*

**Status:** Intent defined, implementation not scoped.

**Intent:** A `ORMQueryCatalogue` that stores GQLAlchemy builder patterns as named, reusable queries. Same dispatch interface as `CypherQueryCatalogue` — consuming code calls `catalogue.execute("find_actors", params)` regardless of catalogue type. Queries are defined in Python (not YAML) since builder patterns are code, not strings.

**Open questions requiring a dedicated scoping session:**
- How are builder pattern queries serialised/stored? (Python functions? Lambda? Callable registry?)
- How is validation applied to builder patterns before execution? (Extract Cypher via `str(builder)` then reuse existing `validate_cypher()`?)
- Should both catalogue types share a common abstract base class or Protocol?
- Can a mixed catalogue (some Cypher strings, some ORM builders) be supported?

**Prerequisite:** E6.1–E6.4 must be complete and validated in a pilot project before this is scoped.
