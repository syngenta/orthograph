# Epic E56: Capability Readability Distillation — Make Validation / Query / Profiling / Comparison Read Cleanly

> **Priority:** High
> **Phase:** v0.1.0 — quality / documentation-readiness
> **Type:** Behaviour-preserving **simplification**. No behaviour change, no test
>   change, no public-interface change, no new abstraction/infrastructure unless
>   it removes net complexity.
> **Decision:** [ADR-042](../../decisions/042-internal-logic-distillation.md)
> **Rubric (every task judged against this):** readability for an engineer
>   *unfamiliar with the code* · maintainability · remove redundancy · remove
>   reader surprise · name hidden contracts · SOLID extensibility (open/closed
>   where it costs nothing) · **no performance sacrifice** · the public verb reads
>   down to the logic without a memorised convention · the diff is a
>   *simplification* (net less code or clearer code, never more machinery).

---

## Why This Epic Exists

Two passes were run (see ADR-042). Radon says the codebase is healthy and the new
root API is exemplary. But reading the **four headline capabilities** as a
newcomer — drilling from each public verb to the logic — surfaces the real debt:
**cross-cutting hidden contracts and near-verbatim duplication** that radon cannot
see. The product wants the code behind *description, validation, query,
profiling, and comparison* to **read as the description of its own algorithm**,
navigable to the low-level functions. This epic delivers that by simplification —
naming what is implicit, deleting what is duplicated, and distilling oversized
functions into dispatchers that narrate the algorithm.

This is one epic, organised **by capability** and sequenced **foundations-first**
so nothing is done-then-undone: within each capability, the shared contract/helper
lands before the functions that consume it are distilled.

---

## Hard Invariants (every task; never weaken)

| Invariant | Check |
|-----------|-------|
| Full suite stays green | `python -m pytest tests -q` |
| No test edited to fit a refactor | `git diff --stat tests/` empty |
| No `ValidationIssue` code/severity/message text change | targeted tests + grep touched messages |
| No public signature change (root modules, ABCs, query bases) | `python -m mypy src/orthograph` clean |
| No vendor import added to a vendor-free layer; no cross-backend import | `python -m pytest tests/test_architecture.py -q` |
| Notebook/doc rendered output unchanged | `python -m pytest notebooks -q` (FINAL) |
| **No new abstraction/indirection unless it deletes more than it adds** | reviewer reads the diff; net LOC should trend **down** |
| **No perf regression on hot paths** | extraction is allocation-neutral on node/rel scans + rule eval (no new per-row temp objects) |
| Touched radon block ends grade **A or B** (D drops ≥1 grade) | `radon cc <file> -s` before/after |

**Per-task loop (green-stays-green; tests already exist):**
```
pwsh> radon cc <file> -s                  # BEFORE (for any radon-flagged target)
# simplify: name the contract / hoist the dup / extract the helper. Behaviour identical.
pwsh> python -m pytest <task test path> -q
pwsh> python -m mypy src/orthograph
pwsh> radon cc <file> -s                  # AFTER
pwsh> python -m pre_commit run --files <changed files>
```
If a test goes red → the change altered behaviour → **revert and redo smaller**.
Never edit the test.

**Target file → test path:**
`cypher/*` → `tests/cypher/` · `comparison/*` → `tests/comparison/` ·
`graph_definition/*` → `tests/graph_definition/` (+ cardinality suites in `tests/`) ·
`visualization/text.py` → `tests/visualization/test_text.py` ·
backends → `tests/backends/<vendor>/` · `graph_profile/*` → `tests/graph_profile/` + backend tests.

---

## Workstream W0 — Setup

`radon cc src/orthograph -s -n C --total-average` and `python -m pytest tests -q`
to confirm the hotspot list and the green baseline (**1611 passed, 84 skipped**).

---

## Workstream W1 — Quick wins: dead code, dedup, naming (lowest risk)

> Land first. Pure deletions and renames; each is independently revertible and
> sets up later tasks. **Haiku/Qwen-class** except where noted.

#### E56.1 — Delete dead `_PARSE_PLACEHOLDER` + de-duplicate the simple-Cypher validation idiom — **Sonnet**
`cypher/validation.py:39` declares `_PARSE_PLACEHOLDER` that is **never used** in
the module (dup of `base_models.py`). Delete it. Then extract the byte-identical
`params_fields`/`identifier_fields` + `validate_cypher_spec(output_model=None)`
logic shared by `validate_query` (≈334-345) and the CypherQuery branch of
`validate_query_catalogue` (≈377-390) into one private helper called by both.
*Done:* both call sites read one line; suite green; grep confirms `_PARSE_PLACEHOLDER` gone.

#### E56.2 — `visualization/text.py`: extract the duplicated property-profile renderer — **Haiku**
`profile_to_text` (CC **D 21**) renders node-property and rel-property blocks with
near-verbatim logic (pct, `[constrained]`/`[unconstrained]`, `values=…`, the
count line). Extract `_render_property_profiles(props, *, header, indent) -> list[str]`,
call twice. **Byte-identical output.** *Done:* `profile_to_text` ≤ B; output diff empty.

#### E56.3 — Hoist duplicated inspector helpers onto `CypherInspector` — **Sonnet**
`validate_database`, `_build_value_distribution`, the value-scan honest-degradation
guard, and `_fetch_node_count`/`_fetch_rel_count` are **near-verbatim duplicated**
between `backends/neo4j/inspector.py` and `backends/memgraph/inspector.py`. Hoist
the common bodies onto the existing `graph_profile/inspection.py::CypherInspector`
base (or a vendor-free helper). **Preserve the Memgraph scalar-histogram parity
deviation as an explicit overridable hook** (ADR-042). No cross-backend import
(Constraint 11). *Done:* each duplicate exists once; both backends' inspector tests green; `tests/test_architecture.py` green.

> **Precondition (E57).** The `_build_value_distribution` bodies are byte-identical;
> the parity deviation lives in the **query-layer histogram key**
> (`apoc.convert.toJson` vs `toStringOrNull`), not the assembler. When hoisting,
> keep that key difference as the variable — do **not** flatten it. See
> [E57](E57_value_distribution_parity_review.md).

#### E56.4 — Name the validation tuple-key contracts — **Sonnet**
`graph_definition/validation.py:25-35`: the aliases `_DegreeCounts`/`_PartitionCounts`/
`_Partition`/`_EndpointProps` hide load-bearing key shapes (`(uid, rel_label)`,
`(source-props, target-props)`). Give each a self-describing name and a one-line
docstring stating the key shape; do **not** change the underlying types or any
signature (pure rename + comment-to-code). Fix the in-file inconsistency where raw
`__source_cardinality__` is read in one place and `source_cardinality()` in
another — standardise on the accessor where it is a no-behaviour-change swap.
*Done:* aliases self-describe; suite green; mypy clean.

---

## Workstream W2 — Comparison reads as an algorithm (medium risk)

> The comparison engine carries the single biggest newcomer barrier (the
> `RuleContext` magic-dict contract + the presence-rule boilerplate). Land the
> **contract-naming task first**, then the dependent distillations.

#### E56.5 — Make the `RuleContext` contract explicit (foundation) — **Opus**
`comparison/rules.py:78-80` + `engine.py:67-133`: `RuleContext.left/right` are
`Any` meaning different things per address, and `extra` is a magic-string dict
(`address_type`, `label`, `prop_name`, `entity_type`) set in the engine and read
by every rule, with the producer/consumer split across files. **Without changing
the `Rule` Protocol or any rule's public call signature**, document the contract
in code: introduce named constants for the `extra` keys (so `extra[ADDRESS_TYPE]`
replaces the bare string), and a single docstring/`TypedDict`-style note co-located
with `RuleContext` that states exactly which keys exist for each address kind and
what `left`/`right` hold. This is the *foundation* the W2 distillations read
against — do it first, keep it minimal (name the contract, don't re-engineer the
dispatch). *Done:* every magic-string key reference goes through a named constant; suite green; no Protocol change.

#### E56.6 — Collapse the 8 presence-rule classes to one documented shape — **Opus**
`rules.py:148-237` (4 satisfaction presence rules) + `diff_rules.py:334-423` (4 diff
presence rules) repeat one boilerplate: check address kind → one-sided `is None`
guard → pull the label/type from `address` → yield one issue. Reduce the
repetition **without changing behaviour or the rule set the engine iterates** —
e.g. a small shared builder the eight rules call, or one parameterised rule
factory, *only if it deletes net code*. If a factory would add more machinery than
it removes, instead extract just the shared guard+emit helper and leave the eight
thin classes. Reader should read the shape **once**. *Done:* the boilerplate exists once; `tests/comparison/` green; the engine still iterates the same rule keys.

#### E56.7 — Distil `CardinalityViolationRule` into a readable verdict flow — **Opus**
`rules.py:683-965`: a ~280-line, five-method mini-engine — the hardest thing in
the capability to read cold. Distil so the entry `__call__` reads as: *resolve the
declared side (constant vs conditional) → compute observed degree per partition →
emit matched-bound / unmatched-floor verdicts.* Name the positional `_PartitionDist`
tuple and the `frozenset`-of-items group key; type the `Any` helper params
(`rt_class`→`type[RelationshipModel]`, `rel_profile`→`RelationshipTypeProfile`)
where it is a pure annotation add. **No change to any `CARDINALITY_*` code/message.**
*Done:* class + methods ≤ B; the conditional-cardinality + partition test suites green; messages identical.

#### E56.8 — Distil the two property rules — **Sonnet**
`PropertyTypeMismatchRule` (class C11) and `PropertyEnumValueRule` (class C12,
`__call__` C11): each `__call__` interleaves guards with multiple verdict
emissions. Keep `__call__` as a short dispatcher (applicability/availability
guards) delegating to named per-verdict helpers (`_unverifiable_issue`,
`_undeclared_value_issues`, `_unobserved_value_issues`, `_type_mismatch_issues`).
Exact codes/severities/messages preserved. Run after E56.5 (uses the named keys).
*Done:* both classes ≤ B; `tests/comparison/` green.

> **Note (out of scope, recorded → tracked as [E58](E58_comparison_dispatch_symmetry.md)):**
> the `engine._compare_views` "five-pass" comment vs four visible passes, and the
> broader `rules.py`↔`diff_rules.py` type-mismatch/operand-kind symmetry, are
> deferred to a follow-on — they touch dispatch design and risk do-and-undo
> against E56.5/6. Fix only the comment miscount opportunistically inside E56.5
> (**done** — `engine.py:51` now reads "four-pass"). The remaining two items
> (the satisfaction-path `left`/`right` inversion and the cross-file rule
> symmetry) are scoped and decision-gated in **E58** so they are tracked rather
> than buried here.

---

## Workstream W3 — Validation reads as an algorithm (medium risk; after W1 naming)

> Depends on E56.4 (named key types). The "absolute convention" is the barrier;
> make it explicit, then distil the mirrored functions.

#### E56.9 — Express the cardinality "absolute convention" once, in code — **Opus**
The rule that `rule.source` always describes the source-label node and
`rule.target` the target-label node — for **both** the source and target
cardinality side — is restated in 4 comment sites (`validation.py:476-479`,
`575-591`; `cardinality_checks.py:34-38`; `graph_definition.py:258-262`) and
enforced nowhere; the `side`/`self_props`/`other_props` names fight it. **Without
changing behaviour**, name the convention in one place (a module constant or a
single well-named helper that resolves "which endpoint props go with this side")
and have the four sites reference it; rename `self_props`/`other_props` to names
that match the convention (e.g. `source_side_props`/`target_side_props`) at the
*private* helper boundary (no public signature touched). *Done:* the convention lives in one named place; the conditional-cardinality suites green.

#### E56.10 — Distil RETURN→Output alignment (headline radon target) — **Opus**
`cypher/validation.py::_check_return_output_alignment` (CC **D 26**, the repo's
worst) encodes the PRD signature "RETURN→Output alignment" algorithm. Classify the
Output once (whole-entity / flat-scalar / projection) then dispatch to
`_check_whole_entity_alignment` and `_check_flat_field_alignment`; the entry reads
as *classify Output → route → return issues.* Every `QUERY_RETURN_OUTPUT_*` message
identical. *Done:* function + helpers ≤ B; RETURN/Output tests green.

#### E56.11 — Make the RETURN-column classifier explicit (resolves the silent-skip finding) — **Opus**
`cypher/parser.py::_extract_return_columns` (CC **C 19**) classifies neighbours by
`hasattr` and **silently drops** unclassifiable columns. Extract
`_classify_return_neighbour(...) -> ReturnColumn | None` with explicit type checks
and a *named, commented* "cannot classify → skip" branch. **No output change** (the
suite locks the columns); the skip merely becomes visible. May run parallel with
E56.10 (different file). *Done:* function ≤ B; `tests/cypher/test_parser.py` + alignment integration tests green.

#### E56.12 — Flatten `validate_query_catalogue` per-query dispatch — **Sonnet**
`cypher/validation.py::validate_query_catalogue` (CC **C 13**): a single loop with
five `continue` exit ramps and an inline typed-tail. Extract
`_validate_one_query(query, definition) -> ValidationResult` (per-kind) so the loop
reads *for each query → merge its validation.* Reasons/codes unchanged. Run after
E56.10 (same file). *Done:* function ≤ B; `tests/cypher/` green.

#### E56.13 — Tame the symmetric node/rel validation methods — **Sonnet**
`GraphValidator._validate_and_index_nodes` (≈796-855) and
`_validate_and_collect_rels` (≈859-927) are two ~65-line near-duplicate methods
(node has 4 guards, rel has 5). Extract the shared guard ladder (label-present →
label-known → extra-props → pydantic) into one helper both call, so the reader
diffs nothing. **No change to issue order/codes.** Run after E56.4. *Done:* both methods read short; `tests/graph_definition/` green; issue ordering identical (assert via existing tests).

#### E56.14 — Factor the symmetric per-side cardinality check — **Opus**
`graph_definition/validation.py::_check_node_cardinality` (CC **C 11**) runs two
mirrored loops (outgoing source side / incoming target side). Extract
`_check_one_side(...)` owning the constant-vs-`ConditionalCardinality` decision so
the entry reads *for each outgoing rel → check source side; for each incoming
directed rel → check target side.* Preserve the directed/undirected count-source
selection exactly. Run after E56.9 (uses the named convention). *Done:* function ≤ B; in-memory + conditional cardinality suites green; all `CARDINALITY_*` identical.

---

## Workstream W4 — Query path clarity (medium risk; after W1)

#### E56.15 — De-duplicate the executor prologue; isolate the query-shape divergence to one place — **Opus**
The `CypherQuery` shape (`params_schema`/`query_id`) vs the typed `ReadQuery`/
`WriteQuery` shape (`Params`/`name`) is reconciled inside the executor by
`getattr(...) or ...` shims duplicated in `read` and `write`
(`query_execution.py:88-89,116-117`), and the identical read/write prologue
(params resolve → query-id resolve → validate → build → `_validate_cypher`) is
written twice. **Without unifying the two shapes and without renaming any public
attribute** (both are deferred to **[E60](E60_query_shape_alignment.md)**),
collapse the duplicated prologue into one private helper
(`CypherExecutor._prepare_statement`) and move the *only* place that knows two
shapes coexist into one named method (`CypherExecutor._query_shape`) whose
docstring names the divergence as accidental and points at E60 + ADR-042. A
reader then sees one prologue and one clearly-labelled reconciliation point that
the alignment epic will delete outright.

> **⚠ Original instruction rejected (latent bug).** This task previously read
> "route the executor through the existing adapters and delete the redundant
> `getattr ... or ...` fallback." That is **wrong**: the
> `CypherQueryReadAdapter`/`CypherQueryWriteAdapter` *re-expose* the simple names
> (`params_schema`/`query_id`), so the shim and the adapters are **coupled, not
> competing** — the shim is what reads the names the adapter exposes. Deleting
> the shim while routing through adapters would break the `CypherQuery`
> execution path, and making adapters the canonical seam would *add* a permanent
> bridging layer, deepening the union/abstraction coupling the product wants to
> remove. The adapters are therefore **left untouched** here. The genuine fix is
> the attribute rename in E60, which lets `_query_shape` be deleted entirely.

*Done:* read/write prologue exists once; the shape fallback lives in one named,
documented method (not duplicated, not in adapters); `tests/cypher/` + executor
tests green; mypy clean; no public attribute or adapter changed.

#### E56.16 — Disambiguate the three same-named `validate_*` functions — **Sonnet**
Three functions named `validate_query` / `validate_cypher` / `validate_query_catalogue`
live across `queries.py`, `cypher/validation.py`, `cypher/parser.py`, and the
public `queries.validate_query` forks into two of them. **Without renaming any
public symbol**, make the internal call sites unambiguous: keep the
`import ... as _cypher_validation` alias consistent, add a one-line "this delegates
to X" pointer at each public fork, and ensure the private helpers have distinct,
descriptive names where they are private-only. Pure clarity; no signature change.
*Done:* a reader following `queries.validate_query` lands unambiguously; suite green.

> **Note (out of scope, recorded → tracked as [E60](E60_query_shape_alignment.md)):**
> the two query shapes diverge by *attribute name only* (`Params`/`Identifiers`/
> `name` on the typed path vs `params_schema`/`identifiers_schema`/`query_id` on
> `CypherQuery`), and that divergence is paid for at five reconciliation sites
> (executor, catalogue `describe()`, two validation extraction blocks, the YAML
> loader, and the adapters). Aligning the names — **typed adopts the Cypher
> names** — collapses all five but is a public-attribute + serialization-adjacent
> design change, deferred to **E60**. E56.15 only does the reversible half
> (prologue de-dup + isolate the divergence into one named method) so nothing is
> built that E60 must undo. The `CypherGenerator` multi-responsibility (node CRUD
> / rel CRUD / DDL / typed read / typed write) and the `__dunder__` data-dict
> schema are real SOLID smells but splitting the class is a design change with
> public-surface risk — deferred to a dedicated follow-on, not mixed in here.

---

## Workstream W5 — FINAL verification sweep — **Haiku**

1. `python -m pytest -q` (full, incl. notebooks) — green.
2. `python -m pytest tests/test_architecture.py -q` — all five invariants green.
3. `python -m mypy src/orthograph` — clean.
4. `python -m pre_commit run --all-files` — clean.
5. Consolidated **before/after radon cc** table for every touched function (the
   seven radon targets must all be ≤ B), and a **net-LOC delta** for the epic
   (must trend down — this was a simplification).
6. Confirm `git diff tests/` is empty.

If any invariant fails → **stop and escalate** to the owning task; never weaken a
test or an architecture invariant.

---

## Reported-but-NOT-changed (behaviour / scope boundary — see ADR-042)

- `value_counts_top_n` default divergence (networkx 10 vs neo4j/memgraph `None`) —
  **behaviour**; changes default profile/notebook output → not this epic.
- `_build_value_distribution` neo4j↔memgraph parity deviation — intentional;
  preserved as an explicit hook when hoisted (E56.3).
- Unifying the two query shapes / splitting `CypherGenerator` — design changes,
  deferred. The query-shape *name* alignment (typed adopts `params_schema`/
  `query_id`) is tracked as [E60](E60_query_shape_alignment.md).
- `rules.py`↔`diff_rules.py` type-mismatch/operand-kind symmetry — deferred to
  avoid do-and-undo against W2.

---

## Model Assignment Summary

| Task | Capability | Model | Why |
|------|-----------|-------|-----|
| E56.1 dead const + dedup validation idiom | query | **Sonnet** | small but spans two call sites |
| E56.2 property-profile renderer dedup | profiling-render | **Haiku** (Qwen ok) | mechanical, exact-output lock |
| E56.3 hoist duplicated inspector helpers | profiling | **Sonnet** | base-vs-subclass placement + parity hook |
| E56.4 name validation tuple-key types | validation | **Sonnet** | rename + contract docstring |
| E56.5 explicit `RuleContext` contract | comparison | **Opus** | foundation; contract design, no Protocol change |
| E56.6 collapse 8 presence rules | comparison | **Opus** | judgement: dedup only if it deletes net code |
| E56.7 distil `CardinalityViolationRule` | comparison | **Opus** | hardest read; verdict-flow design |
| E56.8 distil property rules | comparison | **Sonnet** | local verdict extraction (after E56.5) |
| E56.9 name the "absolute convention" | validation | **Opus** | the central hidden contract |
| E56.10 RETURN→Output alignment split | query | **Opus** | worst CC; algorithm doc source |
| E56.11 explicit RETURN classifier | query | **Opus** | resolves silent-skip; exhaustiveness |
| E56.12 flatten catalogue dispatch | query | **Sonnet** | per-kind ladder (after E56.10) |
| E56.13 tame node/rel validation twins | validation | **Sonnet** | shared guard ladder (after E56.4) |
| E56.14 symmetric per-side cardinality | validation | **Opus** | correctness-sensitive (after E56.9) |
| E56.15 dedup executor prologue + isolate shape seam | query | **Opus** | converge to one prologue + one named divergence point (rename deferred to E60) |
| E56.16 disambiguate `validate_*` names | query | **Sonnet** | clarity, no signature change |
| E56.W5 final sweep | all | **Haiku** | fully-specified verification |

> **Opus** is reserved for the contract-design / algorithm-shape / correctness-
> sensitive tasks (E56.5, .6, .7, .9, .10, .11, .14, .15). Everything else is
> Sonnet; the two purely-mechanical tasks (E56.2, and E56.W5 verification) can run
> on **Haiku/Qwen** under the test+radon gate.

---

## Execution Order (progressive — foundations before consumers, no do-and-undo)

```
W0  setup
W1  E56.1  E56.2  E56.3  E56.4         (independent quick wins; parallel across files)
W2  E56.5 ─► E56.6, E56.7, E56.8       (E56.5 is the foundation; .6/.7 parallel, .8 after .5)
W3  E56.9 ─► E56.14 ;  E56.4 ─► E56.13 ;  E56.10 ─► E56.12 ;  E56.11 ∥ E56.10
W4  E56.15 ;  E56.16                   (after W1)
W5  FINAL sweep
```
Same-file tasks are sequential (E56.1/.10/.12/.15/.16 touch `cypher/*`; the three
`rules.py` tasks; the validation tasks). Different-file tasks parallelise.

---

## Success Criteria

- [ ] Each headline capability's public verb reads down to its logic without a
      memorised magic-dict contract, argument inversion, or 280-line rule —
      ready to lift into algorithm documentation.
- [ ] The hidden contracts are named **in code**, once: the `RuleContext` `extra`
      keys, the validation tuple-key shapes, the cardinality "absolute convention".
- [ ] Near-verbatim duplication removed at the right layer: inspector helpers on
      `CypherInspector`; the property-profile renderer; the simple-Cypher
      validation idiom; the executor prologue; one query-reconciliation seam.
- [ ] Dead `_PARSE_PLACEHOLDER` deleted; the three `validate_*` forks unambiguous.
- [ ] All seven radon targets drop to grade **A/B** (the two D-grades drop ≥1).
- [ ] Full suite + notebooks + mypy + architecture + pre-commit green;
      `git diff tests/` empty; no `ValidationIssue` message/output changed.
- [ ] **Net LOC trends down** and no new framework/registry/indirection was added
      that doesn't delete more than it introduces (reviewer-confirmed).
- [ ] No hot-path perf regression (extraction allocation-neutral).

---

## Out of Scope

- Any behaviour, rule, severity, message, default, or public-signature change.
- Unifying the two query shapes; splitting `CypherGenerator`; the
  `rules.py`↔`diff_rules.py` deep symmetry — deferred design epics.
- The root-level API modules (already clean — ADR-040/041).
- Error-hierarchy / logging (E20); the E20-T7 backtick-`$param` behaviour gap.
- New abstractions or infrastructure that do not remove net complexity.
