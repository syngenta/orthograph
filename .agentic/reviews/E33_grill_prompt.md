# E33 Grill Prompt — Query Contract Ergonomics v2

> Use with the `grill-with-docs` skill.
> Context: orthograph is a **typed query-contract + validation layer** for Neo4j/Memgraph.
> It is NOT an ORM. Read the files listed under "Files to read" before grilling.
> The two questions are independent — grill them in sequence, one at a time.

---

## Files to read before grilling

```
src/orthograph/query/base_models.py          — ReadQuery, WriteQuery, abstract method contracts
src/orthograph/cypher/base_models.py         — CypherReadQuery, CypherWriteQuery, __init_subclass__
src/orthograph/cypher/query_execution.py     — CypherExecutor.read(), CypherExecutor.write()
src/orthograph/query/write_result.py         — WriteResultSummary protocol
.agentic/planning/active_epics/E31_query_contract_implementation.md  — current contract decisions
.agentic/planning/active_epics/E33_query_contract_ergonomics_v2.md   — the two open questions
notebooks/05.01_openapi_ergonomics_assessment.ipynb                  — the lived ergonomic reality
```

---

## Question 1 — Eliminating mandatory `materialize()` for the 1:1 case

### What we are proposing

A new optional class variable `row_mapper: ClassVar[Callable[[dict], D] | None]` on
`CypherReadQuery` (possibly on `ReadQuery`). When set, the library provides a default
`materialize` implementation that calls it, making the method optional for the 1:1 case.

```python
# PROPOSED: 1:1 case — no materialize() needed
class MoviesByYear(CypherReadQuery[MoviesByYearParams, Movie]):
    name = "movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title AS title, ..."
    row_mapper = Movie.model_validate          # ← removes the boilerplate

# UNCHANGED: divergent case — must still implement materialize()
class MovieSummariesByYear(CypherReadQuery[MoviesByYearParams, MovieSummary]):
    name = "movie_summaries_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title AS title, m.released AS released"

    def materialize(self, raw: dict) -> MovieSummary:
        return MovieSummary(title=raw["title"], year=raw["released"])   # explicit, cannot be removed
```

### Grill hard on these points

1. **Does this actually save work?** The consumer still writes `row_mapper = Movie.model_validate`.
   Is that substantially less ceremony than `def materialize(self, raw): return Movie.model_validate(raw)`?
   Or is the real win elsewhere (e.g. making the 1:1 intent *declared* rather than implied)?

2. **Should the default be `Output.model_validate`?** If the intent of the generic `[P, D]`
   parameter is precisely "D is the output type", then `row_mapper = Output.model_validate`
   could be the silent default — making 1:1 the default and the divergent case the explicit
   opt-in. Push hard: what are the failure modes? If the RETURN columns don't match the Output
   fields, `model_validate` raises a `ValidationError` at runtime, not at definition time. Is
   that acceptable, or is silent-default worse than explicit boilerplate?

3. **Where does `row_mapper` live?** `ReadQuery` is the backend-agnostic abstract layer.
   `CypherReadQuery` is Cypher-specific. The *mapping seam* (`materialize`) is declared on
   `ReadQuery`. If `row_mapper` is a shortcut for the mapping seam, it belongs on `ReadQuery`
   too. But `row_mapper = Model.model_validate` is Pydantic-specific vocabulary. Does that
   pull Pydantic assumptions into the abstract layer? What does the SQLAlchemy or GQLAlchemy
   backend story look like?

4. **AbstractMethod interaction.** `materialize` is `@abstractmethod`. If `row_mapper` provides
   a default implementation, `materialize` can no longer be abstract on the same class — it
   needs a concrete default that checks `row_mapper`. But then `inspect.isabstract(cls)` returns
   `False` for any subclass, even ones that have not provided either `row_mapper` or `materialize`.
   How do you enforce that exactly one of the two is provided at class-definition time?

5. **Both set / neither set.** Definition-time enforcement rules:
   - Both `row_mapper` set AND `materialize` overridden → raise `CypherQueryDefinitionError`?
   - Neither `row_mapper` nor `materialize` → raise `CypherQueryDefinitionError`?
   - How does this interact with the existing `inspect.isabstract` guard in `__init_subclass__`?

6. **Type-checker visibility.** `row_mapper = Movie.model_validate` — does mypy/pyright infer
   the return type as `Movie`, or does it lose the type through `ClassVar[Callable[[dict], D]]`?
   If the type is erased, the ergonomic benefit disappears for typed codebases.

7. **Naming.** `row_mapper` vs `record_mapper` vs `row_factory` vs `to_output`. The existing
   codebase uses `materialize` for the per-record mapping. Is `row_mapper` consistent with that
   vocabulary, or does it introduce a second mental model for the same concept?

---

## Question 2 — Should `CypherExecutor.write()` optionally surface `RETURN` rows?

### What we are proposing

Change `CypherWriteResultSummary` to collect rows before consuming the result, so
`interpret_result` can access them:

```python
@dataclass
class CypherWriteResultSummary:
    nodes_created: int = 0
    # ... other counters ...
    rows: list[dict[str, Any]] = field(default_factory=list)   # NEW

    @classmethod
    def from_neo4j_result(cls, result: Any) -> "CypherWriteResultSummary":
        rows = [dict(rec) for rec in result]     # collect BEFORE consume
        summary_counters = result.consume().counters
        return cls(nodes_created=summary_counters.nodes_created, ..., rows=rows)
```

This would allow:

```python
class CreateMovie(CypherWriteQuery[CreateMovieParams, Movie]):
    cypher_template = "CREATE (m:Movie {title: $title, released: $released}) RETURN m.title AS title, m.released AS released"

    def interpret_result(self, raw: WriteResultSummary) -> Movie:
        if not raw.rows:
            raise ValueError("CREATE returned no rows")
        return Movie.model_validate(raw.rows[0])
```

### Grill hard on these points

1. **Driver safety.** With the neo4j Python driver, is `list(result)` followed by
   `result.consume()` safe? Does iterating the result before consuming invalidate the
   transaction cursor? What about the Memgraph driver? Push for evidence — do not accept
   "probably fine".

2. **Protocol breakage.** `WriteResultSummary` is a `runtime_checkable` `Protocol`.
   Adding `rows: list[dict]` breaks every existing test double that satisfies it. The
   `_FakeWriteSummary` in §05.01 notebook has no `rows`. Is adding `rows: list[dict] = []`
   (default empty) an acceptable change to the protocol, or does it change the semantics
   of a protocol that was deliberately "counters only"?

3. **Always-on vs opt-in.** Collecting `list(result)` for every write has a memory and
   latency cost — even for writes that use no `RETURN` (the common case). Should row
   collection be opt-in: a flag on the query class (`returns_rows: ClassVar[bool] = False`),
   or detected from the template (`RETURN` clause present)? The detection approach has a
   false-negative risk (imperative `build()` queries have no template to inspect).

4. **What does `rows` contain for a `MERGE`?** `MERGE (m:Movie {title: $title})` may match
   an existing node or create a new one. The row in `rows` is the matched or created node.
   `nodes_created` may be 0. Is this semantically safe to return as the "created" resource?
   What if the caller assumes `rows[0]` is always a newly-created entity?

5. **Generalisation claim.** The proposal is "writes can now return the entity they wrote".
   Is this a general claim or a `CREATE ... RETURN` specific claim? What happens with:
   - `MERGE` (may or may not create)
   - `UNWIND $items AS item CREATE ...` (batch write — `rows` could be many)
   - `DELETE` with `RETURN` (rows are the deleted nodes, which no longer exist)

6. **Right abstraction level.** An alternative: introduce `WriteQueryWithReturn[P, D]`
   that explicitly declares an `Output` model and mandates a `RETURN` clause. The base
   `WriteQuery` stays counter-only. Is the added type safety worth the extra class?

7. **v0.1 scope.** Given that E31 is not yet fully complete and the `WriteResultSummary`
   protocol was only just introduced, is expanding `write()` return semantics the right
   v0.1 decision? Or is "write returns counters only; echo-back requires a follow-up read"
   the correct stable v0.1 answer, with the expansion planned explicitly for v0.2?
   What is the cost to pilot consumers of the v0.1 limitation?

---

## After grilling

For each question, produce an ADR:

- Q1 → `decisions/025-read-query-row-mapper.md`
- Q2 → `decisions/026-write-query-return-rows.md`

Each ADR must state:
1. **Decision:** implement / reject / defer (with version target if deferred)
2. **Rationale:** the top 2–3 reasons
3. **Rejected alternatives:** at least one named alternative and why it was rejected
4. **Consequences:** what changes in the public API, what existing code breaks, what
   pilot consumers need to do differently

Update `E33_query_contract_ergonomics_v2.md` T1/T2 acceptance criteria as each ADR is written.
