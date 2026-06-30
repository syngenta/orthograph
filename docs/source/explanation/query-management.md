# Query Management — Cypher Queries and Typed Query Contracts

Orthograph provides two authoring paths for Cypher queries: the **simple path**
(`CypherQuery`) and the **typed path** (`TypedCypherReadQueryModel` /
`TypedCypherWriteQueryModel`). Both can be registered in a query catalogue,
validated against a `GraphDefinition`, and executed against a backend.

Choose the simple path for low-ceremony scripts, YAML-configured queries, and
cases where raw rows are sufficient. Choose the typed path when you want
statically-typed parameters, statically-typed result objects, and the full IDE
support that comes with Pydantic models.

→ **Tutorials:** Pillar 3 covers query management end to end:
  {doc}`../notebooks/03.01_cypher_generation`,
  {doc}`../notebooks/03.02_cypher_query_definitions`,
  {doc}`../notebooks/03.03_cypher_query_usage`,
  {doc}`../notebooks/03.04_typed_query_contracts`,
  {doc}`../notebooks/03.05_typed_query_result_shapes_and_materialization`.

---

## The simple path — `CypherQuery`

`CypherQuery` is a concrete, YAML-serialisable Pydantic model. You instantiate
it directly; no subclassing required.

```python
from pydantic import BaseModel
from orthograph.queries import simple_query

class PersonParams(BaseModel):
    name: str

q = simple_query(
    query_id="find_person",
    cypher_template="MATCH (p:Person {name: $name}) RETURN p",
    params_schema=PersonParams,
)
```

- `params_schema` declares the parameter shape as a Pydantic model. The
  validator checks that every `$name` placeholder in the template matches a
  field in the model.
- Results are returned as `list[dict[str, Any]]` — raw rows, no
  materialisation.
- `CypherQuery` makes **no read/write distinction**. The executor you choose
  determines whether the query is sent as a read or a mutation.
- `CypherQuery` can be round-tripped to/from YAML via
  `src/orthograph/cypher/schema_codec.py`.

---

## The typed path — `TypedCypherReadQueryModel` / `TypedCypherWriteQueryModel`

Typed queries are subclasses. You declare the parameter model, the output model,
and implement `materialize` to turn a raw result row into your output type.

```python
from pydantic import BaseModel
from orthograph.queries import TypedCypherReadQueryModel

class PersonParams(BaseModel):
    name: str

class PersonRow(BaseModel):
    name: str
    born: int | None

class FindPerson(TypedCypherReadQueryModel[PersonParams, PersonRow]):
    query_id = "find_person"
    cypher_template = "MATCH (p:Person {name: $name}) RETURN p.name AS name, p.born AS born"
    params_schema = PersonParams

    @classmethod
    def materialize(cls, raw: dict) -> PersonRow:
        return PersonRow.model_validate(raw)
```

- `P` (the first type parameter) is the params model — `fetch()` / `run_read()`
  accepts a `PersonParams` instance.
- `D` (the second type parameter) is the output model — `fetch()` returns
  `list[PersonRow]`.
- `TypedCypherWriteQueryModel[P, R]` is the write counterpart; `R` is the
  result summary type.
- The executors are generic over `ReadQueryModel[P, D]` / `WriteQueryModel[P, R]`
  so the return type is fully inferred by the type checker.

---

## The query catalogue

Both query kinds can be registered in a **query catalogue** — a named, typed
container that governs a set of queries as a unit.

```python
from orthograph.queries import new_catalogue

catalogue = new_catalogue(name="my_graph")
catalogue.register(find_person_query)
catalogue.register(update_status_query)

# validate the whole catalogue against the contract
from orthograph.queries import validate_catalogue
result = validate_catalogue(catalogue, definition)
```

Catalogue validation runs [query validation](query-validation.md) for every
registered query and returns a single aggregated `ValidationResult`. This is the
primary drift-detection entry point for the query-set layer.

---

## Query identifiers — `query_id`

Every query carries a `query_id` string used as its canonical name in error
messages, catalogue lookups, and YAML serialisation. For `CypherQuery` this is
the `name` field (legacy name preserved); for typed queries it is the
`query_id` class variable.

---

## Cypher identifiers and the template language

Cypher templates support two slot types:

- **`$name`** — a query parameter. The value is sent to the database as a
  parameter (safe, no injection risk). Declared in `params_schema`.
- **`<<identifier>>`** — a Cypher identifier (label, property key, relationship
  type) spliced directly into the query string. Declared in `identifiers_schema`.
  Every identifier is validated against `^[A-Za-z_][A-Za-z0-9_]*$` before
  splicing to prevent injection.

---

## Cypher generation from the definition

Orthograph can generate Cypher queries directly from a `GraphDefinition`:

```python
from orthograph.queries import generate_queries

queries = generate_queries(definition)
# returns a list of CypherQuery for common CRUD patterns
```

See {doc}`../notebooks/03.01_cypher_generation` for a walkthrough.

---

## Implementation locations

| Concern | Module |
|---|---|
| `CypherQuery` + `simple_query` factory | `src/orthograph/cypher/query.py` |
| `TypedCypherReadQueryModel` / `TypedCypherWriteQueryModel` | `src/orthograph/cypher/query.py` |
| `ReadQueryModel` / `WriteQueryModel` ABCs | `src/orthograph/cypher/base_models.py` |
| Query catalogue | `src/orthograph/query/` |
| Cypher template generator | `src/orthograph/cypher/generator.py` |
| Identifier validation | `src/orthograph/cypher/identifiers.py` |
| YAML round-trip | `src/orthograph/cypher/schema_codec.py` |
| Public API | `src/orthograph/queries.py` |
| ADR-047 (simple path execution) | `.agentic/decisions/047-simple-path-cypher-execution-surface.md` |
| ADR-043 (query validation surface) | `.agentic/decisions/043-query-validation-public-api-two-phases-two-input-grades.md` |
