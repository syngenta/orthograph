# Quick Reference: CypherQuery Serialization

**TL;DR:** `CypherQuery` instances serialize to/from YAML via a JSON-Schema intermediary. Supports scalar types only (int, str, float, bool). All 37 tests pass. Production-ready.

---

## Python → YAML

```python
from pydantic import BaseModel
from orthograph.cypher.query import CypherQuery
from orthograph.cypher.bindings import NoParams, NoIdentifiers

class FindMovieParams(BaseModel):
    movie_id: str
    limit: int = 10  # Optional with default

q = CypherQuery(
    name="find_movie",
    cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m LIMIT $limit",
    Params=FindMovieParams,
    Identifiers=NoIdentifiers,
    description="Find a movie by ID"
)

# Serialize to dict
d = q.model_dump(by_alias=True, exclude_none=True)
# → {
#     "query_name": "find_movie",
#     "cypher_template": "...",
#     "description": "Find a movie by ID",
#     "params_schema": {
#       "title": "FindMovieParams",
#       "type": "object",
#       "properties": {
#         "movie_id": {"type": "string"},
#         "limit": {"type": "integer", "default": 10}
#       },
#       "required": ["movie_id"]
#     }
#   }

# Write to YAML file
import yaml
with open("queries.yaml", "w") as f:
    yaml.dump([d], f)
```

---

## YAML → Python

```yaml
# queries.yaml
- name: find_movie
  cypher_template: "MATCH (m:Movie {movie_id: $movie_id}) RETURN m LIMIT $limit"
  description: "Find a movie by ID"
  params_schema:
    title: FindMovieParams
    type: object
    properties:
      movie_id: { type: string }
      limit: { type: integer, default: 10 }
    required: [movie_id]
```

```python
from orthograph.io.query_catalogue_yaml import load_query_catalogue_file

queries = load_query_catalogue_file("queries.yaml")
q = queries[0]

assert q.name == "find_movie"
assert q.Params.model_fields["movie_id"].is_required()       # True
assert q.Params.model_fields["limit"].default == 10          # True
```

---

## Supported Field Types

| YAML | Python | Example |
|---|---|---|
| `type: integer` | `int` | `released: 2024` |
| `type: string` | `str` | `title: "Inception"` |
| `type: number` | `float` | `rating: 8.8` |
| `type: boolean` | `bool` | `is_active: true` |

---

## Zero-Parameter Queries

```python
# Python
q = CypherQuery(
    name="count_movies",
    cypher_template="MATCH (m:Movie) RETURN count(m) AS n",
    Params=NoParams,           # ← Empty params
    Identifiers=NoIdentifiers,
)

# YAML (both are equivalent)
# Option 1: Omit params_schema
- name: count_movies
  cypher_template: "MATCH (m:Movie) RETURN count(m) AS n"

# Option 2: Empty params_schema
- name: count_movies
  cypher_template: "MATCH (m:Movie) RETURN count(m) AS n"
  params_schema:
    type: object
    properties: {}
```

---

## Identifier Splicing (Not Parameters)

```python
# For queries that use <<label>> identifier slots (not $params)
class LabelIds(BaseModel):
    label: str

q = CypherQuery(
    name="nodes_by_label",
    cypher_template="MATCH (n:<<label>>) RETURN n",
    Params=NoParams,
    Identifiers=LabelIds,    # ← Identifier model
)

# Build with identifier values
query_data = q.build(identifiers=LabelIds(label="Movie"))
# → Cypher becomes: "MATCH (n:Movie) RETURN n"
```

---

## Errors

### YAML Loading Errors

```python
from orthograph.cypher.exceptions import CypherCatalogueLoadError

try:
    queries = load_query_catalogue_string(yaml_content)
except CypherCatalogueLoadError as e:
    # YAML parse error, missing required field, non-list top-level, etc.
    print(f"Failed to load: {e}")
```

### Schema Validation Errors

```python
from orthograph.cypher.exceptions import CypherQueryDefinitionError

# Occurs when a field uses unsupported construct (array, object, enum, $ref, etc.)
# E.g. params_schema with { "type": "array" } will raise immediately on load
```

### Unsupported Constructs

| Construct | Error | Workaround |
|---|---|---|
| Nested object | `"field uses unsupported construct 'object'"` | Use flat fields |
| Array | `"field uses unsupported construct 'array'"` | Use scalar or typed path |
| Enum | `"field uses unsupported construct 'enum'"` | Use typed path with custom validation |
| `$ref` | `"field uses unsupported construct '$ref'"` | Use inline schema |
| Unknown type | `"field uses unsupported type 'datetime'"` | Use typed path |

---

## Round-Trip Guarantee

✅ **Perfect fidelity:** YAML → Python → YAML produces identical schema.

```python
# Load from YAML
q1 = load_query_catalogue_string(yaml_content)[0]

# Dump back to dict
d = q1.model_dump(by_alias=True, exclude_none=True)

# Write to new YAML
yaml.dump([d], new_file)

# Load new YAML
q2 = load_query_catalogue_string(new_file)[0]

# Queries are functionally identical
assert q1.name == q2.name
assert q1.cypher_template == q2.cypher_template
assert q1.Params.model_fields.keys() == q2.Params.model_fields.keys()
```

---

## Required vs Optional

```python
class Params(BaseModel):
    released: int              # Required (no default)
    limit: int = 10           # Optional (default = 10)

# YAML
params_schema:
  properties:
    released: { type: integer }
    limit: { type: integer, default: 10 }
  required: [released]       # ← Only released is required

# On load, this is reconstructed perfectly
q = load_query_catalogue_string(yaml)[0]
assert q.Params.model_fields["released"].is_required()      # True
assert not q.Params.model_fields["limit"].is_required()     # True (optional)
assert q.Params.model_fields["limit"].default == 10         # True (default preserved)
```

---

## Build & Execute

```python
# Once loaded/created, build query data
query_data = q.build(movie_id="M-001", limit=5)
# → CypherQueryData(
#     cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m LIMIT $limit",
#     params={"movie_id": "M-001", "limit": 5}
#   )

# Pass directly to driver
result = await session.run(query_data.cypher, query_data.params)
```

---

## Integration with Validation

```python
# Validate against graph definition (static, no DB)
result = q.validate_query(my_graph_definition)
if result.is_valid:
    print("Query is valid")
else:
    for issue in result.issues:
        print(f"{issue.code}: {issue.message}")

# Or syntax-only check (no domain validation)
result = q.validate_query(None)
```

---

## File Locations (Orthograph Codebase)

| File | Purpose |
|---|---|
| `src/orthograph/cypher/query.py` | `CypherQuery` class |
| `src/orthograph/cypher/schema_codec.py` | JSON-Schema round-trip helpers |
| `src/orthograph/io/query_catalogue_yaml.py` | YAML loading |
| `src/orthograph/cypher/bindings.py` | `NoParams`, `NoIdentifiers` sentinels |
| `tests/cypher/test_schema_codec.py` | 14 codec tests |
| `tests/io/test_query_catalogue_yaml.py` | 21 YAML tests |
| `tests/cypher/test_query.py` | CypherQuery tests (includes serialization) |

---

## For More Details

See: `.agentic/reviews/cypher_query_serialization_review.md` (full architectural review)
