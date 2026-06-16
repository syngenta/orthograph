# WriteResultSummary protocol lives in the vendor-free query layer

`WriteQuery.interpret_result(raw)` receives a backend-specific result object. Without a typed
contract, `raw: Any` gives implementors no guidance and makes unit-testing impossible without
a real driver or a carefully crafted fake.

We introduce a `WriteResultSummary` Protocol in `src/orthograph/query/` (the vendor-free layer)
with a minimal surface (`nodes_created`, `relationships_created`, `nodes_deleted`, etc.).
`CypherExecutor` wraps the `neo4j.Result` counters into a concrete implementation before passing
it to `interpret_result`. The GQLAlchemy executor, when built, will provide its own implementation.

The protocol is placed in the vendor-free layer — not in `src/orthograph/cypher/` — because
`WriteQuery` itself lives there and the contract must be expressible without a Cypher dependency.
This also creates the correct premises for a future GQLAlchemy executor to satisfy the same
protocol with a different concrete implementation.

## Considered options

- **Docstring only** — leaves the contract in prose, not the type system; does not improve
  testability.
- **Protocol in `cypher/`** — correct for today but couples the abstract base to a Cypher-specific
  module; a future GQLAlchemy executor would have an unnatural dependency.
- **Executor extracts counters into a plain dict before calling `interpret_result`** — loses access
  to the full result object for callers who need it; changes executor behaviour.
