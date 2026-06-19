# ADR-005: Cardinality Semantics — ZERO_OR_MORE Is a Valid Constraint

**Date:** 2026-04-14
**Status:** Accepted
**Category:** core

> **Superseded in part by [ADR-031](031-unify-cardinality-on-uml-notation.md) (2026-06-19).** The two-orthogonal-axes model (`__optional__` vs cardinality) below stands. The named-constant / `EXACTLY` authoring portions are superseded: cardinality is now authored as UML notation (`"0..*"`, `"1..*"`) and the `Cardinality.*` constants and `EXACTLY` are removed.

## Context

User feedback questioned whether `ZERO_OR_MORE` (0..*) is semantically valid,
arguing that "zero means the relationship doesn't exist" and suggesting it
should always be `ONE_OR_MORE`.

## Finding

The current semantics are correct. Cardinality constrains the **instance count
per node**, not the existence of the relationship type in the schema. These are
orthogonal axes:

- `__optional__` controls whether the relationship type must appear at all
- `CardinalitySpec(min, max)` controls how many instances each node may have

`ZERO_OR_MORE` (0..*) is standard UML/ER/OWL notation meaning "optional
participation, unbounded." It is the correct permissive default for a schema
framework that must handle partial data (query results, ETL fragments).

`ONE_OR_MORE` (1..*) means mandatory participation — every node must have at
least one instance. The two cardinalities model different business rules and
are not interchangeable.

## Design: Two Orthogonal Axes

| Axis | What it controls | Mechanism |
|---|---|---|
| **Entity-level optionality** | Whether the relationship *type* must appear at all in the data | `__optional__ = True/False` |
| **Cardinality** | How many instances each *individual node* may have | `CardinalitySpec(min, max)` |

**Use `ZERO_OR_MORE`** (the default) when validating partial query results,
optional relationships, or documenting what *can* exist without enforcing
participation.

**Use `ONE_OR_MORE`** when every node must participate (mandatory relationship),
validating canonical/complete data, or the business rule requires at least one
instance.

## Test Gap Identified and Closed

Prior to this work, `Cardinality.ONE_OR_MORE` was only structurally tested
(min/max values) — never exercised through `contains()` or `GraphValidator`.
`ZERO_OR_MORE.contains(0)` was also never asserted. No test exercised
`__target_cardinality__` violations. Seven new tests were added to close
these gaps across `test_types.py`, `test_relationship_model.py`, and
`test_validator.py`.

## Pre-commit mypy: `py.typed` Marker

The pre-commit mypy hook ran in an isolated venv without the local package
installed. Because `src/orthograph/py.typed` was missing, mypy treated all
orthograph exports as `Any`, causing ~49 `Class cannot subclass` false
positives on any commit touching test files. Adding `py.typed` and the local
package (`.`) to `additional_dependencies` resolved this.

## Actions

- Expanded `Cardinality` class and per-constant docstrings in `core/types.py`
- Documented `__source_cardinality__` / `__target_cardinality__` defaults
  and their relationship to `__optional__` in `relationship_model.py`
- Added explanatory section with side-by-side `ZERO_OR_MORE` vs `ONE_OR_MORE`
  examples in notebook 03
- Added 7 tests: `contains()` for `ZERO_OR_MORE`/`ONE_OR_MORE`, side-by-side
  validator comparison, target cardinality violation, default cardinality assertion
- Added `py.typed` marker and fixed pre-commit mypy configuration
