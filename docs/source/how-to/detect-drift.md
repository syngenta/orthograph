# Profile a live Neo4j database and detect drift

**Goal:** inspect a running Neo4j database into a vendor-free
`GraphProfile`, then compare it against a declared `GraphDefinition` to
surface structural drift.

---

## Prerequisites

Install the `neo4j` extra:

```bash
pip install "orthograph[neo4j]"
```

---

## Steps

### 1. Open a driver (caller-owned)

Orthograph never stores a connection. Create the driver, pass it to
`inspect_neo4j`, then close it as you normally would.

```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
```

### 2. Inspect the database

```python
from orthograph.profile import inspect_neo4j

profile = inspect_neo4j(driver)
```

`inspect_neo4j` auto-detects the best available strategy
(APOC → SCHEMA → CYPHER) and returns a `GraphProfile` containing node
type counts, relationship type counts, property presence statistics, and
constraint information.

### 3. Compare the profile against a definition

```python
from orthograph.compare import profile_to_definition

result = profile_to_definition(profile, definition)

if result.is_valid:
    print("Live database matches the contract.")
else:
    for issue in result.issues:
        print(issue.code, issue.message)
```

### 4. Close the driver

```python
driver.close()
```

---

## Force a specific inspection strategy

To skip APOC/schema probes and use pure-Cypher queries (useful when APOC
is unavailable or restricted):

```python
from orthograph.profile import inspect_neo4j, Neo4jInspectionStrategy

profile = inspect_neo4j(driver, strategy=Neo4jInspectionStrategy.CYPHER)
```

---

## Inspect a specific database

For multi-database Neo4j deployments, pass the database name:

```python
profile = inspect_neo4j(driver, database="production")
```

---

## Include per-property value counts

Pass `value_counts_top_n` to run an opt-in property value scan. This
populates `observed_type_counts` and a bounded value distribution
histogram on each `PropertyProfile`.

```python
profile = inspect_neo4j(driver, value_counts_top_n=50)
```

Use `value_counts_top_n=None` (the default) to skip the scan.

---

## Detect conditional cardinality drift

Supply the definition so that conditional relationship types receive
per-discriminator partitioned cardinality breakdowns, enabling more
precise drift detection:

```python
profile = inspect_neo4j(driver, graph_definition=definition)
result  = profile_to_definition(profile, definition)
```

---

## See also

- {py:func}`orthograph.profile.inspect_neo4j` — full parameter reference
- {py:class}`orthograph.profile.GraphProfile`
- {py:class}`orthograph.profile.Neo4jInspectionStrategy`
- {py:func}`orthograph.compare.profile_to_definition`
- [Tutorial: Profiling and comparison](../tutorials/index.md) — notebooks `05.01`–`05.06`
