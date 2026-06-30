# Validate in-memory data

**Goal:** check that a collection of nodes and relationships satisfies a
`GraphDefinition` before writing anything to a database.

---

## Steps

### 1. Build (or load) a definition

```python
from typing import Optional
from orthograph.definition import GraphDefinition, NodeModel, RelationshipModel

class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    born: Optional[int] = None

class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    year: int

class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    role: str

definition = GraphDefinition(
    name="Filmography",
    node_types=[Person, Movie],
    relationship_types=[ActedIn],
)
```

### 2. Prepare data as dicts or model instances

```python
nodes = [
    {"__label__": "Person", "name": "Alice", "born": 1985},
    {"__label__": "Movie",  "title": "Inception", "year": 2010},
]
relationships = [
    {
        "__label__": "ACTED_IN",
        "__source_uid__": "Alice",
        "__target_uid__": "Inception",
        "role": "Lead",
    }
]
```

### 3. Run `validate_data`

```python
from orthograph.definition import validate_data

result = validate_data(definition, nodes, relationships)
```

### 4. Inspect the result

```python
if result.is_valid:
    print("All records satisfy the contract.")
else:
    for issue in result.issues:
        print(issue.code, issue.message)
```

Each `issue` carries a typed `code` (e.g. `MISSING_REQUIRED_PROPERTY`,
`UNKNOWN_LABEL`) and a human-readable `message`. Iterate `.issues` to drive
structured error handling.

---

## Validate relationships without nodes

Pass `relationships=None` (the default) to check nodes only, or supply just
an empty `nodes=[]` list alongside relationships if your batch contains only
edges.

---

## Validate the contract itself first

If you author a `GraphDefinition` programmatically, validate its internal
consistency once before checking data:

```python
from orthograph.definition import validate_definition

contract_result = validate_definition(definition)
assert contract_result.is_valid, contract_result.issues
```

`validate_definition` checks for duplicate type names, undefined node
references in relationship endpoints, isolated nodes, and cardinality rule
consistency — issues that would produce misleading errors later if left
unchecked.

---

## See also

- {py:func}`orthograph.definition.validate_data` — full parameter reference
- {py:func}`orthograph.definition.validate_definition` — contract consistency check
- {py:class}`orthograph.definition.GraphDefinition`
- {py:class}`orthograph.definition.NodeModel`
- {py:class}`orthograph.definition.RelationshipModel`
- [Tutorial: Validating graph data](../tutorials/index.md) — worked example with cardinality and optionality
