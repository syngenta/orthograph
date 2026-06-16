# WriteQuery uses `interpret_result` not `materialize`

`ReadQuery.materialize(raw: dict)` maps one result-set row to a typed domain object — the name
is accurate. `WriteQuery` receives a driver transaction result handle (counters, summary), not a
row. Calling the same method `materialize` on writes implies semantics that do not hold and is a
first-contact friction point: developers expect `raw` to be a dict and get an opaque driver object.

We rename the abstract method to `interpret_result` on `WriteQuery` and `CypherWriteQuery` only.
`ReadQuery.materialize` is unchanged. The asymmetry is intentional and correct: reads materialise
rows, writes interpret mutation summaries. The rename is made at v0.1.0 before any external
consumers exist.

## Considered options

- **Keep `materialize` on both** — symmetric API but semantically wrong for writes; the notebook
  prose already used `interpret_result`, leaving docs and code in disagreement.
- **Add `interpret_result` as a non-abstract alias on `WriteQuery`** — additive but leaves two
  names for one method; confusing.
- **Fix the notebook prose to match `materialize`** — leaves the naming mismatch in production
  code; defers the problem past the public API boundary.
