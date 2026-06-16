# Epic E29: `__uid_field__` Hardening

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness
> **Origin:** Code review 2026-06-15 — senior review of `NodeModel.__uid_field__` design.
> **Goal:** Close three concrete gaps in `__uid_field__` safety: definition-time field-name
> validation, rejection of nullable UID fields, and elimination of the phantom-key
> fallback in relationship endpoint resolution.
> **Blocked by:** None — all three tasks are independent of each other and of all other epics.
> **ADR:** [ADR-019](../../decisions/019-uid-field-natural-key-identity.md)

---

## Context

`NodeModel.__uid_field__` names the property that carries node identity. It drives
idempotent upserts (`MERGE`), uniqueness-constraint generation, relationship endpoint
anchoring, and referential-integrity indexing. Three gaps were identified in the
current implementation:

1. **No definition-time guard.** A typo in `__uid_field__` (e.g. `"naem"`) is not
   caught at class definition time. The error surfaces deep inside the Cypher
   generator or validator, far from the mistake.

2. **No rejection of nullable UIDs.** A field declared as `name: str | None` is
   accepted as a UID. A nullable UID makes `MERGE` ambiguous and renders uniqueness
   constraints ineffective.

3. **Phantom-key fallback in `_rel_query`.** When a node type used as a relationship
   endpoint has no `__uid_field__`, the generator silently uses the literal string
   `"uid"` as the property key. This bypasses the model guard (ADR-008), generates
   Cypher that matches zero nodes, and raises no error.

Each task below is fully self-contained. An agent can execute any one of them without
context from the others. Read the task's **Files to read first** list, make only the
changes described, and verify against the stated acceptance criteria before closing.

---

## T1: Definition-time validation of `__uid_field__`

> **Effort:** Small — one method, one exception message, two new tests.
> **Files changed:** `src/orthograph/graph_definition/models.py`,
> `tests/graph_definition/test_models.py` (or nearest equivalent test file).

### What to do

Extend `NodeModel.__init_subclass__` (currently at
`src/orthograph/graph_definition/models.py:27`) to validate `__uid_field__` whenever
the subclass sets it in its own `__dict__`.

Add these two checks immediately after the existing `__label__` guard:

**Check A — field name exists on the model:**

```python
uid_field = cls.__dict__.get("__uid_field__")
if uid_field is not None:
    declared = cls.get_property_specs()
    if uid_field not in declared:
        raise MissingClassVarError(
            f"{cls.__name__}.__uid_field__ = {uid_field!r} is not a declared "
            f"property. Declared properties: {sorted(declared)}"
        )
```

**Check B — the named field is not nullable:**

```python
    spec = declared[uid_field]
    if not spec.is_required:
        raise MissingClassVarError(
            f"{cls.__name__}.__uid_field__ = {uid_field!r} is declared as an "
            f"optional (nullable) property. A UID field must be required (non-None). "
            f"Change the annotation from `{uid_field}: <type> | None` to "
            f"`{uid_field}: <type>`."
        )
```

`TypeInfo.is_required` is `False` when the property annotation is `X | None` or
`Optional[X]` — see `src/orthograph/graph_definition/property_spec.py:30`.
`MissingClassVarError` is already imported from
`src/orthograph/graph_definition/exceptions.py`.

### Files to read first

1. `src/orthograph/graph_definition/models.py` — full file (186 lines).
2. `src/orthograph/graph_definition/property_spec.py` — full file (43 lines).
3. `src/orthograph/graph_definition/exceptions.py` — full file (13 lines).
4. The existing `NodeModel` test file — find it with:
   `grep -r "class.*NodeModel" tests/ --include="*.py" -l`

### Acceptance criteria

- [ ] Defining a `NodeModel` subclass with `__uid_field__ = "naem"` when only `name`
      is declared raises `MissingClassVarError` at import / class-definition time.
      The error message contains the class name, the bad field name, and the list of
      declared properties.
- [ ] Defining a `NodeModel` subclass with `__uid_field__ = "name"` where `name` is
      declared as `name: str | None` raises `MissingClassVarError` at class-definition
      time. The error message names the class and explains the field must be required.
- [ ] A valid subclass (`__uid_field__ = "name"`, `name: str`) continues to be defined
      without error.
- [ ] A subclass with no `__uid_field__` is unaffected (the check is guarded by
      `uid_field is not None`).
- [ ] All existing tests pass (`pytest` green).

### Verification command

```
pytest tests/ -x -q
```

---

## T2: Eliminate the `or "uid"` phantom-key fallback in `_rel_query`

> **Effort:** Small — two lines replaced, two existing helpers reused, one new test.
> **Files changed:** `src/orthograph/cypher/generator.py`,
> `tests/cypher/test_generator.py`.

### What to do

In `CypherGenerator._rel_query`
(`src/orthograph/cypher/generator.py:178`), replace the two fallback lines:

```python
# BEFORE (lines 195-196)
src_uid_field = src_node_type.__uid_field__ or "uid"
tgt_uid_field = tgt_node_type.__uid_field__ or "uid"
```

with explicit `_require_uid` calls:

```python
# AFTER
_, src_uid_field = CypherGenerator._require_uid(src_node_type)
_, tgt_uid_field = CypherGenerator._require_uid(tgt_node_type)
```

`_require_uid` (at `generator.py:321`) already raises `MissingUidFieldError` with
a message naming the node type. Update its error message to also name the relationship
and the endpoint role (source or target). To do that, pass the context as an argument
or extend the message after the call — for example:

```python
def _require_uid_for_endpoint(
    node_type: type[NodeModel],
    rel_label: str,
    role: str,        # "source" or "target"
) -> tuple[str, str]:
    uid_field = node_type.__uid_field__
    if uid_field is None:
        raise MissingUidFieldError(
            f"Cannot generate a relationship query for {rel_label!r}: "
            f"the {role} node type {node_type.__label__!r} declares no __uid_field__."
        )
    label = validate_identifier(node_type.__label__, kind="label")
    validate_identifier(uid_field, kind="property key")
    return label, uid_field
```

Add this as a private static method or inline helper in the generator; replace
`_require_uid` calls in `_rel_query` with it.

The existing `_require_uid` method is used by `match_by_uid_query`,
`merge_query`, and `delete_by_uid_query` — do not change those call sites.

### Files to read first

1. `src/orthograph/cypher/generator.py` — full file (413 lines).
2. `src/orthograph/graph_definition/exceptions.py` — full file (13 lines).
3. `tests/cypher/test_generator.py` — skim for existing relationship tests and the
   injection audit block to understand the test structure.

### Acceptance criteria

- [ ] Calling `generator.create_relationship(data)` or `generator.merge_relationship(data)`
      where the source node type has no `__uid_field__` raises `MissingUidFieldError`.
      The error message names the relationship label and identifies the missing endpoint
      as "source".
- [ ] Same for the target node type — error message identifies it as "target".
- [ ] All existing relationship generator tests pass.
- [ ] The injection audit block (if present in `tests/cypher/test_generator.py`) passes.
- [ ] No `or "uid"` string remains in `generator.py` (verify with `grep`).

### Verification commands

```
pytest tests/cypher/ -x -q
grep -n '"uid"' src/orthograph/cypher/generator.py   # must return nothing
```

---

## T3: *(already done — documentation only)*

> **Status: DONE.** ADR-019 is written at
> `.agentic/decisions/019-uid-field-natural-key-identity.md` and E29 is registered
> in `planning/overview.md`. No source-code work belongs to this task.

---

## Completion criteria for the epic

- [x] T1 acceptance criteria met and `pytest` green.
- [x] T2 acceptance criteria met and `pytest` green.
- [x] T3 done (ADR-019 written, overview updated) ✓
- [x] No regressions: `pytest tests/ -x -q` passes end-to-end after T1 and T2 are
      both applied.

---

## Status: DONE (2026-06-15)

All tasks completed and tested. E29 is archived.
