# Epic E50: Endpoint-Aware Relationship Identity

> **Priority:** High (correctness — the observed side silently blends distinct
>   `(source, label, target)` shapes today; the declared side rejects them outright;
>   ADR-015's mirror cannot hold)
> **Phase:** v0.1.0 / pre-pilot
> **Type:** Breaking identity change (no external consumers yet) across **4 subsystems +
>   the YAML format**
> **Decisions:** **ADR-037** (read it first — it is the spec) · supersedes the identity
>   implication of **ADR-014** · amends **ADR-015** (shared address space) · amends
>   **ADR-034 §7/§8** (endpoint rows → presence rows) · relates **ADR-030/ADR-032**
>   (partition keys nest under identity) · **ADR-009** (inspector parity) · **ADR-017** (topology)
> **Rubric (every task judged against this):** strongly-typed · SOLID · readability over
>   cleverness · backend parity mandatory · **same `(src,rel,tgt)` still collapses** ·
>   **different endpoints are different types** · `None`/honesty preserved · each task ends
>   green with guardrails run

---

## Why This Epic Exists

Relationship-type **identity is the bare label** everywhere:
`GraphProfile.rel_type_profiles[label]`, `GraphDefinition._rel_type_map[__label__]`, the
comparison address space (a flat union of label strings), and the YAML `relationship_types:`
mapping keyed by label.

This produces a silent correctness defect on the **observed** side: all three inspectors
group edges by bare label and **merge** the distinct endpoint node-labels into two
`set[str]` fields. A graph with both `Person-KNOWS->Person` and `Company-KNOWS->Company`
yields **one** `RelationshipTypeProfile(rel_type="KNOWS")` whose `count`,
`cardinality_stats`, and `property_profiles` are **blended across two different shapes** —
and aggregate cardinality bound checks then run against blended statistics. The **declared**
side has the mirror-image problem: it rejects two same-label types outright
(`DUPLICATE_RELATIONSHIP_LABEL`), which is the *opposite* of what a real graph DB permits
(Neo4j allows one rel type between many label pairs).

This epic makes **identity the triple `(source_label, label, target_label)`**: same-triple
edges still collapse (the desired aggregation), different endpoints become distinct types.
See **ADR-037** for the full spec. No external consumers exist, so the change is taken as a
single breaking pass rather than a compatibility shim over a wrong identity model.

---

## Decisions Already Made (do not re-litigate — see ADR-037)

- **Identity = `(source_label, label, target_label)`.** `__directed__` stays an **attribute**,
  not identity.
- **Key encoding = deterministic composite string `"source:LABEL:target"`** via a shared
  `RelTypeKey` model. The `:` delimiter is safe (labels match
  `^[A-Za-z_][A-Za-z0-9_]*$`); mirrors the existing `PartitionKey` convention. Consumers
  recover parts via `RelTypeKey.parse`, never ad-hoc splitting.
- **Endpoint mismatch reclassifies to presence findings**: delete `InvalidEndpointRule`;
  an endpoint difference becomes `MISSING_*` / `UNEXPECTED_*`. Trim `ENDPOINTS_CHANGED` to
  the **`__directed__`-flag** delta only.
- **Profile carries scalar endpoints** (`source_label`/`target_label`), not the
  `source_labels`/`target_labels` sets.
- **Declared side** allows same-label/different-endpoint, rejects identical triple
  (`DUPLICATE_RELATIONSHIP_TYPE`); `get_relationship_type` gains endpoints;
  `get_relationship_types_by_label` is added.
- **YAML `relationship_types:` becomes a list** of `{label, source, target, ...}` objects
  (breaking; mapping form cannot hold two same-label keys).
- **Full breaking change, all 4 subsystems + YAML, one pass.**

---

## Existing Code to Reuse / Touch

| Need | Reuse / Touch | Location |
|------|---------------|----------|
| Key convention to mirror | `PartitionKey` (`src=…|tgt=…`) | `graph_profile/models.py` |
| Identifier grammar (delimiter safety) | `validate_identifier`, `_SAFE_IDENTIFIER` | `cypher/identifiers.py` |
| Profile models | `RelationshipTypeProfile`, `GraphProfile.rel_type_profiles`, `relationship_types` | `graph_profile/models.py` |
| Declaration | `_rel_type_map`, `get_relationship_type`, `relationship_labels`, `_check_duplicate_labels`, `get_relationship_label_enum` | `graph_definition/graph_definition.py` |
| YAML format | `_build_model`, `_build_rel_class`, `_serialize_model` | `io/yaml.py` |
| NetworkX reference inspector | `_inspect_relationships` (group by `__label__`) | `backends/networkx/inspector.py` |
| Neo4j / Memgraph inspectors | `_build_rel_profile(s)`, endpoint enrichment | `backends/{neo4j,memgraph}/inspector.py`, `graph_profile/inspection.py` |
| Shared / vendor queries | `InspectEndpointLabelsQuery`, `CardinalityIdentifiers`, `RelTypeIdentifiers` | `graph_profile/queries/shared.py`, `backends/{neo4j,memgraph}/queries.py` |
| Comparison | engine walk, `GraphView` adapters, satisfaction rules, diff rules | `comparison/{engine,views,rules,diff_rules}.py` |
| Cypher tool | `get_relationship_type` consumers | `cypher/parser.py`, `cypher/generator.py` |
| Rendering | profile/definition rel-type rendering | `visualization/{text,mermaid}.py` |

---

## Per-Task Guardrails (apply to EVERY task unless stated)

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

Reshaped models must round-trip through `model_dump` / `model_validate`. Live-DB tests are
opt-in (`--neo4j` / `--memgraph`); default-suite tests use mocked drivers /
`FakeGraphSession` and the in-memory NetworkX backend.

---

## Tasks (execute in order; each ends green)

### E50.0 — ADR-037: relationship identity includes endpoints

> **Model: Opus.** Decision-only, no production code. The irreversible identity spec every
> later task cites; getting the reclassification and amendments right is the whole point.

**Goal:** ADR-037 exists and is Accepted, defining the identity triple, the `RelTypeKey`
encoding contract, the endpoint reclassification, and the amendments to ADR-014/015/034.

**Operation:** Write `.agentic/decisions/037-relationship-identity-includes-endpoints.md`
per the plan: identity = `(source_label, label, target_label)`; `__directed__` is an
attribute; `RelTypeKey` string encoding `"src:LABEL:tgt"`; endpoint mismatch → presence
findings; YAML mapping → list; amend ADR-015 §address-space and ADR-034 §7/§8.

**Done when:** ADR written, status Accepted, cross-references in place. *(No code, no tests.)*

---

### E50.1 — Shared `RelTypeKey` identity primitive

> **Model: Opus.** The single source of truth for identity encoding/decoding; every dict
> key and comparison address depends on it being obviously correct and round-trip-safe.

**Goal:** `RelTypeKey(source_label, label, target_label)` exists with a deterministic
`__str__` and a `parse` inverse.

**Operation** — in `graph_profile/models.py` (next to `PartitionKey`):
1. Add the frozen `RelTypeKey` model; `__str__` → `"source:LABEL:target"`; classmethod
   `parse(key: str) -> RelTypeKey` (split on the two delimiters; reject malformed input).
2. Document the delimiter-safety invariant (labels match `^[A-Za-z_][A-Za-z0-9_]*$`, so `:`
   never appears inside a part) referencing `cypher/identifiers.py`.

**Tests (TDD — write first)** — `tests/graph_profile/test_models.py`:
- `str(RelTypeKey(...))` is the expected `src:LABEL:tgt` form and is stable.
- `RelTypeKey.parse(str(k)) == k` round-trips for representative triples.
- malformed input (wrong delimiter count) raises.

**Care / risks:** keep `parse` strict — a wrong split silently mis-identifies a type. Do
not allow empty parts.

---

### E50.2 — Declaration: re-key by triple, invert duplicate guard, public API

> **Model: Opus.** Public API signature change (`get_relationship_type`) plus inversion of a
> structural guard (`DUPLICATE_RELATIONSHIP_LABEL` → `DUPLICATE_RELATIONSHIP_TYPE`).
> Correctness-critical; the mirror's declared side.

**Goal:** `GraphDefinition` keys relationship types by identity triple; allows
same-label/different-endpoint; rejects identical triple; exposes triple-aware lookup.

**Operation** — in `graph_definition/graph_definition.py`:
1. Re-key `_rel_type_map` by `str(RelTypeKey)` (built from
   `rt.__source_label__` / `rt.__label__` / `rt.__target_label__`).
2. `get_relationship_type(source_label, label, target_label)` returns one class; add
   `get_relationship_types_by_label(label) -> list[type[RelationshipModel]]`.
3. Add `relationship_keys: set[str]`; retain `relationship_labels` (bare-label set) for the
   genuine bare-label callers.
4. Invert `_check_duplicate_labels` → `_check_duplicate_keys`: emit
   `DUPLICATE_RELATIONSHIP_TYPE` (ERROR) only on identical triple; allow duplicate label.
5. `get_relationship_label_enum`: key by composite key (or document that labels may repeat).

**Tests (TDD — write first)** — `tests/graph_definition/…`:
- two types, same label, different endpoints → construction succeeds; both retrievable.
- two types, identical triple → `DUPLICATE_RELATIONSHIP_TYPE`.
- `get_relationship_type(src, label, tgt)` resolves the right shape;
  `get_relationship_types_by_label` returns all shapes.

**Care / risks:** every internal caller of `get_relationship_type(label)` (Cypher tool,
views, validation) breaks here — they are repointed in their own tasks (E50.6/E50.7). Keep
`relationship_labels` for callers that truly want bare labels.

---

### E50.3 — Profile model: scalar endpoints, triple-keyed dict

> **Model: Opus.** Breaking model reshape; must reconcile the partitioned-cardinality
> nesting against ADR-030/032 (no double counting).

**Goal:** `RelationshipTypeProfile` describes exactly one shape; `GraphProfile` keys by
identity.

**Operation** — in `graph_profile/models.py`:
1. Replace `source_labels: set[str]` / `target_labels: set[str]` with scalar
   `source_label: str` / `target_label: str`. Keep `rel_type` (bare label) for display.
2. `GraphProfile.rel_type_profiles` keyed by `str(RelTypeKey)`; `relationship_types`
   property returns the **set of key strings**.
3. Confirm `source_partitioned_cardinality` / `target_partitioned_cardinality` semantics
   under per-shape profiles (partition keys now nest inside one identified type — verify no
   double count vs ADR-032).

**Tests (TDD — write first)** — `tests/graph_profile/test_models.py`:
- full `GraphProfile` with two same-label/different-endpoint profiles round-trips
  (`model_dump`/`model_validate`); keys distinct.
- `relationship_types` returns the two distinct key strings.

**Care / risks:** breaking — every reader of `source_labels`/`target_labels`
(`comparison`, `visualization`, inspectors, tests) updates in its own task. Keep the
partitioned-cardinality fields typed on `BoundedDistribution` (ADR-034 round-trip note).

---

### E50.4 — NetworkX inspector: group by `(source, label, target)`

> **Model: Sonnet.** Reference implementation; the grouping spec is fully pinned by
> E50.1/E50.3 — a mechanical-but-careful change.

**Goal:** the in-memory inspector emits one profile per `(src, rel, tgt)` shape with
un-blended statistics.

**Operation** — in `backends/networkx/inspector.py` `_inspect_relationships`:
group/accumulate by the triple `(src_label, edge __label__, tgt_label)` instead of the bare
`__label__`; key `profiles` by `str(RelTypeKey)`; set scalar `source_label`/`target_label`.

**Tests (TDD — write first)** — `tests/backends/networkx/test_inspector.py`:
- a graph with `Person-KNOWS->Person` **and** `Company-KNOWS->Company` produces **two**
  distinct profiles; `count` / `cardinality_stats` / `property_profiles` are **not blended**.
- a graph with only `Person-KNOWS->Person` still produces one profile (regression).

**Care / risks:** edges whose endpoint node has no `__label__` — preserve the existing
skip/log behaviour; decide and test how a missing endpoint label maps into the triple.

---

### E50.5 — Neo4j + Memgraph: per-shape scans (backend parity)

> **Model: Opus.** Query-flow redesign: discover endpoint pairs, fan out the count /
> property / cardinality scans **per pair**, add endpoint-label filters (via
> `validate_identifier`). Extra round-trips; parity-gated; injection-sensitive.

**Goal:** Neo4j and Memgraph emit one profile per discovered `(src, rel, tgt)` shape,
parity with the NetworkX reference.

**Operation:**
1. Drive grouping off endpoint-pair **discovery** (`InspectEndpointLabelsQuery` returns the
   `(source_labels, target_labels)` pairs per bare rel type); build one profile per pair.
2. Add endpoint-label filters to the per-shape count / property / cardinality scans
   (`CardinalityIdentifiers` / `RelTypeIdentifiers` gain `source_label` / `target_label`
   identifier fields, validated by `validate_identifier` — **never** f-stringed).
3. Key `rel_profiles` by `str(RelTypeKey)`; set scalar endpoints; apply in both backends.

**Tests (TDD — write first)** — `tests/backends/{neo4j,memgraph}/test_inspector.py`
(mocked) + opt-in live:
- mocked schema with two endpoint pairs for one rel type → two profiles, un-blended.
- parity: same logical graph → equivalent profiles across NetworkX/Neo4j/Memgraph.
- identifier-splice safety: endpoint labels pass through `validate_identifier`.

**Care / risks:** extra round-trips are accepted but keep them bounded (one scan set per
discovered pair, not per edge). ADR-009 parity = each backend honest per its strategy, not
value-identity. Guard every spliced endpoint label.

---

### E50.6 — Comparison: re-key address space, reclassify endpoints

> **Model: Opus.** Semantic reclassification (`INVALID_ENDPOINT` → `MISSING_*`/`UNEXPECTED_*`);
> trims `ENDPOINTS_CHANGED` to the `__directed__` delta; rewrites the ADR-034 §8 endpoint rows.

**Goal:** the engine walks a `RelTypeKey`-keyed address space; endpoint differences surface
as presence findings; direction drift stays an INFO delta.

**Operation:**
1. `comparison/views.py`: `relationship_types()` → set of key strings; `relationship_at(key)`
   / `relationship_properties(key)` look up by key on **both** `DefinitionView` and
   `ProfileView`.
2. `comparison/engine.py`: rel-type union/intersection over key strings; property address
   `f"{rel_key}.{prop_name}"`.
3. `comparison/rules.py`: presence rules operate on keys (endpoint mismatch now surfaces
   here); **delete `InvalidEndpointRule`**.
4. `comparison/diff_rules.py`: address by key; `RelTypeOnlyInLeft/Right` now catch endpoint
   differences; **trim `EndpointsChangedRule`** to the `__directed__`-flag delta only (drop
   the source/target-label branches for both profile and definition operands).

**Tests (TDD — write first)** — `tests/comparison/{test_rules,test_diff_rules}.py`:
- declared `Person-KNOWS->Person` vs observed `Person-KNOWS->Company` →
  `MISSING_RELATIONSHIP` + `UNEXPECTED_RELATIONSHIP` (no `INVALID_ENDPOINT`).
- same triple, differing `__directed__` → `ENDPOINTS_CHANGED` (INFO) still emitted.
- two same-label/different-endpoint types on both sides compare independently.
- regression: existing single-shape codes unchanged.

**Care / risks:** this changes the diagnostics contract (ADR-037 §4 / ADR-034 §8). Ensure
no rule still reads `source_labels`/`target_labels` (removed in E50.3). Keep `__directed__`
handling alive — direction drift must not be lost.

---

### E50.7 — Cypher tool: endpoint-aware relationship resolution

> **Model: Sonnet.** Repoint `get_relationship_type` consumers using the pattern's own
> endpoint labels; spec fully pinned by E50.2.

**Goal:** the Cypher parser/generator resolve relationship types by triple.

**Operation:** `cypher/parser.py` (`get_relationship_type` at ~399/423/455 — the parser
already reads `pat.source_label` / `__source_label__` at ~459) and `cypher/generator.py`
(~167) resolve via `get_relationship_type(source, label, target)` (or
`get_relationship_types_by_label` where the pattern under-specifies endpoints — decide and
test the under-specified case).

**Tests (TDD — write first)** — `tests/cypher/…`:
- pattern validation/generation for a model with two same-label/different-endpoint types
  picks the right shape.
- a pattern whose endpoints match no declared triple → the existing endpoint-mismatch error
  path.

**Care / risks:** preserve the existing `_pattern_endpoint_issue` error semantics; do not
silently accept an under-specified pattern that is now ambiguous across shapes.

---

### E50.8 — YAML format: `relationship_types` becomes a list

> **Model: Sonnet.** Breaking file-format change (mapping → list); mechanical but wide —
> migrate every fixture/notebook/doc.

**Goal:** YAML round-trips two same-label/different-endpoint relationship types.

**Operation** — in `io/yaml.py`:
1. `_build_model`: read `relationship_types` as a **list** of objects, each with `label`
   (plus `source`, `target`, and existing spec fields).
2. `_build_rel_class`: take `label` from the object, not the mapping key.
3. `_serialize_model`: emit a list of `{label, source, target, ...}` objects.
4. Migrate all YAML fixtures (`tests/io/…`, any sample `.yaml`), notebooks, and docs to the
   list form.

**Tests (TDD — write first)** — `tests/io/test_yaml.py`:
- a definition with two same-label/different-endpoint types round-trips load→save→load.
- single-relationship definitions still round-trip (regression).
- a list entry missing `label`/`source`/`target` raises a clear error.

**Care / risks:** no backward-compatible read of the mapping form — confirm no test/doc
still depends on it. Keep deterministic save ordering (sort by `str(RelTypeKey)` for stable
diffs).

---

### E50.9 — Rendering: keyed profiles, scalar endpoints

> **Model: Sonnet.** Iterate keyed profiles; same-label edges render separately. Mechanical.

**Operation:**
- `visualization/text.py`: iterate `rel_type_profiles` (keyed by triple); print scalar
  `source_label` / `target_label`; same-label shapes appear as separate entries.
- `visualization/mermaid.py`: same-label/different-endpoint types render as distinct edges;
  the label remains the edge-label string.

**Tests (TDD — write first)** — `tests/visualization/…`:
- two same-label/different-endpoint shapes render as two distinct lines/edges.

**Care / risks:** keep output deterministic (stable ordering).

---

### E50.10 — Test sweep + planning hygiene

> **Model: Haiku.** Fully-specified mechanical updates; verification is "suite stays green".

**Operation:**
1. Update every remaining `rel_type_profiles["LABEL"]` / `relationship_types == {"LABEL"}`
   assertion to the keyed form across `tests/{backends,comparison,graph_profile,visualization,io}`.
2. Add the **E50 row** to `.agentic/planning/overview.md` (Epics table + dependency note +
   Epic Files list) and order it as independent/correctness.
3. Add the **ADR-037 routing row** to `.agentic/CONTEXT.md`; confirm ADR-014/015/034
   cross-links.
4. Run the full guardrail set and confirm green.

**Tests / verify:**
```
pwsh> python -m pytest -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

**Care / risks:** purely mechanical — if a test asserts *behaviour* (not just a key shape)
that changed, escalate rather than force-fit the assertion.

---

### E50.11 — Docstring & comment hygiene after the endpoint-identity rewrite

> **Model: Haiku.** Pure documentation/comment cleanup — **no code logic, no test logic, no
> assertion changes**. Verification is "suite still green + grep finds nothing stale".

**Why:** E50.2–E50.6 changed the relationship address space from bare labels to
`RelTypeKey` triples and deleted `InvalidEndpointRule`, but several **module docstrings,
class docstrings, and `#` comments** still describe the old world (rule counts, the old
`ENDPOINTS_CHANGED` source/target-label behaviour, `INVALID_ENDPOINT`, "keyed by label").
These are stale prose only; the code and tests are already correct.

**Operation — fix the wording in these exact spots (do NOT touch any executable line):**

1. `tests/comparison/test_rules.py`
   - Module docstring (top of file, ~line 10–15): the line `* standard_rules() returns all
     ten rule instances in order.` → say **eleven** (the standard set is now 11 rules after
     `InvalidEndpointRule` was deleted; confirm with
     `len(standard_rules()) == 11`). If the docstring still mentions `InvalidEndpointRule`
     or `INVALID_ENDPOINT`, remove that mention.

2. `tests/comparison/test_diff_rules.py`
   - Module docstring (top of file, ~line 5–14): the bullet
     `` - ``ENDPOINTS_CHANGED`` for both profile and definition shapes.`` is now wrong —
     reword to: `ENDPOINTS_CHANGED` fires **only** for the definition `__directed__`-flag
     delta (it is silent for profiles; endpoint-label differences surface as
     `REL_TYPE_ONLY_IN_LEFT`/`_RIGHT`). Also fix `` ``diff_rules()`` factory returns the
     nine rules in spec order.`` if the stated count no longer matches
     `len(diff_rules())` — verify the number and write the correct word.

3. `src/orthograph/comparison/rules.py`
   - Re-read every class docstring and `#` comment for the words "label", "INVALID_ENDPOINT",
     or "endpoint" and confirm they describe the *new* keyed-by-`RelTypeKey` address space.
     The `CardinalityViolationRule` messages/docstrings that say `Relationship '<label>'`
     now interpolate a `RelTypeKey` string (`source:LABEL:target`) — this is intentional
     (the address *is* the identity); only correct prose that is now factually false, do
     **not** change any emitted-message f-string.

4. `src/orthograph/comparison/diff_rules.py`
   - Same pass: confirm the module docstring's "Address conventions" block and any class
     docstrings match the keyed address space and the trimmed `EndpointsChangedRule`.

**Tests / verify:**
```
pwsh> python -m pytest tests/comparison -q          # unchanged: still green
pwsh> rg -n "INVALID_ENDPOINT|all ten rule|source/target label sets" src/orthograph/comparison tests/comparison
pwsh> python -m pre_commit run --files <files you changed>
```
The `rg` line must return **no** hits in docstrings/comments after the edit (the only
legitimate remaining `INVALID_ENDPOINT` hits are the *Cypher-tool* `QUERY_INVALID_ENDPOINT`
code in `src/orthograph/cypher/` — those are out of scope for this task; do not touch them).

**Care / risks:** comments/docstrings only. If you find a *code* line that still reads
`source_labels`/`target_labels` or keys a dict by a bare label, that is a real bug from an
earlier task — **stop and escalate**, do not silently fix it under this doc-only task.

---

## Success Criteria

- [ ] **ADR-037** written and Accepted; ADR-014/015/034 amendments cross-linked.
- [ ] `RelTypeKey` encodes/decodes deterministically; `parse(str(k)) == k`; delimiter-safe.
- [ ] Declaration keys by triple; allows same-label/different-endpoint; rejects identical
      triple (`DUPLICATE_RELATIONSHIP_TYPE`); `get_relationship_type` takes endpoints;
      `get_relationship_types_by_label` exists.
- [ ] `RelationshipTypeProfile` carries scalar `source_label`/`target_label`;
      `rel_type_profiles` keyed by triple; `relationship_types` returns key strings.
- [ ] All three inspectors group by triple; **counts / cardinality / property profiles are
      un-blended**; 3-backend parity; endpoint labels splice-safe.
- [ ] Comparison address space keyed by `RelTypeKey`; endpoint mismatch →
      `MISSING_*`/`UNEXPECTED_*`; `INVALID_ENDPOINT` removed; `ENDPOINTS_CHANGED` is the
      `__directed__`-flag delta only.
- [ ] Cypher tool resolves by triple; YAML list-format round-trips same-label types.
- [ ] Rendering shows same-label shapes separately.
- [ ] Full suite + mypy + pre-commit green; overview + CONTEXT updated.

---

## Out of Scope

- `__directed__` as part of identity (stays an attribute; compared as `ENDPOINTS_CHANGED`).
- Historical / trend storage of any statistic (monitoring-platform concern — PRD out-of-scope).
- Property value *constraints* (min/max/regex/enum) — still deferred.
- Backend-specific multi-label endpoint constraints (no current backend emits them — ADR-034 §8 note).
- A backward-compatible read path for the old YAML mapping form (pre-pilot; no external consumers).
