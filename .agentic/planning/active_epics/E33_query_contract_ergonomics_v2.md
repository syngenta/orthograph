# Epic E33: Query Contract Ergonomics — v2 Design Decisions

> **Priority:** High
> **Origin:** Notebook ergonomics review session 2026-06-16
> **Goal:** Resolve two open design questions in `ReadQuery`/`WriteQuery` before the
> contract surface stabilises for pilot consumers. Decisions taken here directly change
> the public API; no implementation should start until both questions are grilled
> (use the `grill-with-docs` skill against this epic) and an ADR is written for each.
> **Blocked by:** E31 substantially complete (the vocabulary it introduces —
> `interpret_result`, `WriteResultSummary`, auto-populated `Params`/`Output` — is
> the baseline this epic modifies)
> **Blocks:** Public API stabilisation (v0.1 release gate)

---

## Background

Two problems surfaced during the §05.01 notebook review:

**Problem 1 — `materialize()` is mandatory boilerplate for the 1:1 case.**
For every `CypherReadQuery` whose `RETURN` aliases map exactly 1:1 to the `Output`
model's fields, `materialize` reduces to:

```python
def materialize(self, raw: dict) -> Movie:
    return Movie.model_validate(raw)
```

This is pure boilerplate. The question is whether the library can remove it as a
requirement when the 1:1 mapping holds, and if so how — while preserving the seam for
the divergent case (renamed columns, projections, multiple node sources).

**Problem 2 — `CypherExecutor.write()` discards `RETURN` rows; writes cannot echo
the created resource.** Today a `POST` endpoint cannot return the created node without
a follow-up read query. A REST-idiomatic `201 Created` with the full entity body is
not expressible against the current contract. This is the single largest ergonomic gap
for typical REST APIs.

---

## Design Question 1 — Eliminating mandatory `materialize()` for 1:1 queries

### Current state

`ReadQuery.materialize` is `@abstractmethod`. Every concrete subclass must implement
it, even when the implementation is always `Output.model_validate(raw)`.

`CypherExecutor.read` calls `query.materialize(dict(rec))` for each record.

### Proposed change

Introduce an alternative to the hand-written `materialize()` for the **1:1 case only**:
a function-valued class variable `row_mapper: Callable[[dict], D] | None = None`.

```python
class CypherReadQuery(ReadQuery[P, D]):
    row_mapper: ClassVar[Callable[[dict], D] | None] = None
```

Rules:
- If `row_mapper` is set, `materialize` need not be implemented (it is provided by a
  default implementation that calls `row_mapper`).
- If `row_mapper` is `None` (the default), `materialize` remains abstract and must be
  implemented — the divergent mapping case.
- A query that sets **both** `row_mapper` and overrides `materialize` raises
  `CypherQueryDefinitionError` at class-definition time (ambiguous).

The 1:1 shortcut is sugar:

```python
class MoviesByYear(CypherReadQuery[MoviesByYearParams, Movie]):
    name = "movies_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title AS title, ..."
    row_mapper = Movie.model_validate   # no materialize() needed
```

The divergent case is unchanged:

```python
class MovieSummariesByYear(CypherReadQuery[MoviesByYearParams, MovieSummary]):
    name = "movie_summaries_by_year"
    cypher_template = "MATCH (m:Movie {released: $released}) RETURN m.title AS title, m.released AS released"

    def materialize(self, raw: dict) -> MovieSummary:
        return MovieSummary(title=raw["title"], year=raw["released"])   # explicit seam
```

### Questions to grill

1. Does `row_mapper` actually remove the boilerplate in the common case, or does it
   just rename it? (The caller still writes `row_mapper = Movie.model_validate`.)
2. Should the default `row_mapper` be `Output.model_validate` automatically — i.e.
   make 1:1 the default and require opting in to the divergent mapping? What are the
   failure modes if the columns don't match?
3. `row_mapper` is a `ClassVar` of callable type. Does Pydantic / `ClassVar` inference
   handle `Callable` without unexpected side effects?
4. What does the type-checker see for `row_mapper = Movie.model_validate`? Is the
   return type `Movie` inferred, or is it erased to `Any`?
5. Is `row_mapper` the right name? Alternatives: `record_mapper`, `row_factory`,
   `to_output`. What does the existing codebase call similar constructs?
6. Should `row_mapper` be validated at definition time (e.g. check it is callable)?
7. What happens when `materialize` is declared abstract but `row_mapper` is set —
   is the class still considered abstract by `inspect.isabstract`?
8. Should `row_mapper` live on `ReadQuery` (abstract layer) or only on
   `CypherReadQuery` (Cypher-specific layer)? The mapping seam is backend-agnostic.

### Constraints from existing code

- `ReadQuery.materialize` is `@abstractmethod` in `query/base_models.py:168`.
- `CypherExecutor.read` calls `query.materialize(dict(rec))` in
  `cypher/query_execution.py:101`.
- `_enforce_query_contract` in `query/base_models.py` does not currently validate
  `materialize`'s presence (ABC enforcement handles that). A `row_mapper` default
  would need to either remove the `@abstractmethod` on `materialize` or provide a
  concrete default implementation that calls `row_mapper`.
- The `__init_subclass__` auto-population pattern (E31/T6) sets `Output` from the
  generic arg. If `row_mapper` defaults to `Output.model_validate`, that binding must
  happen after `Output` is set — ordering in `__init_subclass__` matters.

---

## Design Question 2 — Expanding `CypherExecutor.write()` to optionally return created rows

### Current state

`CypherExecutor.write()` (`query_execution.py:103-134`):
1. Calls `tx.run(cypher, **params)` → returns a driver `Result`.
2. Immediately calls `CypherWriteResultSummary.from_neo4j_result(result)` which calls
   `result.consume().counters` — **consuming the cursor and discarding any rows**.
3. Passes only the five counters to `query.interpret_result(summary)`.

`RETURN` rows from a Cypher `CREATE` or `MERGE` are unreachable from `interpret_result`.
A write query that does:

```cypher
CREATE (m:Movie {title: $title}) RETURN m.title AS title, m.released AS released
```

will have those rows silently dropped.

### Proposed change

Make `CypherWriteResultSummary` carry **both** the mutation counters and an optional
list of returned rows. Change `from_neo4j_result` to collect rows before consuming:

```python
@dataclass
class CypherWriteResultSummary:
    nodes_created: int = 0
    # ... other counters ...
    rows: list[dict[str, Any]] = field(default_factory=list)  # NEW

    @classmethod
    def from_neo4j_result(cls, result: Any) -> "CypherWriteResultSummary":
        rows = [dict(rec) for rec in result]          # collect rows first
        summary = result.consume().counters           # then consume
        return cls(
            nodes_created=summary.nodes_created,
            # ...
            rows=rows,
        )
```

`interpret_result` then receives both counters and rows:

```python
class CreateMovie(CypherWriteQuery[CreateMovieParams, Movie]):
    def interpret_result(self, raw: WriteResultSummary) -> Movie:
        if not raw.rows:
            raise ValueError("CREATE returned no rows — check the RETURN clause")
        return Movie.model_validate(raw.rows[0])
```

### Questions to grill

1. Is collecting rows before consuming guaranteed safe with the neo4j Python driver?
   Does calling `list(result)` + `result.consume()` work, or does consuming
   invalidate the iteration cursor?
2. `WriteResultSummary` is currently a `Protocol` with five counter properties. Adding
   `rows: list[dict]` changes the protocol. Every test double that currently satisfies
   it would need `rows` too. Is that an acceptable breaking change, or should `rows`
   be optional (`rows: list[dict] = []`)?
3. Is the `rows` field the right place? Alternative: a separate `WriteRowResult` that
   is returned alongside the summary — i.e. `interpret_result(self, summary, rows)`.
   This avoids mutating the protocol but changes the abstract method signature.
4. Should row collection be opt-in (only when `cypher_template` contains a `RETURN`
   clause, detected at definition time) or always-on (collect rows for every write)?
   Always-on has a performance cost; opt-in adds complexity.
5. Generalisation boundary: is it reasonable to claim that returning the created entity
   from a write is **always** possible, or is this only valid for `CREATE ... RETURN`
   and not for `MERGE` (where the node may already exist) or batch `UNWIND` writes?
6. `CypherWriteResultSummary` is a `dataclass` that satisfies the `WriteResultSummary`
   protocol. If `rows` is added, what is the minimum change to keep all existing test
   doubles valid? (They currently do not set `rows`.)
7. What does the type signature of `interpret_result` look like after this change?
   `raw: WriteResultSummary` is currently `Any` at the abstract layer to stay
   vendor-free. Does that have to change?
8. Is this the right v0.1 decision, or should the correct answer be: "write queries
   return only counters in v0.1; echo-back requires a follow-up read; a
   `WriteQueryWithReturn` subclass is planned for v0.2"?

### Constraints from existing code

- `CypherWriteResultSummary` is in `cypher/query_execution.py:20-51`.
- `WriteResultSummary` protocol is in `query/write_result.py` (E31/T2).
- The protocol is `runtime_checkable` and is checked by an assertion at import time
  (`assert isinstance(CypherWriteResultSummary(), WriteResultSummary)`).
- The `_FakeWriteSummary` in the §05.01 notebook also satisfies the protocol; any
  new required field must be added there too.
- `CypherExecutor.write` is the single implementation site (`query_execution.py:103`).

---

## Scope

| ID | Question | ADR target |
|----|---------|------------|
| Q1 | `row_mapper` / eliminate mandatory `materialize()` for 1:1 | ADR-025 |
| Q2 | Expand `write()` to optionally surface `RETURN` rows | ADR-026 |

These are **design decisions only** in this epic. Implementation tasks will be split
into E33.impl (or folded into E31 remaining tasks) once the ADRs are written.

---

## Tasks

### T1 — Grill Q1 (`row_mapper` / materialize alternative)

Run `grill-with-docs` with the prompt in `.agentic/reviews/E33_grill_prompt.md`.
Record the decision in `decisions/025-read-query-row-mapper.md`.

**Acceptance criteria:**
- [ ] ADR-025 exists with a clear decision: implement `row_mapper`, reject it, or defer.
- [ ] If accepted: a concrete API shape (class variable name, type, validation rules,
      backward-compatibility story for existing `materialize` implementations).
- [ ] If rejected: the reason and what the correct long-term answer is.

---

### T2 — Grill Q2 (write query return expansion)

Run `grill-with-docs` with the prompt in `.agentic/reviews/E33_grill_prompt.md`.
Record the decision in `decisions/026-write-query-return-rows.md`.

**Acceptance criteria:**
- [ ] ADR-026 exists with a clear decision: expand `CypherWriteResultSummary.rows`,
      introduce `WriteQueryWithReturn`, or defer to v0.2.
- [ ] If accepted: driver compatibility verified (neo4j Python driver `list(result)`
      before `consume()` is safe); `WriteResultSummary` protocol change is bounded.
- [ ] If deferred: a clear statement of what the v0.1 ergonomic workaround is (follow-up
      read query after write).

---

### T3 — (post-grill) Implement accepted decisions

After T1 and T2 produce ADRs, split the implementation into independently-executable
tasks here (or extend E31).

---

## Success Criteria

- [ ] ADR-025 written (Q1 decision, whatever it is).
- [ ] ADR-026 written (Q2 decision, whatever it is).
- [ ] If either is accepted: implementation tasks defined, estimated, and unblocked.
- [ ] Notebook `05.01` updated to reflect accepted decisions (or a note that the API
      is unchanged pending the v0.2 milestone).
- [ ] No pilot consumer is blocked: the v0.1 workaround for each gap is documented.
