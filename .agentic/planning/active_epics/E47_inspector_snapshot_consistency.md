# Epic E47: Inspector Snapshot Consistency — Single Read Transaction per Property Scan

> **Priority:** Low (correctness-under-concurrency; not a default-suite failure; revisit when
> the library targets write-heavy or multi-writer deployments)
> **Phase:** post-pilot / as-observed
> **Status:** planned — **do not start unless the reconciliation invariant is observed to fail
> in practice, or the deployment profile changes (write-heavy DB, concurrent schema migrations)**
> **Blocked by:** none (independent; purely internal to the inspector execution surface)
> **Decisions:** ADR-035 §2 (the reconciliation invariant this epic enforces), ADR-009
> (inspector parity — whatever is done must hold across all backends)
> **Origin:** E46.2 code review, 2026-06-23 — deviation recorded in
> `E46_observed_type_counts_population.md` § "Known deviations from ADR-035"

---

## Why This Epic Exists

ADR-035 §2 states a **hard exact-equality reconciliation invariant** for any property whose
value scan runs:

> `sum(observed_type_counts.values()) == value_distribution.count == present_count`

The invariant is meaningful because `present_count`, `observed_type_counts`, and
`value_distribution.count` must all describe the **same population at the same point in time**.
ADR-035 requires this to be enforced by running the three feeding reads inside **one read
transaction** so they share a snapshot.

The E46.2 implementation does not do this. Each read is a separate auto-commit transaction on
the driver. In practice the invariant holds — on a quiescent database or under the test
fixtures, nothing changes between the milliseconds separating the three calls. But it is not
guaranteed by the code; it is guaranteed by the environment. That distinction matters as soon
as the environment changes.

### When the gap becomes observable

The invariant can break if, between the `present_count` read and the type-count / histogram
reads for the same property, concurrent writes add or remove values of that property on the
live graph. Concretely:

- A batch import adds 1000 nodes with `born: 1990` (Long) while the inspector is mid-scan.
  `present_count` reflects the pre-import state; `observed_type_counts` and
  `value_distribution.count` reflect the post-import state. `sum(type_counts) > present_count`.
- A cleanup job deletes nodes between the type-count query and the histogram query.
  `value_distribution.count > sum(type_counts)` because they saw different snapshots.
- A schema migration changes a property type mid-scan. Type keys observed by the type-count
  query may no longer be present in `observed_types` (breaking the
  `set(observed_type_counts) ⊆ set(observed_types)` consistency check).

None of these are theoretical: they are routine operations in a data-engineering context.

---

## The Problem, Precisely

The inspector builds a `PropertyProfile` per property using three reads that must be
consistent:

1. The properties scan (`present_count`, `total_count`, `observed_types`) — issued once per
   label/rel-type, covering all properties of that type in a single query.
2. The type-count aggregation (`observed_type_counts`) — one query per property.
3. The value histogram (`value_distribution`) — one query per property.

Reads 2 and 3 are in the value-scan helpers (`_fetch_node_value_scan`,
`_fetch_rel_value_scan`). Read 1 is in the profile builder, earlier. Each is a separate
`execute_query` call, which the Neo4j driver runs as its own implicit auto-commit transaction
(and similarly on Memgraph). There is no shared session or explicit `BEGIN READ TRANSACTION`
bracketing them.

The invariant `sum(type_counts) == dist.count == present_count` is asserted in tests using
either mocked rows (where the fixture author controls all three values) or a quiescent live DB
(where nothing changes between calls). Neither setting can surface the snapshot divergence.

---

## What This Epic Is Not

- **Not a bug today.** The invariant holds on every tested deployment. This is a
  correctness-under-concurrency gap, not a default-suite failure.
- **Not about query correctness.** The individual queries are correct — they aggregate
  accurately for their own snapshot.
- **Not about the reconciliation *check*.** The assertion logic in tests is fine. The gap is
  that the three snapshots can diverge, not that the check is wrong.
- **Not about E46's other invariants** (SCHEMA-without-APOC gating, `observed_types` subset
  check). Those were fixed in E46.2.

---

## The Structural Obstacle

The reason E46.2 did not implement shared transactions is that the inspector's execution
surface does not expose a transaction handle. Each `_run` / `_run_query` call internally
calls `connection.execute_query(...)`, which is the driver's auto-commit convenience method.
To share a transaction, the three reads would need to run inside a `session.begin_transaction()`
block and pass that transaction object, rather than the top-level `connection` (the driver),
down through every call.

The current `CypherInspector` abstraction passes a `connection` (the driver) and
`execute_kwargs` (e.g. `database_`) through the call stack. It has no concept of an
in-progress transaction as the unit of execution. Adding one is a non-trivial structural
change with consequences across the inspector hierarchy and any backend that inherits from it.

---

## Things to Think Through Before Implementing

These are the questions that matter. The implementation details will have changed by the
time this work starts — treat the questions, not the current code, as the guide.

### 1. Where does the transaction boundary belong?

The natural unit for a consistent scan is **all three reads for one (label/rel-type,
property)** pair. But opening and closing a transaction per-property on a large graph would
create as many transactions as there are properties (potentially thousands). The
alternative is one transaction for all per-type properties — but that holds a read lock
(or MVCC snapshot) for much longer, increasing the chance of conflicting with writes.

There is a real trade-off here. A few options, not exhaustive:

- **Per-property transaction** (smallest snapshot, most overhead): consistent for each
  property individually; `present_count` must also move inside that transaction.
- **Per-label/rel-type transaction** (medium): bracket the properties scan + all per-property
  value scans for one label in one transaction; consistent within a type, not across types.
- **Whole-inspect transaction** (largest snapshot, simplest): one read transaction for the
  entire `inspect()` call; maximally consistent; potentially long-lived.
- **Eventual consistency with a retry** (no structural change): if `sum != present_count`,
  re-run the scan; pragmatic but not a true fix.

The ADR-035 wording ("one read transaction" per property scan) suggests per-property or
per-type, but the decision was made before the structural obstacle was understood. Re-read
ADR-035 §2 with the actual concurrency risk in mind before locking in a boundary.

### 2. Does the driver surface support read transactions?

The Neo4j driver exposes `session.execute_read(fn)` (managed read transaction) and
`session.begin_transaction()` (explicit). `connection.execute_query()` (the current call
site) is a convenience wrapper that uses an implicit auto-commit transaction. Check whether
the driver version in use supports `execute_read` with a multi-statement function, and
whether that function can be structured to issue two or three queries and return all results.
The answer shapes the implementation path.

Memgraph's driver surface may differ — backend parity (ADR-009) means the same transaction
semantics must be achievable on Memgraph before the solution is considered complete.

### 3. How does the execution surface change?

Currently `_run` and `_run_query` receive a `connection` (the driver). If shared transactions
are introduced, the callers need to pass something that is either a transaction or a session
in an active transaction — a different object type. Options:

- Overload `connection` to accept either (fragile, loses type safety).
- Add a separate `transaction` parameter, passed alongside `connection` (explicit but
  pervasive signature change).
- Abstract the execution unit into a protocol that the inspector helpers call uniformly,
  with the caller choosing the underlying driver object.

Whatever approach is taken must not break the existing non-value-scan paths, which do not
need transactions.

### 4. Is the `CypherInspector` base class the right place?

`CypherInspector` is shared by Neo4j and Memgraph backends. If the transaction surface is
added at the base class level, both backends must support it. If it is added only in
`Neo4jInspector`, Memgraph remains inconsistent. Given ADR-009's parity requirement, the
structural change should be designed for both from the start, even if only one backend is
implemented first.

### 5. Can `present_count` move inside the value-scan transaction?

The `present_count` for a property currently comes from the properties scan (read 1), which
runs once per label/rel-type and covers all properties in a single query. If the value-scan
transaction needs to include `present_count`, either:

- (a) Accept that `present_count` for type-count reconciliation comes from a second,
  in-transaction read (a lightweight `COUNT(n.property_name)` query per property), and the
  `PropertyProfile.present_count` field continues to come from the bulk properties scan.
  This means two `present_count` values exist; they should be equal on a quiescent DB but
  may differ under concurrent writes. The invariant would then be
  `sum(type_counts) == dist.count == in_transaction_present_count` — which is not quite the
  same as `== PropertyProfile.present_count`.
- (b) Move the entire properties scan inside a per-label transaction and run the per-property
  value scans within the same transaction. This is the cleanest approach for full consistency
  but is the largest structural change.

This is the most subtle design question. Think through it carefully before writing any code.

### 6. Test coverage

The existing mocked tests assert the reconciliation invariant against fixed data — they prove
the arithmetic is correct but cannot detect snapshot divergence. The e2e tests run against a
quiescent fixture-controlled DB, so they cannot detect it either. A genuine test for this fix
would need to inject a concurrent write during a scan, which is not straightforward with the
current test harness.

At minimum, after the fix, add a comment explaining why the test is insufficient (mocked
snapshot is always consistent) and what a real concurrent-write test would look like. If the
infrastructure for concurrent-write tests exists by the time this is implemented (see E28),
use it.

---

## Acceptance Criteria

These describe the observable outcomes, not the implementation:

- `sum(observed_type_counts.values()) == value_distribution.count == present_count` holds not
  only on quiescent fixtures but is **structurally enforced** — the three reads share a
  snapshot by construction, not by luck.
- The fix applies consistently to Neo4j and Memgraph (ADR-009 backend parity).
- No existing test regresses — all mocked and e2e inspector tests continue to pass.
- The value-scan opt-out path (`value_counts_top_n` unset) is unaffected — no transaction is
  opened when no value scan runs.
- The `CypherInspector` abstraction remains clean — any structural change to the execution
  surface is a considered addition, not a workaround.
- An ADR amendment (or addendum to ADR-035) records the implementation approach chosen and
  the transaction boundary decision (§1 above), because ADR-035's current text assumes
  per-property transactions without acknowledging the structural obstacle.

---

## Guardrails (every task)

```
pwsh> python -m pytest tests/backends/neo4j/test_inspector.py -q
pwsh> python -m pytest tests/backends/memgraph/ -q          # when Memgraph is touched
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <changed files>
pwsh> python -m pytest tests/test_architecture.py -q        # no vendor-concept leaks
```

Live-DB tests remain opt-in (`--neo4j` / `--memgraph`).

---

## Coordination

- **E46 (active):** the gap was introduced in E46.2 and documented there. This epic does not
  change E46's scope — E46 proceeds as planned. E47 is a follow-on.
- **E28 (Testing Strategy):** if E28 delivers a concurrent-write test harness, use it here.
  Otherwise, accept the mocked-snapshot limitation and document it explicitly.
- **ADR-039 (async inspection):** if async inspection is ever added (currently deferred — see
  Deferred table in `overview.md`), transaction management in an async inspector will face the
  same problem. Design this solution to be adaptable, or at least not to foreclose the async
  path.
