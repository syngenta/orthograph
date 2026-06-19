# Epic E40: Conditional Cardinality — In-Memory (Phase 1)

> **Priority:** High
> **Phase:** v0.1.0 — pilot readiness (matterforge / MatProt `Operation` model)
> **Blocked by:** none (additive to existing `graph_definition/`)
> **Blocks:** E41 (profiling enforcement)
> **Type:** Build (new declaration model + seam) + internal refactor (validator counter) + extensible checks + YAML + tests
> **Decisions:** ADR-029 (read it first — it is the spec)
> **Rubric (every task judged against this):** strongly-typed · SOLID · readability over cleverness · small surgical diffs · break complex logic into named functions · docstrings carry only the essential · each task ends green with guardrails run

---

## Why This Epic Exists

A relationship's cardinality must be able to depend on the **property values of
its endpoint nodes**. Concretely (ADR-029): an `Operation` node, discriminated by
a `kind` property, has input/output counts that vary by `kind` **and** by the
kind of the node on the other end of the edge:

```
Operation(subsampling) -[:HAS_OUTPUT]-> Sample(subsampling)   1..2
Operation(split)       -[:HAS_OUTPUT]-> Sample(nothing)        0
Operation(combine)     -[:HAS_OUTPUT]-> Sample(nothing)        0
```

Today a cardinality side is a single `CardinalitySpec(min, max)`. This epic adds
`ConditionalCardinality` — a relationship-declared, endpoint-property-discriminated
cardinality — and enforces it for **in-memory data** (`GraphValidator.validate`).
Live-DB enforcement is E41 (this epic reports it `UNVERIFIABLE`).

---

## Decisions Already Made (do not re-litigate — see ADR-029)

- Cardinality stays **declared on the relationship**; identity stays the label.
- The field is a **polymorphic seam**: `CardinalitySpec | ConditionalCardinality`,
  both exposing `resolve_for_pair(self_props, other_props) -> CardinalitySpec`.
- `__source_cardinality__` partitions by the **target** endpoint's discriminator;
  `__target_cardinality__` by the **source** endpoint's. Each side discriminates
  only on its own endpoint and the opposite endpoint of the **same edge**.
- Rules use **property-map equality predicates**; **most-specific-wins**; **order
  irrelevant**; equal-top-specificity overlap is **rejected at definition time**.
- `default` is **required and explicit**; a `(*, *)` rule is **forbidden**.
- Definition-time checks are an **extensible checklist** (`standard_cardinality_checks()`).
- Discriminator-optionality is an **ERROR** (demotable later).
- Unmatched discriminator value at data time → fall to `default` **+ INFO**.
- Missing partition counts as **0** and is checked against its rule's `min`.
- Query-string validation is **untouched** (cardinality is not a static property).

---

## Existing Code to Reuse

| Need | Reuse | Location |
|------|-------|----------|
| Interval primitive + `contains` | `CardinalitySpec` | `graph_definition/models.py` |
| Named constants pattern | `Cardinality` | `graph_definition/models.py` |
| Declared property names | `get_all_property_names`, `get_required_property_names` | `graph_definition/models.py` (`_PropertySpecMixin`) |
| Construction-time check pattern | `GraphDefinition._check_structure`, `_check_undefined_node_refs` | `graph_definition/graph_definition.py` |
| Pluggable rule-list pattern | `comparison/rules.standard_rules()` | `comparison/rules.py` |
| Result currency | `ValidationIssue`, `ValidationResult`, `Severity`, `EntityType` | `diagnostics/` |
| Node/rel unpacking + degree counting | `_unpack_node`, `_count_rel_degrees`, `_check_node_cardinality` | `graph_definition/validation.py` |
| YAML cardinality parse/serialise | `_parse_cardinality`, `_serialize_relationship_type` | `io/yaml.py` |
| Cardinality formatting | `_format_cardinality` | `visualization/text.py`, `visualization/mermaid.py` |
| Comparison cardinality rule | `CardinalityViolationRule` | `comparison/rules.py` |

---

## Per-Task Guardrails (apply to EVERY task unless stated)

**Test pattern:** Each test must be a standalone function (not a class method) with a docstring that states the scope in the form `"Scope: <what is being tested>"`. Example:
```python
def test_cardinality_zero_contains_zero():
    """Scope: Cardinality.ZERO.contains(0) returns True."""
    assert Cardinality.ZERO.contains(0) is True
```

Run before declaring a task green (PowerShell):

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

Type-strictness: no `Any` in new public signatures (use `Mapping[str, object]`
or precise types); all new models frozen Pydantic (`model_config = {"frozen": True}`);
new public functions/classes fully annotated.

---

## Tasks (execute in order; each ends green)

### E40.1 — `Cardinality.ZERO`, `EXACTLY`, and the `resolve_for_pair` seam on `CardinalitySpec`

> **Model: Haiku.** Pure additions to one file with obvious tests; no cross-module reasoning.

**Goal:** the constant primitive gains the missing `ZERO` constant, an `EXACTLY(n)`
helper, and the polymorphic seam method (returning `self`) so a constant spec is a
valid `resolve_for_pair` participant.

**Operation** — in `src/orthograph/graph_definition/models.py`:
1. Add constant `Cardinality.ZERO: ClassVar[CardinalitySpec] = CardinalitySpec(min=0, max=0)` with a one-line docstring `"0..0 — must not exist."`.
2. Add a module-level function `def EXACTLY(n: int) -> CardinalitySpec: return CardinalitySpec(min=n, max=n)`.
3. Add to `CardinalitySpec`:
   ```python
   def resolve_for_pair(
       self, self_props: Mapping[str, object], other_props: Mapping[str, object]
   ) -> "CardinalitySpec":
       """Constant cardinality ignores endpoint properties."""
       return self
   ```
   Import `Mapping` from `collections.abc`.

**Tests (TDD — write first)** — new file `tests/graph_definition/test_cardinality_spec.py`:
- `Cardinality.ZERO.contains(0) is True`; `.contains(1) is False`.
- `EXACTLY(3) == CardinalitySpec(min=3, max=3)`; `EXACTLY(2).contains(2)` true, `.contains(1)` false.
- `CardinalitySpec(min=1, max=2).resolve_for_pair({}, {}) is the same spec`.

**Care / risks:** do not alter `CardinalitySpec._validate_bounds` (it already
permits `min=max=0`). Keep `Cardinality` constants as `ClassVar` to match the
existing four. `EXACTLY` is a free function, not a method, to mirror constant
ergonomics.

---

### E40.2 — `PropMatch` and `ConditionalCardinality` model + resolution

> **Model: Sonnet.** The resolution algorithm (most-specific-wins, ambiguity at resolve time) needs careful, well-named decomposition; it is the semantic core.

**Goal:** a frozen, typed model expressing the rule set and a pure
`resolve_for_pair` that implements most-specific-wins with explicit `default`.

**Operation** — in `src/orthograph/graph_definition/models.py` (new section):
1. `PropMatch(BaseModel)` (frozen):
   - `conditions: Mapping[str, object] = {}` (empty = match-all).
   - `def matches(self, props: Mapping[str, object]) -> bool:` returns
     `all(props.get(k) == v for k, v in self.conditions.items())`.
   - `@property def specificity(self) -> int: return len(self.conditions)`.
   - `@property def is_wildcard(self) -> bool: return not self.conditions`.
2. `ConditionalRule(BaseModel)` (frozen): `source: PropMatch`, `target: PropMatch`, `spec: CardinalitySpec`.
3. `ConditionalCardinality(BaseModel)` (frozen):
   - `rules: tuple[ConditionalRule, ...]`
   - `default: CardinalitySpec` (required — no default value).
   - `def resolve_for_pair(self, self_props, other_props) -> CardinalitySpec:`
     - collect matching rules (`r.source.matches(self_props) and r.target.matches(other_props)`);
     - if none → return `self.default`;
     - compute each match's score `r.source.specificity + r.target.specificity`;
     - if a **single** rule holds the max score → return its `spec`;
     - if **two or more** share the max score → raise `AmbiguousCardinalityError`
       (new exception in `graph_definition/exceptions.py`) with a message naming
       the conflicting predicates. (Definition-time checks in E40.4 prevent this
       from ever firing in a constructed `GraphDefinition`; the guard is
       defence-in-depth.)
   - `@classmethod def by_kind(cls, *, source_prop: str = "kind", target_prop: str = "kind", rules: Mapping[tuple[str, str], CardinalitySpec], default: CardinalitySpec) -> "ConditionalCardinality":` — sugar that normalises `("split", "nothing"): spec` into `ConditionalRule(PropMatch({source_prop: "split"}), PropMatch({target_prop: "nothing"}), spec)`, where the literal `"*"` produces an empty (`match-all`) `PropMatch` on that side.

   Decompose into small named helpers: `_matching_rules(...)`, `_highest_specificity(...)`. Keep `resolve_for_pair` readable as a sequence of these.

**Authoring contract:** `PropMatch` accepts a positional mapping as its primary form — `PropMatch({"kind": "split"})` — via a thin `__init__` override that maps the leading positional argument onto the `conditions` field before delegating to Pydantic's `super().__init__`. The keyword form `PropMatch(conditions={...})` remains valid. This is the **agreed and canonical** call shape for hand-authored rules; any implementation change to `PropMatch.__init__` must preserve both forms. The custom `__init__` is the only viable seam: Pydantic `BaseModel` has no config switch for positional construction.

**Tests (TDD — write first)** — append to `tests/graph_definition/test_cardinality_spec.py`:
- `PropMatch({"kind": "split"}).matches({"kind": "split"})` true; `.matches({"kind": "x"})` false; empty `PropMatch().matches({...})` always true; `.is_wildcard` true.
- specificity: `PropMatch({"a": 1, "b": 2}).specificity == 2`.
- `by_kind` table from ADR-029 resolves correctly: `(subsampling, subsampling) -> 1..2`, `(split, nothing) -> ZERO`, `(combine, nothing) -> ZERO`, unmatched pair `(x, y) -> default`.
- most-specific-wins: rules `("split", "*"): ZERO` and `("split", "nothing"): ONE` → `(split, nothing)` resolves to `ONE` (more specific), `(split, other)` resolves to `ZERO`.
- order independence: build the same two rules in both orders, assert identical resolution.
- ambiguity guard: rules `("split", "*"): A` and `("*", "nothing"): B`, resolving `(split, nothing)` raises `AmbiguousCardinalityError`.

**Care / risks:** `Mapping[str, object]` (not `dict`, not `Any`) for predicate
values to stay strongly typed and frozen. `conditions` must be hashable/frozen for
the model to be frozen — store as a Pydantic model field; if equality/freezing of
`Mapping` is an issue, accept a `dict` field and rely on Pydantic frozen-copy
semantics (verify with a `==` test). Do **not** implement coverage/contradiction
checks here — that is E40.4. `default` has no implicit value.

---

### E40.3 — Widen the relationship field type and the YAML constructor

> **Model: Haiku.** Mechanical type widening + import; small.

**Goal:** `__source_cardinality__` / `__target_cardinality__` accept either a
constant or a conditional spec, with no behaviour change for existing schemas.

**Operation** — in `src/orthograph/graph_definition/models.py`:
1. Change the `ClassVar` annotations on `RelationshipModel`:
   `__source_cardinality__: ClassVar[CardinalitySpec | ConditionalCardinality] = Cardinality.ZERO_OR_MORE` (and target likewise). Default value unchanged.
2. Update the class docstring's two cardinality bullet points to mention the
   conditional option in one sentence each (essential only).

**Tests (TDD — write first)** — append to `tests/graph_definition/test_relationship_model.py`:
- a `RelationshipModel` subclass with a `ConditionalCardinality` source side constructs without error and the ClassVar reads back equal.
- an existing constant-cardinality subclass still constructs (regression).

**Care / risks:** union widening is backward-compatible; confirm mypy is green
across the repo (existing `__source_cardinality__` readers must still type-check —
they will, since they only call `.resolve_for_pair`/`.contains` after E40.5, and
until then read `.min`/`.max` only on constants; do **not** touch those readers in
this task).

---

### E40.4 — Definition-time checklist `standard_cardinality_checks()`

> **Model: Sonnet.** The ambiguity-overlap check requires careful predicate-compatibility reasoning; the pluggable architecture must be clean (SOLID — open for extension).

**Goal:** at `GraphDefinition` construction, every `ConditionalCardinality` is
cross-validated by an **extensible list** of checks; violations raise
`GraphValidationError` (ERROR) as the existing structural checks do.

**Operation:**
1. New module `src/orthograph/graph_definition/cardinality_checks.py`:
   - A `RuleSetCheck` Protocol: `code: str`; `__call__(self, rel_label: str, side: str, card: ConditionalCardinality, self_node: type[NodeModel], other_node: type[NodeModel]) -> Iterable[ValidationIssue]`. (`side` is `"source"`/`"target"`; `self_node` is the discriminated endpoint for that side, `other_node` the opposite — for `__source_cardinality__`, self=source node, other=target node.)
   - Implement as small frozen `@dataclass` classes, each one responsibility (SOLID):
     - `DiscriminatorPropertyExistsCheck` (`CARDINALITY_UNKNOWN_DISCRIMINATOR`): every `source` `PropMatch` key ∈ `self_node.get_all_property_names()`, every `target` key ∈ `other_node.get_all_property_names()`.
     - `DiscriminatorRequiredCheck` (`CARDINALITY_DISCRIMINATOR_OPTIONAL`): every discriminator key is in the relevant node's `get_required_property_names()`. Clear message: `"HAS_OUTPUT source cardinality discriminates on Operation.kind, but kind is optional (nullable); make it required or remove the rule."`
     - `DuplicateRuleKeyCheck` (`CARDINALITY_DUPLICATE_RULE`): no two rules with identical `(source.conditions, target.conditions)`.
     - `AmbiguousOverlapCheck` (`CARDINALITY_AMBIGUOUS_RULES`): for each rule pair, if they can co-match (no conflicting key in either side's predicate) and have equal specificity → ERROR. Implement `_can_comatch(a, b)` and `_same_specificity(a, b)` as named helpers.
     - `ForbiddenCatchAllRuleCheck` (`CARDINALITY_CATCHALL_RULE`): reject a rule whose source and target are both wildcard.
   - `def standard_cardinality_checks() -> list[RuleSetCheck]:` returns the ordered list (mirror `standard_rules()`).
2. In `graph_definition/graph_definition.py`:
   - Add `_check_cardinality_rules(self, result)` invoked from `_check_structure`. For each relationship type, for each side whose cardinality `isinstance(..., ConditionalCardinality)`, resolve `self_node`/`other_node` via `get_node_type(__source_label__/__target_label__)`, then run every check in `standard_cardinality_checks()` and add issues. (Skip a side whose endpoint node type is undefined — the existing `_check_undefined_node_refs` already reports that.)

**Tests (TDD — write first)** — append to `tests/graph_definition/test_graph_definition.py`, one focused test per check:
- valid conditional schema (the ADR-029 table) constructs cleanly.
- unknown discriminator key → `CARDINALITY_UNKNOWN_DISCRIMINATOR` raised.
- optional `kind` discriminator → `CARDINALITY_DISCRIMINATOR_OPTIONAL` raised, message names the property.
- duplicate `(source, target)` predicate → `CARDINALITY_DUPLICATE_RULE`.
- equal-specificity overlap (`("split","*")` & `("*","nothing")`) → `CARDINALITY_AMBIGUOUS_RULES`.
- narrow-overrides-broad (`("split","*")` & `("split","nothing")`) → **no** error (intentional refinement).
- `(*, *)` rule → `CARDINALITY_CATCHALL_RULE`.

**Care / risks:** keep each check a single-responsibility object so E41 / future
overlap checks add a class without touching others (SOLID). `_can_comatch` must
treat a key present on both sides with **different** values as non-co-matching.
Do not flag narrow-overriding-broad. Severities are ERROR now; the design must
allow demotion by changing one field (`severity` on the issue) without structural
change.

---

### E40.5 — In-memory partitioned validation in `GraphValidator`

> **Model: Opus.** This is the highest-reasoning task: it changes the degree counter to a pair axis, threads endpoint properties through the node index, and must keep the constant-spec path byte-identical. Correctness of the partition/missing-partition semantics is subtle.

**Goal:** `GraphValidator.validate` enforces conditional cardinality per node,
partitioned by the opposite endpoint's discriminator, while the constant-spec path
is unchanged.

**Operation** — in `src/orthograph/graph_definition/validation.py`:
1. **Carry endpoint properties.** Change the node index from `dict[str, tuple[str, str]]`
   to a small frozen dataclass `_IndexedNode(label: str, uid: str, props: Mapping[str, object])`.
   Update `_validate_and_index_nodes` to store `props`, and `_check_referential_integrity`
   to read `.label` instead of tuple `[0]`. (Internal type only — no public API change.)
2. **Pair-aware counting.** Add a counter keyed by `(uid, rel_label, other_discriminator_value_tuple)`.
   To know which property(ies) to read on the other endpoint, derive the
   **referenced discriminator keys** for each side from the relationship's
   `ConditionalCardinality` rules (a helper `_referenced_other_keys(card, side)`).
   For a constant spec, no partitioning — keep the existing total-count path.
   Implement `_count_rel_degrees` to additionally produce, **only for
   conditional sides**, `partitioned[(uid, rel_label)][other_key_values] = count`
   using the other endpoint's props from the node index.
3. **Pair-aware check.** In `_check_node_cardinality` / `_cardinality_violation_issue`:
   - constant spec → unchanged single-count path.
   - conditional spec → for each **declared rule** that targets this node's
     discriminator value (plus the observed partitions), compute the partition's
     count (missing = 0), call `card.resolve_for_pair(self_props, other_props)` to
     get the bound, and emit `CARDINALITY_VIOLATION` per violating partition with
     `context={"source_kind": ..., "target_kind": ..., "expected_min/max": ..., "actual": ...}` and a message naming the pair.
   - if the node's own discriminator value matches no rule and no wildcard → emit
     `CARDINALITY_UNMATCHED_KIND` (INFO) **and** apply the **default floor**:
     check the node's total side degree against `card.default` and emit
     `CARDINALITY_VIOLATION` (`context["default"] = True`) when a `min > 0`
     default is unmet (ADR-029 §7 — prevents a silent pass for an edgeless node
     under a `min > 0` default; a permissive `min == 0` default never trips it).
4. Keep `self_props` = the iterated node's props; `other_props` = the opposite
   endpoint's props (from the index). For `__source_cardinality__` the iterated
   node is the source; for `__target_cardinality__`, the target.

   Break the new logic into named helpers (`_partition_counts`, `_check_conditional_side`,
   `_check_constant_side`) so neither function grows large. Readability first.

**Tests (TDD — write first)** — append to `tests/graph_definition/test_validation.py`:
- **The ADR-029 deciding scenario:** one `Operation{kind:subsampling}` with 2 `HAS_OUTPUT` to `Sample{kind:subsampling}` and 1 to `Sample{kind:nothing}`; with `subsampling→subsampling = 1..2` and `default = ZERO_OR_MORE` → **valid**; with `default = ZERO` → the nothing-Sample partition emits one `CARDINALITY_VIOLATION` naming `(subsampling, nothing)`.
- `combine→nothing = EXACTLY(2)` with an Operation having **zero** nothing-outputs → violation (missing partition counted as 0, min unmet).
- `discard` with `("discard","*"): ZERO` and one output → violation.
- unmatched kind (`Operation{kind:lyophilize}`, no rule) → `CARDINALITY_UNMATCHED_KIND` INFO, no ERROR.
- `__target_cardinality__` conditional: a target node partitioned by source kind behaves symmetrically.
- **Regression:** every existing constant-cardinality test in this file still passes unchanged.

**Care / risks:** the constant-spec path must be untouched in behaviour — guard
the new branch on `isinstance(card, ConditionalCardinality)`. The `_IndexedNode`
change touches `_check_referential_integrity`; update **all** tuple-index reads
(grep `node_index[`). `self`/`other` orientation is the classic bug source — add
an explicit comment and a target-side test. Do not regress undirected-relationship
counting (existing `undirected` path). Keep functions small; if a function exceeds
~25 lines, extract a helper.

---

### E40.6 — YAML round-trip for conditional cardinality

> **Model: Sonnet.** Bidirectional grammar with nested maps; needs care that the flat form stays valid and round-trips are exact.

**Goal:** a `ConditionalCardinality` declaration serialises to YAML and parses back
to an equal object; the existing flat `{min, max}` form is unchanged.

**Operation** — in `src/orthograph/io/yaml.py`:
1. `_parse_cardinality(spec)` accepts either:
   - flat `{min, max}` → `CardinalitySpec` (unchanged), or
   - `{conditional: {source_discriminator, target_discriminator, rules: [{when: {source: {...}, target: {...}}, min, max}], default: {min, max}}}` → `ConditionalCardinality`.
   Add a private `_parse_conditional_cardinality(dict) -> ConditionalCardinality` using `PropMatch`/`ConditionalRule`.
2. `_serialize_relationship_type` emits the conditional form when the side
   `isinstance(..., ConditionalCardinality)`, else the existing flat form.
   Add `_serialize_conditional_cardinality(card) -> dict`.

**Tests (TDD — write first)** — append to `tests/io/test_yaml.py`:
- YAML → model: a conditional `HAS_OUTPUT` parses with the correct rules and default.
- round-trip: `model → serialize → parse` yields an equal `ConditionalCardinality` (assert `==`).
- regression: existing flat-cardinality YAML still parses and round-trips.

**Care / risks:** tuple keys are not YAML-native — represent each rule as a list
entry with explicit `source`/`target` maps (never tuple keys in YAML). `check-yaml`
pre-commit hook must pass. Equality assertions depend on E40.2 frozen-model `==`.

---

### E40.7 — Profile comparison: report conditional as `UNVERIFIABLE`

> **Model: Sonnet.** Small, but must branch correctly and not regress constant-spec comparison.

**Goal:** `compare(definition, profile)` on a relationship whose declared side is
`ConditionalCardinality` emits `CARDINALITY_UNVERIFIABLE` (INFO), never a false
comparison against the aggregate `cardinality_stats`.

**Operation** — in `src/orthograph/comparison/rules.py`:
1. In `CardinalityViolationRule.__call__`, before reading `src_card.contains(...)`,
   branch: if `isinstance(rt_class.__source_cardinality__, ConditionalCardinality)`
   → yield one `ValidationIssue(code="CARDINALITY_UNVERIFIABLE", severity=Severity.INFO, ...)`
   with a message stating the live aggregate cannot confirm per-pair bounds (cite
   that E41/ADR-030 delivers per-pair stats). Return without the aggregate check.
2. Constant spec → existing behaviour unchanged.
3. In `comparison/diff_rules.py` `_cardinality_issue_definition`: when either side
   is conditional, compare structurally via `==` (frozen models) and build the
   context without `.min`/`.max` (which conditional specs lack) — emit
   `CARDINALITY_CHANGED` (INFO) describing the rule-set difference.

**Tests (TDD — write first)** — append to `tests/comparison/test_rules.py` and `tests/comparison/test_diff_rules.py`:
- conditional declared side + any profile with `cardinality_stats` → exactly one `CARDINALITY_UNVERIFIABLE` INFO, no `CARDINALITY_VIOLATION`.
- constant declared side → existing comparison codes unchanged (regression).
- diff: two definitions differing only in conditional rules → `CARDINALITY_CHANGED` INFO; identical conditional rules → no issue.

**Care / risks:** do not read `.min`/`.max` on a conditional spec anywhere
(`AttributeError`). Keep the aggregate path for constants exactly as is.

---

### E40.8 — Presentation: text, mermaid, networkx string

> **Model: Haiku.** Three small format branches; mechanical once the shape is known.

**Goal:** rendering a conditional cardinality does not crash and reads sensibly.

**Operation:**
1. `visualization/text.py` and `visualization/mermaid.py` `_format_cardinality`:
   accept `CardinalitySpec | ConditionalCardinality`; for conditional, render a
   compact summary, e.g. `kind:{(subsampling,subsampling):1..2; (split,nothing):0..0; default:0..*}`.
   Extract a `_format_conditional(card) -> str` helper.
2. `backends/networkx/conversion.py:40-41` does `str(rt.__source_cardinality__)`;
   add a `__str__`/`__repr__` to `ConditionalCardinality` so it stringifies
   cleanly (no crash).

**Tests (TDD — write first)** — append to `tests/visualization/test_text.py`, `tests/visualization/test_mermaid.py`, `tests/backends/networkx/test_conversion.py`:
- a model with a conditional side renders a string containing the discriminator and at least one rule bound; no exception.
- constant-cardinality rendering unchanged (regression).

**Care / risks:** keep the summary readable and bounded (do not dump huge rule
lists); truncate gracefully if needed but keep it deterministic for test assertions.

---

### E40.9 — Public exports, notebook, ADR cross-link, overview

> **Model: Sonnet.** Prose + a runnable notebook section + planning index hygiene.

**Operation:**
1. Export `ConditionalCardinality`, `PropMatch`, and `ConditionalRule` from
   wherever `CardinalitySpec` is publicly re-exported (match the existing pattern
   in `graph_definition` and any top-level `orthograph` surface used by
   tests/notebooks).
   **Do NOT publicly export `EXACTLY` or the `Cardinality.*` constants.** These
   are slated for removal by **E42** (Unify Cardinality on UML Notation), which
   replaces the named-constant / `EXACTLY` authoring forms with parsed UML
   notation on `CardinalitySpec`. Publishing them here would create a public API
   that E42 must immediately walk back. They remain usable internally (and in
   this epic's own tests) until E42 deletes them. If the notebook needs a
   constant or an exact count, author it as `CardinalitySpec(min=…, max=…)` so no
   notebook cell depends on a symbol E42 removes.
2. Add a notebook section to the cardinality notebook
   (`notebooks/01.04_optionality_and_cardinality.ipynb`): declare the `Operation`
   `HAS_OUTPUT` conditional model, validate the deciding-scenario data, show a
   caught violation and the `UNVERIFIABLE` profile finding.
3. Confirm ADR-029 cross-references resolve; add E40 row to `.agentic/planning/overview.md`
   (table + Active list + dependency note: blocks E41).

**Tests / verify:**
```
pwsh> python -m pytest --nbval-lax notebooks/01.04_optionality_and_cardinality.ipynb -q
pwsh> python -m pytest -q
pwsh> python -m mypy src/orthograph
```

**Care / risks:** keep notebook cells deterministic (no DB). Ensure the full suite
is green — this task is the integration gate for the epic.

---

## Success Criteria

- [ ] `Cardinality.ZERO`, `EXACTLY`, and `CardinalitySpec.resolve_for_pair` exist and are tested. *(Note: `Cardinality.*` and `EXACTLY` stay **internal-only** — not publicly exported per E40.9 — and are scheduled for removal by **E42**, which replaces them with parsed UML notation on `CardinalitySpec`.)*
- [ ] `ConditionalCardinality` resolves most-specific-wins, order-independent, with required `default`; ambiguity guard raises.
- [ ] Relationship fields accept `CardinalitySpec | ConditionalCardinality`; existing schemas unchanged (mypy green).
- [ ] `standard_cardinality_checks()` runs at construction; all five checks tested; narrow-overrides-broad is allowed.
- [ ] `GraphValidator.validate` enforces per-pair bounds (deciding scenario green); missing partition counted as 0; unmatched kind → INFO; constant path regression-green.
- [ ] YAML round-trip exact for conditional and flat forms.
- [ ] `compare` reports conditional as `CARDINALITY_UNVERIFIABLE` (INFO); constant comparison unchanged.
- [ ] Rendering conditional cardinality does not crash; constant rendering unchanged.
- [ ] Exports, notebook, ADR cross-links, overview updated; full suite + mypy + pre-commit green.

---

## Out of Scope (→ E41)

- Per-pair **observed** statistics and live-DB enforcement (ADR-030).
- Grouped inspection Cypher and the `partitioned_cardinality` profile field.
- Multi-property discriminators beyond what the model already supports for resolution (the model permits them; profiling them is E41).
- Demoting any ERROR check to WARNING (revisit after pilot feedback).
- The `UnlistedPolicy` extension of `default` (seam reserved; not built).
