# ADR-048: Project-Wide Exception Hierarchy and Self-Logging Bridge

> **Status:** Accepted
> **Date:** 2026-06-30
> **Relates to:** PRD Problem Statement ("applications fail silently"), PRD Constraint 13
>   (Orthograph is a library, not an application), ADR-017 (package topology —
>   `diagnostics/` is the dependency-free shared layer), ADR-041 (root capability
>   modules — `orthograph/errors.py` mirrors this pattern), ADR-049 (library logging
>   — the `get_logger` helper `OrthographError.__init__` uses)
> **Implements:** E20.3–E20.8 (Error Hierarchy & Logging sub-epic of E20)

---

## Context

Before this ADR, Orthograph had three disconnected exception roots:

- `CypherError(Exception)` in `cypher/exceptions.py`
- `GraphValidationError(Exception)` in `diagnostics/result.py`
- `ModelDefinitionError(Exception)` in `graph_definition/exceptions.py`
- `MissingDependencyError(ImportError)` in `dependencies.py`

A consumer could not write a single `except` clause to isolate all library errors.
Errors raised by Orthograph were silent by default — no trace appeared unless the
caller logged the exception, which is a "fail silently" pattern the PRD exists to
prevent.

The E17 refactor session (2026-06-10) introduced a Cypher exception hierarchy and
surfaced the absence of a project-wide root. E20 cuts the fix into context-free tasks.

---

## Decision

### D1 — Single root

Every error Orthograph raises derives from `OrthographError`, directly or via a
mid-tier base. A consumer can write:

```python
except OrthographError:
    ...
```

to isolate every library-raised error.

`OrthographError` lives in `src/orthograph/diagnostics/errors.py`, the
dependency-free shared layer (ADR-017). Its public re-export surface is
`src/orthograph/errors.py` (a thin shim per ADR-041).

### D2 — Three mid-tier groups by *kind*, not by subpackage

| Mid-tier class | Meaning | Examples |
|---|---|---|
| `OrthographUsageError` | Caller misused the API, model definitions, or queries | `CypherError`, `ModelDefinitionError` and all subclasses |
| `OrthographValidationError` | A graph or data set failed validation | `GraphValidationError` |
| `OrthographBackendError` | A live-DB, driver, or optional-dependency problem | `MissingDependencyError` |

Groups are by *kind* (the nature of the fault), not by subpackage. This lets a
consumer catch by fault category regardless of where in the library the error
originates.

### D3 — Concrete exception mapping shipped in E20.4–E20.7

| Exception | Previous base | New base | Kind |
|---|---|---|---|
| `CypherError` (and all Cypher subclasses) | `Exception` | `OrthographUsageError` | Usage |
| `ModelDefinitionError` (and all model-definition subclasses) | `Exception` | `OrthographUsageError` | Usage |
| `GraphValidationError` | `Exception` | `OrthographValidationError` | Validation |
| `MissingDependencyError` | `ImportError` | `OrthographBackendError, ImportError` | Backend |

`MissingDependencyError` uses multiple inheritance (`OrthographBackendError, ImportError`)
so that both `except OrthographError` and the historical `except ImportError` continue
to work.

### D4 — Differentiation by subclass and message; no stale cause-lists

Every concrete exception communicates its specifics through its **subclass identity**
and its **message string**. Docstrings do not carry "possible causes" lists — those
rot without tests. The message carries the specifics; the subclass carries the kind.

### D5 — Builtin boundary

The hierarchy covers *library-domain* errors. Genuinely generic type/value misuse
that is honest as a builtin (`TypeError`, `ValueError`) stays as builtins. Only errors
whose meaning is specific to Orthograph's domain migrate to the hierarchy.

### D6 — Self-logging bridge (the trace-without-noise contract)

`OrthographError.__init__` logs itself once on construction via `get_logger`, at a
per-class `log_level`:

| Class | `log_level` | Rationale |
|---|---|---|
| `OrthographError` (default) | `logging.DEBUG` (10) | Trace without noise; most errors are authoring mistakes caught at dev time |
| `OrthographBackendError` | `logging.ERROR` (40) | A live-DB failure is an operational event; ERROR is the right signal |
| `MissingDependencyError` | `logging.DEBUG` (10) | Expected during backend probing; ERROR would be noisy on every availability check |

**Why log on construct, not on raise?** The raise site is not always the right place to
log — a handler may decide the error is noise (e.g. a probe that expects `MissingDependencyError`).
Logging at ERROR unconditionally on construct would produce noise every time the error
is caught and handled. Logging at DEBUG by default gives a trace for debugging without
demanding the caller suppress it in production.

**Why not rely on the caller?** The PRD problem statement is "applications fail
silently." If the library never logs, a misconfigured application will swallow the
exception with no trace. The per-class level lets the library provide a sensible default
while the application retains full control via the `orthograph.*` logger tree (ADR-049).

The catcher — not the raiser — decides whether a handled error is ultimately noise.

### D7 — Root shim `orthograph/errors.py` (ADR-041 mirror)

`src/orthograph/errors.py` is a thin re-export shim. No logic lives there. Its purpose
is to let consumers write:

```python
from orthograph.errors import OrthographError, CypherSyntaxError
```

without importing from subpackage internals. The shim exposes every class in the
hierarchy by name in its `__all__`. It is registered in `orthograph/__init__.py`
alongside the other capability modules (ADR-041).

---

## Consequences

**Positive**
- `except OrthographError` isolates all library errors in one clause.
- Every raised error leaves a trace in the `orthograph.*` log tree by default.
- Fault kind is machine-inspectable (`issubclass(exc_type, OrthographBackendError)`).
- `MissingDependencyError` remains an `ImportError` — existing caller code unchanged.
- The public surface is stable: `from orthograph.errors import ...` is the import path.

**Negative / costs**
- `GraphValidationError.__init__` now calls `OrthographValidationError.__init__` via
  `super().__init__`, which triggers the self-logging bridge. This is the intended
  behaviour but callers who construct `GraphValidationError` in test assertions will
  see DEBUG log records (suppressible via `caplog` or `logging.disable`).
- Multiple inheritance on `MissingDependencyError` requires care in `__init__` MRO
  traversal; the current implementation delegates to `OrthographBackendError.__init__`
  first, which is correct.

**Neutral**
- Bare `raise TypeError/ValueError` sites across `src/` are not migrated by this ADR.
  Only *library-domain* errors migrate (D5). A follow-up E20.12 task can audit those
  if desired.

---

## Alternatives considered

1. **No root / bare builtins everywhere.** Rejected: cannot isolate library errors; a
   consumer catches `ValueError` from half the Python ecosystem, not just Orthograph.

2. **Two-level shape: root → subpackage-base → concrete.** Rejected: organising by
   *subpackage* leaks internal structure into the public exception API. A consumer
   should not need to know that a validation failure came from `cypher/` vs
   `graph_definition/`; they should know it was a *usage* error. Kind-based mid-tiers
   are the stable interface.

3. **Unconditional ERROR-on-construct.** Rejected: every `MissingDependencyError` raised
   during availability probing would fire an ERROR log, making probing noisy. An
   authoring mistake caught at unit-test time would always log at ERROR even though no
   operational failure occurred.

4. **Log only at the raise site (explicit `logger.error(...)` before each `raise`)**
   Rejected: requires every raise site to be updated; callers that catch-and-suppress
   still see an ERROR they did not ask for; the per-class `log_level` approach gives
   the same control with zero per-site boilerplate.
