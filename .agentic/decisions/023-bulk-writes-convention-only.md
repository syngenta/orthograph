# Bulk writes are convention-only in v0.1.0; BulkWriteQuery is deferred

`WriteQuery` executes a single Cypher statement per call. There is no first-class bulk-write
pattern in the library. A `UNWIND $items AS item CREATE (...)` pattern works today by declaring
a `list[dict]` field on a `Params` model — the executor passes it through to the driver untouched.

We do not introduce a `BulkWriteQuery` base class in v0.1.0. The documented convention is:
use `$items: list[dict]` on `Params` with `UNWIND $items AS item` in the Cypher template.
`WriteQuery` executes one statement per call; teams using a list param for bulk operations are
responsible for that pattern. This boundary is documented explicitly in the Getting Started guide.

There is no framework-level enforcement preventing a regular `WriteQuery` from receiving a list
param — distinguishing "list as a filter" (`WHERE n.tag IN $tags`) from "list as a batch"
(`UNWIND $items`) requires Cypher template analysis that would produce false positives on
legitimate aggregation queries. A `QUERY_BULK_PATTERN_DETECTED` INFO issue will be added to
`validate_query_catalogue` when `BulkWriteQuery` is introduced, not before.

## Considered options

- **`BulkWriteQuery[P, R]` base class now** — meaningful design decision that deserves its own
  scoping session; no evidence of real use cases yet; rushed pre-public without sufficient design.
- **INFO-level detection of `UNWIND $param` patterns now** — would fire on legitimate non-bulk
  UNWIND templates; deferred to the `BulkWriteQuery` epic.
