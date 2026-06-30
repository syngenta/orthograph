# Orthograph

**Graph data governance for Python: one declared contract for your property graph, continuously checked against your data, your queries, and your live database.**

Orthograph is a **contract and governance layer for property graph applications — not another graph ORM.** Property graphs are schema-flexible by design, so the *intended* model — which labels exist, which properties are required, what cardinalities hold — is usually never written down anywhere the application can read. Orthograph gives that intent a home: declare the contract once in Python or YAML, then validate data against it, govern a typed Cypher query catalogue, and detect drift as the live database evolves. It sits *above* your database, driver, and any ORM, and never owns a connection.

```bash
pip install orthograph
```

With Orthograph you can:

1. **Define the contract** once — node types, relationship types, properties, and cardinalities — in Python or YAML.
2. **Validate in-memory data** against the contract before it touches a database.
3. **Govern a typed Cypher query catalogue** — parameters, outputs, language correctness, and domain match, all without executing the queries.
4. **Detect drift** between the contract and a whole query set, or a live database, as either evolves.

---

## Quick start

Define the contract:

```python
from typing import Optional

from orthograph.definition import (
    GraphDefinition,
    NodeModel,
    RelationshipModel,
    validate_data,
)

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

Validate in-memory data against the contract before writing to the database:

```python
nodes = [
    {"__label__": "Person", "name": "Alice", "born": 1985},
    {"__label__": "Movie", "title": "Inception", "year": 2010},
]
relationships = [
    {"__label__": "ACTED_IN", "__source_uid__": "Alice",
     "__target_uid__": "Inception", "role": "Lead"},
]

result = validate_data(definition, nodes, relationships)
print(result.is_valid)                    # True / False
for issue in result.issues:
    print(issue.code, issue.message)      # structured, typed error codes
```

Govern a typed Cypher query — declared parameters, validated against the contract
without executing it:

```python
from pydantic import BaseModel

from orthograph.queries import new_catalogue, simple_query, validate_catalogue

class FindPersonParams(BaseModel):
    name: str

catalogue = new_catalogue()
catalogue.register_cypher_query(
    simple_query(
        name="find_person_by_name",
        cypher_template="MATCH (p:Person {name: $name}) RETURN p",
        params=FindPersonParams,
    )
)

# Drift detection: is the whole query set still consistent with the contract?
drift = validate_catalogue(catalogue, definition)
print(drift.is_valid)
```

Detect drift against a live database (requires the `neo4j` extra):

```python
from neo4j import GraphDatabase

from orthograph.compare import profile_to_definition
from orthograph.profile import inspect_neo4j

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
profile = inspect_neo4j(driver)
result = profile_to_definition(profile, definition)

print(result.is_valid)
for issue in result.issues:
    print(issue.code, issue.message)
```

---

## What Orthograph does

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Define the contract
Declare node types, relationship types, properties, and cardinalities once — in Python or YAML — as the single source of truth.
[→ Tutorials](tutorials/index.md)
:::

:::{grid-item-card} Validate data
Validate in-memory graph data against the contract before it touches a database. Get a structured result with typed error codes.
[→ How-To](how-to/index.md)
:::

:::{grid-item-card} Govern queries
Register typed Cypher queries. Validate parameter and result shapes, language correctness, and domain match against the contract — without executing them.
[→ Reference](reference/index.md)
:::

:::{grid-item-card} Detect drift
Compare a whole query set, or a live database profile, against the contract — so schema evolution never silently desynchronises them from your declared truth.
[→ How-To](how-to/index.md)
:::

::::

> **Query governance** and **drift detection** are distinct concerns. Governance keeps *individual queries* honest against the contract at registration time; drift detection answers whether *whole sets* — the query catalogue, the live database — have diverged from the contract over time.

---

## Where to start

::::{grid} 1 1 3 3
:gutter: 2

:::{grid-item-card} User
Learn by doing. Work through the tutorials to go from zero to a validated graph definition.
[→ Tutorials](tutorials/index.md)
:::

:::{grid-item-card} Developer
Use Orthograph as a library dependency. Start with How-To guides and the API reference.
[→ How-To](how-to/index.md) · [→ Reference](reference/index.md)
:::

:::{grid-item-card} Contributor
Understand the design before modifying code. The Explanation section maps the architecture; `CONTRIBUTING.md` covers setup and the test matrix.
[→ Architecture](explanation/architecture.md) · [→ Explanation](explanation/index.md) · [→ Contributing](https://github.com/syngenta/orthograph/blob/main/CONTRIBUTING.md)
:::

::::

```{toctree}
:maxdepth: 1
:hidden:

installation
tutorials/index
how-to/index
reference/index
explanation/index
```
