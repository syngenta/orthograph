# ADR-015: The Declared/Observed Mirror

**Date:** 2026-06-12
**Status:** Implemented
**Category:** ubiquitous language / domain model / architecture

> Companion to ADR-013 (ubiquitous-language naming) and ADR-014 (relationship
> endpoint labels). Where ADR-013 reconciled *names within each layer*, this
> ADR reconciles *names across two layers* — the declared side and the
> observed side — and fixes the comparison architecture that bridges them.

> **Forward note (ADR-017, 2026-06-12).** This ADR established the
> declared/observed **mirror principle**; **ADR-017** turns that principle into
> a **package topology**: the declared side becomes `graph_definition/`, the
> observed side becomes `graph_profile/`, the comparison engine moves to its own
> `comparison/` package (with the misnamed `validate_profile` retired in favour
> of `compare`), and the shared result currency (`ValidationIssue` /
> `ValidationResult`) moves to a dedicated `diagnostics/` package. The source
> paths cited below (`profile/validation.py`, `profile/rules.py`, …) are the
> state *at the time of this ADR* and are superseded by ADR-017's topology — see
> the path-translation table in ADR-017. This ADR's domain reasoning stands
> unchanged; only the file locations move.

---

## Context

Orthograph holds two parallel descriptions of the same graph structure:

- **The declared side** — *what should be true.* The `GraphDataModel` and its
  `NodeModel` / `RelationshipModel` type definitions, property specs
  (`TypeInfo`), and cardinality constraints (`CardinalitySpec`). Authored by
  hand or generated from YAML / a database. Store-independent.
- **The observed side** — *what is measured.* The `GraphProfile` produced by
  inspection: `NodeTypeProfile`, `RelationshipTypeProfile`, `PropertyProfile`,
  `CardinalityStats`, `ConstraintInfo`. Empirical, dataset-specific.

`validate_profile(profile, graph_data_model)` (`profile/validation.py`) is the
comparison of the observed side against the declared side. The PRD already
names the declared side "the single declared truth" and the operation as
"database schema vs data model."

Two problems motivated this decision.

### Problem 1 — the two sides drift in vocabulary

The declared and observed faces of the *same concept* use different words,
with nothing forcing them to agree:

| Concept (one property) | Declared (`TypeInfo`) | Observed (`PropertyProfile`) |
|---|---|---|
| name | (dict key) | `name` |
| type | `python_type` (should be) | `observed_types` (actually were) |
| presence requirement | `is_required` (declared) | `is_mandatory` (observed — **fixed: now `is_required`**) |

`is_required` vs `is_mandatory` was the warning shot: the same idea wearing two
words, and it drifted with *zero* growth pressure. The observed side is
expected to grow faster than the declared side (distributions, percentiles,
histograms, distinct counts). Without a governing rule, that growth multiplies
the drift and obscures the mirror.

### Problem 2 — the comparison is a per-aspect switchboard

`validate_profile` dispatches to six bespoke `_check_*` functions
(`_check_node_labels`, `_check_rel_types`, `_check_node_properties`,
`_check_rel_properties`, `_check_rel_endpoints`, `_check_cardinality`). Each
has its own signature, traversal, and issue-construction. Adding a newly
*comparable* observed feature (e.g. "value must fall in a declared range")
means adding a seventh `_check_*` and wiring it in — a pipeline per aspect.
That does not scale with the expected growth on the observed side.

---

## Decision

### 1. The Declared/Observed Mirror is a first-class domain principle

> **Declared and observed are two faces of the same addressed structure.**
> Every comparable aspect of the graph has a *declared face* (a constraint:
> what should be true) and an *observed face* (a measurement: what is true),
> and both faces are reached by the **same address** in the structure.

The address vocabulary is shared and uniform:

| Aspect | Address | Declared face | Observed face |
|---|---|---|---|
| node label | `(label)` | exists in model | `NodeTypeProfile` |
| relationship type | `(rel_type)` | exists in model | `RelationshipTypeProfile` |
| property | `(label, property_name)` | `TypeInfo` | `PropertyProfile` |
| cardinality | `(label, rel_type)` | `CardinalitySpec` | `CardinalityStats` |
| distributions, percentiles, … | `(label, property_name)` | *(none yet)* | observed-only, future |

The mirror works because both sides agree on the address. Comparison is then a
**structural walk over a shared key space**, not bespoke matching code.

### 2. Vocabulary reconciliation across the two faces (soft enforcement)

Declared and observed faces of the same concept **must use parallel,
reconciled vocabulary**, so the mirror is visible by name. This applies to
every aspect, not just properties — labels, relationship types, cardinality,
and any future observed dimension.

Enforcement is **soft** (documentation + docstrings + glossary), not a runtime
mechanism. The rule:

> A new observed measurement that mirrors a declared constraint MUST (a) live
> at the same address vocabulary and (b) name its concept with the declared
> side's word. Each observed model carries a docstring pointing at its
> declared twin.

Known reconciliations applied during the refactor:

- `is_required` (declared) ↔ `is_mandatory` (observed) → **unified to `is_required`** (A1).
- `python_type` (declared) ↔ `observed_types` (observed) → parallel naming + cross-reference docstrings (A2).

### 3. The free-growth boundary (Case A vs Case B)

The mirror protects observed-side growth, with an explicit boundary:

- **Case A — observed-only enrichment (the common case).** A new observed
  feature with *no declared twin* (histogram, mean, distinct count) is carried,
  serialized, and displayed, but **does not participate in comparison**.
  Adding it requires **no change to the comparison** — the walk only engages
  aspects that have a declared constraint. This is the principle's core payoff
  and it is free.

- **Case B — a newly comparable feature.** When an observed feature gains a
  *declared twin* (e.g. a declared value range to check against observed
  min/max), it becomes a comparable aspect. It MUST be expressed as the uniform
  triple below — **never** as a new bespoke `_check_*` pipeline.

### 4. Comparison is uniform and injection-based

The comparison is redefined to take its three ingredients **by injection**, so
it composes instead of branching:

- inject a `GraphDataModel` instance (the declared side),
- inject a `GraphProfile` instance (the observed side),
- inject a set of **rules**.

A **rule** is the uniform triple:

> `(declared constraint, observed measurement, satisfaction test)` addressed by
> a key in the shared address space.
>
> **Amended by ADR-037 (2026-06-24, E50).** For **relationship types**, the
> shared address-space key is no longer the bare label but the identity triple
> `(source_label, label, target_label)`, encoded as a `RelTypeKey` string. Both
> sides re-key on it; an endpoint difference becomes a different address
> (`MISSING_*` / `UNEXPECTED_*`) rather than an in-type endpoint-mismatch
> finding. The mirror principle is unchanged — only the relationship address key.

Comparison becomes: *for each rule, locate the declared constraint and the
observed measurement at its address, apply the satisfaction test, emit a
`ValidationIssue` on failure.* Adding a comparable aspect means adding **one
rule**, not one pipeline.

A starter set of standard rules (replacing the six `_check_*` functions,
one rule per behaviour — see `profile/rules.py`, `standard_rules()`):

- **presence** — a declared-required property is observed present.
- **absence** — an observed property/label/type has a declared counterpart
  (no undeclared extras where the model forbids them).
- **extra presence** — observed labels / relationship types / properties that
  are not declared (surfaced as warnings).
- **mandatory match** — a declared `is_required` property has observed
  completeness of 100% (i.e. `PropertyProfile.is_required` is true); the inverse
  is flagged as `PROPERTY_INCOMPLETE`.
- **type match** — observed types conform to the declared type. *Note: type
  conformance is itself a statistic over observed values, so the observed side
  needs a dedicated, addressed place to hold it rather than computing it
  ad hoc inside the comparison.* The addressed place is
  `PropertyProfile.observed_type_counts`.

### 5. Hub naming — decided in ADR-016

This ADR originally retained `GraphDataModel` and deferred the hub name. That
naming question is now resolved in **ADR-016**: the declared hub is renamed
`GraphDataModel` → `GraphDefinition` (pairing with `GraphProfile` as
definition-vs-profile), `GraphSchema` is rejected, and the future
database-facing facade is acknowledged but left unnamed. See ADR-016 for the
rationale and the landscape diagram.

---

## Rationale

- **The mirror already exists implicitly.** `NodeTypeProfile.property_profiles`
  is `dict[str, PropertyProfile]` keyed by property name, exactly mirroring
  `get_property_specs() -> dict[str, TypeInfo]` keyed by property name. The
  observed `RelationshipTypeProfile` already uses `source_labels` /
  `target_labels` — the same `*_label` vocabulary ADR-014 chose for the
  declared endpoints — and `rel_type`. Making the mirror explicit names a
  pattern that is already enacted.
- **Stress-tested against histogram growth.** A value-distribution added to
  `PropertyProfile` is Case A: it has no declared twin, so it rides along with
  zero comparison change. The principle survives the growth case it was
  designed for.
- **Injection keeps comparison open for extension.** Rules are data the caller
  (or a future consuming library) supplies; the comparison engine does not
  grow a branch per feature.

---

## Consequences

### Positive

- The declared/observed relationship is named and teachable, not buried in
  comparison code.
- Observed-side growth (the fast-growing side) is free for the common case.
- New comparable aspects cost one rule, not one pipeline.
- A dedicated, addressed home for type-conformance statistics removes ad hoc
  type checking from the comparison body.

### Negative / risks

- **Refactor blast radius.** Reconciling vocabulary touches the observed models
  (`profile/models.py`), their consumers, serialization, and tests.
- **Comparison rewrite.** Replacing six `_check_*` functions with an
  injection-based rule walk is a behavioural refactor that must preserve every
  existing `ValidationIssue` code and severity (regression-tested).
- **Soft enforcement only.** The vocabulary rule is documentation-backed; it
  relies on review discipline, not a compiler. Accepted deliberately.

---

## Implementation note

This decision was carried out as a **stepwise rename + refactor** across
Phases A–E (vocabulary, type-conformance field, injection engine, free-growth
verification, close-out). The implementation is complete.

Key source files:

> **Superseded by ADR-017.** The paths in this table are as of ADR-015.
> Under ADR-017 they relocate: `profile/` → `graph_profile/`,
> `profile/validation.py` → `comparison/engine.py` (`validate_profile` →
> `compare`), `profile/rules.py` → `comparison/rules.py`. See ADR-017's
> path-translation table.

| Concern | File |
|---|---|
| Observed models + mirror docstrings | `src/orthograph/profile/models.py` |
| Rule abstraction + standard rule set + Case-B recipe | `src/orthograph/profile/rules.py` |
| Injection-based comparison engine | `src/orthograph/profile/validation.py` |
| Public API entry points (`rules=` param) | `src/orthograph/api/database.py`, `api/model.py` |
| Extension recipe tests (Case-A and Case-B) | `tests/profile/test_models.py`, `tests/profile/test_rules.py` |

The plan folder (`.opencode/plans/declared-observed-mirror/`) is now
disposable. This ADR is the durable record.
