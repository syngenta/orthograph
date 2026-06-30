# Relationship Identity and the Endpoint Signature

A **relationship type** in Orthograph is not identified by its label string
alone. Its identity is the full ordered triple:

```
(source_label, relationship_label, target_label)
```

This triple is encoded in the `RelTypeKey` value object and serialised as
`"Source:REL:Target"`. Two relationship types that share a label but connect
different node types — `Person-KNOWS->Person` and `Company-KNOWS->Company` — are
**distinct types** with distinct profiles, distinct declared cardinalities, and
distinct comparison addresses.

→ **Tutorial:** {doc}`../notebooks/04.04_multi_shape_relationships` demonstrates
  declaring and working with multiple relationship shapes for the same label.

---

## Why endpoints are part of identity

Property graph databases — Neo4j, Memgraph — permit a single relationship label
to exist between many node-label pairs. A `KNOWS` relationship in Neo4j can
connect `Person↔Person`, `Company↔Company`, and `Person↔Company` in the same
database.

If identity were only the bare label, a profiler would **blend** all three
shapes into one `KNOWS` profile, averaging their counts, cardinality statistics,
and property distributions across genuinely different relationship semantics.
Drift detection would then run cardinality checks against blended statistics
that do not correspond to any real shape in the database.

Endpoint-aware identity (ADR-037) fixes this: each `(source, label, target)`
shape is measured independently, stored independently, and compared
independently.

---

## Declaring a relationship with its signature

Every `RelationshipModel` subclass carries three class variables that define
its identity:

```python
from orthograph.definition import RelationshipModel

class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"   # tail node label
    __target_label__ = "Movie"    # head node label
    role: str
```

These three fields together constitute the declared signature. Orthograph
rejects two relationship types with the **same triple** (a true duplicate)
at `GraphDefinition` construction time. Two types with the **same label** but
different endpoints are legal and distinct:

```python
class ActedInFilm(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Director"
    __target_label__ = "Film"
    credit: str
```

`ActedIn` and `ActedInFilm` coexist in the same `GraphDefinition`. In YAML,
relationship types are a **list** (not a mapping keyed by label) because a
YAML mapping cannot hold two identical keys:

```yaml
relationship_types:
  - label: ACTED_IN
    source: Person
    target: Movie
    fields:
      role: str
  - label: ACTED_IN
    source: Director
    target: Film
    fields:
      credit: str
```

---

## `RelTypeKey` — the canonical identity encoding

`RelTypeKey` is a frozen Pydantic model that encodes the triple and provides
a deterministic string representation:

```python
key = RelTypeKey(source_label="Person", label="KNOWS", target_label="Person")
str(key)  # "Person:KNOWS:Person"
```

The `:` delimiter is safe because Cypher identifiers are validated against
`^[A-Za-z_][A-Za-z0-9_]*$` — a colon can never appear inside a label.
`RelTypeKey.parse("Person:KNOWS:Person")` recovers the parts.

Both the declared side and the observed side key their relationship dictionaries
on `str(RelTypeKey)`. The comparison engine walks the union of both key sets,
so a declared `Person-KNOWS->Person` and an observed `Person-KNOWS->Company` are
two different addresses, producing `MISSING_RELATIONSHIP` and
`UNEXPECTED_RELATIONSHIP` respectively — not a single "endpoint mismatch" finding.

---

## Directionality

`__directed__` is a class variable on `RelationshipModel` that declares whether
the relationship is directed (default: `True`). Direction is **not** part of
identity — a directed and an undirected relationship of the same triple cannot
coexist in the same definition. Direction is compared as an attribute delta
(`ENDPOINTS_CHANGED` with a `directed-flag` sub-code) in definition-to-definition
and profile-to-profile comparisons.

---

## Implementation locations

| Concern | Module |
|---|---|
| `RelTypeKey` | `src/orthograph/graph_definition/identity.py` |
| Declared side — `GraphDefinition._rel_type_map` | `src/orthograph/graph_definition/graph_definition.py` |
| Observed side — `RelationshipTypeProfile` | `src/orthograph/graph_profile/models.py` |
| Comparison address space | `src/orthograph/comparison/views.py` |
| ADR-037 (full rationale) | `.agentic/decisions/037-relationship-identity-includes-endpoints.md` |
