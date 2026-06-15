# Epic E27: Symmetric Comparison — Compare Any Two Graph Descriptions

> **Priority:** Medium
> **Origin:** Design session 2026-06-13 (extend `comparison/` beyond profile↔definition)
> **Goal:** Let the comparison engine compare **any two operands** over the shared
> address space: profile↔definition (existing), profile↔profile (new), and
> definition↔definition (new), sharing one walker and one `RuleContext`.
> **Blocked by:** none (touches `comparison/` and its call sites only)
> **User stories:** 7 tasks, execute in order T1 → T7.

---

## Context

`src/orthograph/comparison/` reconciles the **declared** side (`GraphDefinition`)
against the **observed** side (`GraphProfile`). The public entry point today is
`compare(profile, graph_definition, rules=None) -> ValidationResult` in
`engine.py`. Internally it is already a **two-sided address walker**: it enumerates
a shared address space in five passes (node labels, rel types, node properties,
rel properties, endpoint/cardinality), builds a `RuleContext` per address, and runs
every rule. Each rule is self-selecting: it inspects `context.declared` /
`context.observed` and `context.extra`, and returns early when the address is not
its concern.

The only thing hard-wired to one direction is:
1. `RuleContext` field names (`graph_definition`/`profile`, `declared`/`observed`).
2. How each operand is **destructured** into labels/types/properties.
3. The standard rule set, which encodes asymmetric declared-vs-observed judgement
   (required/optional, completeness, cardinality bounds).

This epic introduces a `GraphView` adapter so the engine walks **two views** of the
shared address space rather than one profile + one definition. The existing
comparison keeps its exact behaviour and codes; the two new comparisons use a
separate **symmetric diff** rule family that emits neutral `INFO` differences.

**Two questions, two rule families (decided — do not collapse into one):**

| Comparison | Question | Rule family |
|---|---|---|
| profile ↔ definition | "Does observed satisfy declared?" | `standard_rules()` (existing, asymmetric) |
| profile ↔ profile | "What differs?" | `diff_rules()` (new, symmetric) |
| definition ↔ definition | "What differs?" | `diff_rules()` (new, symmetric) |

The satisfaction family **cannot** be reduced to a diff: required-vs-optional,
completeness, and cardinality bounds only exist on the declared side. Keep both.

**Decisions locked in this epic (do not re-litigate):**
- **No backward compatibility.** `compare` is renamed to
  `compare_profile_to_definition`. `RuleContext` fields are renamed to neutral
  `left_graph`/`right_graph` and `left`/`right`. No alias shims.
- **No re-exports** added to `comparison/__init__.py` for the new functions — they
  are imported from `orthograph.comparison.engine` directly, matching today's style.
- **Diff issues are `INFO`** and distinguish `*_ONLY_IN_LEFT` from `*_ONLY_IN_RIGHT`.
- **`RuleContext` keeps reach-back** to both operands as `left_graph`/`right_graph`
  typed `GraphView` (no current rule uses them, but the capability survives in
  neutral form).

---

## Reference: target architecture

```
src/orthograph/comparison/
├── __init__.py          # docstring updated only; NO new re-exports
├── views.py             # NEW — GraphView Protocol + DefinitionView + ProfileView
├── engine.py            # CHANGED — _compare_views() walker + 3 public functions
├── rules.py             # CHANGED — RuleContext neutralised; satisfaction rules renamed reads
└── diff_rules.py        # NEW — symmetric diff rule family + diff_rules() factory
```

Target public API in `engine.py`:

```python
def compare_profile_to_definition(profile, graph_definition, rules=None) -> ValidationResult  # was compare()
def compare_profiles(left: GraphProfile, right: GraphProfile, rules=None) -> ValidationResult  # new
def compare_definitions(left: GraphDefinition, right: GraphDefinition, rules=None) -> ValidationResult  # new
```

Each is a thin wrapper: build two `GraphView`s, choose a default rule set, call the
private `_compare_views(left_graph, right_graph, rules)`.

---

## Tasks

### E27.T1: Add `GraphView` Protocol and two adapters (`comparison/views.py`)

Create a new file `src/orthograph/comparison/views.py`. This is the **single place**
that knows how each operand destructures onto the shared address space. No model is
modified; the views only read existing attributes.

Define a `runtime_checkable` `Protocol`:

```python
class GraphView(Protocol):
    """A read-only projection of one comparison operand onto the shared address space."""
    def node_labels(self) -> set[str]: ...
    def relationship_types(self) -> set[str]: ...
    def node_at(self, label: str) -> Any | None: ...           # side-object for a node-label address
    def relationship_at(self, rel_type: str) -> Any | None: ...# side-object for a rel-type address
    def node_properties(self, label: str) -> dict[str, Any]: ...        # prop_name -> side-object
    def relationship_properties(self, rel_type: str) -> dict[str, Any]: ...
```

Implement two adapters (plain classes wrapping one operand each):

- `DefinitionView(graph_definition: GraphDefinition)`:
  - `node_labels()` → `graph_definition.node_labels`
  - `relationship_types()` → `graph_definition.relationship_labels`
  - `node_at(label)` → `graph_definition.get_node_type(label)` (the `NodeModel`
    subclass, or `None`)
  - `relationship_at(rel_type)` → `graph_definition.get_relationship_type(rel_type)`
    (the `RelationshipModel` subclass, or `None`)
  - `node_properties(label)` / `relationship_properties(rel_type)` →
    `model_type.get_property_specs()` (a `dict[str, TypeInfo]`) for the matching
    model type, or `{}` if the type is absent.
- `ProfileView(profile: GraphProfile)`:
  - `node_labels()` → `profile.node_labels`
  - `relationship_types()` → `profile.relationship_types`
  - `node_at(label)` → `profile.node_type_profiles.get(label)` (a `NodeTypeProfile`)
  - `relationship_at(rel_type)` → `profile.rel_type_profiles.get(rel_type)` (a
    `RelationshipTypeProfile`)
  - `node_properties(label)` → that node profile's `property_profiles` dict, or `{}`
  - `relationship_properties(rel_type)` → that rel profile's `property_profiles`
    dict, or `{}`

Move the `_HasPropertySpecs` Protocol from `engine.py` into `views.py` (it belongs
with `DefinitionView`). Do not import any backend.

**Acceptance criteria:**
- [x] `src/orthograph/comparison/views.py` exists with `GraphView`, `DefinitionView`,
      `ProfileView`.
- [x] `DefinitionView` and `ProfileView` satisfy `isinstance(view, GraphView)`
      (runtime-checkable Protocol).
- [x] No backend (`neo4j`/`memgraph`/`networkx`/`gqlalchemy`) is imported.
- [x] `mypy`/type-check passes for the new module.

---

### E27.T2: Neutralise `RuleContext` and rename satisfaction-rule field reads (`comparison/rules.py`)

In `src/orthograph/comparison/rules.py`:

1. Change `RuleContext` fields:
   - `graph_definition: GraphDefinition` → `left_graph: GraphView`
   - `profile: GraphProfile` → `right_graph: GraphView`
   - `declared: Any` → `left: Any`
   - `observed: Any` → `right: Any`
   - Keep `address: str` and `extra: dict[str, Any]` as-is.
   - Update the import: drop `GraphDefinition`/`GraphProfile`, import `GraphView`
     from `orthograph.comparison.views`.
   - Update the class docstring to describe `left`/`right` neutrally; note that for
     `compare_profile_to_definition` the convention is **left = declared
     (definition), right = observed (profile)**, which is what the satisfaction
     rules below assume.
2. In every existing rule's `__call__`, rename the reads:
   - `context.declared` → `context.left`
   - `context.observed` → `context.right`
   This is a pure rename; **no logic or emitted code/severity changes.** Affected
   rules: `MissingNodeLabelRule`, `UnexpectedNodeLabelRule`, `MissingRelTypeRule`,
   `UnexpectedRelTypeRule`, `MissingPropertyRule`, `UnexpectedPropertyRule`,
   `PropertyIncompleteRule`, `PropertyTypeMismatchRule`, `InvalidEndpointRule`,
   `CardinalityViolationRule`, and `PropertyDistinctCountRule`.
3. Leave `Rule` (Protocol) and `standard_rules()` unchanged.

> Cross-file note: `engine.py` and the tests in T6/T7 must be updated in the same
> change window or the suite will not import. T2 leaves the repo temporarily
> red until T3 lands — execute T2 and T3 back-to-back.

**Acceptance criteria:**
- [x] `RuleContext` has fields `left_graph`, `right_graph`, `address`, `left`,
      `right`, `extra` and no `declared`/`observed`/`graph_definition`/`profile`.
- [x] All eleven rules read `context.left`/`context.right`; emitted `code` and
      `severity` values are byte-for-byte unchanged.
- [x] `standard_rules()` returns the same ten rules in the same order.

---

### E27.T3: Generalise the engine to a two-view walker + three entry points (`comparison/engine.py`)

In `src/orthograph/comparison/engine.py`:

1. Keep `_DB_TYPE_MAP` and `db_type_to_python` exactly where they are.
2. Remove the `_HasPropertySpecs` Protocol (moved to `views.py` in T1).
3. Extract the body of the current `compare` into a **private** walker:

   ```python
   def _compare_views(
       left_graph: GraphView,
       right_graph: GraphView,
       rules: Sequence[Rule],
   ) -> ValidationResult:
   ```

   Rewrite the five passes to read from the two views instead of `profile` /
   `graph_definition`:
   - **Node labels:** iterate `left_graph.node_labels() | right_graph.node_labels()`.
     For each label set `left = left_graph.node_at(label)` and
     `right = right_graph.node_at(label)`; build the `RuleContext` and apply rules.
   - **Rel types:** same shape using `relationship_types()` and `relationship_at()`.
   - **Node properties:** for each label in the union, take
     `left_props = left_graph.node_properties(label)` and
     `right_props = right_graph.node_properties(label)`; for each `prop_name` in
     `set(left_props) | set(right_props)` build a property `RuleContext` with
     `extra = {"label": label, "prop_name": prop_name, "entity_type": EntityType.NODE}`,
     `left = left_props.get(prop_name)`, `right = right_props.get(prop_name)`,
     `address = f"{label}.{prop_name}"`.
   - **Rel properties:** same shape with `EntityType.RELATIONSHIP`.
   - **Endpoint/cardinality:** for each rel type present in **both** views, build a
     `RuleContext(address=rel_type, left=left_graph.relationship_at(rel_type),
     right=right_graph.relationship_at(rel_type))`. (The satisfaction
     `InvalidEndpointRule`/`CardinalityViolationRule` already guard on operand type,
     so they no-op when the sides are not a model+profile pair.)

   This generalisation must be **address-symmetric** — the union iteration replaces
   the current "declared − observed" / "observed − declared" split, and the rules
   decide what to emit. Verify the existing test suite still passes (T6) to confirm
   no behavioural drift.

4. Replace the public `compare` with three thin wrappers:

   ```python
   def compare_profile_to_definition(
       profile: GraphProfile,
       graph_definition: GraphDefinition,
       rules: Sequence[Rule] | None = None,
   ) -> ValidationResult:
       active = rules if rules is not None else standard_rules()
       return _compare_views(DefinitionView(graph_definition), ProfileView(profile), active)

   def compare_profiles(
       left: GraphProfile, right: GraphProfile, rules: Sequence[Rule] | None = None,
   ) -> ValidationResult:
       active = rules if rules is not None else diff_rules()
       return _compare_views(ProfileView(left), ProfileView(right), active)

   def compare_definitions(
       left: GraphDefinition, right: GraphDefinition, rules: Sequence[Rule] | None = None,
   ) -> ValidationResult:
       active = rules if rules is not None else diff_rules()
       return _compare_views(DefinitionView(left), DefinitionView(right), active)
   ```

   - `compare_profile_to_definition` MUST map **definition → `left_graph`** and
     **profile → `right_graph`** so the satisfaction rules (which now read
     `left`=declared, `right`=observed) keep their exact current behaviour.
   - Import `DefinitionView`, `ProfileView` from `.views` and `diff_rules` from
     `.diff_rules` (created in T4).

5. Update the module docstring to mention all three comparisons.
6. Do **not** add re-exports to `comparison/__init__.py`; update only its docstring
   to mention the three functions live in `engine.py`.

**Acceptance criteria:**
- [x] `compare` no longer exists; `compare_profile_to_definition`,
      `compare_profiles`, `compare_definitions` exist with the signatures above.
- [x] `_compare_views` is the only place containing the five-pass loop.
- [x] `_HasPropertySpecs` no longer defined in `engine.py`.
- [x] `comparison/__init__.py` has no new symbol re-exports (docstring may change).

---

### E27.T4: Add the symmetric diff rule family (`comparison/diff_rules.py`)

Create `src/orthograph/comparison/diff_rules.py`. Each rule implements the existing
`Rule` Protocol (has a `key`, is callable `RuleContext -> Iterable[ValidationIssue]`),
reads `context.left`/`context.right` **symmetrically**, and emits `Severity.INFO`
`ValidationIssue`s. Self-selection guards mirror the satisfaction rules (check
`extra` for `prop_name`, check operand types where relevant).

Rules and codes:

| Rule class | `key` | Code | Fires when |
|---|---|---|---|
| `NodeLabelOnlyInLeftRule` | `diff.node_label.only_in_left` | `NODE_LABEL_ONLY_IN_LEFT` | node-label address, `left is not None and right is None` |
| `NodeLabelOnlyInRightRule` | `diff.node_label.only_in_right` | `NODE_LABEL_ONLY_IN_RIGHT` | node-label address, `right is not None and left is None` |
| `RelTypeOnlyInLeftRule` | `diff.rel_type.only_in_left` | `REL_TYPE_ONLY_IN_LEFT` | rel-type address, left-only |
| `RelTypeOnlyInRightRule` | `diff.rel_type.only_in_right` | `REL_TYPE_ONLY_IN_RIGHT` | rel-type address, right-only |
| `PropertyOnlyInLeftRule` | `diff.property.only_in_left` | `PROPERTY_ONLY_IN_LEFT` | property address (`prop_name` in `extra`), left-only |
| `PropertyOnlyInRightRule` | `diff.property.only_in_right` | `PROPERTY_ONLY_IN_RIGHT` | property address, right-only |
| `PropertyTypeChangedRule` | `diff.property.type_changed` | `PROPERTY_TYPE_CHANGED` | property address, both sides present, type descriptors differ |
| `EndpointsChangedRule` | `diff.rel.endpoints_changed` | `ENDPOINTS_CHANGED` | rel-type address, both sides present, source/target label sets differ |
| `CardinalityChangedRule` | `diff.rel.cardinality_changed` | `CARDINALITY_CHANGED` | rel-type address, both sides present, observed cardinality differs |

Detailed rules for the "changed" cases (must handle both operand shapes because a
diff runs over either two profiles or two definitions):

- `PropertyTypeChangedRule`: derive a comparable **type descriptor** from each side:
  - If the side is a `TypeInfo` (definition↔definition) → use `python_type`.
  - If the side is a `PropertyProfile` (profile↔profile) → use the sorted
    `observed_types` list mapped through `db_type_to_python` where possible (compare
    the resulting set of Python types; fall back to raw `observed_types` when a type
    string is unmapped).
  - Emit only when the two descriptors are non-empty and differ. Put both
    descriptors in `issue.context` as `{"left": ..., "right": ...}`.
  - If the two sides are of mixed shape (a `TypeInfo` vs a `PropertyProfile`), do
    not fire — that combination only arises in `compare_profile_to_definition`,
    which uses `standard_rules()`, not `diff_rules()`.
- `EndpointsChangedRule`: only when both sides are `RelationshipTypeProfile`
  (profile↔profile) compare `source_labels`/`target_labels`; when both sides are
  `RelationshipModel` subclasses (definition↔definition) compare
  `__source_label__`/`__target_label__` (and `__directed__`). Emit one issue per
  changed role, mirroring `InvalidEndpointRule`'s context shape
  (`{"role": ..., "left": ..., "right": ...}`).
- `CardinalityChangedRule`: when both sides are `RelationshipTypeProfile` with
  non-`None` `cardinality_stats`, compare `min_degree`/`max_degree`; when both sides
  are `RelationshipModel` subclasses compare `__source_cardinality__`. Emit only on
  difference; skip when either side lacks the data.

Add the factory:

```python
def diff_rules() -> list[Rule]:
    return [
        NodeLabelOnlyInLeftRule(),
        NodeLabelOnlyInRightRule(),
        RelTypeOnlyInLeftRule(),
        RelTypeOnlyInRightRule(),
        PropertyOnlyInLeftRule(),
        PropertyOnlyInRightRule(),
        PropertyTypeChangedRule(),
        EndpointsChangedRule(),
        CardinalityChangedRule(),
    ]
```

All emitted issues use `Severity.INFO`; `entity_id` follows the existing
conventions (label, rel type, or `f"{label}.{prop_name}"`). Messages name the side
("present in left but not right", "left … right …").

**Acceptance criteria:**
- [x] `src/orthograph/comparison/diff_rules.py` exists with the nine rules and
      `diff_rules()`.
- [x] Every diff rule emits only `Severity.INFO`.
- [x] Each rule no-ops (returns nothing) for addresses outside its concern, mirroring
      the guard style in `rules.py`.
- [x] `diff_rules()` returns the nine rules in the order above.

---

### E27.T5: Update the four production call sites of `compare(`

Rename the call (no behaviour change) in:
- `src/orthograph/cypher/validation.py` — line ~10 import and line ~83 call:
  `from orthograph.comparison.engine import compare` →
  `... import compare_profile_to_definition`; `compare(profile, graph_definition,
  rules=rules)` → `compare_profile_to_definition(profile, graph_definition,
  rules=rules)`.
- `src/orthograph/backends/neo4j/inspector.py` — line ~17 import and line ~212 call.
- `src/orthograph/backends/memgraph/inspector.py` — line ~25 import and line ~161
  call.
- `src/orthograph/api/database.py` — line ~19 import and line ~55 call
  (`compare(profile=profile, graph_definition=graph_definition, rules=rules)`).

`src/orthograph/api/model.py` only imports `Rule` from `comparison.rules` — **no
change** (the `Rule` Protocol is unchanged).

**Acceptance criteria:**
- [x] No `from orthograph.comparison.engine import compare` (the bare name) remains
      in `src/`.
- [x] All four files import and call `compare_profile_to_definition`.
- [x] `api/model.py` is unchanged.

---

### E27.T6: Update existing comparison + api tests to the new names

Rename in tests (no new behaviour asserted; these prove no regression):
- `tests/comparison/test_engine.py`: rename the import and all `compare(` call sites
  (~lines 84, 99, 111, 126, 138, 156, 176, 196, 215, 233, 258, 269, 302, 372, 442)
  to `compare_profile_to_definition(`. Update the module docstring mention.
- `tests/comparison/test_rules.py`: the `_ctx` helper and all `RuleContext(...)`
  constructions use `graph_definition=`, `profile=`, `declared=`, `observed=`.
  Replace with `left_graph=`, `right_graph=`, `left=`, `right=`. Where a raw
  `GraphProfile`/`GraphDefinition` is passed (e.g. `_MODEL`, `_PROFILE`), wrap it in
  the matching view: `left_graph=DefinitionView(_MODEL)`,
  `right_graph=ProfileView(_PROFILE)`. Field-access assertions (`ctx.declared`,
  `ctx.observed`) become `ctx.left`, `ctx.right`. The standard rules under test
  assume **left=declared, right=observed**, so map accordingly.
- `tests/api/test_database.py`: the inline `RuleContext` constructions (~lines
  279–358) get the same field rename; the `compare(` calls (~lines 303, 358) become
  `compare_profile_to_definition(`.
- `tests/test_integration.py` line ~244 and
  `tests/cypher/test_validate_query_catalogue_against_profile.py` docstring mention:
  rename the call/reference.

**Acceptance criteria:**
- [x] `pytest tests/comparison tests/api tests/cypher tests/test_integration.py`
      passes.
- [x] No reference to the bare `compare` engine function remains in `tests/`.
- [x] All `RuleContext` constructions in tests use the new field names and pass
      `GraphView` instances for `left_graph`/`right_graph`.

---

### E27.T7: Add tests for views, diff rules, and the two new comparisons

Add three new test modules under `tests/comparison/` (reuse the `filmography_model`
fixture from `conftest.py` and the `_complete_profile` helper pattern from
`test_engine.py`; copy or factor the helper as convenient — do not over-engineer):

- `tests/comparison/test_views.py`:
  - `DefinitionView` and `ProfileView` return the expected label/type sets,
    side-objects, and property dicts for `filmography_model` and a matching profile.
  - `isinstance(view, GraphView)` holds for both.
  - Absent labels/types return `None`; absent property dicts return `{}`.
- `tests/comparison/test_diff_rules.py`: one focused test per diff rule, constructing
  a `RuleContext` directly (mirroring `test_rules.py` style) and asserting the
  emitted code/severity. Cover: only-in-left, only-in-right (node label, rel type,
  property), `PROPERTY_TYPE_CHANGED` for both the `TypeInfo` and `PropertyProfile`
  shapes, `ENDPOINTS_CHANGED`, `CARDINALITY_CHANGED`, and the no-op guards.
- `tests/comparison/test_compare_peers.py`: end-to-end through `compare_profiles`
  and `compare_definitions`:
  - Identical operands → `result.issues == []` and `result.is_valid is True`.
  - A label/type/property present only on one side → the matching
    `*_ONLY_IN_LEFT` / `*_ONLY_IN_RIGHT` `INFO` issue appears.
  - A changed property type / endpoints / cardinality → the matching `*_CHANGED`
    issue appears.
  - Diff results never contain `Severity.ERROR` (so `is_valid` stays `True`).

**Acceptance criteria:**
- [x] `tests/comparison/test_views.py`, `test_diff_rules.py`, `test_compare_peers.py`
      exist and pass.
- [x] `compare_profiles`/`compare_definitions` on identical operands emit zero issues.
- [x] Each diff code has at least one test asserting it is emitted at `INFO`.
- [x] Full suite green: `pytest tests/comparison` and the repo's standard
      lint/type-check command both pass.

---

## Verification protocol (run after every task)

Each task is not done until all three gates are green **in this order**:

1. **Tests** — `pytest tests/comparison/` (add `tests/api tests/cypher
   tests/test_integration.py` when those call sites change in T5/T6):
   ```
   python -m pytest tests/comparison/ -v
   ```
   Every new behaviour must be covered by a test written **before or alongside**
   the implementation (TDD red → green). Tests for the new code live in
   `tests/comparison/` following the existing file-per-module convention
   (`test_views.py`, `test_diff_rules.py`, `test_compare_peers.py`).

2. **Type-check** — mypy on the changed modules:
   ```
   python -m mypy src/orthograph/comparison/ --ignore-missing-imports
   ```

3. **Pre-commit** — all hooks (ruff lint + format, whitespace, yaml, large files):
   ```
   python -m pre_commit run --all-files
   ```

All three must pass before the task acceptance criteria are ticked off.

---

## Definition of Done (epic)

- [x] `comparison/views.py` and `comparison/diff_rules.py` exist; `engine.py` and
      `rules.py` are generalised as described.
- [x] Three public functions: `compare_profile_to_definition` (renamed, behaviour
      identical), `compare_profiles`, `compare_definitions`.
- [x] All production call sites and tests use the new names; no bare `compare`
      remains in `src/` or `tests/`.
- [x] Existing satisfaction-comparison behaviour, codes, and severities are
      unchanged (proved by the migrated `test_engine.py`/`test_rules.py`).
- [x] New peer comparisons emit only `INFO` diff issues and distinguish left/right.
- [x] CONTEXT.md routing row for "How does comparison work?" updated to mention the
      three comparison functions and the `views.py`/`diff_rules.py` split (see
      "Docs" below).
- [x] Verification protocol (tests → mypy → pre-commit) passes clean for every
      task before it is marked complete.

---

## Docs touch-point (do as part of T7 or a final step)

Update the CONTEXT.md routing row:

> | How does comparison work? How do I add a new validation rule? |
> `src/orthograph/comparison/engine.py` (engine: `compare_profile_to_definition`,
> `compare_profiles`, `compare_definitions`) +
> `src/orthograph/comparison/views.py` (`GraphView` adapters) +
> `src/orthograph/comparison/rules.py` (satisfaction rules) +
> `src/orthograph/comparison/diff_rules.py` (symmetric diff rules) + ADR-015 |

Do not duplicate content elsewhere — CONTEXT.md is a routing table only.
