# ADR-037: Relationship Identity Includes Endpoints

**Status:** Accepted — 2026-06-24
**Category:** core
**Epic:** E50 (Endpoint-aware relationship identity)
**Supersedes:** the *identity implication* of ADR-014 (endpoints are no longer merely
attributes of a label-identified type — they are part of the type's identity)
**Amends:** ADR-015 §(shared address space), ADR-034 §7/§8 (endpoint rows reclassify),
ADR-036 §(relationship path — superseded by the per-shape pattern scan, §6a; node path unchanged)
**Relates:** ADR-030/ADR-032 (conditional cardinality partitioning — partition keys now
nest *inside* an endpoint-identified type), ADR-017 (package topology),
ADR-009 (inspector parity)

---

## Context

A relationship type's **identity** is, today, its bare **label** string everywhere in
the library:

- the declared side keys `GraphDefinition._rel_type_map` by `__label__` and rejects two
  relationship types that share a label (`DUPLICATE_RELATIONSHIP_LABEL`, ERROR);
- the observed side keys `GraphProfile.rel_type_profiles` by the bare `rel_type` string;
- the comparison engine walks a flat **union of label strings** and matches left↔right by
  label equality;
- the YAML format encodes `relationship_types:` as a **mapping keyed by label**;
- the Cypher tool resolves patterns via `get_relationship_type(label)`.

ADR-014 made endpoints (`__source_label__` / `__target_label__`) plain **string
attributes** of a label-identified type. It deliberately did *not* decide that the label
is the *unique identity* — but every dict, set, and address listed above has crystallised
that assumption.

This produces a concrete, silent correctness defect on the **observed** side. All three
inspectors (NetworkX / Neo4j / Memgraph) group edges by bare label and **merge** the
distinct endpoint node-labels into two `set[str]` fields (`source_labels`,
`target_labels`). A graph containing both `Person-KNOWS->Person` and
`Company-KNOWS->Company` yields **one** `RelationshipTypeProfile(rel_type="KNOWS")` whose
endpoint sets are `{Person, Company}` and whose `count`, `cardinality_stats`, and
`property_profiles` are **blended across two genuinely different relationship shapes**.
The `Person↔Company` cross-product becomes indistinguishable from `Person↔Person`, and
aggregate cardinality bound checks then run against blended degree statistics.

The declared side does not have the *blending* bug (it rejects the collision outright),
but its rejection is the **opposite** of what a real graph database permits: Neo4j allows
a single relationship type between many label pairs. The declared and observed sides are
therefore both wrong about the same thing, in mirror-image ways, and ADR-015's
declared/observed mirror cannot hold.

Because there are **no external consumers yet**, this is the right moment to take a
**breaking** change rather than layer a compatibility shim over a wrong identity model.

---

## Decision

### 1. Identity is the triple `(source_label, label, target_label)`

A relationship **type** is identified by the ordered triple of its **source node label**,
its **relationship label**, and its **target node label**. Two relationships with the same
label but different endpoint labels are **distinct types**. Two relationships with the
**same** triple are the **same** type and continue to collapse into one profile (this is
the desired aggregation — instances of one shape).

`__directed__` is **not** part of identity. Direction is a property of the type, compared
as an attribute (see §5), not a discriminator. (A future ADR may revisit this if an
undirected/directed pair of the same triple is ever required to coexist; today they cannot.)

Direction is also currently **unobservable** — `RelationshipTypeProfile` carries no
`directed` field and no backend emits an undirected relationship *type*. Putting direction
in identity would require keying the shared address space on a value the observed side
cannot supply (breaking ADR-015's mirror) plus net-new inspector direction-detection.
Adding it later is a bounded change (one new `RelTypeKey` field + inspector detection); the
inspector work is net-new in either case, so deferring costs nothing.

### 2. Identity is encoded as a deterministic composite string: `RelTypeKey`

A single frozen model carries the identity and serialises to a stable string used as the
`dict` key and the comparison **address**:

```python
class RelTypeKey(BaseModel):
    model_config = {"frozen": True}

    source_label: str
    label: str
    target_label: str

    def __str__(self) -> str:
        return f"{self.source_label}:{self.label}:{self.target_label}"

    @classmethod
    def parse(cls, key: str) -> "RelTypeKey": ...
```

The delimiter `:` is **safe**: every label is validated against
`^[A-Za-z_][A-Za-z0-9_]*$` (`cypher/identifiers.py::validate_identifier`), so `:` can never
appear *inside* a label and the encoding is unambiguous. This mirrors the existing
`PartitionKey` convention (`src=<v>|tgt=<v>`): the string is a stable key, but consumers
that need the parts reconstruct them via `RelTypeKey.parse`, never by ad-hoc string
splitting at call sites.

`RelTypeKey` is the **single source of truth** for relationship identity encoding/decoding.
Both the declared side and the observed side key on `str(RelTypeKey)`.

### 3. The shared comparison address space is keyed by `RelTypeKey`

The comparison engine's relationship pass walks a **union of `RelTypeKey` strings** (not
bare labels). Left↔right matching is **triple equality**. The relationship-property address
becomes `f"{rel_key}.{prop_name}"`.

A consequence: when one side declares `Person-KNOWS->Person` and the other observes
`Person-KNOWS->Company`, these are now **two different addresses** — one present only on
the left, one only on the right. They naturally produce `MISSING_*` / `UNEXPECTED_*`
findings (see §4), **not** an endpoint-mismatch-within-one-type finding.

### 4. Endpoint mismatch reclassifies to presence findings

Because endpoints are identity:

- `InvalidEndpointRule` (which fired when a label matched but endpoints differed) is
  **removed**. An endpoint difference is now a different address, reported by the existing
  presence rules as `MISSING_RELATIONSHIP` (declared, not observed) and/or
  `UNEXPECTED_RELATIONSHIP` (observed, not declared).
- The endpoint-label branches of the profile↔profile / definition↔definition
  `ENDPOINTS_CHANGED` diff rule are **removed**. `ENDPOINTS_CHANGED` is **retained only
  for the `__directed__` flag** delta (direction is an attribute, §1/§5), so a change of
  direction on the *same* triple still surfaces as an INFO drift signal rather than an
  add/remove.

This is a **deliberate diagnostics-contract change**: a declared-vs-observed endpoint
difference that was one `INVALID_ENDPOINT` (ERROR) finding becomes a `MISSING_*` +
`UNEXPECTED_*` pair. It is accepted because, under triple identity, the two endpoint
shapes genuinely *are* different types; reporting them as presence deltas is the honest
model.

### 5. The profile model carries scalar endpoints

`RelationshipTypeProfile.source_labels: set[str]` / `target_labels: set[str]` are
**replaced** by scalar `source_label: str` / `target_label: str`. The set fields existed
only to hold the blended endpoint labels of §Context; under triple identity each profile
describes exactly one `(source, label, target)` shape, so the value is singular. `rel_type`
(the bare label) is retained for display and grouping.

`__directed__` remains an attribute on the *declared* side (`RelationshipModel`) and is
compared as a `ENDPOINTS_CHANGED` (directed-flag) delta in diffs (§4).

### 6. Inspection groups by triple, not by label

All three inspectors group edges by `(source_label, label, target_label)`:

- **NetworkX** groups by the triple read from the two endpoint nodes' `__label__` and the
  edge `__label__` (the reference implementation).
- **Neo4j / Memgraph** drive grouping off endpoint-pair **discovery**
  (`InspectEndpointLabelsQuery` returns the `(source_labels, target_labels)` pairs per bare
  rel type), then fan out the count / property / cardinality scans **per discovered pair**.
  Endpoint-label filters are added to the scan queries and pass through
  `validate_identifier` like every spliced identifier. This costs additional round-trips;
  the cost is accepted as the price of honest per-shape statistics (ADR-009 parity:
  each backend honest per its strategy).

#### 6a. The relationship property scan becomes pattern-Cypher (supersedes ADR-036's rel path)

To produce **per-shape** relationship property profiles (un-blended `present_count` /
`value_distribution` / type counts) the relationship property/count/value scans are driven
by an endpoint-filtered pattern `MATCH (n:source)-[r:REL]->(m:target)` for **every**
strategy. This **supersedes the relationship-property portion of ADR-036**: `apoc.meta.relTypeProperties`
aggregates by *bare* relationship type and cannot be constrained to an endpoint pair, so it
can no longer source per-shape relationship `present_count` / `total_count`. The dedicated
`count()`-based correction that ADR-036 introduced is *retained in spirit* — the per-pair
pattern scan already yields a truthful non-null count per shape, which is the corrected
value ADR-036 was reaching for. ADR-036's **node** path is unchanged.

`observed_types` for a relationship property continue to come from the bulk type maps
(`db.schema.relTypeProperties` / `apoc.meta`) keyed by the **bare** rel type and are
attached to each shape: a property key's stored *type* does not vary by endpoint pair, so
this is honest (ADR-009 parity = honest per strategy, not byte-identical), while the counts
that *do* vary by shape are scanned per pair.

### 7. The declared side allows same-label/different-endpoint, rejects identical triple

`GraphDefinition._rel_type_map` is keyed by `RelTypeKey`. The construction-time guard
**inverts**: `DUPLICATE_RELATIONSHIP_LABEL` (which rejected two same-label types) is
replaced by `DUPLICATE_RELATIONSHIP_TYPE`, which fires (ERROR) only when two declared
relationship types share the **same triple**. Two types with the same label and different
endpoints are now legal.

`get_relationship_type(label)` — which returned a single class — becomes
`get_relationship_type(source_label, label, target_label)`. A new
`get_relationship_types_by_label(label) -> list[type[RelationshipModel]]` serves callers
that legitimately want every shape of a label. `relationship_labels` (bare-label set) is
retained where bare labels are genuinely wanted; a `relationship_keys` (`set[str]` of
`RelTypeKey` strings) is added for identity iteration.

### 8. The YAML format becomes a list

`relationship_types:` can no longer be a **mapping keyed by label** — a YAML mapping cannot
hold two `ACTED_IN:` keys. It becomes a **list** of relationship objects, each carrying its
own `label` (plus `source`, `target`, and the existing spec fields):

```yaml
relationship_types:
  - label: ACTED_IN
    source: Person
    target: Movie
  - label: ACTED_IN
    source: Director
    target: Film
```

This is a **breaking file-format change** with no backward-compatible read path for files
that relied on the mapping form. All fixtures, notebooks, and docs migrate to the list
form.

---

## Consequences

- **The observed-side blending defect is fixed.** Distinct `(src, rel, tgt)` shapes now
  produce distinct profiles with un-blended `count` / `cardinality_stats` /
  `property_profiles`; aggregate cardinality checks run against the correct shape.
- **The declared/observed mirror (ADR-015) is restored** around a *correct* identity:
  both sides key on `RelTypeKey`, both permit same-label/different-endpoint, both reject
  the genuinely-duplicate identity.
- **Diagnostics output changes** (§4): endpoint differences move from `INVALID_ENDPOINT`
  (ERROR) to `MISSING_*` / `UNEXPECTED_*`; `ENDPOINTS_CHANGED` shrinks to a directed-flag
  signal. ADR-034 §8's endpoint rows are rewritten accordingly.
- **Public API changes** (§7): `get_relationship_type` gains endpoints;
  `get_relationship_types_by_label` is added. Acceptable — no external consumers.
- **Inspection costs more round-trips** on Neo4j/Memgraph (§6). Accepted.
- **Persisted profiles and YAML files are invalidated** (§2/§8). Accepted — pre-pilot, no
  external consumers; ADR-034 §1 (comparison is field-level, never byte-level) means no
  byte-stable hash depends on the old shape.
- **Conditional cardinality nests under identity** (ADR-030/032): the per-pair
  `*_partitioned_cardinality` breakdown now lives *inside* an already-endpoint-identified
  profile. E50 confirms no double-counting against the ADR-032 enforcement path.

---

## Rejected alternatives

- **Keep label identity; document the blending as a known limitation.** Rejected: it is a
  silent wrong verdict on real graphs (Neo4j permits multi-endpoint rel types), and
  ADR-015's mirror cannot hold while the two sides disagree about identity.
- **Two-level dict `rel_type_profiles[label][(src,tgt)]`.** Rejected: it preserves the
  bare label as the outer key (perpetuating the assumption at every iterator) and
  complicates the comparison address space; a flat `RelTypeKey` is simpler and uniform.
- **A frozen `RelTypeKey` used directly as the dict key / address (not its string).**
  Rejected for the on-the-wire/address surface: a string key serialises cleanly and reads
  legibly in diagnostics; `RelTypeKey.parse` recovers the parts when needed. The model is
  retained as the *encoder/decoder*, not as the key type.
- **Make `__directed__` part of identity.** Rejected: no current requirement for a
  directed and an undirected relationship of the *same* triple to coexist; direction is
  compared as an attribute delta (`ENDPOINTS_CHANGED`). It is also currently
  **unobservable** — `RelationshipTypeProfile` carries no `directed` field and no backend
  emits an undirected relationship *type*, so identity-on-direction would key the shared
  address space on a value the observed side cannot supply (breaking ADR-015's mirror) and
  force net-new inspector direction-detection. Adding it later is a bounded change (one new
  `RelTypeKey` field + inspector detection); the inspector work is net-new in either case,
  so deferring costs nothing.
- **Keep `INVALID_ENDPOINT` as a same-label bridge finding.** Rejected: under triple
  identity the two shapes are different types; a bridge rule would re-introduce label-level
  reasoning on top of triple identity and emit a finding that contradicts the address model.

---

## Cross-references

- ADR-014: relationship endpoint labels (string attributes — identity implication superseded here)
- ADR-015: declared/observed mirror (shared address space now keyed by `RelTypeKey`)
- ADR-034 §7/§8: GraphProfile statistical model & comparison matrix (endpoint rows reclassified)
- ADR-030/ADR-032: conditional cardinality partitioning (partition keys nest under identity)
- `RelTypeKey`: `src/orthograph/graph_definition/identity.py` (foundation of the
  declared/observed mirror — both sides depend on it *downward* per the ADR-017 DAG;
  re-exported from `graph_profile/models.py` for the observed side)
- `RelationshipTypeProfile` / `GraphProfile`: `src/orthograph/graph_profile/models.py`
- declaration: `src/orthograph/graph_definition/graph_definition.py`
- comparison: `src/orthograph/comparison/{engine,views,rules,diff_rules}.py`
- inspection: `src/orthograph/backends/{networkx,neo4j,memgraph}/inspector.py`, `src/orthograph/graph_profile/inspection.py`
- YAML: `src/orthograph/io/yaml.py`
- E50 epic: `.agentic/planning/active_epics/E50_endpoint_aware_relationship_identity.md`
