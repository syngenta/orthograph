# Epic E32: BulkWriteQuery — First-Class Batch Write Contract

> **Priority:** Medium (post-v0.1.0; planned for v0.2.0)
> **Origin:** ADR-023 deferral (2026-06-16) — E30 session explicitly deferred bulk writes to their own scoping + implementation epic
> **Goal:** Introduce `BulkWriteQuery[P, R]` as a first-class base class with a distinct execution path, definition-time validation, and a `QUERY_BULK_PATTERN_DETECTED` INFO issue in `validate_query_catalogue`.
> **Blocked by:** E31 (query contract implementation — `interpret_result` rename, `WriteResultSummary` protocol, and generic auto-population must land first)
> **Blocks:** Nothing (additive)

---

## Why This Epic Exists

ADR-023 documents the deliberate decision not to ship a `BulkWriteQuery` in v0.1.0. The
convention `$items: list[dict]` + `UNWIND $items AS item` works at the driver level today, but
it carries three unresolved problems:

1. **No contract boundary.** A regular `WriteQuery` with a list param is indistinguishable from
   a bulk write. Teams can accidentally use `WriteQuery` for bulk operations without any library
   signal that they are in unsupported territory.

2. **No transaction semantics.** `CypherExecutor.write()` wraps the entire statement in a single
   `tx.run()` + `tx.commit()`. For a bulk write of 50,000 items, this is one enormous transaction
   with no batching, no progress, and no partial-commit option. This is acceptable for small
   batches but brittle for large ones.

3. **No validation.** `validate_query_catalogue` cannot fire `QUERY_BULK_PATTERN_DETECTED` until
   the concept of a bulk query exists in the type system — as ADR-023 explicitly requires.

This epic introduces the concept, closes all three gaps, and does so without touching the
existing `WriteQuery` / `CypherWriteQuery` contract.

---

## Design Decisions (pre-scoping)

These are the decisions that were not resolved in E30 and must be agreed before or during
implementation:

### D1 — What is the shape of `BulkWriteParams`?

**Option A:** The base requires a single `items: list[BaseModel]` field on `Params`. Items are
typed Pydantic models, serialised to dicts before the driver call.

**Option B:** The base requires a single `items: list[dict]` field on `Params`. Items are plain
dicts — no Pydantic validation on individual items.

**Option C:** `BulkWriteQuery` is generic over a third TypeVar `I` (item type): `BulkWriteQuery[P, I, R]`.
`P` is the query-level params (e.g. batch size, dry-run flag); `I` is the per-item type; `R` is
the result type. `items` lives outside `P`, passed separately to `execute()`.

**Recommended:** Option C. Separating query-level params from item data mirrors the existing
`ReadQuery[P, D]` shape and keeps the per-item type statically known without polluting `P`.
However, Option C requires a new executor signature (`write_bulk(query, items, raw_params)`)
which is a larger change. Option A is simpler and avoids a new executor method at the cost of
losing per-item type safety. **This decision must be made before T1.**

### D2 — What is the batching model?

**Option A:** No built-in batching. The entire `items` list is sent in one `UNWIND` transaction.
Document the size limit recommendation.

**Option B:** `BulkWriteQuery` declares a `batch_size: ClassVar[int] = 1000`. The executor
splits `items` into chunks of `batch_size` and runs one transaction per chunk.

**Option C:** `batch_size` is a runtime parameter (on `P` or passed to the executor directly),
not a ClassVar.

**Recommended:** Option B with `batch_size = 1000` as a sensible default that can be overridden
per-class. Option C is more flexible but adds complexity to the executor call site. Option A
leaves the blast-radius problem unaddressed.

### D3 — What does `interpret_result` receive for a bulk write?

With batching (D2 Option B), `interpret_result` is called once per batch transaction, receiving
a `WriteResultSummary` (from E31 T2). The final result `R` should be an aggregate across all
batches. The base class can provide a `_aggregate(results: list[R]) -> R` hook with a default
that sums `WriteResultSummary` fields.

**This decision is entangled with D1 and D2 and must be resolved before T3.**

---

## Scope

This epic is **implementation-only**. The design decisions above (D1–D3) must be resolved in a
brief scoping conversation before T1 begins. If any of D1–D3 is still open when implementation
starts, the implementing agent must surface the conflict and pause.

---

## Task Index

| ID | Title | Group | Depends on | ADR |
|----|-------|-------|-----------|-----|
| T1 | Define `BulkWriteQuery[P, R]` abstract base in `orthograph.query` | A | D1, D2 resolved | new ADR |
| T2 | Define `CypherBulkWriteQuery[P, R]` in `orthograph.cypher` | A | T1 | — |
| T3 | Add `write_bulk()` to `Executor` and `CypherExecutor` | B | T1, T2, D2, D3 resolved | — |
| T4 | Add `QUERY_BULK_PATTERN_DETECTED` INFO issue to `validate_query_catalogue` | C | T2 | ADR-023 |
| T5 | Add `BulkWriteParams` helper (optional mixin or base) | A | T1 | — |
| T6 | Update `QueryCatalogue` to register and describe bulk write queries | D | T1 | — |
| T7 | Write unit tests for `BulkWriteQuery` contract and `CypherBulkWriteQuery` | E | T2 | — |
| T8 | Write integration tests for `CypherExecutor.write_bulk()` batching | E | T3 | — |
| T9 | Add notebook section to `04.01` demonstrating `CypherBulkWriteQuery` | F | T2, T3 | — |
| T10 | Remove E31 T13 convention documentation and replace with `BulkWriteQuery` usage | F | T1 | — |

---

## Tasks

---

### T1 — Define `BulkWriteQuery[P, R]` abstract base in `orthograph.query`

**Depends on:** D1 and D2 resolved (see Design Decisions above)
**File:** `src/orthograph/query/base_models.py`

**What to implement:**

```python
class BulkWriteQuery(ABC, Generic[P, R]):
    """Abstract generic base for typed bulk write queries.

    A bulk write executes a single parametrised Cypher statement once per batch
    of items. Items are passed as a list and split into batches of ``batch_size``
    by the executor — each batch runs in its own transaction.

    Subclasses MUST define:
      - ``Params``     — Pydantic model for query-level params (dry_run, etc.)
                         Does NOT include the items list.
      - ``ItemModel``  — Pydantic model for a single item in the batch.
      - ``name``       — unique string identifier within a catalogue
      - ``backend``    — Backend enum value
      - ``batch_size`` — number of items per transaction (default: 1000)

    Abstract methods:
      - ``build(params)``            — returns (cypher, {}) — item binding is
                                       handled by the executor via UNWIND
      - ``interpret_result(raw)``    — interprets one batch's WriteResultSummary
      - ``aggregate(results)``       — combines per-batch results into final R
    """

    Params: ClassVar[type[BaseModel]]
    ItemModel: ClassVar[type[BaseModel]]
    name: ClassVar[str]
    backend: ClassVar[Backend]
    batch_size: ClassVar[int] = 1000

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return
        _enforce_query_contract(
            cls,
            model_attrs=("Params", "ItemModel"),
            other_attrs=("name", "backend"),
        )

    @abstractmethod
    def build(self, params: P) -> Any:
        """Pure construction — returns (cypher, query-level-params dict).
        The executor injects items as $items; do not include $items in build()."""

    @abstractmethod
    def interpret_result(self, raw: WriteResultSummary) -> R:
        """Interprets the WriteResultSummary for one batch transaction."""

    def aggregate(self, results: list[R]) -> R:
        """Combines per-batch results into the final return value.
        Default implementation: return the last result. Override for summation."""
        return results[-1]
```

**Key design choices encoded:**
- `ItemModel` ClassVar (not `items` on `Params`) — keeps per-item type separate from query-level params (D1 Option C variant adapted for ClassVar pattern).
- `batch_size` ClassVar with default 1000 (D2 Option B).
- `aggregate()` is non-abstract with a sensible default — subclasses that need summation override it.
- `interpret_result` receives `WriteResultSummary` directly (from E31 T2) — not the raw driver object.

**Acceptance criteria:**
- A concrete subclass that omits `ItemModel` raises `TypeError` at class-definition time.
- A concrete subclass that omits `Params` raises `TypeError` at class-definition time.
- `BulkWriteQuery` is not a subclass of `WriteQuery` — they are siblings under `ABC`. Confirm with `assert not issubclass(BulkWriteQuery, WriteQuery)`.
- `batch_size` defaults to 1000 and can be overridden per class.

---

### T2 — Define `CypherBulkWriteQuery[P, R]` in `orthograph.cypher`

**File:** `src/orthograph/cypher/base_models.py`
**Depends on:** T1

**What to implement:**

```python
class CypherBulkWriteQuery(BulkWriteQuery[P, R], Generic[P, R]):
    """Abstract base for typed Cypher bulk write queries.

    Declarative style: set ``cypher_template`` to a Cypher string containing
    ``UNWIND $items AS item``. The executor injects the serialised item list
    as ``$items`` automatically — do not include ``$items`` in ``Params``.

    The ``<<name>>`` identifier mechanism works identically to
    ``CypherWriteQuery``.

    Example::

        class CreatePeople(CypherBulkWriteQuery[NoParams, int]):
            name = "people.create_bulk"
            ItemModel = PersonParams
            cypher_template = (
                "UNWIND $items AS item"
                " CREATE (p:Person {name: item.name, age: item.age})"
            )

            def interpret_result(self, raw: WriteResultSummary) -> int:
                return raw.nodes_created

            def aggregate(self, results: list[int]) -> int:
                return sum(results)
    """

    backend = Backend.CYPHER
    cypher_template: ClassVar[str]
    Identifiers: ClassVar[type[BaseModel]] = NoIdentifiers

    def __init__(self, identifiers: BaseModel | dict[str, Any] | None = None) -> None:
        identifiers = {} if identifiers is None else identifiers
        self._identifiers = type(self).Identifiers.model_validate(identifiers)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _validate_bulk_cypher(cls)  # see below

    def build(self, params: P) -> CypherQuery:
        """Returns (rendered_cypher, params.model_dump()).
        $items is NOT in the returned dict — the executor injects it."""
        cypher = getattr(type(self), "cypher_template", None)
        if cypher is None:
            raise NotImplementedError(
                f"{type(self).__name__}: no cypher_template defined and build() not overridden"
            )
        rendered = render_with_identifiers(cast(str, cypher), self._identifiers)
        return rendered, params.model_dump()
```

**New helper `_validate_bulk_cypher(cls)`** (add to `cypher/base_models.py`):
- Same as `_validate_declarative_cypher` but additionally:
  - Checks the template contains `UNWIND $items` (case-insensitive). If absent, raises `CypherQueryDefinitionError`: "BulkWriteQuery template must contain UNWIND $items".
  - Checks `$items` is NOT in `Params.model_fields` — the executor owns `$items`. If present, raises `CypherQueryDefinitionError`: "$items must not be declared on Params; it is injected by the executor".

**Acceptance criteria:**
- A `CypherBulkWriteQuery` subclass without `UNWIND $items` in its template raises `CypherQueryDefinitionError` at class-definition time.
- A `CypherBulkWriteQuery` subclass with `$items` on its `Params` raises `CypherQueryDefinitionError` at class-definition time.
- A valid `CypherBulkWriteQuery` subclass instantiates without error.
- `build()` returns a `(str, dict)` tuple where the dict does NOT contain `items`.

---

### T3 — Add `write_bulk()` to `Executor` and `CypherExecutor`

**Depends on:** T1, T2, D2 and D3 resolved
**Files:** `src/orthograph/query/base_models.py`, `src/orthograph/cypher/query_execution.py`

**Abstract method on `Executor`:**

```python
@abstractmethod
def write_bulk(
    self,
    query: BulkWriteQuery[P, R],
    items: list[Any],
    raw_params: Any,
) -> R:
    """Execute a bulk write: split items into batches, run one transaction
    per batch, aggregate results."""
```

**Concrete implementation on `CypherExecutor`:**

```python
def write_bulk(
    self,
    query: CypherBulkWriteQuery[P, R],
    items: list[Any],
    raw_params: Any,
) -> R:
    """Validate params → build → split into batches → execute one tx per batch → aggregate."""
    params = cast(P, query.Params.model_validate(raw_params))
    cypher, qparams = query.build(params)
    self._validate_cypher(cypher, query.name)

    # Serialise items to dicts using ItemModel for validation
    serialised = [query.ItemModel.model_validate(item).model_dump() for item in items]

    # Split into batches
    batch_size = type(query).batch_size
    batches = [serialised[i:i + batch_size] for i in range(0, len(serialised), batch_size)]

    batch_results: list[R] = []
    for batch in batches:
        with self._driver_factory() as session:
            tx = session.begin_transaction()
            try:
                result = tx.run(cypher, **qparams, items=batch)
                summary = CypherWriteResultSummary.from_result(result)
                batch_results.append(query.interpret_result(summary))
                tx.commit()
            except BaseException:
                try:
                    tx.rollback()
                except Exception:
                    pass
                raise

    return query.aggregate(batch_results)
```

**Key implementation notes:**
- `items=batch` is passed as a keyword arg alongside `**qparams`. This is why `$items` must not appear on `Params` (enforced by T2).
- `ItemModel.model_validate(item)` validates each item before serialisation. An invalid item raises `ValidationError` before the first transaction opens — fail fast.
- Each batch is a separate transaction. A failure mid-batch raises and propagates; already-committed batches are NOT rolled back (this is documented behaviour — see T9).
- `CypherWriteResultSummary.from_result(result)` — a factory on the class introduced in E31 T2.

**Acceptance criteria:**
- `write_bulk` with 2500 items and `batch_size=1000` opens exactly 3 transactions.
- An invalid item (fails `ItemModel` validation) raises `ValidationError` before any transaction opens.
- A transaction failure on batch 2 of 3 leaves batch 1 committed (no global rollback). This is tested and documented.
- `write_bulk` with an empty `items` list returns `query.aggregate([])` — document the expected default behaviour (empty aggregate).

---

### T4 — Add `QUERY_BULK_PATTERN_DETECTED` INFO issue to `validate_query_catalogue`

**Depends on:** T2
**File:** `src/orthograph/cypher/validation.py`
**Required by:** ADR-023

**What to implement:**

In `validate_query_catalogue`, after the existing Cypher validation loop, add a pass over
`query_catalogue.queries()` that checks each non-`BulkWriteQuery` Cypher query for the presence
of `UNWIND $items` in its template. If found, emit a `QUERY_BULK_PATTERN_DETECTED` INFO issue:

```
"Query '{name}' uses UNWIND $items but is not a BulkWriteQuery. "
"Consider subclassing CypherBulkWriteQuery for explicit batch semantics and item validation."
```

**Why not fire for `BulkWriteQuery` instances:** `BulkWriteQuery` templates are expected to
contain `UNWIND $items` — the presence is required, not suspicious.

**The detection regex:** `re.search(r"UNWIND\s+\$items\b", template, re.IGNORECASE)`. This
distinguishes `UNWIND $items AS item` (bulk pattern) from `UNWIND keys(n) AS key` (inspection
pattern — no `$` prefix).

**Acceptance criteria:**
- A catalogue containing a plain `CypherWriteQuery` with `UNWIND $items` in its template emits exactly one `QUERY_BULK_PATTERN_DETECTED` INFO issue for that query.
- A catalogue containing a `CypherBulkWriteQuery` with `UNWIND $items` emits no `QUERY_BULK_PATTERN_DETECTED` issue.
- Existing inspection templates (`UNWIND keys(n)`) emit no `QUERY_BULK_PATTERN_DETECTED` issue (no `$` prefix).
- All existing `test_validate_query_catalogue.py` tests continue to pass.

---

### T5 — Add `BulkWriteParams` optional mixin

**Depends on:** T1
**File:** `src/orthograph/query/pagination.py` (extend existing file from E31 T8) or new `src/orthograph/query/bulk.py`

**What to implement:**

```python
class BulkWriteParams(BaseModel):
    """Optional mixin for BulkWriteQuery Params that adds common batch-control fields.

    Compose into a Params model when you need dry-run or batch override:

        class CreatePeopleParams(BulkWriteParams):
            source_id: str
    """
    dry_run: bool = False
    batch_size_override: int | None = None
```

Re-export from `orthograph.query.__init__`.

**Note:** `batch_size_override` on the params model takes precedence over the ClassVar
`batch_size` in `CypherExecutor.write_bulk()` — the executor checks `raw_params.get("batch_size_override")` after validation.

**Acceptance criteria:**
- `from orthograph.query import BulkWriteParams` works.
- A `BulkWriteQuery` subclass with `Params = SomeModel(BulkWriteParams)` passes contract enforcement.
- `batch_size_override=500` on params causes the executor to use 500 as the effective batch size.

---

### T6 — Update `QueryCatalogue` to register and describe bulk write queries

**Depends on:** T1
**File:** `src/orthograph/query/catalogue.py`

**What to implement:**
- Add `register_bulk_write(query: BulkWriteQuery[P, R]) -> BulkWriteQuery[P, R]` method — same duplicate-name guard as `register_write`.
- Add `_bulk_writes: dict[str, BulkWriteQuery[Any, Any]]` to `__init__`.
- Update `queries()` to include bulk write instances.
- Update `describe()` to emit `QueryDescription` for bulk writes:
  - `kind="bulk_write"` (new literal — add to `Literal["read", "write", "bulk_write"]` on `QueryDescription`)
  - `params_schema=q.Params.model_json_schema()`
  - `output_schema=q.Output.model_json_schema() if getattr(q, "Output", None) else None`
  - New field `item_schema: dict[str, Any] | None` — `q.ItemModel.model_json_schema()` for bulk writes, `None` for all others. Add this field to `QueryDescription`.

**Acceptance criteria:**
- `catalogue.register_bulk_write(query)` followed by `catalogue.describe()` returns a `QueryDescription` with `kind="bulk_write"` and a non-None `item_schema`.
- Duplicate name across read/write/bulk_write raises `ValueError`.
- `catalogue.queries()` includes bulk write instances.

---

### T7 — Unit tests for `BulkWriteQuery` contract and `CypherBulkWriteQuery`

**Depends on:** T2
**Files:**
- `tests/query/test_bulk_write_base_models.py` (new)
- `tests/cypher/test_bulk_write_base_models.py` (new)

**Test cases for `tests/query/test_bulk_write_base_models.py`:**
- `test_bulk_write_missing_item_model_raises` — omit `ItemModel`, confirm `TypeError`.
- `test_bulk_write_missing_params_raises` — omit `Params`, confirm `TypeError`.
- `test_bulk_write_default_batch_size` — confirm `batch_size == 1000`.
- `test_bulk_write_batch_size_override` — subclass with `batch_size = 500`, confirm value.
- `test_bulk_write_aggregate_default` — `aggregate([r1, r2, r3])` returns `r3`.
- `test_bulk_write_is_not_subclass_of_write_query` — confirm type hierarchy.

**Test cases for `tests/cypher/test_bulk_write_base_models.py`:**
- `test_cypher_bulk_write_missing_unwind_raises` — template without `UNWIND $items` raises `CypherQueryDefinitionError`.
- `test_cypher_bulk_write_items_on_params_raises` — `Params` with `items` field raises `CypherQueryDefinitionError`.
- `test_cypher_bulk_write_valid_definition` — valid subclass instantiates, `build()` returns `(str, dict)` without `items` key.
- `test_cypher_bulk_write_identifier_injection` — template with `<<label>>` + `Identifiers` works correctly.
- `test_cypher_bulk_write_backend_is_cypher` — confirm `backend == Backend.CYPHER`.

---

### T8 — Integration tests for `CypherExecutor.write_bulk()` batching

**Depends on:** T3
**File:** `tests/cypher/test_write_bulk_execution.py` (new)

**Test cases (use a fake driver — no live DB required):**
- `test_write_bulk_splits_into_correct_number_of_batches` — 2500 items, `batch_size=1000` → 3 `tx.run()` calls. Use a `Mock` driver that records calls.
- `test_write_bulk_validates_items_before_first_transaction` — invalid item at index 0 raises `ValidationError`, zero `tx.run()` calls.
- `test_write_bulk_invalid_item_mid_list` — invalid item at index 1500 (in batch 2) raises `ValidationError` before any transactions (validation is upfront).
- `test_write_bulk_transaction_failure_on_batch_2` — batch 2 raises; batch 1 already committed; exception propagates.
- `test_write_bulk_empty_items_returns_aggregate_of_empty` — `items=[]` → no transactions, returns `query.aggregate([])`.
- `test_write_bulk_batch_size_override_via_params` — `BulkWriteParams(batch_size_override=500)` causes 5 transactions for 2500 items.
- `test_write_bulk_aggregate_called_with_all_batch_results` — confirm `aggregate` receives one result per batch.

---

### T9 — Add notebook section to `04.01` demonstrating `CypherBulkWriteQuery`

**Depends on:** T2, T3
**File:** `notebooks/04.01_typed_cypher_queries.ipynb`

**New section (add after the existing write query section):**

1. **When to use `CypherBulkWriteQuery`** — prose explaining the difference from `WriteQuery`; when to use each; the partial-commit semantics (already-committed batches are not rolled back on failure).
2. **Defining a bulk write query** — concrete example: `CreatePeople(CypherBulkWriteQuery[NoParams, int])` with `ItemModel = PersonParams`, `UNWIND $items AS item CREATE (...)`.
3. **Executing** — `executor.write_bulk(query, items=[...], raw_params={})`.
4. **Batching** — show `batch_size` ClassVar override; show `BulkWriteParams` with `batch_size_override`.
5. **Aggregating results** — show a custom `aggregate()` that sums `nodes_created` across batches.
6. **Validation at definition time** — show what happens when `UNWIND $items` is missing (error cell).

**Acceptance criteria:**
- All code cells are syntactically valid Python.
- The partial-commit semantics are explicitly documented in prose.

---

### T10 — Remove E31 T13 convention documentation; replace with `BulkWriteQuery` usage

**Depends on:** T1
**Files:**
- Getting Started guide or `notebooks/04.01` (wherever E31 T13 placed the convention docs)
- `src/orthograph/query/base_models.py` docstring for `WriteQuery`

**What to change:**
- Remove or update the "bulk write convention" documentation added by E31 T13.
- Replace "use `$items: list[dict]` on `Params`..." with "use `CypherBulkWriteQuery` — see notebook `04.01` section N".
- Update `WriteQuery` docstring: remove the sentence about `list[dict]` convention; add "For batch operations use `BulkWriteQuery`."

**Acceptance criteria:**
- No documentation in `src/` or `notebooks/` recommends the manual `UNWIND $items` convention on a plain `WriteQuery`.
- `WriteQuery` docstring references `BulkWriteQuery` as the correct path for batch operations.

---

## Execution Order

```
D1, D2, D3 resolved (scoping) ──► T1 ──┬──► T2 ──┬──► T3 ──► T8
                                        │         ├──► T4
                                        │         ├──► T7
                                        │         └──► T9 (after T3)
                                        ├──► T5
                                        ├──► T6
                                        └──► T10
```

T1 is the single critical-path gate. All other tasks are unblocked once T1 + T2 land.

---

## Acceptance Criteria for E32

- [ ] D1, D2, D3 resolved in a scoping conversation before T1 begins
- [ ] `BulkWriteQuery` and `CypherBulkWriteQuery` are importable from `orthograph.query` and `orthograph.cypher` respectively
- [ ] `CypherExecutor.write_bulk()` exists and batches correctly
- [ ] `validate_query_catalogue` emits `QUERY_BULK_PATTERN_DETECTED` for non-bulk queries using `UNWIND $items`
- [ ] `QueryCatalogue.describe()` emits `kind="bulk_write"` with `item_schema` for registered bulk write queries
- [ ] All unit and integration tests pass
- [ ] Notebook `04.01` has a `CypherBulkWriteQuery` section with partial-commit semantics documented
- [ ] No documentation remains recommending the manual `UNWIND $items` convention on plain `WriteQuery`
- [ ] An ADR is written for the D1/D2/D3 decisions

---

## Constraints and Non-Goals

- **No async support.** Async driver execution is deferred (per `overview.md` deferred table).
- **No global transaction across batches.** Each batch is its own transaction. Cross-batch atomicity is explicitly out of scope — document, don't implement.
- **No streaming/cursor-based bulk reads.** This epic is write-only. Paginated reads are covered by `PaginatedParams` (E31 T8).
- **GQLAlchemy bulk writes are out of scope.** `GqlAlchemyBulkWriteQuery` can be added when a GQLAlchemy executor exists (deferred per ADR-021).
- **No production code from E30.** E32 depends on E31 completing first.
