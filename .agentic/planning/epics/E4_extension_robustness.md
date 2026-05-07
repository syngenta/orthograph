# Epic E4: Extension Robustness & Consistency

> **Priority:** Medium
> **Origin:** Code review 2026-05-07 (sections 5, 6: Simplicity, Redundancy)
> **Goal:** Improve reliability and consistency of extension modules
> **Estimated tasks:** 3

---

## Context

The extension modules were built incrementally (Neo4j first, then Memgraph,
then GQLAlchemy). Each was developed as a self-contained unit, which was
correct for initial velocity. Now that all exist, some inconsistencies
have emerged: fragile class-name matching for backend detection, inconsistent
protocol implementation, and the Memgraph queries class not aligning with
the Neo4j QueryStrategy protocol.

---

## Task E4.1: Add Explicit Backend Parameter to GqlAlchemyClient

**Objective:** Replace the fragile `type(self._db).__name__` string matching in `GqlAlchemyClient._create_inspector()` with an explicit, user-controllable parameter.

**Context:** In `extensions/gqlalchemy/client.py:193-213`, the `_create_inspector()` method detects whether the database is Memgraph or Neo4j by checking `type(self._db).__name__`. This is fragile: subclasses, mock objects in tests, or future GQLAlchemy refactors could break it silently. An explicit parameter is more robust and more testable.

**Implementation:**

1. In `src/orthograph/extensions/gqlalchemy/client.py`, add a `backend` parameter to `__init__`:

```python
from typing import Literal

class GqlAlchemyClient:
    def __init__(
        self,
        model: GraphDataModel,
        db: Any,
        backend: Literal["neo4j", "memgraph"] | None = None,
    ) -> None:
        self._model = model
        self._db = db
        self._backend = backend or self._detect_backend()
        self._schema = generate_gqlalchemy_classes(model)
        self._validator = GraphValidator(model)

    def _detect_backend(self) -> str:
        """Detect backend from db client class name. Fallback heuristic."""
        client_name = type(self._db).__name__.lower()
        if "memgraph" in client_name:
            return "memgraph"
        return "neo4j"
```

2. Update `_create_inspector()` to use `self._backend` instead of re-detecting:

```python
def _create_inspector(self) -> Any:
    if self._backend == "memgraph":
        from orthograph.extensions.memgraph import MemgraphInspector
        driver = getattr(self._db, "_driver", None) or self._db.new_connection()
        return MemgraphInspector(driver=driver)
    from orthograph.extensions.neo4j import Neo4jInspector
    driver = getattr(self._db, "_driver", None) or self._db.new_connection()
    return Neo4jInspector(driver=driver)
```

3. Add `backend` property for read access:

```python
@property
def backend(self) -> str:
    """The detected or explicit backend type ('neo4j' or 'memgraph')."""
    return self._backend
```

4. Update tests in `tests/extensions/gqlalchemy/test_client.py`:
   - `test_explicit_backend_neo4j`
   - `test_explicit_backend_memgraph`
   - `test_auto_detect_backend_from_classname`

5. Update notebook 03.04 to show `backend=` parameter usage.

**Acceptance criteria:**
- `GqlAlchemyClient(model=m, db=db, backend="memgraph")` uses Memgraph inspector
- Auto-detection still works when `backend=None`
- Explicit parameter takes precedence over auto-detection
- All existing tests pass (they don't pass `backend=` so auto-detection is exercised)

---

## Task E4.2: Align MemgraphQueries with QueryStrategy Protocol

**Objective:** Make `MemgraphQueries` implement the `QueryStrategy` protocol from `neo4j/queries.py`, or extract a shared `InspectionQueries` protocol that both implement.

**Context:** `extensions/memgraph/queries.py` defines `MemgraphQueries` with methods `node_properties()`, `rel_properties()`, `constraints()`, and `cardinality()`. The `extensions/neo4j/queries.py` defines a `QueryStrategy` protocol with `node_labels()`, `rel_types()`, `node_properties()`, `rel_properties()`, `cardinality()`, and `constraints()`. The Memgraph class has the same concept but different interface (no `node_labels()`/`rel_types()`, different method signatures for `node_properties`). This inconsistency makes it harder to reason about backend capabilities.

**Implementation:**

Option A (recommended): Extract a minimal shared protocol to `extensions/base.py` or `extensions/protocols.py`:

```python
from typing import Protocol

class InspectionQueries(Protocol):
    """Protocol for backend-specific inspection queries."""
    def node_properties(self, label: str) -> str: ...
    def rel_properties(self, rel_type: str) -> str: ...
    def cardinality(self, label: str, rel_type: str) -> str: ...
    def constraints(self) -> str: ...
```

However, Memgraph's `node_properties()` takes no arguments (it returns ALL properties across all labels). The divergence is real -- the protocol can't be unified without changing behavior.

Option B (documentation-only): Document the intentional divergence in `.agentic/extensions/memgraph.md` and add a note in the code explaining why `MemgraphQueries` doesn't follow `QueryStrategy`.

Option C (align signatures): Modify `MemgraphQueries.node_properties()` to accept a `label` parameter (even if Memgraph's schema procedure returns all at once -- filter in Python). This creates API consistency:

```python
class MemgraphQueries:
    def node_properties(self, label: str | None = None) -> str:
        """Return all node type properties. Label parameter accepted for API
        consistency but Memgraph returns all labels in one call."""
        return "CALL schema.node_type_properties() ..."
```

Choose Option B for now (lowest risk). The divergence is intentional and well-handled by the inspectors.

1. Add a docstring to `MemgraphQueries` explaining the design choice:

```python
class MemgraphQueries:
    """Memgraph-specific queries for schema introspection.

    Note: This class does NOT follow the neo4j QueryStrategy protocol.
    Memgraph's schema procedures return all metadata in single calls
    (not per-label), so the inspector handles grouping internally.
    """
```

2. Add a note in `.agentic/extensions/memgraph.md` about this intentional divergence.

**Acceptance criteria:**
- Clear documentation explains why `MemgraphQueries` doesn't implement `QueryStrategy`
- No behavioral changes
- All existing tests pass

---

## Task E4.3: Complete GQLAlchemy Load Operations (G16/G17)

**Objective:** Implement `load_node()` and `load_relationship()` methods on `GqlAlchemyClient` with post-load validation.

**Context:** The progress tracker shows G16 (`load_node()`) and G17 (`load_relationship()`) as pending. These are the read-side counterparts to `save_node()` and `save_relationship()`. They should query the database for an entity and validate it against the model before returning.

**Implementation:**

1. In `src/orthograph/extensions/gqlalchemy/client.py`, add `load_node()`:

```python
def load_node(
    self,
    node_type: str,
    uid_value: Any,
) -> dict[str, Any]:
    """Load a node from the database and validate against the model.

    Args:
        node_type: The node label to query.
        uid_value: The value of the UID field to match.

    Returns:
        A validated property dict (with __label__).

    Raises:
        KeyError: If node_type is not in the model.
        GraphValidationError: If the loaded data fails validation.
        LookupError: If no node matches the query.
    """
    model_type = self._model.get_node_type(node_type)
    if model_type is None:
        raise KeyError(f"Unknown node type: {node_type}")

    uid_field = model_type.__uid_field__
    if uid_field is None:
        raise ValueError(f"Node type '{node_type}' has no __uid_field__ defined")

    # Query via GQLAlchemy
    gqa_cls = self._schema.get_node_class(node_type)
    query = f"MATCH (n:{node_type} {{{uid_field}: $uid}}) RETURN n"
    results = list(self._db.execute_and_fetch(query, {"uid": uid_value}))

    if not results:
        raise LookupError(f"No {node_type} node found with {uid_field}={uid_value!r}")

    # Convert to validation dict
    node_data = dict(results[0]["n"]._properties)
    node_data["__label__"] = node_type

    # Post-load validation
    result = self._validator.validate_nodes([node_data])
    result.raise_on_errors()

    return node_data
```

2. Add `load_relationship()` with similar pattern (query by endpoint UIDs + type).

3. Add tests in `tests/extensions/gqlalchemy/test_client.py`:
   - `test_load_node_valid`
   - `test_load_node_not_found`
   - `test_load_node_validation_failure`
   - `test_load_node_no_uid_field`
   - `test_load_relationship_valid`
   - `test_load_relationship_not_found`

4. Update progress.md: mark G16 and G17 as done.

5. Update notebook 03.04 to demonstrate load operations.

**Acceptance criteria:**
- `client.load_node("Person", "Alice")` returns validated dict
- Missing nodes raise `LookupError`
- Loaded data that fails validation raises `GraphValidationError`
- All existing tests pass + new tests pass
- Progress tracker updated
