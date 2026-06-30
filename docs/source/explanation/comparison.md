# How Comparison Works

**Comparison** is the process of reconciling two independently-produced
artefacts — a `GraphDefinition` (declared) and a `GraphProfile` (observed) —
and emitting a `ValidationResult` that lists every divergence, its severity,
and the precise address where it was found.

Orthograph provides three comparison functions:

| Function | Left | Right | Answers |
|---|---|---|---|
| `compare_profile_to_definition` | `GraphProfile` | `GraphDefinition` | Does the database match the contract? |
| `compare_profiles` | `GraphProfile` | `GraphProfile` | Did two databases drift apart? |
| `compare_definitions` | `GraphDefinition` | `GraphDefinition` | Did the contract change between versions? |

All three live in `orthograph.compare`. All three return the same
`ValidationResult` type from `orthograph.diagnostics`.

→ **Tutorials:**
  {doc}`../notebooks/05.02_profile_vs_definition`,
  {doc}`../notebooks/05.03_profile_vs_profile`,
  {doc}`../notebooks/05.04_definition_vs_definition`.

---

## The declared / observed mirror

The comparison engine is where the declared/observed mirror (ADR-015) is
realised in code. Because the two artefacts are produced independently, the
comparison is the *only* place where the declared contract meets the observed
reality. This is a deliberate design choice: neither side knows about the other
at construction time, which means:

- Profiling can run without the declared contract.
- The contract can be changed without invalidating existing profiles.
- Comparison can be replayed against archived profiles without a live database.

See [Architecture](architecture.md) for the three-layer stack and
[Profiling](profiling.md) for how a `GraphProfile` is produced.

---

## Algorithmic overview

> **Placeholder** — this section will be expanded with full algorithmic detail
> in the E61 documentation phase. The outline below describes the high-level
> procedure; the governing decisions are linked throughout.

### Step 1 — Address space construction

Both artefacts are wrapped in a `GraphView` adapter
(`src/orthograph/comparison/views.py`) that normalises them into a uniform
dictionary keyed by **comparison addresses**:

- Node addresses: the node label string (e.g. `"Person"`).
- Relationship addresses: the `RelTypeKey` string
  `"source_label:REL_LABEL:target_label"` (ADR-037).
- Property addresses: `"NodeLabel.prop_name"` or `"Source:REL:Target.prop_name"`.

The comparison engine walks the **union** of both address spaces. An address
present on only one side produces a presence finding
(`MISSING_*` or `UNEXPECTED_*`); an address present on both sides enters the
rule-checking phase.

### Step 2 — Presence pass

For every address in the union:

- If it exists on the left but not the right → `MISSING_*` issue (severity:
  ERROR for required types, lower for optional ones).
- If it exists on the right but not the left → `UNEXPECTED_*` issue.
- If it exists on both → proceed to step 3.

### Step 3 — Satisfaction rules (profile-to-definition path)

For each matched address, the engine applies the **satisfaction rules**
(`src/orthograph/comparison/rules.py`). Each rule inspects one declared aspect
against its observed counterpart and emits zero or more `ValidationIssue` objects:

- Property type conformance — does the observed DB type match the declared
  Python type?
- Cardinality bounds — do the observed degree statistics fall within the
  declared `CardinalitySpec`?
- Property presence / optionality — is a required property always present?

The rule set is injected into the engine as a list — adding a new check means
adding a function to `rules.py`, not editing the engine.

### Step 4 — Diff rules (profile-to-profile and definition-to-definition)

For the symmetric comparisons (`compare_profiles`, `compare_definitions`), the
engine applies **diff rules** (`src/orthograph/comparison/diff_rules.py`).
These rules compare corresponding aspects on both sides and emit a drift signal
when they differ (e.g. `PROPERTY_TYPE_CHANGED`, `CARDINALITY_CHANGED`,
`ENDPOINTS_CHANGED` for a directed-flag delta).

### Step 5 — Result assembly

All issues are collected into a `ValidationResult`:

```python
result.is_valid        # True if no ERROR-severity issues
result.issues          # list[ValidationIssue]
result.errors          # filtered to Severity.ERROR
result.warnings        # filtered to Severity.WARNING
```

Each `ValidationIssue` carries `code`, `message`, `severity`, `entity_type`,
and `address` — the precise location in the address space where the divergence
was found.

---

## Argument order note

`compare_profile_to_definition(profile, definition)` has the profile on the
**left** and the definition on the **right**. This is the correct resting state:
the profile is the *subject under test*, the definition is the *reference*. The
satisfaction rules read "left satisfies right?" — i.e. "does the observed value
satisfy the declared bound?". The argument names `left`/`right` in the engine
reflect this, not `observed`/`declared`, to avoid confusion on the symmetric
comparisons where neither side is "more declared" than the other.
See [ADR-044](https://github.com/syngenta/orthograph/blob/main/.agentic/decisions/044-comparison-dispatch-and-rule-symmetry.md).

---

## Implementation locations

| Concern | Module |
|---|---|
| Three comparison functions | `src/orthograph/comparison/engine.py` |
| `GraphView` adapters | `src/orthograph/comparison/views.py` |
| Satisfaction rules | `src/orthograph/comparison/rules.py` |
| Symmetric diff rules | `src/orthograph/comparison/diff_rules.py` |
| DB-type → Python-type mapping | `src/orthograph/comparison/type_mapping.py` |
| Public entry points | `src/orthograph/compare.py` |
| Result currency | `src/orthograph/diagnostics/result.py` |
