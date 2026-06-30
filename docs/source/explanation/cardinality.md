# Cardinality and Optionality

Cardinality and optionality are the two axes that together express **how many
relationships a node is allowed to have, and whether having any at all is
required**.

They are orthogonal — each is set independently — but they are often confused.
The tutorials work through both carefully:

- {doc}`../notebooks/01.03_what_is_cardinality` — introduces `CardinalitySpec`
  and the UML notation.
- {doc}`../notebooks/01.04_optionality_and_cardinality` — introduces
  `__optional__` and explains the difference between cardinality bounds and
  existence.

---

## Existence vs. optionality — the two-axes model

> **The core distinction:** cardinality says *how many*; optionality says
> *whether at all*.

A relationship type can be:

| `__optional__` | Cardinality | Meaning |
|---|---|---|
| `False` (default) | `"1..*"` | Every node of this type **must** have at least one relationship; and if it has any, there must be at least one. |
| `True` | `"1..*"` | The node **may** have no relationships of this type; but **if** it has any, it must have at least one. |
| `False` | `"0..*"` | Every node **must** appear on at least one edge, but the count is unconstrained. *(This is unusual — see below.)* |
| `True` | `"0..*"` | The node may have any count, including zero. This is the permissive default. |

The notional confusion arises because `"0..*"` (zero-or-more) and
`__optional__ = True` both permit zero relationships. They are not the same:

- `__optional__ = True` means *the node is allowed to have no relationships of
  this type at all*. The cardinality bound is checked **conditionally** — only
  when at least one relationship of this type exists.
- `"0..*"` means *when the type is present, the lower bound is zero*. If
  `__optional__ = False`, the validator still checks that *some* relationship
  of this type exists before applying the `0..*` bound.

In practice, most relationship types are either:
- `__optional__ = False`, cardinality `"1..1"` or `"1..*"` — required, bounded.
- `__optional__ = True`, cardinality `"0..*"` — truly optional, unconstrained.

The notebook {doc}`../notebooks/01.04_optionality_and_cardinality` works through
concrete examples of each combination, including the edge cases that trip people
up.

---

## The UML notation

Cardinality is authored as a **UML class-diagram multiplicity string**:
`"<min>..<max>"` where `max` is either a non-negative integer or `*`
(unbounded).

```python
from orthograph.definition import RelationshipModel

class WorksFor(RelationshipModel):
    __label__ = "WORKS_FOR"
    __source_label__ = "Person"
    __target_label__ = "Company"
    __source_cardinality__ = "1..1"   # a person works for exactly one company
    __target_cardinality__ = "1..*"   # a company has at least one employee
```

**Legal examples:**

| Notation | Meaning |
|---|---|
| `"0..1"` | Zero or one |
| `"1..1"` | Exactly one |
| `"1..*"` | One or more |
| `"0..*"` | Zero or more (unconstrained) |
| `"2..5"` | Between two and five |
| `"3..3"` | Exactly three |

**Grammar (strict):** both sides must be explicit; no shorthands like `"1"` or
`"*"` alone. `min` must be ≤ `max`. Negative values and non-integer bounds are
rejected.

The same notation is used in class bodies, YAML files, `__repr__` output, and
schema diagrams — one syntax end to end. See
[ADR-031](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/031-unify-cardinality-on-uml-notation.md)
for the round-trip invariant.

---

## `CardinalitySpec` — the runtime value object

At runtime every cardinality is a `CardinalitySpec(min, max)`. The notation
string is coerced automatically wherever a cardinality is declared:

```python
from orthograph.definition import CardinalitySpec

spec = CardinalitySpec.parse("1..*")
spec.min   # 1
spec.max   # None  (unbounded)
spec.notation   # "1..*"

CardinalitySpec.parse(spec.notation) == spec   # round-trip invariant
```

`CardinalitySpec` is a frozen Pydantic model. Its `.contains(n)` method tests
whether an observed count `n` satisfies the declared bound.

---

## Cardinality in YAML

In a YAML graph definition, cardinality is written as a notation string on the
relationship type:

```yaml
relationship_types:
  - label: WORKS_FOR
    source: Person
    target: Company
    source_cardinality: "1..1"
    target_cardinality: "1..*"
    optional: false
```

Legacy `{min: 1, max: null}` dict form is still accepted on read for backward
compatibility, but new files always emit notation strings.

---

## Implementation locations

| Concern | Module |
|---|---|
| `CardinalitySpec` (parse, notation, contains) | `src/orthograph/graph_definition/models.py` |
| `__optional__` and `__source/target_cardinality__` | `src/orthograph/graph_definition/models.py` (`RelationshipModel`) |
| Coercion in `__init_subclass__` | `src/orthograph/graph_definition/models.py` |
| YAML round-trip | `src/orthograph/io/yaml.py` |
| ADR-031 (notation grammar + round-trip) | `.agentic/decisions/031-unify-cardinality-on-uml-notation.md` |
| ADR-005 (two-axes semantics) | `.agentic/decisions/005-cardinality-semantics.md` |
