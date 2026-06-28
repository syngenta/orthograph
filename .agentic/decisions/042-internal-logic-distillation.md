# ADR-042: Capability Readability Distillation — Behaviour-Preserving Simplification

> **Status:** Accepted
> **Date:** 2026-06-28
> **Supersedes / amends:** none — this is a quality decision, not a contract change
> **Relates to:** ADR-040 / ADR-041 (root-level capability modules — the *facade*
>   was just clarified; this ADR clarifies the *internals behind it*), E2 (code
>   deduplication, done), E20 (tech debt)

---

## Context

Two analysis passes were run over `src/orthograph`.

**Pass 1 (radon).** The codebase scores healthy (avg cyclomatic complexity
**A ≈ 2.8**, every file maintainability grade **A**; the new root-level API
modules are exemplary, avg CC 1.64). Radon flags seven branch-heavy functions
(`_check_return_output_alignment` D26, `profile_to_text` D21,
`_extract_return_columns` C19, `validate_query_catalogue` C13, the two property
rules C11–12, `_check_node_cardinality` C11).

**Pass 2 (capability readability, the deciding pass).** Reading the four key
capabilities — **description/validation, query, profiling, comparison** — as an
engineer *unfamiliar with the code* would, drilling from each public verb down
to the logic, surfaces debt that **radon cannot see**: long-but-flat functions,
opaque names, and — most importantly — **cross-cutting hidden contracts and
near-verbatim duplication** that force a reader to hold conventions in their head
or diff two files to trust they agree.

The product goal is that the code supporting the headline capabilities
**reads as a description of its own algorithm**, navigable by a newcomer down to
the low-level functions. Radon-branch-count is a weak proxy for that; the pass-2
findings are the real target.

### The dominant, capability-spanning findings

| Capability | Highest-impact readability debt (pass 2) | Radon-visible? |
|------------|-------------------------------------------|----------------|
| **Comparison** | `RuleContext.left/right/extra` is an `Any`/magic-string-dict contract set in `engine.py` and read by every rule; the satisfaction-path **left/right argument inversion**; **8 presence-rule classes** repeating one boilerplate shape; `CardinalityViolationRule` is a ~280-line multi-method mini-engine in one rule. | No |
| **Validation** | The **"absolute convention"** (rule.source ⇄ source-label node, for *both* sides) restated in 4 comment sites and enforced nowhere; unnamed tuple-key type aliases (`_DegreeCounts` keyed by `(uid, rel_label)`); two ~65-line near-duplicate methods (`_validate_and_index_nodes`/`_validate_and_collect_rels`); raw `__source_cardinality__` read in one place and the `source_cardinality()` accessor in another. | Partly |
| **Query** | The **two-paths split** (`CypherQuery.params_schema/query_id` vs typed `Params/name`) reconciled by `getattr(...) or ...` shims in `query_execution.py` *and* by dedicated adapters — two competing reconciliation mechanisms; three same-named `validate_*` functions across modules; a **dead `_PARSE_PLACEHOLDER`** constant in `validation.py`. | Partly |
| **Profiling** | `validate_database`, `_build_value_distribution`, the value-scan honest-degradation guard, `_fetch_*_count`, and the source/target partitioned-cardinality dispatch loop are **duplicated near-verbatim across the neo4j and memgraph inspectors** while the shared `CypherInspector` base holds only plumbing; `_discriminator_map` is a same-named mirror pair across two files. | No |

## Decision

Adopt a **behaviour-preserving, capability-organised readability distillation**.
The pass-2 findings drive it; radon CC is a secondary check, not the target.
Every task honours a fixed contract:

1. **No behaviour change. No test change. No public-interface change.** The full
   suite (1611 source tests + notebooks) is the specification and stays green.
   No public function/class signature, no `ValidationIssue` `code`/`severity`/
   `message`, no rendered notebook output changes. (Messages and outputs are
   asserted by tests and notebooks.)
2. **Simplify, do not enlarge.** This is a *simplification* task. Prefer deleting
   duplication and naming hidden contracts over adding layers. **Do not introduce
   a new abstraction or infrastructure unless it removes net complexity** (e.g.
   hoisting an already-duplicated method onto the existing `CypherInspector` base
   is allowed; inventing a new framework, registry, or indirection layer is not).
   When in doubt, the smaller diff wins.
3. **Name the hidden contracts.** Replace `Any`/magic-string-dict and unnamed
   tuple-key conventions with named, documented types or constants **only where
   that is a pure rename/relocate** (no signature change on the public surface).
   The "absolute convention", the `(uid, rel_label)` key shape, and the
   `sk{i}`/`tk{i}` column protocol should be expressed once, in code, not in four
   scattered comments.
4. **Distil by extraction.** Decompose oversized functions into named,
   single-responsibility helpers whose names *state the step they own*; the
   original becomes a short dispatcher that reads like the algorithm's spec.
5. **Remove redundancy at the right layer.** Hoist near-verbatim duplicated logic
   to the existing shared base/helper it already belongs to (respecting backend
   isolation — Constraint 11: no `backends/<X>` imports `backends/<Y>`; shared
   logic lives on `CypherInspector` or a vendor-free helper, never cross-backend).
6. **Performance is not sacrificed.** No extra passes, copies, or per-row
   allocations introduced for the sake of tidiness; extraction must be
   allocation-neutral on the hot paths (node/rel scans, rule evaluation).
7. **Progressive, no do-and-undo.** Sequence so that shared foundations (named
   contracts, hoisted helpers) land *before* the functions that consume them are
   distilled. A later task never rewrites what an earlier task just produced.

### Explicitly reported, NOT changed (behaviour or scope boundary)

- **`value_counts_top_n` default divergence** (networkx defaults to 10, neo4j/
  memgraph to `None`) — this is *behaviour* (it changes default profile output and
  notebook results). **Reported, not changed** here; if it is a real defect it
  belongs to a behaviour epic (E48 configuration territory).
- **`_build_value_distribution` neo4j↔memgraph parity deviation** (scalar-only
  histogram key on Memgraph) — a documented, intentional honest-degradation. When
  hoisting the common arithmetic, the deviation is preserved as an explicit
  subclass hook, never erased.
- **`_extract_return_columns` silent-skip of unclassifiable columns** — made
  *visible* (explicit, named branch) without changing which columns are produced;
  the test suite locks the output. Distinct from the tracked E20-T7 backtick gap.
- **The two-paths query split** is *clarified and de-duplicated* (one
  reconciliation seam, not two; shared idioms named), **not unified** — unifying
  `CypherQuery` and the typed bases is a behaviour/design change, out of scope.

### Addendum (2026-06-28) — query-shape *name* alignment deferred to E60

The W4 re-analysis found the query-path debt is narrower and more structural
than "two reconciliation seams": it is an **accidental attribute-name
divergence**. The typed path uses `Params` / `Identifiers` / `name`; the simple
`CypherQuery` uses `params_schema` / `identifiers_schema` / `query_id`; only
`cypher_template` already agrees. Every generic consumer pays for this at five
sites (executor `_query_shape`, `QueryCatalogue.describe()`, the two
`cypher/validation.py` extraction blocks, the YAML loader, and the
read/write adapters), typically via a `query: ReadQuery | WriteQuery |
CypherQuery` union plus `getattr`/`isinstance` reconciliation — the exact
union+bridge coupling the product wants to dissolve.

**Ratified direction:** the **typed path adopts the Cypher names**
(`params_schema` / `identifiers_schema` / `query_id`), because `CypherQuery`'s
names are already the YAML wire format and the shape the team prefers. This
aligns the *vocabulary* across typed / Cypher / future-ORM paths **without**
collapsing them into one type or union — the paths stay parallel. This is a
public-attribute + serialization-adjacent design change and is therefore **out
of scope for this distillation ADR**; it is tracked as
[E60](../planning/active_epics/E60_query_shape_alignment.md) and gated on its own
ADR.

**What E56 W4 did instead (no-regret, reversible):** E56.15 was rewritten. Its
original "route the executor through the adapters and delete the `getattr` shim"
instruction was **rejected** — the adapters re-expose the simple names, so the
shim and adapters are *coupled, not competing*, and routing through adapters
would both break the `CypherQuery` path and add a permanent bridging layer. W4
only collapsed the duplicated read/write prologue into
`CypherExecutor._prepare_statement` and isolated the divergence into one named,
documented method (`CypherExecutor._query_shape`) pointing at E60. When E60's
rename lands, `_query_shape` is deleted outright — nothing built in W4 needs
undoing.

## Rejected alternatives

- **Radon-only refactor (pass-1 scope).** Rejected: it would tidy seven functions
  while leaving the cross-cutting contracts (the real newcomer barriers) untouched
  — failing the stated product goal.
- **Rewrite the validation/comparison engines from scratch / introduce a typed
  RuleContext-subclass hierarchy.** Rejected this round: it risks behaviour change
  against a correct, test-locked implementation and tends toward *adding*
  abstraction. Naming the existing contract in place is the smaller, safer move.
- **Unify the two query paths.** Rejected: behaviour/design change, not
  simplification of existing behaviour.
- **Lower radon thresholds / suppress warnings.** Rejected: hides the problem.

## Consequences

- A newcomer can read each capability's public verb down to its logic without
  reconstructing a magic-dict contract, an argument inversion, or a 280-line rule
  from memory; the distilled code is ready to lift into algorithm documentation.
- Net **less** code (duplication removed, dead constant deleted), not more.
- The work is delegable task-by-task to lower-capability models because each task
  is a local, test-locked transform with a mechanical gate (suite green + diff is
  a simplification + radon non-regression). Algorithm-shape decisions are reserved
  for higher models.
- One-time `git blame` churn on the touched functions; acceptable for the
  readability gain on otherwise-stable modules.
