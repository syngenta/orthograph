# ADR-001: Relationship Endpoint Labels

**Status:** Accepted
**Date:** 2026-06-11

> **Forward note (ADR-037, 2026-06-24).** This ADR made endpoint labels plain
> string **attributes** of a label-identified relationship type. **ADR-037**
> supersedes that *identity implication*: a relationship type is now identified
> by the triple `(source_label, label, target_label)`, so endpoints are part of
> identity, not merely attributes. Endpoints-as-data here still holds; what
> changes is what *identifies* a type. See E50.

---

## Context

`RelationshipModel` subclasses originally declared their endpoints as Python class
references:

```python
class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_type__: ClassVar[type[NodeModel]] = Person   # class reference
    __target_type__: ClassVar[type[NodeModel]] = Movie   # class reference
```

This meant:

- Both endpoint node classes had to be defined **before** the relationship class in
  Python source order (otherwise a `NameError` was raised at class-definition time).
- Every site that needed the endpoint label had to write `rt.__source_type__.__label__`
  — a two-step dereference through the class object to reach the string.
- The YAML loader (`io/yaml.py`) resolved the string labels from YAML
  (`source:` / `target:` keys) to node classes via a manually maintained
  `node_classes` dict, and stored those class objects on the dynamically-created
  subclass. This required nodes to be loaded before relationships in the YAML
  processing order.

---

## Decision

Rename `__source_type__` → `__source_label__` and `__target_type__` → `__target_label__`.
Both attributes now hold **plain strings** (the string label matching the corresponding
`NodeModel.__label__`), not Python class references.

Endpoint resolution to Python classes happens at `GraphDataModel.__init__` time, through
the existing `_node_type_map: dict[str, type[NodeModel]]` that the model already builds.

```python
class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__: ClassVar[str] = "Person"   # string label
    __target_label__: ClassVar[str] = "Movie"    # string label
```

The `__init_subclass__` guard in `RelationshipModel` now checks that both attributes are
**defined** (using `_check_classvar`), matching the existing `__label__` check. Runtime
type validation (string vs. class) is no longer needed because there is no class to pass
— the string requirement is self-evident.

---

## Rationale

### 1. 12 of 13 endpoint-read sites already operate through an assembled `GraphDataModel`

A survey of all non-test source code showed 13 sites that read endpoint attributes.
12 of those sites already hold a `GraphDataModel` instance and thus have access to
`_node_type_map`. The one exception (`CypherGenerator.match_relationship`) received a
`rel_type` class directly; it now resolves endpoint labels through `self.graph_data_model`
in the same way as `_rel_query`.

The class form provided no additional safety guarantee at import time that the string
form does not also provide at model-assembly time: `GraphDataModel._check_undefined_node_refs`
already validates that both endpoint labels exist in the model for every registered
relationship type, raising `GraphValidationError` on failure.

### 2. Order-independence

With string labels, a `RelationshipModel` subclass can be defined in any order relative
to its endpoint `NodeModel` subclasses — before, after, or in a separate module.
No `NameError` can arise at class-definition time from a forward reference. The YAML
loader benefits most: it no longer needs to process node types before relationship types.

### 3. Symmetry with YAML serialization

The YAML format for a relationship type has always used strings for endpoints:

```yaml
relationship_types:
  ACTED_IN:
    source: Person
    target: Movie
```

The old Python API forced a detour through class objects. The new API aligns the
in-memory representation with the serialization format: both use strings.

### 4. Naming consistency — all string discriminators carry the word `label`

This library uses `__label__` for both node and relationship discriminators as a single
unified concept. The renamed attributes `__source_label__` and `__target_label__` are
consistent with this convention: all dunder attributes that hold string discriminators
now carry the word `label`.

---

## Tradeoffs Accepted

### Loss of IDE jump-to-definition and import-time `NameError`

With class references, IDEs could navigate directly from `__source_type__ = Person` to
the `Person` class definition. With string labels, this navigation is no longer available
at the attribute assignment site.

**Mitigation:** `GraphDataModel._check_undefined_node_refs` raises `GraphValidationError`
at model-assembly time (i.e., at the point where `GraphDataModel(...)` is called) if any
endpoint label is not registered. This occurs early in application startup — much closer
to the point of failure than import time — and the error message names both the
relationship label and the undefined endpoint label.

### `match_relationship` now requires endpoint labels to be registered in the model

Previously, `CypherGenerator.match_relationship(rel_type)` resolved endpoint labels
directly from `rel_type.__source_type__.__label__` and `rel_type.__target_type__.__label__`,
with no requirement that the type be registered in the generator's model. After this
change, the method reads `rel_type.__source_label__` and `rel_type.__target_label__` as
strings, and those strings are validated against the model by the downstream
`_assert_valid` call (which invokes `validate_cypher`). Passing a relationship type whose
endpoint labels are not registered in the model will now raise `CypherModelValidationError`.

This is treated as a **correctness improvement**, not a regression: a Cypher query that
references node labels unknown to the model was already invalid; the old code would have
silently generated a query that failed model validation at the `_assert_valid` step anyway.

### Asymmetry with Neo4j terminology — deliberately retained

Neo4j calls the relationship discriminator a "relationship type" (`rel.type`). This
library uses `__label__` for both node and relationship discriminators. Introducing
`__type__` for relationships would add a second vocabulary word for the same concept
(a string name that identifies an entity type) and would create a confusing collision
with the now-renamed `__source_label__`/`__target_label__` (which are also "types" in
the Python sense). The asymmetry with Neo4j is accepted and documented here; the
library's internal consistency is given priority.

---

## Historical Attribute Names

For the record, the attributes renamed by this decision were:

| Old name | New name | Old type | New type |
|---|---|---|---|
| `RelationshipModel.__source_type__` | `RelationshipModel.__source_label__` | `ClassVar[type[NodeModel]]` | `ClassVar[str]` |
| `RelationshipModel.__target_type__` | `RelationshipModel.__target_label__` | `ClassVar[type[NodeModel]]` | `ClassVar[str]` |
