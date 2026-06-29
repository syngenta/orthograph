# ADR-044: Comparison Dispatch & Rule Symmetry — No-Change Verdicts

> **Status:** Accepted
> **Date:** 2026-06-29
> **Relates to:** ADR-015 (declared/observed mirror), ADR-042 (internal logic
>   distillation boundary), E56 W2 deferred Note (origin of both items),
>   E56.5 (named `RuleContext.extra` keys — the prerequisite this ADR reads against)

---

## Context

Two design questions were deferred from the E56 behaviour-preserving distillation
because they change *how rules are selected or parameterised* — which is a
behaviour/design risk against a correct, test-locked engine. E56 recorded them as
explicitly out of scope so they would be tracked rather than buried. This ADR is
the promised decision record.

The engine is **correct**. The suite is **green**. These are readability/
maintainability questions, not bugs. The decision criteria are:

1. Does the change reduce newcomer tax without touching behaviour?
2. Does it delete net code, or add indirection?
3. Does it risk do-and-undo against what E56 just produced?

---

## Item A — Satisfaction-path `left`/`right` argument inversion

### Current shape

`compare_profile_to_definition(profile, definition)` is the public function.
Internally it calls `_compare_views(DefinitionView(definition), ProfileView(profile), …)`:
the arguments are *reversed* so that inside the walker `context.left` always holds
the declared (definition) side and `context.right` always holds the observed
(profile) side. This is documented in the `compare_profile_to_definition`
docstring. Every satisfaction rule in `rules.py` relies on the convention.

The two symmetric diff functions (`compare_profiles`, `compare_definitions`) pass
their operands in natural order — no inversion.

### The proposed change and why it was rejected

The obvious fix is to add semantic `declared`/`observed` fields to `RuleContext`
so rules read `context.declared` / `context.observed` instead of positional
`context.left` / `context.right`. This would make the satisfaction path
self-explanatory without a docstring note.

**Rejected.** `RuleContext` is shared across *both* rule families. The diff rules
(`diff_rules.py`) treat `left` and `right` as **neutral positional** operands —
they emit `*_ONLY_IN_LEFT` / `*_ONLY_IN_RIGHT` issues and `left=… right=…`
message context bound to the caller's argument order. For the diff path there is
no declared/observed axis: a profile ↔ profile diff has two equally-observed
operands; a definition ↔ definition diff has two equally-declared operands. Adding
`declared`/`observed` fields to `RuleContext` would either:

- bloat the shared dataclass with fields that are semantically void for every diff
  rule (two-thirds of all rule evaluations), or
- force the diff rules to adopt declared/observed vocabulary they correctly reject.

The alternative — re-keying all 11 satisfaction rules so they read `context.left`
as observed and `context.right` as declared (matching the public signature order) —
would invert every rule's reading convention to remove one call-site argument swap.
That is a do-and-undo move against E56's contract-naming work: net zero benefit,
non-trivial blast radius, and a new hidden convention rather than a removed one.

### Verdict: no change

The inversion is the correct resting state. The call-site reversal in
`compare_profile_to_definition` is the one place the convention must be stated;
the rule implementations are correct as written. The docstring in
`compare_profile_to_definition` already carries a clear "Implementation note"
explaining the inversion and why it exists — that is the appropriate location for
this explanation, not the `RuleContext` data model.

The *optional* micro-improvement considered was naming locals `declared = DefinitionView(…)`
/ `observed = ProfileView(…)` at the `_compare_views` call site to make the
intent readable at a glance. This was not actioned: the existing docstring already
names both roles, and the local-rename has zero information value over it. It would
be dead vocabulary since nothing else in the function refers to those locals.

### E58.1 disposition

Closed as **not needed**. The recorded verdict is: the inversion is intentional,
correct, and fully documented at the single call site where it is established.

---

## Item B — `rules.py` ↔ `diff_rules.py` type/operand-kind symmetry

### The apparent symmetry

Both files contain type-comparison logic and operand dispatch. On the surface:

- `rules.py::PropertyTypeMismatchRule` and
  `diff_rules.py::PropertyTypeChangedRule` both deal with property types.
- `diff_rules.py::_rel_operand_kind` dispatches on the runtime type of the
  relationship operand; `rules.py::CardinalityViolationRule` also inspects the
  declared operand type.

The E56 W2 Note described this as "mirrored-but-separate type-mismatch /
operand-kind logic" and asked whether there was a shared core to hoist.

### The prerequisite that now exists

E56.5 named the `RuleContext.extra` contract (the `ADDRESS_TYPE` / `ADDR_NODE_LABEL`
/ `ADDR_REL_TYPE` / `LABEL` / `PROP_NAME` / `ENTITY_TYPE` constants), which is
shared across both files. That was the *structural* prerequisite for safely
reasoning about cross-file symmetry. With it in place, the question can be answered
definitively.

### The actual structure of each rule

**`PropertyTypeMismatchRule` (satisfaction — `rules.py`):**
Checks observed types against *one* declared storage type derived from
`TypeInfo.python_type`. Prevalence-aware: computes each off-type's share of
`observed_type_counts` and modulates severity (ERROR vs WARNING). Enum-aware:
calls `_expected_storage_type` to unwrap enum member value types. Inputs are
always `(TypeInfo, PropertyProfile)` — the satisfaction path's fixed `(declared,
observed)` pairing.

**`PropertyTypeChangedRule` (diff — `diff_rules.py`):**
Compares two *sets* of resolved Python types (`_resolved_profile_types` —
maps each side's `observed_types` through `db_type_to_python` and compares the
resulting sets) or two declared `python_type`s directly (`_resolved_definition_types`).
No prevalence, no enums, no declared constraint to satisfy — just: do the two
sides agree? Inputs can be `(TypeInfo, TypeInfo)` or `(PropertyProfile,
PropertyProfile)` — the diff path's two valid same-kind pairings.

**`_rel_operand_kind` (diff — `diff_rules.py`):**
Exists *only* in the diff path because the diff path must distinguish profile↔profile
from definition↔definition at runtime (both are valid). The satisfaction path has
a structurally fixed `(DefinitionView, ProfileView)` pairing set at the single
`_compare_views` call site in `compare_profile_to_definition` — the engine
guarantees the pairing, so no runtime dispatch is needed.

### The one genuinely-shared core — already hoisted

The DB-type-string → Python-type mapping (`db_type_to_python`) is the only
behaviour-identical piece used by both. It already lives in `type_mapping.py`, a
dependency-free leaf module imported by both rule files. This was already the
correct state prior to this ADR.

### Why consolidation would add indirection rather than remove it

A shared "type mismatch core" would need to serve two structurally different inputs:
- satisfaction: `(TypeInfo, PropertyProfile)` → one declared type vs a set of
  observed types, with prevalence and enum unwrapping.
- diff: `(TypeInfo, TypeInfo)` or `(PropertyProfile, PropertyProfile)` → two
  same-kind sets compared for inequality.

The dispatch required to cover both shapes would be *larger* than the divergence it
replaces. The E56.6 rule — "only if it deletes net code" — is not met. A hoisted
abstraction here would obscure two distinct algorithms behind a unified surface,
which is the opposite of the documentation-readiness goal.

### Verdict: no change; the symmetry is coincidental

The apparent symmetry is coincidental: both files compare types, but they compare
different things in different shapes for different purposes. The correct resting
state is two separate, focused implementations that share only the type-mapping
leaf (`type_mapping.py`). Nothing in the E56.5 named-contract foundation changes
this assessment.

### E58.2 disposition

Closed as **not needed**. The recorded verdict is: the type/operand-kind logic in
`rules.py` and `diff_rules.py` is legitimately divergent; the one shared core is
already consolidated; no further action is warranted.

---

## Consequences

- No production code changes. The engine is correct and remains unchanged.
- Both design questions are now **closed with a reasoned verdict**, not perpetually
  re-openable comments. A newcomer who asks either question can be pointed to this
  document.
- E58.1 and E58.2 are closed as not needed.
- The `compare_profile_to_definition` docstring (the "Implementation note") and the
  `diff_rules.py` module docstring are the in-code locations that carry the
  self-documenting rationale for each finding; they are updated in the same session
  to reflect the settled understanding without referencing this ADR.
