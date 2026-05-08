# Epic E6: Cypher Query Catalogue

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Provide a schema-validated, named-query registry for Cypher that eliminates inline query strings from consuming applications
> **Blocked by:** None — can start immediately (critical path)
> **User stories:** 8, 9, 10, 11, 12, 13

---

## Context

Consuming applications today scatter Cypher query strings across Python files,
with no validation against the graph schema and no central catalogue. Each
application re-implements the same patterns: build a string, execute it, parse
results. This is the primary source of schema drift across multiple entry points
to the same database.

The Cypher Query Catalogue provides:
1. **A single place to declare queries** — in YAML (external config) or in Python (runtime registration)
2. **Schema validation at registration time** — every query is checked against the `GraphDataModel`
3. **Named dispatch** — consuming code calls `catalogue.execute("find_actors", params, connection=conn)` with no knowledge of the underlying Cypher
4. **Result type validation** — returned data is validated against declared output types

**Architectural principle:** Orthograph provides the registry container and validation logic. Consuming projects provide the actual queries and database connections (passed per-call).

---

## Tasks

### E6.1: Define YAML Schema and Catalogue Models

Establish the Pydantic models for query declarations and the YAML format.

**Acceptance criteria:**
- [ ] `QueryDefinition` model: name, description, cypher, parameters (name/type/required/default), returns (field/type map or model reference)
- [ ] `QueryCatalogueConfig` model: version, optional model path, dict of queries
- [ ] `load_catalogue_config(path) -> QueryCatalogueConfig` loads and validates YAML
- [ ] Invalid YAML raises `CatalogueLoadError` with clear message
- [ ] Tests cover valid load, missing fields, unknown types, empty catalogue

---

### E6.2: Implement Query Validation Against GraphDataModel

Validate each query in the catalogue against the schema at load/registration time.

**Acceptance criteria:**
- [ ] `validate_catalogue(config, model) -> ValidationResult` validates all queries
- [ ] Reuses existing `validate_cypher()` from `extensions/cypher/parser.py`
- [ ] Additionally validates `returns` declarations (labels must exist in model)
- [ ] Query name included in each issue message
- [ ] Tests cover: valid catalogue, unknown label/rel_type/property, multiple errors collected

---

### E6.3: Implement `CypherQueryCatalogue` — Core Class

The catalogue object that consuming applications hold and call queries on.

**Acceptance criteria:**
- [ ] `CypherQueryCatalogue.from_yaml(path, model)` loads, validates, and constructs
- [ ] `catalogue.register(name, cypher, parameters, returns)` for runtime registration (validates immediately)
- [ ] `catalogue.execute(name, params, connection=conn)` runs query (connection passed per-call, never stored)
- [ ] `catalogue.execute(name, params, connection=conn, validate_results=True)` validates result against declared output type
- [ ] `catalogue.query_names()` and `catalogue.get_definition(name)` for introspection
- [ ] Unknown name raises `KeyError`, missing required param raises `ValueError`
- [ ] Tests cover: from_yaml, register, execute (mocked), result validation, error cases

---

### E6.4: Public API and Package Structure

Expose the catalogue through a clean import path.

**Acceptance criteria:**
- [ ] `from orthograph.catalogue import CypherQueryCatalogue` works
- [ ] Package structure: `src/orthograph/catalogue/{__init__, models, loader, validation, cypher}.py`
- [ ] Optional dependency group `catalogue` in `pyproject.toml` (requires `graphglot`)
- [ ] Notebook `04.01_query_catalogue.ipynb` demonstrates end-to-end workflow

---

## Relationship to Other Epics

- **E8 (GQLAlchemy Query Catalogue)** shares the registry interface pattern from this epic
- **E11 (Auto-Generated CRUD)** populates catalogues with schema-derived operations
- **E12 (Shared Interface)** extracts the common ABC after both E6 and E8 are complete
