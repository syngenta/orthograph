# ADR-039: Self-Describing, Name-Aware Partitioned-Cardinality Key

**Status:** Accepted — 2026-06-25
**Category:** core
**Epic:** E53 (single-property reshape — delivers value) → E54 (multi-property follow-on)
**Amends:** ADR-034 §3/§7 (the partitioned-cardinality field reshapes from a string-keyed
`dict` to a list of structured rows; the partition key carries discriminator **names**)
· ADR-032 §2 (the "carries it explicitly anyway" generality is now realised on the
*profile* side, not only the enforcement side)
**Relates:** ADR-030 (per-pair observed statistics), ADR-029 (conditional cardinality),
ADR-037 (relationship identity triple — the profile a partition nests under),
ADR-015 (declared/observed mirror), ADR-009 (inspector parity), ADR-033 (field availability),
ADR-017 (package topology)

---

## Context

`RelationshipTypeProfile.source_partitioned_cardinality` /
`target_partitioned_cardinality` (ADR-030/ADR-034 §7, shipped by E41/E49) are the
**observed** side of conditional cardinality: per-pair degree distributions for a
relationship type whose declared cardinality is a `ConditionalCardinality`. Each
partition is a `BoundedDistribution`, keyed by `str(PartitionKey)`.

Today `PartitionKey` carries **only the discriminator values**:

```python
class PartitionKey(BaseModel):          # current
    source_value: str | None
    target_value: str | None
    def __str__(self) -> str:           # "src=<v>|tgt=<v>", None -> "null"
        ...
```

A real profile fragment (the MatProt `Sample -[:IS_INPUT]-> Operation` pilot, where the
input count depends on `Operation.type`) serialises as:

```jsonc
"target_partitioned_cardinality": {
  "src=null|tgt=chromatography":  { "count": 32, "min": 1, "max": 1 },
  "src=null|tgt=combine":         { "count": 9,  "min": 2, "max": 3 }
}
```

### The three defects

1. **The profile is not self-describing.** `src=`/`tgt=` are **endpoint roles**
   (source-label node / target-label node), *not* property names. Nothing in the profile
   says the target discriminator is `type`. `"combine"` is interpretable **only** by
   holding the `GraphDefinition` and re-deriving `type` from its rules
   (`comparison/rules.py::_single_disc_key`). The observed currency is supposed to be
   meaningful for comparison on its own (ADR-034 §1); for partitioned cardinality it is not.

2. **profile↔profile drift is name-blind.** ADR-034 §8 lists "per-partition delta (INFO)"
   for the profile↔profile path — but with no definition present, two snapshots can only
   match partitions by the value string. Two relationship types discriminating the same
   label on *different* properties (`type` vs `stage`) collapse to the same `tgt=final`
   shape with no way to distinguish them. The name that would disambiguate them was never
   stored.

3. **The string key is lossy and fragile.** The `"src=<v>|tgt=<v>"` encoding is ambiguous
   if a value contains `|` or `=`. The model docstring says "consumers must reconstruct via
   the model fields, not by parsing the string" — yet `comparison/rules.py::_decode_partition`
   **does** parse it (`removeprefix("src=")` / `partition("|")`), so the fragile contract is
   load-bearing in the comparison path.

### The latent silent-drift hole (separate but adjacent)

The profiler can represent **one** discriminator property per endpoint
(`inspection.py::_extract_discriminators` and `networkx/inspector.py::_discriminator_value`
both gate on `len(keys) == 1`). The *definition* side (ADR-032) allows arbitrary
multi-property `PropMatch` maps. ADR-032 §4 **claimed** a definition-time guard rejects
rules the enforcement path cannot read — but no such check exists in
`graph_definition/cardinality_checks.py` (the standard checks cover unknown/optional/
duplicate/ambiguous/catch-all keys, none caps property count). Consequently a legal
multi-property conditional rule constructs fine, the profiler silently collapses it to the
`null/null` partition, and comparison emits a soothing `CARDINALITY_UNVERIFIABLE` (INFO)
instead of checking a real contract.

This ADR fixes defects 1–3. It **does not** add the guard, because closing the
representational gap (multi-property profiling) eliminates the hole at its root, and that
work is scoped as the second epic (E54). Until E54 ships, the single-property cut declines
multi-property breakdowns exactly as today (the `CARDINALITY_UNVERIFIABLE` INFO remains for
those types — an honest "unverifiable", not a false verdict per ADR-034 §2).

---

## Decision

### 1. `PartitionKey` carries `{property_name: value}` maps per endpoint

```python
class PartitionKey(BaseModel):
    model_config = {"frozen": True}
    source: dict[str, str | None]   # {} = source-label node carries no discriminator
    target: dict[str, str | None]   # {"type": "combine"}
```

- The discriminator **name** is now part of the key. The profile is self-describing:
  `target={"type": "combine"}` is interpretable with no definition.
- The empty map `{}` replaces the ambiguous `null` value-literal for "this endpoint has no
  grouping key" (the wildcard / source-label node case, ADR-032's absolute convention).
- A `None` *value* (`{"type": None}`) means "the discriminator property is absent/null on
  observed nodes" — distinct from `{}` ("there is no discriminator on this endpoint").
- The maps are the **observed mirror** of a `ConditionalRule`'s `source.conditions` /
  `target.conditions` `PropMatch` maps, so comparison matches map-against-map with no name
  re-derivation.

### 2. The field becomes a list of structured rows, not a string-keyed dict

```python
class PartitionedCardinalityRow(BaseModel):
    model_config = {"frozen": True}
    key: PartitionKey
    stats: BoundedDistribution      # base class, NOT CardinalityStats (round-trip note, §3)

class RelationshipTypeProfile(BaseModel):
    ...
    source_partitioned_cardinality: list[PartitionedCardinalityRow] | None = None
    target_partitioned_cardinality: list[PartitionedCardinalityRow] | None = None
```

- The lossy `str(PartitionKey)` dict key, the `"null"` literal, and the `|`/`=` ambiguity
  are **gone**. Pydantic round-trips a `list[BaseModel]` natively — no custom serializer.
- `comparison/rules.py::_decode_partition` is **deleted**; comparison reads `row.key`
  directly.
- `PartitionKey.__str__` is retained **display-only** (for `visualization/text.py`); it is
  never a serialization key. Its format may be human-friendly (e.g.
  `source={} target={type=combine}`) since nothing parses it back.

### 3. Partition statistics stay `BoundedDistribution` (round-trip invariant preserved)

The ADR-034 round-trip note carries over: `PartitionedCardinalityRow.stats` is typed on
`BoundedDistribution`, **not** the `CardinalityStats` marker subclass, so a value is restored
as its base on reload and round-trip equality holds. Producers construct `BoundedDistribution`
directly.

### 4. Comparison is name-aware on **both** paths

- **profile↔definition** (`comparison/rules.py`): build declared partitions from
  `rule.source.conditions` / `rule.target.conditions` (the `PropMatch` maps); match observed
  `row.key.source` / `row.key.target` maps directly; feed the maps to
  `ConditionalCardinality.resolve_for_pair`. No value-only `PartitionKey` round-trip, no
  name re-derivation from a single-key convention.
- **profile↔profile** (`comparison/diff_rules.py`): per-partition delta matches rows by
  `PartitionKey` **map equality** — `{"type": "combine"}` and `{"stage": "combine"}` no
  longer collide. This closes ADR-034 §8's "per-partition delta (INFO)" honestly.

### 5. The data model is general; the single-property cut is a *producer* restriction

The maps are `dict[str, str | None]` — they already express N properties per endpoint. In
the first epic (E53) the **producers** (NetworkX `_discriminator_value`, Cypher
`_extract_discriminators` + the grouped Cypher queries) still emit at most one entry per
endpoint, exactly as today; nothing represents what the producers cannot yet measure. The
second epic (E54) lifts the producer restriction with **zero** change to the model,
serialization, comparison, diff, visualization, or their tests — only the inspector
internals and the Cypher query layer change. This is the "fix the representation once,
extend the producer later" split (ADR-032 §2 realised on the profile side).

### 6. Two-epic delivery; no declaration-time guard added in either

Per the project owner's direction, the changes ship **one after the other** and we do
**not** add a `len(keys) > 1` rejection at `GraphDefinition` construction:

- **E53** (delivered) reshapes the model/serialization/comparison/diff/visualization for the
  **single-property** case — and **delivers value immediately**: the MatProt pilot's
  `Operation.type` breakdown becomes self-describing and fully name-aware in both comparison
  paths.
- **E54** (delivered) makes the producers emit multi-property maps (Cypher N-property grouping +
  NetworkX multi-key reads), at which point the silent-drift hole is closed at the root: a
  multi-property conditional rule is *profiled and checked*, not declined. No guard is
  needed because the capability gap that motivated it is gone.

---

## Consequences

- **Self-describing profiles.** A serialized profile alone tells you which property each
  partition discriminates on. No definition required to read it.
- **Name-aware comparison, both paths.** profile↔definition stops re-deriving the name by
  convention; profile↔profile stops colliding partitions of different properties.
- **The fragile string parse is deleted.** `_decode_partition` and the `|`/`=`/`null`
  encoding hazard are gone; round-trip is plain Pydantic.
- **Breaking model change, taken now.** The field type changes
  (`dict[str, BoundedDistribution]` → `list[PartitionedCardinalityRow]`) and `PartitionKey`'s
  fields change. Permitted: no external profile consumers (ADR-034 §Context). Every producer,
  consumer, and ~250 test assertion sites update — but **once**: the map-shaped key absorbs
  both E53 and E54, so E54 does not rewrite E53's tests (§5).
- **E54's surface is disjoint from E53's heavy test surface.** E54 touches the Cypher query
  templates, identifier models, `_extract_discriminators`/`_discriminator_value`, and *adds*
  multi-key tests — it does not re-touch the model/serialization/comparison/visualization
  tests E53 rewrote.

---

## Rejected alternatives

- **Add a `source_name`/`target_name` scalar pair to `PartitionKey` (keep scalar values).**
  Rejected: it makes the profile self-describing for one property but forces a *second*
  model migration (scalar → map) when E54 needs multiple properties, re-touching the same
  heavy test surface twice. The map shape absorbs both epics; scalars do not.
- **Keep the `dict[str, BoundedDistribution]` field, just make `str(PartitionKey)`
  unambiguous (JSON-encode name+value).** Rejected: keeps the load-bearing parse path alive
  (still fragile, still must be decoded), when structured rows remove parsing entirely and
  Pydantic handles the round-trip.
- **Add the ADR-032 §4 declaration-time guard now (reject multi-property at construction).**
  Rejected per owner direction: the two epics close the gap by *capability* (E54 profiles
  multi-property), not by *prohibition*. A guard would have to be added in E53 and removed
  in E54 — churn for no end-state value.
- **Do E53 and E54 as one epic.** Rejected: E54's only extra surface is the Cypher query
  layer (variable-width grouping, 6 query classes × strategies × backends, catalogue tests),
  which E53 never touches; combining them lengthens the red period with no test-rework saving
  (§5). Sequential delivery ships the pilot value (E53) first.

---

## Cross-references

- ADR-034 §3/§7: reshaped here (field type + the partition key)
- ADR-032 §2/§4: the generality is realised on the profile side (E54); no declaration-time
  guard added (§6)
- ADR-030: per-pair observed statistics (the field this reshapes)
- ADR-037: relationship identity triple — partitions nest inside an endpoint-identified profile
- `PartitionKey` / `PartitionedCardinalityRow` / partitioned fields:
  `src/orthograph/graph_profile/models.py`
- producers: `src/orthograph/backends/networkx/inspector.py`,
  `src/orthograph/graph_profile/inspection.py`, `src/orthograph/graph_profile/queries/shared.py`
- consumers: `src/orthograph/comparison/rules.py`, `src/orthograph/comparison/diff_rules.py`,
  `src/orthograph/visualization/text.py`
- E53 epic: `.agentic/planning/active_epics/E53_self_describing_partition_key.md`
- E54 epic: `.agentic/planning/active_epics/E54_multi_property_partition_profiling.md`
