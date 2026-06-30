# Compare two definitions (version drift)

**Goal:** diff two `GraphDefinition` objects — for example, a released
version and a candidate — to surface structural divergence before deployment.

---

## Steps

### 1. Load or build both definitions

The definitions can come from YAML files, code, or a mix of both:

```python
from orthograph.definition import load_from_file

v1 = load_from_file("schemas/filmography_v1.yaml")
v2 = load_from_file("schemas/filmography_v2.yaml")
```

Or build them in-place for a one-off comparison:

```python
from orthograph.definition import GraphDefinition, NodeModel

class PersonV1(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str

class PersonV2(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    email: str          # new required property

v1 = GraphDefinition(name="Filmography v1", node_types=[PersonV1])
v2 = GraphDefinition(name="Filmography v2", node_types=[PersonV2])
```

### 2. Run `definitions`

```python
from orthograph.compare import definitions

result = definitions(v1, v2)
```

The comparison is **symmetric**: it reports addresses present in only one
side and properties that differ between them.

### 3. Inspect the result

```python
if result.is_valid:
    print("Definitions are structurally equivalent.")
else:
    for issue in result.issues:
        print(issue.code, issue.message)
```

Issues at INFO severity indicate one-sided addresses (additions or
removals); higher-severity issues indicate incompatible changes.

---

## Compare two observed profiles instead

To diff two live-database snapshots (for example, staging vs. production):

```python
from orthograph.compare import profiles

result = profiles(staging_profile, production_profile)
```

Both `definitions` and `profiles` are symmetric diffs — the order of
arguments does not change the set of issues, only their `left`/`right`
attribution.

---

## Use a custom rule set

All three comparison verbs accept a `rules=` argument to override the
default rule set:

```python
from orthograph.compare import definitions, Rule

result = definitions(v1, v2, rules=[Rule.MISSING_NODE_TYPE])
```

Pass `rules=None` (the default) to use the full built-in rule set.

---

## See also

- {py:func}`orthograph.compare.definitions`
- {py:func}`orthograph.compare.profiles`
- {py:func}`orthograph.compare.profile_to_definition`
- {py:class}`orthograph.compare.Rule`
- {py:func}`orthograph.definition.load_from_file`
- [Profile a live Neo4j database and detect drift](detect-drift.md)
- [Tutorial: Definition vs. definition comparison](../tutorials/index.md) — notebook `05.04`
