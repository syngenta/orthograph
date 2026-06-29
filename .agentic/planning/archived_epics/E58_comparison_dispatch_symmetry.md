# Epic E58: Comparison Dispatch & Rule Symmetry — Scope & Decide (deferred from E56 W2)

> **Priority:** Low
> **Phase:** v0.1.0 — quality / architecture
> **Type:** **Scoping & decision first.** These are *design* changes to the
>   comparison dispatch, not the behaviour-preserving distillation E56 is limited
>   to. This epic produces an ADR (or a recorded "no-change" decision) **before**
>   any production code is touched. A later task/epic actions the chosen design.
> **Origin:** E56 Workstream W2 "Note (out of scope, recorded)" — explicitly
>   deferred to avoid do-and-undo against the E56.5/E56.6 contract-naming and
>   presence-rule work. The single in-scope crumb of that Note (the
>   `_compare_views` "five-pass"→"four-pass" comment miscount) was already fixed
>   inside E56.5; everything else lands here.
> **Relates to:** ADR-042 (E56 distillation; the boundary that pushed this out),
>   E56.5 (named `RuleContext.extra` keys — the foundation these items read
>   against), E56.6 (presence-rule de-duplication), ADR-015 (declared/observed
>   mirror), E27 (symmetric comparison — `views.py` + `diff_rules.py`).

---

## Why this epic exists

E56 distilled the comparison rules **without** touching dispatch design, on
purpose: the two items below change *how rules are selected/parameterised* or
assert a cross-file structural contract, which is a behaviour/design risk against
a correct, test-locked engine. They were recorded as out-of-scope in the E56 W2
Note rather than buried as a comment. This epic gives them a home so the
follow-on is tracked, not lost.

**These are not bugs.** The engine is correct and test-locked. This is a
readability/maintainability investment with a real do-and-undo risk, hence
**decision-first**.

---

## The two deferred items

### Item A — the satisfaction-path `left`/`right` argument inversion

`engine.py::compare_profile_to_definition` takes the public order
`(profile, definition)` but calls the internal walker **reversed**:
`_compare_views(DefinitionView(definition), ProfileView(profile), …)`
(`engine.py:179-191`). The convention — *rules always read `context.left` as
declared, `context.right` as observed* — is documented in a long "Implementation
note" docstring (`engine.py:176-189`) and **enforced nowhere**. A newcomer must
hold the inversion in their head to trust any rule. The pass-2 analysis (ADR-042
§"dominant findings", Comparison row) flagged this as a top newcomer tax that
E56 chose not to touch because removing it touches the public-call convenience
and the shared walker.

**Open question for the ADR:** is the inversion worth removing (e.g. make the
declared/observed roles explicit on `RuleContext` so no rule depends on
positional `left`/`right`), or is the documented convention the right resting
state? Either way the decision must be **recorded**, not left implicit.

### Item B — `rules.py` ↔ `diff_rules.py` type-mismatch / operand-kind symmetry

The satisfaction rules (`rules.py`) and the symmetric diff rules
(`diff_rules.py`, from E27) carry **mirrored-but-separate** type-mismatch and
operand-kind logic. The E56 W2 Note recorded this as "broader symmetry … touches
dispatch design and risks do-and-undo against E56.5/6". With E56.5's named
`extra` keys now in place (`ADDRESS_TYPE`/`ADDR_NODE_LABEL`/`ADDR_REL_TYPE`,
shared across both files), the prerequisite for safely reasoning about the
symmetry exists — but the consolidation itself was deferred.

**Open question for the ADR:** is there a shared, behaviour-identical core to
hoist (mirroring the E56.6 presence-rule decision: *only if it deletes net
code*), or do the two rule sets legitimately diverge enough that the apparent
symmetry is coincidental and should stay separate?

---

## Hard invariants (if/when a fix is actioned — not this scoping round)

Same contract E56 honoured (ADR-042):

| Invariant | Check |
|-----------|-------|
| No `ValidationIssue` code/severity/message change | `tests/comparison/` + grep touched messages |
| No public signature change (`compare_*`, `Rule` Protocol) | `python -m mypy src/orthograph` clean |
| Full suite stays green; no test edited to fit the change | `python -m pytest tests -q`; `git diff --stat tests/` empty |
| Any new indirection must delete more than it adds | reviewer reads the diff; net LOC trends down |
| Architecture invariants hold | `python -m pytest tests/test_architecture.py -q` |

---

## Tasks

#### E58.0 — Decision session + ADR (decision-only; **Opus**)
Read `engine.py:44-191`, `rules.py`, `diff_rules.py`, ADR-015, ADR-042, and the
E56.5/E56.6 outcomes. For **Item A** and **Item B** each, record in a new ADR:
the current shape, the readability cost, the proposed change (or explicit
no-change), the rejected alternatives, and — critically — the
do-and-undo / behaviour-risk assessment that justifies the verdict. **No
production code in this task.**
*Done:* ADR in `.agentic/decisions/` covering both items with a recorded verdict
(change vs no-change) and rationale; CONTEXT.md / overview cross-linked if a
documented boundary moves.

#### E58.1 — Action Item A (only if E58.0 votes "change"; **Opus**)
Implement the ADR's chosen resolution for the `left`/`right` inversion. Behaviour
identical; `Rule` Protocol and public `compare_*` signatures unchanged. If E58.0
votes "no change", this task is closed as **not needed** with the ADR as the
record.
*Done:* the inversion is either removed per the ADR or explicitly retained;
`tests/comparison/` green; mypy clean; messages identical.

#### E58.2 — Action Item B (only if E58.0 finds net-deleting consolidation; **Opus/Sonnet**)
Hoist the shared type-mismatch/operand-kind core per the ADR **only if it deletes
net code** (the E56.6 rule). Otherwise close as **not needed**, recording that the
symmetry is coincidental.
*Done:* the shared core exists once **or** the divergence is documented;
`tests/comparison/` green; mypy clean; `tests/test_architecture.py` green.

---

## Out of scope

- Any behaviour, rule, severity, message, or public-signature change.
- Unifying the two query shapes / splitting `CypherGenerator` (separate deferred
  design epics — see ADR-042 §"reported, not changed").
- Re-doing any E56 distillation; E56's W2 output is the baseline this builds on.

---

## Success criteria

- [ ] Both deferred Item A and Item B have a **recorded verdict** (an ADR), not a
      buried code comment.
- [ ] If a change is actioned, it is behaviour-preserving (messages/signatures
      identical), net-deleting where it adds indirection, and the full suite +
      mypy + architecture invariants stay green.
- [ ] If "no change" is the verdict, the rationale (do-and-undo risk, coincidental
      symmetry) is documented so the question is closed, not perpetually re-opened.
