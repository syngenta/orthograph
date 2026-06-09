# Epic E15: Typed Cypher Catalogue Backend

> **STATUS: RETIRED — superseded by [E16](E16_query_catalogue_unified.md)**
> E15 tasks E15.1–E15.4 are adopted verbatim into E16 as T7. The `to_definition()` bridge
> method (E16 T6) is added to `CypherReadQuery`. Do not pick up new work from this file.

---

> **Priority:** High
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Add typed `CypherReadQuery` / `CypherExecutor` base classes implementing the E13
> contract, so graph queries can register into `QueryCatalogue` and return domain `NodeModel`
> instances — distinct from the string-key `CypherQueryCatalogue` in E6.
> **Blocked by:** E13
> **Parallel with:** E14

---

## Context

E6's `CypherQueryCatalogue` uses named string dispatch: `catalogue.execute("query_name", ...)`.
That is correct for its use case (external YAML-configured queries, schema-validated at
registration). It is **not** the typed materialise contract needed for `ReadQuery[P, D]` where
the Python type checker knows that the output is `list[Sample]` at the call site.

This epic adds the typed Cypher layer: `CypherReadQuery` subclasses `ReadQuery[P, D]` (from E13);
its `build()` returns a `(cypher_string, params_dict)` pair; its `materialize()` maps a driver
record dict to the declared domain `NodeModel`. The `CypherExecutor` is the single graph-driver
seam, paralleling `SqlExecutor` for the relational side.

**These two Cypher catalogue tiers coexist and serve different use cases.** Document the choice:
- E6 `CypherQueryCatalogue`: use when queries are YAML-configured or schema-validated at
  registration; string-key dispatch; returns untyped records.
- E15 `CypherReadQuery`/`CypherExecutor`: use when you need a typed domain-object-returning
  query registered in a `QueryCatalogue` alongside SQL queries, with IDE type safety.

**Reference implementation:** `pocs/p02_matterforge_slice/orthograph_ext/graph.py` (the `GraphStore`
fake + `CypherReadQuery` + `CypherExecutor`). For real driver integration, the `CypherExecutor`
replaces `GraphStore.run()` with `driver.session().run(cypher, params)`.

---

## Tasks

### E15.1: `CypherReadQuery` and `CypherWriteQuery` base classes

**What:** Backend-specific bases that fix `build()` return type and `backend` tag for Cypher.

**Actions:**
1. Create `src/orthograph/extensions/cypher/typed_queries.py` (alongside existing `generator.py`,
   `parser.py` — does not replace them):
   ```python
   from orthograph.catalogue.typed import Backend, ReadQuery, WriteQuery

   class CypherReadQuery(ReadQuery[P, D], Generic[P, D]):
       """build() returns (cypher: str, params: dict).
       materialize() maps a graph record dict to the declared Output NodeModel."""
       backend = Backend.CYPHER

       def build(self, params: P) -> tuple[str, dict]: ...    # abstract
       def materialize(self, raw: dict) -> D: ...              # abstract
       # raw keys follow the graph driver's return projection (e.g. "s.sample_id")

   class CypherWriteQuery(WriteQuery[P, R], Generic[P, R]):
       backend = Backend.CYPHER
       def build(self, params: P) -> tuple[str, dict]: ...     # abstract
       def interpret_result(self, raw: Any) -> R: ...          # abstract
   ```
2. Tests (no graph driver — R1):
   - `CypherReadQuery.build()` returns a `(str, dict)` tuple; no driver needed.
   - `CypherReadQuery.materialize()` with a hand-built fake record dict returns the declared
     `Output` type (a real orthograph `NodeModel` instance).
   - Two `CypherReadQuery`s with the same `Output` type but different Cypher have identical
     `Output.model_json_schema()` (port-swappability proof at the schema level).

**Verification:** `from orthograph.extensions.cypher import CypherReadQuery` works.

---

### E15.2: `CypherExecutor` — the graph driver seam

**What:** Concrete `Executor` for graph databases. Parallel to `SqlExecutor`.

**Actions:**
1. Create `src/orthograph/extensions/cypher/executor.py`:
   ```python
   class CypherExecutor(Executor):
       """The single I/O seam for graph databases.

       Accepts any graph driver whose session supports .run(cypher, **params)
       returning an iterable of records (neo4j, memgraph, etc.).
       Connections are NEVER owned (Constraint 13); a driver_factory is passed in.

       Example (neo4j):
           from neo4j import GraphDatabase
           executor = CypherExecutor(lambda: GraphDatabase.driver(URI).session())

       Example (test fake):
           executor = CypherExecutor(lambda: FakeGraphSession(records))
       """
       def __init__(self, driver_factory: Callable) -> None:
           self._driver_factory = driver_factory

       def read(self, query: CypherReadQuery[P, D], raw_params: Any) -> list[D]:
           params = query.Params.model_validate(raw_params)    # R4
           cypher, qparams = query.build(params)               # R1 — pure
           with self._driver_factory() as session:             # only I/O seam
               records = list(session.run(cypher, **qparams))
           return [query.materialize(dict(rec)) for rec in records]   # R3

       def write(self, query: CypherWriteQuery[P, R], raw_params: Any) -> R:
           params = query.Params.model_validate(raw_params)
           cypher, qparams = query.build(params)
           with self._driver_factory() as session:
               result = session.run(cypher, **qparams)
               # note: graph transactions are driver-managed; document the session contract
           return query.interpret_result(result)
   ```
2. Tests with a **fake graph session** (no live database):
   - `FakeGraphSession` is a small inner class in the test file: takes a fixed list of record
     dicts, returns them on `run()`.
   - `read()` materialises fake records into the declared `Output` NodeModel instances.
   - Bad params prevent `run()` from being called at all.
3. Live tests behind `--neo4j` / `--memgraph` flags (consistent with existing test pattern).

---

### E15.3: Same port, different executors — integration proof

**What:** A test proving that swapping `CypherExecutor` for `SqlExecutor` behind a `ReadPort`
produces identical domain output — the end-to-end proof of the swappable-read-store claim.

**Actions:**
1. Write `tests/extensions/test_typed_catalogue_integration.py`:
   ```python
   def test_sql_and_cypher_backends_return_identical_domain_output():
       """The ReadPort abstraction: both stores return list[Sample] with identical content."""
       # SQL path
       sql_q = FakeSqlSamplesByProtocol()
       sql_ex = SqlExecutor(lambda: Session(engine))
       # Cypher path
       cypher_q = FakeCypherSamplesByProtocol()
       cypher_ex = CypherExecutor(lambda: FakeGraphSession(GRAPH_RECORDS))

       sql_results = sql_ex.read(sql_q, {"protocol_id": 1})
       cypher_results = cypher_ex.read(cypher_q, {"protocol_id": 1})

       assert sql_results == cypher_results  # same domain objects, different raw sources
   ```
   (`FakeSqlSamplesByProtocol` and `FakeCypherSamplesByProtocol` are test-internal implementations
   of `SqlReadQuery`/`CypherReadQuery` that materialise from different raw shapes into the same
   `Sample` NodeModel.)

**Verification:** This test passes. It is the clearest proof that the architecture works — include
it in the orthograph notebook (`04.02_typed_query_catalogue.ipynb`).

---

### E15.4: Export and notebook

**Actions:**
1. Export from `orthograph.extensions.cypher`: `CypherReadQuery`, `CypherWriteQuery`,
   `CypherExecutor`.
2. Create notebook `notebooks/04.02_typed_query_catalogue.ipynb` demonstrating:
   - Define a `NodeModel`.
   - Define a `CypherReadQuery` returning that model.
   - Register it in a `QueryCatalogue`.
   - `describe()` output.
   - Run against a fake graph session.
   - The same `ReadPort` with a `SqlReadQuery` + `SqlExecutor`.

---

## Relationship to Other Epics

- **E13** — implements the contract defined there.
- **E6** — coexists with the string-key `CypherQueryCatalogue`; adds a typed layer alongside it.
- **E14** — parallel; the SQLAlchemy backend does the same for the relational side.
- **E12** — E15's `CypherReadQuery`/`CypherExecutor` and E14's `SqlReadQuery`/`SqlExecutor` share
  the same abstract base (E13). E12 may acknowledge E13 as the unified typed interface and narrow
  its own scope to the string-key tier.
- **matterforge E9** — imports `CypherReadQuery`/`CypherExecutor` from here once landed.
