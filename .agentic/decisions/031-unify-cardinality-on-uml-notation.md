# ADR-031: Unify Cardinality Authoring on UML Notation

**Date:** 2026-06-19
**Status:** Accepted
**Category:** core
**Epic:** E42 (Unify Cardinality on UML Notation)
**Supersedes:** the cardinality-naming portions of ADR-001 (§ Optionality level 3,
§ Cardinality), the named-constant / `EXACTLY` portions of ADR-005
**Extends:** ADR-005 (cardinality semantics — the two-orthogonal-axes model stands)
**Relates:** ADR-029 (conditional cardinality), ADR-015 (declared/observed mirror),
ADR-017 (package topology)

---

## Context

Cardinality is the count bound a relationship side declares per node
(`__source_cardinality__` / `__target_cardinality__`). The runtime value object
has been a single frozen `CardinalitySpec(min, max)` since ADR-001, and ADR-005
fixed its semantics (cardinality counts instances *per node*; `__optional__`
controls whether the type appears at all — two orthogonal axes). Neither of those
facts changes here.

What this ADR addresses is that cardinality is **authored three different ways**
today, all collapsing to the same runtime `CardinalitySpec`:

| Form | Example | Underlying |
|------|---------|------------|
| Named constant | `Cardinality.ONE_OR_MORE` | `CardinalitySpec(min=1, max=None)` |
| Raw spec | `CardinalitySpec(min=2, max=5)` | itself |
| Factory | `EXACTLY(3)` | `CardinalitySpec(min=3, max=3)` |

The fragmentation is only at the **authoring surface**. It is compounded by two
divergent *renderings* of the same value — `CardinalitySpec.__repr__` emits `N`
for an unbounded max, while the visualizers (`visualization/text.py`,
`visualization/mermaid.py`) emit `*` — and by a third, *serialized* form: YAML
stores cardinality as `{min, max}` dicts. A reader therefore meets cardinality in
four notations (constant name, `min/max` kwargs, `N`-style repr, `*`-style
diagram, `{min,max}` YAML) for one concept.

ADR-029/E40 introduced two **internal-only** authoring helpers — `Cardinality.ZERO`
(`0..0`) and `EXACTLY` — for the conditional-cardinality work. E40.9 deliberately
did **not** publicly export `Cardinality` or `EXACTLY` (the empty
`graph_definition/__init__.py` and the absence of these names from the `api/`
surface confirm this), precisely to keep this consolidation cheap and
non-breaking at the public boundary.

UML class-diagram cardinality notation — `"1..*"`, `"0..1"`, `"2..5"` — is the
notation domain experts already read in the rendered diagrams and the one the PRD's
audience (graph/ER modellers) expects. It is a single string that round-trips
losslessly to and from `(min, max)`.

---

## Decision

Make `CardinalitySpec` the **one** cardinality value object, with UML notation as
its first-class, round-tripping (de)serialization, and **remove** the redundant
authoring forms. One notation — `"1..*"` — is used in class bodies, YAML,
`__repr__`, and visualization.

### 1. The value object is an enriched `CardinalitySpec` — no new class

The UML notation is a *behaviour of* `CardinalitySpec`, not a sibling type.
`CardinalitySpec` gains:

- `@classmethod parse(text: str) -> CardinalitySpec` — parses notation.
- `@property notation -> str` — emits notation.

The frozen `(min, max)` fields, `_validate_bounds`, `contains()`, and
`resolve_for_pair()` are **unchanged**. After construction, every value is still a
`CardinalitySpec`; every consumer (`validation.py`, `comparison/`,
`visualization/`, `graph_profile/`) keeps reading `.min` / `.max` / `.contains()`
/ `representative_spec()` exactly as before. The blast radius is wide (authoring
sites) but shallow (no behavioural change past construction).

### 2. The parse seam is a Pydantic `model_validator(mode="before")`

A single `mode="before"` validator on `CardinalitySpec` coerces a `str` input into
the field dict (via `parse`), and passes dicts and instances through untouched.
This one hook covers raw construction, YAML parsing, and `ConditionalCardinality`
rule/`default` values that flow through model validation. It must not shadow the
existing `mode="after"` `_validate_bounds`; semantic checks stay there.

### 3. Class-body authoring is coerced explicitly in `__init_subclass__`

`__source_cardinality__` / `__target_cardinality__` are `ClassVar`s, which Pydantic
does **not** run through field validation. A bare `__source_cardinality__ = "1..*"`
in a `RelationshipModel` subclass is therefore coerced by an explicit step in
`RelationshipModel.__init_subclass__` (a named `_coerce_cardinality` helper that
parses strings and leaves `CardinalitySpec` / `ConditionalCardinality` untouched).
`ConditionalCardinality` rule `spec`s and `default` are coerced the same way via
the `CardinalitySpec` `mode="before"` validator when authored as notation strings
in explicit `ConditionalRule` / `ConditionalCardinality` construction. *(The
`by_kind` convenience factory was removed in E43/ADR-032; authoring is explicit.)*

### 4. One notation everywhere — including YAML serialization

YAML **emits** notation strings (`source_cardinality: "1..*"`) and **reads** them.
The legacy `{min, max}` dict form is still **accepted on read** for backward
compatibility but is **no longer emitted**. The conditional-cardinality YAML
structure from E40.6 keeps its shape; only its per-bound leaves become notation.

### 5. `*` is the canonical unbounded symbol; `__repr__` is fixed

`CardinalitySpec.__repr__` becomes `f"CardinalitySpec({self.notation})"`, so an
unbounded max renders as `*` (previously `N`). The two duplicate visualization
formatters collapse into `CardinalitySpec.notation`. One symbol, one renderer.

### 6. Grammar is strict `min..max`

```
"<min>..<max>"   min = non-negative int;  max = non-negative int OR "*"
legal:   "0..0" "0..1" "1..1" "0..*" "1..*" "2..5" "3..3"
illegal: "1"  "*"  "..5"  "1.."  "*..5"  "1...5"  "5..2"  "-1..0"  "a..b"
```

**Round-trip invariant:** `CardinalitySpec.parse(spec.notation) == spec` for every
spec. `notation` is the exact inverse of `parse`. Syntactic failures raise a new
`CardinalityParseError`; semantic failures (`5..2`, negatives) keep coming from
`_validate_bounds`. No bare-`"1"` / bare-`"*"` shorthand in this epic (see Rejected
Alternatives).

### 7. Big-bang removal of `Cardinality.*` and `EXACTLY`

`class Cardinality` and `def EXACTLY` are **deleted** in this epic (not aliased,
not deprecated). They are not publicly importable, and no import of them remains
in `src/` or `tests/`. Field defaults become `CardinalitySpec(min=0, max=None)`
(the former `ZERO_OR_MORE`).

Because the value object is unchanged and the constants/factory were never public,
this is internal-only churn: the removal mechanically rewrites authoring literals
(`Cardinality.ONE_OR_MORE` → `"1..*"`, `EXACTLY(3)` → `"3..3"`, etc.).

---

## Rejected Alternatives

| Alternative | Why rejected |
|-------------|--------------|
| **Keep `Cardinality.*` / `EXACTLY` as aliases of the notation form** | Leaves three authoring surfaces alive — the exact fragmentation this ADR removes. They were never public (E40.9), so there is no backward-compat reason to retain them. A clean single surface beats an indefinite three-way alias. |
| **Introduce a new, separate value object for notation** | `CardinalitySpec` is *already* the single frozen value object with bounds validation, `contains()`, and `resolve_for_pair()`. Notation is a behaviour of that value, not a new type. A sibling type would double the value-object surface and force every consumer to learn which one it holds. |
| **Keep `{min, max}` dict YAML (do not emit notation)** | Two serialized notations for one concept; readers must mentally map `{min: 1, max: null}` to `1..*`. Emitting notation makes YAML match the diagrams and class bodies. Dict form stays *accepted on read* so existing config files keep loading — back-compat without perpetuating the form. |
| **Shorthand grammar (`"1"` ≡ `1..1`, `"*"` ≡ `0..*`)** | Ambiguous and easy to misread (`"*"` could mean `0..*` or `1..*`); a bare `"1"` hides whether the author meant exactly-one or at-least-one. Strict `min..max` is unambiguous and is the exact inverse of `notation`, preserving the round-trip invariant. Shorthand is deferrable and non-breaking to add later — explicitly out of scope here. |

---

## Consequences

- **One notation, end to end.** `"1..*"` is read and written identically in class
  bodies, YAML, `__repr__`, and Mermaid/text diagrams.
- **Runtime model unchanged.** After construction everything is a
  `CardinalitySpec`; no consumer of `.min`/`.max`/`.contains()`/`resolve_for_pair()`
  changes. The two-axes model of ADR-005 (`__optional__` vs cardinality) stands.
- **Conditional cardinality unaffected in substance.** ADR-029 resolution
  semantics do not change; only the leaf-bound authoring and serialization adopt
  notation.
- **YAML is backward-compatible on read, forward-only on write.** Legacy
  `{min, max}` files still load; new files emit notation.
- **Reversal of an E40 internal addition, by design.** The internal-only
  `Cardinality.ZERO` and `EXACTLY` introduced in E40 are removed; E40.9 not
  exporting them is what makes this a no-public-break change.

---

## Out of Scope

- **UML shorthand** (`"1"`, `"*"`) — deferrable, non-breaking to add later.
- Merging declared `CardinalitySpec` with observed `CardinalityStats` — the
  ADR-015 declared/observed boundary stays.
- Any change to `ConditionalCardinality` resolution semantics (ADR-029) — only its
  leaf-bound authoring/serialization touches notation.
- Removing the `{min, max}` YAML **read** path — it stays accepted-on-read for
  back-compat this phase.

---

## Cross-references

- ADR-001: core architecture and naming — superseded for the cardinality-naming
  portions (named constants; `CardinalitySpec(min, max)` as the custom form).
- ADR-005: cardinality semantics — the two-axes model stands; its named-constant /
  `EXACTLY` authoring portions are superseded.
- ADR-029: conditional cardinality — leaf bounds adopt notation; resolution
  unchanged.
- ADR-015: declared/observed mirror — boundary unchanged.
- ADR-017: package topology — cardinality stays in `graph_definition/`.
- `CardinalitySpec` (`parse`, `notation`, `mode="before"` seam, `__repr__`):
  `src/orthograph/graph_definition/models.py`
- `CardinalityParseError`: `src/orthograph/graph_definition/exceptions.py` (new, E42)
- YAML leaves: `src/orthograph/io/yaml.py`
- Visualization formatters: `src/orthograph/visualization/text.py`,
  `src/orthograph/visualization/mermaid.py`
- E42 epic: `.agentic/planning/active_epics/E42_unify_cardinality_uml_notation.md`
