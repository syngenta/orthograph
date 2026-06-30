# Register and validate a typed query catalogue

**Goal:** register Cypher queries in a `QueryCatalogue` and verify that
the entire set is structurally consistent with a `GraphDefinition` — without
executing any query.

---

## Steps

### 1. Create a catalogue

```python
from orthograph.queries import new_catalogue

catalogue = new_catalogue()
```

### 2. Register a simple Cypher query

Use `simple_query` for plain Cypher templates with a `params` schema:

```python
from pydantic import BaseModel
from orthograph.queries import simple_query

class FindPersonParams(BaseModel):
    name: str

catalogue.register_cypher_query(
    simple_query(
        name="find_person_by_name",
        cypher_template="MATCH (p:Person {name: $name}) RETURN p",
        params=FindPersonParams,
    )
)
```

### 3. Register a typed read query

Typed queries carry a declared result shape and can be executed via
`orthograph.execution`:

```python
from pydantic import BaseModel
from orthograph.queries import TypedCypherReadQueryModel

class PersonResult(BaseModel):
    name: str
    born: int | None = None

class GetPersonByName(TypedCypherReadQueryModel[FindPersonParams, PersonResult]):
    query_id = "get_person_by_name"
    cypher_template = "MATCH (p:Person {name: $name}) RETURN p.name AS name, p.born AS born"
    params_schema = FindPersonParams
    result_schema = PersonResult

catalogue.register_read(GetPersonByName())
```

### 4. Validate the catalogue against a definition

```python
from orthograph.queries import validate_catalogue

result = validate_catalogue(catalogue, definition)

if result.is_valid:
    print("All queries satisfy the contract.")
else:
    for issue in result.issues:
        print(issue.code, issue.message)
```

Queries without a `cypher_template` are reported as
`QUERY_UNVERIFIABLE` (INFO severity) and are never silently skipped.

---

## Load a catalogue from YAML

For larger projects, define queries in YAML and load them all at once:

```python
from orthograph.queries import load_catalogue

catalogue = load_catalogue("queries/filmography.yaml")
result = validate_catalogue(catalogue, definition)
```

---

## Validate against a live profile as well

To combine static catalogue validation with live-DB drift detection in a
single pass, use `validate_catalogue_against_profile`:

```python
from orthograph.queries import validate_catalogue_against_profile

# profile obtained separately from orthograph.profile.inspect_neo4j
result = validate_catalogue_against_profile(catalogue, profile, definition)
```

This function never opens a connection — pass a `GraphProfile` obtained
from `inspect_neo4j` (or another `inspect_*` verb).

---

## Introspect registered queries

```python
# Names of all registered queries
print(catalogue.names())

# Structured metadata for each
for desc in catalogue.describe():
    print(desc.query_id, desc.cypher_template)
```

---

## See also

- {py:class}`orthograph.queries.QueryCatalogue`
- {py:func}`orthograph.queries.validate_catalogue`
- {py:func}`orthograph.queries.validate_catalogue_against_profile`
- {py:func}`orthograph.queries.new_catalogue`
- {py:func}`orthograph.queries.load_catalogue`
- {py:func}`orthograph.queries.simple_query`
- {py:class}`orthograph.queries.TypedCypherReadQueryModel`
- [Tutorial: Query management and validation](../tutorials/index.md) — notebooks `03.01`–`03.05`
